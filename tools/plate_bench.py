"""
tools/plate_bench.py  v4
Bench interactif avec pipeline 2 niveaux + ROI dynamique.
Usage:
    python tools/plate_bench.py            # webcam locale
    python tools/plate_bench.py --pi       # Picamera2 (STYX)
    python tools/plate_bench.py --backend sift
    python tools/plate_bench.py --no-display  # headless, sauvegarde snapshots
"""
from __future__ import annotations
import sys, os, time, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np
from steamcore.recognition.pipeline import RecognitionPipeline
from steamcore.recognition.fast_detector import FastDetector

PLATEST_DIR = os.path.join(os.path.dirname(__file__), "..", "PLATEST")
WIN         = "plate_bench"
FONT        = cv2.FONT_HERSHEY_SIMPLEX
SNAP_DIR    = "/tmp/bench_snaps"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--src",        default="0")
    p.add_argument("--pi",         action="store_true")
    p.add_argument("--backend",    default="orb", choices=["orb", "sift"])
    p.add_argument("--platest",    default=PLATEST_DIR)
    p.add_argument("--no-display", action="store_true",
                   help="Mode headless : sauvegarde snapshots dans /tmp/bench_snaps")
    p.add_argument("--bg-interval", type=float, default=0.4)
    p.add_argument("--result-ttl",  type=float, default=3.0)
    return p.parse_args()


def open_cv_cap(src_str):
    src = int(src_str) if src_str.isdigit() else src_str
    cap = cv2.VideoCapture(src)
    if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def open_picam(w=1280, h=720):
    from picamera2 import Picamera2
    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"size": (w, h), "format": "RGB888"}
    ))
    cam.start()
    time.sleep(2.0)
    return cam


def put(img, text, pos, color=(0, 255, 255), scale=0.55, thick=2):
    cv2.putText(img, text, pos, FONT, scale, (0, 0, 0), thick + 2)
    cv2.putText(img, text, pos, FONT, scale, color, thick)


def main():
    args = parse_args()
    os.makedirs(SNAP_DIR, exist_ok=True)

    pipe = RecognitionPipeline(
        platest_dir=args.platest,
        backend=args.backend,
        bg_interval=args.bg_interval,
        result_ttl=args.result_ttl,
    )
    pipe.start()
    print("[bench] cards : " + str(pipe.card_ids))
    print("[bench] backend=" + args.backend +
          "  headless=" + str(args.no_display))

    if args.pi:
        cam      = open_picam()
        read_fn  = lambda: cv2.cvtColor(cam.capture_array(), cv2.COLOR_RGB2BGR)
        close_fn = cam.stop
    else:
        cap      = open_cv_cap(args.src)
        read_fn  = lambda: (lambda ok, f: f if ok else None)(*cap.read())
        close_fn = cap.release

    fps_t    = time.time()
    fps_val  = 0.0
    snap_n   = 0
    paused   = False
    last_quad = None

    print("[bench] [SPACE]=pause  [W]=warp  [R]=reload  [Q]=quitter")

    while True:
        if not paused:
            frame = read_fn()
            if frame is None:
                print("[bench] fin du flux")
                break

            t0   = time.time()
            quad = pipe._fast.detect(frame)
            if quad is not None:
                last_quad = quad
            result = pipe.process_frame(frame)
            dt   = time.time() - t0

            now     = time.time()
            fps_val = 0.9 * fps_val + 0.1 / max(now - fps_t, 1e-5)
            fps_t   = now

            out = pipe.draw_overlay(frame, quad)

            # OSD
            put(out, "FPS " + str(round(fps_val, 1)) +
                "  L1 " + str(round(dt * 1000)) + "ms", (10, 24))
            put(out, "backend=" + args.backend, (10, 48))
            if quad:
                put(out, "quad conf=" + str(round(quad.confidence, 2)) +
                    "  ROI " + str(quad.w) + "x" + str(quad.h),
                    (10, 72), (0, 255, 100))
            else:
                put(out, "no quad", (10, 72), (0, 100, 255))
            if result:
                put(out, "CONFIRMED: " + result.card_id +
                    "  " + str(round(result.score, 3)),
                    (10, 96), (0, 200, 255))

            if args.no_display:
                if result:
                    snap_path = os.path.join(
                        SNAP_DIR, "snap_" + str(snap_n) + "_" +
                        result.card_id + ".jpg")
                    cv2.imwrite(snap_path, out)
                    print("[bench] snap -> " + snap_path)
                    snap_n += 1
                time.sleep(0.05)
                continue

        if not args.no_display:
            cv2.imshow(WIN, out)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord(" "):
                paused = not paused
                print("[bench] " + ("pause" if paused else "resume"))
            elif key == ord("r"):
                pipe.reload()
                print("[bench] templates rechargees")

    pipe.stop()
    close_fn()
    if not args.no_display:
        cv2.destroyAllWindows()
    print("[bench] bye")


if __name__ == "__main__":
    main()
