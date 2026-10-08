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
function Get-Points($query) {
  $end = [long]([math]::Floor([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() / $Bucket) * $Bucket)
  $res = Invoke-Prom '/api/v1/query_range' @{ query = $query; start = $end - ($Buckets - 1) * $Bucket; end = $end; step = $Bucket }
  $vals = @($res | Select-Object -First 1).values
  if (-not $vals) { throw "no data for $query" }
  @($vals | ForEach-Object { , @([long]$_[0], [math]::Round([double]::Parse($_[1], $inv), 1)) })
}
function New-Chart($title, $subtitle, $pts, $warnAt, $badAt, $yMax) {
  $v = @($pts | ForEach-Object { $_[1] })
  $avg = [math]::Round(($v | Measure-Object -Average).Average, 1); $max = [math]::Round(($v | Measure-Object -Maximum).Maximum, 1)
  $st = if ($max -ge $badAt) { 'bad' } elseif ($max -ge $warnAt) { 'warn' } else { 'ok' }
  $c = [ordered]@{ title = $title; subtitle = $subtitle; kind = 'line'; span_label = '12h'; points = $pts
                   kpis = @(@{ label = 'AVG 12H'; value = ('{0}' -f $avg.ToString($inv)); state = 'ok' }, @{ label = 'PEAK 12H'; value = ('{0}' -f $max.ToString($inv)); state = $st }) }
  if ($yMax) { $c.y_max = $yMax }
  $c
}
function Test-Url($url) { try { (Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch { $false } }
function St($ok) { if ($ok) { 'up' } else { 'down' } }

# ---- charts (Prometheus)
$cpu = Get-Points "100 - avg(rate(node_cpu_seconds_total{job=`"$Job`",mode=`"idle`"}[15m])) * 100"
$mem = Get-Points "avg_over_time(((1 - node_memory_MemAvailable_bytes{job=`"$Job`"} / node_memory_MemTotal_bytes{job=`"$Job`"}) * 100)[15m:1m])"
$tmp = Get-Points "avg_over_time(node_hwmon_temp_celsius{job=`"$Job`",chip=`"pci0000:00_0000:00:18_3`",sensor=`"temp1`"}[15m])"
$charts = @(
  (New-Chart 'CPU' '% busy, 15 min avg' $cpu 70 90 $null),
  (New-Chart 'Memory' '% used, 15 min avg' $mem 80 92 100),
  (New-Chart 'CPU temp' 'deg C, 15 min avg' $tmp 75 90 100))

