$ErrorActionPreference = "Stop"

$RepoRoot = "E:\OV-OrthKD-R3\d2-e0-1-d7b29ca\repo"
$ControlRoot = "E:\OV-OrthKD-R3\d2_zero_training_gate_20260910"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$ResultPath = Join-Path $ControlRoot "d2_zero_training_gate.json"
$StdoutPath = Join-Path $ControlRoot "stdout.log"
$StderrPath = Join-Path $ControlRoot "stderr.log"
$StatePath = Join-Path $ControlRoot "state.json"
$ExitCodePath = Join-Path $ControlRoot "exit_code.txt"
$InputReceiptPath = Join-Path $ControlRoot "input_receipt.json"

$ConfigPath = Join-Path $RepoRoot "configs\diagnostics\recovery\ov_orthkd_visual_only_c2_visual_pretrained_probe.yaml"
$LockPath = Join-Path $RepoRoot "configs\locks\diagnostics\convnextv2_tiny_pretrained_asset.yaml"
$ProbeScriptPath = Join-Path $RepoRoot "scripts\audit_pretrained_representations.py"
$CheckpointPath = "E:\OV-OrthKD-R3\visual_sum_control_9e7a630\diagnostic\phase_c2_static_positive_lr_clip_800\best.pt"
$TrainManifestPath = "E:\OV-OrthKD-R3\repo\data\ov_ave\exported\train.jsonl"
$ValidationManifestPath = "E:\OV-OrthKD-R3\repo\data\ov_ave\exported\val.jsonl"
$AssetRoot = Join-Path $RepoRoot "tmp\d2_pretrained_asset\b1dd46230e80bf4cc3fa0c3c905db2c3ec53a817"
$AssetConfigPath = Join-Path $AssetRoot "config.json"
$AssetWeightsPath = Join-Path $AssetRoot "model.safetensors"

function Write-State {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][string]$Message,
        [AllowNull()][object]$ExitCode
    )

    $payload = [ordered]@{
        status = $Status
        message = $Message
        pid = $PID
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
        exit_code = $ExitCode
        result_path = $ResultPath
    }
    $temporaryPath = "$StatePath.tmp"
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -LiteralPath $temporaryPath -Destination $StatePath -Force
}

function Get-FileReceipt {
    param([Parameter(Mandatory = $true)][string]$Path)

    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        path = $item.FullName
        size_bytes = $item.Length
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

if (-not (Test-Path -LiteralPath $ControlRoot -PathType Container)) {
    throw "Control root is missing: $ControlRoot"
}
if (Test-Path -LiteralPath $ResultPath) {
    throw "Refusing to overwrite an existing scientific result: $ResultPath"
}
if (Test-Path -LiteralPath $ExitCodePath) {
    throw "Refusing to reuse a completed control root: $ExitCodePath"
}
if ($env:COMPUTERNAME -ne "DESKTOP-LPN6MT3") {
    throw "Wrong target host: $env:COMPUTERNAME"
}
$GpuName = (& nvidia-smi --query-gpu=name --format=csv,noheader,nounits | Select-Object -First 1).Trim()
if ($GpuName -notmatch "RTX 5090") {
    throw "Wrong target GPU: $GpuName"
}

$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:TIMM_USE_OLD_CACHE = "1"
$env:PYTHONUTF8 = "1"
$env:CUDA_VISIBLE_DEVICES = "0"

$inputReceipt = [ordered]@{
    schema_version = 1
    status = "INPUTS_LOCKED"
    host = $env:COMPUTERNAME
    gpu = $GpuName
    seed = 42
    task_segments = 10
    sample_count_per_split = 256
    evaluation_split = "validation"
    test_manifest = $null
    offline_only = $true
    optimizer_constructed = $false
    backward_or_update = $false
    model_checkpoint_write = $false
    d2_800_step = $false
    d3 = $false
    formal_full = $false
    files = [ordered]@{
        probe_script = Get-FileReceipt -Path $ProbeScriptPath
        d2_config = Get-FileReceipt -Path $ConfigPath
        asset_lock = Get-FileReceipt -Path $LockPath
        c2_checkpoint = Get-FileReceipt -Path $CheckpointPath
        train_manifest = Get-FileReceipt -Path $TrainManifestPath
        validation_manifest = Get-FileReceipt -Path $ValidationManifestPath
        asset_config = Get-FileReceipt -Path $AssetConfigPath
        asset_weights = Get-FileReceipt -Path $AssetWeightsPath
    }
}
$inputReceipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $InputReceiptPath -Encoding UTF8

Set-Location -LiteralPath $RepoRoot
Write-State -Status "running" -Message "D2 validation-only zero-training QP/VQP gate" -ExitCode $null
$processExitCode = 1
try {
    $arguments = @(
        "scripts\audit_pretrained_representations.py",
        "--config", "configs\diagnostics\recovery\ov_orthkd_visual_only_c2_visual_pretrained_probe.yaml",
        "--checkpoint", $CheckpointPath,
        "--train-manifest", $TrainManifestPath,
        "--validation-manifest", $ValidationManifestPath,
        "--output", $ResultPath,
        "--sample-count", "256",
        "--seed", "42"
    )
    & $Python @arguments 1> $StdoutPath 2> $StderrPath
    $processExitCode = $LASTEXITCODE
    if ($processExitCode -ne 0) {
        throw "Probe exited with code $processExitCode"
    }
    if (-not (Test-Path -LiteralPath $ResultPath -PathType Leaf)) {
        throw "Probe returned zero without a result JSON"
    }
    Write-State -Status "completed" -Message "D2 zero-training gate completed; scientific result is in JSON" -ExitCode $processExitCode
}
catch {
    if ($processExitCode -eq 0) {
        $processExitCode = 1
    }
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $ControlRoot "failure.txt") -Encoding UTF8
    Write-State -Status "failed" -Message $_.Exception.Message -ExitCode $processExitCode
}
finally {
    Set-Content -LiteralPath $ExitCodePath -Value ([string]$processExitCode) -Encoding ASCII
}

exit $processExitCode
