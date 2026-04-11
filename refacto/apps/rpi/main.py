"""
S.T.E.A.M Vision — pipeline principal
======================================
États :
  IDLE        → personne détectée N secondes → INSPECTION
  INSPECTION  → carte losange reconnue        → TRIGGERED
  TRIGGERED   → cooldown écoulé               → IDLE

Config rapide en haut du fichier, pas de fichier YAML nécessaire.
"""
from __future__ import annotations
import argparse, signal, time, socket, random, subprocess, threading
from pathlib import Path
from enum import Enum, auto

import cv2
from picamera2 import Picamera2
from ultralytics import YOLO

from steamcore.recognition.card_detector   import CardDetector
from steamcore.recognition.card_recognizer import CardRecognizer

# ═══════════════════════════════════════════════════════════════
#  CONFIG — modifier ici
# ═══════════════════════════════════════════════════════════════
LOXONE_IP        = "192.168.1.50"
LOXONE_PORT      = 7777
MODEL_PATH       = "yolov8n.pt"
YOLO_IMGSZ       = 320
YOLO_CONF        = 0.5
AUDIO_DIR        = Path("assets/audio")
VIDEO_DIR        = Path("assets/video")
PLATEST_DIR      = "PLATEST"

PERSON_DURATION  = 2.0    # secondes de présence avant inspection
INSPECT_TIMEOUT  = 10.0   # secondes max en mode inspection
CARD_COOLDOWN    = 8.0    # secondes entre deux déclenchements
PERSON_GRACE     = 15     # frames manquées tolérées avant reset timer
# ═══════════════════════════════════════════════════════════════

class State(Enum):
    IDLE       = auto()
    INSPECTION = auto()
    TRIGGERED  = auto()


# ── Utilitaires ───────────────────────────────────────────────

def udp_send(msg: str):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(msg.encode(), (LOXONE_IP, LOXONE_PORT))
        print(f"[udp] → {LOXONE_IP}:{LOXONE_PORT}  {msg}")
    except Exception as e:
        print(f"[udp] ERREUR : {e}")


