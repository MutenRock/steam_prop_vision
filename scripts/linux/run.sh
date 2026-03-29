#!/bin/bash
cd "$(dirname "$0")/../.."
source .venv/bin/activate
export DISPLAY=:0
python3 -m gui.app
