#!/bin/bash
# scripts/download_placeholders.sh
# Télécharge les vidéos placeholder sur STYX via yt-dlp.
# Usage: bash scripts/download_placeholders.sh

set -e
cd "$(dirname "$0")/.."

if ! command -v yt-dlp &> /dev/null; then
    echo "[install] yt-dlp non trouvé, installation..."
    pip install yt-dlp
fi

DL() {
    local OUT="$1"
    local URL="$2"
    if [ -f "$OUT" ]; then
        echo "[skip] $OUT déjà présent"
        return
    fi
    echo "[dl] $OUT..."
    yt-dlp --download-sections "*0:00-5:00" \
        -f "bestvideo[height<=720]+bestaudio/best[height<=720]" \
        --merge-output-format mp4 \
        -o "$OUT" "$URL"
    echo "[ok] $OUT"
}

# ── vampire ─────────────────────────────────────────────────────────────────────────
DL "assets/video/vampire/vampire_placeholder.mp4" \
   "https://www.youtube.com/watch?v=OaedQzCtKgw"

DL "assets/video/vampire/transylvania_placeholder.mp4" \
   "https://www.youtube.com/watch?v=NdNg7KT8e_Q"

# ── autres cartes (à compléter) ───────────────────────────────────────────────────
# DL "assets/video/bougie/bougie_placeholder.mp4"       "https://..."
# DL "assets/video/cellule/cellule_placeholder.mp4"     "https://..."
# DL "assets/video/chaudron/chaudron_placeholder.mp4"   "https://..."
# DL "assets/video/dague/dague_placeholder.mp4"         "https://..."

echo ""
echo "=== Vidéos disponibles ==="
find assets/video -name "*.mp4" | sort
