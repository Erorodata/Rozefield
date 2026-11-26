@echo off
rem Puts a private copy of Python inside this Server folder (python\), so this Server folder runs on any Windows PC
rem without installing Python. Run once on a PC with internet; the folder can then be copied anywhere.
cd /d "%~dp0"
set VER=3.13.1
set ZIP=python-%VER%-embed-amd64.zip
if exist python\python.exe goto deps
echo Downloading Python %VER% (embeddable, about 11 MB) from python.org ...
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest 'https://www.python.org/ftp/python/%VER%/%ZIP%' -OutFile '%TEMP%\%ZIP%'" || goto fail
powershell -NoProfile -Command "Expand-Archive -Force '%TEMP%\%ZIP%' 'python'" || goto fail
rem let the embedded Python see site-packages and this folder
powershell -NoProfile -Command "$f=Get-ChildItem python\python3*._pth | Select -First 1; (Get-Content $f) -replace '^#\s*import site','import site' | Set-Content $f; Add-Content $f '..'" || goto fail
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'python\get-pip.py'" || goto fail
python\python.exe python\get-pip.py --no-warn-script-location -q || goto fail
:deps
python\python.exe -m pip install -q --no-warn-script-location "protobuf>=4.25" "cramjam>=2.8" || goto fail
echo.
echo Done: this Server folder now has its own Python (python\). start_server.bat and Overfield Server.exe use it.
pause
exit /b 0
:fail
echo.
echo Setting up Python failed. Check the internet connection and run this again.
pause
exit /b 1
