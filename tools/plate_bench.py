"""
tools/plate_bench.py
Bench interactif -- camera ouverte UNE seule fois avant le menu.
"""
from __future__ import annotations
import sys, time, csv, argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2
import numpy as np

from steamcore.recognition.card_detector   import CardDetector
from steamcore.recognition.card_recognizer import CardRecognizer

PLATEST_DIR = "PLATEST"
WARP_SIZE   = 400

GREEN  = (80,  220, 80)
ORANGE = (0,   160, 255)
RED    = (60,  60,  220)
GRAY   = (170, 170, 170)
WHITE  = (255, 255, 255)
BLACK  = (0,   0,   0)
GOLD   = (0,   200, 220)


@dataclass
class TestResult:
    expected:    str
    got:         str | None
    score:       float
    matches:     int
    duration_ms: float
    ok:          bool


@dataclass
class Session:
    results: list[TestResult] = field(default_factory=list)

    @property
    def total(self):    return len(self.results)
    @property
    def correct(self):  return sum(1 for r in self.results if r.ok)
    @property
    def missed(self):   return sum(1 for r in self.results if r.got is None)
    @property
    def wrong(self):    return sum(1 for r in self.results if r.got and not r.ok)
    @property
    def accuracy(self): return (self.correct / self.total * 100) if self.total else 0.0


def put(img, text, pos, color=WHITE, scale=0.55, thick=1):
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, thick, cv2.LINE_AA)


def make_camera(use_pi: bool):
    """Ouvre la camera UNE seule fois."""
    if use_pi:
        try:
            from picamera2 import Picamera2
            cam = Picamera2()
            cam.configure(cam.create_preview_configuration(
                main={"format": "RGB888", "size": (1280, 720)}
            ))
            cam.start()
            time.sleep(0.5)
            print("[cam] Picamera2 OK")
            return "pi", cam
        except Exception as e:
            print("[cam] picamera2 indispo : " + str(e) + " -> webcam")
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    print("[cam] Webcam OK")
    return "web", cap


def read_frame(cam_type, cam):
    if cam_type == "pi":
        f = cam.capture_array()
        if f is None:
            return False, None
        return True, cv2.cvtColor(f, cv2.COLOR_RGB2BGR)
    return cam.read()


def stop_camera(cam_type, cam):
    if cam_type == "pi": cam.stop()
    else:                cam.release()


def compute_all_scores(recognizer, warped):
    orb     = cv2.ORB_create(nfeatures=800)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    gray    = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)               if len(warped.shape)==3 else warped
    gray    = cv2.resize(gray, (WARP_SIZE, WARP_SIZE))
    kps_q, desc_q = orb.detectAndCompute(gray, None)
    scores = []
    if desc_q is not None:
        for t in recognizer._templates:
            top_s, top_m = 0.0, 0
            for kps_r, desc_r in t.descs:
                ms   = matcher.knnMatch(desc_q, desc_r, k=2)
                good = [m for m, n in ms if m.distance < 0.75*n.distance]
                s    = len(good) / max(len(kps_r), len(kps_q), 1)
                if s > top_s:
                    top_s, top_m = s, len(good)
            scores.append((t.id, top_s, top_m))
    scores.sort(key=lambda x: -x[1])
    return scores


def ask_card_terminal(cards: list[str]) -> str | None:
    """Question posee dans le terminal SANS fermer la camera."""
    print()
    print("  Quelle carte presenter ?  (0=fin)")
    for i, c in enumerate(cards):
        print("    [" + str(i+1) + "] " + c.replace("plate_","").capitalize())
    while True:
        rep = input("  > ").strip()
        if rep == "0":
            return None
        try:
            idx = int(rep) - 1
            if 0 <= idx < len(cards):
                return cards[idx]
        except ValueError:
            pass


def draw_scores(frame, scores, best_id):
    x0, y0 = frame.shape[1] - 270, 10
    panel_h = 30 + len(scores) * 26 + 10
    ov = frame.copy()
    cv2.rectangle(ov, (x0-8, y0-5), (frame.shape[1]-5, y0+panel_h), BLACK, -1)
    cv2.addWeighted(ov, 0.6, frame, 0.4, 0, frame)
    put(frame, "Scores ORB", (x0, y0+16), GOLD, 0.5)
    for i, (cid, sc, mc) in enumerate(scores):
        y     = y0 + 36 + i*26
        color = GREEN if cid == best_id else GRAY
        bar   = int(min(sc * 1100, 160))
        cv2.rectangle(frame, (x0, y-12), (x0+bar, y+4), color, -1)
        name  = cid.replace("plate_","")[:9]
        put(frame, name + "  " + str(round(sc,3)) + " (" + str(mc) + ")",
            (x0+bar+5, y), color, 0.42)


