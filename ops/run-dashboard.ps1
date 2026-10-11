<#
.SYNOPSIS
Collect actual observations, run local zero-shot models, and refresh line plots.
.DESCRIPTION
Uses completed 1-hour candles and forecasts the next 24 hourly values.
Writes a local HTML report; only sources with public rights enter the site JSON.
Does not publish, train models, download weights, or register a scheduled task.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RuntimeEnvFile,
    [string]$StateDir,
    [ValidateSet('1h', '1d')]
    [string]$Frequency = '1h',
    [string]$ReportOutput,
    [switch]$ObservationsOnly,
    [switch]$NoSite,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
$corePython = Join-Path $repoPath 'pipeline\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $corePython -PathType Leaf)) { throw 'Core Python runtime is missing.' }
$runnerArgs = @((Join-Path $PSScriptRoot 'update_dashboard.py'), '--runtime-env-file', $RuntimeEnvFile)
$runnerArgs += @('--frequency', $Frequency)
if ($StateDir) { $runnerArgs += @('--state-dir', $StateDir) }
if ($ReportOutput) { $runnerArgs += @('--report-output', $ReportOutput) }
if ($ObservationsOnly) { $runnerArgs += '--observations-only' }
if ($NoSite) { $runnerArgs += '--no-site' }
if ($CheckOnly) { $runnerArgs += '--check-only' }
& $corePython @runnerArgs
exit $LASTEXITCODE
