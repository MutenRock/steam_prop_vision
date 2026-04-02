# udp_test.py  -  test UDP Loxone standalone (sans camera)
# -*- coding: utf-8 -*-
"""
Teste l'envoi UDP vers la Miniserver Loxone independamment du pipeline vision.
Configurer LOXONE_IP et LOXONE_PORT avant de lancer.

Usage:
    python3 udp_test.py
    python3 udp_test.py --ip 192.168.1.50 --port 7777 --msg "CMD:START"
"""
import socket
import argparse
import time

# ── A CONFIGURER ─────────────────────────────────────────────────────────────
LOXONE_IP   = "192.168.1.xx"   # <- IP de ta Miniserver Loxone
LOXONE_PORT = 7777              # <- Port UDP configuré dans Loxone
# ─────────────────────────────────────────────────────────────────────────────

def send_udp(msg: str, ip: str = LOXONE_IP, port: int = LOXONE_PORT) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(2.0)
            s.sendto(msg.encode("utf-8"), (ip, port))
        print(f"[UDP] ✓ {ip}:{port} → '{msg}'")
        return True
    except Exception as e:
        print(f"[UDP] ✗ Erreur: {e}")
        return False

def run_sequence(ip: str, port: int):
    """Sequence de test — verifie dans Loxone que les messages arrivent."""
    messages = [
        "CMD:START",
        "LOXONE:LIGHTS=ON",
        "PLAQUE:plaque_A",
        "PRESENCE:1",
        "CMD:STOP",
    ]
    print(f"\n[UDP] Sequence de test vers {ip}:{port}")
    print("-" * 40)
    for msg in messages:
        send_udp(msg, ip, port)
        time.sleep(0.5)
    print("-" * 40)
    print("[UDP] Sequence terminee. Verifier la Miniserver Loxone.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test UDP Loxone")
    parser.add_argument("--ip",   default=LOXONE_IP,   help="IP Miniserver")
    parser.add_argument("--port", default=LOXONE_PORT, type=int, help="Port UDP")
    parser.add_argument("--msg",  default=None,        help="Message unique a envoyer")
    args = parser.parse_args()

    if args.msg:
        send_udp(args.msg, args.ip, args.port)
    else:
        run_sequence(args.ip, args.port)
