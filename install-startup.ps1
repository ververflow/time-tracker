# Makes the tracker start automatically every time you log in.
$startup = [Environment]::GetFolderPath('Startup')
$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut((Join-Path $startup 'TimeTracker.lnk'))
$lnk.TargetPath = (Join-Path $PSScriptRoot 'start-tracker.vbs')
$lnk.WorkingDirectory = $PSScriptRoot
$lnk.Description = 'Local Time Tracker'
$lnk.Save()
Write-Host "Installed. The tracker will now start automatically when you log in." -ForegroundColor Green
Write-Host "Starting it now too..."
& (Join-Path $PSScriptRoot 'start-tracker.vbs')
