$ErrorActionPreference = "Stop"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s4-74d211d"
$ControlRoot = "E:\OV-OrthKD-R3\student_shortcut_control"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "74d211d34ace74ce3b74ea082a7dfd0379b251fb"
$ExpectedS3Commit = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
$ExpectedConfigSha = "5b81218b55907a5dfb0419e62eff2128f0d08ce9301c97c081237f8c8f599b33"
$Expected = [ordered]@{
    "run_s4_worker_74d211d.ps1" = "757710ca129c153b02d6c30c36658f84c53990c0fe27f032303a79a7edee26dd"
    "launch_s4_74d211d.ps1" = "a03b4e55ad1c3e7fe9e31014c46b190255b51e24de6eb02cdddb6ff1ed5c70af"
    "resume_s4_74d211d.ps1" = "b4beb413f4188691e2d101b3efbc004efe1f7551752a0ad112addab9c9157193"
    "query_s4_74d211d.ps1" = "3925dd97f9a566dbfb17bb1c3505634771a203f34665bcfe774ba660d016c274"
}

function Get-NormalizedTextSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8).Replace("`r`n", "`n")
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text)))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

$receipts = @()
foreach ($entry in $Expected.GetEnumerator()) {
    $path = Join-Path $ControlRoot $entry.Key
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing uploaded S4 file: $path" }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.Value) { throw "Uploaded S4 SHA256 mismatch: $($entry.Key)" }
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count -ne 0) { throw "Uploaded PowerShell parse failure: $($entry.Key)" }
    $receipts += [ordered]@{
        name = $entry.Key
        bytes = (Get-Item -LiteralPath $path).Length
        sha256 = $actual
        parse_errors = $parseErrors.Count
    }
}

$verificationPath = Join-Path $ControlRoot "candidate_s4_74d211d\verification_receipt.json"
$verification = Get-Content -LiteralPath $verificationPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($verification.status -ne "PASS" -or $verification.expected_commit -ne $ExpectedCommit -or
    $verification.head_before -ne $ExpectedCommit -or $verification.head_after -ne $ExpectedCommit -or
    [int]$verification.dirty_before -ne 0 -or [int]$verification.dirty_after -ne 0 -or
    [int]$verification.focused_pytest_exit -ne 0 -or [int]$verification.compileall_exit -ne 0 -or
    [int]$verification.pytest_exit -ne 0) {
    throw "S4 candidate verification receipt did not satisfy preflight"
}
$s3TrainingPath = Join-Path $ControlRoot "s3_a0aa4d7\s3_training_artifact_audit.json"
$s3Training = Get-Content -LiteralPath $s3TrainingPath -Raw -Encoding UTF8 | ConvertFrom-Json
$s3PosthocPath = Join-Path $ControlRoot "s3_posthoc_a0aa4d7_results\s3_posthoc_artifact_audit.json"
$s3Posthoc = Get-Content -LiteralPath $s3PosthocPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($s3Training.status -ne "PASS" -or $s3Posthoc.status -ne "PASS" -or
    $s3Training.git_commit -ne $ExpectedS3Commit -or $s3Posthoc.git_commit -ne $ExpectedS3Commit -or
    [int]$s3Training.task_segments -ne 10 -or [int]$s3Posthoc.task_segments -ne 10 -or
    $s3Posthoc.training_audit.sha256 -ne (Get-FileHash -LiteralPath $s3TrainingPath -Algorithm SHA256).Hash.ToLowerInvariant()) {
    throw "S3 audit chain did not satisfy preflight"
}

$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
$configPath = Join-Path $RepoRoot "configs\diagnostics\recovery\ov_orthkd_s4_no_augment_seed42.yaml"
$configSha = Get-NormalizedTextSha256 -Path $configPath
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0 -or $configSha -ne $ExpectedConfigSha) {
    throw "Exact clean S4 candidate worktree/config check failed"
}
$processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*run_s4_worker_74d211d.ps1*"
})
if ($processes.Count -ne 0) { throw "An S4 or training process exists before launch preflight" }

[ordered]@{
    schema_version = 1
    status = "READY_TO_LAUNCH_S4"
    utc = [DateTime]::UtcNow.ToString("o")
    files = $receipts
    candidate_verification_sha256 = (Get-FileHash -LiteralPath $verificationPath -Algorithm SHA256).Hash.ToLowerInvariant()
    candidate_focused_pytest_exit = [int]$verification.focused_pytest_exit
    candidate_compileall_exit = [int]$verification.compileall_exit
    candidate_pytest_exit = [int]$verification.pytest_exit
    s3_training_audit_sha256 = (Get-FileHash -LiteralPath $s3TrainingPath -Algorithm SHA256).Hash.ToLowerInvariant()
    s3_posthoc_audit_sha256 = (Get-FileHash -LiteralPath $s3PosthocPath -Algorithm SHA256).Hash.ToLowerInvariant()
    git_head = $head
    git_dirty_lines = $dirty.Count
    config_sha256 = $configSha
    sole_scientific_change_from_s0 = "data.train_augment_true_to_false"
    s4_process_count = $processes.Count
} | ConvertTo-Json -Depth 8
