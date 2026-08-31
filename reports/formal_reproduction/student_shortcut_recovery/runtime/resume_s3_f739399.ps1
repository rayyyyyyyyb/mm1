$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s3_worker_f739399.ps1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s3_a0aa4d7"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-a0aa4d7"
$A0AuditPath = "E:\OV-OrthKD-R3\student_shortcut_control\a0_f739399_results\a0_artifact_audit.json"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
$ExpectedA0Commit = "f739399463c082cd670dff56e43c710d4fa6f283"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "6c6370b9ec811ee5f760595deb1d551681061d6a9700714278fbce926ef27306"

if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) { throw "Persistent module SHA mismatch" }
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) { throw "S3 worker SHA mismatch" }
if (-not (Test-Path -LiteralPath $A0AuditPath -PathType Leaf)) { throw "S3 resume is gated on the A0 artifact audit" }
$a0 = Get-Content -LiteralPath $A0AuditPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($a0.status -ne "PASS" -or $a0.git_commit -ne $ExpectedA0Commit -or [int]$a0.task_segments -ne 10) { throw "A0 artifact audit did not satisfy the S3 gate" }
if (-not (Test-Path -LiteralPath $ControlDir -PathType Container)) { throw "Resume requires an existing S3 control directory" }
$statePath = Join-Path $ControlDir "worker_state.json"
$stateBefore = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($stateBefore.status -eq "completed") { throw "S3 is already completed" }
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "Resume requires exact clean S3 commit" }
$matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*audit_pretrained_backbones.py*" -or
    $_.CommandLine -like "*run_s3_worker_f739399.ps1*"
})
if ($matching.Count -ne 0) { throw "A conflicting training or S3 process is already running" }

Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath -ArgumentList @("-Resume")
$workerProcessId = [int]$created.ProcessId
Start-Sleep -Seconds 10
$process = Get-Process -Id $workerProcessId -ErrorAction SilentlyContinue
$stateAfter = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($null -eq $process) { throw "Persistent S3 resume worker exited during launch: $($stateAfter.message)" }
if ($stateAfter.status -ne "running") { throw "Persistent S3 resume worker did not report running" }

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
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
[ordered]@{
    receipt_path = $receiptPath
    receipt = $receipt
    process = @(Get-CimInstance Win32_Process -Filter "ProcessId=$workerProcessId" | Select-Object ProcessId, ParentProcessId, Name, CommandLine)
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 10
