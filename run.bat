@echo off
title Spotify Playlist Cloner and Downloader
cd /d "%~dp0"

echo ========================================================
echo   Spotify Playlist Cloner and Downloader
echo ========================================================
echo.

:: Check Python installation
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in PATH!
    echo Please install Python 3.10+ from python.org and check "Add Python to PATH".
    pause
    exit /b 1
)

:: Free port 8800 if an old instance was left running in the background
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8800" ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)

:: Create virtual environment if not already present
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating isolated Python virtual environment...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: Install requirements if first run
if not exist ".venv\.installed" (
    echo [2/3] Installing dependencies for first-time launch...
    .venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
    echo installed > ".venv\.installed"
) else (
    echo [2/3] Dependencies verified.
)

:: Verify FFmpeg audio engine
echo [3/3] Verifying FFmpeg audio engine...
.venv\Scripts\python.exe setup_ffmpeg.py

echo.
echo ========================================================
echo   Launching Spotify Playlist Cloner & Downloader
echo ========================================================
echo.

.venv\Scripts\python.exe desktop.py

pause
