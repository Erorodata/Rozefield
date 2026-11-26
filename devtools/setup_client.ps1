<#  Rozefield client switch. Default target is the game folder next to the Server folder (H:\Backup\Overfield) so the Steam install stays
    original for the official servers. Run in an *Administrator* PowerShell:
      powershell -ExecutionPolicy Bypass -File setup_client.ps1            # point the game at this PC
      powershell -ExecutionPolicy Bypass -File setup_client.ps1 -Revert    # restore the original files
    It (1) swaps PCSDKUI.exe for the offline login stub (original kept as PCSDKUI.exe.orig),
       (2) sets UseCustomConfig/RemoteServerIP in StreamingAssets\Config.txt (original kept as Config.txt.orig),
       (3) adds a Windows Firewall rule that stops THIS copy's launcher.exe reaching the internet, so it can't fall
           back to the official servers while they are still up (local 127.0.0.1 traffic is unaffected),
       (4) with -AddHosts, adds hosts-file lines sending the game's dispatch domains to 127.0.0.1.            #>
param([string]$Game = (Join-Path $PSScriptRoot '..\Overfield'), [string]$ServerIP = '127.0.0.1', [string]$LookupName = '', [switch]$Revert, [switch]$AddHosts)
$ErrorActionPreference = 'Stop'
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host 'Run this in an Administrator window: right-click Start > Terminal (Admin), then run it again.' -ForegroundColor Red; exit 1 }
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

$fwName = 'Rozefield - keep backup copy offline'
$exe = Join-Path $Game 'launcher.exe'
if ($Revert) {
  netsh advfirewall firewall delete rule name="$fwName" | Out-Null
  if (Test-Path "$sdk\PCSDKUI.exe.orig") { Copy-Item "$sdk\PCSDKUI.exe.orig" "$sdk\PCSDKUI.exe" -Force }
  if (Test-Path "$cfg.orig") { Copy-Item "$cfg.orig" $cfg -Force }
  $meta = Join-Path $Game 'launcher_Data\il2cpp_data\Metadata\global-metadata.dat'
  if (Test-Path "$meta.orig") { Copy-Item "$meta.orig" $meta -Force }
  $null = Write-Hosts (@([IO.File]::ReadAllLines($hosts)) | Where-Object { $_ -notmatch [regex]::Escape($tag) })
  ipconfig /flushdns | Out-Null
  Write-Host 'Restored original SDK, Config.txt and hosts file.'; exit
}
if (-not (Test-Path "$sdk\PCSDKUI.exe.orig")) { Copy-Item "$sdk\PCSDKUI.exe" "$sdk\PCSDKUI.exe.orig" }
Copy-Item (Join-Path $here 'sdk_stub\PCSDKUI.exe') "$sdk\PCSDKUI.exe" -Force
if (-not (Test-Path "$sdk\rozefield_sdk.ini")) { Copy-Item (Join-Path $here 'sdk_stub\rozefield_sdk.ini') "$sdk\rozefield_sdk.ini" }
# login window: which server to ask for accounts
$ini = [IO.File]::ReadAllText("$sdk\rozefield_sdk.ini")
if ($ini -match '(?m)^ip\s*=') { $ini = $ini -replace '(?m)^ip\s*=.*$', "ip=$ServerIP" }
elseif ($ini -match '(?m)^\[server\]') { $ini = $ini -replace '(?m)^\[server\]\s*$', "[server]`r`nip=$ServerIP" }
else { $ini += "`r`n[server]`r`nip=$ServerIP`r`n" }
[IO.File]::WriteAllText("$sdk\rozefield_sdk.ini", $ini, (New-Object Text.ASCIIEncoding))
# the game's own server lookup (HTTPDNS, hard-coded 8.134.240.36 in global-metadata.dat): point it at the server
# (same as tools\patch_client_dns.py, no Python needed). The address must fit in 12 characters.
function Set-GameLookup([string]$Target) {
  $meta = Join-Path $Game 'launcher_Data\il2cpp_data\Metadata\global-metadata.dat'
  if (-not (Test-Path "$meta.orig")) { Copy-Item $meta "$meta.orig" }
  if ($Target.Length -gt 12) { Write-Warning "Lookup not patched: '$Target' is longer than 12 characters. Use -LookupName rozefield and add '$ServerIP rozefield' to the hosts file."; return }
  $d = [IO.File]::ReadAllBytes("$meta.orig")
  $lo = [BitConverter]::ToUInt32($d, 8); $ls = [BitConverter]::ToUInt32($d, 12); $ldo = [BitConverter]::ToUInt32($d, 16)
  $enc = [Text.Encoding]::GetEncoding(28591)
  $pos = $enc.GetString($d).IndexOf('8.134.240.36', [int]$ldo) - $ldo
  if ($pos -lt 0) { Write-Warning 'Game lookup address not found (unknown build); skipped.'; return }
  $hit = -1
  for ($i = 0; $i -lt $ls / 8; $i++) {
    $o = $lo + $i * 8
    if ([BitConverter]::ToUInt32($d, $o) -eq 12 -and [BitConverter]::ToInt32($d, $o + 4) -eq $pos) { $hit = $o; break }
  }
  if ($hit -lt 0) { Write-Warning 'Game lookup string not found (unknown build); skipped.'; return }
  $b = [Text.Encoding]::ASCII.GetBytes($Target)
  [Array]::Copy($b, 0, $d, $ldo + $pos, $b.Length)
  [BitConverter]::GetBytes([uint32]$b.Length).CopyTo($d, $hit)
  [IO.File]::WriteAllBytes($meta, $d)
  Write-Host "Game lookup -> $Target"
}
Set-GameLookup $(if ($LookupName) { $LookupName } else { $ServerIP })
if (-not (Test-Path "$cfg.orig")) { Copy-Item $cfg "$cfg.orig" }
$t = [IO.File]::ReadAllText($cfg)
$t = $t -replace 'UseCustomConfig\s*=\s*\w+', 'UseCustomConfig = TRUE' -replace 'RemoteServerIP\s*=\s*[^\r\n]*', "RemoteServerIP = $ServerIP"
[IO.File]::WriteAllText($cfg, $t, (New-Object Text.UTF8Encoding $false))
$lines = @([IO.File]::ReadAllLines($hosts)) | Where-Object { $_ -notmatch [regex]::Escape($tag) }
if ($AddHosts) { $lines += $domains | ForEach-Object { "$ServerIP $_ $tag" } }  # off by default: hosts entries would redirect every copy of the game
if ($LookupName) { $lines += "$ServerIP $LookupName $tag" }   # short name for the game lookup (long addresses)
$null = Write-Hosts $lines
ipconfig /flushdns | Out-Null
netsh advfirewall firewall delete rule name="$fwName" | Out-Null
if ($ServerIP -eq '127.0.0.1') {   # server on this PC: the game needs no internet at all
  # quoted: PowerShell would split a bare a,b,c into separate arguments
  netsh advfirewall firewall add rule "name=$fwName" dir=out action=block "program=$exe" enable=yes `
    "remoteip=1.0.0.0-126.255.255.255,128.0.0.0-255.255.255.255,2000::/3" | Out-Null
  if ($LASTEXITCODE -eq 0) { Write-Host "Firewall: $exe can no longer reach the official servers." }
  else { Write-Warning "Firewall rule was NOT added (netsh error $LASTEXITCODE)." }
}
Write-Host "$Game now points at $ServerIP (other game copies untouched). Start start_server.bat, then run $Game\launcher.exe"
