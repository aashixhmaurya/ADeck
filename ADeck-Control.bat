@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ADeck Control

:menu
cls
echo.
echo  ADeck Control
echo  ================================
echo   [1] Start ADeck
echo   [2] Check System
echo   [3] Install / Repair
echo   [4] Reinstall Firmware
echo   [5] View Logs
echo   [6] Stop ADeck
echo   [7] Show Latest Errors
echo   [8] Status Summary
echo   [9] Exit
echo  ================================
echo.
set "CHOICE="
set /p CHOICE=Select option [1-9]: 

if "%CHOICE%"=="1" goto start
if "%CHOICE%"=="2" goto check
if "%CHOICE%"=="3" goto repair
if "%CHOICE%"=="4" goto firmware
if "%CHOICE%"=="5" goto logs
if "%CHOICE%"=="6" goto stop
if "%CHOICE%"=="7" goto errors
if "%CHOICE%"=="8" goto status
if "%CHOICE%"=="9" goto end
echo.
echo Invalid choice.
pause
goto menu

:run_adeck
if exist "%~dp0.venv\Scripts\python.exe" goto run_adeck_venv
where py >nul 2>&1
if not errorlevel 1 goto run_adeck_py
where python >nul 2>&1
if not errorlevel 1 goto run_adeck_python
echo.
echo Python was not found. Run Setup ADeck.bat first.
exit /b 1

:run_adeck_venv
"%~dp0.venv\Scripts\python.exe" "%~dp0adeck_control.py" %*
exit /b %ERRORLEVEL%

:run_adeck_py
py -3 "%~dp0adeck_control.py" %*
exit /b %ERRORLEVEL%

:run_adeck_python
python "%~dp0adeck_control.py" %*
exit /b %ERRORLEVEL%

:start
echo.
call :run_adeck start || goto start_failed
goto menu_pause

:check
echo.
call :run_adeck check || goto check_failed
goto menu_pause

:repair
echo.
call :run_adeck repair || goto repair_failed
goto menu_pause

:firmware
echo.
echo This will stop ADeck and reflash the UNO R4 WiFi.
set "CONFIRM="
set /p CONFIRM=Continue? [y/N]: 
if /i not "%CONFIRM%"=="y" if /i not "%CONFIRM%"=="yes" goto menu
call :run_adeck reinstall-firmware || goto firmware_failed
goto menu_pause

:logs
echo.
call :run_adeck logs || goto action_failed
goto menu_pause

:stop
echo.
call :run_adeck stop || goto action_failed
goto menu_pause

:errors
echo.
call :run_adeck errors || goto action_failed
goto menu_pause

:status
echo.
call :run_adeck status || goto action_failed
goto menu_pause

:start_failed
echo.
echo Could not start ADeck. Try [2] Check System or [3] Install / Repair.
goto menu_pause

:check_failed
echo.
echo Some checks failed. See messages above, or try [3] Install / Repair.
goto menu_pause

:repair_failed
echo.
echo Repair did not finish. Try [7] Show Latest Errors for details.
goto menu_pause

:firmware_failed
echo.
echo Firmware reinstall did not finish. Try [7] Show Latest Errors.
goto menu_pause

:action_failed
echo.
echo That action did not complete. Try [7] Show Latest Errors.
goto menu_pause

:menu_pause
echo.
pause
goto menu

:end
exit /b 0
