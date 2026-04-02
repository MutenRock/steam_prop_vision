# app_flask.py  –  steam_prop_vision (Pi headless)
# -*- coding: utf-8 -*-
"""
Remplace app-6.py (Tkinter) par un serveur Flask MJPEG.
Reuse tous les modules gui/ et core/ existants.
"""
from __future__ import annotations
import os, time, threading, json, argparse
os.environ.setdefault('OPENCV_LOG_LEVEL', 'SILENT')

from flask import Flask, Response, request, jsonify
import cv2

from picamera2 import Picamera2

from core.sim_core import SimulationEngine
from gui.config_manager import load_config_folder, get_plaques_folder
from gui.rule_engine import RuleEngine
from gui.action_router import ActionRouter

# ── Config ─────────────────────────────────────────────────────────────────
CAM_WIDTH     = 1280
CAM_HEIGHT    = 720
JPEG_QUALITY  = 80
AWB_WARMUP_S  = 2.0
FLASK_PORT    = 5050
LOOP_INTERVAL = 0.05   # ~20 fps pipeline

# ── Globals ─────────────────────────────────────────────────────────────────
app        = Flask(__name__)
engine     = SimulationEngine()
rules      = RuleEngine()
router     = ActionRouter()
_detectors = []

_lock         = threading.Lock()
_latest_frame = None          # BGR numpy array, annotated
_status       = {
    "fsm": "IDLE", "presence": False, "presence_score": 0.0,
    "plaque": None, "plaque_score": 0.0, "t": 0.0,
    "action_log": [], "config_folder": None,
}
_presence_prev    = False
_action_log_lines = []

# ── Picamera2 ────────────────────────────────────────────────────────────────
def init_camera() -> Picamera2:
    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"size": (CAM_WIDTH, CAM_HEIGHT), "format": "RGB888"}
    ))
    cam.start()
    print(f"[cam] AWB warmup {AWB_WARMUP_S}s...")
    time.sleep(AWB_WARMUP_S)
    print("[cam] Ready")
    return cam

