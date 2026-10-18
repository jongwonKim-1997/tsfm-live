<# Replace only the action of the existing hourly task after a verified publication.
Preview is the default. Back up XML before Apply; preserve triggers and principal. #>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('Preview', 'Apply')][string]$Action = 'Preview',
    [Parameter(Mandatory = $true)][string]$RuntimeEnvFile,
    [Parameter(Mandatory = $true)][string]$PublishEnvFile,
    [string]$TaskName = 'TSFM-Local-Dashboard'
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$workspace = Split-Path -Parent (Split-Path -Parent $repo)
function Resolve-PrivateFile([string]$Value) {
    $resolved = (Resolve-Path -LiteralPath $Value).ProviderPath
    if ($resolved.StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Runtime files must be outside the repository.'
    }
    $cursor = $resolved
    while ($cursor) {
        if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Runtime files must not use links or junctions.'
        }
        $cursor = Split-Path -Parent $cursor
    }
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf) -or $resolved.Contains('"')) {
        throw 'Invalid runtime file.'
    }
    return $resolved
}
$runtime = Resolve-PrivateFile $RuntimeEnvFile
$publish = Resolve-PrivateFile $PublishEnvFile
$task = Get-ScheduledTask -TaskName $TaskName -TaskPath '\'
$program = Join-Path $repo 'pipeline\.venv\Scripts\pythonw.exe'
$script = Join-Path $PSScriptRoot 'public_daily.py'
if (@($task.Actions).Count -ne 1 -or $task.Actions[0].Execute -ine $program -or
    @($task.Triggers).Count -ne 24) {
    throw 'Expected this repository''s existing hourly pythonw task; nothing changed.'
}
$arguments = '-X utf8 "' + $script + '" --runtime-env-file "' + $runtime + '" --publish-env-file "' + $publish + '" --no-site'
[ordered]@{ Mode=$Action; Task=$TaskName; Program=$program; Arguments=$arguments;
    Preserved=@('Triggers','Principal','Settings','Description'); DailyInference='08:10 KST or next run';
    ActualRefresh='Existing hourly schedule' } | ConvertTo-Json -Depth 3
if ($Action -ne 'Apply') { return }
$receiptPath = Join-Path $workspace 'work\tsfm-daily-public\latest-run.json'
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
if ($receipt.status -ne 'ok' -or -not $receipt.published -or -not $receipt.publication.readback_verified) {
    throw 'A successful GPU run and matching public readback are required before scheduling.'
}
if ($PSCmdlet.ShouldProcess($TaskName, 'Back up XML and replace the action with the daily GPU publisher')) {
    $xml = Export-ScheduledTask -TaskName $TaskName -TaskPath '\'
    $backupDir = Join-Path $workspace 'work\scheduled-task-backups'
    [void][IO.Directory]::CreateDirectory($backupDir)
    $backup = Join-Path $backupDir ($TaskName + '-daily-' + [Guid]::NewGuid().ToString('N') + '.xml')
    [IO.File]::WriteAllText($backup, $xml, (New-Object Text.UTF8Encoding($false)))
    $replacement = New-ScheduledTaskAction -Execute $program -Argument $arguments -WorkingDirectory $repo
    Set-ScheduledTask -TaskName $TaskName -TaskPath '\' -Action $replacement | Out-Null
    $after = [xml](Export-ScheduledTask -TaskName $TaskName -TaskPath '\')
    $before = [xml]$xml
    foreach ($name in @('Triggers','Principals','Settings','RegistrationInfo')) {
        if ($before.Task.$name.OuterXml -cne $after.Task.$name.OuterXml) {
            throw ('Task metadata changed unexpectedly. Restore from: ' + $backup)
        }
    }
    [ordered]@{ Updated=$true; Backup=$backup; NextRun=(Get-ScheduledTaskInfo -TaskName $TaskName).NextRunTime } | ConvertTo-Json
}
