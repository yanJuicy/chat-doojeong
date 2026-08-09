@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" %*
if errorlevel 1 (
  echo.
  echo Setup failed. Read the error above before closing this window.
  pause
  exit /b 1
)
echo.
echo Setup completed successfully.
pause
