#!/bin/bash
# Test rapide sans GUI — vérifie caméra + YOLO sur RPi
cd "$(dirname "$0")/../.."
source .venv/bin/activate
python3 - <<'EOF'
import cv2, sys

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
if not cap.isOpened():
    print("[ERROR] Caméra non disponible sur /dev/video0")
    sys.exit(1)
ret, frame = cap.read()
cap.release()
if not ret:
    print("[ERROR] Frame non lisible")
    sys.exit(1)
print(f"[OK] Caméra : {frame.shape[1]}x{frame.shape[0]}")

from ultralytics import YOLO
model = YOLO("yolov8n.pt")
results = model(frame, verbose=False)
print(f"[OK] YOLO : {len(results[0].boxes)} détections sur frame test")
print("Environnement RPi OK.")
EOF
