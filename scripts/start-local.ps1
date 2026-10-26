# Starts the dashboard (http://127.0.0.1:8000) with the built-in 09:00 Central scheduler.
# The scheduler only fires while this window/process is running. To run daily even
# when this server is not open, either deploy (see README) or register the Windows
# scheduled task with scripts\register-windows-task.ps1 (your PC must be on/awake).
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
& "$root\.venv\Scripts\python.exe" -m hunt serve
