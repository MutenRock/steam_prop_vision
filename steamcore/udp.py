"""
steamcore/udp.py
- send_event()   : envoie un message UDP à Loxone
- broadcast()    : envoie STEAM_RUN_OK en broadcast LAN
- UDPListener    : écoute les ACK/commandes entrants
"""
from __future__ import annotations
import socket
import threading
import time


BROADCAST_PORT = 9999
LOXONE_PORT    = 7777
LISTEN_PORT    = 8888


def send_event(msg: str, ip: str, port: int = LOXONE_PORT) -> None:
    """Envoie un message UDP texte à l'IP:port cible (ex: Loxone)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(msg.encode(), (ip, port))
    print(f"[udp] → {ip}:{port}  {msg}")


def broadcast(msg: str = "STEAM_RUN_OK", port: int = BROADCAST_PORT) -> None:
    """Broadcast UDP sur le LAN."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(msg.encode(), ("<broadcast>", port))


class HeartbeatThread(threading.Thread):
    """Envoie STEAM_RUN_OK en broadcast toutes les `interval` secondes."""
    def __init__(self, interval: float = 5.0):
        super().__init__(daemon=True)
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self):
        print(f"[udp] Heartbeat broadcast STEAM_RUN_OK toutes les {self.interval}s")
        while not self._stop_event.wait(self.interval):
            broadcast("STEAM_RUN_OK")

    def stop(self):
        self._stop_event.set()


class UDPListener(threading.Thread):
    """
    Écoute les messages UDP entrants (ACK Loxone, commandes réseau).
    Appelle on_message(msg: str, addr: tuple) à chaque réception.
    """
    def __init__(self, port: int = LISTEN_PORT, on_message=None):
        super().__init__(daemon=True)
        self.port = port
        self.on_message = on_message or (lambda msg, addr: print(f"[udp] ← {addr} : {msg}"))
        self._stop_event = threading.Event()

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.settimeout(1.0)
            s.bind(("0.0.0.0", self.port))
            print(f"[udp] Écoute sur port {self.port}")
            while not self._stop_event.is_set():
                try:
                    data, addr = s.recvfrom(1024)
                    self.on_message(data.decode().strip(), addr)
                except socket.timeout:
                    continue

    def stop(self):
        self._stop_event.set()
