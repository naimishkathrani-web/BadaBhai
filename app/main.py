import asyncio
import base64
import contextlib
import io
import math
import struct
import json
import logging
import os
import re
import secrets
import wave
import time
from datetime import datetime, timezone
from websockets.exceptions import ConnectionClosed
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
from app import meta, voice
from app.audio import Resampler, chunks
from app.archive import get_call, list_calls
from app.live import dashboard

log = logging.getLogger('badabhai')
WELCOME_HI = 'नमस्ते, मैं बड़ा भाई हूँ। इस फोन पर हिंदी या अंग्रेज़ी में सवाल पूछिए। अंग्रेज़ी के लिए दो दबाएँ।'
WELCOME_EN = "Hello, I'm Bada Bhai. Ask me anything in Hindi or English. Press 2 for English, or 3 for Hindi."
RETRY_HI = 'माफ़ कीजिए, फिर से पूछिए।'
RETRY_EN = 'Sorry, please ask that again.'
CAPABILITIES_EN = 'I explain everyday questions in simple Hindi or English, and I can repeat anything. Press 2 for English, 3 for Hindi, or just talk over me if you want to ask something else.'
CAPABILITIES_HI = 'मैं रोज़मर्रा के सवाल आसान हिंदी या अंग्रेज़ी में समझाता हूँ, और दोहरा भी सकता हूँ। अंग्रेज़ी के लिए दो दबाएँ, या बीच में बोलकर नया सवाल पूछें।'
CAPABILITY_AUDIO = {}
WAIT_TONE_AUDIO = {}


def soft_tone(rate=8000, duration_ms=180):
    frames = int(rate * duration_ms / 1000)
    edge = max(1, int(rate * 0.02))
    samples = []
    for i in range(frames):
        envelope = min(1.0, i / edge, (frames - i) / edge)
        samples.append(struct.pack('<h', int(1200 * envelope * math.sin(2 * math.pi * 520 * i / rate))))
    return b''.join(samples)


def wait_tone(rate):
    if rate not in WAIT_TONE_AUDIO:
        path = Path(__file__).resolve().parents[1] / 'assets' / 'wait-tone.wav'
        try:
            with wave.open(str(path), 'rb') as wav:
                source_rate = wav.getframerate()
                pcm = wav.readframes(wav.getnframes())
            WAIT_TONE_AUDIO[rate] = Resampler(source_rate, rate).convert(pcm)
        except (FileNotFoundError, wave.Error):
            WAIT_TONE_AUDIO[rate] = soft_tone(rate, 1000)
    return WAIT_TONE_AUDIO[rate]


@asynccontextmanager
async def lifespan(app):
    if os.getenv('PREWARM_VOICES', '0') == '1' and os.getenv('CALL_MODE') != 'echo':
        log.warning('Preparing both voices and welcome audio before accepting calls')
        audio_dir = Path(__file__).resolve().parents[1] / 'runtime' / 'audio'
        audio_dir.mkdir(parents=True, exist_ok=True)
        for language, text in [('hi', WELCOME_HI), ('en', WELCOME_EN), ('hi', RETRY_HI), ('en', RETRY_EN),
                               ('hi', CAPABILITIES_HI), ('en', CAPABILITIES_EN)]:
            for rate in (8000, 16000, 24000):
                pcm = await asyncio.to_thread(voice.synthesize, text, language, rate)
                if text in (CAPABILITIES_HI, CAPABILITIES_EN):
                    CAPABILITY_AUDIO[(language, rate)] = pcm
                    if rate == 8000:
                        output = io.BytesIO()
                        with wave.open(output, 'wb') as wav:
                            wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                            wav.writeframes(pcm)
                        (audio_dir / f'capabilities_{language}.wav').write_bytes(output.getvalue())
        log.warning('Voice startup complete: ready to accept calls')
    # Calls are not saved. The live desk shows words only while a call is open.
    yield


app = FastAPI(title='BadaBhai', lifespan=lifespan)
active_calls = 0
live_state = {'status': 'waiting', 'call_id': None, 'language': None, 'country_code': None}


def authorized(value):
    token = os.getenv('APP_TOKEN', '')
    return bool(token and value and secrets.compare_digest(value, token))


def default_language_for_caller(phone_number):
    """Choose Hindi for Indian caller IDs and English as the general default."""
    digits = re.sub(r'\D', '', str(phone_number or ''))
    return 'hi' if digits.startswith('91') else 'en'


def _html_file(name):
    return Path(__file__).with_name(name).read_text(encoding='utf-8')


