"""
monitor/ws_bridge.py
Serveur WebSocket leger (port 8889).
Fix: _clients utilise set() global + difference_update() pour eviter UnboundLocalError
"""
from __future__ import annotations
import asyncio
import json
import threading
import queue

try:
    import websockets
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False
    print("[ws] WARN: websockets non installe -> pip install websockets")

_event_queue: queue.Queue = queue.Queue()
_clients: set = set()
_PORT = 8889


def push_event(event: dict) -> None:
    """Appel synchrone depuis le pipeline."""
    if _WS_AVAILABLE:
        _event_queue.put_nowait(event)


async def _handler(websocket):
    global _clients
    _clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        _clients.discard(websocket)


async def _broadcaster():
    global _clients
    while True:
        await asyncio.sleep(0.05)
        msgs = []
        try:
            while True:
                msgs.append(_event_queue.get_nowait())
        except queue.Empty:
            pass
        if msgs and _clients:
            dead = set()
            for client in list(_clients):
                try:
                    for m in msgs:
                        await client.send(json.dumps(m))
                except Exception:
                    dead.add(client)
            _clients.difference_update(dead)


async def _serve():
    async with websockets.serve(_handler, "0.0.0.0", _PORT):
        print(f"[ws] Monitor WebSocket sur ws://0.0.0.0:{_PORT}")
        await _broadcaster()


def start_in_thread() -> threading.Thread | None:
    if not _WS_AVAILABLE:
        print("[ws] Monitor desactive (websockets manquant)")
        return None
    def run():
        asyncio.run(_serve())
    t = threading.Thread(target=run, daemon=True, name="ws-bridge")
    t.start()
    return t


if __name__ == "__main__":
    asyncio.run(_serve())
