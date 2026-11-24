@echo off
rem Rozefield - import a player's .rzsave (from export_my_data.bat) as their own account.
rem Drag one or more .rzsave files onto this file. The player then logs in with their in-game name.
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
py -3.12 -c "1" >nul 2>nul && set PY=py -3.12
py -3.13 -c "1" >nul 2>nul && set PY=py -3.13
if "%~1"=="" (
  echo Drag .rzsave files onto import_player.bat
  pause & exit /b 1
)
:next
if "%~1"=="" goto done
%PY% tools\import_player.py "%~1"
shift
goto next
:done
pause
