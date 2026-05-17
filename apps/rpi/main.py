"""
apps/rpi/main.py  —  S.T.E.A.M Vision STYX
Piloté par config/features.yaml

╔══════════════════════════════════════════════════════╗
║  pipeline_mode: "card"   (défaut — lance une vidéo)  ║
║  ─────────────────────────────────────────────────── ║
║  Scan continu de la carte via L1→L2→L3               ║
║  Même carte maintenue card_hold_ms (2000ms) → TRIGGER ║
║  Lecture vidéo + UDP → retour IDLE après idle_after_s ║
║  Pas de YOLO requis                                  ║
╠══════════════════════════════════════════════════════╣
║  pipeline_mode: "person"  (mode spécial — joue MP3)  ║
║  ─────────────────────────────────────────────────── ║
║  YOLO person détecté X secondes → lecture audio      ║
║  → retour IDLE après idle_after_s                    ║
╚══════════════════════════════════════════════════════╝
"""
from __future__ import annotations
import logging
import logging.handlers
import shutil
import signal
import sys
import time
import threading
from pathlib import Path
from enum import Enum, auto

import cv2
import yaml
from picamera2 import Picamera2

from steamcore.audio                       import AudioPlayer
from steamcore.video_player                import VideoPlayer
from steamcore.rules                       import RuleEngine
from steamcore.udp                         import send_event as udp_send_raw, HeartbeatThread, UDPListener
from steamcore.recognition.fast_detector   import FastDetector
from steamcore.recognition.card_detector   import CardDetector
from steamcore.recognition.card_recognizer import CardRecognizer
from monitor.ws_bridge                     import start_in_thread as start_ws, push_event
from monitor.rule_api                      import start_in_thread as start_rule_api

CONFIG_FILE = "config/features.yaml"
LOG_FILE    = "logs/steam_vision.log"


# ── Logging ────────────────────────────────────────────────────────

def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, console])


log = logging.getLogger("steam")


# ── Config ─────────────────────────────────────────────────────────

def load_config():
    p = Path(CONFIG_FILE)
    if not p.exists():
        log.warning("[config] features.yaml introuvable, valeurs par defaut")
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ── Boot checks ────────────────────────────────────────────────────

def boot_checks():
    """Vérifie les dépendances critiques au démarrage. Abort si manquant."""
    errors = []

    # Lecteur vidéo
    players = ["mpv", "ffplay", "vlc"]
    if not any(shutil.which(p) for p in players):
        errors.append("Aucun lecteur vidéo trouvé (mpv / ffplay / vlc). "
                      "Installer avec : sudo apt install mpv")
    else:
        found = next(p for p in players if shutil.which(p))
        log.info(f"[boot] Lecteur vidéo : {found} OK")

    # aplay pour l'audio
    if not shutil.which("aplay") and not shutil.which("mpg123"):
        log.warning("[boot] WARN : aplay et mpg123 introuvables — audio désactivé")

    # PLATEST
    if not Path("PLATEST").exists() or not any(Path("PLATEST").iterdir()):
        errors.append("Dossier PLATEST vide ou absent — aucun template de plate.")
    else:
        plates = [d for d in Path("PLATEST").iterdir() if d.is_dir()]
        log.info(f"[boot] PLATEST : {len(plates)} plate(s) trouvée(s)")

    # config/rules.yaml
    if not Path("config/rules.yaml").exists():
        log.warning("[boot] WARN : config/rules.yaml absent — aucune action ne sera déclenchée")

    if errors:
        for e in errors:
            log.error(f"[boot] ERREUR CRITIQUE : {e}")
        log.error("[boot] Démarrage annulé.")
        sys.exit(1)


class State(Enum):
    IDLE    = auto()
    STANDBY = auto()   # vidéo en cours — aucune détection


# ── Helpers ───────────────────────────────────────────────────────

def udp_send(msg, ip, port):
    """Envoie UDP + pousse l'event sur le monitor WS."""
    try:
        udp_send_raw(msg, ip, port)
    except Exception as e:
        log.error("[udp] ERREUR : " + str(e))
    push_event({"type": "udp_sent", "msg": msg, "ip": ip, "port": port})


