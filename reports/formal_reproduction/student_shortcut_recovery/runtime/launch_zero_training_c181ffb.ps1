$ErrorActionPreference = "Stop"

$ExpectedCommit = "c181ffb3297ff480a0d01186c626acce7c66afff"
$RepoRoot = "E:\OV-OrthKD-R3\zero-training-c181ffb"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\zero_training_control\run_zero_training_worker_c181ffb.ps1"
$ControlRoot = "E:\OV-OrthKD-R3\zero_training_control\c181ffb"
$WorkerControl = Join-Path $ControlRoot "worker"
$Results = Join-Path $ControlRoot "results"
$StatePath = Join-Path $WorkerControl "worker_state.json"
$PreflightPath = Join-Path $ControlRoot "preflight_receipt.json"
$LaunchPath = Join-Path $ControlRoot "launch.json"
$ExpectedModuleSha256 = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha256 = "e572bd314a1188b0a9f5eb9a7511d2cfdd4b10565fe4b586aac090b2b49a5a18"
$ExpectedPreflightSha256 = "3c7a1dca9a969587d077e2580437ffed3297e2966a0cc0301efb32889fd06692"

foreach ($locked in ([ordered]@{
    $ModulePath = $ExpectedModuleSha256
    $WorkerPath = $ExpectedWorkerSha256
    $PreflightPath = $ExpectedPreflightSha256
}).GetEnumerator()) {
    if (-not (Test-Path -LiteralPath $locked.Key -PathType Leaf)) { throw "Launch lock is missing: $($locked.Key)" }
    $actual = (Get-FileHash -LiteralPath $locked.Key -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $locked.Value) { throw "Launch lock SHA256 mismatch: $($locked.Key)" }
}
$preflight = Get-Content -LiteralPath $PreflightPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    $preflight.status -ne "READY" -or
    $preflight.git_commit -ne $ExpectedCommit -or
    [int]$preflight.git_dirty_count -ne 0 -or
    $preflight.outputs_absent -ne $true -or
    [int]$preflight.active_conflict_count -ne 0
) { throw "Preflight receipt did not satisfy the launch gate" }
if (
    (Test-Path -LiteralPath $WorkerControl) -or
    (Test-Path -LiteralPath $Results) -or
    (Test-Path -LiteralPath $LaunchPath)
) { throw "Fresh launch refuses existing worker/results/launch state" }
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "Launch candidate is not exact and clean" }
$conflicts = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*diagnose_s7_zero_training.py*" -or
    $_.CommandLine -like "*diagnose_full_projector_probe.py*" -or
    $_.CommandLine -like "*audit_zero_training_evidence.py*" -or
    $_.CommandLine -like "*run_zero_training_worker_c181ffb.ps1*"
})
if ($conflicts.Count -ne 0) { throw "A conflicting zero-training process is already running" }

Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath
$workerProcessId = [int]$created.ProcessId
Start-Sleep -Seconds 10
$process = Get-Process -Id $workerProcessId -ErrorAction SilentlyContinue
$state = if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
    Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
}
else { $null }
if ($null -eq $process) { throw "Persistent zero-training worker exited during launch: $($state.message)" }
if ($null -eq $state -or $state.status -ne "running" -or $state.current_phase -ne "ae") {
    throw "Persistent worker did not report running A-E state"
}
$receipt = [ordered]@{
    schema_version = 1
    status = "running"
    launch_method = "Win32_Process.Create_via_verified_PersistentProcess_module"
    utc = [DateTime]::UtcNow.ToString("o")
    worker_process_id = $workerProcessId
    return_value = [int]$created.ReturnValue
    module_sha256 = $ExpectedModuleSha256
    worker_sha256 = $ExpectedWorkerSha256
    preflight_sha256 = $ExpectedPreflightSha256
    git_head = $ExpectedCommit
    sequence = @("ae", "f", "audit")
    starts_training = $false
    starts_s8 = $false
    worker_state = $StatePath
}
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $LaunchPath -Encoding UTF8
[ordered]@{
    receipt = $receipt
    state = $state
    process = @(Get-CimInstance Win32_Process -Filter "ProcessId=$workerProcessId" | Select-Object ProcessId, ParentProcessId, Name, CommandLine)
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 8
