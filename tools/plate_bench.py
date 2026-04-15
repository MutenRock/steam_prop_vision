"""
tools/plate_bench.py  v6.1
Bench interactif avec pipeline 2 niveaux + ROI dynamique + VideoPlayer.

Modes :
  (aucun)               idle screen OpenCV + mpv fullscreen sur detection
  --no-display          headless, snap uniquement au changement de carte
  --stream              serveur MJPEG Flask sur :5051
  --no-video            désactive le VideoPlayer (bench pur)

Usage:
    python tools/plate_bench.py --pi                  # display + video
    python tools/plate_bench.py --pi --no-video       # display sans video
    python tools/plate_bench.py --pi --no-display     # headless snaps
    python tools/plate_bench.py --pi --stream         # MJPEG :5051
"""
from __future__ import annotations
import sys, os, time, argparse, threading, signal
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
from steamcore.recognition.pipeline import RecognitionPipeline

PLATEST_DIR  = os.path.join(os.path.dirname(__file__), "..", "PLATEST")
VIDEO_DIR    = os.path.join(os.path.dirname(__file__), "..", "assets", "video")
WIN          = "plate_bench"
FONT         = cv2.FONT_HERSHEY_SIMPLEX
SNAP_DIR     = "/tmp/bench_snaps"
STREAM_PORT  = 5051
JPEG_QUALITY = 75


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--src",         default="0")
    p.add_argument("--pi",          action="store_true")
    p.add_argument("--backend",     default="orb", choices=["orb", "sift"])
    p.add_argument("--platest",     default=PLATEST_DIR)
    p.add_argument("--no-display",  action="store_true")
    p.add_argument("--stream",      action="store_true")
    p.add_argument("--port",        type=int, default=STREAM_PORT)
    p.add_argument("--no-video",    action="store_true",
                   help="Désactive le VideoPlayer mpv")
    p.add_argument("--video-dir",   default=VIDEO_DIR)
    p.add_argument("--bg-interval", type=float, default=0.4)
    p.add_argument("--result-ttl",  type=float, default=3.0)
    return p.parse_args()


# ── Camera ────────────────────────────────────────────────────────────────────

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


# ── OSD (mode bench uniquement, pas en mode video) ─────────────────────────

def put(img, text, pos, color=(0, 255, 255), scale=0.55, thick=2):
    cv2.putText(img, text, pos, FONT, scale, (0, 0, 0), thick + 2)
    cv2.putText(img, text, pos, FONT, scale, color, thick)


def build_overlay(frame, quad, result, fps, dt_ms, backend, player_active):
    out = frame.copy()
    if quad is not None:
        pts = quad.corners.astype(int)
        for i in range(4):
            cv2.line(out, tuple(pts[i]), tuple(pts[(i+1) % 4]), (0, 255, 100), 2)
        cv2.rectangle(out, (quad.x, quad.y),
                      (quad.x + quad.w, quad.y + quad.h), (0, 180, 255), 1)

    put(out, "FPS " + str(round(fps, 1)) + "  L1 " + str(round(dt_ms)) + "ms",
        (10, 24))
    put(out, "backend=" + backend +
        ("  [VIDEO ON]" if player_active else ""), (10, 48))

    if quad:
        put(out, "quad conf=" + str(round(quad.confidence, 2)) +
            "  ROI " + str(quad.w) + "x" + str(quad.h),
            (10, 72), (0, 255, 100))
    else:
        put(out, "no quad", (10, 72), (0, 100, 255))

    if result:
        label = result.card_id.replace("plate_", "").upper()
        tw = cv2.getTextSize(label, FONT, 1.4, 3)[0][0]
        cx = (out.shape[1] - tw) // 2
        cy = out.shape[0] - 40
        cv2.putText(out, label, (cx, cy), FONT, 1.4, (0, 0, 0), 6)
        cv2.putText(out, label, (cx, cy), FONT, 1.4, (0, 220, 255), 3)
        put(out, "CONFIRMED: " + result.card_id +
            "  score=" + str(round(result.score, 3)),
            (10, 96), (0, 200, 255))
    return out


# ── MJPEG stream ──────────────────────────────────────────────────────────────

_stream_frame = None
_stream_lock  = threading.Lock()


