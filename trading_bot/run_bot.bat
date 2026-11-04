@echo off
title MT5 Trading Bot
cd /d "%~dp0"
echo.
echo ============================================
echo   MT5 Trading Bot - بوت التداول الآلي
echo ============================================
echo.

if "%1"=="--close-all" (
    python trading_bot.py --close-all
    pause
    exit
)

if "%1"=="dry" (
    echo [DRY RUN MODE - No real trades]
    python trading_bot.py --dry-run %2 %3 %4
) else (
    python trading_bot.py %*
)

pause
