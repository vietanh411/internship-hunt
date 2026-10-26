# Registers a Windows Task Scheduler job that runs the pipeline daily at 9:00 AM
# local time (the PC is set to Central time). It wakes the PC from sleep, runs on
# battery, and catches up if the PC was off at 9:00. It runs without a window
# (pythonw.exe), so there is no console to close by accident. Output: data\task.log.
# Remove with:  Unregister-ScheduledTask -TaskName "Summer2027Hunt" -Confirm:$false
$root = Split-Path -Parent $PSScriptRoot
$pythonw = "$root\.venv\Scripts\pythonw.exe"
$log = "$root\data\task.log"
$action = New-ScheduledTaskAction -Execute $pythonw `
  -Argument "-m hunt --log-file `"$log`" run --max-minutes 170" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName "Summer2027Hunt" -Action $action -Trigger $trigger -Settings $settings `
  -Description "Viet Anh's Summer 2027 internship pipeline (daily 9:00)" -Force | Out-Null
Write-Host "Registered task 'Summer2027Hunt' (daily 9:00 AM)."
