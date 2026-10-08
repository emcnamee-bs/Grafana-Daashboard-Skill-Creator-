<#
  Wake-Wall.ps1 - run by the scheduled task GrafanaWallWake (daily, wakes the PC from sleep).
  It lights up the displays (a 1-pixel mouse nudge counts as user input), makes sure the wall supervisor is running, and logs
  what it saw to logs\wake.log. The supervisor does the rest: it re-places or relaunches any dashboard window that is missing,
  and its daily refresh (restartDaily in monitors.json) fires on the first loop after that time.
#>
$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
$logDir = Join-Path $root 'logs'; New-Item -ItemType Directory -Force $logDir | Out-Null
function Write-Log($m) {
  $f = Join-Path $logDir 'wake.log'
  if ((Test-Path $f) -and (Get-Item $f).Length -gt 256KB) { Move-Item $f "$f.old" -Force }
  Add-Content $f ('{0:yyyy-MM-dd HH:mm:ss} {1}' -f (Get-Date), $m)
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class WakeW32 {
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, int dx, int dy, uint data, UIntPtr extra);
}
'@
function Nudge { [WakeW32]::mouse_event(1, 1, 0, 0, [UIntPtr]::Zero); Start-Sleep -Milliseconds 150; [WakeW32]::mouse_event(1, -1, 0, 0, [UIntPtr]::Zero) }

Write-Log '=== wake task fired ==='
Nudge; Start-Sleep 8; Nudge        # first nudge turns the displays on; the second catches TVs that were slow to detect the signal

$sup = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -match 'GrafanaWall\.ps1' })
if ($sup.Count -eq 0) { Write-Log 'supervisor not running: starting task GrafanaWall'; Start-ScheduledTask -TaskName GrafanaWall } else { Write-Log "supervisor running (pid $($sup[0].ProcessId))" }

# give the network (mini-mac) and the displays a moment, then record what is visible
$cfg = Get-Content (Join-Path $root 'monitors.json') -Raw | ConvertFrom-Json
$grafana = $false
for ($i = 0; $i -lt 18 -and -not $grafana; $i++) {
  try { $u = [uri]$cfg.monitors[0].url; $grafana = ((Invoke-WebRequest ($u.GetLeftPart('Authority') + '/api/health') -UseBasicParsing -TimeoutSec 4).StatusCode -eq 200) } catch { Start-Sleep 5 }
}
$screens = [System.Windows.Forms.Screen]::AllScreens
$missing = @($cfg.monitors | Where-Object { $_.display -notin $screens.DeviceName } | ForEach-Object { $_.name })
Write-Log ("grafana reachable: $grafana; screens: $($screens.Count); wall monitors missing: " + $(if ($missing) { $missing -join ',' } else { 'none' }))
Nudge
