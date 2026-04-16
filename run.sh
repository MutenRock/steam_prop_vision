#!/bin/bash
# run.sh - S.T.E.A.M Vision v2
# Usage:
#   ./run.sh            -> ouvre le GUI de configuration
#   ./run.sh --debug    -> lance directement en mode debug
#   ./run.sh --escape   -> lance directement en mode escape (prod)
cd "$(dirname "$0")"

MODE=""
if [[ "$1" == "--debug" || "$1" == "--escape" ]]; then
  MODE="$1"
fi

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

if [ -n "$MODE" ]; then
  echo "[run] Lancement direct : mode $MODE"
  python3 main.py "$MODE"
else
  echo "[run] Lancement GUI S.T.E.A.M Vision v2..."
  python3 gui_setup.py
fi
