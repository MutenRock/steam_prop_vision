#!/bin/bash
# Lance le setup GUI (puis main.py automatiquement)
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONPATH=.
python3 gui_setup.py
