@echo off
setlocal
cd /d "%~dp0"
title Setup ADeck
echo.
echo  ADeck Setup
echo  Connect the UNO R4 WiFi, then press any key to install.
echo.
pause >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
set "CODE=%ERRORLEVEL%"
echo.
if not "%CODE%"=="0" (
  echo Setup did not finish.
  echo Next step: open ADeck-Control.bat and choose Check System or Install / Repair.
) else (
  echo ADeck is ready. Daily use: double-click Start ADeck.bat
)
pause
exit /b %CODE%
