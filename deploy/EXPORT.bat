@echo off
setlocal
set "ROOT=%~dp0.."
pushd "%ROOT%"
set "SYNC=%~1"
if "%SYNC%"=="" set "SYNC=%ROOT%\out"
if not exist "%SYNC%" mkdir "%SYNC%" 2>nul

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py"

rem WorkBuddy ships its own Python. Try the per-user binaries folder first.
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
rem Then the app install roots.
if not defined PY (
  for %%R in ("%ProgramData%\workbuddy" "D:\ProgramData\workbuddy" "C:\ProgramData\workbuddy" "%LOCALAPPDATA%\Programs\WorkBuddy" "%ProgramFiles%\WorkBuddy") do (
    if exist "%%~R\resources\vendor\python\python.exe" if not defined PY set "PY=%%~R\resources\vendor\python\python.exe"
  )
)

if not defined PY (
  echo.
  echo [ERROR] No Python found on this machine. Install Python 3.9+ or check the WorkBuddy folder.
  echo.
  pause
  popd
  exit /b 1
)

echo Using Python: %PY%
echo Device: %COMPUTERNAME%
echo Output: "%SYNC%\%COMPUTERNAME%.json"
echo.
"%PY%" "%ROOT%\scripts\export.py" --device "%COMPUTERNAME%" --out "%SYNC%\%COMPUTERNAME%.json"
if errorlevel 1 (
  echo.
  echo [ERROR] Export failed.
  pause
  popd
  exit /b 1
)
echo.
echo Done. Copy the JSON into the shared sync folder on your main machine.
pause
popd
