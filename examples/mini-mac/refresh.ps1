# mini-mac host tile: host charts from Prometheus (15-min aligned buckets) + live router/uplink checks over ssh.
# Read-only and cheap (2 ping packets per target). Prints one JSON object. Any failure -> non-zero exit -> the wall keeps the last tile.
$ErrorActionPreference = 'Stop'
$Host_ = 'mini-mac.local'; $Prom = "http://${Host_}:9090"; $Job = 'mini-mac'
$Ssh = 'C:\Windows\System32\OpenSSH\ssh.exe'
$GL_OUI = '94:83:c4'                     # GL Technologies (GL.iNet) vendor prefix of the wired gateway's MAC
$Bucket = 900; $Buckets = 48             # 12 h of 15-min buckets
$inv = [Globalization.CultureInfo]::InvariantCulture

function Invoke-Prom($path, $body) {
  $r = Invoke-RestMethod -Uri "$Prom$path" -Method Post -Body $body -TimeoutSec 15
  if ($r.status -ne 'success') { throw "prometheus $path failed" }
  $r.data.result
}
function Get-Points($query, $bucket = $Bucket, $buckets = $Buckets) {
  $end = [long]([math]::Floor([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() / $bucket) * $bucket)
  $res = Invoke-Prom '/api/v1/query_range' @{ query = $query; start = $end - ($buckets - 1) * $bucket; end = $end; step = $bucket }
  $vals = @($res | Select-Object -First 1).values
  if (-not $vals) { throw "no data for $query" }
  @($vals | ForEach-Object { , @([long]$_[0], [math]::Round([double]::Parse($_[1], $inv), 1)) })
}
function New-Chart($title, $subtitle, $pts, $warnAt, $badAt, $yMax, $explain, $hist) {
  $v = @($pts | ForEach-Object { $_[1] })
  $avg = [math]::Round(($v | Measure-Object -Average).Average, 1); $max = [math]::Round(($v | Measure-Object -Maximum).Maximum, 1)
  $st = if ($max -ge $badAt) { 'bad' } elseif ($max -ge $warnAt) { 'warn' } else { 'ok' }
  $c = [ordered]@{ title = $title; subtitle = $subtitle; kind = 'line'; span_label = '12h'; points = $pts; explain = $explain
                   kpis = @(@{ label = 'AVG 12H'; value = ('{0}' -f $avg.ToString($inv)); state = 'ok'; explain = 'Average over the last 12 hours.' },
                            @{ label = 'PEAK 12H'; value = ('{0}' -f $max.ToString($inv)); state = $st; explain = "Highest 15-minute bucket in the last 12 hours (warn from $warnAt, bad from $badAt)." }) }
  if ($yMax) { $c.y_max = $yMax }
  if ($hist) { $c.history = $hist; $c.history_label = '7d' }
  $c
}
function Test-Url($url) { try { (Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch { $false } }
function St($ok) { if ($ok) { 'up' } else { 'down' } }
# docker's own status text -> a health state. `docker ps -a` is used so a container that has DIED still appears (as down): it is the one
# state the full-screen Containers view exists to reveal. Never uses docker's ticking uptime (it would redraw the tile constantly).
function Get-ContainerState($status) {
  if ($status -match '^(Exited|Dead|Created|Restarting|Removal)') { return 'down' }
  if ($status -match 'unhealthy|health: starting|Paused') { return 'degraded' }
  if ($status -match '^Up') { return 'up' }
  'unknown'
}
# the 'Canary relay' light: the container's docker status plus the relay's own answer to "can you reach your data source?"
# ('true', 'false', or '' when it could not be read). 'up' needs both; a running relay that cannot reach its source is 'degraded'.
function Get-RelayState($status, $upstream) {
  if (-not $status) { return 'down' }                       # no such container
  $c = Get-ContainerState $status
  if ($c -ne 'up') { return $c }                            # down / degraded / unknown, straight from docker's status
  if ($upstream -eq 'true') { return 'up' }
  'degraded'                                                # running, but cannot reach its source or its answer was unreadable
}
# a health light with its hover/full-screen explanation; `why` (what is wrong right now) is attached only when the light is not up
function New-Light($name, $state, $explain, $why) {
  $l = [ordered]@{ name = $name; state = $state; explain = $explain }
  if ($why -and $state -ne 'up') { $l.detail = @{ why = $why } }
  $l
}

# ---- charts (Prometheus)
# {W} is the averaging window: 15m for the 12 h chart, 1h for the 7-day history (168 hourly buckets, aligned so the picture only changes when the data does)
$qCpu = "100 - avg(rate(node_cpu_seconds_total{job=`"$Job`",mode=`"idle`"}[{W}])) * 100"
$qMem = "avg_over_time(((1 - node_memory_MemAvailable_bytes{job=`"$Job`"} / node_memory_MemTotal_bytes{job=`"$Job`"}) * 100)[{W}:1m])"
$qTmp = "avg_over_time(node_hwmon_temp_celsius{job=`"$Job`",chip=`"pci0000:00_0000:00:18_3`",sensor=`"temp1`"}[{W}])"
$cpu = Get-Points $qCpu.Replace('{W}', '15m'); $mem = Get-Points $qMem.Replace('{W}', '15m'); $tmp = Get-Points $qTmp.Replace('{W}', '15m')
function Get-History($q) { try { Get-Points $q.Replace('{W}', '1h') 3600 168 } catch { $null } }     # history is a bonus: a failure here must not blank the tile
$charts = @(
  (New-Chart 'CPU' '% busy, 15 min avg' $cpu 70 90 $null 'Average CPU busy %, 15-minute buckets. Sustained values above 90% mean the host is overloaded.' (Get-History $qCpu)),
  (New-Chart 'Memory' '% used, 15 min avg' $mem 80 92 100 'Average memory in use %, 15-minute buckets. High and rising usually means a container is leaking.' (Get-History $qMem)),
  (New-Chart 'CPU temp' 'deg C, 15 min avg' $tmp 75 90 100 'CPU temperature in deg C, 15-minute buckets. Above 90 risks throttling.' (Get-History $qTmp)))

