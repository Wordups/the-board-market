# Registers the daily Robinhood pilot as a Windows Scheduled Task.
# Run once: powershell -File automation\register_task.ps1
# Remove with: schtasks /Delete /TN "BoardMarketRobinhoodDaily" /F

# 9:45 AM ET = 15 min after open, after the Pages board cron (8:15 ET) has refreshed.
# Adjust /ST if this machine is not on Eastern time.
$wrapper = Join-Path $PSScriptRoot "run_daily.cmd"
schtasks /Create /F /TN "BoardMarketRobinhoodDaily" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:45 /TR "`"$wrapper`""

Write-Host "Registered. Test now with: schtasks /Run /TN BoardMarketRobinhoodDaily"
Write-Host "Runs in DRY-RUN until automation\LIVE_ENABLED exists."
