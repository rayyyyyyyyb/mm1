param(
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$ExpectedCommit = "c181ffb3297ff480a0d01186c626acce7c66afff"
$RepoRoot = "E:\OV-OrthKD-R3\zero-training-c181ffb"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$ControlRoot = "E:\OV-OrthKD-R3\zero_training_control\c181ffb"
$WorkerControl = Join-Path $ControlRoot "worker"
$Results = Join-Path $ControlRoot "results"
$WorkerStatePath = Join-Path $WorkerControl "worker_state.json"

$S7Output = "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0\outputs\diagnostic\recovery_s7_temporal_identity_seed42"
$S7TrainingAudit = "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0\s7_training_artifact_audit.json"
$S7Trajectory = "E:\OV-OrthKD-R3\student_shortcut_control\s7_posthoc_a7f0dc0_results\s7_checkpoint_trajectory.json"
$FullConfig = "E:\OV-OrthKD-R3\formal-canonical-31b86c0\outputs\formal\mm26_canonical_seed42\resolved_config.yaml"
$FullCheckpoint = "E:\OV-OrthKD-R3\formal-canonical-31b86c0\outputs\formal\mm26_canonical_seed42\best.pt"

$AEReport = Join-Path $Results "s7_zero_training_ae.json"
$Predictions = Join-Path $Results "s7_zero_training_interventions.npz"
$FReport = Join-Path $Results "full_projector_probe.json"
$AuditReport = Join-Path $Results "zero_training_artifact_audit.json"

$LockedFiles = [ordered]@{
    $S7TrainingAudit = "6583c7f403041be961bba5a40dd7f7e4c8f8d38fd1fee2c7548396b5b6e30dc2"
    $S7Trajectory = "74fd36bafd08d0d30e0e165c886e02b84fa94ac092b359399714d71e360be992"
    (Join-Path $S7Output "resolved_config.yaml") = "6453f0c0c2bf9d09c8ac19089ffff60a5bf044be2cee5b76fa0750406889d366"
    (Join-Path $S7Output "best.pt") = "60cfb52dfb366e315feeee3e704c996793636ba8b802e7b7d92072ba19bbf572"
    (Join-Path $S7Output "diagnostic_checkpoints\step_000400.pt") = "c4c591b4f4a4cdfbe0586939de803db8c27901a9c4c5be47ec3f55c59cf75c26"
    (Join-Path $S7Output "diagnostic_checkpoints\step_000800.pt") = "d100d89f7e816005f85a4e4b66f9b1d34c2dd71b5cfd3723ec05dbb48ad445e0"
    (Join-Path $S7Output "diagnostic_checkpoints\step_001200.pt") = "1a65c41b23ac854ec7568ec308ef444469a21130a115e25c24c7f98e38e2c958"
    $FullConfig = "9d7ed87ac27303596f70463f56bba95a0bee687bc328f2ec0f14930dc2e66dc7"
    $FullCheckpoint = "01cdb036ec11768ced94331742490d62c1f62bf842b2b2ee03134101dba1f392"
}

$env:PATH = "$(Split-Path -Parent $Git);$env:PATH"
$env:HF_HUB_CACHE = Join-Path $RepoRoot "data\downloads\hf_cache"
$env:TORCH_HOME = "E:\OV-OrthKD-R3\zero_training_control\model_cache\torch"
$env:TOKENIZERS_PARALLELISM = "false"
$env:TIMM_USE_OLD_CACHE = "1"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"

function Write-WorkerState {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [AllowNull()][string]$CurrentPhase,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$CompletedPhases,
        [Nullable[int]]$ExitCode,
        [Parameter(Mandatory = $true)][string]$Message
    )
    New-Item -ItemType Directory -Force -Path $WorkerControl | Out-Null
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

function Assert-LockedSources {
    foreach ($path in $LockedFiles.Keys) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Locked source is missing: $path"
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $LockedFiles[$path]) {
            throw "Locked source SHA256 mismatch: $path :: $actual"
        }
    }
}

function Assert-CleanCandidate {
    $head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
    $dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
    if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) {
        throw "Worker requires exact clean candidate $ExpectedCommit"
    }
}

function Read-PassJson {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Expected PASS JSON is missing: $Path"
    }
    $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($value.status -ne "PASS") { throw "JSON is not PASS: $Path" }
    return $value
}

