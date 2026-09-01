$ErrorActionPreference = "Stop"

$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Candidate = "E:\OV-OrthKD-R3\student-shortcut-s9-b8ea747"
$Control = "E:\OV-OrthKD-R3\student_shortcut_control\s9_b8ea747_verification"
$ExpectedCommit = "b8ea747dd792c939251152ead734d1826c26980d"

if (Test-Path -LiteralPath $Control) {
    throw "S9 verification control directory already exists: $Control"
}
New-Item -ItemType Directory -Path $Control | Out-Null
$env:PATH = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd;" + $env:PATH
$env:PYTHONDONTWRITEBYTECODE = "1"

$HeadBefore = (& $Git -C $Candidate rev-parse HEAD).Trim()
$DirtyBefore = @(& $Git -C $Candidate status --porcelain=v1 --untracked-files=all)
if ($HeadBefore -ne $ExpectedCommit -or $DirtyBefore.Count -ne 0) {
    throw "S9 candidate is not exact and clean before verification"
}

Push-Location $Candidate
try {
    & $Python -m compileall -q scripts src tests 1> (Join-Path $Control "compileall.stdout.txt") 2> (Join-Path $Control "compileall.stderr.txt")
    $CompileExit = $LASTEXITCODE
    if ($CompileExit -ne 0) { throw "S9 compileall failed with exit $CompileExit" }
    & $Python -m pytest -q -p no:cacheprovider 1> (Join-Path $Control "pytest.stdout.txt") 2> (Join-Path $Control "pytest.stderr.txt")
    $PytestExit = $LASTEXITCODE
    if ($PytestExit -ne 0) { throw "S9 pytest failed with exit $PytestExit" }
    & $Python scripts\audit_s8_results.py --help 1> (Join-Path $Control "training_audit_help.txt") 2> (Join-Path $Control "training_audit_help.stderr.txt")
    $TrainingHelpExit = $LASTEXITCODE
    & $Python scripts\audit_s9_posthoc.py --help 1> (Join-Path $Control "posthoc_audit_help.txt") 2> (Join-Path $Control "posthoc_audit_help.stderr.txt")
    $PosthocHelpExit = $LASTEXITCODE
    & $Python scripts\diagnose_s7_zero_training.py --help 1> (Join-Path $Control "ae_help.txt") 2> (Join-Path $Control "ae_help.stderr.txt")
    $AeHelpExit = $LASTEXITCODE
    if ($TrainingHelpExit -ne 0 -or $PosthocHelpExit -ne 0 -or $AeHelpExit -ne 0) {
        throw "One or more locked S9 CLI help checks failed"
    }
}
finally {
    Pop-Location
}

$HeadAfter = (& $Git -C $Candidate rev-parse HEAD).Trim()
$DirtyAfter = @(& $Git -C $Candidate status --porcelain=v1 --untracked-files=all)
if ($HeadAfter -ne $ExpectedCommit -or $DirtyAfter.Count -ne 0) {
    throw "S9 candidate is not exact and clean after verification"
}
$Receipt = [ordered]@{
    schema_version = 1
    status = "PASS"
    commit_before = $HeadBefore
    commit_after = $HeadAfter
    dirty_before = $DirtyBefore.Count
    dirty_after = $DirtyAfter.Count
    compileall_exit = $CompileExit
    pytest_exit = $PytestExit
    training_audit_help_exit = $TrainingHelpExit
    posthoc_audit_help_exit = $PosthocHelpExit
    ae_help_exit = $AeHelpExit
    compileall_stdout_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Control "compileall.stdout.txt")).Hash.ToLowerInvariant()
    compileall_stderr_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Control "compileall.stderr.txt")).Hash.ToLowerInvariant()
    pytest_stdout_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Control "pytest.stdout.txt")).Hash.ToLowerInvariant()
    pytest_stderr_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Control "pytest.stderr.txt")).Hash.ToLowerInvariant()
    completed_utc = [DateTime]::UtcNow.ToString("o")
}
$ReceiptPath = Join-Path $Control "verification_receipt.json"
$Receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
$Receipt | ConvertTo-Json -Depth 5
