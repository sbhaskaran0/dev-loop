# Register the daily dev-loop task at 09:30 (after the 09:00 watchlist
# refresh). Uses PowerShell cmdlets, NOT schtasks — schtasks loses quoting on
# paths with spaces and defaults to AC-power-only (learned on this machine).
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$runCmd = Join-Path (Split-Path -Parent $here) "scripts\run.cmd"

$action = New-ScheduledTaskAction -Execute $runCmd
$trigger = New-ScheduledTaskTrigger -Daily -At 09:30
Register-ScheduledTask -TaskName "DevLoop Daily" -Action $action -Trigger $trigger -Force

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 6)
Set-ScheduledTask -TaskName "DevLoop Daily" -Settings $settings

Get-ScheduledTask -TaskName "DevLoop Daily" | Format-List TaskName, State
Write-Host "Registered. Test now with: Start-ScheduledTask -TaskName 'DevLoop Daily'"
