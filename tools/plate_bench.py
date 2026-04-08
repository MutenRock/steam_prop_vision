"""
tools/plate_bench.py
Jeu de test interactif -- valider la reconnaissance des 5 cartes.

Usage :
  python tools/plate_bench.py           # webcam
  python tools/plate_bench.py --pi      # picamera2
  python tools/plate_bench.py --report  # genere rapport CSV a la fin

Session :
  - Tu montres chaque carte devant la camera
  - Appuie ESPACE pour capturer et tester
  - Le resultat s affiche : bonne carte / mauvaise / non reconnue
  - A la fin : tableau recapitulatif + score global
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
    expected:   str
    got:        str | None
    score:      float
    matches:    int
    duration_ms: float
    ok:         bool


@dataclass
class Session:
    results: list[TestResult] = field(default_factory=list)
    start:   float            = field(default_factory=time.time)

    @property
    def total(self):     return len(self.results)
    @property
    def correct(self):   return sum(1 for r in self.results if r.ok)
    @property
    def missed(self):    return sum(1 for r in self.results if r.got is None)
    @property
    def wrong(self):     return sum(1 for r in self.results if r.got and not r.ok)
    @property
    def accuracy(self):  return (self.correct / self.total * 100) if self.total else 0


def put(img, text, pos, color=WHITE, scale=0.55, thick=1):
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, thick, cv2.LINE_AA)


def make_camera(use_pi: bool):
    if use_pi:
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
            print("[cam] picamera2 indisponible : " + str(e) + " -> webcam")
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    return "web", cap


def read_frame(cam_type, cam):
    if cam_type == "pi":
        f = cam.capture_array()
        if f is None:
            return False, None
        return True, cv2.cvtColor(f, cv2.COLOR_RGB2BGR)
    return cam.read()


def stop_camera(cam_type, cam):
    if cam_type == "pi":
        cam.stop()
    else:
        cam.release()


def draw_all_scores(frame, recognizer, region):
    """Panneau scores droite -- toutes les cartes."""
    orb    = cv2.ORB_create(nfeatures=800)
    matcher= cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    gray_w = cv2.cvtColor(region.warped, cv2.COLOR_BGR2GRAY)              if len(region.warped.shape)==3 else region.warped
    gray_w = cv2.resize(gray_w, (WARP_SIZE, WARP_SIZE))
    kps_q, desc_q = orb.detectAndCompute(gray_w, None)
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

    x0, y0 = frame.shape[1] - 265, 10
    panel_h = 30 + len(scores) * 28 + 10
    ov = frame.copy()
    cv2.rectangle(ov, (x0-8, y0-5), (frame.shape[1]-5, y0+panel_h), BLACK, -1)
    cv2.addWeighted(ov, 0.6, frame, 0.4, 0, frame)
    put(frame, "Scores ORB", (x0, y0+16), GOLD, 0.55, 1)

    best_id = scores[0][0] if scores else None
    for i, (cid, sc, mc) in enumerate(scores):
        y     = y0 + 38 + i * 28
        color = GREEN if cid == best_id else GRAY
        bar   = int(min(sc * 1200, 165))
        cv2.rectangle(frame, (x0, y-12), (x0+bar, y+4), color, -1)
        name  = cid.replace("plate_","")[:10]
        put(frame, name + "  " + str(round(sc,3)) + " (" + str(mc) + ")",
            (x0+bar+5, y), color, 0.45)
    return scores


def draw_result_banner(frame, result, expected, duration_ms):
    h, w = frame.shape[:2]
    ok    = result is not None and result.card_id == expected
    color = GREEN if ok else (ORANGE if result is None else RED)
    label = "OK  " + result.label if ok             else ("NON RECONNUE" if result is None             else "ERREUR -> " + result.label)
    cv2.rectangle(frame, (0, h-60), (w, h), BLACK, -1)
    put(frame, label, (20, h-30), color, 0.9, 2)
    put(frame, str(round(duration_ms)) + " ms", (w-120, h-30), GRAY, 0.5)


def interactive_ask_card(cards: list[str]) -> str:
    """Demande quelle carte va etre presentee."""
    print()
    print("  Quelle carte allez-vous presenter ?")
    for i, c in enumerate(cards):
        print("    [" + str(i+1) + "] " + c.replace("plate_","").capitalize())
    print("    [0] Fin du bench")
    while True:
        rep = input("  > ").strip()
        if rep == "0":
            return "__end__"
        try:
            idx = int(rep) - 1
            if 0 <= idx < len(cards):
                return cards[idx]
        except ValueError:
            pass
        print("  Choix invalide.")


def draw_summary(session: Session, cards: list[str]) -> np.ndarray:
    """Image de synthese finale."""
    h, w  = 80 + len(cards)*36 + 80, 700
    img   = np.zeros((h, w, 3), dtype=np.uint8)
    title = "BENCH S.T.E.A.M -- " + str(session.correct) + "/" + str(session.total) +             "  (" + str(round(session.accuracy, 1)) + "%)"
    put(img, title, (20, 35), GOLD, 0.75, 2)

    per_card: dict[str, list[TestResult]] = {c: [] for c in cards}
    for r in session.results:
        if r.expected in per_card:
            per_card[r.expected].append(r)

    for i, cid in enumerate(cards):
        y    = 70 + i * 36
        rs   = per_card[cid]
        ok   = sum(1 for r in rs if r.ok)
        tot  = len(rs)
        name = cid.replace("plate_","").capitalize()
        if tot == 0:
            color, tag = GRAY, "non testee"
        elif ok == tot:
            color, tag = GREEN, str(ok) + "/" + str(tot) + " OK"
        elif ok > 0:
            color, tag = ORANGE, str(ok) + "/" + str(tot) + " partiel"
        else:
            color, tag = RED, "0/" + str(tot) + " echec"
        avg_score = round(sum(r.score for r in rs)/max(len(rs),1), 3)
        put(img, name.ljust(14) + tag.ljust(16) + "score moy=" + str(avg_score),
            (20, y), color, 0.55)

    put(img, "Correct:" + str(session.correct) + "  Manques:" + str(session.missed) +
        "  Erreurs:" + str(session.wrong),
        (20, h-20), GRAY, 0.5)
    return img


def save_csv(session: Session, cards: list[str]):
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = "bench_" + ts + ".csv"
    with open(name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["expected","got","score","matches","duration_ms","ok"])
        for r in session.results:
            w.writerow([r.expected, r.got or "", r.score,
                        r.matches, round(r.duration_ms), r.ok])
    print("[bench] Rapport -> " + name)
    return name


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pi",     action="store_true")
    p.add_argument("--report", action="store_true")
    args = p.parse_args()

    detector   = CardDetector(min_area=1500)
    recognizer = CardRecognizer(PLATEST_DIR)
    cards      = [t.id for t in recognizer._templates]

    if not cards:
        print("[bench] Aucune carte dans PLATEST -- abandonne.")
        return

    print()
    print("=" * 55)
    print("  S.T.E.A.M Plate Bench")
    print("=" * 55)
    print("  " + str(len(cards)) + " carte(s) chargees : " + ", ".join(c.replace("plate_","") for c in cards))
    print()
    print("  ESPACE = capturer et tester")
    print("  R      = recharger templates")
    print("  Q/ESC  = terminer session")
    print()

    cam_type, cam = make_camera(args.pi)
    session       = Session()
    last_result   = None
    last_scores   = []
    snap_count    = 0
    prev_time     = time.time()
    expected      = None
    waiting_card  = True

    while True:
        # Demander quelle carte avant chaque test
        if waiting_card:
            stop_camera(cam_type, cam)
            cv2.destroyAllWindows()
            expected = interactive_ask_card(cards)
            if expected == "__end__":
                break
            cam_type, cam = make_camera(args.pi)
            waiting_card  = False
            last_result   = None
            last_scores   = []
            print("  Montrez la carte [" + expected.replace("plate_","").capitalize() + "] puis appuyez ESPACE")

        ok, frame = read_frame(cam_type, cam)
        if not ok or frame is None:
            continue

        now = time.time()
        fps = 1.0 / max(now - prev_time, 0.001)
        prev_time = now
        display   = frame.copy()

        region = detector.detect(frame)

        if region is not None:
            last_scores = draw_all_scores(display, recognizer, region)
            corners = region.corners.astype(np.int32)
            cv2.polylines(display, [corners], True, ORANGE, 2)
            warp_thumb = cv2.resize(region.warped, (160, 160))
            display[10:170, 10:170] = warp_thumb

        put(display, "FPS: " + str(round(fps,1)), (185, 25), GRAY)
        put(display, "Carte attendue : " + expected.replace("plate_","").upper(),
            (185, 55), GOLD, 0.65, 1)
        put(display, "ESPACE=capturer  R=reload  Q=quitter",
            (10, display.shape[0]-10), GRAY, 0.45)

        if last_result is not None:
            draw_result_banner(display, last_result[0], last_result[1], last_result[2])

        cv2.imshow("S.T.E.A.M -- Plate Bench", display)
        key = cv2.waitKey(1) & 0xFF

        if key in (ord("q"), 27):
            break

        elif key == ord("r"):
            recognizer.reload()
            print("[bench] Templates recharges")

        elif key == ord(" "):
            # Capture et test
            t0 = time.time()
            reg2 = detector.detect(frame)
            if reg2 is None:
                print("[bench] Aucun losange detecte -- reessaie")
                continue
            result  = recognizer.recognize(reg2.warped)
            dur_ms  = (time.time() - t0) * 1000
            got     = result.card_id if result else None
            score   = result.score   if result else 0.0
            matches = result.matches if result else 0
            ok_flag = got == expected

            tr = TestResult(expected=expected, got=got, score=score,
                            matches=matches, duration_ms=dur_ms, ok=ok_flag)
            session.results.append(tr)
            last_result = (result, expected, dur_ms)

            emoji = "OK" if ok_flag else ("RATE" if got is None else "ERREUR")
            print("[bench] " + emoji + " | attendu=" + expected.replace("plate_","") +
                  " | obtenu=" + (got or "rien").replace("plate_","") +
                  " | score=" + str(round(score,3)) +
                  " | " + str(round(dur_ms)) + "ms")

            # Sauvegarder snapshot
            snap_count += 1
            fname = "bench_snap_" + str(snap_count).zfill(3) + "_" + emoji + ".jpg"
            cv2.imwrite(fname, display)

            # Passer a la carte suivante apres 2s
            cv2.imshow("S.T.E.A.M -- Plate Bench", display)
            cv2.waitKey(2000)
            waiting_card = True

    stop_camera(cam_type, cam)
    cv2.destroyAllWindows()

    if session.total == 0:
        print("[bench] Aucun test effectue.")
        return

    # Afficher synthese
    print()
    print("=" * 55)
    print("  RESULTATS FINAUX")
    print("=" * 55)
    print("  Correct  : " + str(session.correct) + "/" + str(session.total))
    print("  Manques  : " + str(session.missed))
    print("  Erreurs  : " + str(session.wrong))
    print("  Precision: " + str(round(session.accuracy, 1)) + "%")

    summary_img = draw_summary(session, cards)
    cv2.imshow("Bench Summary", summary_img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    if args.report:
        save_csv(session, cards)


if __name__ == "__main__":
    main()
