@echo off
REM Start LoadFlow Server
REM This script will start the Flask development server

echo ================================
echo   LoadFlow - Load Balancer Simulator
echo   Starting Server...
echo ================================
echo.

REM Kill any existing Python processes on port 5000
for /f "tokens=5" %%a in ('netstat -ano ^| find ":5000"') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM Wait a moment for port to be released
timeout /t 2 /nobreak

REM Start Flask
cd /d "%~dp0"
python -c "from app import app; app.run(host='127.0.0.1', port=5000, debug=True)"

pause
