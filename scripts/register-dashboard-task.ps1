# Starts the dashboard (http://localhost:8000) without a window whenever you sign in
# to Windows, so Finish application / Finish all are always available. It runs in your
# desktop session, so the browser windows those buttons open appear on your screen.
# Output: data\dashboard.log. Restarts itself if it stops unexpectedly.
# Remove with:  Unregister-ScheduledTask -TaskName "Summer2027HuntDashboard" -Confirm:$false
$root = Split-Path -Parent $PSScriptRoot
$pythonw = "$root\.venv\Scripts\pythonw.exe"
$log = "$root\data\dashboard.log"
$action = New-ScheduledTaskAction -Execute $pythonw `
  -Argument "-m hunt --log-file `"$log`" serve --port 8000" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
  -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Summer2027HuntDashboard" -Action $action -Trigger $trigger -Settings $settings `
  -Description "Viet Anh's Summer 2027 Hunt dashboard at http://localhost:8000 (starts at sign-in)" -Force | Out-Null
Write-Host "Registered task 'Summer2027HuntDashboard' (starts at sign-in)."
