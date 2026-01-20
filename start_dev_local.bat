@echo off
title Monter Development Servers
color 0B

echo =================================
echo Monter Development Environment
echo =================================
echo.
echo This will start both Backend and Frontend servers
echo.
echo Backend: http://localhost:8001
echo Frontend: http://localhost:3000
echo.
echo Press Ctrl+C to stop both servers
echo =================================
echo.

REM 백엔드 서버 시작 (새 창)
start "Monter Backend" cmd /k "cd /d C:\Users\Administrator\Desktop\web_backend\monter_web_backend && python main.py"

REM 잠시 대기 (백엔드 서버 시작 시간 확보)
timeout /t 3 /nobreak >nul

