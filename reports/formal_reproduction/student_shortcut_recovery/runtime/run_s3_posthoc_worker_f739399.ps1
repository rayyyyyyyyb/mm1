param(
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$ExpectedCommit = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-a0aa4d7"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$S3Control = "E:\OV-OrthKD-R3\student_shortcut_control\s3_a0aa4d7"
$TrainingAuditPath = Join-Path $S3Control "s3_training_artifact_audit.json"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s3_posthoc_a0aa4d7"
$ResultsDir = "E:\OV-OrthKD-R3\student_shortcut_control\s3_posthoc_a0aa4d7_results"
$WorkerStatePath = Join-Path $ControlDir "worker_state.json"
$TrainingOutput = Join-Path $RepoRoot "outputs\diagnostic\recovery_s3_pretrained_seed42"
$PredictionOutput = Join-Path $ResultsDir "prediction_shortcut.json"
$ModalityOutput = Join-Path $ResultsDir "checkpoint_modality.json"
$ExpectedCacheAssets = [ordered]@{
    visual = [ordered]@{
        Path = "E:\OV-OrthKD-R3\student_shortcut_control\model_cache\torch\hub\checkpoints\convnextv2_tiny_22k_224_ema.pt"
        Bytes = 114604362
        Sha256 = "853d431aa9363f1b058e3c343d4bf2fca5fe2a4196621c381ddbcd4828290a96"
    }
    audio = [ordered]@{
        Path = "E:\OV-OrthKD-R3\student_shortcut_control\model_cache\torch\hub\checkpoints\tf_efficientnetv2_b2-847de54e.pth"
        Bytes = 40795861
        Sha256 = "847de54eb133fad3ab1230ff637ed242aefe9fd2da197d041e6753d9ec5a80bd"
    }
}

$env:Path = "$(Split-Path -Parent $Git);$env:Path"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:HF_HUB_CACHE = Join-Path $RepoRoot "data\downloads\hf_cache"
$env:TIMM_USE_OLD_CACHE = "1"
$env:TORCH_HOME = "E:\OV-OrthKD-R3\student_shortcut_control\model_cache\torch"
$env:TOKENIZERS_PARALLELISM = "false"

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
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $WorkerStatePath -Force
}

function Assert-JsonPass {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing posthoc JSON: $Path" }
    $payload = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($payload.status -ne "PASS" -or [int]$payload.protocol.task_segments -ne 10 -or
        $payload.protocol.temporal_conversion -ne "forbidden") {
        throw "Invalid posthoc JSON: $Path"
    }
}