def _is_ai_crawler(request: Request):
    agent = (request.headers.get('user-agent') or '').lower()
    return any(token in agent for token in (
        'meta-externalagent', 'meta-webindexer', 'meta-externalfetcher',
        'facebookbot', 'facebot', 'chatgpt', 'gptbot', 'claudebot',
        'anthropic', 'perplexity', 'bytespider', 'google-extended',
    ))


def _crawler_landing(html):
    """AI browsers often fail when third-party video iframes are blocked; keep links only."""
    html = re.sub(r'<iframe\b[^>]*>\s*</iframe>', '', html, flags=re.I)
    html = re.sub(r'<iframe\b[^>]*/>', '', html, flags=re.I)
    return html


SITE_PAGES = {
    'how-it-works': 'how-it-works.html',
    'future': 'future.html',
    'commitment': 'commitment.html',
    'architecture': 'architecture.html',
    'backup-demo': 'backup-demo.html',
}


@app.get('/', response_class=HTMLResponse)
def home(request: Request):
    html = _html_file('landing.html')
    if _is_ai_crawler(request):
        html = _crawler_landing(html)
    return HTMLResponse(html)


@app.get('/gig-work')
@app.get('/gig-work.html')
def gig_work_redirect():
    return RedirectResponse('/future#impact', status_code=302)


@app.get('/how-it-works', response_class=HTMLResponse)
@app.get('/future', response_class=HTMLResponse)
@app.get('/commitment', response_class=HTMLResponse)
@app.get('/architecture', response_class=HTMLResponse)
@app.get('/backup-demo', response_class=HTMLResponse)
def site_page(request: Request):
    name = request.url.path.strip('/')
    filename = SITE_PAGES.get(name)
    if not filename:
        raise HTTPException(404, 'Page not found')
    return HTMLResponse(_html_file(filename))


@app.get('/how-it-works.html')
@app.get('/future.html')
@app.get('/commitment.html')
@app.get('/architecture.html')
@app.get('/backup-demo.html')
def site_page_html_redirect(request: Request):
    """Extensionless URLs are canonical; .html aliases redirect for crawlers/judges."""
    name = request.url.path.strip('/').removesuffix('.html')
    if name not in SITE_PAGES:
        raise HTTPException(404, 'Page not found')
    return RedirectResponse(url=f'/{name}', status_code=301)


@app.head('/')
def head_home():
    body = _html_file('landing.html').encode('utf-8')
    return Response(content=b'', media_type='text/html; charset=utf-8',
                    headers={'content-length': str(len(body))})


@app.head('/how-it-works')
@app.head('/future')
@app.head('/commitment')
@app.head('/architecture')
@app.head('/backup-demo')
def head_site_page(request: Request):
    name = request.url.path.strip('/')
    filename = SITE_PAGES.get(name)
    if not filename:
        raise HTTPException(404, 'Page not found')
    body = _html_file(filename).encode('utf-8')
    return Response(content=b'', media_type='text/html; charset=utf-8',
                    headers={'content-length': str(len(body))})


@app.head('/dashboard')
@app.head('/operator')
def head_dashboard():
    body = _html_file('index.html').encode('utf-8')
    return Response(content=b'', media_type='text/html; charset=utf-8',
                    headers={'content-length': str(len(body))})


@app.head('/health')
def head_health():
    body = b'{"status":"running"}'
    return Response(content=b'', media_type='application/json',
                    headers={'content-length': str(len(body))})


@app.get('/backup-demo', response_class=HTMLResponse)
def backup_demo():
    return Path(__file__).with_name('backup_demo.html').read_text(encoding='utf-8')


@app.get('/operator', response_class=HTMLResponse)
@app.get('/dashboard', response_class=HTMLResponse)
def operator_dashboard():
    return HTMLResponse(_html_file('index.html'))


# Local media (wait tone, walkthrough MP4 placeholders). Keep after page routes.
_assets_dir = Path(__file__).resolve().parents[1] / 'assets'
_assets_dir.mkdir(parents=True, exist_ok=True)
app.mount('/assets', StaticFiles(directory=str(_assets_dir)), name='assets')


def require_private_archive_user(value, request):
    """Private archive stays off the public hostname (Nginx returns 403).

    IIS Windows Auth is not installed on this host, so loopback browser access is
    allowed without X-IIS-User. Non-loopback still requires that trusted header.
    """
    host = request.client.host if request.client else ''
    if host in ('127.0.0.1', '::1'):
        return
    if not value or not value.strip():
        raise HTTPException(403, 'Private archive requires Windows sign-in through IIS')


