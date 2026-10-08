# Registers task GrafanaWallWake: every day at -At (default 10:00) it WAKES the PC from sleep and runs Wake-Wall.ps1
# (lights the displays, makes sure the wall supervisor is running).
# Usage: powershell -ExecutionPolicy Bypass -File Install-Wake.ps1 [-At 10:00]
# Change the time: run again with a new -At.   Remove: Unregister-ScheduledTask GrafanaWallWake -Confirm:$false
# A shut-down PC cannot be woken by Windows (only by the BIOS RTC alarm); the task stays registered and is armed again whenever
# the PC is on and goes to sleep. -StartWhenAvailable: if the PC was off at that time, the task runs once as soon as it is back on.
param([string]$At = '10:00')
$script = Join-Path $PSScriptRoot 'Wake-Wall.ps1'
$action = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'GrafanaWallWake' -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Registered GrafanaWallWake: daily $At, wakes the PC from sleep."
