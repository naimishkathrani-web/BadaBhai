"""Exercise a local Exotel-shaped call against live Meta models. Uses API credits."""
import asyncio
import base64
import json
import os
from urllib.parse import quote

import websockets
from dotenv import dotenv_values
from app.voice import synthesize


async def main():
    config = dotenv_values('.env')
    uri = 'ws://127.0.0.1:8000/exotel?token=' + quote(config['APP_TOKEN'], safe='')
    language = os.getenv('SMOKE_LANGUAGE', 'en')
    question = await asyncio.to_thread(synthesize, 'मजबूत पासवर्ड कैसे बनाएं?' if language == 'hi' else 'What is a strong password?', language, 8000)
    marks = asyncio.Queue()
    audio = asyncio.Queue()
    received = 0
    async with websockets.connect(uri, max_size=2**20) as ws:
        await ws.send(json.dumps({'event': 'start', 'start': {
            'stream_sid': 'local-smoke-test', 'media_format': {'sample_rate': '8000'}}}))

        async def reader():
            nonlocal received
            async for raw in ws:
                event = json.loads(raw)
                if event['event'] == 'media':
                    received += len(base64.b64decode(event['media']['payload']))
                elif event['event'] == 'mark':
                    await ws.send(json.dumps(event))
                    await marks.put(event['mark']['name'])

        async def sender():
            while True:
                try:
                    pcm = audio.get_nowait()
                except asyncio.QueueEmpty:
                    pcm = bytes(1600)
                await ws.send(json.dumps({'event': 'media', 'media': {
                    'payload': base64.b64encode(pcm).decode()}}))
                await asyncio.sleep(.1)

        tasks = [asyncio.create_task(reader()), asyncio.create_task(sender())]
        try:
            await asyncio.wait_for(marks.get(), 90)
            await asyncio.wait_for(marks.get(), 30)
            print('Bilingual welcome received', flush=True)
            await ws.send(json.dumps({'event': 'dtmf', 'dtmf': {'digit': '1' if language == 'hi' else '2'}}))
            await asyncio.wait_for(marks.get(), 30)
            print('Language selection received:', language, flush=True)
            for index in range(0, len(question), 1600):
                audio.put_nowait(question[index:index+1600].ljust(1600, b'\0'))
            before = received
            await asyncio.wait_for(marks.get(), 90)
            assert received > before
            print('Spoken Meta answer received: local call pipeline passed', flush=True)
            await ws.send(json.dumps({'event': 'stop'}))
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == '__main__':
    asyncio.run(main())
