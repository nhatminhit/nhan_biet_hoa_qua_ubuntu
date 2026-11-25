@echo off
setlocal enabledelayedexpansion
title FruitGuard AI - Cai dat moi truong tu dong
chcp 65001 > nul
cd /d "%~dp0"

echo ============================================================
echo   FRUITGUARD AI - CAI DAT TU DONG CHO MAY MOI
echo ============================================================
echo.

REM --- Buoc 1: Tim Python 3 ---
set "PY_CMD="
where py >nul 2>nul
if !errorlevel! equ 0 (
    py -3 --version >nul 2>nul
    if !errorlevel! equ 0 set "PY_CMD=py -3"
)
if not defined PY_CMD (
    where python >nul 2>nul
    if !errorlevel! equ 0 (
        python --version >nul 2>nul
        if !errorlevel! equ 0 set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    echo [LOI] May tinh nay chua cai Python 3 hoac chua them vao PATH.
    echo       Vui long tai Python 3.10 - 3.12 tai: https://www.python.org/downloads/
    echo       Luu y: Nho tich chon "Add Python to PATH" khi cai dat!
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%v in ('!PY_CMD! --version') do set "PY_VER=%%v"
echo [1/5] Da tim thay: !PY_VER!

REM --- Buoc 2: Kiem tra hoac tao moi moi truong ao .venv ---
set "NEED_VENV=0"
if not exist ".venv\Scripts\python.exe" (
    set "NEED_VENV=1"
) else (
    ".venv\Scripts\python.exe" -c "import sys; print(sys.executable)" >nul 2>nul
    if !errorlevel! neq 0 (
        echo [!] Phat hien .venv tu may cu khong tuong thich, dang tao lai...
        rmdir /s /q ".venv"
        set "NEED_VENV=1"
    )
)

if "!NEED_VENV!"=="1" (
    echo [2/5] Dang tao moi truong ao Python (.venv)...
    !PY_CMD! -m venv .venv
    if !errorlevel! neq 0 (
        echo [LOI] Khong the tao moi truong ao .venv.
        pause
        exit /b 1
    )
) else (
    echo [2/5] Moi truong ao .venv da san sang.
)

set "VENV_PY=.venv\Scripts\python.exe"

REM --- Buoc 3: Cai dat thu vien Python ---
echo [3/5] Dang cap nhat pip va cai dat thu vien Python (co the mat 2-5 phut)...
"%VENV_PY%" -m pip install --upgrade pip
if !errorlevel! neq 0 (
    echo [CANH BAO] Khong cap nhat duoc pip, tiep tuc cai dat thu vien...
)

if exist "requirements.txt" (
    "%VENV_PY%" -m pip install -r requirements.txt
) else (
    "%VENV_PY%" -m pip install ultralytics opencv-python numpy pillow customtkinter fastapi uvicorn pydantic
)
if !errorlevel! neq 0 (
    echo [LOI] Cai dat thu vien Python that bai. Vui long kiem tra ket noi mang.
    pause
    exit /b 1
)

REM --- Buoc 4: Kiem tra / dong goi giao dien Web Dashboard ---
echo [4/5] Dang kiem tra giao dien Web Dashboard...
where npm >nul 2>nul
if !errorlevel! equ 0 (
    if not exist "web\node_modules" (
        echo       Dang cai dat thu vien giao dien React (npm install)...
        pushd web
        call npm install
        if !errorlevel! neq 0 (
            popd
            echo [CANH BAO] npm install that bai. Se dung ban giao dien da dong goi san (neu co).
            goto :verify
        )
        popd
    )
    echo       Dang dong goi giao dien React (npm run build)...
    pushd web
    call npm run build
    popd
) else (
    if exist "web\dist\index.html" (
        echo       Khong co Node.js - su dung ban Web Dashboard da dong goi san (web\dist).
    ) else (
        echo [CANH BAO] May chua cai Node.js va chua co web\dist.
        echo            Hay cai Node.js (https://nodejs.org) hoac copy thu muc web\dist tu may cu.
    )
)

:verify
REM --- Buoc 5: Kiem tra sau cai dat ---
echo [5/5] Dang kiem tra toan bo thu vien va tep bat buoc...
"%VENV_PY%" -c "import cv2, torch, ultralytics, customtkinter, fastapi, uvicorn, pydantic, PIL, warehouse_manager; print('      [OK] Tat ca thu vien Python hoat dong binh thuong!')"
if !errorlevel! neq 0 (
    echo [LOI] Kiem tra thu vien that bai.
    pause
    exit /b 1
)

set "MISSING_FILES="
for %%f in (best.pt yolov8n.pt demo_conveyor.mp4 app_gui.py api_server.py) do (
    if not exist "%%f" set "MISSING_FILES=!MISSING_FILES! %%f"
)
if defined MISSING_FILES (
    echo [CANH BAO] Thieu cac tep sau:!MISSING_FILES!
) else (
    echo       [OK] Day du model AI va tep chuong trinh.
)

echo.
echo ============================================================
echo   CAI DAT HOAN TAT!
echo   De chay du an, hay nhap dup vao:
echo     - CHAY_TRIEN_LAM_AN_TOAN.bat (Chay ca GUI + Web Dashboard)
echo     - CHAY_WEB_DASHBOARD.bat     (Chi chay Web Dashboard)
echo     - CHAY_GIAO_DIEN_GUI.bat     (Chi chay Desktop GUI)
echo ============================================================
echo.
pause
exit /b 0
