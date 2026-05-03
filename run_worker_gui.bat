@echo off
color 0E
title PMCC Worker Sandbox GUI
cd /d "%~dp0"
echo Starting IBKR Worker Sandbox GUI...
echo If the browser does not open automatically, go to: http://localhost:8502
python -m streamlit run services/worker_gui.py --server.port 8502
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Streamlit failed to start. 
    echo Trying alternative command...
    streamlit run services/worker_gui.py --server.port 8502
)
pause
