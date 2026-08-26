param(
    [ValidateSet("start", "resume")]
    [string]$Mode
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
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerStatePath = Join-Path $ControlDir "worker_state.json"
$StdoutPath = Join-Path $ControlDir "python.stdout.log"
$StderrPath = Join-Path $ControlDir "python.stderr.log"

$env:Path = "$(Split-Path -Parent $Git);$env:Path"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:TOKENIZERS_PARALLELISM = "false"

function Write-WorkerState {
    param(
        [string]$Status,
        [Nullable[int]]$ExitCode,
        [string]$Message
    )
    New-Item -ItemType Directory -Force -Path $ControlDir | Out-Null
    $payload = [ordered]@{
        schema_version = 1
        status = $Status
        mode = $Mode
        worker_process_id = $PID
        updated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        git_commit = $ExpectedCommit
        output_dir = $OutputDir
        exit_code = $ExitCode
        message = $Message
    }
    $temporary = "$WorkerStatePath.tmp.$PID"
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $WorkerStatePath -Force
}

try {
    foreach ($required in @($RepoRoot, $Python, $Git, (Join-Path $RepoRoot $Config), $ModulePath)) {
        if (-not (Test-Path -LiteralPath $required)) {
            throw "Required formal worker path is missing: $required"
        }
    }
    $head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
    $status = @(& $Git -C $RepoRoot status --porcelain --untracked-files=all)
    if ($head -ne $ExpectedCommit) {
        throw "Wrong formal worker Git HEAD: $head"
    }
    if ($status.Count -ne 0) {
        throw "Formal worker Git tree must be clean; status lines: $($status.Count)"
    }

    $arguments = @(
        "scripts\train_ov_orthkd.py",
        "--config", $Config
    )
    if ($Mode -eq "resume") {
        $lastCheckpoint = Join-Path $OutputDir "last.pt"
        if (-not (Test-Path -LiteralPath $lastCheckpoint -PathType Leaf)) {
            throw "Formal resume checkpoint is missing: $lastCheckpoint"
        }
        $arguments += @("--resume", "$RelativeOutput\last.pt")
    }
    $arguments += @("--output-dir", $RelativeOutput)

    New-Item -ItemType Directory -Force -Path $ControlDir, $OutputDir | Out-Null
    Import-Module $ModulePath -Force
    Set-Location -LiteralPath $RepoRoot
    Write-WorkerState -Status "running" -ExitCode $null -Message "canonical Python process running"
    $code = Invoke-NativeProcessWithRedirect `
        -FilePath $Python `
        -ArgumentList $arguments `
        -WorkingDirectory $RepoRoot `
        -StandardOutputPath $StdoutPath `
        -StandardErrorPath $StderrPath
    $finalMetrics = Test-Path -LiteralPath (Join-Path $OutputDir "final_metrics.json") -PathType Leaf
    if ($code -eq 0 -and $finalMetrics) {
        Write-WorkerState -Status "completed" -ExitCode $code -Message "canonical training and evaluation completed"
        exit 0
    }
    Write-WorkerState -Status "failed" -ExitCode $code -Message "canonical Python exited without a complete final_metrics.json"
    exit $(if ($code -ne 0) { $code } else { 1 })
} catch {
    Write-WorkerState -Status "failed" -ExitCode 1 -Message $_.Exception.ToString()
    exit 1
}
