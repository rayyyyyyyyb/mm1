$ErrorActionPreference = "Stop"

$gitExe = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$pythonExe = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$candidate = "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0"
$control = "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0_verification"
$expectedCommit = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"

if (Test-Path -LiteralPath $control) {
    throw "Verification control directory already exists: $control"
}
New-Item -ItemType Directory -Path $control | Out-Null
$env:PATH = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd;" + $env:PATH
$env:PYTHONDONTWRITEBYTECODE = "1"

$headBefore = (& $gitExe -C $candidate rev-parse HEAD).Trim()
$dirtyBefore = @(& $gitExe -C $candidate status --short)
if ($headBefore -ne $expectedCommit -or $dirtyBefore.Count -ne 0) {
    throw "Candidate is not exact and clean before verification"
}

Push-Location $candidate
try {
    & $pythonExe -m compileall -q scripts src tests 1> (Join-Path $control "compileall.stdout.txt") 2> (Join-Path $control "compileall.stderr.txt")
    $compileExit = $LASTEXITCODE
    if ($compileExit -ne 0) {
        throw "compileall failed with exit $compileExit"
    }
    & $pythonExe -m pytest -q 1> (Join-Path $control "pytest.stdout.txt") 2> (Join-Path $control "pytest.stderr.txt")
    $pytestExit = $LASTEXITCODE
    if ($pytestExit -ne 0) {
        throw "pytest failed with exit $pytestExit"
    }
}
finally {
    Pop-Location
}

$headAfter = (& $gitExe -C $candidate rev-parse HEAD).Trim()
$dirtyAfter = @(& $gitExe -C $candidate status --short)
if ($headAfter -ne $expectedCommit -or $dirtyAfter.Count -ne 0) {
    throw "Candidate is not exact and clean after verification"
}

$receipt = [ordered]@{
    status = "PASS"
    commit_before = $headBefore
    commit_after = $headAfter
    dirty_before = $dirtyBefore.Count
    dirty_after = $dirtyAfter.Count
    compileall_exit = $compileExit
    pytest_exit = $pytestExit
    compileall_stdout_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $control "compileall.stdout.txt")).Hash.ToLowerInvariant()
    compileall_stderr_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $control "compileall.stderr.txt")).Hash.ToLowerInvariant()
    pytest_stdout_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $control "pytest.stdout.txt")).Hash.ToLowerInvariant()
    pytest_stderr_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $control "pytest.stderr.txt")).Hash.ToLowerInvariant()
    completed_utc = [DateTime]::UtcNow.ToString("o")
}
$receiptPath = Join-Path $control "verification_receipt.json"
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
$receipt | ConvertTo-Json -Depth 5
