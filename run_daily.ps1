<#
    run_daily.ps1 - what the scheduled task actually executes.

    Runs the updater, keeps a rolling log, and exits non-zero if the run failed
    so Task Scheduler shows the failure in its history instead of silently
    reporting success.
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    $python = (Get-Command py -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    Write-Error 'Python not found on PATH.'
    exit 1
}

& $python "$root\update.py"
$code = $LASTEXITCODE

# Keep the last 60 daily logs, drop the rest.
Get-ChildItem "$root\logs\update-*.log" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 60 |
    Remove-Item -Force -ErrorAction SilentlyContinue

exit $code