# ── Pipeline thread ──────────────────────────────────────────────────────────
def pipeline_loop(cam: Picamera2):
    global _latest_frame, _presence_prev, _action_log_lines

    while True:
        t0 = time.time()

        # Capture + convert RGB→BGR
        rgb   = cam.capture_array()
        frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

        # Detection
        validated = rules.process_frame(frame)

        # Actions
        now = time.time()
        action_lines = []
        if validated.presence and not _presence_prev:
            action_lines += router.handle(
                key="presence", presence=True,
                sim_engine=engine,
                default_conf=max(0.0, min(1.0, validated.presence_score)),
            )
        _presence_prev = bool(validated.presence)

        if validated.plaque_id:
            action_lines += router.handle(
                key=f"PLAQUE:{validated.plaque_id}",
                presence=validated.presence,
                sim_engine=engine,
                default_conf=max(0.0, min(1.0, validated.plaque_score)),
            )
            engine.inject_detection(
                f"PLAQUE:{validated.plaque_id}",
                max(0.0, min(1.0, validated.plaque_score)),
            )

        if validated.presence:
            engine.inject_detection("presence",
                max(0.0, min(1.0, validated.presence_score)))

        engine.step(LOOP_INTERVAL)

        # Extra detectors (si chargés via config)
        for det in _detectors:
            try:
                results = det.process_frame(frame)
            except Exception:
                results = []
            for r in results:
                al = router.handle(
                    key=r.label, presence=validated.presence,
                    sim_engine=engine, default_conf=r.confidence,
                )
                action_lines += al
                engine.inject_detection(r.label, r.confidence)

        _action_log_lines = (action_lines + _action_log_lines)[:50]

        # OSD
        snap = engine.snapshot()
        cv2.putText(frame,
            f"presence={validated.presence} score={validated.presence_score:.2f}"
            f" ({rules.last_presence.detail})",
            (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        plaque_txt = "plaque=none"
        if rules.last_plaque:
            plaque_txt = (f"plaque={rules.last_plaque.plaque_id}"
                          f" score={rules.last_plaque.score:.2f}"
                          f" good={rules.last_plaque.good_matches}")
        cv2.putText(frame, plaque_txt,
            (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        fsm = snap["fsm"]
        cv2.putText(frame, f"FSM:{fsm['state']} t={snap['t']:.1f}s",
            (10, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)

        with _lock:
            _latest_frame = frame.copy()
            _status.update({
                "fsm": fsm["state"],
                "presence": bool(validated.presence),
                "presence_score": round(validated.presence_score, 3),
                "plaque": validated.plaque_id,
                "plaque_score": round(validated.plaque_score, 3),
                "t": round(snap["t"], 1),
                "action_log": _action_log_lines[:10],
                "config_folder": _status.get("config_folder"),
            })

        elapsed = time.time() - t0
        sleep = max(0.0, LOOP_INTERVAL - elapsed)
        time.sleep(sleep)

# ── MJPEG generator ──────────────────────────────────────────────────────────
def gen_frames():
    while True:
        with _lock:
            frame = _latest_frame
        if frame is None:
            time.sleep(0.05)
            continue
        ok, buf = cv2.imencode('.jpg', frame,
                               [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            continue
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n'
               + buf.tobytes() + b'\r\n')

# ── Routes ───────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    s = _status
    return f"""<!DOCTYPE html><html><head>
<title>steam_prop_vision</title>
<style>body{{background:#111;color:#eee;font-family:monospace;padding:16px}}
img{{max-width:100%}} .card{{background:#222;padding:12px;margin:8px 0;border-radius:6px}}
</style><meta http-equiv="refresh" content="2"></head><body>
<h2>🎥 steam_prop_vision</h2>
<img src="/stream"><br>
<div class="card">
  <b>FSM:</b> {s['fsm']} &nbsp; <b>t:</b> {s['t']}s<br>
  <b>Presence:</b> {s['presence']} ({s['presence_score']})<br>
  <b>Plaque:</b> {s['plaque'] or 'none'} ({s['plaque_score']})<br>
  <b>Config:</b> {s['config_folder'] or '(none)'}
</div>
<div class="card"><b>Actions:</b><br>
{'<br>'.join(s['action_log']) or '(none)'}
</div>
<hr>
<form method="POST" action="/api/config">
  Config folder: <input name="folder" style="width:400px">
  <button type="submit">Load</button>
</form>
</body></html>"""

@app.route('/stream')
def stream():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def api_status():
    with _lock:
        return jsonify(_status)

@app.route('/api/config', methods=['POST'])
def api_config():
    global _detectors
    folder = (request.form.get('folder') or
              (request.json or {}).get('folder', '')).strip()
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": "folder not found"}), 400
    try:
        loaded = load_config_folder(folder)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    rules.apply_config(loaded.data)
    plaques_folder = get_plaques_folder(folder)
    loaded_ids = []
    if os.path.isdir(plaques_folder):
        loaded_ids = rules.plaque.load_from_folder(plaques_folder)
    ok, msg = router.load_rules(folder)

    try:
        from core.detectors import build_detectors
        _detectors = build_detectors(loaded.data)
    except Exception:
        _detectors = []

    with _lock:
        _status["config_folder"] = folder

    return jsonify({
        "plaques": loaded_ids,
        "rules": msg,
        "detectors": [type(d).__name__ for d in _detectors],
    })

@app.route('/api/inject', methods=['POST'])
def api_inject():
    data  = request.json or {}
    label = str(data.get('label', '')).strip()
    conf  = float(data.get('conf', 0.9))
    if not label:
        return jsonify({"error": "label required"}), 400
    engine.inject_detection(label, conf)
    return jsonify({"ok": True, "label": label, "conf": conf})

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='', help='Config folder to load at startup')
    parser.add_argument('--port',   default=FLASK_PORT, type=int)
    args = parser.parse_args()

    cam = init_camera()

    if args.config and os.path.isdir(args.config):
        try:
            loaded = load_config_folder(args.config)
            rules.apply_config(loaded.data)
            pf = get_plaques_folder(args.config)
            if os.path.isdir(pf):
                rules.plaque.load_from_folder(pf)
            router.load_rules(args.config)
            _status["config_folder"] = args.config
            print(f"[config] Loaded: {args.config}")
        except Exception as e:
            print(f"[config] Error: {e}")

    t = threading.Thread(target=pipeline_loop, args=(cam,), daemon=True)
    t.start()

    print(f"[flask] http://0.0.0.0:{args.port}")
    app.run(host='0.0.0.0', port=args.port, threaded=True)