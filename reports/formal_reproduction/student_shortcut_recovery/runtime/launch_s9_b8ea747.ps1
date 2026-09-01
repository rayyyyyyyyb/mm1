param([switch]$PreflightOnly)

$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s9_worker_b8ea747.ps1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s9_b8ea747"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s9-b8ea747"
$OutputDir = Join-Path $RepoRoot "outputs\diagnostic\recovery_s9_paper_additive_seed42"
$VerificationPath = "E:\OV-OrthKD-R3\student_shortcut_control\s9_b8ea747_verification\verification_receipt.json"
$PreparePath = "E:\OV-OrthKD-R3\student_shortcut_control\s9_b8ea747_prepare.json"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "b8ea747dd792c939251152ead734d1826c26980d"
$ExpectedConfigSha = "61942acb92fe0a9a1a87a828764073303761328783b515c606e97d8f10e26cbe"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "2e8909674b3b56ca6ae4d408e3d14c43f72927af8e32f6deac9f43329799dd4b"
$ExpectedVerificationSha = "e2071da533d757ec627b9e55c2998f334c5a3385f209b4d2509d73944ac9acc7"
$ExpectedPrepareSha = "536a946a9c843d84251f2116a32a74aea61b84ef94d66bcdc1ead6aa3ab3f6a3"
$ExpectedBlockerAuditSha = "7784887d05199ae4d70a81c29d497d4a9cd6c689a0746d56aa459b83df4e0d5b"

function Get-NormalizedTextSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $Text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8).Replace("`r`n", "`n")
    $Sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($Sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace("-", "").ToLowerInvariant() }
    finally { $Sha.Dispose() }
}
function Read-LockedReceipt {
    param([string]$Path, [string]$ExpectedSha, [string]$Name)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing $Name" }
    $Actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $ExpectedSha) { throw "$Name SHA256 mismatch: $Actual" }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) { throw "Persistent module SHA256 mismatch" }
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) { throw "S9 worker SHA256 mismatch" }
$Verification = Read-LockedReceipt -Path $VerificationPath -ExpectedSha $ExpectedVerificationSha -Name "S9 candidate verification"
$Prepare = Read-LockedReceipt -Path $PreparePath -ExpectedSha $ExpectedPrepareSha -Name "S9 candidate prepare receipt"
if (
    $Verification.status -ne "PASS" -or $Verification.commit_before -ne $ExpectedCommit -or
    $Verification.commit_after -ne $ExpectedCommit -or [int]$Verification.dirty_before -ne 0 -or
    [int]$Verification.dirty_after -ne 0 -or [int]$Verification.compileall_exit -ne 0 -or
    [int]$Verification.pytest_exit -ne 0 -or [int]$Verification.training_audit_help_exit -ne 0 -or
    [int]$Verification.posthoc_audit_help_exit -ne 0 -or [int]$Verification.ae_help_exit -ne 0
) { throw "S9 verification receipt did not satisfy the launch gate" }
if ($Prepare.status -ne "PASS" -or $Prepare.commit -ne $ExpectedCommit -or [int]$Prepare.dirty_count -ne 0 -or @($Prepare.junctions).Count -ne 9) {
    throw "S9 prepare receipt did not satisfy the launch gate"
}
$BlockerPath = Join-Path $RepoRoot "reports\formal_reproduction\student_shortcut_recovery\evidence\s8\posthoc\s8_posthoc_audit.json"
if ((Get-FileHash -LiteralPath $BlockerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedBlockerAuditSha) { throw "S9 blocker audit SHA256 mismatch" }
$Blocker = Get-Content -LiteralPath $BlockerPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Blocker.status -ne "PASS" -or [int]$Blocker.task_segments -ne 10 -or $Blocker.automatic_scientific_success_claimed -ne $false -or $Blocker.next_experiment_authorized -ne $false -or $Blocker.formal_full_training_authorized -ne $false) { throw "S9 blocker audit did not satisfy the launch gate" }

