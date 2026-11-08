@echo off
setlocal
set "ROOT=%~dp0.."
pushd "%ROOT%"

rem ---- 一键：导出本机 token 明细 + 上传资料库固定节点 ----
rem args: %1=设备名（可省略，默认取主机名）
set "DEV=%~1"
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
echo.
"%PY%" "%ROOT%\scripts\publish_bundle.py" --device "%DEV%"
echo.
echo [DONE] 可把这个命令写进 WorkBuddy 自动化任务，每天自动跑。见 SETUP-AUTOMATION.txt
pause
popd
