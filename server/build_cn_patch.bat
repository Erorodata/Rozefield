@echo off
rem Builds the Rozefield resource patch that adds CN-client content to the Steam client.
rem Run once (and again if either game updates). Then restart start_server.bat.
rem Lives in the Server folder (repo) or in Tools\server_dev (PC layout); runs the server's own tools either way.
set SRV=%~dp0
if not exist "%SRV%rozefield_server.py" set SRV=%~dp0..\..\Server\
set CFG=%~dp0patch_src\pbstaticconfigure.bundle
if not exist "%CFG%" set CFG=%SRV%patch_src\pbstaticconfigure.bundle
cd /d "%SRV%"
set GAME=%SRV%..\Overfield
if exist game_path.txt set /p GAME=<game_path.txt
set CN=H:\OverField\OverField Game
if exist cn_game_path.txt set /p CN=<cn_game_path.txt
rem UnityPy has no builds for pre-release Python 3.15 yet: prefer an installed 3.13 / 3.12
set PY=python
where py >nul 2>nul && set PY=py -3
py -3.12 -c "1" >nul 2>nul && set PY=py -3.12
py -3.13 -c "1" >nul 2>nul && set PY=py -3.13
echo Using %PY%
%PY% -c "import UnityPy, google.protobuf" 2>nul || %PY% -m pip install -r requirements.txt
%PY% tools\build_cn_patch.py --global "%GAME%\launcher_Data\yoo" --cn "%CN%\launcher_Data\yoo" --config "%CFG%"
pause
