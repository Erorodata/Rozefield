@echo off
rem Builds the Rozefield resource patch that adds CN-client content to the Steam client.
rem Run once (and again if either game updates). Then restart start_server.bat.
cd /d "%~dp0"
set GAME=H:\Backup\OverField
if exist game_path.txt set /p GAME=<game_path.txt
set CN=H:\OverField\OverField Game
if exist cn_game_path.txt set /p CN=<cn_game_path.txt
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -c "import UnityPy, google.protobuf" 2>nul || %PY% -m pip install -r requirements.txt
%PY% tools\build_cn_patch.py --global "%GAME%\launcher_Data\yoo" --cn "%CN%\launcher_Data\yoo" --config patch_src\pbstaticconfigure.bundle
pause
