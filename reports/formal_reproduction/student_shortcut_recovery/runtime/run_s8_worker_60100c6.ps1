param([switch]$Resume)

$ErrorActionPreference = "Stop"
$ExpectedCommit = "60100c6fff95b313ae92bc91b10a3be7135dc437"
$ExpectedConfigSha = "9175ae127d602741f8e6357366b093dafec433d3a578d096be8d49ae2ad1c505"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s8-60100c6"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s8_60100c6"
$WorkerStatePath = Join-Path $ControlDir "worker_state.json"
$TrainingPhaseStatePath = Join-Path $ControlDir "training_phase_state.json"
$VerificationPath = "E:\OV-OrthKD-R3\student_shortcut_control\s8_60100c6_verification\verification_receipt.json"
$Config = "configs\diagnostics\recovery\ov_orthkd_s8_identity_fixed_gate_seed42.yaml"
$S7Config = "configs\diagnostics\recovery\ov_orthkd_s7_temporal_identity_seed42.yaml"
$RelativeOutput = "outputs\diagnostic\recovery_s8_identity_fixed_gate_seed42"
$OutputDir = Join-Path $RepoRoot $RelativeOutput
$TrainingAudit = Join-Path $ControlDir "s8_training_audit.json"
$AeReport = Join-Path $ControlDir "s8_zero_training_ae.json"
$AePredictions = Join-Path $ControlDir "s8_zero_training_predictions.npz"
$PosthocAudit = Join-Path $ControlDir "s8_posthoc_audit.json"

$env:PATH = "$(Split-Path -Parent $Git);$env:PATH"
$env:HF_HUB_CACHE = Join-Path $RepoRoot "data\downloads\hf_cache"
$env:TORCH_HOME = "E:\OV-OrthKD-R3\student_shortcut_control\model_cache\torch"
$env:TOKENIZERS_PARALLELISM = "false"
$env:TIMM_USE_OLD_CACHE = "1"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"

function Get-NormalizedTextSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $Text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8).Replace("`r`n", "`n")
    $Sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($Sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace("-", "").ToLowerInvariant()
    }
    finally { $Sha.Dispose() }
}

function Write-WorkerState {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [AllowNull()][string]$CurrentPhase,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$CompletedPhases,
        [Nullable[int]]$ExitCode,
        [Parameter(Mandatory = $true)][string]$Message
    )
    New-Item -ItemType Directory -Path $ControlDir -Force | Out-Null
    $Payload = [ordered]@{
        schema_version = 1
        status = $Status
        worker_process_id = $PID
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
        git_commit = $ExpectedCommit
        config_sha256 = $ExpectedConfigSha
        current_phase = $CurrentPhase
        completed_phases = @($CompletedPhases)
        exit_code = $ExitCode
        message = $Message
    }
    $Temporary = "$WorkerStatePath.tmp.$PID"
    $Payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Temporary -Encoding UTF8
    Move-Item -LiteralPath $Temporary -Destination $WorkerStatePath -Force
}

function Assert-JsonPass {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $Value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    return $Value.status -eq "PASS"
}

function Assert-CompletedTraining {
    foreach ($Name in @(
        "best.pt", "last.pt", "final_metrics.json", "history.jsonl",
        "training_diagnostics.jsonl", "implementation_behavior.json",
        "resolved_config.yaml", "config_resolved.yaml",
        "validation_predictions.npz", "test_predictions.npz",
        "diagnostic_checkpoints\step_000400.pt",
        "diagnostic_checkpoints\step_000800.pt",
        "diagnostic_checkpoints\step_001200.pt"
    )) {
        $Path = Join-Path $OutputDir $Name
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or (Get-Item -LiteralPath $Path).Length -le 0) {
            throw "Completed S8 output is missing or empty: $Name"
        }
    }
    $History = @(Get-Content -LiteralPath (Join-Path $OutputDir "history.jsonl") -Encoding UTF8 | ForEach-Object { $_ | ConvertFrom-Json })
    $Diagnostics = @(Get-Content -LiteralPath (Join-Path $OutputDir "training_diagnostics.jsonl") -Encoding UTF8 | ForEach-Object { $_ | ConvertFrom-Json })
    if ($History.Count -ne 3 -or $Diagnostics.Count -ne 3 -or (@($History.global_step) -join ",") -ne "400,800,1200") {
        throw "S8 training does not contain exact 3x400 history/diagnostics"
    }
    $Behavior = Get-Content -LiteralPath (Join-Path $OutputDir "implementation_behavior.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Behavior.student.temporal_path_mode -ne "identity_passthrough" -or $Behavior.student.gate_mode -ne "fixed_equal") {
        throw "S8 runtime behavior is not identity_passthrough + fixed_equal"
    }
}

