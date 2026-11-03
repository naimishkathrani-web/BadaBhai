import base64
import json
import asyncio
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from app.audio import Resampler, chunks
from app.main import app
from starlette.websockets import WebSocketDisconnect
import pytest


def stream_from_answer(responder):
    async def stream(messages, language):
        yield await responder(messages, language)
    return stream


def test_chat_requires_token(monkeypatch):
    monkeypatch.setenv('APP_TOKEN', 'test-secret')
    with TestClient(app) as client:
        assert client.post('/api/chat', json={'text': 'hello'}).status_code == 401


def test_home_serves_live_operator_dashboard():
    with TestClient(app) as client:
        page = client.get('/')
    assert page.status_code == 200
    assert 'Live conversation' in page.text
    assert '/api/live' in page.text
    assert 'Official source' in page.text


def test_chat_uses_selected_language(monkeypatch):
    monkeypatch.setenv('APP_TOKEN', 'test-secret')
    answer = AsyncMock(return_value='नमस्ते')
    monkeypatch.setattr('app.main.meta.answer', answer)
    with TestClient(app) as client:
        result = client.post('/api/chat', headers={'X-App-Token': 'test-secret'}, json={'text': 'hello', 'language': 'hi'})
        assert result.json() == {'answer': 'नमस्ते'}
    assert answer.call_args.args[1] == 'hi'


def test_pm_kisan_question_receives_official_context(monkeypatch):
    monkeypatch.setenv('APP_TOKEN', 'test-secret')
    answer = AsyncMock(return_value='Check the official status page.')
    monkeypatch.setattr('app.main.meta.answer', answer)
    with TestClient(app) as client:
        result = client.post('/api/chat', headers={'X-App-Token': 'test-secret'},
                             json={'text': 'How do I check PM-KISAN status?', 'language': 'en'})
        assert result.status_code == 200
    messages = answer.call_args.args[0]
    assert messages[0]['role'] == 'developer'
    assert 'pmkisan.gov.in' in messages[0]['content']
    assert messages[-1]['role'] == 'user'


def test_live_dashboard_requires_app_token(monkeypatch):
    monkeypatch.setenv('APP_TOKEN', 'test-secret')
    with TestClient(app) as client:
        with client.websocket_connect('/api/live') as ws:
            ws.send_json({'token': 'wrong'})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_live_dashboard_sends_snapshot_to_authenticated_operator(monkeypatch):
    monkeypatch.setenv('APP_TOKEN', 'test-secret')
    with TestClient(app) as client:
        with client.websocket_connect('/api/live') as ws:
            ws.send_json({'token': 'test-secret'})
            assert ws.receive_json()['event'] == 'snapshot'


def test_echo_protocol(monkeypatch):
    monkeypatch.setenv('APP_TOKEN', 'test-secret')
    monkeypatch.setenv('CALL_MODE', 'echo')
    with TestClient(app) as client:
        with client.websocket_connect('/exotel?token=test-secret') as ws:
            ws.send_json({'event': 'connected'})
            ws.send_json({'event': 'start', 'start': {'stream_sid': 'stream-1', 'media_format': {'sample_rate': '8000'}}})
            payload = base64.b64encode(bytes(3200)).decode()
            ws.send_json({'event': 'media', 'media': {'payload': payload}})
            assert ws.receive_json() == {'event': 'media', 'stream_sid': 'stream-1', 'media': {'payload': payload}}
            ws.send_json({'event': 'stop'})


def test_websocket_rejects_missing_token(monkeypatch):
    monkeypatch.setenv('APP_TOKEN', 'test-secret')
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/exotel'):
            pass


def test_path_token_connection(monkeypatch):
    monkeypatch.setenv('APP_TOKEN', 'test-secret')
    monkeypatch.setenv('CALL_MODE', 'echo')
    with TestClient(app) as client:
        with client.websocket_connect('/exotel/test-secret') as ws:
            ws.send_json({'event': 'stop'})
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/exotel/wrong-token'):
                pass


def test_meta_asr_handshake(monkeypatch):
    from app.meta import connect_asr
    socket = AsyncMock()
    socket.recv.return_value = json.dumps({'sessionId': 'mock-session'})
    monkeypatch.setenv('MODEL_API_KEY', 'fake-test-key')
    monkeypatch.setattr('app.meta.websockets.connect', AsyncMock(return_value=socket))
    assert asyncio.run(connect_asr()) is socket
    handshake = json.loads(socket.send.call_args.args[0])
    assert handshake['mode'] == 'ENDPOINTING'
    assert handshake['languageBias'] == ['Hindi', 'English']
    assert 'PM-KISAN' in handshake['keywords']
    assert handshake['authorization']['accessToken'] == 'Bearer fake-test-key'


def test_audio_resampling_and_packet_alignment():
    assert abs(len(Resampler(8000, 24000).convert(bytes(16000))) - 48000) < 10
    packets = list(chunks(bytes(3210), 8000))
    assert len(packets) == 2
    assert all(len(packet) == 3200 for packet in packets)


