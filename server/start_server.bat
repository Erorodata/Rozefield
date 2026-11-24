@echo off
rem Rozefield private server launcher. Double-click to run. Close the window to stop.
cd /d "%~dp0"
set GAME=H:\Backup\OverField
if exist game_path.txt set /p GAME=<game_path.txt
rem UnityPy has no builds for pre-release Python 3.15 yet: prefer an installed 3.13 / 3.12
set PY=python
where py >nul 2>nul && set PY=py -3
py -3.12 -c "1" >nul 2>nul && set PY=py -3.12
py -3.13 -c "1" >nul 2>nul && set PY=py -3.13
echo Using %PY%
%PY% -c "import google.protobuf, cramjam" 2>nul || %PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo Python 3 is needed: install it from python.org ^(tick "Add python to PATH"^), then run this again.
  pause & exit /b 1
)
%PY% rozefield_server.py --res-dir "%GAME%\launcher_Data\yoo" %*
pause
