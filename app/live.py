"""Ephemeral, token-protected events for the judge/demo dashboard."""

import asyncio


class LiveDashboard:
    def __init__(self):
        self.clients = set()
        self.lock = asyncio.Lock()

    async def connect(self, websocket):
        self.clients.add(websocket)

    def disconnect(self, websocket):
        self.clients.discard(websocket)

    async def emit(self, event, **data):
        if not self.clients:
            return
        message = {"event": event, **data}
        stale = []
        async with self.lock:
            for client in tuple(self.clients):
                try:
                    await asyncio.wait_for(client.send_json(message), timeout=0.25)
                except Exception:
                    stale.append(client)
        for client in stale:
            self.disconnect(client)


dashboard = LiveDashboard()
