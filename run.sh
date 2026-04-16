#!/bin/bash
# run.sh - S.T.E.A.M Vision v2
cd "$(dirname "$0")"

# Verif venv
if [ ! -d .venv ]; then
  echo "[run] ERREUR : venv manquant."
  echo "[run] Creez-le : python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

# Active venv
source .venv/bin/activate || { echo "[run] ERREUR : impossible d'activer le venv"; exit 1; }

# Verif DISPLAY
if [ -z "$DISPLAY" ]; then
  export DISPLAY=:0
  echo "[run] DISPLAY=:0 force"
fi

# Verif opencv
python3 -c "import cv2" 2>/dev/null \
  && echo "[run] OpenCV OK" \
  || { echo "[run] ERREUR : cv2 manquant -> pip install opencv-python"; exit 1; }

echo "[run] Lancement S.T.E.A.M Vision v2..."
python3 gui_setup.py
