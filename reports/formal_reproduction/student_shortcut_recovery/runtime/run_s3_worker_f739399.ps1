param(
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$ExpectedCommit = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
$ExpectedConfigSha = "96b98047f0ae8404a1e1fb99d0cc4934e1ed87c858766d05a2d502eb362b39e5"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-a0aa4d7"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s3_a0aa4d7"
$WorkerStatePath = Join-Path $ControlDir "worker_state.json"
$ReceiptPath = Join-Path $ControlDir "pretrained_backbone_receipt.json"
$OfficialCacheReceiptPath = "E:\OV-OrthKD-R3\student_shortcut_control\timm_direct_f739399\official_cache_receipt.json"
$ExpectedCacheDir = "E:\OV-OrthKD-R3\student_shortcut_control\model_cache\torch\hub\checkpoints"
$Config = "configs\diagnostics\recovery\ov_orthkd_s3_pretrained_seed42.yaml"
$RelativeOutput = "outputs\diagnostic\recovery_s3_pretrained_seed42"
$OutputDir = Join-Path $RepoRoot $RelativeOutput

$env:Path = "$(Split-Path -Parent $Git);$env:Path"
$env:HF_HUB_CACHE = Join-Path $RepoRoot "data\downloads\hf_cache"
$env:TORCH_HOME = "E:\OV-OrthKD-R3\student_shortcut_control\model_cache\torch"
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

    New-Item -ItemType Directory -Force -Path $ControlDir | Out-Null
    $payload = [ordered]@{
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
    $temporary = "$WorkerStatePath.tmp.$PID"
    $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $WorkerStatePath -Force
}

function Assert-PretrainedReceipt {
    if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) {
        throw "Pretrained receipt is missing"
    }
    $receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($receipt.status -ne "PASS" -or $receipt.config.sha256 -ne $ExpectedConfigSha) {
        throw "Pretrained receipt status/config mismatch"
    }
    $roles = @($receipt.backbones.psobject.Properties.Name | Sort-Object)
    if (@(Compare-Object -ReferenceObject @("audio", "visual") -DifferenceObject $roles).Count -ne 0) {
        throw "Pretrained receipt does not contain exactly audio and visual"
    }
    foreach ($role in $roles) {
        $backbone = $receipt.backbones.$role
        if ($backbone.status -ne "PASS" -or -not [bool]$backbone.pretrained_requested -or
            [bool]$backbone.random_reference_requested -or -not [bool]$backbone.state_hashes_differ -or
            $backbone.pretrained_state_sha256 -eq $backbone.random_state_sha256) {
            throw "Invalid pretrained construction receipt for $role"
        }
    }
}

