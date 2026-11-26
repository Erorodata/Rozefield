# OverField archival capture script
# Run in an ADMINISTRATOR PowerShell while the servers are still online:
#   powershell -ExecutionPolicy Bypass -File "H:\Backup\OverField\_archive\OverField_Capture.ps1"
#
# What it does (nothing is installed, no certificates, no system settings changed):
#   1. SHA-256 hash manifest of every client file (proves the archive is intact)
#   2. Full packet capture with Windows' built-in pktmon -> .pcapng (open in Wireshark)
#   3. Logs every TCP connection the game opens (which IP:port each server lives on)
#   4. Copies the client's own logs (Unity Player.log, SDK log) after you quit
#
# During the capture: launch the game normally from Steam, log in, and visit as much
# as you can (lobby, story, shop, gacha banners, mail, events, friends, settings).
# Close browsers/Discord/other online apps first so the capture stays clean.

$ErrorActionPreference = 'Continue'
$GameDir   = 'H:\Backup\OverField'
$SteamDir  = 'H:\SteamLibrary\steamapps\common\OverField'   # the copy Steam actually runs
$Out       = Join-Path $GameDir ('_archive\capture_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Start-Transcript -Path (Join-Path $Out 'transcript.txt')

# ---------- 1. Hash manifest ----------
Write-Host "[1/4] Hashing client files (takes a few minutes)..."
foreach ($d in @($GameDir, $SteamDir)) {
  if (Test-Path $d) {
    $name = ($d -replace '[:\\]', '_')
    Get-ChildItem -LiteralPath $d -Recurse -File -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -notlike '*\_archive\*' } |
      ForEach-Object {
        [pscustomobject]@{
          Path     = $_.FullName.Substring($d.Length + 1)
          Bytes    = $_.Length
          Modified = $_.LastWriteTimeUtc.ToString('o')
          SHA256   = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
      } | Export-Csv -NoTypeInformation -Encoding UTF8 (Join-Path $Out "hashes$name.csv")
  }
}

# ---------- 2. Resolve known hosts ----------
$hosts = 'sdkapi-of-global.inutan.com'
$dns = foreach ($h in $hosts) { Resolve-DnsName $h -ErrorAction SilentlyContinue | Where-Object IPAddress }
$dns | Select-Object Name, Type, IPAddress | Export-Csv -NoTypeInformation (Join-Path $Out 'dns.csv')

# ---------- 3. Packet capture ----------
Write-Host "[2/4] Starting packet capture..."
$etl = Join-Path $Out 'capture.etl'
pktmon filter remove | Out-Null
pktmon start --capture --pkt-size 0 --file-name $etl --file-size 4096 | Out-Null

# ---------- 4. Connection logger ----------
$connLog = Join-Path $Out 'game_connections.csv'
"TimeUtc,Process,PID,LocalPort,RemoteAddress,RemotePort,State" | Out-File $connLog -Encoding utf8
$seen = @{}
Write-Host "[3/4] NOW start OverField from Steam and play. Press Q in this window when you have quit the game."
while ($true) {
  $procs = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^(launcher|PCSDKUI|QtWebEngineProcess)$' }
  foreach ($p in $procs) {
    Get-NetTCPConnection -OwningProcess $p.Id -ErrorAction SilentlyContinue | ForEach-Object {
      $key = "$($p.ProcessName)|$($_.RemoteAddress)|$($_.RemotePort)|$($_.State)"
      if (-not $seen.ContainsKey($key) -and $_.RemoteAddress -notin '0.0.0.0','::','127.0.0.1','::1') {
        $seen[$key] = 1
        "$((Get-Date).ToUniversalTime().ToString('o')),$($p.ProcessName),$($p.Id),$($_.LocalPort),$($_.RemoteAddress),$($_.RemotePort),$($_.State)" | Add-Content $connLog
        Write-Host "  + $($p.ProcessName) -> $($_.RemoteAddress):$($_.RemotePort)"
      }
    }
  }
  if ([Console]::KeyAvailable -and ([Console]::ReadKey($true).Key -eq 'Q')) { break }
  Start-Sleep -Milliseconds 500
}

Write-Host "[4/4] Stopping capture and converting to pcapng..."
pktmon stop | Out-Null
pktmon etl2pcap $etl --out (Join-Path $Out 'capture.pcapng') | Out-Null

# ---------- Client-side logs ----------
$logs = @(
  "$env:USERPROFILE\AppData\LocalLow\Inutan\OverField",
  "$GameDir\launcher_Data\Quicksdk",
  "$SteamDir\launcher_Data\Quicksdk"
)
foreach ($l in $logs) {
  if (Test-Path $l) {
    $dest = Join-Path $Out ('clientlogs_' + ($l -replace '[:\\ ]', '_'))
    Copy-Item -LiteralPath $l -Destination $dest -Recurse -Force -ErrorAction SilentlyContinue
  }
}

Stop-Transcript
Write-Host "Done. Everything is in: $Out"
Write-Host "WARNING: capture.pcapng and clientlogs contain your login tokens. Do not share them publicly unredacted."
