param([switch]$PreflightOnly)

$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s8_worker_60100c6.ps1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s8_60100c6"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s8-60100c6"
$OutputDir = Join-Path $RepoRoot "outputs\diagnostic\recovery_s8_identity_fixed_gate_seed42"
$VerificationPath = "E:\OV-OrthKD-R3\student_shortcut_control\s8_60100c6_verification\verification_receipt.json"
$PreparePath = "E:\OV-OrthKD-R3\student_shortcut_control\s8_60100c6_prepare.json"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "60100c6fff95b313ae92bc91b10a3be7135dc437"
$ExpectedConfigSha = "9175ae127d602741f8e6357366b093dafec433d3a578d096be8d49ae2ad1c505"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "0956fcbef0be3e7b4a14476e1f60a0556d9f72ebc81f04ce4a48eb3f2a2daa4e"
$ExpectedVerificationSha = "80aa29b284c2ab5ae4ec91277f7f7d53c178d18a6c4fe2f84e438cdbd0e12223"
$ExpectedPrepareSha = "97e90f746b33eb27cd1ec79bc56884a86105607246baadbfb5a6a13617d9dffb"
$ExpectedBlockerAuditSha = "a90cf867cb9c1598644b2e072691f1dba26446d19973ecaa1a7e202e4affd31a"

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
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) { throw "S8 worker SHA256 mismatch" }
$Verification = Read-LockedReceipt -Path $VerificationPath -ExpectedSha $ExpectedVerificationSha -Name "S8 candidate verification"
$Prepare = Read-LockedReceipt -Path $PreparePath -ExpectedSha $ExpectedPrepareSha -Name "S8 candidate prepare receipt"
if (
    $Verification.status -ne "PASS" -or $Verification.commit_before -ne $ExpectedCommit -or
    $Verification.commit_after -ne $ExpectedCommit -or [int]$Verification.dirty_before -ne 0 -or
    [int]$Verification.dirty_after -ne 0 -or [int]$Verification.compileall_exit -ne 0 -or
    [int]$Verification.pytest_exit -ne 0 -or [int]$Verification.training_audit_help_exit -ne 0 -or
    [int]$Verification.posthoc_audit_help_exit -ne 0 -or [int]$Verification.ae_help_exit -ne 0
) { throw "S8 verification receipt did not satisfy the launch gate" }
if ($Prepare.status -ne "PASS" -or $Prepare.commit -ne $ExpectedCommit -or [int]$Prepare.dirty_count -ne 0 -or @($Prepare.junctions).Count -ne 9) {
    throw "S8 prepare receipt did not satisfy the launch gate"
}
$BlockerPath = Join-Path $RepoRoot "reports\formal_reproduction\student_shortcut_recovery\evidence\zero_training\zero_training_artifact_audit.json"
if ((Get-FileHash -LiteralPath $BlockerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedBlockerAuditSha) { throw "S8 blocker audit SHA256 mismatch" }
$Blocker = Get-Content -LiteralPath $BlockerPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Blocker.status -ne "PASS" -or [int]$Blocker.task_segments -ne 10 -or $Blocker.scientific_success_claimed -ne $false) { throw "S8 blocker audit did not satisfy the launch gate" }

if (Test-Path -LiteralPath $ControlDir) { throw "Fresh launch refuses an existing S8 control directory" }
if ((Test-Path -LiteralPath $OutputDir) -and @(Get-ChildItem -LiteralPath $OutputDir -Force).Count -ne 0) { throw "Fresh launch refuses a nonempty S8 output" }
$Head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$Dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
$ConfigPath = Join-Path $RepoRoot "configs\diagnostics\recovery\ov_orthkd_s8_identity_fixed_gate_seed42.yaml"
$ConfigSha = Get-NormalizedTextSha256 -Path $ConfigPath
if ($Head -ne $ExpectedCommit -or $Dirty.Count -ne 0 -or $ConfigSha -ne $ExpectedConfigSha) { throw "Launch requires exact clean S8 commit/config" }
$Matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*diagnose_s7_zero_training.py*" -or
    $_.CommandLine -like "*run_s8_worker_60100c6.ps1*"
})
if ($Matching.Count -ne 0) { throw "A conflicting training/A-E/S8 process is already running" }

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
        sole_scientific_change_from_s7 = "student.gate_mode_learned_to_fixed_equal"
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
if ($null -eq $Process) { throw "Persistent S8 worker exited during launch: $($State.message)" }
if ($null -eq $State -or $State.status -ne "running" -or $State.current_phase -ne "s8_training") { throw "Persistent S8 worker did not report training state" }

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
    sole_scientific_change_from_s7 = "student.gate_mode_learned_to_fixed_equal"
    sequence = @("s8_training", "training_audit", "s8_ae", "posthoc_audit")
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
