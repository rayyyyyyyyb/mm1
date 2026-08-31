$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s3_posthoc_worker_f739399.ps1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s3_posthoc_a0aa4d7"
$ResultsDir = "E:\OV-OrthKD-R3\student_shortcut_control\s3_posthoc_a0aa4d7_results"
$S3AuditPath = "E:\OV-OrthKD-R3\student_shortcut_control\s3_a0aa4d7\s3_training_artifact_audit.json"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-a0aa4d7"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "d7932dda1afea09b0f7cea62fdbde862b1851b69f45a20b649d00f884846926e"

if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) { throw "Persistent module SHA mismatch" }
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) { throw "S3 posthoc worker SHA mismatch" }
if (-not (Test-Path -LiteralPath $S3AuditPath -PathType Leaf)) { throw "S3 posthoc is gated on the training artifact audit" }
$audit = Get-Content -LiteralPath $S3AuditPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($audit.status -ne "PASS" -or $audit.git_commit -ne $ExpectedCommit -or [int]$audit.task_segments -ne 10) { throw "S3 training artifact audit gate failed" }
if (Test-Path -LiteralPath $ControlDir) { throw "Fresh posthoc launch refuses existing control directory" }
if (Test-Path -LiteralPath $ResultsDir) {
    if (@(Get-ChildItem -LiteralPath $ResultsDir -Force).Count -ne 0) { throw "Fresh posthoc launch refuses nonempty results" }
}
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "Posthoc launch requires exact clean commit" }
$matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*diagnose_student_shortcuts.py*" -or
    $_.CommandLine -like "*diagnose_checkpoint_modalities.py*" -or
    $_.CommandLine -like "*run_s3_posthoc_worker_f739399.ps1*"
})
if ($matching.Count -ne 0) { throw "A conflicting training or diagnostic process is running" }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ControlDir) | Out-Null
New-Item -ItemType Directory -Path $ControlDir | Out-Null
Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath
$workerProcessId = [int]$created.ProcessId
Start-Sleep -Seconds 10
$process = Get-Process -Id $workerProcessId -ErrorAction SilentlyContinue
$statePath = Join-Path $ControlDir "worker_state.json"
$state = if (Test-Path -LiteralPath $statePath) { Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
if ($null -eq $process) { throw "Persistent S3 posthoc worker exited during launch: $($state.message)" }
if ($null -eq $state -or $state.status -ne "running") { throw "Persistent S3 posthoc worker did not report running" }

$receipt = [ordered]@{
    schema_version = 1
    status = "running"
    utc = [DateTime]::UtcNow.ToString("o")
    worker_process_id = $workerProcessId
    return_value = [int]$created.ReturnValue
    module_sha256 = $ExpectedModuleSha
    worker_sha256 = $ExpectedWorkerSha
    git_head = $ExpectedCommit
    s3_training_audit_sha256 = (Get-FileHash -LiteralPath $S3AuditPath -Algorithm SHA256).Hash.ToLowerInvariant()
    sequence = @("prediction", "modality")
}
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $ControlDir "launch.json") -Encoding UTF8
[ordered]@{
    receipt = $receipt
    state = $state
    process = @(Get-CimInstance Win32_Process -Filter "ProcessId=$workerProcessId" | Select-Object ProcessId, ParentProcessId, Name, CommandLine)
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 8
