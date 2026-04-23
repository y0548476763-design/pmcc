@echo off
color 0e
title PMCC NextOffice v3.0 — 3-Server Mode
cd c:\Users\User\Desktop\pmcc1

echo ============================================================
echo  PMCC NextOffice — Starting 3 services in parallel
echo ============================================================
echo.

echo [1/3] Starting Yahoo API server on port 8001...
start "PMCC Yahoo API :8001" cmd /k "color 0A & python -m uvicorn api_yahoo:app --port 8001 --reload"

timeout /t 2 /nobreak > nul

echo [2/3] Starting IBKR API server on port 8002...
start "PMCC IBKR API :8002" cmd /k "color 0B & python -m uvicorn api_ibkr:app --port 8002 --reload"

timeout /t 3 /nobreak > nul

echo [3/3] Starting Streamlit Dashboard on port 8501...
start "PMCC Dashboard :8501" cmd /k "color 09 & streamlit run app.py --server.port 8501"

timeout /t 4 /nobreak > nul
start http://localhost:8501

echo.
echo All 3 services started. You can close this window.
pause
