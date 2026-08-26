param(
    [ValidateSet("Validate", "Start", "Resume", "RecoverPreTraining", "Status")]
    [string]$Action = "Status"
)

$ErrorActionPreference = "Stop"
$ExpectedCommit = "31b86c0d60c4bf2ed028edf1385ed5d2c9e89153"
$RepoRoot = "E:\OV-OrthKD-R3\formal-canonical-31b86c0"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$Config = "configs\ov_orthkd_mm26_repro_ready.yaml"
$RelativeOutput = "outputs\formal\mm26_canonical_seed42"
$OutputDir = Join-Path $RepoRoot $RelativeOutput
$ControlDir = "E:\OV-OrthKD-R3\formal_control\mm26_canonical_seed42"
$StatePath = Join-Path $ControlDir "launch_state.json"
$WorkerStatePath = Join-Path $ControlDir "worker_state.json"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerScript = "E:\OV-OrthKD-R3\formal_control\run_canonical_seed42_worker.ps1"
$StdoutPath = Join-Path $ControlDir "python.stdout.log"
$StderrPath = Join-Path $ControlDir "python.stderr.log"
$RuntimeEvaluatorSource = Join-Path $RepoRoot "proposed_method\ImageBind-main\utils\eval_metrics.py"
$ExpectedEvaluatorSha256 = "013949f6371dc11a93f4e5b1df448601b98cf5590e7651d103600f981a4ded19"
$ExpectedCacheSha256 = "6707900b5d4acb39752baeea11cd1e90d8d3394600b1fa3a6cc3984223860244"
$PreTrainingArchiveDir = Join-Path $ControlDir "pretraining_wrapper_failure_20260825T170502Z"

$env:Path = "$(Split-Path -Parent $Git);$env:Path"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:TOKENIZERS_PARALLELISM = "false"

function Get-GitState {
    if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) {
        throw "Formal worktree is missing: $RepoRoot"
    }
    $head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot resolve formal worktree HEAD"
    }
    $status = @(& $Git -C $RepoRoot status --porcelain --untracked-files=all)
    [ordered]@{
        head = $head
        status_lines = $status.Count
        clean = ($status.Count -eq 0)
    }
}

function Assert-FormalEnvironment {
    foreach ($required in @(
        $RepoRoot,
        $Python,
        $Git,
        (Join-Path $RepoRoot $Config),
        $ModulePath,
        $WorkerScript
    )) {
        if (-not (Test-Path -LiteralPath $required)) {
            throw "Required formal path is missing: $required"
        }
    }
    $gitState = Get-GitState
    if ($gitState.head -ne $ExpectedCommit) {
        throw "Wrong formal Git HEAD: $($gitState.head)"
    }
    if (-not $gitState.clean) {
        throw "Formal Git tree must be clean; status lines: $($gitState.status_lines)"
    }
    if (-not (Test-Path -LiteralPath $RuntimeEvaluatorSource -PathType Leaf)) {
        throw "Runtime evaluator compatibility path is missing: $RuntimeEvaluatorSource"
    }
    $evaluatorSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $RuntimeEvaluatorSource).Hash.ToLowerInvariant()
    if ($evaluatorSha256 -ne $ExpectedEvaluatorSha256) {
        throw "Runtime evaluator SHA256 mismatch: $evaluatorSha256"
    }
    return $gitState
}

function Save-PreTrainingFailureEvidence {
    if (Test-Path -LiteralPath $PreTrainingArchiveDir) {
        throw "Pre-training failure archive already exists; refusing to overwrite it: $PreTrainingArchiveDir"
    }
    New-Item -ItemType Directory -Path $PreTrainingArchiveDir | Out-Null
    foreach ($file in @(Get-ChildItem -LiteralPath $OutputDir -File -Force)) {
        Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $PreTrainingArchiveDir $file.Name)
    }
    foreach ($path in @($StatePath, $WorkerStatePath, $StdoutPath, $StderrPath)) {
        Copy-Item -LiteralPath $path -Destination (
            Join-Path $PreTrainingArchiveDir ("control_" + (Split-Path -Leaf $path))
        )
    }
    $manifest = @(
        Get-ChildItem -LiteralPath $PreTrainingArchiveDir -File -Force |
            Sort-Object Name |
            ForEach-Object {
                [ordered]@{
                    name = $_.Name
                    bytes = $_.Length
                    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
                }
            }
    )
    [ordered]@{
        schema_version = 1
        status = "preserved_pretraining_wrapper_failure"
        archived_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        optimizer_steps = 0
        source_output_dir = $OutputDir
        files = $manifest
    } | ConvertTo-Json -Depth 8 | Set-Content `
        -LiteralPath (Join-Path $PreTrainingArchiveDir "archive_manifest.json") `
        -Encoding UTF8
}

