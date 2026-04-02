"""
monitor/ws_bridge.py
Serveur WebSocket léger (port 8889) qui relaie les événements
du pipeline vers la page monitor/index.html.

Pas de Flask. Dépendance unique : websockets
  pip install websockets

Usage : lancé automatiquement par apps/rpi/main.py si --monitor actif.
Ou manuellement : python monitor/ws_bridge.py
"""
from __future__ import annotations
import asyncio
import json
import threading
import queue
from typing import Set

import websockets


_event_queue: queue.Queue = queue.Queue()
_clients: Set = set()
_PORT = 8889


def push_event(event: dict) -> None:
    """Appel synchrone depuis le pipeline pour pousser un event."""
    _event_queue.put_nowait(event)


async def _handler(websocket):
    _clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        _clients.discard(websocket)


async def _broadcaster():
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
            _clients -= dead


async def _serve():
    async with websockets.serve(_handler, "0.0.0.0", _PORT):
        print(f"[ws] Monitor WebSocket sur ws://0.0.0.0:{_PORT}")
        await _broadcaster()


def start_in_thread() -> threading.Thread:
    """Lance le serveur WS dans un thread daemon (appel depuis main.py)."""
    def run():
        asyncio.run(_serve())
    t = threading.Thread(target=run, daemon=True, name="ws-bridge")
    t.start()
    return t


if __name__ == "__main__":
    asyncio.run(_serve())
