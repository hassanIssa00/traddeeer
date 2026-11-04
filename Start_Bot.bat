@echo off
title MT5 Trading Bot - Automated Engine
cd /d "%~dp0"
echo =======================================================
echo   Starting MT5 Automated Trading Bot...
echo =======================================================
python trading_bot.py --goal 20 %*
pause
