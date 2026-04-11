"""
apps/rpi/main_gui.py  —  S.T.E.A.M Vision STYX  (mode GUI fullscreen)
Même pipeline que main.py, MAIS affiche une interface fullscreen sur le
display HDMI du Pi (ou de tout PC Linux/Windows avec écran).

Architecture :
  ┌─────────────────────────────────────────────────────┐
  │  Worker thread  : camera → L1→L2→L3 → display_state │
  │  Main   thread  : OpenCV window → draw @ ~30 fps     │
  └─────────────────────────────────────────────────────┘

Usage :
  python apps/rpi/main_gui.py
  DISPLAY=:0 python apps/rpi/main_gui.py   # forcer display Pi
"""
from __future__ import annotations
import os
import math
import signal
import threading
import time
from enum import Enum, auto
from pathlib import Path

# ── forcer le display X11 si variable absente (Pi sans session graphique ouverte)
os.environ.setdefault("DISPLAY", ":0")

import cv2
import numpy as np
import yaml

# ── steamcore ─────────────────────────────────────────────────────────────────
from steamcore.audio                       import AudioPlayer
from steamcore.video_player                import VideoPlayer
from steamcore.rules                       import RuleEngine
from steamcore.udp                         import send_event as udp_send_raw, HeartbeatThread, UDPListener
from steamcore.recognition.fast_detector   import FastDetector
from steamcore.recognition.card_detector   import CardDetector
from steamcore.recognition.card_recognizer import CardRecognizer
from monitor.ws_bridge                     import start_in_thread as start_ws, push_event
from monitor.rule_api                      import start_in_thread as start_rule_api

# ── constantes fenêtre ────────────────────────────────────────────────────────
WIN_NAME   = "S.T.E.A.M Vision"
WIN_W, WIN_H = 1280, 720

CONFIG_FILE = "config/features.yaml"


# ══════════════════════════════════════════════════════════════════════════════
# État partagé worker → main thread
# ══════════════════════════════════════════════════════════════════════════════

class Screen(Enum):
    IDLE          = auto()
    HOLD          = auto()
    TRIGGER_FLASH = auto()
    STANDBY       = auto()


_state_lock = threading.Lock()
display_state: dict = {
    "screen":     Screen.IDLE,
    "card_label": "",
    "card_score": 0.0,
    "hold_pct":   0,
    "hold_ms":    0,
    "flash_start": 0.0,
}


def _set_state(**kwargs):
    with _state_lock:
        display_state.update(kwargs)


def _get_state() -> dict:
    with _state_lock:
        return dict(display_state)


# ══════════════════════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════════════════════

def load_config() -> dict:
    p = Path(CONFIG_FILE)
    if not p.exists():
        print("[config] features.yaml introuvable, valeurs par defaut")
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ══════════════════════════════════════════════════════════════════════════════
# Helpers UDP / actions  (identiques à main.py)
# ══════════════════════════════════════════════════════════════════════════════

def udp_send(msg: str, ip: str, port: int):
    try:
        udp_send_raw(msg, ip, port)
    except Exception as e:
        print("[udp] ERREUR : " + str(e))
    push_event({"type": "udp_sent", "msg": msg, "ip": ip, "port": port})


def run_actions(cfg: dict, rule_engine: RuleEngine,
                label_or_result, audio: AudioPlayer, video: VideoPlayer):
    lox_ip   = cfg.get("loxone_ip",   "192.168.1.50")
    lox_port = cfg.get("loxone_port", 7777)

    if hasattr(label_or_result, "card_id"):
        cid   = label_or_result.card_id
    else:
        cid   = label_or_result

    actions = rule_engine.get_actions(cid)
    if not actions:
        udp_send("STEAM_DETECT_" + cid.upper(), lox_ip, lox_port)
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


# ══════════════════════════════════════════════════════════════════════════════
# Worker thread  —  pipeline caméra
# ══════════════════════════════════════════════════════════════════════════════

class PipelineState(Enum):
    IDLE    = auto()
    STANDBY = auto()


