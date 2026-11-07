import asyncio
import json
import os
import logging
import re

import httpx
import websockets


def key():
    value = os.getenv('MODEL_API_KEY', '').strip()
    if not value:
        raise RuntimeError('Add MODEL_API_KEY to .env and restart the app')
    return value


# Live / changing facts → Meta web search. Pure knowledge questions stay on the fast chat path.
# Avoid bare "phone" so "feature phone" stays on the fast path.
LIVE_FACT_RE = re.compile(
    r'\b(address|helpline|office|location|contact number|phone number|phone no|mobile number|'
    r'labour|labor|worker|district|pata|'
    r'train|railway|irctc|hotel|resort|tent|booking|itinerary|ticket|fare|price|cost|'
    r'flight|bus|tourism|utsav|temple|trip|travel|package|weather|temperature|forecast|mausam|'
    r'gold|silver|petrol|diesel|rate|score|match|news|timing|timings|schedule|'
    r'availability|fees|charges|today|tonight|tomorrow|current|latest|aaj|kal)\b',
    re.I,
)

LOOKUP_HINTS = (
    'पता', 'नंबर', 'नम्बर', 'दफ्तर', 'कार्यालय', 'फोन', 'संपर्क', 'कहाँ', 'कहां', 'हेल्पलाइन',
    'श्रम', 'जिला', 'ट्रेन', 'रेल', 'होटल', 'रिसॉर्ट', 'टेंट', 'बुकिंग', 'किराया',
    'दाम', 'खर्च', 'यात्रा', 'मंदिर', 'उत्सव', 'टिकट', 'मौसम', 'तापमान', 'सोना', 'चांदी',
    'पेट्रोल', 'डीज़ल', 'आज', 'कल', 'खुला', 'बंद', 'समय', 'किराया', 'रेट', 'स्कॉर',
)

TRAVEL_HINTS = (
    'train', 'railway', 'irctc', 'hotel', 'resort', 'tent', 'booking', 'itinerary',
    'ticket', 'fare', 'price', 'cost', 'flight', 'bus', 'tourism', 'utsav', 'temple',
    'trip', 'travel', 'package',
    'ट्रेन', 'रेल', 'होटल', 'रिसॉर्ट', 'टेंट', 'बुकिंग', 'दाम', 'खर्च', 'यात्रा', 'मंदिर',
    'उत्सव', 'टिकट', 'किराया', 'घूम',
)

HINDI_ROMAN = re.compile(
    r'\b(kya|kyun|kyu|hai|hain|hoon|hun|haan|nahi|nahin|batao|bataiye|samjhao|samjhaao|'
    r'mujhe|mera|meri|mere|aap|aapka|kaise|kaisa|kahan|kidhar|chahiye|krdo|karo|'
    r'namaste|namaskar|dhanyavad|shukriya|accha|theek|thik|bhai|didi|'
    r'prakash|sanshlen|sarkari|yojana|davakhana|aspataal|aspataal)\b',
    re.I,
)

TRAILING_FLUFF = re.compile(
    r'(?i)^(would you like|do you want|anything else|let me know|feel free|'
    r'if you (want|need)|i can also|shall i|press\b|keypad|button|'
    r'और कुछ|कुछ और|बताइए|बताओ तो|क्या मैं|अगर आप|मैं और|'
    r'hope (that )?helps|is there anything)\b'
)


def detect_language(text, default='hi'):
    """Pick Hindi or English from what the caller said, including romanized Hindi."""
    text = (text or '').strip()
    if not text:
        return default
    if re.search(r'[\u0900-\u097F]', text):
        return 'hi'
    letters = re.findall(r'[A-Za-z\u0900-\u097F]', text)
    if not letters:
        return default
    if HINDI_ROMAN.search(text):
        return 'hi'
    # Mostly ASCII Latin without Hindi cues → English.
    latin = sum(1 for ch in letters if 'A' <= ch <= 'Z' or 'a' <= ch <= 'z')
    if latin / max(1, len(letters)) >= 0.8:
        return 'en'
    return default


