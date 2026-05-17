#!/bin/bash
# split_all_plates.sh
# Split toutes les images sources de PLATEST/ en 4 crops (top/bottom/left/right).
# Ne re-split PAS les images deja splittees (_top/_bottom/_left/_right).
# Usage : ./split_all_plates.sh [--overlap 0.15] [--platest PLATEST]

cd "$(dirname "$0")"

OVERLAP="0.15"
PLATEST="PLATEST"

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --overlap) OVERLAP="$2"; shift 2 ;;
    --platest) PLATEST="$2"; shift 2 ;;
    *) echo "[split_all] option inconnue : $1"; exit 1 ;;
  esac
done

# Verif venv
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi

python3 -c "import cv2" 2>/dev/null || { echo "[split_all] ERREUR : cv2 manquant"; exit 1; }

echo "[split_all] PLATEST : $PLATEST"
echo "[split_all] Overlap  : ${OVERLAP}"
echo ""

TOTAL=0
SKIPPED=0

for plate_dir in "$PLATEST"/*/; do
  plate=$(basename "$plate_dir")
  echo "── $plate"

  for img in "$plate_dir"*.jpg "$plate_dir"*.jpeg "$plate_dir"*.png; do
    [ -f "$img" ] || continue

    # Ignore les fichiers deja splittes
    base=$(basename "$img")
    if [[ "$base" == *_top.* || "$base" == *_bottom.* || "$base" == *_left.* || "$base" == *_right.* ]]; then
      echo "   skip (deja split) : $base"
      ((SKIPPED++))
      continue
    fi

    echo "   split : $base"
    python3 split_plate.py "$img" --overlap "$OVERLAP"
    ((TOTAL++))
  done
done

echo ""
echo "[split_all] Done : $TOTAL image(s) splitee(s), $SKIPPED ignoree(s)."
