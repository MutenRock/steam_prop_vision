#!/bin/bash
# S.T.E.A.M Vision — STYX run script
# Usage : bash scripts/linux_run.sh [--loxone 192.168.1.50] [--no-udp] [--no-audio]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

cd "$ROOT"
source .venv/bin/activate

echo "=== S.T.E.A.M Vision — STYX ==="
python apps/rpi/main.py "$@"
