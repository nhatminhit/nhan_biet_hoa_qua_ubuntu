#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
export PATH="$HOME/.local/node/bin:$PATH"

echo "==================================================="
echo " Dang khoi dong Dashboard FastAPI + React..."
echo "==================================================="

if [ ! -f "web/dist/index.html" ]; then
    if command -v npm >/dev/null 2>&1; then
        echo "[1/2] Dang build giao dien React..."
        (cd web && [ -d node_modules ] || npm install)
        (cd web && npm run build)
    else
        echo "[CANH BAO] Khong tim thay npm va chua co web/dist."
    fi
fi

echo "Dang mo trung tam dieu hanh tai http://127.0.0.1:8000"
if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python -m uvicorn api_server:app --host 0.0.0.0 --port 8000
else
    exec python3 -m uvicorn api_server:app --host 0.0.0.0 --port 8000
fi