function Assert-AEPhase {
    $report = Read-PassJson -Path $AEReport
    if ([int]$report.protocol.task_segments -ne 10) { throw "A-E task segments are not 10" }
    if (-not (Test-Path -LiteralPath $Predictions -PathType Leaf)) { throw "A-E prediction archive is missing" }
    $actual = (Get-FileHash -LiteralPath $Predictions -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($report.sources.prediction_archive.sha256 -ne $actual) { throw "A-E prediction archive receipt mismatch" }
}

function Assert-FPhase {
    $report = Read-PassJson -Path $FReport
    if (
        [int]$report.protocol.task_segments -ne 10 -or
        [int]$report.protocol.optimizer_steps_on_source -ne 0 -or
        $report.probe.disposable_adamw_step.persisted -ne $false
    ) {
        throw "F disposable clone boundary failed"
    }
}

function Assert-AuditPhase {
    $report = Read-PassJson -Path $AuditReport
    if ([int]$report.task_segments -ne 10 -or $report.claim_level -ne "artifact_integrity_only") {
        throw "Independent artifact audit boundary failed"
    }
}

function Invoke-LockedPython {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$LogStem
    )
    $stdout = Join-Path $WorkerControl "$LogStem.stdout.log"
    $stderr = Join-Path $WorkerControl "$LogStem.stderr.log"
    if ((Test-Path -LiteralPath $stdout) -or (Test-Path -LiteralPath $stderr)) {
        throw "Phase log collision: $LogStem"
    }
    & $Python @Arguments 1> $stdout 2> $stderr
    if ($LASTEXITCODE -ne 0) {
        throw "$LogStem exited with code $LASTEXITCODE"
    }
}

$completed = New-Object System.Collections.Generic.List[string]
try {
    foreach ($required in @($RepoRoot, $Python, $Git, $ModulePath, $S7Output)) {
        if (-not (Test-Path -LiteralPath $required)) { throw "Required worker path is missing: $required" }
    }
    Assert-CleanCandidate
    Assert-LockedSources
    New-Item -ItemType Directory -Force -Path $WorkerControl, $Results, $env:HF_HUB_CACHE, $env:TORCH_HOME | Out-Null
    Set-Location -LiteralPath $RepoRoot

    if ($Resume -and (Test-Path -LiteralPath $AEReport -PathType Leaf)) {
        Assert-AEPhase
    }
    else {
        if ((Test-Path -LiteralPath $AEReport) -or (Test-Path -LiteralPath $Predictions)) {
            throw "A-E output collision or incomplete phase requires manual audit"
        }
        Write-WorkerState -Status "running" -CurrentPhase "ae" -CompletedPhases @($completed) -ExitCode $null -Message "S7 A-E zero-training diagnostics running"
        Invoke-LockedPython -LogStem "ae" -Arguments @(
            "scripts\diagnose_s7_zero_training.py",
            "--repo", $RepoRoot,
            "--git", $Git,
            "--training-output", $S7Output,
            "--training-audit", $S7TrainingAudit,
            "--output", $AEReport,
            "--prediction-output", $Predictions,
            "--expected-commit", $ExpectedCommit,
            "--device", "cuda",
            "--shuffle-repeats", "100",
            "--image-examples", "8"
        )
        Assert-AEPhase
    }
    $completed.Add("ae")
    Assert-CleanCandidate
    Assert-LockedSources

    if ($Resume -and (Test-Path -LiteralPath $FReport -PathType Leaf)) {
        Assert-FPhase
    }
    else {
        if (Test-Path -LiteralPath $FReport) { throw "F output collision" }
        Write-WorkerState -Status "running" -CurrentPhase "f" -CompletedPhases @($completed) -ExitCode $null -Message "Disposable Full projector probe running"
        Invoke-LockedPython -LogStem "f" -Arguments @(
            "scripts\diagnose_full_projector_probe.py",
            "--repo", $RepoRoot,
            "--git", $Git,
            "--config", $FullConfig,
            "--checkpoint", $FullCheckpoint,
            "--output", $FReport,
            "--expected-commit", $ExpectedCommit,
            "--device", "cuda"
        )
        Assert-FPhase
    }
    $completed.Add("f")
    Assert-CleanCandidate
    Assert-LockedSources

    if ($Resume -and (Test-Path -LiteralPath $AuditReport -PathType Leaf)) {
        Assert-AuditPhase
    }
    else {
        if (Test-Path -LiteralPath $AuditReport) { throw "Audit output collision" }
        Write-WorkerState -Status "running" -CurrentPhase "audit" -CompletedPhases @($completed) -ExitCode $null -Message "Independent artifact audit running"
        Invoke-LockedPython -LogStem "audit" -Arguments @(
            "scripts\audit_zero_training_evidence.py",
            "--repo", $RepoRoot,
            "--git", $Git,
            "--ae-report", $AEReport,
            "--predictions", $Predictions,
            "--f-report", $FReport,
            "--training-audit", $S7TrainingAudit,
            "--trajectory", $S7Trajectory,
            "--output", $AuditReport,
            "--expected-commit", $ExpectedCommit
        )
        Assert-AuditPhase
    }
    $completed.Add("audit")
    Assert-CleanCandidate
    Assert-LockedSources
    Write-WorkerState -Status "completed" -CurrentPhase $null -CompletedPhases @($completed) -ExitCode 0 -Message "A-F zero-training diagnostics and independent audit completed"
    exit 0
}
catch {
    Write-WorkerState -Status "failed" -CurrentPhase $null -CompletedPhases @($completed) -ExitCode 1 -Message $_.Exception.ToString()
    exit 1
}
