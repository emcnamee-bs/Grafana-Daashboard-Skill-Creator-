# Registers GrafanaWall to start at logon and re-fire every 5 minutes as a watchdog (the supervisor's mutex makes extra
# launches exit immediately). Run: powershell -ExecutionPolicy Bypass -File Install.ps1
# Remove with: Unregister-ScheduledTask GrafanaWall -Confirm:$false
$script = Join-Path $PSScriptRoot 'GrafanaWall.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = 'PT20S'
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'GrafanaWall' -Action $action -Trigger @($logon, $watchdog) -Settings $settings -Force | Out-Null
Write-Host 'Registered scheduled task GrafanaWall (at logon + every 5 min watchdog).'
