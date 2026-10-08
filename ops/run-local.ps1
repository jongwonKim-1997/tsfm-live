<#
.SYNOPSIS
Run the benchmark locally with existing CPU runtimes and cached weights.
.DESCRIPTION
Always performs a dry-run. Does not publish, install packages, download weights,
load credentials, or register a scheduled task. The runtime environment file
must be outside the public repository. Source data may be fetched over HTTPS.
.EXAMPLE
.\ops\run-local.ps1 -RuntimeEnvFile ..\..\work\model-smoke\runtime.env
.EXAMPLE
.\ops\run-local.ps1 -RuntimeEnvFile ..\..\work\model-smoke\runtime.env -CheckOnly
.EXAMPLE
.\ops\run-local.ps1 -RuntimeEnvFile ..\..\work\model-smoke\runtime.env -AsOf 2026-10-07
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$RuntimeEnvFile,
    [string]$AsOf,
    [string]$CacheDir,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$repoPath = Split-Path -Parent $PSScriptRoot
$corePython = Join-Path $repoPath 'pipeline\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $corePython -PathType Leaf)) {
    Write-Error 'Core runtime missing. Run: uv sync --project pipeline --frozen --python 3.12'
    exit 1
}

$runnerArgs = @((Join-Path $PSScriptRoot 'local_run.py'), '--runtime-env-file', $RuntimeEnvFile)
if ($AsOf) { $runnerArgs += @('--as-of', $AsOf) }
if ($CacheDir) { $runnerArgs += @('--cache-dir', $CacheDir) }
if ($CheckOnly) { $runnerArgs += '--check-only' }

try {
    & $corePython @runnerArgs
    $runnerExitCode = $LASTEXITCODE
    if ($null -eq $runnerExitCode) { throw 'Core runtime did not return an exit status.' }
    exit $runnerExitCode
} catch {
    Write-Error $_
    exit 1
}
