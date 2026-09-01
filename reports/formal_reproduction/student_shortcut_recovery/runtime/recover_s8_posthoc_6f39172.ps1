param([switch]$PreflightOnly)

$ErrorActionPreference = "Stop"
$ScientificRepo = "E:\OV-OrthKD-R3\student-shortcut-s8-60100c6"
$AuditRepo = "E:\OV-OrthKD-R3\student-shortcut-s8-audit-6f39172"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s8_60100c6"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$VerificationPath = "E:\OV-OrthKD-R3\student_shortcut_control\s8_audit_fix_verification_6f39172.json"
$BundlePath = "E:\OV-OrthKD-R3\student_shortcut_control\s8_audit_fix_6f39172.bundle"
$ScientificCommit = "60100c6fff95b313ae92bc91b10a3be7135dc437"
$AuditCommit = "6f39172120ab877c246d3fd6fbd1a4699a6f2871"
$ConfigSha = "9175ae127d602741f8e6357366b093dafec433d3a578d096be8d49ae2ad1c505"
$VerificationSha = "0ce8cf933c256eb710a0b6dd223aab2d8961a6665925dc4c1d44217449dd549c"
$BundleSha = "e9090d00f204b9f4f3e2af4e28ec8f39c195143923d00722bc5f05b7be1abb4f"
$AuditScriptSha = "f64a7305b38c63ad75d0a3e5e1ff37d0cf949e2f39d8ef53f13f45de74187934"
$AuditResultsSha = "a83bde2a06261b6a9e571f769c1de99375a0565f8e0dda8f4e30d2915dbb9b7b"
$TrainingAuditSha = "7aa1108a8f536f720735edec5183d9846d52e8b28ce7236db2f5121354bc6a11"
$AeReportSha = "54baa6c27b286226bce5698ef0a3e56456aadf739c577915d5a57c82af55ca7d"
$PredictionsSha = "5a28ce8cc58674f89aa4388b9e205410877a954491051b93c9db9e839c2bec68"

$StatePath = Join-Path $ControlDir "worker_state.json"
$FailedStateCopy = Join-Path $ControlDir "worker_state_failed_before_posthoc_recovery.json"
$TrainingAudit = Join-Path $ControlDir "s8_training_audit.json"
$AeReport = Join-Path $ControlDir "s8_zero_training_ae.json"
$Predictions = Join-Path $ControlDir "s8_zero_training_predictions.npz"
$PosthocAudit = Join-Path $ControlDir "s8_posthoc_audit.json"
$RecoveryStdout = Join-Path $ControlDir "posthoc_recovery.stdout.log"
$RecoveryStderr = Join-Path $ControlDir "posthoc_recovery.stderr.log"
$RecoveryReceipt = Join-Path $ControlDir "posthoc_recovery_receipt_6f39172.json"
$ConfigPath = Join-Path $ScientificRepo "configs\diagnostics\recovery\ov_orthkd_s8_identity_fixed_gate_seed42.yaml"
$AuditScript = Join-Path $AuditRepo "scripts\audit_s8_posthoc.py"
$AuditResults = Join-Path $AuditRepo "scripts\audit_s8_results.py"

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-NormalizedTextSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $Text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8).Replace("`r`n", "`n")
    $Sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($Sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $Sha.Dispose()
    }
}

function Write-JsonAtomically {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value,
        [int]$Depth = 16
    )
    $Temporary = "$Path.tmp.$PID"
    $Json = $Value | ConvertTo-Json -Depth $Depth
    [IO.File]::WriteAllText($Temporary, $Json, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $Temporary -Destination $Path -Force
}

function Assert-FileSha {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label is missing: $Path"
    }
    $Actual = Get-Sha256 -Path $Path
    if ($Actual -ne $Expected) {
        throw "$Label SHA256 mismatch: expected $Expected, got $Actual"
    }
}

function Assert-NormalizedTextSha {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label is missing: $Path"
    }
    $Actual = Get-NormalizedTextSha256 -Path $Path
    if ($Actual -ne $Expected) {
        throw "$Label normalized SHA256 mismatch: expected $Expected, got $Actual"
    }
}

