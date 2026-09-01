$ErrorActionPreference = "Stop"

$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Candidate = "E:\OV-OrthKD-R3\zero-training-c181ffb"
$Control = "E:\OV-OrthKD-R3\zero_training_control\c181ffb\verification"
$ExpectedCommit = "c181ffb3297ff480a0d01186c626acce7c66afff"

foreach ($required in @($Git, $Python, $Candidate)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required verification path is missing: $required"
    }
}
if (Test-Path -LiteralPath $Control) {
    throw "Verification output already exists: $Control"
}
New-Item -ItemType Directory -Path $Control | Out-Null
$env:PATH = "$(Split-Path -Parent $Git);$env:PATH"
$env:PYTHONDONTWRITEBYTECODE = "1"

$headBefore = (& $Git -C $Candidate rev-parse HEAD).Trim()
$dirtyBefore = @(& $Git -C $Candidate status --porcelain=v1 --untracked-files=all)
if ($headBefore -ne $ExpectedCommit -or $dirtyBefore.Count -ne 0) {
    throw "Candidate is not exact and clean before verification"
}

Push-Location $Candidate
try {
    & $Python -m compileall -q scripts src tests 1> (Join-Path $Control "compileall.stdout.txt") 2> (Join-Path $Control "compileall.stderr.txt")
    $compileExit = $LASTEXITCODE
    if ($compileExit -ne 0) { throw "compileall failed with exit $compileExit" }
    & $Python -m pytest -q -p no:cacheprovider 1> (Join-Path $Control "pytest.stdout.txt") 2> (Join-Path $Control "pytest.stderr.txt")
    $pytestExit = $LASTEXITCODE
    if ($pytestExit -ne 0) { throw "pytest failed with exit $pytestExit" }
}
finally {
    Pop-Location
}

$headAfter = (& $Git -C $Candidate rev-parse HEAD).Trim()
$dirtyAfter = @(& $Git -C $Candidate status --porcelain=v1 --untracked-files=all)
if ($headAfter -ne $ExpectedCommit -or $dirtyAfter.Count -ne 0) {
    throw "Candidate is not exact and clean after verification"
}
$receipt = [ordered]@{
    schema_version = 1
    status = "PASS"
    commit_before = $headBefore
    commit_after = $headAfter
    dirty_before = $dirtyBefore.Count
    dirty_after = $dirtyAfter.Count
    compileall_exit = $compileExit
    pytest_exit = $pytestExit
    compileall_stdout_sha256 = (Get-FileHash -LiteralPath (Join-Path $Control "compileall.stdout.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
    compileall_stderr_sha256 = (Get-FileHash -LiteralPath (Join-Path $Control "compileall.stderr.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
    pytest_stdout_sha256 = (Get-FileHash -LiteralPath (Join-Path $Control "pytest.stdout.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
    pytest_stderr_sha256 = (Get-FileHash -LiteralPath (Join-Path $Control "pytest.stderr.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
    completed_utc = [DateTime]::UtcNow.ToString("o")
}
$receiptPath = Join-Path $Control "verification_receipt.json"
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
$receipt | ConvertTo-Json -Depth 5