def test_voicebot_welcome_language_and_answer(monkeypatch):
    from app.main import Call

    async def scenario():
        class FakeSocket:
            async def send_json(self, event):
                if event['event'] == 'mark':
                    call.playback.set()
        call = Call(FakeSocket())
        call.sid = 'fake-stream'
        monkeypatch.setattr('app.main.voice.synthesize', lambda *args: bytes(3200))
        responder = AsyncMock(return_value='A short answer.')
        monkeypatch.setattr('app.main.meta.stream_sentences', stream_from_answer(responder))
        task = asyncio.create_task(call.respond())
        try:
            call.queue.put_nowait(('welcome', ''))
            await asyncio.sleep(0.5)
            assert not call.busy
            call.language = 'en'
            call.queue.put_nowait(('question', 'Hello'))
            await asyncio.sleep(0.3)
            assert call.history[-1]['content'] == 'A short answer.'
            assert responder.call_args.args[1] == 'en'
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_meta_errors_are_not_exposed(monkeypatch):
    monkeypatch.setenv('APP_TOKEN', 'test-secret')
    monkeypatch.setattr('app.main.meta.answer', AsyncMock(side_effect=RuntimeError('private-key')))
    with TestClient(app) as client:
        result = client.post('/api/chat', headers={'X-App-Token': 'test-secret'}, json={'text': 'hello'})
        assert result.status_code == 502
        assert 'private-key' not in result.text


def test_language_key_is_kept_during_welcome():
    from app.main import Call

    async def scenario():
        socket = AsyncMock()
        socket.receive_json.side_effect = [
            {'event': 'dtmf', 'dtmf': {'digit': '2'}}, {'event': 'stop'}]
        call = Call(socket)
        call.asr = object()
        call.busy = True
        await call.receive()
        assert call.language == 'en'
        assert call.queue.get_nowait() == ('language', 'en')

    asyncio.run(scenario())


def test_sms_requires_keypad_consent_and_is_disabled_without_exotel_setup(monkeypatch):
    from app.main import Call
    from app.benefits import PM_KISAN
    for key in ('EXOTEL_API_KEY', 'EXOTEL_API_TOKEN', 'EXOTEL_ACCOUNT_SID', 'EXOTEL_SMS_FROM',
                'EXOTEL_DLT_ENTITY_ID', 'EXOTEL_DLT_TEMPLATE_HI', 'EXOTEL_DLT_TEMPLATE_EN'):
        monkeypatch.delenv(key, raising=False)

    async def scenario():
        socket = AsyncMock()
        socket.receive_json.side_effect = [
            {'event': 'dtmf', 'dtmf': {'digit': '3'}},
            {'event': 'stop'},
        ]
        call = Call(socket)
        call.sid = 'test'
        call.source = PM_KISAN
        call.caller_number = '+919876543210'
        await call.receive()
        assert call.sms_task is not None
        await call.sms_task
        assert call.sms_requested
        assert call.queue.get_nowait()[0] == 'sms_setup'

    asyncio.run(scenario())


def test_sms_sender_uses_configured_exotel_credentials_and_dlt_template(monkeypatch):
    from app import sms
    for key, value in {
        'EXOTEL_API_KEY': 'test-key',
        'EXOTEL_API_TOKEN': 'test-token',
        'EXOTEL_ACCOUNT_SID': 'test-account',
        'EXOTEL_SMS_FROM': 'EXOTEL',
        'EXOTEL_DLT_ENTITY_ID': 'test-entity',
        'EXOTEL_DLT_TEMPLATE_EN': 'test-template',
        'EXOTEL_SMS_BASE_URL': 'https://api.in.exotel.com',
    }.items():
        monkeypatch.setenv(key, value)

    captured = {}
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'SMSMessage': {'Status': 'queued'}}
    class Client:
        def __init__(self, **kwargs):
            captured['timeout'] = kwargs['timeout']
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, **kwargs):
            captured['url'] = url
            captured.update(kwargs)
            return Response()
    monkeypatch.setattr(sms.httpx, 'AsyncClient', Client)
    result = asyncio.run(sms.send_recap(
        '+919876543210', 'en', 'PM-KISAN info: https://pmkisan.gov.in/'))
    assert result == 'queued'
    assert captured['url'].endswith('/v1/Accounts/test-account/Sms/send')
    assert captured['auth'] == ('test-key', 'test-token')
    assert captured['data']['To'] == '+919876543210'
    assert captured['data']['DltEntityId'] == 'test-entity'
    assert captured['data']['DltTemplateId'] == 'test-template'
    assert captured['data']['SmsType'] == 'transactional_opt_in'


def test_answer_failure_keeps_call_open(monkeypatch):
    from app.main import Call
    async def scenario():
        call = Call(AsyncMock())
        call.language = 'en'
        call.say = AsyncMock()
        monkeypatch.setattr('app.main.voice.synthesize', lambda *args: bytes(3200))
        monkeypatch.setattr('app.main.meta.stream_sentences', stream_from_answer(AsyncMock(side_effect=[RuntimeError('empty answer'), 'It worked.'])))
        worker = asyncio.create_task(call.respond())
        try:
            await call.queue.put(('question', 'First question'))
            await asyncio.sleep(.05)
            assert not worker.done()
            assert 'Please ask' in call.say.call_args.args[0]
            await call.queue.put(('question', 'Second question'))
            await asyncio.sleep(.05)
            assert call.history[-1]['content'] == 'It worked.'
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
    asyncio.run(scenario())
