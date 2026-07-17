@echo off
cd /d "%~dp0.."
claude -p "Read and execute automation/robinhood_daily.md exactly. Log everything." --allowedTools "mcp__robinhood__*,Read,Write,Bash,PowerShell,WebFetch" >> "%~dp0task_run.log" 2>&1
