$ErrorActionPreference = "Stop"

$repo = "E:\OV-OrthKD-R3\student-shortcut-s4-74d211d"
$python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$test = Join-Path $repo "tests\test_s7_temporal_identity.py"

Set-Location $repo
& $python -m pytest -q $test
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    exit $exitCode
}
