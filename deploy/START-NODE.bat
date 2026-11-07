@echo off
setlocal
set "ROOT=%~dp0.."
pushd "%ROOT%"

rem ---- args: %1=token  %2=port  %3=device name ----
set "TOKEN=%~1"
set "PORT=%~2"
set "DEV=%~3"
if "%TOKEN%"=="" set "TOKEN=change-me"
if "%PORT%"=="" set "PORT=8765"
if "%DEV%"=="" set "DEV=%COMPUTERNAME%"

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py"
if not defined PY (
  for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do (
    if exist "%%D\python.exe" if not defined PY set "PY=%%D\python.exe"
  )
)
if not defined PY (
  for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\python\pkgs\*") do (
    if exist "%%D\python.exe" if not defined PY set "PY=%%D\python.exe"
  )
)
if not defined PY (
  for %%R in ("%ProgramData%\workbuddy" "D:\ProgramData\workbuddy" "C:\ProgramData\workbuddy" "%LOCALAPPDATA%\Programs\WorkBuddy" "%ProgramFiles%\WorkBuddy") do (
    if exist "%%~R\resources\vendor\python\python.exe" if not defined PY set "PY=%%~R\resources\vendor\python\python.exe"
  )
)
if not defined PY (
  echo [ERROR] No Python found. Install Python 3.9+ or check the WorkBuddy install folder.
  pause
  popd
  exit /b 1
)

echo Device: %DEV%
echo Python: %PY%
echo Listen: 0.0.0.0:%PORT%  token: %TOKEN%
echo Others on your LAN / Tailscale can fetch http://YOUR-IP:%PORT%/api/bundle?token=%TOKEN%
echo Press Ctrl+C to stop.
echo.
"%PY%" "%ROOT%\scripts\serve.py" --host 0.0.0.0 --port %PORT% --token "%TOKEN%" --bundle-device "%DEV%" --no-prompts
pause
popd
