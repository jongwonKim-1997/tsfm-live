<#
.SYNOPSIS
Collect sources, freeze on-time private forecasts, evaluate outcomes and update a local report.
.DESCRIPTION
Uses the actual KST date and a private journal. New inference starts only between
08:10 and 08:48 KST. Late/manual retries still collect, evaluate and export.
Never publishes to Git, creates a public receipt, installs packages or registers a task.
.EXAMPLE
.\ops\run-daily.ps1 -RuntimeEnvFile ..\..\work\model-smoke\runtime.env -CheckOnly
.EXAMPLE
.\ops\run-daily.ps1 -RuntimeEnvFile ..\..\work\model-smoke\runtime.env
.EXAMPLE
.\ops\run-daily.ps1 -RuntimeEnvFile ..\..\work\model-smoke\runtime.env -EvaluateOnly
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$RuntimeEnvFile,
    [string]$StateDir,
    [switch]$EvaluateOnly,
    [switch]$CheckOnly,
    [switch]$SourceProbeNetwork,
    [ValidateRange(1, 3)]
    [int]$Retries = 2
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$repoPath = Split-Path -Parent $PSScriptRoot
$corePython = Join-Path $repoPath 'pipeline\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $corePython -PathType Leaf)) {
    Write-Error 'Core runtime missing. Run: uv sync --project pipeline --frozen --python 3.12'
    exit 1
}
$runnerArgs = @((Join-Path $PSScriptRoot 'daily_local.py'), '--runtime-env-file', $RuntimeEnvFile,
                '--retries', [string]$Retries)
if ($StateDir) { $runnerArgs += @('--state-dir', $StateDir) }
if ($EvaluateOnly) { $runnerArgs += '--evaluate-only' }
if ($CheckOnly) { $runnerArgs += '--check-only' }
if ($SourceProbeNetwork) { $runnerArgs += '--source-probe-network' }
try {
    & $corePython @runnerArgs
    $runnerExitCode = $LASTEXITCODE
    if ($null -eq $runnerExitCode) { throw 'Core runtime did not return an exit status.' }
    exit $runnerExitCode
} catch {
    Write-Error ('Daily launcher failed: ' + $_.Exception.GetType().Name)
    exit 1
}