def _latest_user_text(messages):
    return next((item.get('content') or '' for item in reversed(messages) if item.get('role') == 'user'), '')


def needs_travel_help(messages):
    text = _latest_user_text(messages)
    folded = text.casefold()
    if re.search(
        r'\b(train|railway|irctc|hotel|resort|tent|booking|itinerary|ticket|fare|price|cost|'
        r'flight|bus|tourism|utsav|temple|trip|travel|package)\b',
        folded,
    ):
        return True
    return any(hint in text for hint in TRAVEL_HINTS if not hint.isascii())


def needs_lookup(messages):
    """Current public facts need a fresh search; textbook knowledge stays on the fast path."""
    text = _latest_user_text(messages)
    if LIVE_FACT_RE.search(text):
        return True
    return any(hint in text for hint in LOOKUP_HINTS)


def system_prompt(language, lookup=False, travel=False):
    spoken = (
        'simple spoken Hindi in Devanagari script'
        if language == 'hi'
        else 'simple spoken Indian English'
    )
    system = (
        'You are BadaBhai, a calm older sibling on an ordinary phone call. '
        f'You use Meta {os.getenv("META_CHAT_MODEL", "muse-wonder-1.0")} for answers and Meta speech-to-text to hear the caller. '
        'If asked who built your models, say Meta. '
        f'Reply only in {spoken}. '
        'If the caller mixed Hindi and English, still stay in that reply language. '
        'Be useful for many everyday situations: explaining, planning, comparing choices, and clear next steps. '
        'Sound like a normal conversation. Start with the answer in the first words. '
        'Use one short sentence, or two only when needed. No lists and no web addresses. '
        'Do not ask a follow-up question. Do not offer more help. '
        'Do not mention keypad buttons, menus, recording, or apps. '
        'Never say you are recording, storing, transcribing, or training on the call. '
        'Never invent a street, a phone number, account data, live fare, or a job listing. '
        'Do not decide eligibility or give a medical diagnosis. '
        'Do not ask for Aadhaar, OTP, bank numbers, or PINs. '
        'For danger, tell them to contact local emergency help. '
        'If you already said you lack a detail, do not repeat that sentence. Give a new concrete next step instead.'
    )
    if lookup and travel:
        system += (
            ' This is a travel planning question. Search before you speak. '
            'Do not say that you are searching. Answer only what they asked first. '
            'If they asked ticket/fare: give the best confirmed train or bus with class-wise fare range if found. '
            'If they asked hotel/tent/resort: give a named stay area or property type with a price range if found. '
            'If they asked for an itinerary: sentence one is day-1 travel, sentence two is stay or day-2 place with cost. '
            'Always say date-sensitive fares must be rechecked on IRCTC or the official booking page. '
            'Do not invent exact fares, train numbers, or hotel names you did not find. '
            'Do not refuse with the same vague line twice; give the best found numbers or one clear next step.'
        )
    elif lookup:
        system += (
            ' This question needs a current public fact. Search before you speak. '
            'Do not say that you are searching. Speak only confirmed facts, in Devanagari when the reply language is Hindi. '
            'Prefer names, numbers, timings, rates, or places you actually found. '
            'If you cannot confirm them, say that in one sentence and give one official place to check. '
            'Do not invent a street, phone number, fare, or rate.'
        )
    return system


def _history(messages):
    return [{'role': item['role'], 'content': item.get('content') or ''} for item in messages[-6:]]