def worker_card_mode(cfg: dict, cam, rule_engine: RuleEngine,
                     audio: AudioPlayer, video: VideoPlayer,
                     stop_event: threading.Event):
    """Tourne dans un thread daemon. Écrit dans display_state."""
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

    pipe_state     = PipelineState.IDLE
    last_triggered = 0.0
    hold_card_id   = None     # carte confirmée en cours de hold
    hold_start     = 0.0
    consec_card_id = None     # carte vue en frames consécutives
    consec_count   = 0
    frame_count    = 0

    print("[worker] Pipeline card — IDLE (hold=" + str(card_hold_ms) +
          "ms, consec=" + str(consec_required) + ")")
    push_event({"type": "state", "state": "IDLE"})
    _set_state(screen=Screen.IDLE, card_label="", hold_pct=0)

    def _reset_detection():
        nonlocal hold_card_id, hold_start, consec_card_id, consec_count
        hold_card_id   = None
        hold_start     = 0.0
        consec_card_id = None
        consec_count   = 0

    while not stop_event.is_set():
        frame = cam.capture_array()
        if frame is None:
            time.sleep(0.01)
            continue
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        frame_count += 1
        now = time.time()

        # ── STANDBY : vidéo en cours ──────────────────────────
        if pipe_state == PipelineState.STANDBY:
            elapsed    = now - last_triggered
            video_done = not video.is_playing()
            if video_done and elapsed >= idle_after_s:
                pipe_state = PipelineState.IDLE
                _reset_detection()
                print("[state] -> IDLE")
                push_event({"type": "state", "state": "IDLE"})
                _set_state(screen=Screen.IDLE, card_label="", hold_pct=0)
            continue

        # ── L1 : détection losange ────────────────────────────
        quad = fast_detector.detect(frame)
        if quad is None:
            if consec_card_id is not None:
                _reset_detection()
                _set_state(screen=Screen.IDLE, card_label="", hold_pct=0)
            continue

        # ── L2 : ORB/SIFT sur ROI ────────────────────────────
        roi    = quad.crop(frame)
        region = card_detector.detect(roi)
        if region is None:
            if consec_card_id is not None:
                _reset_detection()
                _set_state(screen=Screen.IDLE, card_label="", hold_pct=0)
            continue

        # ── L3 : confirmation ─────────────────────────────────
        result = recognizer.recognize(region.warped)
        if result is None:
            if consec_card_id is not None:
                _reset_detection()
                _set_state(screen=Screen.IDLE, card_label="", hold_pct=0)
            continue

        # ── Compteur frames consécutives ──────────────────────
        if result.card_id != consec_card_id:
            consec_card_id = result.card_id
            consec_count   = 1
            hold_card_id   = None
            hold_start     = 0.0
            continue                # pas encore confirmée

        consec_count += 1
        if consec_count < consec_required:
            continue                # en attente de confirmation

        # ── Carte confirmée (consec_required frames d'affilée) ─
        if hold_card_id is None:
            hold_card_id = result.card_id
            hold_start   = now
            push_event({"type": "card_detected",
                        "card_id": result.card_id,
                        "label":   result.label,
                        "score":   round(result.score, 3)})
            print("[card] confirmée (" + str(consec_required) + "f) : " +
                  result.label + "  score=" + str(round(result.score, 3)))
            _set_state(screen=Screen.HOLD,
                       card_label=result.label,
                       card_score=result.score,
                       hold_pct=0, hold_ms=0)

        # ── Hold timer ────────────────────────────────────────
        held_ms = (now - hold_start) * 1000
        pct     = min(100, int(held_ms / card_hold_ms * 100))
        push_event({"type": "hold",
                    "card_id":   result.card_id,
                    "label":     result.label,
                    "pct":       pct,
                    "held_ms":   int(held_ms),
                    "target_ms": card_hold_ms})
        _set_state(screen=Screen.HOLD,
                   card_label=result.label,
                   card_score=result.score,
                   hold_pct=pct, hold_ms=int(held_ms))

        if held_ms < card_hold_ms:
            continue

        # ── TRIGGER ───────────────────────────────────────────
        print("[TRIGGER] " + result.label +
              "  score=" + str(round(result.score, 3)) +
              "  hold=" + str(int(held_ms)) + "ms")
        _set_state(screen=Screen.TRIGGER_FLASH,
                   card_label=result.label,
                   card_score=result.score,
                   flash_start=time.monotonic())
        push_event({"type": "state", "state": "STANDBY"})
        run_actions(cfg, rule_engine, result, audio, video)
        pipe_state     = PipelineState.STANDBY
        last_triggered = now
        _reset_detection()
        print("[state] -> STANDBY (" + str(idle_after_s) + "s)")

        # Attendre fin du flash avant de passer l'état à STANDBY côté GUI
        time.sleep(0.40)
        _set_state(screen=Screen.STANDBY)

    print("[worker] " + str(frame_count) + " frames traitees.")


