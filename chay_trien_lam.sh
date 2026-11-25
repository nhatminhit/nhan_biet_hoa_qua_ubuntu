#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "==================================================="
echo " FRUITGUARD AI - CHE DO TRIEN LAM AN TOAN (UBUNTU)"
echo "==================================================="

if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python exhibition_launcher.py
else
    exec python3 exhibition_launcher.py
fi
