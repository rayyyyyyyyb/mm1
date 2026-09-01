$ErrorActionPreference = "Stop"
$ExpectedCommit = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$ControlRoot = "E:\OV-OrthKD-R3\student_shortcut_control"
$TrainingControl = Join-Path $ControlRoot "s7_a7f0dc0"
$PosthocControl = Join-Path $ControlRoot "s7_posthoc_a7f0dc0"
$PosthocResults = Join-Path $ControlRoot "s7_posthoc_a7f0dc0_results"
$expectedFiles = [ordered]@{
    "audit_s7_training.py" = "7c768b7039e9740949ae8214a9a860fa43e14dfe4e4a5318a7a2065303e530c3"
    "diagnose_s7_checkpoint_trajectory.py" = "efd36105f131dd4096c3ee35dfc1cba19bc175975f1931e7c9d1f749ffe5425a"
    "run_s7_posthoc_worker_a7f0dc0.ps1" = "31414e2b7e8b7437d4332678a99ce6ce446063e9f0eb4067bfc24a48f36728be"
    "launch_s7_posthoc_a7f0dc0.ps1" = "d20d5e0047f742008dcfc64d23d157158eb4c614779a3fad633d83229fa802c5"
    "query_s7_posthoc_a7f0dc0.ps1" = "681331577bbeca44cf2f7e9b1376be860c4043226df7c3f0ef7975d67b885691"
    "resume_s7_posthoc_a7f0dc0.ps1" = "7aa943cec85e1573a41434b57eb907398b424c8f5f8b8cf8a310e727e87a6463"
}

$receipts = @()
foreach ($entry in $expectedFiles.GetEnumerator()) {
    $path = Join-Path $ControlRoot $entry.Key
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing uploaded S7 posthoc file: $path" }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.Value) { throw "Uploaded S7 posthoc SHA256 mismatch: $path" }
    $receipts += [ordered]@{ name=$entry.Key; bytes=(Get-Item -LiteralPath $path).Length; sha256=$actual }
}

foreach ($name in @(
    "run_s7_posthoc_worker_a7f0dc0.ps1",
    "launch_s7_posthoc_a7f0dc0.ps1",
    "query_s7_posthoc_a7f0dc0.ps1",
    "resume_s7_posthoc_a7f0dc0.ps1"
)) {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $ControlRoot $name),
        [ref]$tokens,
        [ref]$errors
    ) | Out-Null
    if ($errors.Count -ne 0) { throw "Uploaded PowerShell parser errors in $name" }
}
$env:PYTHONDONTWRITEBYTECODE = "1"
foreach ($name in @("audit_s7_training.py", "diagnose_s7_checkpoint_trajectory.py")) {
    $null = @(& $Python (Join-Path $ControlRoot $name) --help)
    if ($LASTEXITCODE -ne 0) { throw "Uploaded S7 Python parse/import failed: $name" }
}

$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "S7 candidate is not exact and clean" }
if (Test-Path -LiteralPath $PosthocControl) { throw "S7 posthoc control already exists" }
if (Test-Path -LiteralPath $PosthocResults) { throw "S7 posthoc results already exist" }
$matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*run_s7_posthoc_worker_a7f0dc0.ps1*" -or
    $_.CommandLine -like "*diagnose_s7_checkpoint_trajectory.py*" -or
    $_.CommandLine -like "*audit_s7_training.py*"
})
if ($matching.Count -ne 0) { throw "Unexpected S7 posthoc processes already exist" }

$trainingState = Get-Content -LiteralPath (Join-Path $TrainingControl "worker_state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$status = if ($trainingState.status -eq "completed" -and [int]$trainingState.exit_code -eq 0) {
    "READY_TO_LAUNCH_S7_POSTHOC"
} elseif ($trainingState.status -eq "running" -and $trainingState.current_phase -eq "s7_training") {
    "WAITING_FOR_S7_TRAINING"
} else {
    throw "S7 training state is neither healthy-running nor completed"
}
[ordered]@{
    status = $status
    git_commit = $head
    dirty_count = $dirty.Count
    training_state = $trainingState
    uploaded_files = $receipts
    parser_errors = 0
    python_parse_import_exit = 0
    matching_posthoc_processes = $matching.Count
} | ConvertTo-Json -Depth 8