# ══════════════════════════════════════════════════════════════════════════════
# Rendu graphique  —  fonctions de dessin
# ══════════════════════════════════════════════════════════════════════════════

# Palette
C_BLACK  = (0,   0,   0)
C_WHITE  = (255, 255, 255)
C_CYAN   = (255, 220,  20)   # BGR → teinte dorée chaleureuse
C_STEAM  = ( 20, 200, 200)   # cyan vif
C_DIM    = ( 40,  40,  40)
C_RED    = ( 30,  30, 200)
C_GREEN  = ( 30, 200,  80)

FONT      = cv2.FONT_HERSHEY_DUPLEX
FONT_THIN = cv2.FONT_HERSHEY_SIMPLEX


def build_vignette_mask(w: int, h: int) -> np.ndarray:
    """Masque float32 [0-1] sombre sur les bords, clair au centre."""
    cx, cy = w / 2, h / 2
    Y, X   = np.ogrid[:h, :w]
    dist   = np.sqrt(((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2)
    mask   = np.clip(1.0 - dist * 0.75, 0.0, 1.0).astype(np.float32)
    return mask[:, :, np.newaxis]   # shape (H,W,1) pour broadcast BGR


def _apply_vignette(canvas: np.ndarray, mask: np.ndarray):
    canvas[:] = (canvas.astype(np.float32) * mask).astype(np.uint8)


def _center_text(canvas, text: str, y: int,
                 font=FONT, scale: float = 1.0,
                 color=(255, 255, 255), thickness: int = 1):
    (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
    x = (WIN_W - tw) // 2
    cv2.putText(canvas, text, (x, y), font, scale, color, thickness, cv2.LINE_AA)


# ── IDLE ──────────────────────────────────────────────────────────────────────

def draw_idle(canvas: np.ndarray, vignette: np.ndarray):
    canvas[:] = 10   # fond quasi noir
    t  = time.monotonic()

    # Anneau pulsant central
    cx, cy = WIN_W // 2, WIN_H // 2
    pulse  = 0.5 + 0.5 * math.sin(t * 1.8)           # 0→1
    radius = int(90 + 18 * pulse)
    alpha  = int(60 + 80 * pulse)
    cv2.circle(canvas, (cx, cy), radius,
               (alpha, alpha, alpha), 2, cv2.LINE_AA)
    cv2.circle(canvas, (cx, cy), radius - 12,
               (alpha // 2, alpha // 2, alpha // 2), 1, cv2.LINE_AA)

    # Croix centrale fine
    cv2.line(canvas, (cx - 20, cy), (cx + 20, cy), (70, 70, 70), 1)
    cv2.line(canvas, (cx, cy - 20), (cx, cy + 20), (70, 70, 70), 1)

    # Marques de coin
    L, T = 30, 2
    for (ox, oy) in [(30, 30), (WIN_W - 30, 30),
                     (30, WIN_H - 30), (WIN_W - 30, WIN_H - 30)]:
        sx = 1 if ox < WIN_W // 2 else -1
        sy = 1 if oy < WIN_H // 2 else -1
        cv2.line(canvas, (ox, oy), (ox + sx * L, oy), (80, 80, 80), T)
        cv2.line(canvas, (ox, oy), (ox, oy + sy * L), (80, 80, 80), T)

    # Texte discret
    _center_text(canvas, "APPROCHEZ LA CARTE",
                 WIN_H // 2 + 160, FONT_THIN, 0.55, (60, 60, 60), 1)

    _apply_vignette(canvas, vignette)


# ── HOLD ──────────────────────────────────────────────────────────────────────

def draw_hold(canvas: np.ndarray, vignette: np.ndarray,
              label: str, score: float, pct: int, held_ms: int):
    canvas[:] = 5
    cx, cy = WIN_W // 2, WIN_H // 2

    # Nom de la carte
    _center_text(canvas, label.upper(),
                 cy - 60, FONT, 1.6, (200, 200, 200), 2)

    # Score
    score_txt = "score " + str(round(score, 3))
    _center_text(canvas, score_txt, cy - 20, FONT_THIN, 0.5, (80, 80, 80), 1)

    # Barre de progression
    bar_w, bar_h = 500, 14
    bx = (WIN_W - bar_w) // 2
    by = cy + 50
    cv2.rectangle(canvas, (bx, by), (bx + bar_w, by + bar_h),
                  (40, 40, 40), -1)
    fill = int(bar_w * pct / 100)
    if fill > 0:
        # Dégradé cyan → blanc selon avancement
        b = int(200 + 55 * (pct / 100))
        g = int(180 + 75 * (pct / 100))
        r = int(20  + 80 * (pct / 100))
        cv2.rectangle(canvas, (bx, by), (bx + fill, by + bar_h),
                      (b, g, r), -1)
    # Contour barre
    cv2.rectangle(canvas, (bx, by), (bx + bar_w, by + bar_h),
                  (100, 100, 100), 1)

    # Temps restant
    target_ms  = max(1, int(held_ms / max(pct, 1) * 100)) if pct else 2000
    remain_s   = max(0, (target_ms - held_ms) / 1000)
    remain_txt = "Maintenez... " + str(round(remain_s, 1)) + "s"
    _center_text(canvas, remain_txt, by + 45, FONT_THIN, 0.55, (120, 120, 120), 1)

    # Cercle indicateur
    t      = time.monotonic()
    pulse  = 0.5 + 0.5 * math.sin(t * 4.0)
    alpha  = int(100 + 80 * pulse)
    cv2.circle(canvas, (cx, cy - 140), 8, (alpha, alpha, alpha), -1, cv2.LINE_AA)

    _apply_vignette(canvas, vignette)


# ── TRIGGER FLASH ─────────────────────────────────────────────────────────────

def draw_trigger_flash(canvas: np.ndarray, label: str, flash_start: float):
    elapsed = time.monotonic() - flash_start

    if elapsed < 0.12:
        # Phase 1 : blanc total qui s'estompe
        fade = 1.0 - (elapsed / 0.12)
        v    = int(255 * fade)
        canvas[:] = v

    else:
        # Phase 2 : fond sombre + lueur cyan centrée
        progress = min(1.0, (elapsed - 0.12) / 0.23)   # 0→1 sur 230ms
        canvas[:] = 0
        cx, cy = WIN_W // 2, WIN_H // 2
        # Cercle rayonnant
        r     = int(30 + 200 * progress)
        alpha = int(255 * (1.0 - progress))
        cv2.circle(canvas, (cx, cy), r, (alpha, int(alpha * 0.9), 0), -1, cv2.LINE_AA)
        # Texte
        a_txt = max(0, int(255 * (progress - 0.3) / 0.7))
        if a_txt > 0:
            _center_text(canvas, label.upper(), cy - 20, FONT, 1.8,
                         (a_txt, a_txt, a_txt), 2)
            _center_text(canvas, "DÉTECTÉE !", cy + 40, FONT_THIN, 0.8,
                         (0, a_txt, a_txt), 1)


# ── STANDBY ───────────────────────────────────────────────────────────────────

def draw_standby(canvas: np.ndarray, label: str):
    canvas[:] = 0
    # Texte très discret
    _center_text(canvas, label.upper() if label else "",
                 WIN_H // 2 - 20, FONT_THIN, 0.6, (25, 25, 25), 1)
    _center_text(canvas, "en cours de lecture...",
                 WIN_H // 2 + 20, FONT_THIN, 0.45, (25, 25, 25), 1)


# ══════════════════════════════════════════════════════════════════════════════
# Main  —  boucle principale (thread principal = thread OpenCV)
# ══════════════════════════════════════════════════════════════════════════════

def main():
    cfg = load_config()

    pipeline_mode = cfg.get("pipeline_mode",    "card")
    monitor_on    = cfg.get("enable_monitor",    True)
    rule_api_on   = cfg.get("enable_rule_api",   True)
    heartbeat_on  = cfg.get("enable_heartbeat",  True)
    listen_port   = cfg.get("udp_listen_port",   8888)

    print("=" * 55)
    print("  S.T.E.A.M Vision — STYX GUI  |  Pi 5")
    print("=" * 55)
    print("  Mode        : " + pipeline_mode.upper())
    print("  Hold        : " + str(cfg.get("card_hold_ms", 2000)) + "ms")
    print("  Idle after  : " + str(cfg.get("idle_after_s", 3.0)) + "s")
    print("  Monitor WS  : " + ("ON :8889" if monitor_on else "OFF"))
    print("  Rule API    : " + ("ON :8890" if rule_api_on else "OFF"))
    print()

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
        print("[UDP RX] " + addr[0] + " -> " + msg),
        push_event({"type": "udp_rx", "msg": msg, "from": addr[0]})
    )).start()

    # ── Caméra ────────────────────────────────────────────────
    from picamera2 import Picamera2
    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"format": "RGB888",
              "size": (cfg.get("camera_width",  1280),
                       cfg.get("camera_height",  720))}
    ))
    cam.start()
    print("[init] Camera OK")

    # ── Worker thread ─────────────────────────────────────────
    stop_event = threading.Event()

    def _stop(s, f):
        stop_event.set()
        print("[stop] Arret propre...")
    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    worker = threading.Thread(
        target=worker_card_mode,
        args=(cfg, cam, rule_engine, audio, video, stop_event),
        daemon=True, name="pipeline-worker"
    )
    worker.start()

    # ── Fenêtre OpenCV fullscreen ─────────────────────────────
    cv2.namedWindow(WIN_NAME, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(WIN_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.moveWindow(WIN_NAME, 0, 0)

    canvas   = np.zeros((WIN_H, WIN_W, 3), dtype=np.uint8)
    vignette = build_vignette_mask(WIN_W, WIN_H)

    print("[gui] Fenêtre ouverte — ESC ou Q pour quitter")

    while not stop_event.is_set():
        st = _get_state()

        if st["screen"] == Screen.IDLE:
            draw_idle(canvas, vignette)

        elif st["screen"] == Screen.HOLD:
            draw_hold(canvas, vignette,
                      st["card_label"], st["card_score"],
                      st["hold_pct"],   st["hold_ms"])

        elif st["screen"] == Screen.TRIGGER_FLASH:
            draw_trigger_flash(canvas, st["card_label"], st["flash_start"])

        elif st["screen"] == Screen.STANDBY:
            draw_standby(canvas, st["card_label"])

        cv2.imshow(WIN_NAME, canvas)
        key = cv2.waitKey(33) & 0xFF   # ~30 fps
        if key in (27, ord("q"), ord("Q")):   # ESC ou Q
            stop_event.set()

    # ── Nettoyage ─────────────────────────────────────────────
    cv2.destroyAllWindows()
    cam.stop()
    audio.stop()
    video.stop()
    print("[gui] Fin.")


if __name__ == "__main__":
    main()
