<#
  End-to-end check of the interactive tiles on the REAL wall page, driven through Chrome's DevTools protocol (headless Chrome, real mouse
  and keyboard events): hover lights a box, a click opens the full-screen view, an open view holds the wrapper's auto-reload (a dashboard
  version bump is applied only after Esc), Esc closes, a chart box opens its chart view.
  Usage:  live-check.ps1 [-Url http://mini-mac.local:8088/wall/wall-top?w=95] [-Uid wall-top] [-Shots DIR] [-NoBump]
  The bump re-saves the dashboard unchanged (bump_version.py): the real monitors reload once, nothing visible changes.
#>
param(
  [string]$Url = 'http://mini-mac.local:8088/wall/wall-top?w=95',
  [string]$Uid = 'wall-top',
  [string]$Shots = (Join-Path $env:TEMP 'wl-live'),
  [int]$Port = 9333,
  [switch]$NoBump,
  [string]$Extra = ''          # optional extra target to click and report, e.g. "[data-wl='stat:3']" (the Containers chip on the mini-mac tile)
)
$ErrorActionPreference = 'Stop'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item -ItemType Directory -Force $Shots | Out-Null
$results = New-Object System.Collections.ArrayList
function Check($name, $ok, $detail) { [void]$script:results.Add([pscustomobject]@{ ok = [bool]$ok; name = $name; detail = "$detail" }); '{0}  {1}  {2}' -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name, $detail }

$prof = Join-Path $env:TEMP 'wl-live-profile'
$proc = Start-Process $chrome -ArgumentList '--headless=new', '--disable-gpu', "--remote-debugging-port=$Port", '--remote-allow-origins=*', "--user-data-dir=$prof", '--window-size=1960,1300', 'about:blank' -PassThru
$ws = $null
try {
  $page = $null
  for ($i = 0; $i -lt 80 -and -not $page; $i++) {
    try {
      $tabs = Invoke-RestMethod "http://127.0.0.1:$Port/json" -TimeoutSec 2       # Windows PowerShell 5.1 hands the JSON array back as ONE object: iterate it, do not pipe it
      foreach ($t in $tabs) { if ($t.type -eq 'page' -and -not $page) { $page = $t } }
    } catch { }
    if (-not $page) { Start-Sleep -Milliseconds 250 }
  }
  if (-not $page) { throw 'Chrome debugging endpoint did not come up' }
  $ws = New-Object System.Net.WebSockets.ClientWebSocket
  $ws.ConnectAsync([Uri]$page.webSocketDebuggerUrl, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
  $script:cid = 0
  $buf = New-Object byte[] 4194304

  function Send-Cdp([string]$method, $params) {
    $script:cid++
    $msg = @{ id = $script:cid; method = $method }
    if ($null -ne $params) { $msg.params = $params }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($msg | ConvertTo-Json -Depth 10 -Compress))
    $cts = New-Object Threading.CancellationTokenSource; $cts.CancelAfter(60000)
    $ws.SendAsync((New-Object 'System.ArraySegment[byte]' -ArgumentList (, $bytes)), [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cts.Token).GetAwaiter().GetResult()
    while ($true) {
      $sb = New-Object Text.StringBuilder
      do {
        $r = $ws.ReceiveAsync((New-Object 'System.ArraySegment[byte]' -ArgumentList (, $buf)), $cts.Token).GetAwaiter().GetResult()
        [void]$sb.Append([Text.Encoding]::UTF8.GetString($buf, 0, $r.Count))
      } while (-not $r.EndOfMessage)
      $m = $sb.ToString() | ConvertFrom-Json
      if ($m.id -eq $script:cid) { if ($m.error) { throw "CDP $method failed: $($m.error.message)" }; return $m.result }     # anything else is an event: ignored
    }
  }
  function Eval-Top($expr) { (Send-Cdp 'Runtime.evaluate' @{ expression = $expr; returnByValue = $true }).result.value }
  function Eval-In($ctx, $expr) {
    try { return (Send-Cdp 'Runtime.evaluate' @{ expression = $expr; contextId = $ctx; returnByValue = $true }).result.value }
    catch {
      if ("$_" -notmatch 'Cannot find context') { throw }
      # the live wall redrew a tile and the wrapper swapped in a fresh Grafana frame: find the new one and retry once
      $fresh = $null; for ($i = 0; $i -lt 20 -and -not $fresh; $i++) { try { $fresh = Get-Ctx } catch { }; if (-not $fresh) { Start-Sleep -Milliseconds 500 } }
      return (Send-Cdp 'Runtime.evaluate' @{ expression = $expr; contextId = $fresh; returnByValue = $true }).result.value
    }
  }
  function Get-Ctx {                      # an isolated world in the Grafana frame (DOM + computed styles visible, page globals not)
    $t = (Send-Cdp 'Page.getFrameTree' $null).frameTree
    $c = @($t.childFrames) | Where-Object { $_.frame.url -like '*:3000*' } | Select-Object -First 1
    if (-not $c) { return $null }
    (Send-Cdp 'Page.createIsolatedWorld' @{ frameId = $c.frame.id; worldName = 'wl-check' }).executionContextId
  }
  function Wait-Tile([string]$sel) {      # wait until the Grafana frame shows the wanted element; returns its context id
    for ($i = 0; $i -lt 50; $i++) {
      try { $ctx = Get-Ctx; if ($ctx -and (Eval-In $ctx "!!document.querySelector(""$sel"")")) { return $ctx } } catch { }
      Start-Sleep -Milliseconds 800
    }
    throw "timed out waiting for $sel in the Grafana frame"
  }
  function Center($ctx, [string]$sel) {   # page coordinates of an element's centre (frame offset + element rect)
    $off = Eval-Top "(function(){var f=document.querySelectorAll('iframe');var r=f[f.length-1].getBoundingClientRect();return [r.left,r.top]})()"
    $r = Eval-In $ctx "(function(){var r=document.querySelector(""$sel"").getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()"
    @(($off[0] + $r[0]), ($off[1] + $r[1]))
  }
  function Mouse($type, $x, $y) { [void](Send-Cdp 'Input.dispatchMouseEvent' @{ type = $type; x = $x; y = $y; button = $(if ($type -eq 'mouseMoved') { 'none' } else { 'left' }); clickCount = $(if ($type -eq 'mouseMoved') { 0 } else { 1 }) }) }
  function Esc { [void](Send-Cdp 'Input.dispatchKeyEvent' @{ type = 'keyDown'; key = 'Escape'; code = 'Escape'; windowsVirtualKeyCode = 27 }); [void](Send-Cdp 'Input.dispatchKeyEvent' @{ type = 'keyUp'; key = 'Escape'; code = 'Escape'; windowsVirtualKeyCode = 27 }) }
  function Shot($name) { $d = (Send-Cdp 'Page.captureScreenshot' @{ format = 'png' }).data; [IO.File]::WriteAllBytes((Join-Path $Shots "$name.png"), [Convert]::FromBase64String($d)) }

  [void](Send-Cdp 'Page.enable' $null)
  [void](Send-Cdp 'Emulation.setDeviceMetricsOverride' @{ width = 1920; height = 1080; deviceScaleFactor = 1; mobile = $false })
  [void](Send-Cdp 'Page.navigate' @{ url = $Url })
  $sq = "[data-wl='square']"
  $ctx = Wait-Tile $sq
  Start-Sleep -Seconds 2
  Check 'viewer script loaded in Grafana' ((Eval-In $ctx "document.documentElement.getAttribute('data-wl-viewer')") -eq '1') 'data-wl-viewer marker (the tile bootstrap fetched /wall/viewer.js)'
  Shot '1-wall'

  # --- hover lights the whole top bar
  $xy = Center $ctx $sq
  Mouse 'mouseMoved' $xy[0] $xy[1]; Start-Sleep -Milliseconds 500
  $cs = Eval-In $ctx "(function(){var s=getComputedStyle(document.querySelector(""$sq""));return [s.borderTopColor,s.boxShadow]})()"
  Check 'hover lights the top bar' (($cs[0] -eq 'rgb(77, 163, 255)') -and ($cs[1] -ne 'none')) "border=$($cs[0]) shadow=$($cs[1])"
  Shot '2-hover'

  # --- click opens the whole-square view; the wrapper holds reloads
  Mouse 'mousePressed' $xy[0] $xy[1]; Mouse 'mouseReleased' $xy[0] $xy[1]; Start-Sleep -Milliseconds 800
  $open = Eval-In $ctx "!!document.querySelector('[data-wl-overlay]')"
  Check 'click opens the full-screen square view' $open ''
  $hdr = Eval-In $ctx "(function(){var o=document.querySelector('[data-wl-overlay]');return o?[o.getBoundingClientRect().width,o.getBoundingClientRect().height,o.scrollWidth<=o.clientWidth+1&&o.scrollHeight<=o.clientHeight+1]:null})()"
  Check 'view fills the frame without overflow' ($hdr -and $hdr[2]) $(if ($hdr) { "overlay $([int]$hdr[0])x$([int]$hdr[1])" } else { 'no overlay' })
  Shot '3-square-view'
  Check 'wrapper holds reloads while the view is open' ((Eval-Top 'hold') -eq $true) 'wrapper variable hold=true (set by the viewer via postMessage)'

  # --- a dashboard version bump while open must NOT reload the frame
  if (-not $NoBump) {
    $before = Eval-Top "document.querySelectorAll('iframe').length"
    $v0 = Eval-Top 'v'                                       # the dashboard version the wrapper currently knows
    $o = Join-Path $Shots 'bump.out'
    $bump = "ssh -o BatchMode=yes emac@mini-mac.local `"docker exec -i slot-writer python - $Uid`" < `"$(Join-Path $here 'bump_version.py')`""
    Start-Process cmd.exe -ArgumentList '/c', $bump -Wait -WindowStyle Hidden -RedirectStandardOutput $o | Out-Null
    $noticed = $false                                        # the wrapper polls every 5 s: wait until it has seen the new version (or give up after 25 s)
    for ($i = 0; $i -lt 25 -and -not $noticed; $i++) { Start-Sleep -Seconds 1; $noticed = ((Eval-Top 'v') -ne $v0) }
    Start-Sleep -Seconds 2
    $v1 = Eval-Top 'v'; $pend = Eval-Top 'pend'; $n = Eval-Top "document.querySelectorAll('iframe').length"
    Check 'wrapper noticed the version bump' $noticed "version $v0 -> $v1 ($((Get-Content $o -Raw).Trim()))"
    Check 'version bump is deferred while open' (($pend -eq $true) -and ($n -eq $before) -and (Eval-In $ctx "!!document.querySelector('[data-wl-overlay]')")) "pend=$pend, frames=$n (was $before), view still open"
  }

  # --- Esc closes, releases the hold, and the deferred reload then happens
  Esc; Start-Sleep -Milliseconds 600
  Check 'Esc closes the view' (-not (Eval-In $ctx "!!document.querySelector('[data-wl-overlay]')")) ''
  Check 'hold released on close' ((Eval-Top 'hold') -eq $false) ''
  if (-not $NoBump) {
    $ok = $false; $maxFrames = 0                              # after Esc the pending reload loads a NEW frame behind the old one (2 frames), then the old one goes (1)
    for ($i = 0; $i -lt 20 -and -not $ok; $i++) { Start-Sleep -Seconds 1; $maxFrames = [Math]::Max($maxFrames, [int](Eval-Top "document.querySelectorAll('iframe').length")); $ok = ($maxFrames -ge 2) }
    Check 'deferred reload applied after Esc' $ok "a second frame appeared (max frames seen: $maxFrames)"
    Start-Sleep -Seconds 7          # let the new frame swap in and the old one go
  }

  # --- a chart box opens its chart view (re-find the frame: it may have been reloaded)
  $ctx = Wait-Tile "[data-wl='chart:0']"
  Start-Sleep -Seconds 2
  $xy = Center $ctx "[data-wl='chart:0']"
  Mouse 'mouseMoved' $xy[0] $xy[1]; Start-Sleep -Milliseconds 400
  $cs = Eval-In $ctx "(function(){var s=getComputedStyle(document.querySelector(""[data-wl='chart:0']""));return s.borderTopColor})()"
  Check 'hover lights a chart box' ($cs -eq 'rgb(77, 163, 255)') "border=$cs"
  Mouse 'mousePressed' $xy[0] $xy[1]; Mouse 'mouseReleased' $xy[0] $xy[1]; Start-Sleep -Milliseconds 800
  $title = Eval-In $ctx "(function(){var o=document.querySelector('[data-wl-overlay]');return o?o.textContent.slice(0,60):null})()"
  Check 'click opens the chart view' ($null -ne $title) "overlay text starts: $title"
  Shot '4-chart-view'
  Esc; Start-Sleep -Milliseconds 500
  Check 'Esc closes the chart view' (-not (Eval-In $ctx "!!document.querySelector('[data-wl-overlay]')")) ''

  # --- optional: one more target (e.g. the mini-mac Containers chip: members with health and purpose)
  if ($Extra) {
    $xy = Center $ctx $Extra
    Mouse 'mouseMoved' $xy[0] $xy[1]; Start-Sleep -Milliseconds 300
    Mouse 'mousePressed' $xy[0] $xy[1]; Mouse 'mouseReleased' $xy[0] $xy[1]; Start-Sleep -Milliseconds 800
    $txt = Eval-In $ctx "(function(){var o=document.querySelector('[data-wl-overlay]');return o?o.innerText.replace(/\s+/g,' ').slice(0,400):null})()"
    Check "click opens $Extra" ($null -ne $txt) "text: $txt"
    Shot '5-extra-view'
    Esc; Start-Sleep -Milliseconds 400
    Check "Esc closes $Extra" (-not (Eval-In $ctx "!!document.querySelector('[data-wl-overlay]')")) ''
  }
}
finally {
  if ($ws) { try { $ws.Abort() } catch { } }
  if ($proc -and -not $proc.HasExited) { try { Stop-Process -Id $proc.Id -Force } catch { } }
}
$failed = @($results | Where-Object { -not $_.ok }).Count
"{0}/{1} checks passed. Screenshots: {2}" -f ($results.Count - $failed), $results.Count, $Shots
if ($failed) { exit 1 }
