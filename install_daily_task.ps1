<#
    install_daily_task.ps1 - register the daily run with Windows Task Scheduler.

    Usage (no admin rights needed - it registers under your own account):

        powershell -ExecutionPolicy Bypass -File .\install_daily_task.ps1
        powershell -ExecutionPolicy Bypass -File .\install_daily_task.ps1 -At 07:30
        powershell -ExecutionPolicy Bypass -File .\install_daily_task.ps1 -Remove

    The task runs whether or not you are logged in is NOT set, deliberately:
    it runs when you are logged on, and catches up if the machine was asleep at
    the scheduled time.
#>

[CmdletBinding()]
param(
    [string]$At = '09:00',
    [string]$TaskName = 'ScholarshipTracker-Daily',
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $root 'run_daily.ps1'

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'."
    } else {
        Write-Host "No scheduled task named '$TaskName' to remove."
    }
    return
}

if (-not (Test-Path $script)) {
    Write-Error "Cannot find $script"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -MultipleInstances IgnoreNew

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description 'Rebuilds the fully-funded BSc scholarship tracker: checks official links, re-reads watched pages, recalculates deadlines.' | Out-Null

Write-Host "Registered '$TaskName' to run every day at $At."
Write-Host "Run it now with:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove it with:   .\install_daily_task.ps1 -Remove"
