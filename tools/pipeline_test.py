"""
tools/pipeline_test.py
Mini pipeline interactif pour calibration et debug.

Lance depuis le repo :
  python tools/pipeline_test.py

Detection auto camera : picamera2 (Pi) ou webcam (PC/dev).
"""
from __future__ import annotations
import sys
import time
import socket
import yaml
import cv2
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from steamcore.recognition.card_detector   import CardDetector
from steamcore.recognition.card_recognizer import CardRecognizer, RecognitionResult

CONFIG_FILE = "config/features.yaml"
PLATEST_DIR = "PLATEST"

# ── Couleurs overlay ──────────────────────────────────────────
GREEN   = (80,  220, 80)
ORANGE  = (0,   160, 255)
RED     = (60,  60,  220)
GRAY    = (170, 170, 170)
WHITE   = (255, 255, 255)
BLACK   = (0,   0,   0)
GOLD    = (0,   200, 220)


# ═══════════════════════════════════════════════════════════════
#  MENU INTERACTIF
# ═══════════════════════════════════════════════════════════════

def ask(question, choices: list[tuple[str, str]]) -> str:
    print()
    print("  " + question)
    for key, label in choices:
        print("    [" + key + "] " + label)
    while True:
        rep = input("  > ").strip().lower()
        if rep in [k for k, _ in choices]:
            return rep
        print("  Choix invalide.")


def menu():
    print()
    print("=" * 55)
    print("  S.T.E.A.M Vision -- Pipeline Test")
    print("=" * 55)

    mode = ask("Mode ?", [
        ("run", "RUN  -- Pipeline normal (production)"),
        ("dev", "DEV  -- Preview camera + analyse losange + scores"),
        ("cal", "CALIBRATION -- Ajuster parametres et les sauvegarder"),
    ])

    camera = ask("Source camera ?", [
        ("pi",  "Raspberry Pi (picamera2)"),
        ("web", "Webcam locale (OpenCV, index 0)"),
    ])

    cfg = load_config()

    if mode == "dev":
        show_warp = ask("Afficher le warp 400x400 (carte redressee) ?", [
            ("o", "Oui"),
            ("n", "Non"),
        ]) == "o"
        show_scores = ask("Afficher scores toutes les cartes ?", [
            ("o", "Oui"),
            ("n", "Non"),
        ]) == "o"
        return mode, camera, cfg, {"show_warp": show_warp, "show_scores": show_scores}

    if mode == "cal":
        print()
        print("  Parametres actuels :")
        for k in ["card_min_area","card_min_matches","card_score_threshold",
                  "require_person","card_first","persist_after_loss"]:
            print("    " + k + " = " + str(cfg.get(k,"")))
        print()
        print("  Entrer nouveau card_min_matches (Enter = garder " +
              str(cfg.get("card_min_matches", 12)) + ") :", end=" ")
        v = input().strip()
        if v:
            cfg["card_min_matches"] = int(v)
        print("  Entrer nouveau card_score_threshold (Enter = garder " +
              str(cfg.get("card_score_threshold", 0.08)) + ") :", end=" ")
        v = input().strip()
        if v:
            cfg["card_score_threshold"] = float(v)
        save_config(cfg)
        print("  Config sauvegardee.")
        return "dev", camera, cfg, {"show_warp": True, "show_scores": True}

    return mode, camera, cfg, {}


def load_config():
    p = Path(CONFIG_FILE)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config(cfg):
    Path(CONFIG_FILE).parent.mkdir(exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ═══════════════════════════════════════════════════════════════
#  CAMERA
# ═══════════════════════════════════════════════════════════════

def make_camera(source: str):
    if source == "pi":
        try:
            from picamera2 import Picamera2
            cam = Picamera2()
            cam.configure(cam.create_preview_configuration(
                main={"format": "RGB888", "size": (1280, 720)}
            ))
            cam.start()
            time.sleep(0.5)
            return "pi", cam
        except Exception as e:
            print("[cam] picamera2 indisponible : " + str(e) + " -> fallback webcam")

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    return "web", cap


def read_frame(cam_type, cam):
    if cam_type == "pi":
        f = cam.capture_array()
        return (f is not None), f
    else:
        return cam.read()


def stop_camera(cam_type, cam):
    if cam_type == "pi":
        cam.stop()
    else:
        cam.release()


# ═══════════════════════════════════════════════════════════════
#  OVERLAY HELPERS
# ═══════════════════════════════════════════════════════════════

def put(img, text, pos, color=WHITE, scale=0.55, thickness=1):
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, thickness, cv2.LINE_AA)


