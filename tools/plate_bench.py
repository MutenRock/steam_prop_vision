"""
tools/plate_bench.py
Bench interactif SIFT/ORB sur flux cam -- v3
Compatible CardDetector v2 (min_matches, min_inliers) et CardRecognizer v2 (.card_id).
Usage:
    python tools/plate_bench.py            # webcam locale index 0
    python tools/plate_bench.py --pi       # Picamera2 (STYX)
    python tools/plate_bench.py --src rtsp://...
    python tools/plate_bench.py --src 1
"""
from __future__ import annotations
import sys, os, time, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np
from steamcore.recognition.card_detector   import CardDetector
from steamcore.recognition.card_recognizer import CardRecognizer

PLATEST_DIR  = os.path.join(os.path.dirname(__file__), "..", "PLATEST")
WARP_SIZE    = 400
WIN          = "plate_bench"
FONT         = cv2.FONT_HERSHEY_SIMPLEX


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--src",  default="0",  help="Source: index ou URL RTSP")
    p.add_argument("--pi",   action="store_true", help="Utiliser Picamera2")
    p.add_argument("--platest", default=PLATEST_DIR, help="Dossier PLATEST")
    p.add_argument("--min-matches",  type=int,   default=8)
    p.add_argument("--min-inliers",  type=int,   default=6)
    p.add_argument("--ratio",        type=float, default=0.75)
    p.add_argument("--min-orb",      type=int,   default=8,
                   help="min_matches pour CardRecognizer")
    p.add_argument("--threshold",    type=float, default=0.04,
                   help="Score threshold CardRecognizer")
    return p.parse_args()


# ── Camera helpers ────────────────────────────────────────────────────────────

def open_cv_cap(src_str: str):
    src = int(src_str) if src_str.isdigit() else src_str
    cap = cv2.VideoCapture(src)
    if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def open_picam(width=1280, height=720):
    from picamera2 import Picamera2
    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"size": (width, height), "format": "RGB888"}
    ))
    cam.start()
    time.sleep(2.0)   # AWB warmup
    return cam


def read_frame_cv(cap):
    ok, frame = cap.read()
    return frame if ok else None


def read_frame_pi(cam):
    rgb = cam.capture_array()
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


# ── Overlay helpers ───────────────────────────────────────────────────────────

def put(img, text, pos, color=(0, 255, 255), scale=0.55, thick=2):
    cv2.putText(img, text, pos, FONT, scale, (0, 0, 0), thick + 2)
    cv2.putText(img, text, pos, FONT, scale, color, thick)


def draw_quad(img, corners, color=(0, 255, 0)):
    pts = corners.astype(int)
    for i in range(4):
        cv2.line(img, tuple(pts[i]), tuple(pts[(i+1) % 4]), color, 2)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    detector   = CardDetector(
        platest_dir=args.platest,
        min_matches=args.min_matches,
        min_inliers=args.min_inliers,
        ratio_test=args.ratio,
    )
    recognizer = CardRecognizer(
        platest_dir=args.platest,
        min_matches=args.min_orb,
        threshold=args.threshold,
    )

    print("[bench] cards charges :", detector.card_ids)

    if args.pi:
        print("[bench] mode Picamera2")
        cam     = open_picam()
        read_fn = lambda: read_frame_pi(cam)
        close_fn = cam.stop
    else:
        src = args.src
        print("[bench] mode cv2.VideoCapture src=" + str(src))
        cap     = open_cv_cap(src)
        read_fn = lambda: read_frame_cv(cap)
        close_fn = cap.release

    paused      = False
    show_warp   = False
    last_result = None
    last_region = None
    fps_t       = time.time()
    fps_val     = 0.0

    print("[bench] Commandes : [SPACE] pause  [W] toggle warp  [Q] quitter")

    while True:
        if not paused:
            frame = read_fn()
            if frame is None:
                print("[bench] frame None, fin.")
                break

            t0     = time.time()
            region = detector.detect(frame)
            dt_det = time.time() - t0

            result = None
            if region is not None:
                hint = None
                result = recognizer.recognize(region.warped, hint_id=hint)
                last_region = region
                last_result = result
                draw_quad(frame, region.corners)

            # FPS
            now   = time.time()
            fps_val = 0.9 * fps_val + 0.1 * (1.0 / max(now - fps_t, 1e-5))
            fps_t = now

            # OSD
            put(frame, "FPS: " + str(round(fps_val, 1)), (10, 24))
            put(frame, "det: " + str(round(dt_det * 1000)) + "ms", (10, 48))

            if region:
                put(frame, "matches: " + str(region.match_count), (10, 72), (0, 255, 0))
                if result:
                    lbl = result.card_id + "  " + str(round(result.score, 3))                           + "  (" + str(result.matches) + "m)"
                    put(frame, lbl, (10, 96), (0, 200, 255))
                else:
                    put(frame, "recognition: none", (10, 96), (0, 140, 255))
            else:
                put(frame, "no card detected", (10, 72), (0, 100, 255))

        # Affichage
        if show_warp and last_region is not None:
            disp = cv2.resize(last_region.warped, (WARP_SIZE, WARP_SIZE))
            if last_result:
                put(disp, last_result.card_id, (10, 30), (0, 255, 100))
            cv2.imshow(WIN, disp)
        else:
            cv2.imshow(WIN, frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord(" "):
            paused = not paused
            print("[bench] " + ("pause" if paused else "resume"))
        elif key == ord("w"):
            show_warp = not show_warp
            print("[bench] warp=" + str(show_warp))
        elif key == ord("r"):
            detector.reload()
            recognizer.reload()
            print("[bench] rechargement templates")

    close_fn()
    cv2.destroyAllWindows()
    print("[bench] bye")


if __name__ == "__main__":
    main()
