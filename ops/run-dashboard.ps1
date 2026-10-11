<#
.SYNOPSIS
Collect actual observations, run local zero-shot models, and refresh line plots.
.DESCRIPTION
Uses the real clock and the next market session. It has no morning-only gate.
Writes a local HTML report and the site's local_dashboard.json source snapshot.
Does not publish, train models, download weights, or register a scheduled task.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RuntimeEnvFile,
    [string]$StateDir,
    [switch]$ObservationsOnly,
    [switch]$NoSite,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
$corePython = Join-Path $repoPath 'pipeline\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $corePython -PathType Leaf)) { throw 'Core Python runtime is missing.' }
$runnerArgs = @((Join-Path $PSScriptRoot 'update_dashboard.py'), '--runtime-env-file', $RuntimeEnvFile)
if ($StateDir) { $runnerArgs += @('--state-dir', $StateDir) }
if ($ObservationsOnly) { $runnerArgs += '--observations-only' }
if ($NoSite) { $runnerArgs += '--no-site' }
if ($CheckOnly) { $runnerArgs += '--check-only' }
& $corePython @runnerArgs
exit $LASTEXITCODE
