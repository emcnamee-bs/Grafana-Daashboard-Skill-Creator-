<#
  GrafanaWall - keeps one fullscreen Chrome window per auxiliary monitor pointed at a Grafana dashboard.
  Config: monitors.json (edit it while running; changes are picked up within ~10s).
  Usage:  GrafanaWall.ps1            run the supervisor
          GrafanaWall.ps1 -List      list detected monitors
          GrafanaWall.ps1 -Stop      stop supervisor and all dashboard windows
#>
param([switch]$List, [switch]$Stop)

$root    = $PSScriptRoot
$cfgPath = Join-Path $root 'monitors.json'
$logDir  = Join-Path $root 'logs'
$profDir = Join-Path $root 'profiles'
New-Item -ItemType Directory -Force $logDir, $profDir | Out-Null

Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class W32 {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
'@
[void][W32]::SetProcessDPIAware()

function Get-Screens { [System.Windows.Forms.Screen]::AllScreens }

if ($List) {
  Get-Screens | ForEach-Object { '{0,-16} primary={1,-5} x={2} y={3} {4}x{5}' -f $_.DeviceName, $_.Primary, $_.Bounds.X, $_.Bounds.Y, $_.Bounds.Width, $_.Bounds.Height }
  return
}

function Write-Log($msg) {
  $f = Join-Path $logDir 'wall.log'
  if ((Test-Path $f) -and (Get-Item $f).Length -gt 1MB) { Move-Item $f "$f.old" -Force }
  Add-Content $f ('{0:yyyy-MM-dd HH:mm:ss} {1}' -f (Get-Date), $msg)
}

function Stop-Tree($procId) { if ($procId) { & taskkill.exe /PID $procId /T /F *> $null } }

if ($Stop) {
  Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -match 'GrafanaWall\.ps1' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Tree $_.ProcessId }
  Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object { $_.CommandLine -like "*$profDir*" } | ForEach-Object { & taskkill.exe /PID $_.ProcessId /F *> $null }
  return
}

# single instance
$created = $false
$mutex = New-Object System.Threading.Mutex($true, 'Global\GrafanaWallSupervisor', [ref]$created)
if (-not $created) { return }   # already running (the task re-fires every 5 min as a watchdog)

function Load-Config {
  try { Get-Content $cfgPath -Raw | ConvertFrom-Json } catch { Write-Log "config error: $_"; $null }
}

