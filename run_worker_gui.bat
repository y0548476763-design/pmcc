@echo off
color 0E
title PMCC Worker Sandbox GUI
cd /d "%~dp0"
echo Starting IBKR Worker Sandbox GUI...
echo.
echo [DEBUG] Python version:
python --version
echo.
echo [DEBUG] Trying to run Streamlit...
python -m streamlit run services/worker_gui.py --server.port 8502
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [CRITICAL ERROR] Streamlit failed to start. 
    echo Possible causes:
    echo 1. Streamlit is not installed (run: pip install streamlit)
    echo 2. Syntax error in services/worker_gui.py
    echo 3. Port 8502 is already in use.
)
pause
