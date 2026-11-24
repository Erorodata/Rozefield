@echo off
rem Rozefield - save YOUR OverField account before the official servers close.
rem Run this, then start OverField and log in normally. Your data is written to the "exports" folder.
cd /d "%~dp0"
chcp 65001 >nul
set PY=python
where py >nul 2>nul && set PY=py -3
py -3.12 -c "1" >nul 2>nul && set PY=py -3.12
py -3.13 -c "1" >nul 2>nul && set PY=py -3.13
%PY% -c "import google.protobuf, cramjam" 2>nul || %PY% -m pip install protobuf cramjam
if errorlevel 1 (
  echo Python 3 is needed: install it from python.org ^(tick "Add python to PATH"^), then run this again.
  pause & exit /b 1
)
set GAME=
if exist export_game_path.txt set /p GAME=<export_game_path.txt
for %%D in ("C:\Program Files (x86)\Steam" "D:\SteamLibrary" "E:\SteamLibrary" "H:\SteamLibrary") do if not defined GAME if exist "%%~D\steamapps\common\OverField\launcher.exe" set "GAME=%%~D\steamapps\common\OverField"
if not defined GAME (
  echo Drag your OverField game folder ^(the one with launcher.exe^) onto this window and press Enter:
  set /p GAME=
)
set GAME=%GAME:"=%
if not exist "%GAME%\launcher.exe" (
  echo launcher.exe not found in "%GAME%"
  pause & exit /b 1
)
echo %GAME%>export_game_path.txt
%PY% tools\rz_export.py --game "%GAME%" %*
%PY% tools\rz_export.py --game "%GAME%" --restore
echo.
echo Send the .rzsave file in the "exports" folder to your Rozefield server host (or keep it safe).
pause
