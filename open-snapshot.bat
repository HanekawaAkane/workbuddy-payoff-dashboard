@echo off
cd /d "%~dp0"
echo WorkBuddy Token Dashboard - rebuild snapshot and open it.
python scripts\run.py --open
if errorlevel 1 (
  echo.
  echo Failed. Make sure Python 3.9+ is on PATH.
  pause
)
