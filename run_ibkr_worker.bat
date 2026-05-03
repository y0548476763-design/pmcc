@echo off
color 0A
title PMCC IBKR Worker :8001
cd /d "%~dp0"
echo Starting IBKR Worker Service on port 8001...
python services/ibkr_worker.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Worker failed to start. Check if Python is installed and requirements are met.
)
pause
