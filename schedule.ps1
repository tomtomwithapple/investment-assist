# The two investment-assist jobs via Windows Task Scheduler: the Windows counterpart of the
# launchd jobs (launchd/install.sh, macOS only). Safe to re-run: re-installing replaces the tasks.
#
#   powershell -ExecutionPolicy Bypass -File schedule.ps1 [install|uninstall|status|run] [options]
#
# Keep this file ASCII-only: Windows PowerShell 5.1 reads BOM-less scripts as ANSI.
param(
    [Parameter(Position = 0)] [string] $Command = 'install',
    [string] $Uv,
    [switch] $Regime,
    [switch] $DryRun,
    [switch] $Help,
    [Parameter(ValueFromRemainingArguments = $true)] [string[]] $Rest
)
$ErrorActionPreference = 'Stop'

$LogDir = Join-Path $env:LOCALAPPDATA 'investment-assist\logs'
$Root = $PSScriptRoot
# name -> assist command, trigger, log file. launchd starts both at 07:00 and job.sh's lockf runs
# them one after the other; Task Scheduler has no lock across tasks, so the daily check starts at
# 07:05 and on Mondays compares with the regime the weekly run has just journalled.
$Jobs = [ordered]@{
    'investment-assist-weekly' = @{ Cli = 'run'; Days = 'Monday'; At = '07:00'; Log = 'weekly.log' }
    'investment-assist-regime' = @{ Cli = 'regime --check'; Days = $null; At = '07:05'; Log = 'regime.log' }
}

function Show-Usage {
    @"
Usage: powershell -ExecutionPolicy Bypass -File schedule.ps1 [install|uninstall|status|run] [options]

  install     (default) register (or replace) investment-assist-weekly and investment-assist-regime
  uninstall   remove both tasks
  status      show each task's state, last run, last result and next run
  run         start investment-assist-weekly now (-Regime: investment-assist-regime)

Options (install):
  -Uv path     uv.exe to use (default: uv on PATH, resolved when installing)
  -DryRun      print the tasks it would register; registers nothing, writes nothing
  -Help        show this help

investment-assist-weekly runs ``uv run assist run`` (stances, journal, brief, Telegram summary)
on Mondays at 07:00 and investment-assist-regime runs ``uv run assist regime --check`` (Telegram
only when the regime changed) daily at 07:05, local time, in this directory (so out/, journal/
and data/ are the interactive ones) as the current user, without elevation and with no console
window. Output is appended to $LogDir\weekly.log and regime.log. They run only while you are
logged on; a missed run starts as soon as possible. Telegram needs ASSIST_TELEGRAM_TOKEN and
ASSIST_TELEGRAM_CHAT in the user environment (there is no Keychain here); without them nothing
is sent. Last result: 0 ok, 1 no stance written or a step failed (see the log).
"@
}

function Say([string] $msg) { Write-Output "==> $msg" }
function Fail([string] $msg, [int] $code = 1) {
    [Console]::Error.WriteLine("error: $msg")
    exit $code
}

if ($Help) { Show-Usage; exit 0 }
if ($Command -notin 'install', 'uninstall', 'status', 'run') {
    Fail "unknown command: $Command (install, uninstall, status, run; see -Help)" 2
}
if ($Rest) { Fail "unexpected argument(s): $($Rest -join ' ') (see -Help)" 2 }
if ($DryRun -and $Command -ne 'install') { Fail "-DryRun is for install only, not $Command" 2 }
if ($Regime -and $Command -ne 'run') { Fail "-Regime is for run only, not $Command" 2 }

switch ($Command) {
    'uninstall' {
        foreach ($name in $Jobs.Keys) {
            if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
                Unregister-ScheduledTask -TaskName $name -Confirm:$false
                Say "Removed $name"
            } else {
                Say "$name is not registered"
            }
        }
        exit 0
    }
    'status' {
        foreach ($name in $Jobs.Keys) {
            $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
            if (-not $task) { Write-Output "$name is not registered"; continue }
            $info = Get-ScheduledTaskInfo -TaskName $name
            Write-Output "${name}:"
            Write-Output "  state: $($task.State)"
            Write-Output "  last run: $($info.LastRunTime)    last result: $($info.LastTaskResult)"
            Write-Output "  next run: $($info.NextRunTime)"
            Write-Output "  action: $($task.Actions[0].Execute) $($task.Actions[0].Arguments)"
            Write-Output "  log: $(Join-Path $LogDir $Jobs[$name].Log)"
        }
        exit 0
    }
    'run' {
        $name = if ($Regime) { 'investment-assist-regime' } else { 'investment-assist-weekly' }
        if (-not (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue)) {
            Fail "$name is not registered; run schedule.ps1 install"
        }
        Start-ScheduledTask -TaskName $name
        Say "Started; follow with: Get-Content -Wait '$(Join-Path $LogDir $Jobs[$name].Log)'"
        exit 0
    }
}

if ($Uv) {
    if (-not (Test-Path -LiteralPath $Uv -PathType Leaf)) { Fail "uv not found: $Uv" }
    $UvExe = (Resolve-Path -LiteralPath $Uv).Path
} else {
    $found = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $found) { Fail 'uv not found on PATH; install it (https://docs.astral.sh/uv/) or pass -Uv' }
    $UvExe = $found.Source
}

# schedule-hidden.js runs the command with no console window and cmd.exe does the log
# redirection (Task Scheduler has none of its own); the task's last result is the command's
# exit code.
$Launcher = Join-Path $Root 'schedule-hidden.js'
if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
foreach ($name in $Jobs.Keys) {
    $job = $Jobs[$name]
    $log = Join-Path $LogDir $job.Log
    $arguments = "//E:JScript //B //Nologo `"$Launcher`" `"$log`" `"$UvExe`" run assist $($job.Cli)"
    $when = if ($job.Days) { "$($job.Days) at $($job.At)" } else { "daily at $($job.At)" }
    if ($DryRun) {
        Write-Output "task: $name"
        Write-Output "  when: $when"
        Write-Output "  workdir: $Root"
        Write-Output '  execute: wscript.exe'
        Write-Output "  arguments: $arguments"
        continue
    }
    $at = [datetime]::ParseExact($job.At, 'HH:mm', $null)
    $trigger = if ($job.Days) {
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek $job.Days -At $at
    } else {
        New-ScheduledTaskTrigger -Daily -At $at
    }
    $action = New-ScheduledTaskAction -Execute 'wscript.exe' -WorkingDirectory $Root -Argument $arguments
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
        -Settings $settings -Description "investment-assist: assist $($job.Cli) in $Root" -Force | Out-Null
    Say "Scheduled ${name}: $when local time with $UvExe"
}
if ($DryRun) { exit 0 }
Write-Output "    logs: $LogDir"
Write-Output "    status: schedule.ps1 status    run now: schedule.ps1 run [-Regime]    remove: schedule.ps1 uninstall"
