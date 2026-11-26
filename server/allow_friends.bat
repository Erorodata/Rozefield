@echo off
rem Lets friends on other PCs reach this Rozefield server (run once, as Administrator).
net session >nul 2>&1 || (echo Right-click this file and choose "Run as administrator". & pause & exit /b 1)
netsh advfirewall firewall delete rule name="Rozefield server" >nul 2>&1
netsh advfirewall firewall add rule name="Rozefield server" dir=in action=allow protocol=TCP localport=18880,80,18881,11001 >nul
echo Windows Firewall: TCP 18880, 80, 18881 and 11001 are open for Rozefield.
echo.
echo Your addresses for friends:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo   LAN (same Wi-Fi / router):%%a
for /f %%a in ('powershell -NoProfile -Command "(Invoke-RestMethod -TimeoutSec 5 https://api.ipify.org) 2>$null"') do echo   Internet: %%a   (for internet players forward TCP 18880 on your router to this PC, or use playit.gg)
echo.
echo Run make_friend_kit.bat and send your friend the kit plus a copy of the game folder.
pause
