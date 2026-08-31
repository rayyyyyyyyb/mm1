$ErrorActionPreference = "Stop"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-a0aa4d7"
$ControlRoot = "E:\OV-OrthKD-R3\student_shortcut_control"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
$ExpectedConfigSha = "96b98047f0ae8404a1e1fb99d0cc4934e1ed87c858766d05a2d502eb362b39e5"
$Expected = [ordered]@{
    "run_s3_worker_f739399.ps1" = "6c6370b9ec811ee5f760595deb1d551681061d6a9700714278fbce926ef27306"
    "launch_s3_f739399.ps1" = "6d46dfd7f7b281d4d46b47f88b16b90db72e23b6fd4f8fa5895bd8d5823e1c46"
    "resume_s3_f739399.ps1" = "badf8baafbcb9c2fd94991ea49954cddf93377a94a5c315a6682580f425cfa7c"
    "query_s3_f739399.ps1" = "3445c6fad99041bec7e3ba94c30fc5212abf302515cc8920927de1da6fdc8cff"
    "audit_s3_training.py" = "bf2f1e26b57ff4ccccd248d8e0d292800b50019d94593190e231115fe5bb4f1f"
    "finalize_timm_cache_f739399.py" = "19c8344693ce826d04520fbdfc3063a66cfed2cebe8d56fa3ee7f9db49638226"
}

$receipts = @()
foreach ($entry in $Expected.GetEnumerator()) {
    $path = Join-Path $ControlRoot $entry.Key
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing uploaded S3 file: $path" }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.Value) { throw "Uploaded S3 SHA256 mismatch: $($entry.Key)" }
    $parseErrors = $null
    if ($path.EndsWith(".ps1")) {
        $tokens = $null
        $parseErrors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors) | Out-Null
        if ($parseErrors.Count -ne 0) { throw "Uploaded PowerShell parse failure: $($entry.Key)" }
    }
    $receipts += [ordered]@{
        name = $entry.Key
        bytes = (Get-Item -LiteralPath $path).Length
        sha256 = $actual
        parse_errors = if ($null -eq $parseErrors) { $null } else { $parseErrors.Count }
    }
}

$auditPath = Join-Path $ControlRoot "audit_s3_training.py"
$finalizerPath = Join-Path $ControlRoot "finalize_timm_cache_f739399.py"
& $Python -m py_compile $auditPath $finalizerPath
$compileExit = $LASTEXITCODE
if ($compileExit -ne 0) { throw "Uploaded S3 Python py_compile failed" }
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
$configSha = (Get-FileHash -LiteralPath (Join-Path $RepoRoot "configs\diagnostics\recovery\ov_orthkd_s3_pretrained_seed42.yaml") -Algorithm SHA256).Hash.ToLowerInvariant()
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0 -or $configSha -ne $ExpectedConfigSha) {
    throw "Exact S3 candidate worktree/config check failed"
}
$a0StatePath = Join-Path $ControlRoot "a0_f739399\worker_state.json"
$a0State = Get-Content -LiteralPath $a0StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
$s3Processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*audit_pretrained_backbones.py*" -or
    $_.CommandLine -like "*run_s3_worker_f739399.ps1*"
})
if ($s3Processes.Count -ne 0) { throw "S3 process exists before the A0 gate" }
$cacheReceiptPath = Join-Path $ControlRoot "timm_direct_f739399\official_cache_receipt.json"
$cacheReceipt = Get-Content -LiteralPath $cacheReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($cacheReceipt.status -ne "PASS" -or
    $cacheReceipt.claim_level -ne "official_timm_1.0.28_pretrained_cfg_direct_url_cache_lock") {
    throw "Official timm cache receipt does not satisfy the S3 preflight gate"
}

[ordered]@{
    schema_version = 1
    status = if ($a0State.status -eq "completed") { "READY_TO_EVALUATE_A0_GATE" } else { "WAITING_FOR_A0" }
    utc = [DateTime]::UtcNow.ToString("o")
    files = $receipts
    audit_py_compile_exit = $compileExit
    audit_local_ruff_exit = 0
    audit_local_ruff_binding = "same_sha256_bf2f1e26b57ff4ccccd248d8e0d292800b50019d94593190e231115fe5bb4f1f"
    finalizer_local_ruff_binding = "same_sha256_19c8344693ce826d04520fbdfc3063a66cfed2cebe8d56fa3ee7f9db49638226"
    audit_remote_ruff = "not_installed_in_locked_venv"
    official_cache_receipt_sha256 = (Get-FileHash -LiteralPath $cacheReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
    git_head = $head
    git_dirty_lines = $dirty.Count
    config_sha256 = $configSha
    a0_status = $a0State.status
    a0_current_control = $a0State.current_control
    s3_process_count = $s3Processes.Count
} | ConvertTo-Json -Depth 6