# ---- host facts (Prometheus instant)
$exporterUp = [double](Invoke-Prom '/api/v1/query' @{ query = "up{job=`"$Job`"}" } | Select-Object -First 1).value[1] -eq 1
$diskFree = [math]::Round([double](Invoke-Prom '/api/v1/query' @{ query = "node_filesystem_avail_bytes{job=`"$Job`",mountpoint=`"/`"}/node_filesystem_size_bytes{job=`"$Job`",mountpoint=`"/`"}*100" } | Select-Object -First 1).value[1])

# ---- router / uplink (one ssh, one script on stdin)
$probe = @'
W=eno1
lossof() { ping -c2 -W1 -q "$@" 2>/dev/null | sed -n 's/.* \([0-9.]*\)% packet loss.*/\1/p' | head -1; }
WGW=$(ip -4 route show default dev $W 2>/dev/null | awk '{print $3; exit}')
echo "ACTIVE_DEV=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1)"
echo "ETH_CARRIER=$(cat /sys/class/net/$W/carrier 2>/dev/null || echo 0)"
echo "WIRED_GW=${WGW:-}"
echo "WIRED_LOSS=$([ -n "$WGW" ] && lossof "$WGW" || echo 100)"
echo "WIRED_MAC=$([ -n "$WGW" ] && ip neigh show "$WGW" dev $W 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="lladdr") print tolower($(i+1))}' | head -1)"
echo "NET_LOSS=$(lossof 1.1.1.1)"
echo "RELAY_STATUS=$(docker ps -a --filter name='^/canary-relay$' --format '{{.Status}}' 2>/dev/null | head -1)"
echo "RELAY_UPSTREAM=$(docker exec canary-relay python -c "import json,urllib.request;print(str(json.load(urllib.request.urlopen('http://127.0.0.1:8091/healthz',timeout=4)).get('upstream_reachable')).lower())" 2>/dev/null)"
echo "CONTAINERS=$(docker ps -q --filter label=com.docker.compose.project=monitoring 2>/dev/null | wc -l)"
echo "CONTAINER_LIST=$(docker ps -a --filter label=com.docker.compose.project=monitoring --format '{{.Names}}|{{.Status}}' 2>/dev/null | tr '\n' ';')"
echo "UPTIME_S=$(cut -d. -f1 /proc/uptime)"
'@
$net = @{}; $routerKnown = $true
try {
  $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  # script travels as base64 so PowerShell's pipe encoding (BOM, CRLF) cannot corrupt it
  $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($probe -replace "`r", '')))
  $out = & $Ssh -o BatchMode=yes -o ConnectTimeout=5 "emac@$Host_" "echo $b64 | base64 -d | bash"
  $code = $LASTEXITCODE; $ErrorActionPreference = $old
  if ($code -ne 0) { throw "ssh exit $code" }
  foreach ($l in @($out)) { if ($l -match '^([A-Z_]+)=(.*)$') { $net[$Matches[1]] = $Matches[2].Trim() } }
  if (-not $net.ContainsKey('NET_LOSS')) { throw 'probe printed nothing usable' }
} catch { $routerKnown = $false; $ErrorActionPreference = 'Stop' }

