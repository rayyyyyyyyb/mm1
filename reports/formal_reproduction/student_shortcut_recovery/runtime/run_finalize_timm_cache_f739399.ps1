$ErrorActionPreference = "Stop"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Script = "E:\OV-OrthKD-R3\student_shortcut_control\finalize_timm_cache_f739399.py"
$ExpectedScriptSha = "19c8344693ce826d04520fbdfc3063a66cfed2cebe8d56fa3ee7f9db49638226"
$CacheDir = "E:\OV-OrthKD-R3\student_shortcut_control\model_cache\torch\hub\checkpoints"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\timm_direct_f739399"
$RangeControl = "E:\OV-OrthKD-R3\student_shortcut_control\audio_ranges_f739399"
$RangeStatePath = Join-Path $RangeControl "worker_state.json"
$AudioReceiptPath = Join-Path $RangeControl "download_receipt.json"
$OfficialReceiptPath = Join-Path $ControlDir "official_cache_receipt.json"

if ((Get-FileHash -LiteralPath $Script -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedScriptSha) {
    throw "Cache finalizer SHA mismatch"
}
if (Test-Path -LiteralPath $OfficialReceiptPath -PathType Leaf) {
    throw "Fresh cache finalization refuses an existing official receipt"
}
$rangeState = Get-Content -LiteralPath $RangeStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
$audioReceipt = Get-Content -LiteralPath $AudioReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($rangeState.status -ne "completed" -or [int]$rangeState.exit_code -ne 0 -or
    $audioReceipt.status -ne "PASS") {
    throw "Parallel audio range download has not passed"
}
$matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*download_audio_ranges_f739399.py*"
})
if ($matching.Count -ne 0) { throw "Audio range downloader still has a live matching process" }

$stdout = Join-Path $ControlDir "cache_finalizer.stdout.log"
$stderr = Join-Path $ControlDir "cache_finalizer.stderr.log"
& $Python $Script --cache-dir $CacheDir --control-dir $ControlDir --audio-receipt $AudioReceiptPath 1> $stdout 2> $stderr
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) { throw "Cache finalizer exited with code $exitCode" }
$receipt = Get-Content -LiteralPath $OfficialReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($receipt.status -ne "PASS") { throw "Official cache receipt is not PASS" }
[ordered]@{
    schema_version = 1
    status = "PASS"
    utc = [DateTime]::UtcNow.ToString("o")
    finalizer_sha256 = $ExpectedScriptSha
    finalizer_exit = $exitCode
    official_receipt_path = $OfficialReceiptPath
    official_receipt_sha256 = (Get-FileHash -LiteralPath $OfficialReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
    assets = $receipt.assets
    stderr_bytes = (Get-Item -LiteralPath $stderr).Length
} | ConvertTo-Json -Depth 7
