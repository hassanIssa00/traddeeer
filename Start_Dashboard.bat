@echo off
title MT5 Trading Bot - Web Dashboard
cd /d "%~dp0"
echo =======================================================
echo   Starting MT5 Trading Bot Web Dashboard...
echo   Opening: http://127.0.0.1:8050/
echo =======================================================
python web_server.py
pause
