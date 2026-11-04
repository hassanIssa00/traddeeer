@echo off
title MT5 Trading Bot - Dry Run Mode
cd /d "%~dp0"
echo =======================================================
echo   Starting MT5 Bot in Dry-Run Mode (Analysis Only)...
echo =======================================================
python trading_bot.py --dry-run --goal 20 %*
pause
