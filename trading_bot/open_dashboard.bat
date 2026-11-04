@echo off
title MT5 Bot - Web Dashboard
cd /d "%~dp0"
echo.
echo ============================================
echo   MT5 Trading Bot - Web Dashboard
echo   Opening: http://localhost:8050
echo ============================================
echo.
python web_dashboard.py
pause
