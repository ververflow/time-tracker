# Removes the tracker from automatic startup (does not delete your data).
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'TimeTracker.lnk'
if (Test-Path $lnk) {
    Remove-Item $lnk -Force
    Write-Host "Removed from startup." -ForegroundColor Yellow
} else {
    Write-Host "It wasn't set to start automatically."
}