@app.get('/operator/archive', response_class=HTMLResponse)
def private_archive(request: Request, x_iis_user: str = Header(default='')):
    require_private_archive_user(x_iis_user, request)
    return Path(__file__).with_name('archive.html').read_text(encoding='utf-8')


@app.get('/api/private/calls')
async def private_call_list(request: Request, search: str = '', x_iis_user: str = Header(default='')):
    require_private_archive_user(x_iis_user, request)
    if not os.getenv('PGDATABASE'):
        raise HTTPException(503, 'Private PostgreSQL archive is not configured')
    try:
        return {'calls': await list_calls(search)}
    except Exception as exc:
        log.warning('Private call list failed (%s)', type(exc).__name__)
        raise HTTPException(503, 'Call archive is unavailable') from None


@app.get('/api/private/calls/{call_sid}')
async def private_call_detail(call_sid: str, request: Request, x_iis_user: str = Header(default='')):
    require_private_archive_user(x_iis_user, request)
    if not os.getenv('PGDATABASE'):
        raise HTTPException(503, 'Private PostgreSQL archive is not configured')
    try:
        call = await get_call(call_sid)
    except Exception as exc:
        log.warning('Private call detail failed (%s)', type(exc).__name__)
        raise HTTPException(503, 'Call archive is unavailable') from None
    if not call:
        raise HTTPException(404, 'Call not found')
    call.pop('recording_base64', None)
    return call


@app.get('/api/private/calls/{call_sid}/recording')
async def private_call_recording(call_sid: str, request: Request, x_iis_user: str = Header(default='')):
    require_private_archive_user(x_iis_user, request)
    if not os.getenv('PGDATABASE'):
        raise HTTPException(503, 'Private PostgreSQL archive is not configured')
    try:
        call = await get_call(call_sid, include_recording=True)
        data = call.get('recording_base64') if call else None
        if not data:
            raise HTTPException(404, 'Recording not found')
        return Response(base64.b64decode(data), media_type=call.get('recording_content_type') or 'audio/mpeg',
                        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})
    except HTTPException:
        raise
    except Exception as exc:
        log.warning('Private recording retrieval failed (%s)', type(exc).__name__)
        raise HTTPException(503, 'Recording is unavailable') from None


@app.get('/api/public-demo-config')
def public_demo_config():
    # Only deliberately public, non-secret display values belong here.
    phone = os.getenv('JUDGES_PUBLIC_PHONE_E164', '').strip() or '+917948504917'
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}', phone):
        phone = ''
    return {'phone': phone,
            'video_url': os.getenv('JUDGES_PUBLIC_VIDEO_URL', '/assets/bada-how.mp4'),
            'backup_video_url': os.getenv('JUDGES_BACKUP_VIDEO_URL', '/assets/bada-live-demo.mp4')}


@app.get('/health')
def health():
    return {'status': 'running', 'meta_key_configured': bool(os.getenv('MODEL_API_KEY')),
            'call_mode': os.getenv('CALL_MODE', 'meta'),
            'note': 'Configuration only; live model access and local TTS are not checked.'}


