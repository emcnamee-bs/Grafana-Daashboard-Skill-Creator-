# Tests how refresh.ps1 turns a `docker ps -a` status string into a health state, without running the hook (it talks to the network).
# A container that has died must show as down: it is the one state the full-screen Containers view exists to reveal.
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'refresh.ps1'), [ref]$null, [ref]$null)
$fn = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-ContainerState' }, $true)
if (-not $fn) { 'FAIL  Get-ContainerState is not defined in refresh.ps1'; exit 1 }
. ([scriptblock]::Create($fn.Extent.Text))
$cases = [ordered]@{
  'Up 3 hours'                        = 'up'
  'Up 3 hours (healthy)'              = 'up'
  'Up 5 seconds (health: starting)'   = 'degraded'
  'Up 2 hours (unhealthy)'            = 'degraded'
  'Up 2 hours (Paused)'               = 'degraded'
  'Exited (1) 5 minutes ago'          = 'down'
  'Exited (0) 2 days ago'             = 'down'
  'Dead'                              = 'down'
  'Created'                           = 'down'
  'Restarting (1) 3 seconds ago'      = 'down'
  ''                                  = 'unknown'
}
$bad = 0
foreach ($k in $cases.Keys) {
  $got = Get-ContainerState $k
  if ($got -eq $cases[$k]) { 'PASS  {0,-34} -> {1}' -f "'$k'", $got } else { $bad++; 'FAIL  {0,-34} -> {1} (wanted {2})' -f "'$k'", $got, $cases[$k] }
}
"{0}/{1} passed" -f ($cases.Count - $bad), $cases.Count
if ($bad) { exit 1 }
