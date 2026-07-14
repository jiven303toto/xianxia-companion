[CmdletBinding()]
param(
    [switch]$Remove,
    [switch]$Enable,
    [switch]$Disable,
    [switch]$KeepDisabled,
    [ValidateSet(1, 2, 3, 6, 12, 24)]
    [int]$IntervalHours = 1
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$TaskName = 'ZidongXiuxian Telegram Bot Sync'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ProjectName = Split-Path -Leaf $ProjectRoot
$PythonPath = Join-Path (Split-Path -Parent $ProjectRoot) ".venvs\$ProjectName\Scripts\python.exe"
$PythonwPath = Join-Path (Split-Path -Parent $ProjectRoot) ".venvs\$ProjectName\Scripts\pythonw.exe"
$RunnerPath = Join-Path $PSScriptRoot 'run_telegram_game_bot_sync_scheduled.py'

$selectedModes = @($Remove.IsPresent, $Enable.IsPresent, $Disable.IsPresent) | Where-Object { $_ }
if ($selectedModes.Count -gt 1) {
    throw 'Remove, Enable and Disable cannot be used together.'
}
if ($Remove) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -ne $task) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Removed scheduled task: $TaskName"
    } else {
        Write-Output "Scheduled task does not exist: $TaskName"
    }
    exit 0
}

if ($Disable) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        throw "Scheduled task does not exist: $TaskName"
    }
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
    Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
    exit 0
}

if ($Enable) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -ne $task -and -not $PSBoundParameters.ContainsKey('IntervalHours')) {
        $existingInterval = [string](@($task.Triggers)[0].Repetition.Interval)
        if ($existingInterval -match '^PT(\d+)H$') {
            $IntervalHours = [int]$Matches[1]
        }
    }
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python executable not found: $PythonPath"
}
if (-not (Test-Path -LiteralPath $PythonwPath)) {
    throw "Python windowless executable not found: $PythonwPath"
}
if (-not (Test-Path -LiteralPath $RunnerPath)) {
    throw "Scheduled runner not found: $RunnerPath"
}

$serverNow = Get-Date
$startAt = $serverNow.AddHours($IntervalHours)
$action = New-ScheduledTaskAction `
    -Execute $PythonwPath `
    -Argument "`"$RunnerPath`"" `
    -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At $startAt `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -Hidden
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Scans 5000 Telegram group messages every $IntervalHours hour(s) and synchronizes newly observed cultivation Bot IDs." `
    -Force | Out-Null

if ($KeepDisabled) {
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
}

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object NextRunTime, LastRunTime, LastTaskResult