def request_for(messages, language):
    """Ordinary questions stay on a fast chat call. Live facts use Meta web search."""
    history = _history(messages)
    model = os.getenv('META_CHAT_MODEL', 'muse-wonder-1.0')
    travel = needs_travel_help(messages)
    # Low reasoning keeps phone turns snappy; token headroom still covers short spoken answers.
    if needs_lookup(messages):
        return '/responses', {
            'model': model,
            'input': [{'role': 'system', 'content': system_prompt(language, lookup=True, travel=travel)}] + history,
            'tools': [{'type': 'web_search'}],
            'reasoning': {'effort': os.getenv('META_LOOKUP_REASONING_EFFORT', 'low')},
            'max_output_tokens': int(os.getenv('META_LOOKUP_MAX_TOKENS', '1200')),
            'stream': True,
        }
    return '/chat/completions', {
        'model': model,
        'messages': [{'role': 'system', 'content': system_prompt(language)}] + history,
        'reasoning_effort': os.getenv('META_REASONING_EFFORT', 'low'),
        'max_tokens': int(os.getenv('META_MAX_TOKENS', '900')),
        'stream': True,
    }


async def answer(messages, language):
    parts = [sentence async for sentence in stream_sentences(messages, language)]
    return ' '.join(parts).strip()


async def _events(path, payload):
    from app.streaming import SentenceBuffer
    buffer = SentenceBuffer()
    emitted = False
    async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10)) as client:
        async with client.stream(
            'POST', os.getenv('META_BASE_URL', 'https://api.meta.ai/v1').rstrip('/') + path,
            headers={'Authorization': 'Bearer ' + key(), 'Accept': 'text/event-stream'},
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    break
                event = json.loads(data)
                if event.get('type') in ('response.failed', 'error') or event.get('error'):
                    raise RuntimeError('Meta streaming request failed')
                pieces = []
                if event.get('type') == 'response.output_text.delta':
                    pieces.append(event.get('delta') or '')
                for choice in event.get('choices', []):
                    content = choice.get('delta', {}).get('content') or ''
                    if isinstance(content, str):
                        pieces.append(content)
                for piece in pieces:
                    for sentence in buffer.feed(piece):
                        emitted = True
                        yield sentence
    for sentence in buffer.finish():
        emitted = True
        yield sentence
    if not emitted:
        raise RuntimeError('Meta returned no answer text')


def _has_phone_or_digit(sentence):
    return any(ch.isdigit() or '०' <= ch <= '९' for ch in sentence)


def _search_status(sentence):
    """Drop the model's own 'still searching' lines. The phone already says it is checking."""
    if _has_phone_or_digit(sentence):
        return False
    folded = sentence.casefold()
    markers = (
        'dhoondh', 'looking', 'look up', 'let me search', 'found a', "i'll open", 'i will open',
        'still searching', 'got it', "i'll confirm", 'i will confirm', 'before answering',
        'रहा हूँ', 'रही हूँ', 'ढूंढ', 'ढूँढ', 'suchi', 'सूची',
        'mil gaya', 'bata raha', 'bata rahi', 'खोज', 'देखकर बताता', 'देख कर बताता',
        'पक्का करके बताता', 'मिलें नंबर अलग', 'मिले नंबर अलग',
    )
    return any(marker in folded or marker in sentence for marker in markers)


def _looks_factual(sentence):
    folded = sentence.casefold()
    if _has_phone_or_digit(sentence):
        return True
    cues = (
        'train', 'express', 'special', 'tent', 'hotel', 'resort', 'rupee', 'rs', 'km',
        'temple', 'bhuj', 'rajkot', 'irctc', 'night', 'morning', 'office', 'weather',
        'degree', 'celsius', 'open', 'closed',
        'ट्रेन', 'स्पेशल', 'एक्सप्रेस', 'टेंट', 'होटल', 'रिसॉर्ट', 'रुपये', 'किलो',
        'मंदिर', 'भुज', 'राजकोट', 'हज़ार', 'हजार', 'किराया', 'दाम', 'कार्यालय', 'मौसम',
        'डिग्री', 'खुला', 'बंद',
    )
    return any(cue in folded or cue in sentence for cue in cues)


def _lookup_sentences(sentences):
    """On the phone, speak confirmed facts, not search chatter."""
    kept = [sentence for sentence in sentences if not _search_status(sentence)]
    factual = [sentence for sentence in kept if _looks_factual(sentence)]
    chosen = factual or kept
    # Travel answers often need two short facts: route + stay/cost.
    return chosen[:2]


def _is_fluff(sentence):
    text = (sentence or '').strip()
    if not text:
        return True
    return bool(TRAILING_FLUFF.search(text))


def _is_fragment(sentence):
    """Drop orphan tails that start mid-thought after a bad split or truncated stream."""
    text = (sentence or '').strip()
    if not text:
        return True
    if re.search(r'[\u0900-\u097F]', text):
        return False
    # English continuations after a bad split almost always start lowercase.
    return text[0].islower()


def spoken_sentences(sentences, lookup=False):
    """Keep the useful spoken lines and drop trailing helper/chatter sentences."""
    cleaned = [
        sentence.strip() for sentence in sentences
        if sentence and sentence.strip() and not _is_fluff(sentence) and not _is_fragment(sentence)
    ]
    if lookup:
        return _lookup_sentences(cleaned)
    # Phone calls should stay short even if the model adds a polite closer.
    return cleaned[:2]


async def _chat_fallback(messages, language, model):
    travel = needs_travel_help(messages)
    fallback = {
        'model': model,
        'messages': [{'role': 'system', 'content': system_prompt(language, travel=travel)}] + _history(messages),
        'reasoning_effort': os.getenv('META_REASONING_EFFORT', 'low'),
        'max_tokens': int(os.getenv('META_MAX_TOKENS', '900')),
        'stream': True,
    }
    emitted = []
    async for sentence in _events('/chat/completions', fallback):
        if _is_fluff(sentence) or _is_fragment(sentence):
            continue
        emitted.append(sentence)
        yield sentence
        if len(emitted) >= 2:
            return
    if not emitted:
        raise RuntimeError('Meta returned no answer text')


async def stream_sentences(messages, language):
    """Yield speakable sentences as Meta generates them, without logging content."""
    path, payload = request_for(messages, language)
    lookup = path == '/responses'
    try:
        if lookup:
            collected = [sentence async for sentence in _events(path, payload)]
            spoken = spoken_sentences(collected, lookup=True)
            if spoken:
                for sentence in spoken:
                    yield sentence
                return
            logging.getLogger('badabhai').warning('Search answer had no speakable lines; falling back')
            async for sentence in _chat_fallback(messages, language, payload['model']):
                yield sentence
            return
        emitted = []
        async for sentence in _events(path, payload):
            if _is_fluff(sentence) or _is_fragment(sentence):
                continue
            emitted.append(sentence)
            yield sentence
            if len(emitted) >= 2:
                return
        if not emitted:
            raise RuntimeError('Meta returned no answer text')
    except httpx.HTTPStatusError:
        if path != '/responses':
            raise
        logging.getLogger('badabhai').warning('Search answer was rejected; answering without search')
        async for sentence in _chat_fallback(messages, language, payload['model']):
            yield sentence


async def connect_asr(language='hi'):
    """Open Meta Voice Transcribe with Hindi+English bias so either language is heard."""
    # Keep both languages available so auto-detect can switch without a keypad.
    bias = ['Hindi', 'English']
    socket = await websockets.connect(
        os.getenv('META_ASR_URL', 'wss://api.meta.ai/v1/asr/realtime'),
        open_timeout=20, max_size=2**20,
    )
    try:
        await socket.send(json.dumps({
            'authorization': {'accessToken': 'Bearer ' + key()},
            'model': os.getenv('META_ASR_MODEL', 'muse-voice-transcribe-1.0'),
            'audioEncoding': 'PCM_24KHZ', 'mode': 'ENDPOINTING',
            'languageBias': bias,
            'partialMode': 'CUMULATIVE', 'emitAudioProgress': False,
        }))
        handshake = json.loads(await asyncio.wait_for(socket.recv(), 20))
        if 'sessionId' not in handshake:
            raise RuntimeError('Meta speech handshake failed; check model access in your dashboard')
        return socket
    except BaseException:
        await socket.close()
        raise
