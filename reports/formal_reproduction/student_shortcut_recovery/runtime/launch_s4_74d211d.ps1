$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s4_worker_74d211d.ps1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s4_74d211d"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s4-74d211d"
$OutputDir = Join-Path $RepoRoot "outputs\diagnostic\recovery_s4_no_augment_seed42"
$VerificationPath = "E:\OV-OrthKD-R3\student_shortcut_control\candidate_s4_74d211d\verification_receipt.json"
$S3TrainingAuditPath = "E:\OV-OrthKD-R3\student_shortcut_control\s3_a0aa4d7\s3_training_artifact_audit.json"
$S3PosthocAuditPath = "E:\OV-OrthKD-R3\student_shortcut_control\s3_posthoc_a0aa4d7_results\s3_posthoc_artifact_audit.json"
$A0AuditPath = "E:\OV-OrthKD-R3\student_shortcut_control\a0_f739399_results\a0_artifact_audit.json"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "74d211d34ace74ce3b74ea082a7dfd0379b251fb"
$ExpectedS3Commit = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
$ExpectedA0Commit = "f739399463c082cd670dff56e43c710d4fa6f283"
$ExpectedConfigSha = "5b81218b55907a5dfb0419e62eff2128f0d08ce9301c97c081237f8c8f599b33"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "757710ca129c153b02d6c30c36658f84c53990c0fe27f032303a79a7edee26dd"

function Get-NormalizedTextSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8).Replace("`r`n", "`n")
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text)))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Read-PassReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing $Name receipt: $Path" }
    $receipt = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($receipt.status -ne "PASS") { throw "$Name receipt is not PASS" }
    return $receipt
}

if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) {
    throw "Persistent module SHA256 mismatch"
}
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) {
    throw "S4 worker SHA256 mismatch"
}

$verification = Read-PassReceipt -Path $VerificationPath -Name "S4 candidate verification"
if ($verification.expected_commit -ne $ExpectedCommit -or
    $verification.head_before -ne $ExpectedCommit -or
    $verification.head_after -ne $ExpectedCommit -or
    [int]$verification.dirty_before -ne 0 -or
    [int]$verification.dirty_after -ne 0 -or
    [int]$verification.focused_pytest_exit -ne 0 -or
    [int]$verification.compileall_exit -ne 0 -or
    [int]$verification.pytest_exit -ne 0) {
    throw "S4 candidate verification receipt did not satisfy the launch gate"
}

$s3Training = Read-PassReceipt -Path $S3TrainingAuditPath -Name "S3 training audit"
if ($s3Training.git_commit -ne $ExpectedS3Commit -or
    [int]$s3Training.task_segments -ne 10 -or
    $s3Training.sole_scientific_change_from_s0 -ne "student.pretrained_false_to_true") {
    throw "S3 training audit did not satisfy the launch gate"
}
$s3Posthoc = Read-PassReceipt -Path $S3PosthocAuditPath -Name "S3 posthoc audit"
if ($s3Posthoc.git_commit -ne $ExpectedS3Commit -or
    [int]$s3Posthoc.task_segments -ne 10 -or
    $s3Posthoc.training_audit.sha256 -ne (Get-FileHash -LiteralPath $S3TrainingAuditPath -Algorithm SHA256).Hash.ToLowerInvariant()) {
    throw "S3 posthoc audit did not satisfy the launch gate"
}
$a0 = Read-PassReceipt -Path $A0AuditPath -Name "A0 audit"
$a0Runs = @($a0.runs.psobject.Properties.Name | Sort-Object)
if ($a0.git_commit -ne $ExpectedA0Commit -or [int]$a0.task_segments -ne 10 -or
    @(Compare-Object -ReferenceObject @("full", "s0", "student", "visual") -DifferenceObject $a0Runs).Count -ne 0) {
    throw "A0 audit did not satisfy the launch gate"
}

if (Test-Path -LiteralPath $ControlDir) { throw "Fresh launch refuses an existing S4 control directory" }
if (Test-Path -LiteralPath $OutputDir) {
    if (@(Get-ChildItem -LiteralPath $OutputDir -Force).Count -ne 0) {
        throw "Fresh launch refuses a nonempty S4 output directory"
    }
}
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
$configPath = Join-Path $RepoRoot "configs\diagnostics\recovery\ov_orthkd_s4_no_augment_seed42.yaml"
$configSha = Get-NormalizedTextSha256 -Path $configPath
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0 -or $configSha -ne $ExpectedConfigSha) {
    throw "Launch requires the exact clean S4 commit and config"
}
$matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*run_s4_worker_74d211d.ps1*"
})
if ($matching.Count -ne 0) { throw "A conflicting training or S4 process is already running" }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ControlDir) | Out-Null
New-Item -ItemType Directory -Path $ControlDir | Out-Null
Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath
$workerProcessId = [int]$created.ProcessId
Start-Sleep -Seconds 10
$process = Get-Process -Id $workerProcessId -ErrorAction SilentlyContinue
$statePath = Join-Path $ControlDir "worker_state.json"
$state = if (Test-Path -LiteralPath $statePath) {
    Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
} else { $null }
if ($null -eq $process) { throw "Persistent S4 worker exited during launch: $($state.message)" }
if ($null -eq $state -or $state.status -ne "running" -or $state.current_phase -ne "s4_training") {
    throw "Persistent S4 worker did not report the expected running state"
}

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
    config_sha256 = $ExpectedConfigSha
    candidate_verification_sha256 = (Get-FileHash -LiteralPath $VerificationPath -Algorithm SHA256).Hash.ToLowerInvariant()
    s3_training_audit_sha256 = (Get-FileHash -LiteralPath $S3TrainingAuditPath -Algorithm SHA256).Hash.ToLowerInvariant()
    s3_posthoc_audit_sha256 = (Get-FileHash -LiteralPath $S3PosthocAuditPath -Algorithm SHA256).Hash.ToLowerInvariant()
    a0_audit_sha256 = (Get-FileHash -LiteralPath $A0AuditPath -Algorithm SHA256).Hash.ToLowerInvariant()
    sole_scientific_change_from_s0 = "data.train_augment_true_to_false"
    sequence = @("s4_training")
    worker_state = $statePath
}
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $ControlDir "launch.json") -Encoding UTF8
[ordered]@{
    receipt = $receipt
    state = $state
    process = @(Get-CimInstance Win32_Process -Filter "ProcessId=$workerProcessId" | Select-Object ProcessId, ParentProcessId, Name, CommandLine)
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 8
