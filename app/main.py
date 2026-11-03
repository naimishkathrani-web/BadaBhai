import asyncio
import base64
import contextlib
import io
import json
import logging
import os
import secrets
import wave
import time
from websockets.exceptions import ConnectionClosed
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
from app import meta, voice
from app.audio import Resampler, chunks

log = logging.getLogger('badabhai')
WELCOME_HI = 'नमस्ते। मैं बड़ा भाई, आपका ए आई सहायक हूँ। हिंदी के लिए एक दबाएं।'
WELCOME_EN = 'For English, press two. You can also start speaking.'
RETRY_HI = 'माफ़ कीजिए, जवाब मिलने में समस्या हुई। कृपया अपना सवाल फिर से पूछिए।'
RETRY_EN = 'Sorry, I could not get an answer. Please ask your question again.'


@asynccontextmanager
async def lifespan(app):
    if os.getenv('PREWARM_VOICES', '0') == '1' and os.getenv('CALL_MODE') != 'echo':
        log.warning('Preparing both voices and welcome audio before accepting calls')
        for language, text in [('hi', WELCOME_HI), ('en', WELCOME_EN), ('hi', RETRY_HI), ('en', RETRY_EN)]:
            for rate in (8000, 16000, 24000):
                await asyncio.to_thread(voice.synthesize, text, language, rate)
        log.warning('Voice startup complete: ready to accept calls')
    yield


app = FastAPI(title='BadaBhai', lifespan=lifespan)
active_calls = 0


def authorized(value):
    token = os.getenv('APP_TOKEN', '')
    return bool(token and value and secrets.compare_digest(value, token))


@app.get('/', response_class=HTMLResponse)
def home():
    return Path(__file__).with_name('index.html').read_text(encoding='utf-8')


@app.get('/health')
def health():
    return {'status': 'running', 'meta_key_configured': bool(os.getenv('MODEL_API_KEY')),
            'call_mode': os.getenv('CALL_MODE', 'meta'),
            'note': 'Configuration only; live model access and local TTS are not checked.'}


