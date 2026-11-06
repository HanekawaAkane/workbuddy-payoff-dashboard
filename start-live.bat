@echo off
cd /d "%~dp0"
echo WorkBuddy Token Dashboard - live local server
echo Browser: http://127.0.0.1:8765/
echo Page auto-reloads when WorkBuddy writes new usage data.
echo Press Ctrl+C to stop.
python scripts\serve.py --open
if errorlevel 1 pause