function Assert-CleanCommit {
    param(
        [Parameter(Mandatory = $true)][string]$Repo,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $Head = (& $Git -C $Repo rev-parse HEAD).Trim()
    $Dirty = @(& $Git -C $Repo status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0 -or $Head -ne $Expected -or $Dirty.Count -ne 0) {
        throw "$Label must be exact and clean: head=$Head dirty=$($Dirty.Count)"
    }
}

Assert-FileSha -Path $VerificationPath -Expected $VerificationSha -Label "audit verification receipt"
Assert-FileSha -Path $BundlePath -Expected $BundleSha -Label "audit bundle"
Assert-FileSha -Path $TrainingAudit -Expected $TrainingAuditSha -Label "S8 training audit"
Assert-FileSha -Path $AeReport -Expected $AeReportSha -Label "S8 A-E report"
Assert-FileSha -Path $Predictions -Expected $PredictionsSha -Label "S8 prediction archive"
Assert-NormalizedTextSha -Path $AuditScript -Expected $AuditScriptSha -Label "posthoc auditor"
Assert-NormalizedTextSha -Path $AuditResults -Expected $AuditResultsSha -Label "posthoc metric extractor"
Assert-CleanCommit -Repo $ScientificRepo -Expected $ScientificCommit -Label "scientific candidate"
Assert-CleanCommit -Repo $AuditRepo -Expected $AuditCommit -Label "audit candidate"
if ((Get-NormalizedTextSha256 -Path $ConfigPath) -ne $ConfigSha) {
    throw "S8 scientific config SHA256 mismatch"
}

$Verification = Get-Content -LiteralPath $VerificationPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    $Verification.status -ne "PASS" -or
    $Verification.git_commit -ne $AuditCommit -or
    [int]$Verification.compileall.exit_code -ne 0 -or
    [int]$Verification.pytest.exit_code -ne 0 -or
    [int]$Verification.pytest.passed -ne 536 -or
    [int]$Verification.pytest.failed -ne 0 -or
    $Verification.head_before -ne $AuditCommit -or
    $Verification.head_after -ne $AuditCommit -or
    [string]$Verification.status_before -ne "" -or
    [string]$Verification.status_after -ne ""
) {
    throw "Audit candidate verification receipt is not an exact full PASS"
}

$ScopedScientificDiff = @(& $Git -C $AuditRepo diff --name-only "$ScientificCommit..$AuditCommit" -- src scripts configs)
if ($LASTEXITCODE -ne 0 -or $ScopedScientificDiff.Count -ne 1 -or $ScopedScientificDiff[0] -ne "scripts/audit_s8_results.py") {
    throw "Audit candidate changes unexpected scientific code: $($ScopedScientificDiff -join ',')"
}

if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw "Original S8 worker state is missing"
}
$StateBefore = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
$CompletedBefore = @($StateBefore.completed_phases)
if (
    $StateBefore.status -ne "failed" -or
    [int]$StateBefore.exit_code -ne 1 -or
    $StateBefore.git_commit -ne $ScientificCommit -or
    $StateBefore.config_sha256 -ne $ConfigSha -or
    ($CompletedBefore -join ",") -ne "s8_training,training_audit,s8_ae" -or
    [string]$StateBefore.message -notlike "*posthoc audit failed*"
) {
    throw "Original S8 state is not the exact isolated posthoc failure"
}

if (Test-Path -LiteralPath $PosthocAudit -PathType Leaf) {
    $Existing = Get-Content -LiteralPath $PosthocAudit -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Existing.status -eq "PASS") {
        throw "Formal S8 posthoc audit already passed; refusing duplicate recovery"
    }
    throw "Unexpected non-PASS formal posthoc artifact exists"
}
if (Test-Path -LiteralPath $RecoveryReceipt -PathType Leaf) {
    throw "Posthoc recovery receipt already exists"
}

$Conflicts = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*diagnose_s7_zero_training.py*" -or
    $_.CommandLine -like "*audit_s8_posthoc.py*" -or
    $_.CommandLine -like "*run_s8_worker_60100c6.ps1*"
})
if ($Conflicts.Count -ne 0) {
    throw "Conflicting training/A-E/posthoc process exists: $($Conflicts.ProcessId -join ',')"
}

$ControlSha = Get-Sha256 -Path $PSCommandPath
$Gate = [ordered]@{
    schema_version = 1
    status = "READY"
    preflight_only = [bool]$PreflightOnly
    scientific_commit = $ScientificCommit
    audit_commit = $AuditCommit
    config_sha256 = $ConfigSha
    verification_sha256 = $VerificationSha
    bundle_sha256 = $BundleSha
    training_audit_sha256 = $TrainingAuditSha
    ae_report_sha256 = $AeReportSha
    predictions_sha256 = $PredictionsSha
    recovery_control_sha256 = $ControlSha
    completed_phases_before = $CompletedBefore
    starts_training = $false
    starts_ae = $false
    changes_canonical_loss = $false
    formal_full_training_authorized = $false
    next_experiment_authorized = $false
}
if ($PreflightOnly) {
    $Gate.starts_posthoc_audit = $false
    $Gate | ConvertTo-Json -Depth 8
    exit 0
}

