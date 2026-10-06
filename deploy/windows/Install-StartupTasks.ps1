#Requires -Version 5.1
<#
.SYNOPSIS
  Registers Windows Scheduled Tasks to start Route Card backend + frontend at boot.

.DESCRIPTION
  Creates:
    - RouteCard-Backend   (uvicorn :8008)
    - RouteCard-Frontend  (Vite --host :5174)

  Trigger: At startup, delay 90 seconds (Postgres / network).
  Restart on failure: 3 times, 1 minute apart.

  Run once as Administrator from an elevated PowerShell:

    cd D:\PMF\route-card-app\deploy\windows
    powershell -ExecutionPolicy Bypass -File .\Install-StartupTasks.ps1
#>
[CmdletBinding()]
param(
    [int]$StartupDelaySeconds = 90
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    Write-Error "Run this script from an elevated PowerShell (Run as administrator)."
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendBat = Join-Path $ScriptDir "start-backend.bat"
$FrontendBat = Join-Path $ScriptDir "start-frontend.bat"
$LogDir = Join-Path $ScriptDir "logs"

if (-not (Test-Path $BackendBat)) { throw "Missing $BackendBat" }
if (-not (Test-Path $FrontendBat)) { throw "Missing $FrontendBat" }
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$delay = New-TimeSpan -Seconds $StartupDelaySeconds

function Register-RouteCardTask {
    param(
        [Parameter(Mandatory)][string]$TaskName,
        [Parameter(Mandatory)][string]$BatPath,
        [Parameter(Mandatory)][string]$Description
    )

    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    $action = New-ScheduledTaskAction `
        -Execute "cmd.exe" `
        -Argument "/c `"$BatPath`"" `
        -WorkingDirectory (Split-Path -Parent $BatPath)

    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = "PT{0}S" -f [int]$delay.TotalSeconds

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Days 0) `
        -MultipleInstances IgnoreNew

    # Run as the installing admin; works after reboot when that account is used / auto-logon.
    # For headless boot with no login, re-register with a dedicated service account.
    $principal = New-ScheduledTaskPrincipal `
        -UserId $env:USERNAME `
        -LogonType Interactive `
        -RunLevel Highest

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description $Description `
        -Force | Out-Null

    Write-Host "Registered task: $TaskName"
}

Register-RouteCardTask `
    -TaskName "RouteCard-Backend" `
    -BatPath $BackendBat `
    -Description "Route Card Generator API (uvicorn on 0.0.0.0:8008)"

Register-RouteCardTask `
    -TaskName "RouteCard-Frontend" `
    -BatPath $FrontendBat `
    -Description "Route Card Generator UI (Vite --host on port 5174)"

Write-Host ""
Write-Host "Done. Tasks start $StartupDelaySeconds seconds after Windows boots."
Write-Host "Logs: $LogDir"
Write-Host ""
Write-Host "Verify:"
Write-Host "  Get-ScheduledTask -TaskName 'RouteCard-*'"
Write-Host "  Start-ScheduledTask -TaskName RouteCard-Backend"
Write-Host "  Start-ScheduledTask -TaskName RouteCard-Frontend"
Write-Host "  http://localhost:8008/health"
Write-Host "  http://localhost:5174"
Write-Host ""
Write-Host "If you use local_vlm, confirm the Ollama Windows service Startup type is Automatic."
