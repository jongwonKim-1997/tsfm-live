<#
.SYNOPSIS
Preview, explicitly install, or uninstall the user's local TSFM daily task.
.DESCRIPTION
Default Preview changes nothing. Installation is opt-in with -Action Install.
Requires the Windows time zone Korea Standard Time and an interactive user login.
Runs at 06:10 (collect/evaluate) and 08:10 (collect/forecast/evaluate), local KST.
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
$runner = Join-Path $PSScriptRoot 'run-daily.ps1'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $runner + '" -RuntimeEnvFile "' + $resolvedEnv + '"'
if ($StateDir) {
    $resolvedState = [System.IO.Path]::GetFullPath($StateDir)
    $arguments += ' -StateDir "' + $resolvedState + '"'
}
$description = 'Private TSFM diagnostic loop. 06:10 KST evaluates prior outcomes; 08:10 KST also admits new on-time forecasts. No public publishing.'
$definition = [ordered]@{
    TaskName = $TaskName
    Action = $Action
    TimesKst = @('06:10', '08:10')
    Program = 'powershell.exe'
    Arguments = $arguments
    WorkingDirectory = $repoPath
    UserMustBeLoggedIn = $true
    StartWhenAvailable = $true
    MultipleInstances = 'IgnoreNew'
    LivePublication = $false
}
$definition | ConvertTo-Json -Depth 3
if ($Action -ne 'Install') { return }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw 'A task with this name already exists. Review and explicitly uninstall it before replacing it.'
}
if ($PSCmdlet.ShouldProcess($TaskName, 'Register twice-daily private TSFM task')) {
    $scheduledAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $repoPath
    $triggers = @(New-ScheduledTaskTrigger -Daily -At '06:10'; New-ScheduledTaskTrigger -Daily -At '08:10')
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    $principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $scheduledAction -Trigger $triggers -Settings $settings -Principal $principal -Description $description | Out-Null
}