if (Test-Path -LiteralPath $FailedStateCopy) {
    throw "Failed-state preservation artifact already exists"
}
Copy-Item -LiteralPath $StatePath -Destination $FailedStateCopy
$FailedStateCopySha = Get-Sha256 -Path $FailedStateCopy

$PosthocArguments = @(
    $AuditScript,
    "--repo", $ScientificRepo,
    "--git", $Git,
    "--ae-report", $AeReport,
    "--predictions", $Predictions,
    "--training-audit", $TrainingAudit,
    "--output", $PosthocAudit,
    "--expected-commit", $ScientificCommit
)
$Process = Start-Process -FilePath $Python -ArgumentList $PosthocArguments -WorkingDirectory $AuditRepo -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $RecoveryStdout -RedirectStandardError $RecoveryStderr
if ([int]$Process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $PosthocAudit -PathType Leaf)) {
    throw "Recovered posthoc auditor failed with code $($Process.ExitCode)"
}
$Posthoc = Get-Content -LiteralPath $PosthocAudit -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    $Posthoc.status -ne "PASS" -or
    $Posthoc.claim_level -ne "artifact_integrity_and_exact_metrics_only" -or
    [int]$Posthoc.task_segments -ne 10 -or
    $Posthoc.expected_gate_mode -ne "fixed_equal" -or
    $Posthoc.git_commit -ne $ScientificCommit -or
    $Posthoc.integrity_audit.status -ne "PASS" -or
    [int]$Posthoc.integrity_audit.verified_source_receipt_count -ne 8 -or
    [int]$Posthoc.integrity_audit.prediction_archive.mode_count -ne 17 -or
    [int]$Posthoc.integrity_audit.prediction_archive.sample_count -ne 5820 -or
    [int]$Posthoc.integrity_audit.prediction_archive.segment_count -ne 58200 -or
    [bool]$Posthoc.scientific_outcome_threshold_preregistered -ne $false -or
    [bool]$Posthoc.automatic_scientific_success_claimed -ne $false -or
    [bool]$Posthoc.next_experiment_authorized -ne $false -or
    [bool]$Posthoc.formal_full_training_authorized -ne $false
) {
    throw "Recovered posthoc output does not satisfy the exact artifact-only contract"
}
if (
    $Posthoc.sources.training_audit.sha256 -ne $TrainingAuditSha -or
    $Posthoc.sources.ae_report.sha256 -ne $AeReportSha -or
    $Posthoc.sources.prediction_archive.sha256 -ne $PredictionsSha
) {
    throw "Recovered posthoc output source receipts do not match locked S8 artifacts"
}

$StateAfter = [ordered]@{
    schema_version = 1
    status = "completed"
    worker_process_id = $PID
    updated_at_utc = [DateTime]::UtcNow.ToString("o")
    git_commit = $ScientificCommit
    config_sha256 = $ConfigSha
    current_phase = $null
    completed_phases = @("s8_training", "training_audit", "s8_ae", "posthoc_audit")
    exit_code = 0
    message = "S8 identity+fixed-equal training and independent audits completed via posthoc reader fix $AuditCommit"
}
Write-JsonAtomically -Path $StatePath -Value $StateAfter -Depth 8

$PosthocReceipt = [ordered]@{
    path = $PosthocAudit
    bytes = (Get-Item -LiteralPath $PosthocAudit).Length
    sha256 = Get-Sha256 -Path $PosthocAudit
    independent_metrics_canonical_sha256 = [string]$Posthoc.integrity_audit.independent_metrics_canonical_sha256
}
$Receipt = [ordered]@{
    schema_version = 1
    status = "PASS"
    claim_level = "s8_posthoc_reader_fix_recovery"
    completed_utc = [DateTime]::UtcNow.ToString("o")
    gate = $Gate
    scientific_worker_state_before = $StateBefore
    preserved_failed_state = [ordered]@{
        path = $FailedStateCopy
        sha256 = $FailedStateCopySha
    }
    scientific_worker_state_after = $StateAfter
    recovered_posthoc_audit = $PosthocReceipt
    recovery_logs = [ordered]@{
        stdout = [ordered]@{ bytes = (Get-Item -LiteralPath $RecoveryStdout).Length; sha256 = Get-Sha256 -Path $RecoveryStdout }
        stderr = [ordered]@{ bytes = (Get-Item -LiteralPath $RecoveryStderr).Length; sha256 = Get-Sha256 -Path $RecoveryStderr }
    }
    starts_training = $false
    starts_ae = $false
    changes_canonical_loss = $false
    formal_full_training_authorized = $false
    next_experiment_authorized = $false
}
Write-JsonAtomically -Path $RecoveryReceipt -Value $Receipt -Depth 18
$Receipt | ConvertTo-Json -Depth 18
