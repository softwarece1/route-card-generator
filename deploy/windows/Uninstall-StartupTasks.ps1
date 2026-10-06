#Requires -Version 5.1
<#
.SYNOPSIS
  Removes Route Card auto-start Scheduled Tasks.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\Uninstall-StartupTasks.ps1
#>
[CmdletBinding()]
param()

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

$names = @("RouteCard-Backend", "RouteCard-Frontend")
foreach ($name in $names) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($task) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "Removed task: $name"
    }
    else {
        Write-Host "Task not found (skipped): $name"
    }
}

Write-Host "Done. Apps still running can be stopped with stop-apps.bat"