function Assert-OfficialCacheReceipt {
    if (-not (Test-Path -LiteralPath $OfficialCacheReceiptPath -PathType Leaf)) {
        throw "Official timm cache receipt is missing"
    }
    $receipt = Get-Content -LiteralPath $OfficialCacheReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($receipt.status -ne "PASS" -or
        $receipt.claim_level -ne "official_timm_1.0.28_pretrained_cfg_direct_url_cache_lock" -or
        $receipt.source_policy -ne "exact_url_from_locked_timm_1.0.28_pretrained_cfg" -or
        $receipt.cache_dir -ne $ExpectedCacheDir) {
        throw "Official timm cache receipt metadata mismatch"
    }
    $expected = [ordered]@{
        audio = [ordered]@{
            model = "tf_efficientnetv2_b2.in1k"
            url = "https://github.com/rwightman/pytorch-image-models/releases/download/v0.1-effv2-weights/tf_efficientnetv2_b2-847de54e.pth"
            target = Join-Path $ExpectedCacheDir "tf_efficientnetv2_b2-847de54e.pth"
            bytes = [int64]40795861
            sha256_prefix = "847de54e"
        }
        visual = [ordered]@{
            model = "convnextv2_tiny.fcmae_ft_in22k_in1k"
            url = "https://dl.fbaipublicfiles.com/convnext/convnextv2/im22k/convnextv2_tiny_22k_224_ema.pt"
            target = Join-Path $ExpectedCacheDir "convnextv2_tiny_22k_224_ema.pt"
            bytes = [int64]114604362
            sha256_prefix = $null
        }
    }
    $roles = @($receipt.assets.psobject.Properties.Name | Sort-Object)
    if (@(Compare-Object -ReferenceObject @("audio", "visual") -DifferenceObject $roles).Count -ne 0) {
        throw "Official timm cache receipt does not contain exactly audio and visual"
    }
    foreach ($role in $roles) {
        $actual = $receipt.assets.$role
        $wanted = $expected[$role]
        if ($actual.status -ne "PASS" -or $actual.model -ne $wanted.model -or
            $actual.url -ne $wanted.url -or $actual.target -ne $wanted.target -or
            [int64]$actual.bytes -ne $wanted.bytes -or
            [string]$actual.sha256 -notmatch "^[0-9a-f]{64}$") {
            throw "Official timm cache receipt asset metadata mismatch for $role"
        }
        if (-not (Test-Path -LiteralPath $actual.target -PathType Leaf) -or
            (Get-Item -LiteralPath $actual.target).Length -ne $wanted.bytes) {
            throw "Official timm cached file is missing or has wrong size for $role"
        }
        $fileSha = (Get-FileHash -LiteralPath $actual.target -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($fileSha -ne $actual.sha256 -or
            ($null -ne $wanted.sha256_prefix -and -not $fileSha.StartsWith($wanted.sha256_prefix))) {
            throw "Official timm cached file SHA256 mismatch for $role"
        }
    }
    $rangeReceiptPath = [string]$receipt.audio_range_receipt.path
    if (-not (Test-Path -LiteralPath $rangeReceiptPath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $rangeReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
            [string]$receipt.audio_range_receipt.sha256) {
        throw "Audio range receipt hash binding is invalid"
    }
}

function Assert-CompletedOutput {
    foreach ($requiredName in @(
        "best.pt",
        "last.pt",
        "final_metrics.json",
        "history.jsonl",
        "training_diagnostics.jsonl",
        "implementation_behavior.json",
        "resolved_config.yaml",
        "validation_predictions.npz",
        "test_predictions.npz"
    )) {
        $requiredPath = Join-Path $OutputDir $requiredName
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf) -or
            (Get-Item -LiteralPath $requiredPath).Length -le 0) {
            throw "Completed S3 output is missing or empty: $requiredName"
        }
    }
    $history = @(Get-Content -LiteralPath (Join-Path $OutputDir "history.jsonl") -Encoding UTF8)
    $diagnostics = @(
        Get-Content -LiteralPath (Join-Path $OutputDir "training_diagnostics.jsonl") -Encoding UTF8
    )
    if ($history.Count -ne 3 -or $diagnostics.Count -ne 3) {
        throw "Expected exactly three S3 history/diagnostic records, got $($history.Count)/$($diagnostics.Count)"
    }
    foreach ($line in @($history + $diagnostics)) {
        $null = $line | ConvertFrom-Json
    }
    $lastHistory = $history[-1] | ConvertFrom-Json
    if ([int]$lastHistory.global_step -ne 1200) {
        throw "Expected S3 final global_step 1200, got $($lastHistory.global_step)"
    }
    $null = Get-Content -LiteralPath (Join-Path $OutputDir "final_metrics.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $null = Get-Content -LiteralPath (Join-Path $OutputDir "implementation_behavior.json") -Raw -Encoding UTF8 | ConvertFrom-Json
}

$completed = New-Object System.Collections.Generic.List[string]

try {
    foreach ($required in @($RepoRoot, $Python, $Git, $ModulePath, (Join-Path $RepoRoot $Config))) {
        if (-not (Test-Path -LiteralPath $required)) {
            throw "Required S3 path is missing: $required"
        }
    }
    $head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
    $dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
    if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) {
        throw "S3 worker requires exact clean commit $ExpectedCommit; observed $head with $($dirty.Count) status lines"
    }
    $configPath = Join-Path $RepoRoot $Config
    $actualConfigSha = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualConfigSha -ne $ExpectedConfigSha) {
        throw "S3 config SHA256 mismatch: $actualConfigSha"
    }
    Assert-OfficialCacheReceipt

    New-Item -ItemType Directory -Force -Path $ControlDir, $env:HF_HUB_CACHE, $env:TORCH_HOME | Out-Null
    Import-Module $ModulePath -Force
    Set-Location -LiteralPath $RepoRoot

    if (Test-Path -LiteralPath $ReceiptPath -PathType Leaf) {
        if (-not $Resume) {
            throw "Fresh S3 run refuses a pre-existing pretrained receipt"
        }
        Assert-PretrainedReceipt
    } else {
        Write-WorkerState -Status "running" -CurrentPhase "pretrained_receipt" -CompletedPhases @() -ExitCode $null -Message "constructing pretrained and same-seed random backbones from the verified offline timm URL cache"
        $receiptStdout = Join-Path $ControlDir "pretrained_receipt.stdout.log"
        $receiptStderr = Join-Path $ControlDir "pretrained_receipt.stderr.log"
        $receiptArguments = @(
            "scripts\audit_pretrained_backbones.py",
            "--config", $Config,
            "--output", $ReceiptPath
        )
        $receiptExit = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $receiptArguments -WorkingDirectory $RepoRoot -StandardOutputPath $receiptStdout -StandardErrorPath $receiptStderr
        if ($receiptExit -ne 0) {
            throw "Pretrained backbone receipt exited with code $receiptExit"
        }
        Assert-PretrainedReceipt
    }
    $completed.Add("pretrained_receipt")

    $finalMetrics = Join-Path $OutputDir "final_metrics.json"
    if (Test-Path -LiteralPath $finalMetrics -PathType Leaf) {
        if (-not $Resume) {
            throw "Fresh S3 run refuses a completed output"
        }
        Assert-CompletedOutput
    } else {
        $arguments = @(
            "scripts\train_ov_orthkd.py",
            "--config", $Config,
            "--output-dir", $RelativeOutput
        )
        if (Test-Path -LiteralPath $OutputDir) {
            $existing = @(Get-ChildItem -LiteralPath $OutputDir -Force)
            if ($existing.Count -gt 0) {
                $lastCheckpoint = Join-Path $OutputDir "last.pt"
                if (-not $Resume -or -not (Test-Path -LiteralPath $lastCheckpoint -PathType Leaf)) {
                    throw "Nonempty incomplete S3 output requires -Resume and last.pt"
                }
                $arguments += @("--resume", "$RelativeOutput\last.pt")
            }
        }
        New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
        Write-WorkerState -Status "running" -CurrentPhase "s3_training" -CompletedPhases @($completed) -ExitCode $null -Message "S3 pretrained-only diagnostic training is running"
        $trainStdout = Join-Path $ControlDir "s3.stdout.log"
        $trainStderr = Join-Path $ControlDir "s3.stderr.log"
        $trainExit = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $arguments -WorkingDirectory $RepoRoot -StandardOutputPath $trainStdout -StandardErrorPath $trainStderr
        if ($trainExit -ne 0) {
            throw "S3 training exited with code $trainExit"
        }
        Assert-CompletedOutput
    }
    $completed.Add("s3_training")
    Write-WorkerState -Status "completed" -CurrentPhase $null -CompletedPhases @($completed) -ExitCode 0 -Message "pretrained receipt and S3 diagnostic completed"
    exit 0
} catch {
    Write-WorkerState -Status "failed" -CurrentPhase $null -CompletedPhases @($completed) -ExitCode 1 -Message $_.Exception.ToString()
    exit 1
}
