<#
.SYNOPSIS
Preview, explicitly install, or uninstall the user's local TSFM daily task.
.DESCRIPTION
Default Preview changes nothing. Installation is opt-in with -Action Install.
Requires the Windows time zone Korea Standard Time and an interactive user login.
Benchmark runs at 06:10 and 08:10 KST. Dashboard runs hourly at minute 05
and refreshes completed hourly actuals plus 24-hour local zero-shot line plots.
No passwords, cloud services or public publication are configured.
.EXAMPLE
.\ops\configure-daily-task.ps1 -RuntimeEnvFile ..\..\work\model-smoke\runtime.env
.EXAMPLE
.\ops\configure-daily-task.ps1 -RuntimeEnvFile ..\..\work\model-smoke\runtime.env -Action Install
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('Preview', 'Install', 'Uninstall')]
    [string]$Action = 'Preview',
    [string]$RuntimeEnvFile,
    [string]$StateDir,
    [switch]$SourceProbeNetwork,
    [ValidateSet('Benchmark', 'Dashboard')]
    [string]$Runner = 'Benchmark',
    [ValidatePattern('^[A-Za-z0-9_-]+$')]
    [string]$TaskName = 'TSFM-Local-Daily'
)
$ErrorActionPreference = 'Stop'
if ($Action -eq 'Uninstall') {
    if ($PSCmdlet.ShouldProcess($TaskName, 'Unregister local TSFM scheduled task')) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    return
}
if ((Get-TimeZone).Id -ne 'Korea Standard Time') {
    throw 'This task definition requires Windows time zone Korea Standard Time. No system setting was changed.'
}
if (-not $RuntimeEnvFile) { throw 'RuntimeEnvFile is required for Preview or Install.' }
$resolvedEnv = (Resolve-Path -LiteralPath $RuntimeEnvFile).Path
$repoPath = Split-Path -Parent $PSScriptRoot
$runnerScript = Join-Path $PSScriptRoot 'run-daily.ps1'
if ($Runner -eq 'Dashboard') { $runnerScript = Join-Path $PSScriptRoot 'run-dashboard.ps1' }
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $runnerScript + '" -RuntimeEnvFile "' + $resolvedEnv + '"'
$program = 'powershell.exe'
if ($Runner -eq 'Dashboard') {
    # Use the installed GUI Python executable for a quiet background task.
    # Windows PowerShell script policy does not affect native Python execution.
    $program = Join-Path $repoPath 'pipeline\.venv\Scripts\pythonw.exe'
    if (-not (Test-Path -LiteralPath $program -PathType Leaf)) { throw 'The installed Python GUI runtime is missing.' }
    $arguments = '-X utf8 "' + (Join-Path $PSScriptRoot 'update_dashboard.py') + '" --runtime-env-file "' + $resolvedEnv + '"'
    $arguments += ' --frequency 1h'
}
if ($StateDir) {
    $resolvedState = [System.IO.Path]::GetFullPath($StateDir)
    if ($Runner -eq 'Dashboard') { $arguments += ' --state-dir "' + $resolvedState + '"' }
    else { $arguments += ' -StateDir "' + $resolvedState + '"' }
}
if ($SourceProbeNetwork -and $Runner -eq 'Dashboard') { throw 'SourceProbeNetwork applies only to the Benchmark runner.' }
if ($SourceProbeNetwork) { $arguments += ' -SourceProbeNetwork' }
$description = 'Private TSFM diagnostic loop. 06:10 KST evaluates prior outcomes; 08:10 KST also admits new on-time forecasts. No public publishing.'
$times = @('06:10', '08:10')
if ($Runner -eq 'Dashboard') {
    $times = @(0..23 | ForEach-Object { '{0:D2}:05' -f $_ })
    $description = 'Hourly local zero-shot line plots at minute 05. Completed 1-hour candles and next 24 hourly values. Personal-use data stays local. No automatic public publishing.'
}
$definition = [ordered]@{
    TaskName = $TaskName
    Action = $Action
    Runner = $Runner
    TimesKst = $times
    Program = $program
    Arguments = $arguments
    WorkingDirectory = $repoPath
    UserMustBeLoggedIn = $true
    StartWhenAvailable = $true
    MultipleInstances = 'IgnoreNew'
    LivePublication = $false
    SourceProbeNetwork = [bool]$SourceProbeNetwork
}
$definition | ConvertTo-Json -Depth 3
if ($Action -ne 'Install') { return }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw 'A task with this name already exists. Review and explicitly uninstall it before replacing it.'
}
if ($PSCmdlet.ShouldProcess($TaskName, 'Register private TSFM task')) {
    $scheduledAction = New-ScheduledTaskAction -Execute $program -Argument $arguments -WorkingDirectory $repoPath
    $triggers = @($times | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ })
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    $principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $scheduledAction -Trigger $triggers -Settings $settings -Principal $principal -Description $description | Out-Null
}
