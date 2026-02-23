@echo off
title Real Estate AI Bot
echo.
echo ==================================
echo   REAL ESTATE AI BOT - Bashlayir
echo ==================================
echo.
cd /d "%~dp0"
call venv\Scripts\activate
echo [OK] Virtual muhit aktivleshdi
echo [OK] Bot ishi bashlayir...
echo.
python main.py
echo.
echo Bot dayandi. Kechmek ucun her hansi duyme basin...
pause