if (Test-Path -LiteralPath $ControlDir) { throw "Fresh launch refuses an existing S9 control directory" }
if ((Test-Path -LiteralPath $OutputDir) -and @(Get-ChildItem -LiteralPath $OutputDir -Force).Count -ne 0) { throw "Fresh launch refuses a nonempty S9 output" }
$Head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$Dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
$ConfigPath = Join-Path $RepoRoot "configs\diagnostics\recovery\ov_orthkd_s9_paper_additive_seed42.yaml"
$ConfigSha = Get-NormalizedTextSha256 -Path $ConfigPath
if ($Head -ne $ExpectedCommit -or $Dirty.Count -ne 0 -or $ConfigSha -ne $ExpectedConfigSha) { throw "Launch requires exact clean S9 commit/config" }
$Matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*diagnose_s7_zero_training.py*" -or
    $_.CommandLine -like "*run_s9_worker_b8ea747.ps1*"
})
if ($Matching.Count -ne 0) { throw "A conflicting training/A-E/S9 process is already running" }

if ($PreflightOnly) {
    [ordered]@{
        schema_version = 1
        status = "READY"
        starts_worker = $false
        starts_training = $false
        git_head = $Head
        config_sha256 = $ConfigSha
        verification_sha256 = $ExpectedVerificationSha
        prepare_sha256 = $ExpectedPrepareSha
        blocker_audit_sha256 = $ExpectedBlockerAuditSha
        sole_scientific_change_from_s8 = "student.fusion_mode_concat_to_paper_additive"
        formal_full_training = $false
        canonical_loss_changed = $false
        next_experiment_authorized = $false
    } | ConvertTo-Json -Depth 5
    exit 0
}

New-Item -ItemType Directory -Path (Split-Path -Parent $ControlDir) -Force | Out-Null
New-Item -ItemType Directory -Path $ControlDir | Out-Null
Import-Module $ModulePath -Force
$Created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath
$WorkerProcessId = [int]$Created.ProcessId
Start-Sleep -Seconds 10
$Process = Get-Process -Id $WorkerProcessId -ErrorAction SilentlyContinue
$StatePath = Join-Path $ControlDir "worker_state.json"
$State = if (Test-Path -LiteralPath $StatePath) { Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
if ($null -eq $Process) { throw "Persistent S9 worker exited during launch: $($State.message)" }
if ($null -eq $State -or $State.status -ne "running" -or $State.current_phase -ne "s9_training") { throw "Persistent S9 worker did not report training state" }

$Receipt = [ordered]@{
    schema_version = 1
    status = "running"
    launch_method = "Win32_Process.Create_via_verified_PersistentProcess_module"
    utc = [DateTime]::UtcNow.ToString("o")
    worker_process_id = $WorkerProcessId
    return_value = [int]$Created.ReturnValue
    module_sha256 = $ExpectedModuleSha
    worker_sha256 = $ExpectedWorkerSha
    git_head = $ExpectedCommit
    config_sha256 = $ExpectedConfigSha
    candidate_verification_sha256 = $ExpectedVerificationSha
    candidate_prepare_sha256 = $ExpectedPrepareSha
    blocker_audit_sha256 = $ExpectedBlockerAuditSha
    sole_scientific_change_from_s8 = "student.fusion_mode_concat_to_paper_additive"
    sequence = @("s9_training", "training_audit", "s9_ae", "posthoc_audit")
    formal_full_training = $false
    canonical_loss_changed = $false
    next_experiment_authorized = $false
    worker_state = $StatePath
}
$Receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $ControlDir "launch.json") -Encoding UTF8
[ordered]@{
    receipt = $Receipt
    state = $State
    process = @(Get-CimInstance Win32_Process -Filter "ProcessId=$WorkerProcessId" | Select-Object ProcessId,ParentProcessId,Name,CommandLine)
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 8
