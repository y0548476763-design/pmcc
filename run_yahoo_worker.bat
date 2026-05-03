@echo off
color 0B
title PMCC Yahoo Worker :8002
cd /d "%~dp0"
echo Starting Yahoo Finance Worker Service...
python services/yahoo_worker.py
pause
