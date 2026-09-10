$ErrorActionPreference = "Stop"

$testRoot = "E:\OV-OrthKD-R3\d2-gate-test-c0dca35"
$repo = Join-Path $testRoot "repo"
$verification = Join-Path $testRoot "verification"
$python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$git = "E:\OV-OrthKD-R0\env\Git\cmd\git.exe"
$archive = "E:\OV-OrthKD-R3\d2_gate_candidate_c0dca35.zip"
$stdout = Join-Path $verification "pytest_full.stdout.log"
$stderr = Join-Path $verification "pytest_full.stderr.log"
$statePath = Join-Path $verification "pytest_full.state.json"
$receiptPath = Join-Path $verification "pytest_full.receipt.json"
$exitPath = Join-Path $verification "pytest_full.exit.txt"

foreach ($file in @($python, $git, $archive)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Required file is missing: $file"
    }
}
if (-not (Test-Path -LiteralPath $repo -PathType Container)) {
    throw "Candidate repository is missing: $repo"
}
New-Item -ItemType Directory -Path $verification -Force | Out-Null

$statusBefore = @(& $git -C $repo status --short)
if ($LASTEXITCODE -ne 0 -or $statusBefore.Count -ne 0) {
    throw "Candidate worktree is not clean before pytest: $($statusBefore -join '; ')"
}

$started = (Get-Date).ToUniversalTime()
$runningState = [ordered]@{
    schema_version = 1
    status = "RUNNING"
    started_at = $started.ToString("o")
    hostname = $env:COMPUTERNAME
    process_id = $PID
    candidate_archive_sha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    command = "$python -m pytest -q"
}
$runningState | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding UTF8

$oldPythonPath = $env:PYTHONPATH
$oldPythonEncoding = $env:PYTHONIOENCODING
$oldPath = $env:PATH
$env:PYTHONPATH = $repo
$env:PYTHONIOENCODING = "utf-8"
$env:PATH = "$(Split-Path -Parent $git);$oldPath"
Push-Location $repo
try {
    & $python -m pytest -q 1> $stdout 2> $stderr
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    $env:PYTHONPATH = $oldPythonPath
    $env:PYTHONIOENCODING = $oldPythonEncoding
    $env:PATH = $oldPath
}
$completed = (Get-Date).ToUniversalTime()
$statusAfter = @(& $git -C $repo status --short)
$receipt = [ordered]@{
    schema_version = 1
    status = if ($exitCode -eq 0) { "PASS" } else { "FAIL" }
    started_at = $started.ToString("o")
    completed_at = $completed.ToString("o")
    elapsed_seconds = [math]::Round(($completed - $started).TotalSeconds, 3)
    hostname = $env:COMPUTERNAME
    process_id = $PID
    candidate_archive_sha256 = $runningState.candidate_archive_sha256
    command = $runningState.command
    exit_code = $exitCode
    stdout_bytes = (Get-Item -LiteralPath $stdout).Length
    stdout_sha256 = (Get-FileHash -LiteralPath $stdout -Algorithm SHA256).Hash.ToLowerInvariant()
    stderr_bytes = (Get-Item -LiteralPath $stderr).Length
    stderr_sha256 = (Get-FileHash -LiteralPath $stderr -Algorithm SHA256).Hash.ToLowerInvariant()
    git_status_after = $statusAfter
}
$receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
[string]$exitCode | Set-Content -LiteralPath $exitPath -Encoding ASCII
$finalState = [ordered]@{
    schema_version = 1
    status = $receipt.status
    started_at = $receipt.started_at
    completed_at = $receipt.completed_at
    elapsed_seconds = $receipt.elapsed_seconds
    exit_code = $receipt.exit_code
    receipt = $receiptPath
}
$finalState | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding UTF8
exit $exitCode