def draw_hud(frame, fps, expected, last_result):
    h, w = frame.shape[:2]
    exp_name = expected.replace("plate_","").upper() if expected else "---"
    put(frame, "FPS " + str(round(fps,1)) + "  |  Carte : " + exp_name,
        (10, 30), GOLD, 0.6, 1)
    put(frame, "ESPACE=tester  R=reload  Q=quitter  (terminal : changer carte)",
        (10, h-12), GRAY, 0.42)
    if last_result:
        res, exp_last, dur = last_result
        ok    = res is not None and res.card_id == exp_last
        color = GREEN if ok else (ORANGE if res is None else RED)
        label = ("OK : " + res.label) if ok else ("RATE" if res is None else "ERREUR -> " + (res.label if res else ""))
        cv2.rectangle(frame, (0, h-55), (w, h-35), BLACK, -1)
        put(frame, label + "  " + str(round(dur)) + "ms", (10, h-38), color, 0.6, 1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pi",     action="store_true")
    p.add_argument("--report", action="store_true")
    args = p.parse_args()

    detector   = CardDetector(min_area=1500)
    recognizer = CardRecognizer(PLATEST_DIR)
    cards      = [t.card_id for t in recognizer._templates]

    if not cards:
        print("[bench] Aucune carte dans PLATEST.")
        return

    print()
    print("=" * 55)
    print("  S.T.E.A.M Plate Bench")
    print("=" * 55)
    print("  " + str(len(cards)) + " cartes : " +
          ", ".join(c.replace("plate_","") for c in cards))
    print()

    # ── Camera ouverte UNE SEULE FOIS ────────────────────────
    cam_type, cam = make_camera(args.pi)

    session     = Session()
    expected    = cards[0]
    last_result = None
    last_scores = []
    snap_count  = 0
    prev_time   = time.time()
    freeze_until = 0.0

    print("[bench] Prêt -- touches : ESPACE tester | R reload | Q quitter")
    print("[bench] Pour changer de carte : taper 1-" + str(len(cards)) +
          " dans ce terminal puis Entree")
    print()

    cv2.namedWindow("S.T.E.A.M Plate Bench", cv2.WINDOW_AUTOSIZE)

    import threading

    # Thread terminal : changer la carte sans bloquer la camera
    def terminal_input():
        nonlocal expected, last_result, last_scores
        while True:
            try:
                line = input()
                line = line.strip()
                if line == "0" or line.lower() == "q":
                    break
                idx = int(line) - 1
                if 0 <= idx < len(cards):
                    expected    = cards[idx]
                    last_result = None
                    last_scores = []
                    print("[bench] Carte -> " + expected.replace("plate_","").upper())
                    print("  Montrez la carte et appuyez ESPACE")
            except (ValueError, EOFError):
                pass

    t = threading.Thread(target=terminal_input, daemon=True)
    t.start()

    print("  Carte courante : " + expected.replace("plate_","").upper())
    print("  Montrez la carte et appuyez ESPACE")

    while True:
        ok, frame = read_frame(cam_type, cam)
        if not ok or frame is None:
            continue

        now   = time.time()
        fps   = 1.0 / max(now - prev_time, 0.001)
        prev_time = now
        freeze = now < freeze_until

        region = detector.detect(frame)
        result = None
        if region is not None and not freeze:
            result      = recognizer.recognize(region.warped)
            last_scores = compute_all_scores(recognizer, region.warped)
            corners     = region.corners.astype(np.int32)
            color       = GREEN if result else ORANGE
            cv2.polylines(frame, [corners], True, color, 2)
            for pt in corners:
                cv2.circle(frame, tuple(pt), 5, color, -1)
            warp_th = cv2.resize(region.warped, (160, 160))
            frame[8:168, 8:168] = warp_th
            if result:
                cx = int(corners[:,0].mean())
                cy = int(corners[:,1].mean())
                put(frame, result.label, (cx-60, cy-12), GREEN, 0.75, 2)

        if last_scores:
            best_id = last_scores[0][0] if last_scores else None
            draw_scores(frame, last_scores, best_id)

        draw_hud(frame, fps, expected, last_result)
        cv2.imshow("S.T.E.A.M Plate Bench", frame)
        key = cv2.waitKey(1) & 0xFF

        if key in (ord("q"), 27):
            break
        elif key == ord("r"):
            recognizer.reload()
            last_scores = []
            print("[bench] Templates recharges")
        elif key == ord(" "):
            t0   = time.time()
            reg2 = detector.detect(frame)
            if reg2 is None:
                print("[bench] Aucun losange -- reessaie")
                continue
            res     = recognizer.recognize(reg2.warped)
            dur_ms  = (time.time() - t0) * 1000
            got     = res.card_id if res else None
            score   = res.score   if res else 0.0
            matches = res.matches if res else 0
            ok_flag = got == expected
            session.results.append(TestResult(
                expected=expected, got=got, score=score,
                matches=matches, duration_ms=dur_ms, ok=ok_flag))
            last_result  = (res, expected, dur_ms)
            freeze_until = now + 2.0
            emoji = "OK" if ok_flag else ("RATE" if got is None else "ERREUR")
            print("[bench] " + emoji +
                  " | attendu=" + expected.replace("plate_","") +
                  " | obtenu=" + (got or "rien").replace("plate_","") +
                  " | score=" + str(round(score,3)) +
                  " | m=" + str(matches) +
                  " | " + str(round(dur_ms)) + "ms")
            snap_count += 1
            cv2.imwrite("bench_" + str(snap_count).zfill(3) + "_" + emoji + ".jpg", frame)

    stop_camera(cam_type, cam)
    cv2.destroyAllWindows()

    if session.total == 0:
        print("[bench] Aucun test.")
        return

    print()
    print("=" * 50)
    print("  SCORE : " + str(session.correct) + "/" + str(session.total) +
          "  (" + str(round(session.accuracy,1)) + "%)")
    print("  Manques : " + str(session.missed) +
          "  Erreurs : " + str(session.wrong))
    per = {c: [r for r in session.results if r.expected==c] for c in cards}
    for cid, rs in per.items():
        if not rs: continue
        ok  = sum(1 for r in rs if r.ok)
        avg = round(sum(r.score for r in rs)/len(rs), 3)
        print("  " + cid.replace("plate_","").ljust(12) +
              str(ok) + "/" + str(len(rs)) + "  score_moy=" + str(avg))
    print("=" * 50)

    if args.report:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = "bench_" + ts + ".csv"
        with open(name, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["expected","got","score","matches","duration_ms","ok"])
            for r in session.results:
                w.writerow([r.expected, r.got or "", r.score,
                            r.matches, round(r.duration_ms), r.ok])
        print("[bench] CSV -> " + name)


if __name__ == "__main__":
    main()
