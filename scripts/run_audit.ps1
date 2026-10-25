<#
.SYNOPSIS
    Runs the invoice audit. Called by the Power Automate Desktop flow (or by hand).

.DESCRIPTION
    Goes to the project folder, runs `uv run audit run --config <Config>`, saves the console output to
    logs\pad_<timestamp>.log and passes the CLI's exit code back (0 = done, 2 = done but some files failed,
    1 = fatal). The last two lines are always:
        WORKPAPER: <full path to the .xlsx>      (only when a workpaper was written)
        EXITCODE: <n>
    With -ArchiveInbox, files in the inbox folders are moved to processed\<timestamp>\ after a run that
    completed (exit code 0 or 2), so they are not processed again.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\run_audit.ps1 -Config runs\pad_run.toml -ArchiveInbox
#>
param(
    [Parameter(Mandatory = $true)][string]$Config,
    [ValidateSet("auto", "live", "batch")][string]$Mode = "auto",
    [switch]$ArchiveInbox,
    [string]$InboxDir = "inbox",
    [string]$ProcessedDir = "processed"
)

$ErrorActionPreference = "Continue"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

# Power Automate may start PowerShell with an old PATH; reload it so `uv` is found.
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
$env:PYTHONIOENCODING = "utf-8"
$env:NO_COLOR = "1"
$env:COLUMNS = "160"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Output "uv was not found. Install it with: winget install --id=astral-sh.uv -e"
    Write-Output "EXITCODE: 1"
    exit 1
}

New-Item -ItemType Directory -Force (Join-Path $InboxDir "main"), (Join-Path $InboxDir "cutoff"), "logs" | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = Join-Path "logs" "pad_$stamp.log"

# Run the audit; show the output and keep a copy in the log.
& uv run audit run --config $Config --mode $Mode 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log
$code = $LASTEXITCODE

if ($ArchiveInbox -and ($code -eq 0 -or $code -eq 2)) {
    foreach ($test in @("main", "cutoff")) {
        $source = Join-Path $InboxDir $test
        $files = Get-ChildItem -Path $source -Force -ErrorAction SilentlyContinue
        if ($files) {
            $target = Join-Path (Join-Path $ProcessedDir $stamp) $test
            New-Item -ItemType Directory -Force $target | Out-Null
            $files | Move-Item -Destination $target -Force
        }
    }
    Write-Output "Inbox files moved to $(Join-Path $ProcessedDir $stamp)"
}

Write-Output "Log: $log"
Write-Output "EXITCODE: $code"
exit $code
