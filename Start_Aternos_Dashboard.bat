@echo off
title Aternos 24/7 Keep-Alive Launcher
echo ===================================================
echo   Aternos 24/7 Keep-Alive & Dashboard Launcher
echo ===================================================
echo.

:: Open browser dashboard
start http://localhost:8000

:: Start python application in background if not already running
tasklist /FI "IMAGENAME eq python.exe" 2>NUL | find /I /N "python.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [INFO] Aternos Bot is already running!
) else (
    echo [INFO] Starting Aternos Bot engine...
    python -m src.main
)