$Completed = New-Object System.Collections.Generic.List[string]
try {
    foreach ($Required in @($RepoRoot, $Python, $Git, $ModulePath, $VerificationPath, (Join-Path $RepoRoot $Config))) {
        if (-not (Test-Path -LiteralPath $Required)) { throw "Required S8 path is missing: $Required" }
    }
    $Head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
    $Dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
    $ConfigSha = Get-NormalizedTextSha256 -Path (Join-Path $RepoRoot $Config)
    if ($Head -ne $ExpectedCommit -or $Dirty.Count -ne 0 -or $ConfigSha -ne $ExpectedConfigSha) {
        throw "S8 worker requires the exact clean implementation commit and config"
    }
    $Verification = Get-Content -LiteralPath $VerificationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        $Verification.status -ne "PASS" -or
        $Verification.commit_before -ne $ExpectedCommit -or
        $Verification.commit_after -ne $ExpectedCommit -or
        [int]$Verification.pytest_exit -ne 0
    ) { throw "S8 candidate verification is not PASS" }
    New-Item -ItemType Directory -Path $ControlDir, $env:HF_HUB_CACHE, $env:TORCH_HOME -Force | Out-Null
    Import-Module $ModulePath -Force
    Set-Location -LiteralPath $RepoRoot

    Write-WorkerState -Status "running" -CurrentPhase "s8_training" -CompletedPhases @($Completed) -ExitCode $null -Message "S8 identity+fixed-equal Student-only training is running"
    if (Test-Path -LiteralPath (Join-Path $OutputDir "final_metrics.json") -PathType Leaf) {
        if (-not $Resume) { throw "Fresh S8 run refuses a completed output" }
        Assert-CompletedTraining
    }
    else {
        $Arguments = @("scripts\train_ov_orthkd.py", "--config", $Config, "--output-dir", $RelativeOutput)
        if ((Test-Path -LiteralPath $OutputDir -PathType Container) -and @(Get-ChildItem -LiteralPath $OutputDir -Force).Count -gt 0) {
            $Last = Join-Path $OutputDir "last.pt"
            if (-not $Resume -or -not (Test-Path -LiteralPath $Last -PathType Leaf)) {
                throw "Nonempty incomplete S8 output requires -Resume and last.pt"
            }
            $Arguments += @("--resume", "$RelativeOutput\last.pt")
        }
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
        $Exit = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $RepoRoot -StandardOutputPath (Join-Path $ControlDir "s8_training.stdout.log") -StandardErrorPath (Join-Path $ControlDir "s8_training.stderr.log")
        if ($Exit -ne 0) { throw "S8 training exited with code $Exit" }
        Assert-CompletedTraining
    }
    $Completed.Add("s8_training")
    [ordered]@{
        schema_version = 1
        status = "completed"
        exit_code = 0
        git_commit = $ExpectedCommit
        config_sha256 = $ExpectedConfigSha
        completed_phases = @("s8_training")
        completed_utc = [DateTime]::UtcNow.ToString("o")
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $TrainingPhaseStatePath -Encoding UTF8

    Write-WorkerState -Status "running" -CurrentPhase "training_audit" -CompletedPhases @($Completed) -ExitCode $null -Message "Independent S8 training artifact audit is running"
    if (Assert-JsonPass -Path $TrainingAudit) {
        if (-not $Resume) { throw "Fresh S8 run refuses an existing training audit" }
    }
    else {
        $AuditArguments = @(
            "scripts\audit_s8_results.py",
            "--repo", $RepoRoot,
            "--git", $Git,
            "--output", $OutputDir,
            "--source-config", (Join-Path $RepoRoot $Config),
            "--s7-config", (Join-Path $RepoRoot $S7Config),
            "--worker-state", $TrainingPhaseStatePath,
            "--candidate-verification", $VerificationPath,
            "--audit-output", $TrainingAudit,
            "--expected-commit", $ExpectedCommit,
            "--expected-config-sha256", $ExpectedConfigSha
        )
        $Exit = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $AuditArguments -WorkingDirectory $RepoRoot -StandardOutputPath (Join-Path $ControlDir "training_audit.stdout.log") -StandardErrorPath (Join-Path $ControlDir "training_audit.stderr.log")
        if ($Exit -ne 0 -or -not (Assert-JsonPass -Path $TrainingAudit)) { throw "Independent S8 training audit failed with code $Exit" }
    }
    $Completed.Add("training_audit")

    Write-WorkerState -Status "running" -CurrentPhase "s8_ae" -CompletedPhases @($Completed) -ExitCode $null -Message "S8 full A-E zero/near-zero-training diagnostics are running"
    if ((Assert-JsonPass -Path $AeReport) -and (Test-Path -LiteralPath $AePredictions -PathType Leaf)) {
        if (-not $Resume) { throw "Fresh S8 run refuses existing A-E artifacts" }
    }
    else {
        $AeArguments = @(
            "scripts\diagnose_s7_zero_training.py",
            "--repo", $RepoRoot,
            "--git", $Git,
            "--training-output", $OutputDir,
            "--training-audit", $TrainingAudit,
            "--output", $AeReport,
            "--prediction-output", $AePredictions,
            "--expected-commit", $ExpectedCommit,
            "--expected-gate-mode", "fixed_equal",
            "--device", "cuda",
            "--shuffle-repeats", "100",
            "--image-examples", "8"
        )
        $Exit = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $AeArguments -WorkingDirectory $RepoRoot -StandardOutputPath (Join-Path $ControlDir "s8_ae.stdout.log") -StandardErrorPath (Join-Path $ControlDir "s8_ae.stderr.log")
        if ($Exit -ne 0 -or -not (Assert-JsonPass -Path $AeReport) -or -not (Test-Path -LiteralPath $AePredictions -PathType Leaf)) { throw "S8 A-E diagnostics failed with code $Exit" }
    }
    $Completed.Add("s8_ae")

    Write-WorkerState -Status "running" -CurrentPhase "posthoc_audit" -CompletedPhases @($Completed) -ExitCode $null -Message "Independent S8 posthoc artifact audit is running"
    if (Assert-JsonPass -Path $PosthocAudit) {
        if (-not $Resume) { throw "Fresh S8 run refuses an existing posthoc audit" }
    }
    else {
        $PosthocArguments = @(
            "scripts\audit_s8_posthoc.py",
            "--repo", $RepoRoot,
            "--git", $Git,
            "--ae-report", $AeReport,
            "--predictions", $AePredictions,
            "--training-audit", $TrainingAudit,
            "--output", $PosthocAudit,
            "--expected-commit", $ExpectedCommit
        )
        $Exit = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $PosthocArguments -WorkingDirectory $RepoRoot -StandardOutputPath (Join-Path $ControlDir "posthoc_audit.stdout.log") -StandardErrorPath (Join-Path $ControlDir "posthoc_audit.stderr.log")
        if ($Exit -ne 0 -or -not (Assert-JsonPass -Path $PosthocAudit)) { throw "Independent S8 posthoc audit failed with code $Exit" }
    }
    $Completed.Add("posthoc_audit")
    Write-WorkerState -Status "completed" -CurrentPhase $null -CompletedPhases @($Completed) -ExitCode 0 -Message "S8 identity+fixed-equal training and independent audits completed"
    exit 0
}
catch {
    Write-WorkerState -Status "failed" -CurrentPhase $null -CompletedPhases @($Completed) -ExitCode 1 -Message $_.Exception.ToString()
    exit 1
}
