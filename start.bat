@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
  echo ADeck is not installed yet.
  echo Double-click Setup ADeck.bat first.
  pause
  exit /b 1
)

"%~dp0.venv\Scripts\python.exe" "%~dp0adeck_control.py" start
if errorlevel 1 (
  echo.
  echo ADeck could not start. Open ADeck-Control.bat and choose Check System.
  echo Logs: %LOCALAPPDATA%\ADeck
  pause
  exit /b 1
)
exit /b 0
