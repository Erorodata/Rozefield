@echo off
rem Rozefield private server launcher. Double-click to run. Close the window to stop.
cd /d "%~dp0"
set GAME=H:\Backup\OverField
if exist game_path.txt set /p GAME=<game_path.txt
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -c "import google.protobuf, cramjam" 2>nul || %PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo Python 3 is needed: install it from python.org ^(tick "Add python to PATH"^), then run this again.
  pause & exit /b 1
)
%PY% rozefield_server.py --res-dir "%GAME%\launcher_Data\yoo" %*
pause