class Chat(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: str = Field(default='hi', pattern='^(hi|en)$')


@app.post('/api/chat')
async def chat(body: Chat, x_app_token: str = Header(default='')):
    if not authorized(x_app_token):
        raise HTTPException(401, 'Invalid app token')
    try:
        return {'answer': await meta.answer([{'role': 'user', 'content': body.text}], body.language)}
    except Exception as exc:
        log.warning('Chat failed: %s', type(exc).__name__)
        raise HTTPException(502, 'Meta request failed. Check key, model access and server console.') from None


@app.post('/api/speech')
async def speech(body: Chat, x_app_token: str = Header(default='')):
    if not authorized(x_app_token):
        raise HTTPException(401, 'Invalid app token')
    try:
        pcm = await asyncio.to_thread(voice.synthesize, body.text, body.language, 16000)
    except Exception as exc:
        log.warning('Local voice failed: %s', type(exc).__name__)
        raise HTTPException(503, 'Local MMS voice unavailable. Install voice dependencies and warm up models.') from None
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(pcm)
    return Response(output.getvalue(), media_type='audio/wav')


class Call:
    def __init__(self, ws):
        self.ws, self.asr = ws, None
        self.sid, self.rate, self.language = None, 8000, 'hi'
        self.history = []
        self.queue = asyncio.Queue(maxsize=3)
        self.playback = asyncio.Event()
        self.playback.set()
        self.mark = None
        self.busy = False
        self.media_seen = False
        self.interrupted = asyncio.Event()
        self.turn_task = None

    async def send(self, event, **kwargs):
        await self.ws.send_json({'event': event, 'stream_sid': self.sid, **kwargs})

    async def say(self, text, language, pcm=None):
        was_busy = self.busy
        self.busy = True
        try:
            started = time.perf_counter()
            if pcm is None:
                pcm = await asyncio.to_thread(voice.synthesize, text, language, self.rate)
            log.warning('Speech synthesis completed in %.2fs', time.perf_counter() - started)
            log.warning('Sending spoken audio: language=%s duration=%.1fs', language, len(pcm)/(self.rate*2))
            self.playback.clear()
            self.mark = secrets.token_hex(8)
            for chunk in chunks(pcm, self.rate):
                if self.interrupted.is_set():
                    return
                await self.send('media', media={'payload': base64.b64encode(chunk).decode()})
                await asyncio.sleep(0.2)
            await self.send('mark', mark={'name': self.mark})
            # Exotel confirms that the caller has heard all queued audio.
            await asyncio.wait_for(self.playback.wait(), 20)
        finally:
            self.busy = was_busy

    async def receive(self):
        converter = None
        while True:
            event = await self.ws.receive_json()
            kind = event.get('event')
            if kind != 'media':
                log.warning('Call event: %s', kind if kind in ('connected', 'start', 'mark', 'dtmf', 'stop') else 'unknown')
            if kind == 'start':
                if self.sid:
                    raise ValueError('Duplicate start')
                start = event['start']
                self.sid = start.get('stream_sid') or event.get('stream_sid')
                self.rate = int(start.get('media_format', {}).get('sample_rate', 8000))
                if not self.sid or self.rate not in (8000, 16000, 24000):
                    raise ValueError('Unsupported audio format')
                converter = Resampler(self.rate, 24000)
                log.warning('Call audio ready: sample_rate=%d', self.rate)
                if os.getenv('CALL_MODE') != 'echo':
                    self.asr = await meta.connect_asr()
                    self.queue.put_nowait(('welcome', ''))
            elif kind == 'media' and self.sid:
                if not self.media_seen:
                    self.media_seen = True
                    log.warning('First incoming audio packet received')
                pcm = base64.b64decode(event['media']['payload'], validate=True)
                if os.getenv('CALL_MODE') == 'echo':
                    await self.send('media', media={'payload': base64.b64encode(pcm).decode()})
                elif self.asr:
                    # Half-duplex MVP: send silence while replying to avoid echo feedback.
                    try:
                        await self.asr.send(converter.convert(bytes(len(pcm)) if self.busy else pcm))
                    except ConnectionClosed:
                        # Recognition reader reconnects; retain the telephone connection.
                        self.asr = None
            elif kind == 'mark' and event.get('mark', {}).get('name') == self.mark:
                self.playback.set()
            elif kind == 'dtmf':
                digit = event.get('dtmf', {}).get('digit')
                if digit == '9':
                    self.interrupted.set()
                    await self.send('clear')
                    self.playback.set()
                    if self.turn_task and not self.turn_task.done():
                        self.turn_task.cancel()
                    log.warning('Caller interrupted playback using keypad')
                if digit in ('1', '2') and not self.queue.full():
                    self.language = 'hi' if digit == '1' else 'en'
                    self.queue.put_nowait(('language', self.language))
            elif kind == 'stop':
                return

    async def transcripts(self):
        failures = 0
        while True:
            while self.asr is None:
                await asyncio.sleep(0.05)
            current = self.asr
            try:
                async for raw in current:
                    if not isinstance(raw, str):
                        continue
                    event = json.loads(raw)
                    if event.get('type') == 'error':
                        raise RuntimeError('Meta recognition provider error')
                    if event.get('type') == 'speechComplete':
                        text = event.get('transcript', '').strip()
                        if text and not self.busy and not self.queue.full():
                            failures = 0
                            log.warning('Completed speech turn received; queued for answer')
                            self.queue.put_nowait(('question', text[:2000]))
            except (ConnectionClosed, RuntimeError) as exc:
                log.warning('Recognition stream interrupted: %s', type(exc).__name__)
            self.asr = None
            await current.close()
            while self.asr is None:
                failures += 1
                if failures > 3:
                    raise RuntimeError('Recognition could not reconnect after three attempts')
                try:
                    self.asr = await meta.connect_asr()
                    log.warning('Recognition reconnected; telephone call preserved')
                    if not self.busy and not self.queue.full():
                        self.queue.put_nowait(('notice', ''))
                except Exception as exc:
                    log.warning('Recognition reconnect failed: %s', type(exc).__name__)
                    await asyncio.sleep(1)

    async def speak_answer(self, messages, language):
        """Overlap model text and next-sentence synthesis with current audio playback."""
        queue = asyncio.Queue(maxsize=2)
        started = time.perf_counter()
        spoken = []

        async def produce():
            try:
                async for sentence in meta.stream_sentences(messages, language):
                    if self.interrupted.is_set():
                        break
                    text_ready = time.perf_counter()
                    log.warning('Streamed sentence text ready at %.2fs', text_ready - started)
                    pcm = await asyncio.to_thread(voice.synthesize, sentence, language, self.rate)
                    log.warning('Streamed sentence synthesis took %.2fs', time.perf_counter() - text_ready)
                    await queue.put((sentence, pcm, None))
            except Exception as exc:
                await queue.put((None, None, exc))
            finally:
                # Cancellation must not block trying to enqueue into a full queue.
                if not asyncio.current_task().cancelling():
                    await queue.put((None, None, None))

        producer = asyncio.create_task(produce())
        try:
            while not self.interrupted.is_set():
                sentence, pcm, error = await queue.get()
                if error:
                    raise error
                if sentence is None:
                    break
                if not spoken:
                    log.warning('Answer first audio ready in %.2fs after final transcript', time.perf_counter() - started)
                spoken.append(sentence)
                await self.say(sentence, language, pcm=pcm)
            if not spoken and not self.interrupted.is_set():
                raise RuntimeError('No spoken answer generated')
            return ' '.join(spoken) + (' [Interrupted by caller]' if self.interrupted.is_set() else '')
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    async def respond(self):
        while True:
            kind, text = await self.queue.get()
            self.interrupted.clear()
            if kind == 'welcome':
                await self.say(WELCOME_HI, 'hi')
                await self.say(WELCOME_EN, 'en')
            elif kind == 'language':
                await self.say('अपना सवाल पूछिए।' if text == 'hi' else 'Please ask your question.', text)
            elif kind == 'notice':
                await self.say(RETRY_HI if self.language == 'hi' else RETRY_EN, self.language)
            else:
                self.busy = True
                try:
                    messages = self.history + [{'role': 'user', 'content': text}]
                    log.warning('Requesting Meta answer')
                    started = time.perf_counter()
                    self.turn_task = asyncio.create_task(self.speak_answer(messages, self.language))
                    try:
                        reply = await self.turn_task
                    except asyncio.CancelledError:
                        if not self.interrupted.is_set():
                            raise
                        reply = '[Reply interrupted by caller]'
                    log.warning('Spoken answer turn completed in %.2fs', time.perf_counter() - started)
                    self.history = (messages + [{'role': 'assistant', 'content': reply}])[-12:]
                except Exception as exc:
                    log.warning('Answer turn failed (%s); keeping call open', type(exc).__name__)
                    await self.say(RETRY_HI if self.language == 'hi' else RETRY_EN, self.language)
                finally:
                    self.turn_task = None
                    self.busy = False


@app.websocket('/exotel')
@app.websocket('/exotel/{connection_token}')
async def exotel(ws: WebSocket, connection_token: str = ''):
    global active_calls
    if not authorized(connection_token or ws.query_params.get('token')):
        log.warning('Call connection rejected: app token missing or incorrect')
        await ws.close(code=1008)
        return
    if active_calls >= int(os.getenv('MAX_CONCURRENT_CALLS', '1')):
        await ws.close(code=1013)
        return
    active_calls += 1
    try:
        await ws.accept()
    except BaseException:
        active_calls -= 1
        raise
    log.warning('Call connection accepted')
    call = Call(ws)
    tasks = [asyncio.create_task(call.receive(), name='telephone')]
    if os.getenv('CALL_MODE') != 'echo':
        tasks += [asyncio.create_task(call.transcripts(), name='recognition'), asyncio.create_task(call.respond(), name='answer')]
    try:
        done, _ = await asyncio.wait(tasks, timeout=int(os.getenv('MAX_CALL_SECONDS', '300')),
                                     return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if not task.cancelled() and task.exception():
                log.warning('Failed call stage: %s', task.get_name())
            task.result()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        # Avoid logging API responses, transcripts, caller numbers or URL tokens.
        log.warning('Call ended with %s; verify model access/audio configuration', type(exc).__name__)
    finally:
        active_calls -= 1
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if call.asr:
            await call.asr.close()
        with contextlib.suppress(Exception):
            await ws.close()
