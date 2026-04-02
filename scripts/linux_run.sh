#!/usr/bin/env bash
set -euo pipefail

# Remonte à la racine du projet (un niveau au-dessus de scripts/)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

export PYTHONPATH="$PROJECT_ROOT:${PYTHONPATH:-}"

echo "=== S.T.E.A.M Vision — STYX ==="
echo "ROOT   : $PROJECT_ROOT"
echo "PYTHON : $(python --version)"

exec python apps/rpi/main.py "$@"
