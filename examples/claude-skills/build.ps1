# Builds tile.json (a rotating "Claude Skills" showcase for wall slot 7) from items.txt (group|title|one-line description).
# Usage: .\build.ps1 [-Slot 7] [-Interval 10]   then: wall.ps1 snapshot -File tile.json
param([int]$Slot = 7, [int]$Interval = 10)
$items = Get-Content (Join-Path $PSScriptRoot 'items.txt') -Encoding UTF8 | Where-Object { $_.Trim() } | ForEach-Object {
  $g, $t, $d = $_ -split '\|', 3
  [ordered]@{ group = $g; title = $t; text = $d }
}
[ordered]@{
  project = 'claude-skills'; name = 'Claude Skills'; status = 'ok'; status_label = "$($items.Count) SKILLS"; slot = $Slot
  showcase = [ordered]@{ interval = $Interval; items = @($items) }
} | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $PSScriptRoot 'tile.json') -Encoding UTF8
"wrote tile.json with $($items.Count) skills, $Interval s each (loop $($items.Count * $Interval) s)"