$completed = New-Object System.Collections.Generic.List[string]
try {
    foreach ($required in @($RepoRoot, $Python, $Git, $ModulePath, $TrainingAuditPath)) {
        if (-not (Test-Path -LiteralPath $required)) { throw "Required S3 posthoc path is missing: $required" }
    }
    $head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
    $dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
    if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "S3 posthoc requires exact clean commit" }
    $training = Get-Content -LiteralPath $TrainingAuditPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($training.status -ne "PASS" -or $training.git_commit -ne $ExpectedCommit -or
        [int]$training.task_segments -ne 10) { throw "S3 training audit gate failed" }
    foreach ($role in @("visual", "audio")) {
        $asset = $training.official_cache_receipt.assets.$role
        $expected = $ExpectedCacheAssets[$role]
        $expectedTarget = [string]$expected.Path
        if ($null -eq $asset -or $asset.status -ne "PASS" -or
            [string]$asset.target -ne $expectedTarget -or
            [int64]$asset.bytes -ne [int64]$expected.Bytes -or
            [string]$asset.sha256 -ne [string]$expected.Sha256) {
            throw "S3 posthoc official cache receipt mismatch for $role"
        }
        if (-not (Test-Path -LiteralPath $expectedTarget -PathType Leaf) -or
            (Get-Item -LiteralPath $expectedTarget).Length -ne [int64]$expected.Bytes) {
            throw "S3 posthoc official cache file is missing or has wrong size for $role"
        }
        $actualCacheSha = (Get-FileHash -LiteralPath $expectedTarget -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualCacheSha -ne [string]$asset.sha256) {
            throw "S3 posthoc official cache SHA256 mismatch for $role"
        }
    }
    $validation = Join-Path $TrainingOutput "validation_predictions.npz"
    $test = Join-Path $TrainingOutput "test_predictions.npz"
    $checkpoint = Join-Path $TrainingOutput "best.pt"
    $config = Join-Path $TrainingOutput "resolved_config.yaml"
    foreach ($item in @(
        @($validation, $training.predictions.validation.sha256),
        @($test, $training.predictions.test.sha256),
        @($checkpoint, $training.artifacts.'best.pt'.sha256),
        @($config, $training.artifacts.'resolved_config.yaml'.sha256)
    )) {
        if (-not (Test-Path -LiteralPath $item[0] -PathType Leaf)) { throw "Missing S3 source artifact: $($item[0])" }
        $actual = (Get-FileHash -LiteralPath $item[0] -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$item[1]) { throw "S3 source SHA256 mismatch: $($item[0])" }
    }
    New-Item -ItemType Directory -Force -Path $ControlDir, $ResultsDir | Out-Null
    Import-Module $ModulePath -Force
    Set-Location -LiteralPath $RepoRoot

    if (Test-Path -LiteralPath $PredictionOutput -PathType Leaf) {
        if (-not $Resume) { throw "Fresh posthoc refuses pre-existing prediction result" }
        Assert-JsonPass -Path $PredictionOutput
    } else {
        Write-WorkerState -Status "running" -CurrentPhase "prediction" -CompletedPhases @() -ExitCode $null -Message "S3 prediction shortcut diagnostic"
        $arguments = @(
            "scripts\diagnose_student_shortcuts.py",
            "--train-manifest", "data\ov_ave\exported\train.jsonl",
            "--validation", $validation,
            "--test", $test,
            "--output", $PredictionOutput,
            "--expected-segments", "10",
            "--shuffle-repeats", "100",
            "--seed", "42"
        )
        $code = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $arguments -WorkingDirectory $RepoRoot -StandardOutputPath (Join-Path $ControlDir "prediction.stdout.log") -StandardErrorPath (Join-Path $ControlDir "prediction.stderr.log")
        if ($code -ne 0) { throw "S3 prediction diagnostic exited with code $code" }
        Assert-JsonPass -Path $PredictionOutput
    }
    $completed.Add("prediction")

    if (Test-Path -LiteralPath $ModalityOutput -PathType Leaf) {
        if (-not $Resume) { throw "Fresh posthoc refuses pre-existing modality result" }
        Assert-JsonPass -Path $ModalityOutput
    } else {
        Write-WorkerState -Status "running" -CurrentPhase "modality" -CompletedPhases @($completed) -ExitCode $null -Message "S3 checkpoint modality diagnostic"
        $arguments = @(
            "scripts\diagnose_checkpoint_modalities.py",
            "--config", $config,
            "--checkpoint", $checkpoint,
            "--output", $ModalityOutput,
            "--device", "cuda",
            "--expected-segments", "10"
        )
        $code = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $arguments -WorkingDirectory $RepoRoot -StandardOutputPath (Join-Path $ControlDir "modality.stdout.log") -StandardErrorPath (Join-Path $ControlDir "modality.stderr.log")
        if ($code -ne 0) { throw "S3 modality diagnostic exited with code $code" }
        Assert-JsonPass -Path $ModalityOutput
    }
    $completed.Add("modality")
    Write-WorkerState -Status "completed" -CurrentPhase $null -CompletedPhases @($completed) -ExitCode 0 -Message "S3 prediction and modality diagnostics completed"
    exit 0
} catch {
    Write-WorkerState -Status "failed" -CurrentPhase $null -CompletedPhases @($completed) -ExitCode 1 -Message $_.Exception.ToString()
    exit 1
}
