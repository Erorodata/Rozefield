<#  Rozefield client switch. Run in an *Administrator* PowerShell:
      powershell -ExecutionPolicy Bypass -File setup_client.ps1            # point the game at this PC
      powershell -ExecutionPolicy Bypass -File setup_client.ps1 -Revert    # restore the original files
    It (1) swaps PCSDKUI.exe for the offline login stub (original kept as PCSDKUI.exe.orig),
       (2) sets UseCustomConfig/RemoteServerIP in StreamingAssets\Config.txt (original kept as Config.txt.orig),
       (3) adds hosts-file lines sending the game's dispatch domains to 127.0.0.1.            #>
param([string]$Game = 'H:\SteamLibrary\steamapps\common\OverField', [string]$ServerIP = '127.0.0.1', [switch]$Revert)
$ErrorActionPreference = 'Stop'
$here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$sdk   = Join-Path $Game 'launcher_Data\Plugins\Win\PCSDK_release'
$cfg   = Join-Path $Game 'launcher_Data\StreamingAssets\Config.txt'
$hosts = "$env:SystemRoot\System32\drivers\etc\hosts"
$tag   = '# rozefield'
function Write-Hosts($lines) {
  for ($i = 1; $i -le 10; $i++) {
    try { [IO.File]::WriteAllLines($hosts, [string[]]$lines, [Text.Encoding]::ASCII); return $true }
    catch { Start-Sleep -Milliseconds 700 }
  }
  Write-Warning "hosts file is locked by another program (antivirus, VPN, Docker, ad-blocker...). Skipped it; Config.txt may be enough."
  return $false
}
$domains = 'dsp-global-of.inutan.com','cdn-of-global.inutan.com','sdkapi-of-global.inutan.com','d2b0sg4npngm2p.cloudfront.net','te-receiver-aws.thinkingdata.jp'

if ($Revert) {
  if (Test-Path "$sdk\PCSDKUI.exe.orig") { Copy-Item "$sdk\PCSDKUI.exe.orig" "$sdk\PCSDKUI.exe" -Force }
  if (Test-Path "$cfg.orig") { Copy-Item "$cfg.orig" $cfg -Force }
  $null = Write-Hosts (@([IO.File]::ReadAllLines($hosts)) | Where-Object { $_ -notmatch [regex]::Escape($tag) })
  ipconfig /flushdns | Out-Null
  Write-Host 'Restored original SDK, Config.txt and hosts file.'; exit
}
if (-not (Test-Path "$sdk\PCSDKUI.exe.orig")) { Copy-Item "$sdk\PCSDKUI.exe" "$sdk\PCSDKUI.exe.orig" }
Copy-Item (Join-Path $here 'sdk_stub\PCSDKUI.exe') "$sdk\PCSDKUI.exe" -Force
if (-not (Test-Path "$sdk\rozefield_sdk.ini")) { Copy-Item (Join-Path $here 'sdk_stub\rozefield_sdk.ini') "$sdk\rozefield_sdk.ini" }
if (-not (Test-Path "$cfg.orig")) { Copy-Item $cfg "$cfg.orig" }
$t = [IO.File]::ReadAllText($cfg)
$t = $t -replace 'UseCustomConfig\s*=\s*\w+', 'UseCustomConfig = TRUE' -replace 'RemoteServerIP\s*=\s*[^\r\n]*', "RemoteServerIP = $ServerIP"
[IO.File]::WriteAllText($cfg, $t, (New-Object Text.UTF8Encoding $false))
$lines = @([IO.File]::ReadAllLines($hosts)) | Where-Object { $_ -notmatch [regex]::Escape($tag) }
$lines += $domains | ForEach-Object { "$ServerIP $_ $tag" }
$null = Write-Hosts $lines
ipconfig /flushdns | Out-Null
Write-Host "Game now points at $ServerIP. Start start_server.bat, then launch the game (Steam or launcher.exe)."
