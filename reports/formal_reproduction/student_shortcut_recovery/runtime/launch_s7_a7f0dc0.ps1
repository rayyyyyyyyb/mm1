$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s7_worker_a7f0dc0.ps1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0"
$OutputDir = Join-Path $RepoRoot "outputs\diagnostic\recovery_s7_temporal_identity_seed42"
$VerificationPath = "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0_verification\verification_receipt.json"
$S4TrainingAuditPath = "E:\OV-OrthKD-R3\student_shortcut_control\s4_74d211d\s4_training_artifact_audit.json"
$S4PosthocAuditPath = "E:\OV-OrthKD-R3\student_shortcut_control\s4_posthoc_74d211d_results\s4_posthoc_artifact_audit.json"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"
$ExpectedS4Commit = "74d211d34ace74ce3b74ea082a7dfd0379b251fb"
$ExpectedConfigSha = "26e3f21504d7ce3f9a5498b8c89073fc910db80cbdf058c4b6a397b8735518b6"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "1ef0988ca6ec8e8d20464fa3dc44671b00499111fdb2cce077efbcad87bac99b"
$ExpectedVerificationSha = "ce10e08506e7382bedfc16442c4d46f30834b2f20b0b90d54148100193ae7cf9"
$ExpectedS4TrainingAuditSha = "6f28df765bd436cf38db8fe0a38a239ce3d967518a934d214ebeee5416faa962"
$ExpectedS4PosthocAuditSha = "1a9751cbafe3f8504105063150f33cc09214abafb7768e88a1ba4f5c765dfe80"

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

function Read-LockedReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing $Name receipt" }
    $actualSha = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha -ne $ExpectedSha) { throw "$Name receipt SHA256 mismatch: $actualSha" }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) {
    throw "Persistent module SHA256 mismatch"
}
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) {
    throw "S7 worker SHA256 mismatch"
}

$verification = Read-LockedReceipt -Path $VerificationPath -ExpectedSha $ExpectedVerificationSha -Name "S7 candidate verification"
if (
    $verification.status -ne "PASS" -or
    $verification.commit_before -ne $ExpectedCommit -or
    $verification.commit_after -ne $ExpectedCommit -or
    [int]$verification.dirty_before -ne 0 -or
    [int]$verification.dirty_after -ne 0 -or
    [int]$verification.compileall_exit -ne 0 -or
    [int]$verification.pytest_exit -ne 0
) {
    throw "S7 candidate verification receipt did not satisfy the launch gate"
}
$s4Training = Read-LockedReceipt -Path $S4TrainingAuditPath -ExpectedSha $ExpectedS4TrainingAuditSha -Name "S4 training audit"
if (
    $s4Training.status -ne "PASS" -or
    $s4Training.git_commit -ne $ExpectedS4Commit -or
    [int]$s4Training.task_segments -ne 10 -or
    $s4Training.sole_scientific_change_from_s0 -ne "data.train_augment_true_to_false"
) {
    throw "S4 training audit did not satisfy the launch gate"
}
$s4Posthoc = Read-LockedReceipt -Path $S4PosthocAuditPath -ExpectedSha $ExpectedS4PosthocAuditSha -Name "S4 posthoc audit"
if ($s4Posthoc.status -ne "PASS" -or $s4Posthoc.git_commit -ne $ExpectedS4Commit -or [int]$s4Posthoc.task_segments -ne 10) {
    throw "S4 posthoc audit did not satisfy the launch gate"
}

if (Test-Path -LiteralPath $ControlDir) { throw "Fresh launch refuses an existing S7 control directory" }
if (Test-Path -LiteralPath $OutputDir) {
    if (@(Get-ChildItem -LiteralPath $OutputDir -Force).Count -ne 0) {
        throw "Fresh launch refuses a nonempty S7 output directory"
    }
}
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
$configPath = Join-Path $RepoRoot "configs\diagnostics\recovery\ov_orthkd_s7_temporal_identity_seed42.yaml"
$configSha = Get-NormalizedTextSha256 -Path $configPath
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0 -or $configSha -ne $ExpectedConfigSha) {
    throw "Launch requires the exact clean S7 commit and config"
}
$matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*run_s7_worker_a7f0dc0.ps1*"
})
if ($matching.Count -ne 0) { throw "A conflicting training or S7 process is already running" }

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
if ($null -eq $process) { throw "Persistent S7 worker exited during launch: $($state.message)" }
if ($null -eq $state -or $state.status -ne "running" -or $state.current_phase -ne "s7_training") {
    throw "Persistent S7 worker did not report the expected running state"
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
    candidate_verification_sha256 = $ExpectedVerificationSha
    s4_training_audit_sha256 = $ExpectedS4TrainingAuditSha
    s4_posthoc_audit_sha256 = $ExpectedS4PosthocAuditSha
    sole_scientific_change_from_s0 = "student.temporal_path_mode_transformer_to_identity_passthrough"
    sequence = @("s7_training")
    worker_state = $statePath
}
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $ControlDir "launch.json") -Encoding UTF8
[ordered]@{
    receipt = $receipt
    state = $state
    process = @(Get-CimInstance Win32_Process -Filter "ProcessId=$workerProcessId" | Select-Object ProcessId, ParentProcessId, Name, CommandLine)
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 8
