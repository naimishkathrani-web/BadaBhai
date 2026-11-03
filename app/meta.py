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


async def answer(messages, language):
    system = (
        'You are BadaBhai, a helpful AI reached by ordinary telephone. '
        f'You use Meta {os.getenv("META_CHAT_MODEL", "muse-spark-1.3")} for answers, Meta Muse Voice Transcribe for recognition, and Meta MMS for speech. '
        'You do not use Google models. State this plainly if asked about your model provider. '
        f'Reply only in {"Hindi in Devanagari" if language == "hi" else "English"}. '
        'Use simple spoken language, one or two brief sentences, at most 45 words, no markdown. '
        'Ask one clarifying question if needed. Never invent live facts or claim to browse. '
        'Explain uncertainty. You cannot place calls, access accounts or perform transactions. '
        'Focus on practical everyday information, digital literacy, and navigating public services. '
        'Do not provide medical or mental health advice, diagnosis, treatment, nutrition coaching, '
        'political persuasion, war-related assistance, personality analysis, employment screening, '
        'or sports coaching. Briefly decline those requests and offer an in-scope topic. '
        'For urgent danger tell the caller to seek local emergency assistance. '
        'Do not present legal or financial guesses as professional advice.'
    )
    async with httpx.AsyncClient(timeout=35) as client:
        response = await client.post(
            os.getenv('META_BASE_URL', 'https://api.meta.ai/v1').rstrip('/') + '/chat/completions',
            headers={'Authorization': 'Bearer ' + key()},
            json={'model': os.getenv('META_CHAT_MODEL', 'muse-spark-1.3'),
                  'messages': [{'role': 'system', 'content': system}] + messages[-12:],
                  'reasoning_effort': os.getenv('META_REASONING_EFFORT', 'low'),
                  'max_tokens': int(os.getenv('META_MAX_TOKENS', '1500'))},
        )
        response.raise_for_status()
        text = response.json()['choices'][0]['message']['content']
        if not isinstance(text, str) or not text.strip():
            logging.getLogger('badabhai').warning('Meta returned an empty answer: finish_reason=%s', response.json()['choices'][0].get('finish_reason'))
            raise RuntimeError('Meta returned no answer text')
        return text.strip()


async def connect_asr():
    socket = await websockets.connect(
        os.getenv('META_ASR_URL', 'wss://api.meta.ai/v1/asr/realtime'),
        open_timeout=20, max_size=2**20,
    )
    try:
        await socket.send(json.dumps({
            'authorization': {'accessToken': 'Bearer ' + key()},
            'model': os.getenv('META_ASR_MODEL', 'muse-voice-transcribe-1.0'),
            'audioEncoding': 'PCM_24KHZ', 'mode': 'ENDPOINTING',
            'languageBias': ['Hindi', 'English'],
            'partialMode': 'CUMULATIVE', 'emitAudioProgress': False,
        }))
        handshake = json.loads(await asyncio.wait_for(socket.recv(), 20))
        if 'sessionId' not in handshake:
            raise RuntimeError('Meta speech handshake failed; check model access in your dashboard')
        return socket
    except BaseException:
        await socket.close()
        raise
