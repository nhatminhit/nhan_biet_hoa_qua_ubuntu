@echo off
title FruitGuard AI - Che do Trien lam An toan
chcp 65001 > nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" exhibition_launcher.py
) else (
    python exhibition_launcher.py
)
if errorlevel 1 pause
