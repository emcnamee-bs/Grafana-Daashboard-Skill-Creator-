# Builds the blank 3-monitor x 6-slot Grafana wall (18 slots) and pushes it to Grafana.
# Usage: .\build_board.ps1 [-Grafana http://mini-mac:3000] [-Token TOKEN] [-Dry]
# Dashboards (uids): wall-top (slots 01-06), wall-middle (07-12), wall-bottom (13-18). Each slot is 640x540 on a 1920x1080 kiosk.
param([string]$Grafana = 'http://mini-mac:3000', [string]$Token = $env:GRAFANA_TOKEN, [switch]$Dry)
$cols = 3; $w = 8; $h = 13
function New-Slot($sid, $i) {
  $r = [math]::Floor($i / $cols); $c = $i % $cols
  $n = '{0:00}' -f $sid
  $html = "<div style='box-sizing:border-box;height:100%;border:1px solid #1f5fae;border-radius:8px;box-shadow:inset 0 0 18px rgba(31,95,174,.25);display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:Inter,sans-serif;letter-spacing:.2em'><div style='font-size:43px;font-weight:700;color:#1f3a5f'>$n</div><div style='font-size:14px;color:#3b4f6b'>VACANT</div></div>"
  @{ id = $sid; type = 'text'; title = ""; transparent = $true; gridPos = @{ x = $c * $w; y = $r * $h; w = $w; h = $h }
     options = @{ mode = 'html'; content = $html } }
}
$headers = @{}; if ($Token) { $headers.Authorization = "Bearer $Token" }
foreach ($m in @(@('top', 1), @('middle', 7), @('bottom', 13))) {
  $panels = 0..5 | ForEach-Object { New-Slot ($m[1] + $_) $_ }
  $dash = @{ uid = "wall-$($m[0])"; title = "Wall - $($m[0])"; tags = @('wall'); timezone = 'browser'; refresh = '30s'; editable = $true
             schemaVersion = 39; time = @{ from = 'now-6h'; to = 'now' }; panels = @($panels) }
  $body = @{ dashboard = $dash; overwrite = $true; message = 'blank board' } | ConvertTo-Json -Depth 12
  if ($Dry) { $body; continue }
  Invoke-RestMethod -Uri "$Grafana/api/dashboards/db" -Method Post -Body $body -ContentType 'application/json; charset=utf-8' -Headers $headers
}
