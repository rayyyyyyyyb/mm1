param(
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$ExpectedCommit = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"
$ExpectedConfigSha = "26e3f21504d7ce3f9a5498b8c89073fc910db80cbdf058c4b6a397b8735518b6"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0"
$WorkerStatePath = Join-Path $ControlDir "worker_state.json"
$Config = "configs\diagnostics\recovery\ov_orthkd_s7_temporal_identity_seed42.yaml"
$RelativeOutput = "outputs\diagnostic\recovery_s7_temporal_identity_seed42"
$OutputDir = Join-Path $RepoRoot $RelativeOutput

$env:Path = "$(Split-Path -Parent $Git);$env:Path"
$env:HF_HUB_CACHE = Join-Path $RepoRoot "data\downloads\hf_cache"
$env:TORCH_HOME = "E:\OV-OrthKD-R3\student_shortcut_control\model_cache\torch"
$env:TOKENIZERS_PARALLELISM = "false"
$env:TIMM_USE_OLD_CACHE = "1"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"

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
        "test_predictions.npz",
        "diagnostic_checkpoints\step_000400.pt",
        "diagnostic_checkpoints\step_000800.pt",
        "diagnostic_checkpoints\step_001200.pt"
    )) {
        $requiredPath = Join-Path $OutputDir $requiredName
        if (
            -not (Test-Path -LiteralPath $requiredPath -PathType Leaf) -or
            (Get-Item -LiteralPath $requiredPath).Length -le 0
        ) {
            throw "Completed S7 output is missing or empty: $requiredName"
        }
    }
    $history = @(Get-Content -LiteralPath (Join-Path $OutputDir "history.jsonl") -Encoding UTF8)
    $diagnostics = @(Get-Content -LiteralPath (Join-Path $OutputDir "training_diagnostics.jsonl") -Encoding UTF8)
    if ($history.Count -ne 3 -or $diagnostics.Count -ne 3) {
        throw "Expected exactly three S7 history/diagnostic records, got $($history.Count)/$($diagnostics.Count)"
    }
    $historyRecords = @($history | ForEach-Object { $_ | ConvertFrom-Json })
    foreach ($line in $diagnostics) { $null = $line | ConvertFrom-Json }
    if (@($historyRecords.global_step) -join "," -ne "400,800,1200") {
        throw "Expected S7 history global steps 400,800,1200"
    }
    $behavior = Get-Content -LiteralPath (Join-Path $OutputDir "implementation_behavior.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($behavior.student.temporal_path_mode -ne "identity_passthrough") {
        throw "S7 runtime behavior did not record identity_passthrough"
    }
    $null = Get-Content -LiteralPath (Join-Path $OutputDir "final_metrics.json") -Raw -Encoding UTF8 | ConvertFrom-Json
}

$completed = New-Object System.Collections.Generic.List[string]

try {
    foreach ($required in @($RepoRoot, $Python, $Git, $ModulePath, (Join-Path $RepoRoot $Config))) {
        if (-not (Test-Path -LiteralPath $required)) { throw "Required S7 path is missing: $required" }
    }
    $head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
    $dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
    if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) {
        throw "S7 worker requires exact clean commit $ExpectedCommit; observed $head with $($dirty.Count) status lines"
    }
    $configPath = Join-Path $RepoRoot $Config
    $actualConfigSha = Get-NormalizedTextSha256 -Path $configPath
    if ($actualConfigSha -ne $ExpectedConfigSha) { throw "S7 config SHA256 mismatch: $actualConfigSha" }

    New-Item -ItemType Directory -Force -Path $ControlDir, $env:HF_HUB_CACHE, $env:TORCH_HOME | Out-Null
    Import-Module $ModulePath -Force
    Set-Location -LiteralPath $RepoRoot

    $finalMetrics = Join-Path $OutputDir "final_metrics.json"
    if (Test-Path -LiteralPath $finalMetrics -PathType Leaf) {
        if (-not $Resume) { throw "Fresh S7 run refuses a completed output" }
        Assert-CompletedOutput
    } else {
        $arguments = @("scripts\train_ov_orthkd.py", "--config", $Config, "--output-dir", $RelativeOutput)
        if (Test-Path -LiteralPath $OutputDir) {
            $existing = @(Get-ChildItem -LiteralPath $OutputDir -Force)
            if ($existing.Count -gt 0) {
                $lastCheckpoint = Join-Path $OutputDir "last.pt"
                if (-not $Resume -or -not (Test-Path -LiteralPath $lastCheckpoint -PathType Leaf)) {
                    throw "Nonempty incomplete S7 output requires -Resume and last.pt"
                }
                $arguments += @("--resume", "$RelativeOutput\last.pt")
            }
        }
        New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
        Write-WorkerState -Status "running" -CurrentPhase "s7_training" -CompletedPhases @() -ExitCode $null -Message "S7 temporal identity Student-only diagnostic training is running"
        $trainStdout = Join-Path $ControlDir "s7.stdout.log"
        $trainStderr = Join-Path $ControlDir "s7.stderr.log"
        $trainExit = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $arguments -WorkingDirectory $RepoRoot -StandardOutputPath $trainStdout -StandardErrorPath $trainStderr
        if ($trainExit -ne 0) { throw "S7 training exited with code $trainExit" }
        Assert-CompletedOutput
    }
    $completed.Add("s7_training")
    Write-WorkerState -Status "completed" -CurrentPhase $null -CompletedPhases @($completed) -ExitCode 0 -Message "S7 temporal identity diagnostic completed"
    exit 0
} catch {
    Write-WorkerState -Status "failed" -CurrentPhase $null -CompletedPhases @($completed) -ExitCode 1 -Message $_.Exception.ToString()
    exit 1
}
