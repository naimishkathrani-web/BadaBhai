import asyncio
import base64
import contextlib
import io
import json
import logging
import os
import re
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
from app import benefits, sms
from app.audio import Resampler, chunks
from app.live import dashboard

log = logging.getLogger('badabhai')
WELCOME_HI = 'नमस्ते। मैं बड़ा भाई, आपका ए आई सहायक हूँ। हिंदी के लिए एक दबाएं। पीएम-किसान जानकारी के बाद संदेश के लिए तीन दबाएं।'
WELCOME_EN = 'For English, press two. Ask in your own words. For a PM-KISAN SMS recap after the answer, press three.'
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
live_state = {'status': 'waiting', 'call_id': None, 'language': None, 'source': None}


def authorized(value):
    token = os.getenv('APP_TOKEN', '')
    return bool(token and value and secrets.compare_digest(value, token))


@app.get('/', response_class=HTMLResponse)
def home():
    return Path(__file__).with_name('landing.html').read_text(encoding='utf-8')


@app.get('/operator', response_class=HTMLResponse)
def operator_dashboard():
    return Path(__file__).with_name('index.html').read_text(encoding='utf-8')


@app.get('/api/public-demo-config')
def public_demo_config():
    # Only deliberately public, non-secret display values belong here.
    phone = os.getenv('JUDGES_PUBLIC_PHONE_E164', '').strip() or '+917948504917'
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}', phone):
        phone = ''
    return {'phone': phone,
            'video_url': os.getenv('JUDGES_PUBLIC_VIDEO_URL',
                'https://scrimba.com/explain/guide04lf97i2e?claim=j7oakcpcb1jsi5o4&fullscreen=1')}


@app.get('/health')
def health():
    return {'status': 'running', 'meta_key_configured': bool(os.getenv('MODEL_API_KEY')),
            'call_mode': os.getenv('CALL_MODE', 'meta'),
            'note': 'Configuration only; live model access and local TTS are not checked.'}


@app.websocket('/api/live')
async def live_dashboard(ws: WebSocket):
    await ws.accept()
    try:
        hello = await asyncio.wait_for(ws.receive_json(), timeout=10)
        if not isinstance(hello, dict) or not authorized(str(hello.get('token', ''))):
            await ws.close(code=1008)
            return
        await dashboard.connect(ws)
        await ws.send_json({'event': 'snapshot', **live_state})
        while True:
            # Keep the connection open without accepting control actions from the UI.
            await ws.receive_text()
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        dashboard.disconnect(ws)