def run_actions(cfg, rule_engine, label_or_result, audio, video, card_id=None):
    """
    Dispatche les actions d'une règle (carte ou person).
    label_or_result : RecognitionResult (mode card) ou str (mode person).
    """
    lox_ip   = cfg.get("loxone_ip",   "192.168.1.50")
    lox_port = cfg.get("loxone_port", 7777)

    if hasattr(label_or_result, "card_id"):
        cid   = label_or_result.card_id
        label = label_or_result.label
    else:
        cid   = label_or_result
        label = label_or_result

    actions = rule_engine.get_actions(cid)
    if not actions:
        msg = "STEAM_DETECT_" + cid.upper()
        udp_send(msg, lox_ip, lox_port)
        return

    for action in actions:
        if action.type == "audio" and cfg.get("enable_audio", True):
            threading.Thread(target=audio.play_random,
                             args=(action.subdir,), daemon=True).start()
            push_event({"type": "audio", "card": cid, "subdir": action.subdir})

        elif action.type == "video" and cfg.get("enable_video", True):
            threading.Thread(target=video.play_random,
                             args=(action.subdir,), daemon=True).start()
            push_event({"type": "video", "card": cid, "subdir": action.subdir})

        elif action.type == "image" and cfg.get("enable_video", True):
            from steamcore.image_player import ImagePlayer
            threading.Thread(target=ImagePlayer("assets/img").show_random,
                             args=(action.subdir,), daemon=True).start()
            push_event({"type": "image", "card": cid, "subdir": action.subdir})

        elif action.type == "udp":
            msg = action.message or ("STEAM_DETECT_" + cid.upper())
            udp_send(msg, lox_ip, lox_port)


# ══════════════════════════════════════════════════════════════════
# MODE CARD  —  L1→L2→L3, hold 2s, vidéo
# ══════════════════════════════════════════════════════════════════

def run_card_mode(cfg, cam, rule_engine, audio, video):
    card_hold_ms    = cfg.get("card_hold_ms",          1000)
    idle_after_s    = cfg.get("idle_after_s",           3.0)
    card_min_area   = cfg.get("card_min_area",         4000)
    card_min_match  = cfg.get("card_min_matches",        12)
    card_threshold  = cfg.get("card_score_threshold",  0.20)
    consec_required = cfg.get("card_consec_frames",       5)

    fast_detector = FastDetector(min_area=card_min_area)
    card_detector = CardDetector()
    recognizer    = CardRecognizer("PLATEST",
                                   min_matches=card_min_match,
                                   threshold=card_threshold)

    state          = State.IDLE
    last_triggered = 0.0
    hold_card_id   = None
    hold_start     = 0.0
    consec_card_id = None
    consec_count   = 0
    frame_count    = 0

    log.info("[card] Pipeline card — IDLE (hold=" + str(card_hold_ms) +
             "ms, consec=" + str(consec_required) + ")")
    push_event({"type": "state", "state": "IDLE"})

    running = True
    def _stop(s, f):
        nonlocal running
        running = False
        log.info("[stop] Arret propre...")
    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    def _reset_detection():
        nonlocal hold_card_id, hold_start, consec_card_id, consec_count
        hold_card_id   = None
        hold_start     = 0.0
        consec_card_id = None
        consec_count   = 0

    while running:
        frame = cam.capture_array()
        if frame is None:
            time.sleep(0.01)
            continue
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        frame_count += 1
        now = time.time()

        if state == State.STANDBY:
            elapsed    = now - last_triggered
            video_done = not video.is_playing()
            if video_done and elapsed >= idle_after_s:
                state = State.IDLE
                _reset_detection()
                log.info("[state] -> IDLE")
                push_event({"type": "state", "state": "IDLE"})
            continue

        quad = fast_detector.detect(frame)
        if quad is None:
            if consec_card_id is not None:
                _reset_detection()
            continue

        roi    = quad.crop(frame)
        region = card_detector.detect(roi)
        if region is None:
            if consec_card_id is not None:
                _reset_detection()
            continue

        result = recognizer.recognize(region.warped)
        if result is None:
            if consec_card_id is not None:
                _reset_detection()
            continue

        if result.card_id != consec_card_id:
            consec_card_id = result.card_id
            consec_count   = 1
            hold_card_id   = None
            hold_start     = 0.0
            continue

        consec_count += 1
        if consec_count < consec_required:
            continue

        if hold_card_id is None:
            hold_card_id = result.card_id
            hold_start   = now
            push_event({"type": "card_detected",
                        "card_id": result.card_id,
                        "label":   result.label,
                        "score":   round(result.score, 3)})
            log.info("[card] confirmée (" + str(consec_required) + "f) : " +
                     result.label + "  score=" + str(round(result.score, 3)))

        held_ms = (now - hold_start) * 1000
        pct     = min(100, int(held_ms / card_hold_ms * 100))
        push_event({"type": "hold",
                    "card_id":   result.card_id,
                    "label":     result.label,
                    "pct":       pct,
                    "held_ms":   int(held_ms),
                    "target_ms": card_hold_ms})

        if held_ms < card_hold_ms:
            continue

        log.info("[TRIGGER] " + result.label +
                 "  score=" + str(round(result.score, 3)) +
                 "  hold=" + str(int(held_ms)) + "ms")
        push_event({"type": "state", "state": "STANDBY"})
        run_actions(cfg, rule_engine, result, audio, video)
        state          = State.STANDBY
        last_triggered = now
        _reset_detection()
        log.info("[state] -> STANDBY (" + str(idle_after_s) + "s)")

    log.info("[stop] " + str(frame_count) + " frames traitees.")