function Read-LaunchState {
    if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
        return $null
    }
    Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Read-WorkerState {
    if (-not (Test-Path -LiteralPath $WorkerStatePath -PathType Leaf)) {
        return $null
    }
    Get-Content -LiteralPath $WorkerStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Write-LaunchState {
    param(
        [string]$Mode,
        [int]$ProcessId,
        [string]$Status
    )
    New-Item -ItemType Directory -Force -Path $ControlDir | Out-Null
    $payload = [ordered]@{
        schema_version = 1
        status = $Status
        mode = $Mode
        process_id = $ProcessId
        launched_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        git_commit = $ExpectedCommit
        repo_root = $RepoRoot
        config = $Config
        output_dir = $OutputDir
        command = if ($Mode -eq "resume") {
            "$Python scripts\train_ov_orthkd.py --config $Config --resume $RelativeOutput\last.pt --output-dir $RelativeOutput"
        } else {
            "$Python scripts\train_ov_orthkd.py --config $Config --output-dir $RelativeOutput"
        }
        stdout = $StdoutPath
        stderr = $StderrPath
    }
    $temporary = "$StatePath.tmp.$PID"
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $StatePath -Force
}

function Get-FormalStatus {
    Import-Module $ModulePath -Force
    $gitState = Get-GitState
    $state = Read-LaunchState
    $workerState = Read-WorkerState
    $processId = if ($null -ne $state) { [int]$state.process_id } else { 0 }
    $process = if ($processId -gt 0) {
        Get-Process -Id $processId -ErrorAction SilentlyContinue
    } else {
        $null
    }
    $historyPath = Join-Path $OutputDir "history.jsonl"
    $history = @(Read-JsonLinesFile -Path $historyPath)
    $lastHistory = if ($history.Count -gt 0) {
        $history[-1]
    } else {
        $null
    }
    $finalMetrics = Test-Path -LiteralPath (Join-Path $OutputDir "final_metrics.json") -PathType Leaf
    $derivedStatus = if ($null -eq $state) {
        "not_started"
    } elseif ($null -ne $process) {
        "running"
    } elseif ($finalMetrics -and $null -ne $workerState -and $workerState.status -eq "completed") {
        "completed"
    } else {
        "interrupted_or_failed"
    }
    [ordered]@{
        schema_version = 1
        status = $derivedStatus
        git = $gitState
        launch = $state
        worker = $workerState
        process_alive = ($null -ne $process)
        epoch_records = $history.Count
        last_epoch = if ($null -ne $lastHistory) { $lastHistory.epoch } else { $null }
        global_step = if ($null -ne $lastHistory) { $lastHistory.global_step } else { 0 }
        best_checkpoint_exists = Test-Path -LiteralPath (Join-Path $OutputDir "best.pt") -PathType Leaf
        last_checkpoint_exists = Test-Path -LiteralPath (Join-Path $OutputDir "last.pt") -PathType Leaf
        final_metrics_exists = $finalMetrics
        incompatible_marker_exists = Test-Path -LiteralPath (Join-Path $OutputDir "INCOMPATIBLE_RESUME.txt") -PathType Leaf
        output_dir = $OutputDir
    }
}

if ($Action -eq "Validate") {
    $gitState = Assert-FormalEnvironment
    [ordered]@{
        status = "validated"
        git = $gitState
        python = $Python
        config = Join-Path $RepoRoot $Config
        output_dir = $OutputDir
    } | ConvertTo-Json -Depth 5
    exit 0
}

if ($Action -eq "Status") {
    Get-FormalStatus | ConvertTo-Json -Depth 8
    exit 0
}

$gitState = Assert-FormalEnvironment
$current = Get-FormalStatus
if ($current.process_alive) {
    throw "Canonical training process is already running with PID $($current.launch.process_id)"
}
if ($current.final_metrics_exists) {
    throw "Canonical final_metrics.json already exists; refusing to overwrite the first formal result"
}

if ($Action -eq "Start") {
    if (Test-Path -LiteralPath $OutputDir) {
        $existing = @(Get-ChildItem -LiteralPath $OutputDir -Force)
        if ($existing.Count -ne 0) {
            throw "Canonical output directory is not empty; use Resume only after diagnosis: $OutputDir"
        }
    }
    $mode = "start"
} elseif ($Action -eq "Resume") {
    $lastCheckpoint = Join-Path $OutputDir "last.pt"
    if (-not (Test-Path -LiteralPath $lastCheckpoint -PathType Leaf)) {
        throw "Resume requires the canonical last.pt checkpoint: $lastCheckpoint"
    }
    if (Test-Path -LiteralPath (Join-Path $OutputDir "INCOMPATIBLE_RESUME.txt") -PathType Leaf) {
        throw "Incompatible resume marker exists; formal resume is forbidden"
    }
    $mode = "resume"
} else {
    Import-Module $ModulePath -Force
    Assert-CanonicalPreTrainingRecovery `
        -OutputDirectory $OutputDir `
        -WorkerStatePath $WorkerStatePath `
        -StandardOutputPath $StdoutPath `
        -StandardErrorPath $StderrPath `
        -ExpectedCacheHash $ExpectedCacheSha256 | Out-Null
    Save-PreTrainingFailureEvidence
    $mode = "start"
}

New-Item -ItemType Directory -Force -Path $ControlDir, $OutputDir | Out-Null
Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript `
    -ScriptPath $WorkerScript `
    -ArgumentList @("-Mode", $mode)
$processId = [int]$created.ProcessId
Start-Sleep -Seconds 3
if (-not (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
    $workerState = Read-WorkerState
    throw "Canonical worker exited during the three-second launch check: $($workerState.message)"
}
Write-LaunchState -Mode $mode -ProcessId $processId -Status "running"
Get-FormalStatus | ConvertTo-Json -Depth 8
