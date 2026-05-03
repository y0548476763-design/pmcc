@echo off
color 0E
title PMCC Dashboard :8501
cd /d "%~dp0"
echo Starting Streamlit Dashboard...
streamlit run app.py --server.port 8501
pause
