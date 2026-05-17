#!/bin/bash
# add_plate.sh - Ajoute ou met à jour une plate dans PLATEST/
# Usage : ./add_plate.sh <nom> <image>
# Exemple : ./add_plate.sh bougie /tmp/photo.jpg

set -euo pipefail
cd "$(dirname "$0")"

NAME="${1:-}"
IMG="${2:-}"

if [ -z "$NAME" ] || [ -z "$IMG" ]; then
  echo "Usage : ./add_plate.sh <nom> <image>"
  echo "Ex    : ./add_plate.sh bougie photo.jpg"
  exit 1
fi

if [ ! -f "$IMG" ]; then
  echo "[add_plate] ERREUR : fichier introuvable : $IMG"
  exit 1
fi

NAME="$(echo "$NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '_' | tr '-' '_')"
PLATE_DIR="PLATEST/plate_${NAME}"

[ -f .venv/bin/activate ] && source .venv/bin/activate

python3 -c "import cv2" >/dev/null 2>&1 || {
  echo "[add_plate] ERREUR : cv2 manquant"
  exit 1
}

mkdir -p "$PLATE_DIR"
echo "[add_plate] Plate   : plate_${NAME}"
echo "[add_plate] Source  : $IMG"
echo "[add_plate] Dossier : $PLATE_DIR"

# Nettoie les anciennes images (update propre)
find "$PLATE_DIR" -maxdepth 1 -type f \( \
  -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.webp" \
\) -delete

EXT="${IMG##*.}"
EXT="$(echo "$EXT" | tr '[:upper:]' '[:lower:]')"
DEST="$PLATE_DIR/${NAME}.${EXT}"
cp "$IMG" "$DEST"
echo "[add_plate] Source copiée → $DEST"

echo "[add_plate] Split en cours..."
python3 split_plate.py "$DEST"

echo ""
echo "[add_plate] ✅ Done — contenu de $PLATE_DIR :"
ls -1 "$PLATE_DIR"