def draw_scores(frame, all_scores: list[tuple[str, float, int]], best_id: str | None):
    """Panneau scores en haut a droite."""
    x0, y0 = frame.shape[1] - 260, 10
    panel_h = 20 + len(all_scores) * 24 + 10
    overlay = frame.copy()
    cv2.rectangle(overlay, (x0-5, y0-5),
                  (frame.shape[1]-5, y0 + panel_h), BLACK, -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    put(frame, "Scores ORB", (x0, y0+14), GOLD, 0.5, 1)
    for i, (cid, score, matches) in enumerate(all_scores):
        y  = y0 + 34 + i*24
        color = GREEN if cid == best_id else GRAY
        bar_w = int(min(score * 1000, 160))
        cv2.rectangle(frame, (x0, y-10), (x0 + bar_w, y+2), color, -1)
        name  = cid.replace("plate_", "")[:10]
        label = name + "  " + str(round(score, 3)) + " (" + str(matches) + ")"
        put(frame, label, (x0 + bar_w + 5, y), color, 0.45)


def draw_diamond(frame, region, result):
    corners = region.corners.astype(np.int32)
    color   = GREEN if result else ORANGE
    cv2.polylines(frame, [corners], True, color, 2)
    for pt in corners:
        cv2.circle(frame, tuple(pt), 5, color, -1)
    cx = int(corners[:, 0].mean())
    cy = int(corners[:, 1].mean())
    if result:
        put(frame, result.label, (cx - 50, cy - 10), GREEN, 0.7, 2)
        put(frame, "score=" + str(round(result.score, 3)), (cx - 50, cy + 15), GREEN, 0.5)
    else:
        put(frame, "Losange detecte", (cx - 60, cy), ORANGE, 0.55)


def draw_hud(frame, fps, state_txt, person_count):
    put(frame, "FPS: " + str(round(fps, 1)), (10, 25), GRAY, 0.55)
    put(frame, "Etat: " + state_txt, (10, 50), WHITE, 0.6, 1)
    if person_count > 0:
        put(frame, "Joueurs: " + str(person_count), (10, 75), GREEN, 0.55)
    put(frame, "Q=quitter  R=reload  S=snapshot", (10, frame.shape[0]-10), GRAY, 0.45)


# ═══════════════════════════════════════════════════════════════
#  BOUCLES
# ═══════════════════════════════════════════════════════════════

def run_dev(cam_type, cam, cfg, opts):
    """Mode DEV -- preview cam + analyse en temps reel."""
    detector   = CardDetector(min_area=cfg.get("card_min_area", 1500))
    recognizer = CardRecognizer(
        PLATEST_DIR,
        min_matches=cfg.get("card_min_matches", 12),
        threshold=cfg.get("card_score_threshold", 0.08),
    )

    show_warp   = opts.get("show_warp",   True)
    show_scores = opts.get("show_scores", True)

    # Detection personne rapide (optionnelle)
    try:
        from ultralytics import YOLO
        yolo = YOLO(cfg.get("yolo_model", "yolov8n.pt"))
        use_yolo = True
        print("[dev] YOLO charge")
    except Exception:
        yolo     = None
        use_yolo = False
        print("[dev] YOLO non disponible -- comptage desactive")

    print("[dev] DEV mode demarre -- touches : Q quitter | R recharger | S snapshot")
    print()

    prev_time   = time.time()
    snap_count  = 0
    last_result = None
    last_scores = []

    while True:
        ok, frame = read_frame(cam_type, cam)
        if not ok or frame is None:
            continue

        # BGR pour OpenCV si picamera2 (RGB)
        display = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR) if cam_type == "pi" else frame.copy()
        now     = time.time()
        fps     = 1.0 / max(now - prev_time, 0.001)
        prev_time = now

        # Comptage joueurs
        person_count = 0
        if use_yolo:
            results = yolo.predict(frame, imgsz=320, conf=0.5, verbose=False)
            for r in results:
                for box in r.boxes:
                    if yolo.names[int(box.cls)] == "person":
                        person_count += 1
                        x1,y1,x2,y2 = [int(v) for v in box.xyxy[0]]
                        cv2.rectangle(display, (x1,y1),(x2,y2), (200,200,60), 1)

        # Detection losange
        region = detector.detect(frame if cam_type == "pi" else cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        result = None
        scores = []

        if region is not None:
            result = recognizer.recognize(region.warped)
            # Scores toutes les cartes pour affichage
            if show_scores:
                gray_w = cv2.cvtColor(region.warped, cv2.COLOR_BGR2GRAY)                          if len(region.warped.shape)==3 else region.warped
                gray_w = cv2.resize(gray_w, (400, 400))
                orb    = cv2.ORB_create(nfeatures=800)
                matcher= cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
                kps_q, desc_q = orb.detectAndCompute(gray_w, None)
                if desc_q is not None:
                    for t in recognizer._templates:
                        top_s, top_m = 0.0, 0
                        for kps_r, desc_r in t.descs:
                            ms   = matcher.knnMatch(desc_q, desc_r, k=2)
                            good = [m for m,n in ms if m.distance < 0.75*n.distance]
                            s    = len(good)/max(len(kps_r),len(kps_q),1)
                            if s > top_s:
                                top_s, top_m = s, len(good)
                        scores.append((t.id, top_s, top_m))
                    scores.sort(key=lambda x: -x[1])
                    last_scores = scores

            draw_diamond(display, region, result)

            if show_warp:
                warp_disp = cv2.resize(region.warped, (200, 200))
                display[10:210, 10:210] = warp_disp

        best_id = result.card_id if result else None
        if show_scores and last_scores:
            draw_scores(display, last_scores, best_id)

        state_txt = ("CARTE: " + result.label) if result else ("Losange" if region else "Scan...")
        draw_hud(display, fps, state_txt, person_count)

        cv2.imshow("S.T.E.A.M -- DEV", display)
        key = cv2.waitKey(1) & 0xFF

        if key in (ord("q"), 27):
            break
        elif key == ord("r"):
            recognizer.reload()
            print("[dev] Templates recharges")
        elif key == ord("s"):
            snap_count += 1
            fname = "snapshot_" + str(snap_count).zfill(3) + ".jpg"
            cv2.imwrite(fname, display)
            if region is not None:
                cv2.imwrite("warp_" + str(snap_count).zfill(3) + ".jpg", region.warped)
            print("[dev] Snapshot -> " + fname)

    cv2.destroyAllWindows()


def run_pipeline(cam_type, cam, cfg):
    """Mode RUN -- pipeline normal sans affichage."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "main", str(Path(__file__).parent.parent / "apps/rpi/main.py"))
    print("[run] Lancement pipeline normal...")
    print("      (Ctrl+C pour arreter)")
    try:
        import subprocess, sys
        subprocess.run([sys.executable, "apps/rpi/main.py"], check=True)
    except KeyboardInterrupt:
        pass


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mode, camera_src, cfg, opts = menu()
    cam_type, cam = make_camera(camera_src)
    print()
    print("[cam] Camera prete (" + cam_type + ")")

    try:
        if mode in ("dev", "cal"):
            run_dev(cam_type, cam, cfg, opts)
        else:
            run_pipeline(cam_type, cam, cfg)
    finally:
        stop_camera(cam_type, cam)
        print("[exit] Fermeture propre.")
