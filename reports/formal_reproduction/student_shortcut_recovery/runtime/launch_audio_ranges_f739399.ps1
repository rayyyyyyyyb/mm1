$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_audio_ranges_f739399.ps1"
$Control = "E:\OV-OrthKD-R3\student_shortcut_control\audio_ranges_f739399"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "03c723fd4f634a549e67d8d7d3f3cf3e626318f89346fdf79a7680913c091153"
if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) { throw "Persistent module SHA mismatch" }
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) { throw "Range-download worker SHA mismatch" }
if (Test-Path -LiteralPath $Control) { throw "Fresh range-download launch refuses existing control directory" }
Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath
$workerProcessId = [int]$created.ProcessId
Start-Sleep -Seconds 3
$statePath = Join-Path $Control "worker_state.json"
$state = if (Test-Path -LiteralPath $statePath) { Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
if ($null -eq $state -or $state.status -ne "running") { throw "Range-download worker did not report running" }
[ordered]@{
    schema_version = 1
    status = "running"
    utc = [DateTime]::UtcNow.ToString("o")
    worker_process_id = $workerProcessId
    return_value = [int]$created.ReturnValue
    module_sha256 = $ExpectedModuleSha
    worker_sha256 = $ExpectedWorkerSha
    state = $state
} | ConvertTo-Json -Depth 10
