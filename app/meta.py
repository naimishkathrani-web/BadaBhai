import asyncio
import json
import os
import logging

import httpx
import websockets


def key():
    value = os.getenv('MODEL_API_KEY', '').strip()
    if not value:
        raise RuntimeError('Add MODEL_API_KEY to .env and restart the app')
    return value


def system_prompt(language):
    system = (
        'You are BadaBhai, a helpful voice AI on an ordinary phone call for the Meta Global AI Developer Hackathon. '
        f'You use Meta {os.getenv("META_CHAT_MODEL", "muse-spark-1.3")} for answers, Meta Muse Voice Transcribe for recognition, and Meta MMS for speech. '
        'You do not use Google models. State this plainly if asked about your model provider. '
        f'Reply only in {"Hindi in Devanagari" if language == "hi" else "clear Indian English"}. '
        'Use simple spoken language for a phone call. Start with a direct helpful answer. '
        'Use 2–3 short sentences (about 40–55 words). No markdown, no lists, no stage directions. '
        'For everyday knowledge (science, maths, how-to, definitions, general public schemes overview), give a clear useful answer first. '
        'Do NOT say "I am not sure", "I don\'t know", or "I cannot be certain" for ordinary general-knowledge questions you can explain. '
        'If a detail may vary by place or year, still give the best general guidance, then optionally name one official place to confirm (helpline, government website, or local office). '
        'Ask at most one short clarifying question only when the caller\'s goal is ambiguous. '
        'Never invent live personal account data, never claim to browse the live web, and never invent phone numbers you do not know. '
        'You cannot place calls, access accounts, or perform transactions. '
        'Focus on practical everyday questions, clear explanations, brainstorming, digital literacy, and general public-service guidance. '
        'For personal eligibility, application status, medical diagnosis, or legal advice specific to one person, say you give general information only and direct them to the official source. '
        'Repeat key information when asked. '
        'Do not request Aadhaar numbers, one-time passwords, bank account numbers, or PINs. '
        'Do not collect sensitive personal details or claim access to a government, bank, or other personal account. '
        'Do not provide medical or mental health diagnosis/treatment, political persuasion, war-related assistance, personality analysis, employment screening, or sports coaching. '
        'Briefly decline those requests and offer an in-scope topic. '
        'For urgent danger tell the caller to seek local emergency assistance.'
    )
    return system


async def answer(messages, language):
    async with httpx.AsyncClient(timeout=35) as client:
        response = await client.post(
            os.getenv('META_BASE_URL', 'https://api.meta.ai/v1').rstrip('/') + '/chat/completions',
            headers={'Authorization': 'Bearer ' + key()},
            json={'model': os.getenv('META_CHAT_MODEL', 'muse-spark-1.3'),
                  'messages': [{'role': 'system', 'content': system_prompt(language)}] + messages[-12:],
                  'reasoning_effort': os.getenv('META_REASONING_EFFORT', 'medium'),
                  'max_tokens': int(os.getenv('META_MAX_TOKENS', '1500'))},
        )
        response.raise_for_status()
        text = response.json()['choices'][0]['message']['content']
        if not isinstance(text, str) or not text.strip():
            logging.getLogger('badabhai').warning('Meta returned an empty answer: finish_reason=%s', response.json()['choices'][0].get('finish_reason'))
            raise RuntimeError('Meta returned no answer text')
        return text.strip()


async def stream_sentences(messages, language):
    """Yield speakable sentences as Meta generates them, without logging content."""
    from app.streaming import SentenceBuffer
    buffer = SentenceBuffer()
    emitted = False
    payload = {'model': os.getenv('META_CHAT_MODEL', 'muse-spark-1.3'),
               'messages': [{'role': 'system', 'content': system_prompt(language)}] + messages[-12:],
               'reasoning_effort': os.getenv('META_REASONING_EFFORT', 'medium'),
               'max_tokens': int(os.getenv('META_MAX_TOKENS', '1500')), 'stream': True}
    async with httpx.AsyncClient(timeout=httpx.Timeout(35, connect=10)) as client:
        async with client.stream('POST', os.getenv('META_BASE_URL', 'https://api.meta.ai/v1').rstrip('/') + '/chat/completions',
                                 headers={'Authorization': 'Bearer ' + key()}, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    break
                event = json.loads(data)
                if event.get('error'):
                    raise RuntimeError('Meta streaming request failed')
                for choice in event.get('choices', []):
                    text = choice.get('delta', {}).get('content') or ''
                    if not isinstance(text, str):
                        continue
                    for sentence in buffer.feed(text):
                        emitted = True
                        yield sentence
    for sentence in buffer.finish():
        emitted = True
        yield sentence
    if not emitted:
        raise RuntimeError('Meta returned no answer text')


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
