# Tests how refresh.ps1 turns the relay container's docker status text and its health answer into the 'Canary relay' light,
# without running the hook (it talks to the network). The light is only 'up' when the container is healthy AND the relay
# reports that it can reach its data source; a running relay that cannot reach its source is the case worth seeing.
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'refresh.ps1'), [ref]$null, [ref]$null)
foreach ($name in 'Get-ContainerState', 'Get-RelayState') {
  $fn = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true)
  if (-not $fn) { "FAIL  $name is not defined in refresh.ps1"; exit 1 }
  . ([scriptblock]::Create($fn.Extent.Text))
}
# status text | upstream answer ('true', 'false' or '' when it could not be read) -> light state
$cases = @(
  @('Up 3 hours (healthy)',             'true',  'up'),
  @('Up 3 hours',                       'true',  'up'),
  @('Up 3 hours (healthy)',             'false', 'degraded'),   # running, but cannot reach its source
  @('Up 3 hours (healthy)',             '',      'degraded'),   # running, health answer unreadable
  @('Up 5 seconds (health: starting)',  'true',  'degraded'),
  @('Up 2 hours (unhealthy)',           'true',  'degraded'),
  @('Exited (0) 2 minutes ago',         '',      'down'),
  @('Restarting (1) 5 seconds ago',     '',      'down'),
  @('Created',                          '',      'down'),
  @('',                                 '',      'down'),       # no such container
  @('something unexpected',             '',      'unknown')
)
$bad = 0
foreach ($c in $cases) {
  $got = Get-RelayState $c[0] $c[1]
  $label = "'{0}' / '{1}'" -f $c[0], $c[1]
  if ($got -eq $c[2]) { 'PASS  {0,-52} -> {1}' -f $label, $got } else { $bad++; 'FAIL  {0,-52} -> {1} (wanted {2})' -f $label, $got, $c[2] }
}
# mini-mac no longer uses Wi-Fi (it caused a network loop through the switch), so the hook must not mention it any more.
$wifiHits = @(Select-String -Path (Join-Path $PSScriptRoot 'refresh.ps1') -Pattern 'wi-fi|wifi|wlp1s0')
if ($wifiHits.Count -eq 0) { 'PASS  refresh.ps1 has no Wi-Fi references' } else { $bad++; $wifiHits | ForEach-Object { 'FAIL  Wi-Fi reference at line {0}: {1}' -f $_.LineNumber, $_.Line.Trim().Substring(0, [Math]::Min(90, $_.Line.Trim().Length)) } }
$total = $cases.Count + 1
"{0}/{1} passed" -f ($total - $bad), $total
if ($bad) { exit 1 }