$health = @()
$status = 'ok'; $label = 'ALL GREEN'; $uplink = '?'; $task = 'Router status unknown (ssh probe failed)'; $up = ''; $cont = '?'
$items = @(); $okc = 0
$exWired = 'The wired gateway answers ping and carries the default route.'; $exNet = 'Pings to 1.1.1.1 arrive with no packet loss.'; $exRelay = 'The read-only relay that feeds one of the wall tiles is running, healthy and can reach its data source.'
if ($routerKnown) {
  $num = { param($k) [double]::Parse(('0' + $net[$k]).Replace(',', '.'), $inv) }
  $wired = if ($net.ETH_CARRIER -ne '1' -or -not $net.WIRED_GW -or (& $num 'WIRED_LOSS') -ge 100) { 'down' }
           elseif ($net.ACTIVE_DEV -ne 'eno1' -or (& $num 'WIRED_LOSS') -gt 0) { 'degraded' } else { 'up' }
  $netS = if ((& $num 'NET_LOSS') -ge 100) { 'down' } elseif ((& $num 'NET_LOSS') -gt 0) { 'degraded' } else { 'up' }
  $relay = Get-RelayState $net.RELAY_STATUS $net.RELAY_UPSTREAM
  $relayWhy = if (-not $net.RELAY_STATUS) { 'The relay container does not exist.' }
              elseif ($relay -eq 'down') { 'The relay container is not running.' }
              elseif ($net.RELAY_UPSTREAM -eq 'false') { 'The relay is running but cannot reach its data source.' }
              else { 'The relay is starting, unhealthy, or its health answer could not be read.' }
  $isGl = ($net.WIRED_MAC -like "$GL_OUI*")
  $gwName = if ($isGl) { 'GL.iNet' } else { 'wired gateway' }
  $uplink = if ($net.ACTIVE_DEV -eq 'eno1') { if ($isGl) { 'GL.iNet' } else { 'Wired' } } else { 'Not wired' }
  $task = if ($net.ACTIVE_DEV -eq 'eno1') { "Running via $gwName travel router (wired)" } else { 'Not on the wired link - travel router not in path' }
  $cont = $net.CONTAINERS
  # what each known container does (unknown ones are listed without a purpose); states come from docker's own status text, never its ticking uptime
  $purpose = @{ grafana = 'Dashboards: draws the wall'; prometheus = 'Metrics database (5-year retention)'; pushgateway = 'Receives pushed wall series'
                'node-exporter' = 'Host CPU, memory, disk and temperature metrics'; 'slot-writer' = 'Draws and releases wall tiles; serves the wall page' }
  foreach ($e in (($net.CONTAINER_LIST) -split ';' | Where-Object { $_ })) {
    $nm, $stt = $e -split '\|', 2
    $items += @{ name = $nm; state = (Get-ContainerState $stt); what = $(if ($purpose[$nm]) { $purpose[$nm] } else { '' }) }
  }
  $okc = @($items | Where-Object { $_.state -eq 'up' }).Count
  $s = [int](& $num 'UPTIME_S'); $d = [math]::Floor($s / 86400); $h = [math]::Floor(($s % 86400) / 3600)
  $up = if ($d -gt 0) { "${d}d ${h}h" } else { "${h}h" }
  $wiredWhy = if ($net.ETH_CARRIER -ne '1') { 'The Ethernet link is down.' } elseif (-not $net.WIRED_GW) { 'There is no wired default route.' }
              elseif ((& $num 'WIRED_LOSS') -ge 100) { 'The wired gateway does not answer ping.' }
              elseif ($net.ACTIVE_DEV -ne 'eno1') { 'Traffic is not using the wired link.' } else { 'Pings to the wired gateway are dropping packets.' }
  $health += (New-Light 'Travel router' $wired $exWired $wiredWhy),
             (New-Light 'Internet' $netS $exNet $(if ($netS -eq 'down') { 'Every ping to 1.1.1.1 was lost.' } else { 'Some pings to 1.1.1.1 were lost.' })),
             (New-Light 'Canary relay' $relay $exRelay $relayWhy)
} else {
  $noProbe = 'The ssh probe to mini-mac failed, so this could not be checked.'
  $health += (New-Light 'Travel router' 'unknown' $exWired $noProbe), (New-Light 'Internet' 'unknown' $exNet $noProbe), (New-Light 'Canary relay' 'unknown' $exRelay $noProbe)
}
$noAnswer = 'The health endpoint did not answer.'
$health += (New-Light 'Grafana' (St (Test-Url "http://${Host_}:3000/api/health")) 'Grafana health endpoint answers (draws the wall dashboards).' $noAnswer),
           (New-Light 'Prometheus' (St (Test-Url "$Prom/-/healthy")) 'Prometheus health endpoint answers (stores the metrics).' $noAnswer),
           (New-Light 'Node exporter' (St $exporterUp) 'Prometheus can scrape the host metrics exporter.' 'Prometheus reports the exporter target as down.'),
           (New-Light 'Wall writer' (St (Test-Url "http://${Host_}:8088/wall/wall-top/version")) 'The slot-writer answers (it draws and refreshes the tiles).' $noAnswer)

