"""
tools/card_test.py
Test interactif de la pipeline détection+reconnaissance.

Usage :
  python tools/card_test.py                   # webcam
  python tools/card_test.py --image photo.jpg # image statique
  python tools/card_test.py --platest PLATEST # dossier custom
  python tools/card_test.py --save-crops      # sauvegarde les warps pour debug

Commandes :
  Q / ESC  → quitter
  S        → sauvegarder le warp courant dans PLATEST/<id>/images/
  R        → recharger les templates PLATEST
"""
from __future__ import annotations
import argparse
import sys
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2

from steamcore.recognition.card_detector  import CardDetector
from steamcore.recognition.card_recognizer import CardRecognizer


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--image",      default=None)
    p.add_argument("--camera",     default=0, type=int)
    p.add_argument("--platest",    default="PLATEST")
    p.add_argument("--save-crops", action="store_true")
    return p.parse_args()


def draw_overlay(frame, region, result, fps):
    out = CardDetector.draw_debug(frame, region)
    y   = 30

    # FPS
    cv2.putText(out, f"FPS: {fps:.1f}", (10, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)
    y += 28

    if result:
        color = (80, 220, 80)
        cv2.putText(out, f"CARTE: {result.label}", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        y += 28
        cv2.putText(out, f"score={result.score:.3f}  matches={result.match_count}", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)
        y += 24
        cv2.putText(out, f"action: {result.trigger_action}", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 200, 255), 1)
    else:
        cv2.putText(out, "Carte non reconnue", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 80, 220), 1)
    return out


def main():
    args       = parse_args()
    detector   = CardDetector()
    recognizer = CardRecognizer(args.platest)

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            print(f"Impossible de lire : {args.image}")
            return
        region = detector.detect(frame)
        if region:
            result = recognizer.recognize(region.warped)
            out    = draw_overlay(frame, region, result, 0)
            cv2.imshow("S.T.E.A.M — Card Test", out)
            cv2.imshow("Warp 400x400", region.warped)
            cv2.waitKey(0)
        else:
            print("Aucun losange détecté dans l'image")
            cv2.imshow("Input", frame)
            cv2.waitKey(0)
        cv2.destroyAllWindows()
        return

    # Mode webcam
    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    print("\n[card_test] Démarré — commandes : S=sauvegarder warp | R=recharger | Q=quitter\n")

    prev_time  = time.time()
    last_warp  = None
    save_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        now = time.time()
        fps = 1.0 / max(now - prev_time, 0.001)
        prev_time = now

        region = detector.detect(frame)
        result = None

        if region is not None:
            result   = recognizer.recognize(region.warped)
            last_warp = region.warped
            out      = draw_overlay(frame, region, result, fps)
            cv2.imshow("Warp 400x400", region.warped)
        else:
            out = frame.copy()
            cv2.putText(out, "Aucun losange", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 80, 220), 2)
            cv2.putText(out, f"FPS: {fps:.1f}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)

        cv2.imshow("S.T.E.A.M — Card Test", out)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key == ord('s') and last_warp is not None:
            # Sauvegarder le warp comme nouvelle image de référence
            card_id = input("ID de la carte à sauvegarder (ex: plate01) : ").strip()
            if card_id:
                dst = Path(args.platest) / card_id / "images"
                dst.mkdir(parents=True, exist_ok=True)
                save_count += 1
                fname = dst / f"ref_{save_count:03d}.jpg"
                cv2.imwrite(str(fname), last_warp)
                print(f"[saved] {fname}")
        elif key == ord('r'):
            recognizer.reload()
            print("[reload] Templates rechargés")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