# ══════════════════════════════════════════════════════════════════
# MODE PERSON  —  YOLO + audio seulement
# ══════════════════════════════════════════════════════════════════

def run_person_mode(cfg, cam, rule_engine, audio, video):
    from steamcore.detector       import YOLODetector
    from steamcore.person_tracker import PersonTracker, PersonState

    person_duration = cfg.get("person_duration",    2.0)
    persist         = cfg.get("persist_after_loss", 5.0)
    idle_after_s    = cfg.get("idle_after_s",       3.0)

    detector = YOLODetector(
        model_path = cfg.get("yolo_model", "yolov8n.pt"),
        imgsz      = cfg.get("yolo_imgsz", 320),
        conf       = cfg.get("yolo_conf",  0.5),
    )
    tracker = PersonTracker(
        person_duration    = person_duration,
        persist_after_loss = persist,
        grace_frames       = 15,
    )

    state          = State.IDLE
    last_triggered = 0.0
    last_count     = 0.0
    frame_count    = 0

    log.info("[person] Pipeline person — IDLE (duration=" + str(person_duration) + "s)")
    push_event({"type": "state", "state": "IDLE"})

    running = True
    def _stop(s, f):
        nonlocal running
        running = False
        log.info("[stop] Arret propre...")
    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    while running:
        frame = cam.capture_array()
        if frame is None:
            time.sleep(0.01)
            continue
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        frame_count += 1
        now = time.time()

        if state == State.STANDBY:
            if now - last_triggered >= idle_after_s:
                state = State.IDLE
                tracker.reset()
                log.info("[state] -> IDLE")
                push_event({"type": "state", "state": "IDLE"})
            continue

        pf = detector.detect_persons(frame)
        ts = tracker.update(pf)

        if now - last_count > 3.0 and pf.count > 0:
            push_event({"type": "count", "value": pf.count})
            last_count = now

        if ts.ready_for_inspect and state == State.IDLE:
            log.info("[person] Joueur détecté depuis " +
                     str(round(ts.presence_elapsed, 1)) + "s -> TRIGGER")
            push_event({"type": "state", "state": "STANDBY"})
            run_actions(cfg, rule_engine, "person", audio, video)
            state          = State.STANDBY
            last_triggered = now
            log.info("[state] -> STANDBY (" + str(idle_after_s) + "s)")

    log.info("[stop] " + str(frame_count) + " frames traitees.")


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

def main():
    setup_logging()
    boot_checks()   # ← vérifie mpv, PLATEST, rules.yaml — abort si critique

    cfg = load_config()

    pipeline_mode = cfg.get("pipeline_mode", "card")
    monitor_on    = cfg.get("enable_monitor",   True)
    rule_api_on   = cfg.get("enable_rule_api",  True)
    heartbeat_on  = cfg.get("enable_heartbeat", True)
    listen_port   = cfg.get("udp_listen_port",  8888)

    log.info("=" * 55)
    log.info("  S.T.E.A.M Vision — STYX  |  Pi 5")
    log.info("=" * 55)
    log.info("  Mode        : " + pipeline_mode.upper())
    if pipeline_mode == "card":
        log.info("  Hold        : " + str(cfg.get("card_hold_ms", 2000)) + "ms")
    log.info("  Idle after  : " + str(cfg.get("idle_after_s", 3.0)) + "s")
    log.info("  Monitor WS  : " + ("ON :8889" if monitor_on else "OFF"))
    log.info("  Rule API    : " + ("ON :8890" if rule_api_on else "OFF"))

    rule_engine = RuleEngine("config/rules.yaml")
    audio       = AudioPlayer("assets/audio")
    video       = VideoPlayer("assets/video")

    if monitor_on:
        start_ws()
    if rule_api_on:
        start_rule_api(engine=rule_engine)
    if heartbeat_on:
        HeartbeatThread(interval=5.0).start()

    UDPListener(port=listen_port, on_message=lambda msg, addr: (
        log.info("[UDP RX] " + addr[0] + " -> " + msg),
        push_event({"type": "udp_rx", "msg": msg, "from": addr[0]})
    )).start()

    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"format": "RGB888",
              "size": (cfg.get("camera_width",  1280),
                       cfg.get("camera_height", 720))}
    ))
    cam.start()
    log.info("[init] Camera OK")

    if pipeline_mode == "person":
        run_person_mode(cfg, cam, rule_engine, audio, video)
    else:
        run_card_mode(cfg, cam, rule_engine, audio, video)

    cam.stop()
    audio.stop()
    video.stop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("[main] Interruption clavier — arrêt propre.")
    except Exception as e:
        logging.exception("[main] CRASH NON GÉRÉ — voir logs/steam_vision.log")
        sys.exit(1)
