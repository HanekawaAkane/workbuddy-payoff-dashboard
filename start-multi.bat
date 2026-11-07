@echo off
cd /d "%~dp0"
set "SYNC=%~1"
if "%SYNC%"=="" set "SYNC=output\bundles"
echo WorkBuddy Token Dashboard - multi-device
echo Sync folder: %SYNC%
echo Browser: http://127.0.0.1:8765/
echo Press Ctrl+C to stop.
python scripts\serve.py --sources "%SYNC%" --open
if errorlevel 1 pause
