param(
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$ExpectedCommit = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"
$ExpectedTrainingAuditScriptSha = "7c768b7039e9740949ae8214a9a860fa43e14dfe4e4a5318a7a2065303e530c3"
$ExpectedTrajectoryScriptSha = "efd36105f131dd4096c3ee35dfc1cba19bc175975f1931e7c9d1f749ffe5425a"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$TrainingControl = "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0"
$TrainingOutput = Join-Path $RepoRoot "outputs\diagnostic\recovery_s7_temporal_identity_seed42"
$CandidateVerification = "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0_verification\verification_receipt.json"
$S4TrainingAudit = "E:\OV-OrthKD-R3\student_shortcut_control\s4_74d211d\s4_training_artifact_audit.json"
$S4PosthocAudit = "E:\OV-OrthKD-R3\student_shortcut_control\s4_posthoc_74d211d_results\s4_posthoc_artifact_audit.json"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s7_posthoc_a7f0dc0"
$ResultsDir = "E:\OV-OrthKD-R3\student_shortcut_control\s7_posthoc_a7f0dc0_results"
$WorkerStatePath = Join-Path $ControlDir "worker_state.json"
$TrainingAuditScript = "E:\OV-OrthKD-R3\student_shortcut_control\audit_s7_training.py"
$TrajectoryScript = "E:\OV-OrthKD-R3\student_shortcut_control\diagnose_s7_checkpoint_trajectory.py"
$TrainingAuditOutput = Join-Path $TrainingControl "s7_training_artifact_audit.json"
$TrajectoryOutput = Join-Path $ResultsDir "s7_checkpoint_trajectory.json"

$env:Path = "$(Split-Path -Parent $Git);$env:Path"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:HF_HUB_CACHE = Join-Path $RepoRoot "data\downloads\hf_cache"
$env:TIMM_USE_OLD_CACHE = "1"
$env:TORCH_HOME = "E:\OV-OrthKD-R3\student_shortcut_control\model_cache\torch"
$env:TOKENIZERS_PARALLELISM = "false"
$env:PYTHONDONTWRITEBYTECODE = "1"

function Write-WorkerState {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [AllowNull()][string]$CurrentPhase,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$CompletedPhases,
        [Nullable[int]]$ExitCode,
        [Parameter(Mandatory = $true)][string]$Message
    )
    New-Item -ItemType Directory -Force -Path $ControlDir | Out-Null
    $payload = [ordered]@{
        schema_version = 1
        status = $Status
        worker_process_id = $PID
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
        git_commit = $ExpectedCommit
        current_phase = $CurrentPhase
        completed_phases = @($CompletedPhases)
        exit_code = $ExitCode
        message = $Message
    }
    $temporary = "$WorkerStatePath.tmp.$PID"
    $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $WorkerStatePath -Force
}

function Assert-PassJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ClaimLevel
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing JSON evidence: $Path" }
    $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        $value.status -ne "PASS" -or
        $value.claim_level -ne $ClaimLevel -or
        $value.git_commit -ne $ExpectedCommit
    ) {
        throw "Invalid JSON evidence: $Path"
    }
    return $value
}

