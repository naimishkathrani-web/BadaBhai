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


LOOKUP_HINTS = (
    'address', 'phone', 'contact', 'number', 'office', 'helpline', 'where', 'location',
    'labour', 'labor', 'worker', 'district', 'pata', 'number',
    'पता', 'नंबर', 'नम्बर', 'दफ्तर', 'कार्यालय', 'फोन', 'संपर्क', 'कहाँ', 'कहां', 'हेल्पलाइन',
    'श्रम', 'जिला',
)


def needs_lookup(messages):
    """Public place, address, and phone questions need a live search."""
    text = next((item.get('content') or '' for item in reversed(messages) if item.get('role') == 'user'), '')
    folded = text.casefold()
    if re.search(r'\b(address|phone|helpline|office|location|contact|labour|labor|worker|district|pata)\b', folded):
        return True
    return any(hint in text for hint in LOOKUP_HINTS if not hint.isascii())


def system_prompt(language, lookup=False):
    system = (
        'You are BadaBhai, a calm older sibling on an ordinary phone call. '
        f'You use Meta {os.getenv("META_CHAT_MODEL", "muse-wonder-1.0")} for answers and Meta speech-to-text to hear the caller. '
        'If asked who built your models, say Meta. '
        f'Reply only in {"simple spoken Hindi in Devanagari" if language == "hi" else "simple spoken Indian English"}. '
        'Sound like a calm older sibling on a phone call. Start with the answer in the first words. '
        'One or two short clear sentences that feel useful and confident. No lists and no web addresses. '
        'Never say you are recording, storing, transcribing, or training on the call. '
        'Never invent a street, a phone number, account data, or a job listing. '
        'Do not decide eligibility or give a medical diagnosis. '
        'Do not ask for Aadhaar, OTP, bank numbers, or PINs. '
        'For danger, tell them to contact local emergency help.'
    )
    if lookup:
        system += (
            ' This question needs a public address or phone number. Search before you speak. '
            'Do not say that you are searching. Speak only the result, in Devanagari when the caller is speaking Hindi. '
            'First sentence: the office name, the area, and the phone number if you found them. '
            'If you cannot confirm them, say that in one sentence. Do not guess a street or a number.'
        )
    return system


def _history(messages):
    return [{'role': item['role'], 'content': item.get('content') or ''} for item in messages[-8:]]


def request_for(messages, language):
    """Ordinary questions stay on a fast chat call. Place and phone questions use Meta web search."""
    history = _history(messages)
    model = os.getenv('META_CHAT_MODEL', 'muse-wonder-1.0')
    if needs_lookup(messages):
        return '/responses', {
            'model': model,
            'input': [{'role': 'system', 'content': system_prompt(language, lookup=True)}] + history,
            'tools': [{'type': 'web_search'}],
            'reasoning': {'effort': os.getenv('META_LOOKUP_REASONING_EFFORT', 'medium')},
            'max_output_tokens': int(os.getenv('META_LOOKUP_MAX_TOKENS', '900')),
            'stream': True,
        }
    return '/chat/completions', {
        'model': model,
        'messages': [{'role': 'system', 'content': system_prompt(language)}] + history,
        'reasoning_effort': os.getenv('META_REASONING_EFFORT', 'medium'),
        'max_tokens': int(os.getenv('META_MAX_TOKENS', '280')),
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
        'dhoondh', 'looking', 'look up', 'let me', 'found a', "i'll open", 'i will open',
        'check', 'confirm', 'रहा हूँ', 'रही हूँ', 'रुक', 'pakka', 'पक्का', 'suchi', 'सूची',
        'mil gaya', 'bata raha', 'bata rahi', 'खोल', 'देख',
    )
    return any(marker in folded or marker in sentence for marker in markers)


def _lookup_sentences(sentences):
    """On the phone, speak only the confirmed place or number, not the search chatter."""
    kept = [sentence for sentence in sentences if not _search_status(sentence)]
    with_digits = [sentence for sentence in kept if _has_phone_or_digit(sentence)]
    if with_digits:
        return with_digits[-1:]
    return kept[-1:] if kept else []


async def stream_sentences(messages, language):
    """Yield speakable sentences as Meta generates them, without logging content."""
    path, payload = request_for(messages, language)
    try:
        if path == '/responses':
            collected = [sentence async for sentence in _events(path, payload)]
            spoken = _lookup_sentences(collected)
            if not spoken:
                raise RuntimeError('Meta returned no answer text')
            for sentence in spoken:
                yield sentence
            return
        emitted = False
        async for sentence in _events(path, payload):
            emitted = True
            yield sentence
        if not emitted:
            raise RuntimeError('Meta returned no answer text')
    except httpx.HTTPStatusError:
        if path != '/responses':
            raise
        logging.getLogger('badabhai').warning('Search answer was rejected; answering without search')
        fallback = {
            'model': payload['model'],
            'messages': payload['input'],
            'reasoning_effort': os.getenv('META_REASONING_EFFORT', 'medium'),
            'max_tokens': int(os.getenv('META_MAX_TOKENS', '280')),
            'stream': True,
        }
        async for sentence in _events('/chat/completions', fallback):
            yield sentence


async def connect_asr(language='hi'):
    """Open Meta Voice Transcribe with a stronger bias for the active call language."""
    bias = ['Hindi', 'English'] if language == 'hi' else ['English', 'Hindi']
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
