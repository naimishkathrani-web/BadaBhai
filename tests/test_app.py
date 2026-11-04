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


def test_home_and_operator_routes_serve_their_pages():
    with TestClient(app) as client:
        landing = client.get('/')
        dashboard_page = client.get('/operator')
        public_dashboard = client.get('/dashboard')
        backup_demo = client.get('/backup-demo')
        closed = client.get('/operator/archive')
    assert landing.status_code == dashboard_page.status_code == public_dashboard.status_code == backup_demo.status_code == 200
    assert 'Good guidance.' in landing.text
    assert 'What we might pick up next' in landing.text
    assert 'Nothing from the call is saved' in landing.text
    assert 'PM-KISAN' not in landing.text
    assert 'scrimba.com/explain/guide0gn7k887i' in landing.text
    assert 'Backup walkthrough if the line is down' in backup_demo.text
    assert 'guide0pnl4j0rk' in backup_demo.text
    assert 'Recorded' not in backup_demo.text
    assert 'Live conversation' in dashboard_page.text
    assert 'usefulness' not in dashboard_page.text.casefold()
    assert '/api/live' in dashboard_page.text
    assert closed.status_code == 404


def test_chat_uses_selected_language(monkeypatch):
    monkeypatch.setenv('APP_TOKEN', 'test-secret')
    answer = AsyncMock(return_value='नमस्ते')
    monkeypatch.setattr('app.main.meta.answer', answer)
    with TestClient(app) as client:
        result = client.post('/api/chat', headers={'X-App-Token': 'test-secret'}, json={'text': 'hello', 'language': 'hi'})
        assert result.json() == {'answer': 'नमस्ते'}
    assert answer.call_args.args[1] == 'hi'


def test_generic_question_is_not_injected_with_scheme_context(monkeypatch):
    monkeypatch.setenv('APP_TOKEN', 'test-secret')
    answer = AsyncMock(return_value='Check the official status page.')
    monkeypatch.setattr('app.main.meta.answer', answer)
    with TestClient(app) as client:
        result = client.post('/api/chat', headers={'X-App-Token': 'test-secret'},
                             json={'text': 'How do I explain photosynthesis simply?', 'language': 'en'})
        assert result.status_code == 200
    messages = answer.call_args.args[0]
    assert len(messages) == 1
    assert messages[0]['role'] == 'user'


def test_live_dashboard_is_public_read_only():
    with TestClient(app) as client:
        with client.websocket_connect('/api/live') as ws:
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
    assert 'keywords' not in handshake
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
        call.media_ready.set()
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


def test_keypad_one_queues_capabilities_and_three_switches_to_hindi():
    from app.main import Call

    async def scenario():
        socket = AsyncMock()
        socket.receive_json.side_effect = [
            {'event': 'dtmf', 'dtmf': {'digit': '1'}},
            {'event': 'dtmf', 'dtmf': {'digit': '3'}},
            {'event': 'stop'},
        ]
        call = Call(socket)
        call.sid = 'test'
        await call.receive()
        assert call.queue.get_nowait() == ('capabilities', 'hi')
        assert call.language == 'hi'

    asyncio.run(scenario())


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
            assert 'ask that again' in call.say.call_args.args[0]
            await call.queue.put(('question', 'Second question'))
            await asyncio.sleep(.05)
            assert call.history[-1]['content'] == 'It worked.'
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
    asyncio.run(scenario())