$completed = New-Object System.Collections.Generic.List[string]
try {
    foreach ($required in @(
        $RepoRoot,
        $Python,
        $Git,
        $ModulePath,
        $TrainingControl,
        $TrainingOutput,
        $CandidateVerification,
        $S4TrainingAudit,
        $S4PosthocAudit,
        $TrainingAuditScript,
        $TrajectoryScript
    )) {
        if (-not (Test-Path -LiteralPath $required)) { throw "Required S7 posthoc path is missing: $required" }
    }
    if ((Get-FileHash -LiteralPath $TrainingAuditScript -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedTrainingAuditScriptSha) {
        throw "S7 training audit script SHA256 mismatch"
    }
    if ((Get-FileHash -LiteralPath $TrajectoryScript -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedTrajectoryScriptSha) {
        throw "S7 trajectory script SHA256 mismatch"
    }
    $head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
    $dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
    if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "S7 posthoc requires exact clean commit" }
    $trainingState = Get-Content -LiteralPath (Join-Path $TrainingControl "worker_state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if (
        $trainingState.status -ne "completed" -or
        [int]$trainingState.exit_code -ne 0 -or
        @($trainingState.completed_phases) -join "," -ne "s7_training"
    ) {
        throw "S7 training worker is not completed"
    }

    New-Item -ItemType Directory -Force -Path $ControlDir, $ResultsDir | Out-Null
    Import-Module $ModulePath -Force
    Set-Location -LiteralPath $RepoRoot

    if (Test-Path -LiteralPath $TrainingAuditOutput -PathType Leaf) {
        if (-not $Resume) { throw "Fresh S7 posthoc refuses pre-existing training audit" }
        $null = Assert-PassJson -Path $TrainingAuditOutput -ClaimLevel "noncanonical_s7_training_artifact_audit"
    } else {
        Write-WorkerState -Status "running" -CurrentPhase "training_audit" -CompletedPhases @() -ExitCode $null -Message "S7 training artifact audit is running"
        $arguments = @(
            $TrainingAuditScript,
            "--repo", $RepoRoot,
            "--git", $Git,
            "--control", $TrainingControl,
            "--output", $TrainingOutput,
            "--audit-output", $TrainingAuditOutput,
            "--candidate-verification", $CandidateVerification,
            "--s4-training-audit", $S4TrainingAudit,
            "--s4-posthoc-audit", $S4PosthocAudit
        )
        $code = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $arguments -WorkingDirectory $RepoRoot -StandardOutputPath (Join-Path $ControlDir "training_audit.stdout.log") -StandardErrorPath (Join-Path $ControlDir "training_audit.stderr.log")
        if ($code -ne 0) { throw "S7 training audit exited with code $code" }
        $null = Assert-PassJson -Path $TrainingAuditOutput -ClaimLevel "noncanonical_s7_training_artifact_audit"
    }
    $completed.Add("training_audit")

    if (Test-Path -LiteralPath $TrajectoryOutput -PathType Leaf) {
        if (-not $Resume) { throw "Fresh S7 posthoc refuses pre-existing trajectory result" }
        $null = Assert-PassJson -Path $TrajectoryOutput -ClaimLevel "noncanonical_s7_checkpoint_trajectory_diagnostic"
    } else {
        Write-WorkerState -Status "running" -CurrentPhase "checkpoint_trajectory" -CompletedPhases @($completed) -ExitCode $null -Message "S7 checkpoint trajectory and causal ablations are running"
        $arguments = @(
            $TrajectoryScript,
            "--repo", $RepoRoot,
            "--git", $Git,
            "--training-output", $TrainingOutput,
            "--training-audit", $TrainingAuditOutput,
            "--output", $TrajectoryOutput,
            "--device", "cuda",
            "--shuffle-repeats", "100"
        )
        $code = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $arguments -WorkingDirectory $RepoRoot -StandardOutputPath (Join-Path $ControlDir "trajectory.stdout.log") -StandardErrorPath (Join-Path $ControlDir "trajectory.stderr.log")
        if ($code -ne 0) { throw "S7 checkpoint trajectory exited with code $code" }
        $null = Assert-PassJson -Path $TrajectoryOutput -ClaimLevel "noncanonical_s7_checkpoint_trajectory_diagnostic"
    }
    $completed.Add("checkpoint_trajectory")
    Write-WorkerState -Status "completed" -CurrentPhase $null -CompletedPhases @($completed) -ExitCode 0 -Message "S7 training audit and checkpoint trajectory completed"
    exit 0
} catch {
    Write-WorkerState -Status "failed" -CurrentPhase $null -CompletedPhases @($completed) -ExitCode 1 -Message $_.Exception.ToString()
    exit 1
}
