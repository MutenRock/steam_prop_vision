#!/bin/bash
set -e

echo "=== S.T.E.A.M Prop Vision — Install RPi (Trixie/aarch64) ==="

sudo apt update
sudo apt install -y python3-venv python3-pip ffmpeg \
    python3-tk libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements_rpi.txt

echo ""
echo "=== Installation terminée ==="
echo "Lancer : source .venv/bin/activate && python3 -m gui.app"
