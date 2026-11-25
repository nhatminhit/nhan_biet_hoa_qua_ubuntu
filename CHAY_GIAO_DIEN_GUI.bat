@echo off
title Fruit Conveyor AI - Desktop GUI
chcp 65001 > nul
cd /d "%~dp0"
echo ===================================================
echo  Dang khoi dong Giao dien Desktop (CustomTkinter)...
echo ===================================================
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app_gui.py
) else (
    python app_gui.py
)
pause
