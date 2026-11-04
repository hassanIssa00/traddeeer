@echo off
title MT5 Bot - DRY RUN
cd /d "%~dp0"
echo [DRY RUN - Analysis only, no real trades]
python trading_bot.py --dry-run --goal 20
pause
