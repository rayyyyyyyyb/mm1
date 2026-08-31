param(
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$ExpectedCommit = "74d211d34ace74ce3b74ea082a7dfd0379b251fb"
$ExpectedConfigSha = "5b81218b55907a5dfb0419e62eff2128f0d08ce9301c97c081237f8c8f599b33"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s4-74d211d"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s4_74d211d"
$WorkerStatePath = Join-Path $ControlDir "worker_state.json"
$Config = "configs\diagnostics\recovery\ov_orthkd_s4_no_augment_seed42.yaml"
$RelativeOutput = "outputs\diagnostic\recovery_s4_no_augment_seed42"
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
        "test_predictions.npz"
    )) {
        $requiredPath = Join-Path $OutputDir $requiredName
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf) -or
            (Get-Item -LiteralPath $requiredPath).Length -le 0) {
            throw "Completed S4 output is missing or empty: $requiredName"
        }
    }
    $history = @(Get-Content -LiteralPath (Join-Path $OutputDir "history.jsonl") -Encoding UTF8)
    $diagnostics = @(Get-Content -LiteralPath (Join-Path $OutputDir "training_diagnostics.jsonl") -Encoding UTF8)
    if ($history.Count -ne 3 -or $diagnostics.Count -ne 3) {
        throw "Expected exactly three S4 history/diagnostic records, got $($history.Count)/$($diagnostics.Count)"
    }
    foreach ($line in @($history + $diagnostics)) { $null = $line | ConvertFrom-Json }
    $lastHistory = $history[-1] | ConvertFrom-Json
    if ([int]$lastHistory.global_step -ne 1200) {
        throw "Expected S4 final global_step 1200, got $($lastHistory.global_step)"
    }
    $null = Get-Content -LiteralPath (Join-Path $OutputDir "final_metrics.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $null = Get-Content -LiteralPath (Join-Path $OutputDir "implementation_behavior.json") -Raw -Encoding UTF8 | ConvertFrom-Json
}

$completed = New-Object System.Collections.Generic.List[string]

try {
    foreach ($required in @($RepoRoot, $Python, $Git, $ModulePath, (Join-Path $RepoRoot $Config))) {
        if (-not (Test-Path -LiteralPath $required)) { throw "Required S4 path is missing: $required" }
    }
    $head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
    $dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
    if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) {
        throw "S4 worker requires exact clean commit $ExpectedCommit; observed $head with $($dirty.Count) status lines"
    }
    $configPath = Join-Path $RepoRoot $Config
    $actualConfigSha = Get-NormalizedTextSha256 -Path $configPath
    if ($actualConfigSha -ne $ExpectedConfigSha) { throw "S4 config SHA256 mismatch: $actualConfigSha" }

    New-Item -ItemType Directory -Force -Path $ControlDir, $env:HF_HUB_CACHE, $env:TORCH_HOME | Out-Null
    Import-Module $ModulePath -Force
    Set-Location -LiteralPath $RepoRoot

    $finalMetrics = Join-Path $OutputDir "final_metrics.json"
    if (Test-Path -LiteralPath $finalMetrics -PathType Leaf) {
        if (-not $Resume) { throw "Fresh S4 run refuses a completed output" }
        Assert-CompletedOutput
    } else {
        $arguments = @("scripts\train_ov_orthkd.py", "--config", $Config, "--output-dir", $RelativeOutput)
        if (Test-Path -LiteralPath $OutputDir) {
            $existing = @(Get-ChildItem -LiteralPath $OutputDir -Force)
            if ($existing.Count -gt 0) {
                $lastCheckpoint = Join-Path $OutputDir "last.pt"
                if (-not $Resume -or -not (Test-Path -LiteralPath $lastCheckpoint -PathType Leaf)) {
                    throw "Nonempty incomplete S4 output requires -Resume and last.pt"
                }
                $arguments += @("--resume", "$RelativeOutput\last.pt")
            }
        }
        New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
        Write-WorkerState -Status "running" -CurrentPhase "s4_training" -CompletedPhases @() -ExitCode $null -Message "S4 no-augmentation Student-only diagnostic training is running"
        $trainStdout = Join-Path $ControlDir "s4.stdout.log"
        $trainStderr = Join-Path $ControlDir "s4.stderr.log"
        $trainExit = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $arguments -WorkingDirectory $RepoRoot -StandardOutputPath $trainStdout -StandardErrorPath $trainStderr
        if ($trainExit -ne 0) { throw "S4 training exited with code $trainExit" }
        Assert-CompletedOutput
    }
    $completed.Add("s4_training")
    Write-WorkerState -Status "completed" -CurrentPhase $null -CompletedPhases @($completed) -ExitCode 0 -Message "S4 no-augmentation diagnostic completed"
    exit 0
} catch {
    Write-WorkerState -Status "failed" -CurrentPhase $null -CompletedPhases @($completed) -ExitCode 1 -Message $_.Exception.ToString()
    exit 1
}
