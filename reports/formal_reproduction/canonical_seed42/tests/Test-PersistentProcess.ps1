$ErrorActionPreference = "Stop"
$modulePath = Join-Path (Split-Path -Parent $PSScriptRoot) "PersistentProcess.psm1"
Import-Module $modulePath -Force

$testRoot = Join-Path $env:TEMP ("ov-orthkd-persistent-process-" + [Guid]::NewGuid().ToString("N"))
$workerPath = Join-Path $testRoot "worker.ps1"
$markerPath = Join-Path $testRoot "marker.txt"
$launchedProcessId = $null

try {
    New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
    @'
param([string]$MarkerPath)
Start-Sleep -Seconds 2
Set-Content -LiteralPath $MarkerPath -Value "completed" -Encoding ASCII
Start-Sleep -Seconds 30
'@ | Set-Content -LiteralPath $workerPath -Encoding UTF8

    $launched = Start-PersistentPowerShellScript `
        -ScriptPath $workerPath `
        -ArgumentList @("-MarkerPath", $markerPath)
    $launchedProcessId = [int]$launched.ProcessId

    if ($launched.ReturnValue -ne 0) {
        throw "Expected Win32_Process.Create ReturnValue 0, got $($launched.ReturnValue)"
    }
    if ($launchedProcessId -le 0) {
        throw "Expected a positive persistent process ID"
    }
    Start-Sleep -Seconds 4
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        throw "Persistent worker did not write its marker"
    }
    if (-not (Get-Process -Id $launchedProcessId -ErrorAction SilentlyContinue)) {
        throw "Persistent worker exited before the behavior check"
    }
    Write-Output "PERSISTENT_PROCESS_TEST=PASS"
    Write-Output "PERSISTENT_PROCESS_PID=$launchedProcessId"
} finally {
    if ($null -ne $launchedProcessId) {
        Stop-Process -Id $launchedProcessId -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