def _update_stream(frame):
    global _stream_frame
    ok, buf = cv2.imencode(".jpg", frame,
                           [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if ok:
        with _stream_lock:
            _stream_frame = buf.tobytes()


def _gen_frames():
    while True:
        with _stream_lock:
            f = _stream_frame
        if f is None:
            time.sleep(0.05)
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + f + b"\r\n")
        time.sleep(0.04)


def start_flask_server(port):
    from flask import Flask, Response
    app = Flask(__name__)

    @app.route("/")
    def index():
        return (
            "<!DOCTYPE html><html><head><title>plate_bench</title>"
            "<style>body{background:#111;color:#eee;font-family:monospace;padding:16px}"
            "img{max-width:100%}</style></head><body>"
            "<h2>plate_bench v6</h2>"
            "<img src='/stream'>"
            "</body></html>"
        )

    @app.route("/stream")
    def stream():
        return Response(_gen_frames(),
                        mimetype="multipart/x-mixed-replace; boundary=frame")

    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, threaded=True),
        daemon=True, name="flask-bench"
    ).start()
    print("[bench] stream MJPEG -> http://<IP_STYX>:" + str(port) + "/")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    os.makedirs(SNAP_DIR, exist_ok=True)

    # ── Pipeline ──────────────────────────────────────────────────────────────
    pipe = RecognitionPipeline(
        platest_dir=args.platest,
        backend=args.backend,
        bg_interval=args.bg_interval,
        result_ttl=args.result_ttl,
    )
    pipe.start()
    print("[bench] cards   : " + str(pipe.card_ids))
    print("[bench] backend=" + args.backend +
          "  headless=" + str(args.no_display) +
          "  stream=" + str(args.stream) +
          "  video=" + str(not args.no_video))

    # ── VideoPlayer ───────────────────────────────────────────────────────────
    player = None
    if not args.no_video:
        try:
            from apps.video_player import VideoPlayer
            player = VideoPlayer(video_dir=args.video_dir)
            player.start()   # idle screen : fond noir + titre
            print("[bench] VideoPlayer prêt")
        except Exception as e:
            print("[bench] VideoPlayer indisponible : " + str(e))
            player = None

    # ── Stream MJPEG ──────────────────────────────────────────────────────────
    if args.stream:
        start_flask_server(args.port)

    # ── Camera ────────────────────────────────────────────────────────────────
    if args.pi:
        cam      = open_picam()
        read_fn  = lambda: __import__('cv2').cvtColor(
                       cam.capture_array(), __import__('cv2').COLOR_RGB2BGR)
        close_fn = cam.stop
    else:
        cap      = open_cv_cap(args.src)
        read_fn  = lambda: (lambda ok, f: f if ok else None)(*cap.read())
        close_fn = cap.release

    if not args.no_display and not args.stream:
        print("[bench] [SPACE]=pause  [R]=reload  [Q]=quitter")

    fps_t        = time.time()
    fps_val      = 0.0
    snap_n       = 0
    last_snap_id = None
    last_play_id = None
    paused       = False
    running      = True
    out          = None

    def _stop(_s=None, _f=None):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    while running:
        if not paused:
            frame = read_fn()
            if frame is None:
                print("[bench] fin du flux")
                break

            t0     = time.time()
            quad   = pipe._fast.detect(frame)
            result = pipe.process_frame(frame)
            dt_ms  = (time.time() - t0) * 1000

            now     = time.time()
            fps_val = 0.9 * fps_val + 0.1 / max(now - fps_t, 1e-5)
            fps_t   = now

            out = build_overlay(frame, quad, result, fps_val, dt_ms,
                                args.backend, player is not None)

            # ── Déclencher la vidéo sur nouvelle carte confirmée ──────────────
            if player and result:
                if result.card_id != last_play_id:
                    player.play_card(result.card_id)
                    last_play_id = result.card_id
            elif player and not result:
                last_play_id = None

            # ── Mode headless ─────────────────────────────────────────────────
            if args.no_display:
                new_id = result.card_id if result else None
                if new_id and new_id != last_snap_id:
                    snap_path = os.path.join(
                        SNAP_DIR,
                        "snap_" + str(snap_n) + "_" + new_id + ".jpg")
                    cv2.imwrite(snap_path, out)
                    print("[bench] snap -> " + snap_path)
                    snap_n += 1
                last_snap_id = new_id
                time.sleep(0.05)
                continue

            # ── Mode stream ───────────────────────────────────────────────────
            if args.stream:
                _update_stream(out)
                time.sleep(0.04)
                continue

        # ── Mode display local (bench sans video) ──────────────────────────
        if not player:
            if out is not None:
                cv2.imshow(WIN, out)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                running = False
            elif key == ord(" "):
                paused = not paused
                print("[bench] " + ("pause" if paused else "resume"))
            elif key == ord("r"):
                pipe.reload()
                print("[bench] templates rechargees")
        else:
            # VideoPlayer gère son propre affichage, juste waitKey pour Qt
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                running = False

    pipe.stop()
    if player:
        player.stop()
    close_fn()
    if not player and not args.no_display and not args.stream:
        cv2.destroyAllWindows()
    print("[bench] bye")


if __name__ == "__main__":
    main()
