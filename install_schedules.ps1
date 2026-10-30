# install_schedules.ps1 — Windows Task Scheduler Setup (v4.0.0)
# Registers scheduled automation tasks for SCOUT and ANALYST pipeline.

$WorkDir = $PSScriptRoot
if (-not $WorkDir) { $WorkDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $WorkDir) { $WorkDir = (Get-Location).Path }

$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) { $PythonExe = "python" }

Write-Host "[SCHEDULE] Configuring Windows Scheduled Tasks in $WorkDir..." -ForegroundColor Cyan

$TaskSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

$PipelineCmd = "Set-Location '$WorkDir'; & '$PythonExe' scout_agent.py run --mode clustered >> '$WorkDir\pipeline.log' 2>&1; & '$PythonExe' analyst_agent.py --run >> '$WorkDir\pipeline.log' 2>&1"
$ActionPipeline = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -Command `"$PipelineCmd`"" `
    -WorkingDirectory $WorkDir
$TriggerPipeline = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "08:30AM"

Register-ScheduledTask -TaskName "CareerOps_01_ScoutAndAnalyst" `
    -Action $ActionPipeline `
    -Trigger $TriggerPipeline `
    -Settings $TaskSettings `
    -Description "Daily 08:30 AM SCOUT + ANALYST Pipeline Execution" -Force

$ActionBrief = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument "/c start `"`" `"$WorkDir\index.html`" && start `"`" `"$WorkDir\morning_brief.md`" && start `"`" `"$WorkDir\proposals_ready.md`"" `
    -WorkingDirectory $WorkDir
$TriggerBrief = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "08:45AM"

Register-ScheduledTask -TaskName "CareerOps_02_MorningBriefOpen" `
    -Action $ActionBrief `
    -Trigger $TriggerBrief `
    -Settings $TaskSettings `
    -Description "Daily 08:45 AM Opens Dashboard index.html and Morning Briefing" -Force

Write-Host "[OK] Registered Windows Scheduled Tasks in $WorkDir" -ForegroundColor Green