# ---- host facts (Prometheus instant)
$exporterUp = [double](Invoke-Prom '/api/v1/query' @{ query = "up{job=`"$Job`"}" } | Select-Object -First 1).value[1] -eq 1
$diskFree = [math]::Round([double](Invoke-Prom '/api/v1/query' @{ query = "node_filesystem_avail_bytes{job=`"$Job`",mountpoint=`"/`"}/node_filesystem_size_bytes{job=`"$Job`",mountpoint=`"/`"}*100" } | Select-Object -First 1).value[1])

# ---- router / uplink (one ssh, one script on stdin)
$probe = @'
W=eno1; F=wlp1s0
lossof() { ping -c2 -W1 -q "$@" 2>/dev/null | sed -n 's/.* \([0-9.]*\)% packet loss.*/\1/p' | head -1; }
WGW=$(ip -4 route show default dev $W 2>/dev/null | awk '{print $3; exit}')
FGW=$(ip -4 route show default dev $F 2>/dev/null | awk '{print $3; exit}')
echo "ACTIVE_DEV=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1)"
echo "ETH_CARRIER=$(cat /sys/class/net/$W/carrier 2>/dev/null || echo 0)"
echo "WIRED_GW=${WGW:-}"
echo "WIRED_LOSS=$([ -n "$WGW" ] && lossof "$WGW" || echo 100)"
echo "WIRED_MAC=$([ -n "$WGW" ] && ip neigh show "$WGW" dev $W 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="lladdr") print tolower($(i+1))}' | head -1)"
echo "WIFI_GW=${FGW:-}"
echo "WIFI_LOSS=$([ -n "$FGW" ] && lossof -I $F "$FGW" || echo 100)"
echo "NET_LOSS=$(lossof 1.1.1.1)"
echo "CONTAINERS=$(docker ps -q 2>/dev/null | wc -l)"
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
if ($routerKnown) {
  $num = { param($k) [double]::Parse(('0' + $net[$k]).Replace(',', '.'), $inv) }
  $wired = if ($net.ETH_CARRIER -ne '1' -or -not $net.WIRED_GW -or (& $num 'WIRED_LOSS') -ge 100) { 'down' }
           elseif ($net.ACTIVE_DEV -ne 'eno1' -or (& $num 'WIRED_LOSS') -gt 0) { 'degraded' } else { 'up' }
  $netS = if ((& $num 'NET_LOSS') -ge 100) { 'down' } elseif ((& $num 'NET_LOSS') -gt 0) { 'degraded' } else { 'up' }
  $wifi = if (-not $net.WIFI_GW -or (& $num 'WIFI_LOSS') -ge 100) { 'down' } elseif ((& $num 'WIFI_LOSS') -gt 0) { 'degraded' } else { 'up' }
  $isGl = ($net.WIRED_MAC -like "$GL_OUI*")
  $gwName = if ($isGl) { 'GL.iNet' } else { 'wired gateway' }
  $uplink = if ($net.ACTIVE_DEV -eq 'eno1') { if ($isGl) { 'GL.iNet' } else { 'Wired' } } else { 'Wi-Fi' }
  $task = if ($net.ACTIVE_DEV -eq 'eno1') { "Running via $gwName travel router (wired)" } else { 'On Wi-Fi backup - travel router not in path' }
  $cont = $net.CONTAINERS
  $s = [int](& $num 'UPTIME_S'); $d = [math]::Floor($s / 86400); $h = [math]::Floor(($s % 86400) / 3600)
  $up = if ($d -gt 0) { "${d}d ${h}h" } else { "${h}h" }
  $health += @{ name = 'Travel router'; state = $wired }, @{ name = 'Internet'; state = $netS }, @{ name = 'Wi-Fi backup'; state = $wifi }
} else {
  $health += @{ name = 'Travel router'; state = 'unknown' }, @{ name = 'Internet'; state = 'unknown' }, @{ name = 'Wi-Fi backup'; state = 'unknown' }
}
$health += @{ name = 'Grafana'; state = (St (Test-Url "http://${Host_}:3000/api/health")) },
           @{ name = 'Prometheus'; state = (St (Test-Url "$Prom/-/healthy")) },
           @{ name = 'Node exporter'; state = (St $exporterUp) },
           @{ name = 'Wall writer'; state = (St (Test-Url "http://${Host_}:8088/wall/wall-top/version")) }

$bad = @($health | Where-Object { $_.state -eq 'down' }); $odd = @($health | Where-Object { $_.state -in 'degraded', 'unknown' })
if ($routerKnown -and ($health | Where-Object { $_.name -eq 'Internet' }).state -eq 'down') { $status = 'fail'; $label = 'NO INTERNET' }
elseif ($routerKnown -and $net.ACTIVE_DEV -ne 'eno1') { $status = 'warn'; $label = 'ON WI-FI' }
elseif (-not $routerKnown) { $status = 'warn'; $label = 'NO ROUTER DATA' }
elseif ($bad.Count -gt 0) { $status = 'warn'; $label = "$($bad.Count) DOWN" }
elseif ($odd.Count -gt 0) { $status = 'warn'; $label = "$($odd.Count) DEGRADED" }

$stats = @(@{ label = 'UPLINK'; value = $uplink }, @{ label = 'Disk free'; value = "$diskFree%" })
if ($up) { $stats += @{ label = 'Uptime'; value = $up } }
$stats += @{ label = 'Containers'; value = $cont }

[ordered]@{
  status = $status; status_label = $label; task = $task; health = $health; stats = $stats; charts = $charts
  activity = [ordered]@{ state = $(if ($exporterUp) { 'active' } else { 'stalled' }); label = $(if ($up) { "up $up" } else { '' }) }
} | ConvertTo-Json -Depth 8 -Compress
