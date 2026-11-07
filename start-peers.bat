@echo off
cd /d "%~dp0"
echo WorkBuddy Token Dashboard - auto pull from online peers
echo Config: config\peers.json
echo Browser: http://127.0.0.1:8765/
echo Press Ctrl+C to stop.
if not exist "config\peers.json" (
  echo.
  echo [ERROR] config\peers.json not found.
  echo Copy config\peers.example.json and fill in the peer URLs and token.
  pause
  exit /b 1
)
python scripts\serve.py --peers config\peers.json --poll-seconds 60 --open
if errorlevel 1 pause
