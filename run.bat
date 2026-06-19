@echo off
REM Start ADT MCP server and open the web admin in the browser.
setlocal

cd /d "%~dp0"

set "URL=http://127.0.0.1:8765/"
set "PORT=8765"

REM Kill any old server still holding the port so the new code is loaded.
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do (
    echo Killing old server PID %%P on port %PORT%
    taskkill /f /pid %%P >nul 2>&1
)

REM Open the browser after a short delay so the server has time to bind.
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start "" %URL%"

echo Starting ADT MCP on %URL%  (MCP at /mcp, admin at /)
python -m adt_mcp

endlocal