class Chat(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: str = Field(default='hi', pattern='^(hi|en)$')


@app.post('/api/chat')
async def chat(body: Chat, x_app_token: str = Header(default='')):
    if not authorized(x_app_token):
        raise HTTPException(401, 'Invalid app token')
    try:
        messages = [{'role': 'user', 'content': body.text}]
        reference = benefits.reference_for_text(body.text)
        if reference:
            messages.insert(0, {'role': 'developer', 'content': reference['model_context']})
        return {'answer': await meta.answer(messages, body.language)}
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
        self.last_partial_at = 0.0
        self.speech_end_at = None
        self.interrupted = asyncio.Event()
        self.turn_task = None
        self.call_id = None
        self.caller_number = None
        self.source = None
        self.sms_requested = False
        self.turn_started = None
        self.request_started = None
        self.answer_first_audio_sent = False
        self.in_answer = False
        self.sms_task = None

    async def publish(self, event, **data):
        if self.call_id:
            await dashboard.emit(event, call_id=self.call_id, **data)

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
            first_packet = True
            for chunk in chunks(pcm, self.rate):
                if self.interrupted.is_set():
                    return
                await self.send('media', media={'payload': base64.b64encode(chunk).decode()})
                if first_packet and self.in_answer and not self.answer_first_audio_sent:
                    self.answer_first_audio_sent = True
                    await self.publish('performance', stage='first_audio',
                                       ms=round((time.perf_counter() - self.turn_started) * 1000, 1))
                first_packet = False
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
                self.call_id = secrets.token_hex(4)
                self.caller_number = start.get('from')
                self.rate = int(start.get('media_format', {}).get('sample_rate', 8000))
                if not self.sid or self.rate not in (8000, 16000, 24000):
                    raise ValueError('Unsupported audio format')
                converter = Resampler(self.rate, 24000)
                log.warning('Call audio ready: sample_rate=%d', self.rate)
                live_state.update({'status': 'connected', 'call_id': self.call_id,
                                   'language': self.language, 'source': None})
                await self.publish('call_state', status='connected', language=self.language)
                if os.getenv('CALL_MODE') != 'echo':
                    self.queue.put_nowait(('welcome', ''))
                    # Speak immediately while the recognition service opens its
                    # WebSocket; waiting here first can leave Exotel callers silent.
                    self.asr = await meta.connect_asr()
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
                    live_state['language'] = self.language
                    await self.publish('language', language=self.language)
                    self.queue.put_nowait(('language', self.language))
                elif digit == '3':
                    if (self.source and not self.sms_requested and self.caller_number
                            and re.fullmatch(r'\+[1-9]\d{7,14}', self.caller_number)):
                        self.sms_requested = True
                        await self.publish('sms_state', status='opted_in')
                        self.sms_task = asyncio.create_task(self.send_recap())
                    elif self.sms_requested:
                        await self.publish('sms_state', status='already_requested')
                    else:
                        await self.publish('sms_state', status='unavailable')
                        if not self.queue.full():
                            self.queue.put_nowait(('sms_notice', ''))
            elif kind == 'stop':
                await self.publish('call_state', status='ended')
                live_state.update({'status': 'waiting', 'call_id': None,
                                   'language': None, 'source': None})
                return

    async def send_recap(self):
        if not self.source or not self.caller_number:
            return
        if not sms.ready(self.language):
            await self.publish('sms_state', status='not_configured')
            log.warning('Caller opted in to SMS recap, but Exotel/DLT SMS settings are incomplete')
            if not self.queue.full():
                self.queue.put_nowait(('sms_setup', ''))
            return
        body = self.source['sms_hi' if self.language == 'hi' else 'sms_en']
        try:
            status = await sms.send_recap(self.caller_number, self.language, body)
            if str(status).casefold().startswith('failed'):
                await self.publish('sms_state', status='failed')
                log.warning('Exotel did not accept the opt-in SMS recap')
                if not self.queue.full():
                    self.queue.put_nowait(('sms_setup', ''))
            else:
                await self.publish('sms_state', status='accepted', provider_status=status)
                log.warning('Opt-in SMS recap accepted by Exotel; delivery is not yet confirmed')
                if not self.queue.full():
                    self.queue.put_nowait(('sms_sent', ''))
        except Exception as exc:
            await self.publish('sms_state', status='failed')
            log.warning('Opt-in SMS recap failed (%s)', type(exc).__name__)
            if not self.queue.full():
                self.queue.put_nowait(('sms_setup', ''))

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
                    if event.get('type') == 'speechEnd':
                        self.speech_end_at = time.perf_counter()
                    if event.get('type') == 'transcript' and not event.get('final'):
                        now = time.perf_counter()
                        if now - self.last_partial_at >= 0.25:
                            self.last_partial_at = now
                            await self.publish('transcript_partial', text=event.get('transcript', '')[:2000])
                    if event.get('type') == 'speechComplete':
                        text = event.get('transcript', '').strip()
                        if self.speech_end_at is not None:
                            await self.publish('performance', stage='asr_finalize',
                                               ms=round((time.perf_counter() - self.speech_end_at) * 1000, 1))
                        self.speech_end_at = None
                        if text and not self.busy and not self.queue.full():
                            self.request_started = time.perf_counter()
                        if text:
                            await self.publish('transcript_final', text=text[:2000])
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
        started = self.request_started or time.perf_counter()
        self.request_started = None
        self.turn_started = started
        self.answer_first_audio_sent = False
        spoken = []

        async def produce():
            try:
                async for sentence in meta.stream_sentences(messages, language):
                    if self.interrupted.is_set():
                        break
                    text_ready = time.perf_counter()
                    log.warning('Streamed sentence text ready at %.2fs', text_ready - started)
                    if not spoken:
                        await self.publish('performance', stage='first_text',
                                           ms=round((text_ready - started) * 1000, 1))
                    await self.publish('assistant_sentence', text=sentence, language=language)
                    await self.publish('source', source=(self.source or {}).get('title'),
                                       url=(self.source or {}).get('url'),
                                       verified_on=(self.source or {}).get('verified_on'))
                    synthesis_started = time.perf_counter()
                    pcm = await asyncio.to_thread(voice.synthesize, sentence, language, self.rate)
                    log.warning('Streamed sentence synthesis took %.2fs', time.perf_counter() - text_ready)
                    if not spoken:
                        await self.publish('performance', stage='first_synthesis',
                                           ms=round((time.perf_counter() - synthesis_started) * 1000, 1))
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
                self.in_answer = True
                try:
                    await self.say(sentence, language, pcm=pcm)
                finally:
                    self.in_answer = False
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
            elif kind == 'sms_notice':
                await self.say('पीएम-किसान जानकारी के बाद संदेश के लिए तीन दबाएं।' if self.language == 'hi'
                               else 'After PM-KISAN guidance, press three for an SMS recap.', self.language)
            elif kind == 'sms_setup':
                await self.say('माफ़ कीजिए, इस डेमो लाइन पर संदेश सेवा अभी तैयार नहीं है।' if self.language == 'hi'
                               else 'Sorry, SMS is not configured on this demo line yet.', self.language)
            elif kind == 'sms_sent':
                await self.say('आधिकारिक लिंक वाला संदेश भेजने के लिए रख दिया है।' if self.language == 'hi'
                               else 'I have submitted the official link by text.', self.language)
            else:
                self.busy = True
                try:
                    self.source = benefits.reference_for_text(text)
                    live_state['source'] = self.source['title'] if self.source else None
                    messages = self.history + [{'role': 'user', 'content': text}]
                    model_messages = list(messages)
                    if self.source:
                        await self.publish('source', source=self.source['title'], url=self.source['url'],
                                           verified_on=self.source['verified_on'])
                        # Place trusted context before the caller question; don't store it in history.
                        model_messages.insert(len(model_messages) - 1,
                                              {'role': 'developer', 'content': self.source['model_context']})
                    await self.publish('assistant_state', status='thinking')
                    log.warning('Requesting Meta answer')
                    started = time.perf_counter()
                    self.turn_task = asyncio.create_task(self.speak_answer(model_messages, self.language))
                    try:
                        reply = await self.turn_task
                    except asyncio.CancelledError:
                        if not self.interrupted.is_set():
                            raise
                        reply = '[Reply interrupted by caller]'
                    log.warning('Spoken answer turn completed in %.2fs', time.perf_counter() - started)
                    self.history = (messages + [{'role': 'assistant', 'content': reply}])[-12:]
                    await self.publish('assistant_state', status='complete')
                    await self.publish('performance', stage='turn_complete',
                                       ms=round((time.perf_counter() - (self.turn_started or started)) * 1000, 1))
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
        if call.call_id:
            live_state.update({'status': 'waiting', 'call_id': None,
                               'language': None, 'source': None})
            await call.publish('call_state', status='ended')
        active_calls -= 1
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if call.asr:
            await call.asr.close()
        if call.sms_task:
            await asyncio.gather(call.sms_task, return_exceptions=True)
        with contextlib.suppress(Exception):
            await ws.close()