@app.websocket('/api/live')
@app.websocket('/ws')
async def live_dashboard(ws: WebSocket):
    await ws.accept()
    try:
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
        self.exotel_call_sid = None
        self.started_at = None
        self.history = []
        self.transcript = []
        self.usefulness = None
        self.feedback_available = False
        self.queue = asyncio.Queue(maxsize=3)
        self.playback = asyncio.Event()
        self.playback.set()
        self.mark = None
        self.busy = False
        self.media_seen = False
        self.media_ready = asyncio.Event()
        self.last_partial_at = 0.0
        self.speech_end_at = None
        self.interrupted = asyncio.Event()
        self.turn_task = None
        self.call_id = None
        self.caller_number = None
        self.country_code = None
        self.turn_started = None
        self.request_started = None
        self.answer_first_audio_sent = False
        self.in_answer = False
        self.playback_started_at = 0.0
        self.last_assistant_text = ''

    async def publish(self, event, **data):
        if self.call_id:
            await dashboard.emit(event, call_id=self.call_id, **data)

    async def send(self, event, **kwargs):
        await self.ws.send_json({'event': event, 'stream_sid': self.sid, **kwargs})

    def _looks_like_echo(self, text):
        """Ignore ASR finals that mostly repeat what we just spoke into the handset."""
        spoken = re.sub(r'\W+', ' ', (self.last_assistant_text or '').lower()).strip()
        heard = re.sub(r'\W+', ' ', (text or '').lower()).strip()
        if not spoken or not heard or len(heard) < 8:
            return False
        if heard in spoken or spoken in heard:
            return True
        spoken_words = set(spoken.split())
        heard_words = set(heard.split())
        if not heard_words:
            return False
        overlap = len(spoken_words & heard_words) / max(1, len(heard_words))
        return overlap >= 0.7

    async def barge_in(self, text, method='voice'):
        """Stop current playback immediately so the caller can redirect, Gemini-style."""
        self.interrupted.set()
        try:
            await self.send('clear')
        except Exception:
            pass
        self.playback.set()
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
        log.warning('Caller interrupted playback using %s', method)
        await self.publish('interrupt', method=method)
        if text and not self.queue.full():
            self.request_started = time.perf_counter()
            self.queue.put_nowait(('question', text[:2000]))

    async def say(self, text, language, pcm=None):
        was_busy = self.busy
        self.busy = True
        try:
            started = time.perf_counter()
            if pcm is None:
                pcm = await asyncio.to_thread(voice.synthesize, text, language, self.rate)
            if text:
                self.last_assistant_text = text
            log.warning('Speech synthesis completed in %.2fs', time.perf_counter() - started)
            if not pcm:
                return
            # Exotel drops early outbound audio until the inbound media stream is live.
            if not self.media_ready.is_set():
                try:
                    await asyncio.wait_for(self.media_ready.wait(), 10)
                except asyncio.TimeoutError:
                    log.warning('Speaking without confirmed inbound media yet')
            log.warning('Sending spoken audio: language=%s duration=%.1fs', language, len(pcm)/(self.rate*2))
            self.playback.clear()
            self.playback_started_at = time.perf_counter()
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
                self.exotel_call_sid = start.get('call_sid')
                self.started_at = datetime.now(timezone.utc)
                self.call_id = secrets.token_hex(4)
                self.caller_number = start.get('from')
                self.language = default_language_for_caller(self.caller_number)
                digits = re.sub(r'\D', '', str(self.caller_number or ''))
                self.country_code = next((code for code in ('91', '1', '44', '61', '65', '62', '63', '254', '234', '27')
                                          if digits.startswith(code)), None)
                self.rate = int(start.get('media_format', {}).get('sample_rate', 8000))
                if not self.sid or self.rate not in (8000, 16000, 24000):
                    raise ValueError('Unsupported audio format')
                converter = Resampler(self.rate, 24000)
                log.warning('Call audio ready: sample_rate=%d', self.rate)
                live_state.update({'status': 'connected', 'call_id': self.call_id,
                                   'language': self.language,
                                   'country_code': '+' + self.country_code if self.country_code else None})
                await self.publish('call_state', status='connected', language=self.language,
                                   country_code='+' + self.country_code if self.country_code else None)
                if os.getenv('CALL_MODE') != 'echo':
                    self.queue.put_nowait(('welcome', ''))
                    # Speak immediately while the recognition service opens its
                    # WebSocket; waiting here first can leave Exotel callers silent.
                    self.asr = await meta.connect_asr(self.language)
            elif kind == 'media' and self.sid:
                if not self.media_seen:
                    self.media_seen = True
                    self.media_ready.set()
                    log.warning('First incoming audio packet received')
                pcm = base64.b64decode(event['media']['payload'], validate=True)
                if os.getenv('CALL_MODE') == 'echo':
                    await self.send('media', media={'payload': base64.b64encode(pcm).decode()})
                elif self.asr:
                    # Full-duplex listening so callers can barge in while BadaBhai speaks.
                    try:
                        await self.asr.send(converter.convert(pcm))
                    except ConnectionClosed:
                        # Recognition reader reconnects; retain the telephone connection.
                        self.asr = None
            elif kind == 'mark' and event.get('mark', {}).get('name') == self.mark:
                self.playback.set()
            elif kind == 'dtmf':
                digit = event.get('dtmf', {}).get('digit')
                if digit == '9':
                    await self.barge_in('', method='keypad')
                elif digit in ('7', '8') and self.feedback_available:
                    self.usefulness = 'helpful' if digit == '7' else 'not_helpful'
                    self.transcript.append({'role': 'feedback', 'value': self.usefulness,
                                            'at': datetime.now(timezone.utc).isoformat()})
                    await self.publish('usefulness', value=self.usefulness)
                if digit == '1' and not self.queue.full():
                    self.queue.put_nowait(('capabilities', self.language))
                elif digit == '2' and not self.queue.full():
                    self.language = 'en'
                    live_state['language'] = self.language
                    await self.publish('language', language=self.language)
                    # Re-open ASR with English-first bias for better recognition.
                    try:
                        if self.asr:
                            await self.asr.close()
                    except Exception:
                        pass
                    self.asr = None
                    self.queue.put_nowait(('language', self.language))
                elif digit == '3' and not self.queue.full():
                    self.language = 'hi'
                    live_state['language'] = self.language
                    await self.publish('language', language=self.language)
                    try:
                        if self.asr:
                            await self.asr.close()
                    except Exception:
                        pass
                    self.asr = None
                    self.queue.put_nowait(('language', self.language))
            elif kind == 'stop':
                self.exotel_call_sid = self.exotel_call_sid or event.get('stop', {}).get('call_sid')
                await self.publish('call_state', status='ended')
                live_state.update({'status': 'waiting', 'call_id': None,
                                   'language': None, 'country_code': None})
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
                            await self.publish('performance', stage='asr_finalize', key='stt_ms',
                                               ms=round((time.perf_counter() - self.speech_end_at) * 1000, 1))
                        self.speech_end_at = None
                        if not text:
                            continue
                        if self._looks_like_echo(text):
                            log.warning('Ignored likely TTS echo transcript')
                            continue
                        self.transcript.append({'role': 'caller', 'text': text[:2000],
                                                'at': datetime.now(timezone.utc).isoformat()})
                        await self.publish('transcript_final', text=text[:2000])
                        # Voice barge-in only during answer playback (not greeting),
                        # so echo/noise cannot wipe the welcome.
                        if self.in_answer and self.busy and len(text) >= 10 and (
                                self.playback_started_at
                                and time.perf_counter() - self.playback_started_at >= 0.8):
                            failures = 0
                            await self.barge_in(text, method='voice')
                            continue
                        if not self.busy and not self.queue.full():
                            failures = 0
                            self.request_started = time.perf_counter()
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
                    self.asr = await meta.connect_asr(self.language)
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
                        await self.publish('performance', stage='first_text', key='spark_ms',
                                           ms=round((text_ready - started) * 1000, 1))
                    await self.publish('assistant_sentence', text=sentence, language=language)
                    self.transcript.append({'role': 'assistant', 'text': sentence,
                                            'at': datetime.now(timezone.utc).isoformat()})
                    synthesis_started = time.perf_counter()
                    pcm = await asyncio.to_thread(voice.synthesize, sentence, language, self.rate)
                    log.warning('Streamed sentence synthesis took %.2fs', time.perf_counter() - text_ready)
                    if not spoken:
                        await self.publish('performance', stage='first_synthesis', key='tts_ms',
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
                try:
                    sentence, pcm, error = await asyncio.wait_for(queue.get(), timeout=8)
                except asyncio.TimeoutError:
                    # Stay silent while thinking — no waiting beep/tone.
                    continue
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
                text = WELCOME_HI if self.language == 'hi' else WELCOME_EN
                await self.say(text, self.language)
            elif kind == 'capabilities':
                clip = CAPABILITY_AUDIO.get((text, self.rate))
                if clip:
                    await self.say('', text, pcm=clip)
                else:
                    await self.say(CAPABILITIES_HI if text == 'hi' else CAPABILITIES_EN, text)
                await self.say('अब अपना सवाल पूछिए।' if text == 'hi' else 'Please ask your question now.', text)
            elif kind == 'language':
                await self.say('अब अपना सवाल पूछिए।' if text == 'hi'
                               else 'Please ask your question now.', text)
            elif kind == 'notice':
                await self.say(RETRY_HI if self.language == 'hi' else RETRY_EN, self.language)
            else:
                self.busy = True
                try:
                    messages = self.history + [{'role': 'user', 'content': text}]
                    model_messages = list(messages)
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
                    await self.publish('performance', stage='turn_complete', key='total_ms',
                                       ms=round((time.perf_counter() - (self.turn_started or started)) * 1000, 1))
                    # Keep keypad 7/8 available silently for the live dashboard; do not
                    # interrupt the conversation with a spoken usefulness prompt.
                    self.feedback_available = True
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
            live_state.update({'status': 'waiting', 'call_id': None, 'language': None, 'country_code': None})
            await call.publish('call_state', status='ended')
        active_calls -= 1
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if call.asr:
            await call.asr.close()
        with contextlib.suppress(Exception):
            await ws.close()
