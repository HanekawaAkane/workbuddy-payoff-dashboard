@echo off
cd /d "%~dp0"
set "SYNC=%~1"
if "%SYNC%"=="" set "SYNC=output\bundles"
echo Exporting this device to: %SYNC%
python scripts\export.py --device %COMPUTERNAME% --out "%SYNC%\%COMPUTERNAME%.json"
if errorlevel 1 (
  echo.
  echo Failed. Make sure Python 3.9+ is on PATH.
  pause
)
