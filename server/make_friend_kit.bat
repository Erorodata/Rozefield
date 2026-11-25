@echo off
rem Builds Rozefield_friend_kit.zip: what a friend needs (besides a copy of the game folder) to play on this server.
cd /d "%~dp0"
set KIT=%~dp0Rozefield_friend_kit
if exist "%KIT%" rmdir /s /q "%KIT%"
mkdir "%KIT%\sdk_stub"
copy /y setup_client.ps1 "%KIT%\" >nul
copy /y sdk_stub\PCSDKUI.exe "%KIT%\sdk_stub\" >nul
copy /y sdk_stub\rozefield_sdk.ini "%KIT%\sdk_stub\" >nul
(
echo Rozefield - play on a friend's server
echo.
echo 1. Copy the Rozefield game folder from the host ^(the whole folder with launcher.exe; the _archive folder is not needed^).
echo 2. Right-click Start ^> Terminal ^(Admin^), go to this folder and run:
echo      powershell -ExecutionPolicy Bypass -File setup_client.ps1 -Game "C:\Games\OverField" -ServerIP HOST_ADDRESS
echo    HOST_ADDRESS = the host's LAN address ^(192.168.x.x^) or public internet address, as the host tells you.
echo    If the address is longer than 12 characters, add:  -LookupName rozefield
echo 3. Start launcher.exe in the game folder. Create an account in the login window and play.
echo    The first start downloads the Rozefield update from the host.
echo.
echo To undo:  powershell -ExecutionPolicy Bypass -File setup_client.ps1 -Game "C:\Games\OverField" -Revert
) > "%KIT%\READ ME.txt"
powershell -NoProfile -Command "Compress-Archive -Path '%KIT%\*' -DestinationPath '%~dp0Rozefield_friend_kit.zip' -Force"
echo Made Rozefield_friend_kit.zip - send it to your friend together with a copy of the game folder.
pause
