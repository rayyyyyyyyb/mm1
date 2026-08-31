$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s4_posthoc_worker_74d211d.ps1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s4_posthoc_74d211d"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s4-74d211d"
$TrainingAuditPath = "E:\OV-OrthKD-R3\student_shortcut_control\s4_74d211d\s4_training_artifact_audit.json"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "74d211d34ace74ce3b74ea082a7dfd0379b251fb"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "359af5713509e818c0908200ad894cf33014b23572743564ddaf61efce46c748"

if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) {
    throw "Persistent module SHA256 mismatch"
}
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) {
    throw "S4 posthoc worker SHA256 mismatch"
}
$audit = Get-Content -LiteralPath $TrainingAuditPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($audit.status -ne "PASS" -or $audit.git_commit -ne $ExpectedCommit -or
    [int]$audit.task_segments -ne 10) { throw "S4 training artifact audit gate failed" }
if (-not (Test-Path -LiteralPath $ControlDir -PathType Container)) {
    throw "Resume requires an existing S4 posthoc control directory"
}
$statePath = Join-Path $ControlDir "worker_state.json"
$stateBefore = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($stateBefore.status -eq "completed") { throw "S4 posthoc is already completed" }
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "S4 posthoc resume requires exact clean commit" }
$matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*diagnose_student_shortcuts.py*" -or
    $_.CommandLine -like "*diagnose_checkpoint_modalities.py*" -or
    $_.CommandLine -like "*run_s4_posthoc_worker_74d211d.ps1*"
})
if ($matching.Count -ne 0) { throw "A conflicting training or diagnostic process is running" }

Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath -ArgumentList @("-Resume")
$workerProcessId = [int]$created.ProcessId
Start-Sleep -Seconds 10
$process = Get-Process -Id $workerProcessId -ErrorAction SilentlyContinue
$stateAfter = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($null -eq $process) { throw "Persistent S4 posthoc resume worker exited during launch: $($stateAfter.message)" }
if ($stateAfter.status -ne "running") { throw "Persistent S4 posthoc resume worker did not report running" }

$receipt = [ordered]@{
    schema_version = 1
    status = "running"
    resume = $true
    utc = [DateTime]::UtcNow.ToString("o")
    worker_process_id = $workerProcessId
    return_value = [int]$created.ReturnValue
    module_sha256 = $ExpectedModuleSha
    worker_sha256 = $ExpectedWorkerSha
    git_head = $ExpectedCommit
    state_before = $stateBefore
    state_after = $stateAfter
}
$receiptPath = Join-Path $ControlDir ("resume_launch_" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ") + ".json")
$receipt | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
[ordered]@{
    receipt_path = $receiptPath
    receipt = $receipt
    process = @(Get-CimInstance Win32_Process -Filter "ProcessId=$workerProcessId" | Select-Object ProcessId, ParentProcessId, Name, CommandLine)
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 9
