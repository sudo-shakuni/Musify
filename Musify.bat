@echo off
title Musify
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" desktop.py
) else (
    start "" python desktop.py
)
