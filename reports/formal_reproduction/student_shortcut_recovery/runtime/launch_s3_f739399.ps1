$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s3_worker_f739399.ps1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s3_a0aa4d7"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-a0aa4d7"
$OutputDir = Join-Path $RepoRoot "outputs\diagnostic\recovery_s3_pretrained_seed42"
$A0AuditPath = "E:\OV-OrthKD-R3\student_shortcut_control\a0_f739399_results\a0_artifact_audit.json"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
$ExpectedA0Commit = "f739399463c082cd670dff56e43c710d4fa6f283"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "6c6370b9ec811ee5f760595deb1d551681061d6a9700714278fbce926ef27306"

if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) { throw "Persistent module SHA mismatch" }
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) { throw "S3 worker SHA mismatch" }
if (-not (Test-Path -LiteralPath $A0AuditPath -PathType Leaf)) { throw "S3 is gated on the completed A0 artifact audit" }
$a0 = Get-Content -LiteralPath $A0AuditPath -Raw -Encoding UTF8 | ConvertFrom-Json
$a0Runs = @($a0.runs.psobject.Properties.Name | Sort-Object)
if ($a0.status -ne "PASS" -or $a0.git_commit -ne $ExpectedA0Commit -or [int]$a0.task_segments -ne 10 -or
    @(Compare-Object -ReferenceObject @("full", "s0", "student", "visual") -DifferenceObject $a0Runs).Count -ne 0) {
    throw "A0 artifact audit did not satisfy the S3 gate"
}
if (Test-Path -LiteralPath $ControlDir) { throw "Fresh launch refuses an existing S3 control directory" }
if (Test-Path -LiteralPath $OutputDir) {
    if (@(Get-ChildItem -LiteralPath $OutputDir -Force).Count -ne 0) { throw "Fresh launch refuses nonempty S3 output" }
}
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "Launch requires exact clean S3 commit" }
$matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*audit_pretrained_backbones.py*" -or
    $_.CommandLine -like "*run_s3_worker_f739399.ps1*"
})
if ($matching.Count -ne 0) { throw "A conflicting training or S3 process is already running" }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ControlDir) | Out-Null
New-Item -ItemType Directory -Path $ControlDir | Out-Null
Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath
$workerProcessId = [int]$created.ProcessId
Start-Sleep -Seconds 10
$process = Get-Process -Id $workerProcessId -ErrorAction SilentlyContinue
$statePath = Join-Path $ControlDir "worker_state.json"
$state = if (Test-Path -LiteralPath $statePath) { Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
if ($null -eq $process) { throw "Persistent S3 worker exited during launch: $($state.message)" }
if ($null -eq $state -or $state.status -ne "running") { throw "Persistent S3 worker did not report running" }

$receipt = [ordered]@{
    schema_version = 1
    status = "running"
    launch_method = "Win32_Process.Create_via_verified_PersistentProcess_module"
    utc = [DateTime]::UtcNow.ToString("o")
    worker_process_id = $workerProcessId
    return_value = [int]$created.ReturnValue
    module_sha256 = $ExpectedModuleSha
    worker_sha256 = $ExpectedWorkerSha
    git_head = $ExpectedCommit
    a0_audit_sha256 = (Get-FileHash -LiteralPath $A0AuditPath -Algorithm SHA256).Hash.ToLowerInvariant()
    sequence = @("pretrained_receipt", "s3_training")
    worker_state = $statePath
}
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $ControlDir "launch.json") -Encoding UTF8
[ordered]@{
    receipt = $receipt
    state = $state
    process = @(Get-CimInstance Win32_Process -Filter "ProcessId=$workerProcessId" | Select-Object ProcessId, ParentProcessId, Name, CommandLine)
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 8