$bad = @($health | Where-Object { $_.state -eq 'down' }); $odd = @($health | Where-Object { $_.state -in 'degraded', 'unknown' })
if ($routerKnown -and ($health | Where-Object { $_.name -eq 'Internet' }).state -eq 'down') { $status = 'fail'; $label = 'NO INTERNET' }
elseif ($routerKnown -and $net.ACTIVE_DEV -ne 'eno1') { $status = 'warn'; $label = 'OFF WIRED' }
elseif (-not $routerKnown) { $status = 'warn'; $label = 'NO ROUTER DATA' }
elseif ($bad.Count -gt 0) { $status = 'warn'; $label = "$($bad.Count) DOWN" }
elseif ($odd.Count -gt 0) { $status = 'warn'; $label = "$($odd.Count) DEGRADED" }

$stats = @(@{ label = 'UPLINK'; value = $uplink; explain = 'Which link carries mini-mac traffic: the wired travel router.' },
           @{ label = 'Disk free'; value = "$diskFree%"; explain = 'Free space on the root disk.' })
if ($up) { $stats += @{ label = 'Uptime'; value = $up; explain = 'Time since the host last booted.' } }
$cstat = @{ label = 'Containers'; value = $cont; explain = 'Running containers of the monitoring stack on mini-mac (the full-screen view also lists any that have stopped).' }
if ($items.Count -gt 0) { $cstat.detail = @{ why = "$okc of $($items.Count) healthy"; items = $items } }
$stats += $cstat

[ordered]@{
  status = $status; status_label = $label; task = $task; health = $health; stats = $stats; charts = $charts
  summary = 'The always-on host that runs the monitoring stack and the wall.'
  activity = [ordered]@{ state = $(if ($exporterUp) { 'active' } else { 'stalled' }); label = $(if ($up) { "up $up" } else { '' }) }
} | ConvertTo-Json -Depth 8 -Compress
