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
        'You are BadaBhai, a calm older sibling on an ordinary phone call. '
        f'You use Meta {os.getenv("META_CHAT_MODEL", "muse-spark-1.3")} for answers and Meta speech tools to hear and speak. '
        'If asked who built your models, say Meta. '
        f'Reply only in {"simple spoken Hindi in Devanagari" if language == "hi" else "simple spoken Indian English"}. '
        'Sound like a normal conversation. One or two short sentences, about 25 words. No lists, no labels, no disclaimers. '
        'Answer the question first. Add one official place to check only when the answer depends on a local office. '
        'Never say you are recording, storing, transcribing, or training on the call. '
        'Do not say you are unsure about ordinary facts you can explain. '
        'Ask one short question only when you cannot guide without it. '
        'Never invent account data, phone numbers, or job listings. '
        'Do not decide eligibility or give a medical diagnosis. '
        'Do not ask for Aadhaar, OTP, bank numbers, or PINs. '
        'For danger, tell them to contact local emergency help.'
    )
    return system


async def answer(messages, language):
    async with httpx.AsyncClient(timeout=35) as client:
        response = await client.post(
            os.getenv('META_BASE_URL', 'https://api.meta.ai/v1').rstrip('/') + '/chat/completions',
            headers={'Authorization': 'Bearer ' + key()},
            json={'model': os.getenv('META_CHAT_MODEL', 'muse-spark-1.3'),
                  'messages': [{'role': 'system', 'content': system_prompt(language)}] + messages[-12:],
                  'reasoning_effort': os.getenv('META_REASONING_EFFORT', 'low'),
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
               'reasoning_effort': os.getenv('META_REASONING_EFFORT', 'low'),
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