def audio_play_random(subdir=""):
    folder = AUDIO_DIR / subdir if subdir else AUDIO_DIR
    files  = [p for p in folder.rglob("*.mp3")] if folder.exists() else []
    if not files:
        print(f"[audio] Aucun fichier dans {folder}")
        return
    chosen = random.choice(files)
    print(f"[audio] >> {chosen.name}")
    subprocess.Popen(["mpg123", "-q", str(chosen)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def video_play_random(subdir=""):
    folder = VIDEO_DIR / subdir if subdir else VIDEO_DIR
    exts   = {".mp4",".mkv",".avi",".mov",".webm"}
    files  = [p for p in folder.rglob("*") if p.suffix.lower() in exts] if folder.exists() else []
    if not files:
        print(f"[video] Aucune vidéo dans {folder}")
        return
    chosen = random.choice(files)
    print(f"[video] >> {chosen.name}")
    import os
    env = {**os.environ, "DISPLAY": ":0"}
    subprocess.Popen(["mpv","--fullscreen","--no-terminal","--really-quiet","--no-audio",str(chosen)],
                     env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def heartbeat():
    while True:
        udp_send("STEAM_RUN_OK")
        time.sleep(5)


# ── YOLO personne ─────────────────────────────────────────────

def detect_person(model, frame) -> bool:
    results = model.predict(frame, imgsz=YOLO_IMGSZ, conf=YOLO_CONF, verbose=False)
    for r in results:
        for box in r.boxes:
            if model.names[int(box.cls)] == "person":
                return True
    return False


# ── Carte → actions ───────────────────────────────────────────
#  Définis ici ce que fait chaque carte quand elle est reconnue.
#  Modifie librement.

CARD_ACTIONS = {
    "plate_bougie":   {"udp": "STEAM_CARD_BOUGIE",   "audio": True, "video": True},
    "plate_chaudron": {"udp": "STEAM_CARD_CHAUDRON",  "audio": True, "video": True},
    "plate_vampire":  {"udp": "STEAM_CARD_VAMPIRE",   "audio": True, "video": True},
    "plate_cellule":  {"udp": "STEAM_CARD_CELLULE",   "audio": True, "video": True},
    "plate_dague":    {"udp": "STEAM_CARD_DAGUE",     "audio": True, "video": True},
}

def trigger_card(result):
    actions = CARD_ACTIONS.get(result.card_id, {"udp": result.action, "audio": True})
    if actions.get("audio"):
        threading.Thread(target=audio_play_random, daemon=True).start()
    if actions.get("video"):
        threading.Thread(target=video_play_random, daemon=True).start()
    if actions.get("udp"):
        udp_send(actions["udp"])


# ── Main ──────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  S.T.E.A.M Vision — STYX  |  Pi 5 headless")
    print("=" * 55)
    print(f"  Person   : stable {PERSON_DURATION}s → inspection")
    print(f"  Inspect  : timeout {INSPECT_TIMEOUT}s")
    print(f"  Cooldown : {CARD_COOLDOWN}s après détection")
    print()

    # Chargement modèles
    print("[init] Chargement YOLO...")
    model = YOLO(MODEL_PATH)

    print("[init] Chargement CardDetector + CardRecognizer...")
    card_detector   = CardDetector(min_area=1500)
    card_recognizer = CardRecognizer(PLATEST_DIR)

    # Caméra
    print("[init] Démarrage caméra...")
    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"format": "RGB888", "size": (1280, 720)}
    ))
    cam.start()
    print("[init] Caméra OK")
    print("[run]  Pipeline démarré — IDLE
")

    # Heartbeat UDP
    threading.Thread(target=heartbeat, daemon=True).start()

    # Variables d'état
    state             = State.IDLE
    person_first_seen = 0.0
    person_miss_count = 0
    inspect_start     = 0.0
    last_triggered    = 0.0

    running = True
    def stop(s, f):
        nonlocal running
        print("
[stop] Arrêt propre...")
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    frame_count = 0

    while running:
        frame = cam.capture_array()
        if frame is None:
            time.sleep(0.01)
            continue

        frame_count += 1
        now = time.time()

        # ─── TRIGGERED : attendre cooldown ──────────────────
        if state == State.TRIGGERED:
            if now - last_triggered >= CARD_COOLDOWN:
                state = State.IDLE
                person_first_seen = 0.0
                person_miss_count = 0
                print("[state] → IDLE")
            continue

        # ─── Détection personne ──────────────────────────────
        person_seen = detect_person(model, frame)

        if person_seen:
            person_miss_count = 0
            if person_first_seen == 0.0:
                person_first_seen = now
                print("[person] Joueur détecté, décompte...")
        else:
            person_miss_count += 1
            if person_miss_count >= PERSON_GRACE:
                if person_first_seen > 0.0:
                    print("[person] Joueur parti → reset")
                person_first_seen = 0.0
                person_miss_count = 0
                if state == State.INSPECTION:
                    state = State.IDLE
                    print("[state] INSPECTION → IDLE (joueur parti)")

        # ─── IDLE → INSPECTION ──────────────────────────────
        if state == State.IDLE:
            if person_first_seen > 0.0 and (now - person_first_seen) >= PERSON_DURATION:
                state         = State.INSPECTION
                inspect_start = now
                print("[state] → INSPECTION")
                threading.Thread(target=audio_play_random, daemon=True).start()
            continue

        # ─── INSPECTION : chercher une carte ────────────────
        if state == State.INSPECTION:
            if now - inspect_start > INSPECT_TIMEOUT:
                state = State.IDLE
                person_first_seen = 0.0
                person_miss_count = 0
                print("[state] INSPECTION timeout → IDLE")
                continue

            region = card_detector.detect(frame)
            if region is None:
                continue

            result = card_recognizer.recognize(region.warped)
            if result is None:
                continue

            print(f"[CARD] ✓ {result.label}  score={result.score:.3f}  matches={result.matches}")
            trigger_card(result)
            state          = State.TRIGGERED
            last_triggered = now
            print(f"[state] → TRIGGERED ({CARD_COOLDOWN}s cooldown)")

    cam.stop()
    print(f"[stop] {frame_count} frames traitées.")


if __name__ == "__main__":
    main()