function Test-Url($url) {
  try {
    $u = [uri]$url
    if ($u.Scheme -notin 'http', 'https') { return $true }
    $r = Invoke-WebRequest -Uri ($u.GetLeftPart('Authority') + '/api/health') -UseBasicParsing -TimeoutSec 4
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

# Grafana re-queries data on its refresh interval but never re-reads the dashboard layout, so a tile redrawn by the
# slot-writer would not appear until the page reloads. We track the saved version and relaunch the window when it changes.
function Get-DashVersion($url) {
  try {
    $u = [uri]$url
    if ($u.AbsolutePath -notmatch '^/d/([^/]+)') { return $null }
    return (Invoke-RestMethod -Uri ($u.GetLeftPart('Authority') + '/api/dashboards/uid/' + $Matches[1]) -TimeoutSec 4).dashboard.version
  } catch { return $null }
}

function Start-Dash($m, $cfg) {
  $screen = Get-Screens | Where-Object { $_.DeviceName -eq $m.display }
  if (-not $screen) { Write-Log "[$($m.name)] display $($m.display) not found"; return $null }
  $b = $screen.Bounds
  $pd = Join-Path $profDir $m.name
  # A Chrome left over from a dead supervisor still owns this profile: a new launch would only open another window inside it and
  # exit at once (looks like a crash -> relaunch loop, a new fullscreen window every ~18s). Clear it so our launch is the real browser.
  $stale = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object { $_.CommandLine -like "*$pd*" })
  if ($stale.Count) { Write-Log "[$($m.name)] clearing $($stale.Count) leftover chrome process(es) on this profile"; $stale | ForEach-Object { & taskkill.exe /PID $_.ProcessId /F *> $null }; Start-Sleep 1 }
  # insetX/insetY = pixels hidden per side by TV overscan (0 = true fullscreen kiosk).
  # scale makes the slot grid (contentHeight CSS px tall) fill the visible height exactly.
  $ix = [int]$m.insetX; $iy = [int]$m.insetY
  $rx = $b.X + $ix; $ry = $b.Y + $iy; $rw = $b.Width - 2 * $ix; $rh = $b.Height - 2 * $iy
  $contentH = if ($cfg.contentHeight) { [double]$cfg.contentHeight } else { 1012 }
  $scale = [math]::Round($rh / $contentH, 4)
  $inset = ($ix -ne 0 -or $iy -ne 0)
  $args = @(
    "--user-data-dir=`"$pd`"", "--app=$($m.url)", "--force-device-scale-factor=$scale",
    "--window-position=$rx,$ry", "--window-size=$rw,$rh",
    '--no-first-run', '--no-default-browser-check', '--noerrdialogs', '--disable-infobars',
    '--disable-session-crashed-bubble', '--hide-crash-restore-bubble', '--password-store=basic',
    '--disable-features=Translate,CalculateNativeWinOcclusion',
    '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--disable-background-timer-throttling'
  )
  $args += '--kiosk'   # always borderless; an inset is applied afterwards by resizing the window (a non-kiosk --app window would show a title bar)
  $ver = Get-DashVersion $m.url      # read before launching so a save during startup still triggers a reload
  $p = Start-Process -FilePath $cfg.chromePath -ArgumentList $args -PassThru
  # wait for window, then pin to the monitor
  $h = [IntPtr]::Zero
  for ($i = 0; $i -lt 40 -and $h -eq [IntPtr]::Zero; $i++) {
    Start-Sleep -Milliseconds 500
    $p.Refresh()
    if ($p.HasExited) { break }
    $h = $p.MainWindowHandle
  }
  if ($h -ne [IntPtr]::Zero) {
    [void][W32]::SetWindowPos($h, [IntPtr]::Zero, $rx, $ry, $rw, $rh, 0x0044) # NOZORDER|SHOWWINDOW
  }
  Write-Log "[$($m.name)] started pid $($p.Id) on $($m.display) -> $($m.url)"
  [pscustomobject]@{ Proc = $p; Hwnd = $h; Bounds = $b; Url = $m.url; Display = $m.display; Backoff = 5; NextTry = Get-Date; WasDown = $false; DownSince = $null; Version = $ver; Inset = "$ix,$iy" }
}

function Test-InPlace($st) {
  if (-not $st.Hwnd -or $st.Hwnd -eq [IntPtr]::Zero) { return $true }
  $r = New-Object W32+RECT
  if (-not [W32]::GetWindowRect($st.Hwnd, [ref]$r)) { return $true }
  $cx = ($r.L + $r.R) / 2; $cy = ($r.T + $r.B) / 2
  $b = $st.Bounds
  return ($cx -ge $b.Left -and $cx -le $b.Right -and $cy -ge $b.Top -and $cy -le $b.Bottom)
}

Write-Log '=== supervisor starting ==='
$state = @{}
$cfg = Load-Config
$cfgStamp = (Get-Item $cfgPath).LastWriteTime
# A wall must not idle-sleep or blank its displays (Windows would after the idle timeouts, since Chrome showing a dashboard is not "input").
# ES_CONTINUOUS|ES_SYSTEM_REQUIRED|ES_DISPLAY_REQUIRED lasts while this loop runs; a manual Sleep / Shut down from the Start menu still works.
# Set "keepAwake": false in monitors.json to let Windows decide again.
if (-not $cfg -or $cfg.keepAwake -ne $false) { [void][W32]::SetThreadExecutionState(0x80000003); Write-Log 'keep-awake requested (display + system)' }
$lastDaily = (Get-Date).Date

while ($true) {
  try {
    if ((Get-Item $cfgPath).LastWriteTime -ne $cfgStamp) {
      $new = Load-Config
      if ($new) { $cfg = $new; Write-Log 'config reloaded' }
      $cfgStamp = (Get-Item $cfgPath).LastWriteTime
    }
    if (-not $cfg) { Start-Sleep 10; continue }

    $names = @($cfg.monitors | ForEach-Object { $_.name })
    foreach ($n in @($state.Keys)) {
      if ($n -notin $names) { Stop-Tree $state[$n].Proc.Id; $state.Remove($n); Write-Log "[$n] removed" }
    }

    $dailyDue = $false
    if ($cfg.restartDaily) {
      $t = [datetime]::ParseExact($cfg.restartDaily, 'HH:mm', $null)
      $due = (Get-Date).Date.Add($t.TimeOfDay)
      if ((Get-Date) -ge $due -and $lastDaily -lt (Get-Date).Date) { $dailyDue = $true; $lastDaily = (Get-Date).Date }
    }

    foreach ($m in $cfg.monitors) {
      $st = $state[$m.name]
      $reason = $null
      if ($st) {
        if ($st.Url -ne $m.url -or $st.Display -ne $m.display -or $st.Inset -ne ('{0},{1}' -f [int]$m.insetX, [int]$m.insetY)) { $reason = 'config changed' }
        elseif ($dailyDue) { $reason = 'daily refresh' }
        elseif ($st.Proc.HasExited) { $reason = 'process exited' }
        elseif (-not (Test-InPlace $st)) { $reason = 'window left its monitor' }
        else {
          $up = Test-Url $m.url
          if (-not $up) { if (-not $st.DownSince) { $st.DownSince = Get-Date }; if (((Get-Date) - $st.DownSince).TotalSeconds -gt 60) { $st.WasDown = $true } }
          else {
            $st.DownSince = $null
            if ($st.WasDown) { $reason = 'Grafana recovered' }
            else {
              $v = Get-DashVersion $m.url
              if ($null -ne $v -and $null -ne $st.Version -and $v -ne $st.Version) { $reason = 'dashboard changed' }
              elseif ($null -eq $st.Version -and $null -ne $v) { $st.Version = $v }
            }
          }
        }
        if ($reason) { Write-Log "[$($m.name)] restart: $reason"; Stop-Tree $st.Proc.Id; $state.Remove($m.name); $st = $null; if ($reason -eq 'process exited') { Start-Sleep 2 } }
        else { continue }
      }
      # (re)launch only once Grafana answers
      if (-not (Test-Url $m.url)) { continue }
      $ns = Start-Dash $m $cfg
      if ($ns) { $state[$m.name] = $ns }
    }
  } catch { Write-Log "loop error: $_" }
  Start-Sleep 10
}
