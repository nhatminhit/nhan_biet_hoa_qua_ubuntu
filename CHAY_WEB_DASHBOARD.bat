@echo off
title Fruit Conveyor AI - Web Dashboard
chcp 65001 > nul
cd /d "%~dp0"
echo ===================================================
echo  Dang khoi dong Dashboard FastAPI + React...
echo ===================================================
if not exist "web\node_modules" (
    echo [1/3] Dang cai giao dien React lan dau...
    pushd web
    call npm install
    if errorlevel 1 goto :error
    popd
)
echo [2/3] Dang dong goi giao dien...
pushd web
call npm run build
if errorlevel 1 goto :error
popd
echo [3/3] Dang mo trung tam dieu hanh tai http://127.0.0.1:8000
start "" "http://127.0.0.1:8000"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m uvicorn api_server:app --host 0.0.0.0 --port 8000
) else (
    python -m uvicorn api_server:app --host 0.0.0.0 --port 8000
)
goto :end
:error
echo Khong the khoi dong dashboard. Vui long xem loi phia tren.
:end
pause
