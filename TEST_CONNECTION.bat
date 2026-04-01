@echo off
REM Quick Connection Test Script
REM Use this to diagnose connection issues

echo.
echo ================================================
echo   LoadFlow - Connection Test
echo ================================================
echo.

REM Check if server is running
echo [1/3] Checking if server is running...
netstat -ano | findstr ":5000" > nul
if %errorlevel% equ 0 (
    echo     ✅ Server is running on port 5000
) else (
    echo     ❌ Server is NOT running!
    echo.
    echo     Start the server with: python app.py
    pause
    exit /b 1
)

REM Test with curl/powershell
echo.
echo [2/3] Testing connection to http://127.0.0.1:5000...
powershell -Command "try { $response = Invoke-WebRequest -Uri 'http://127.0.0.1:5000/' -UseBasicParsing -TimeoutSec 5; if ($response.StatusCode -eq 200) { Write-Host '    ✅ Server responding (Status 200)' } } catch { Write-Host '    ❌ Connection failed' }"

REM Open browser
echo.
echo [3/3] Opening browser...
start http://127.0.0.1:5000/
echo     ✅ Browser should open shortly

echo.
echo ================================================
echo   If browser didn't open automatically:
echo   Visit: http://127.0.0.1:5000/
echo ================================================
echo.

pause
