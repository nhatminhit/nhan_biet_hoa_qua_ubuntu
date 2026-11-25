#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "==================================================="
echo " Dang khoi dong Giao dien Desktop (CustomTkinter)..."
echo "==================================================="

if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python app_gui.py
else
    exec python3 app_gui.py
fi
