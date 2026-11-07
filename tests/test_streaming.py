import asyncio
import json
from unittest.mock import AsyncMock

import httpx

from app.streaming import SentenceBuffer


def test_sentence_boundaries_and_tail():
    buffer = SentenceBuffer()
    assert buffer.feed('Value is 3.1 and') == []
    assert buffer.feed(' useful. Next') == ['Value is 3.1 and useful.']
    assert buffer.feed(' sentence!') == ['Next sentence!']
    assert buffer.feed(' नमस्ते।') == ['नमस्ते।']
    assert buffer.feed(' trailing words') == []
    assert buffer.finish() == ['trailing words']


def test_meta_sse_ignores_reasoning_and_streams_text(monkeypatch):
    from app.meta import stream_sentences
    client_type = httpx.AsyncClient
    async def handler(request):
        body = json.loads(request.content)
        assert body['stream'] is True
        events = [{'choices': [{'delta': {'reasoning_content': 'private internal reasoning'}}]},
                  {'choices': [{'delta': {'content': 'Hello. '}}]},
                  {'choices': [{'delta': {'content': 'How can I help?'}}]}]
        data = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events) + 'data: [DONE]\n\n'
        return httpx.Response(200, text=data, headers={'content-type': 'text/event-stream'})
    monkeypatch.setenv('MODEL_API_KEY', 'fake-test-key')
    monkeypatch.setattr('app.meta.httpx.AsyncClient', lambda **kwargs: client_type(transport=httpx.MockTransport(handler)))
    async def scenario():
        return [part async for part in stream_sentences([{'role': 'user', 'content': 'hello'}], 'en')]
    assert asyncio.run(scenario()) == ['Hello.', 'How can I help?']


def test_place_question_uses_meta_web_search():
    from app.meta import request_for, _lookup_sentences
    path, payload = request_for([{'role': 'user', 'content': 'What is the address of the Rajkot labour office?'}], 'en')
    assert path == '/responses'
    assert payload['tools'] == [{'type': 'web_search'}]
    chat_path, chat_payload = request_for([{'role': 'user', 'content': 'What is two plus two?'}], 'en')
    assert chat_path == '/chat/completions'
    assert chat_payload['reasoning_effort'] == 'medium'
    assert _lookup_sentences([
        'I will look up the office.',
        'The labour office is at Jilla Seva Sadan and the number is 0281-2474654.',
    ]) == ['The labour office is at Jilla Seva Sadan and the number is 0281-2474654.']


def test_first_sentence_plays_before_generation_finishes(monkeypatch):
    from app.main import Call
    async def scenario():
        first_played = asyncio.Event()
        async def stream(*args):
            yield 'First sentence.'
            await asyncio.wait_for(first_played.wait(), 2)
            yield 'Second sentence.'
        call = Call(AsyncMock())
        async def say(text, language, pcm=None):
            first_played.set()
        call.say = AsyncMock(side_effect=say)
        monkeypatch.setattr('app.main.meta.stream_sentences', stream)
        monkeypatch.setattr('app.main.voice.synthesize', lambda *args: bytes(3200))
        reply = await call.speak_answer([], 'en')
        assert reply == 'First sentence. Second sentence.'
        assert call.say.call_count == 2
    asyncio.run(scenario())


def test_recognition_disconnect_reconnects_without_ending_call(monkeypatch):
    from app.main import Call
    class ClosedStream:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration
        async def close(self):
            pass
    class NewStream(ClosedStream):
        async def __anext__(self):
            await asyncio.sleep(100)
    async def scenario():
        call = Call(AsyncMock())
        call.asr = ClosedStream()
        replacement = NewStream()
        reconnect = AsyncMock(return_value=replacement)
        monkeypatch.setattr('app.main.meta.connect_asr', reconnect)
        worker = asyncio.create_task(call.transcripts())
        try:
            await asyncio.sleep(.05)
            assert not worker.done()
            assert call.asr is replacement
            assert call.queue.get_nowait()[0] == 'notice'
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
    asyncio.run(scenario())


def test_keypad_interrupt_cancels_generation_but_preserves_call(monkeypatch):
    from app.main import Call
    async def scenario():
        begun = asyncio.Event()
        async def stream(*args):
            begun.set()
            await asyncio.sleep(100)
            yield 'Too late.'
        socket = AsyncMock()
        socket.receive_json.side_effect = [{'event': 'dtmf', 'dtmf': {'digit': '9'}}, {'event': 'stop'}]
        call = Call(socket)
        call.sid = 'test'
        monkeypatch.setattr('app.main.meta.stream_sentences', stream)
        worker = asyncio.create_task(call.respond())
        try:
            call.queue.put_nowait(('question', 'hello'))
            await asyncio.wait_for(begun.wait(), 1)
            await call.receive()
            await asyncio.sleep(.05)
            assert not worker.done()
            assert not call.busy
            assert socket.send_json.call_args.args[0]['event'] == 'clear'
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
    asyncio.run(scenario())
