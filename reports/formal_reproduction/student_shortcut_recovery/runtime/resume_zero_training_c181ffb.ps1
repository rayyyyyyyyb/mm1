$ErrorActionPreference = "Stop"

$ExpectedCommit = "c181ffb3297ff480a0d01186c626acce7c66afff"
$RepoRoot = "E:\OV-OrthKD-R3\zero-training-c181ffb"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\zero_training_control\run_zero_training_worker_c181ffb.ps1"
$ControlRoot = "E:\OV-OrthKD-R3\zero_training_control\c181ffb"
$WorkerControl = Join-Path $ControlRoot "worker"
$StatePath = Join-Path $WorkerControl "worker_state.json"
$PreflightPath = Join-Path $ControlRoot "preflight_receipt.json"
$ExpectedModuleSha256 = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha256 = "e572bd314a1188b0a9f5eb9a7511d2cfdd4b10565fe4b586aac090b2b49a5a18"
$ExpectedPreflightSha256 = "3c7a1dca9a969587d077e2580437ffed3297e2966a0cc0301efb32889fd06692"

foreach ($locked in ([ordered]@{
    $ModulePath = $ExpectedModuleSha256
    $WorkerPath = $ExpectedWorkerSha256
    $PreflightPath = $ExpectedPreflightSha256
}).GetEnumerator()) {
    if (-not (Test-Path -LiteralPath $locked.Key -PathType Leaf)) { throw "Resume lock is missing: $($locked.Key)" }
    $actual = (Get-FileHash -LiteralPath $locked.Key -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $locked.Value) { throw "Resume lock SHA256 mismatch: $($locked.Key)" }
}
$preflight = Get-Content -LiteralPath $PreflightPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($preflight.status -ne "READY" -or $preflight.git_commit -ne $ExpectedCommit) {
    throw "Preflight receipt did not satisfy the resume gate"
}
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) { throw "Resume requires worker_state.json" }
$stateBefore = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($stateBefore.status -eq "completed") { throw "Zero-training worker is already completed" }
$existing = @(Get-CimInstance Win32_Process -Filter "ProcessId=$($stateBefore.worker_process_id)")
if ($existing.Count -ne 0) { throw "Recorded zero-training worker is still running" }
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "Resume candidate is not exact and clean" }
$conflicts = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*diagnose_s7_zero_training.py*" -or
    $_.CommandLine -like "*diagnose_full_projector_probe.py*" -or
    $_.CommandLine -like "*audit_zero_training_evidence.py*" -or
    $_.CommandLine -like "*run_zero_training_worker_c181ffb.ps1*"
})
if ($conflicts.Count -ne 0) { throw "A conflicting zero-training process is already running" }

Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath -ArgumentList @("-Resume")
$workerProcessId = [int]$created.ProcessId
Start-Sleep -Seconds 10
$process = Get-Process -Id $workerProcessId -ErrorAction SilentlyContinue
$stateAfter = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($null -eq $process) { throw "Persistent resume worker exited during launch: $($stateAfter.message)" }
if ($stateAfter.status -ne "running") { throw "Resume worker did not report running state" }
$receipt = [ordered]@{
    schema_version = 1
    status = "running"
    resume = $true
    utc = [DateTime]::UtcNow.ToString("o")
    worker_process_id = $workerProcessId
    return_value = [int]$created.ReturnValue
    module_sha256 = $ExpectedModuleSha256
    worker_sha256 = $ExpectedWorkerSha256
    preflight_sha256 = $ExpectedPreflightSha256
    git_head = $ExpectedCommit
    state_before = $stateBefore
    state_after = $stateAfter
}
$receiptPath = Join-Path $WorkerControl ("resume_launch_" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ") + ".json")
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
[ordered]@{
    receipt_path = $receiptPath
    receipt = $receipt
    process = @(Get-CimInstance Win32_Process -Filter "ProcessId=$workerProcessId" | Select-Object ProcessId, ParentProcessId, Name, CommandLine)
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 10
