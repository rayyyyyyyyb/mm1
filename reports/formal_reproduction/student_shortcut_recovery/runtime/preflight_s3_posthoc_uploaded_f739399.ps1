$ErrorActionPreference = "Stop"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-a0aa4d7"
$ControlRoot = "E:\OV-OrthKD-R3\student_shortcut_control"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
$Expected = [ordered]@{
    "run_s3_posthoc_worker_f739399.ps1" = "d7932dda1afea09b0f7cea62fdbde862b1851b69f45a20b649d00f884846926e"
    "launch_s3_posthoc_f739399.ps1" = "a510af501c7a447aa72f9189170844e74dedd94ad8fc7e22cc9ce468020cb559"
    "resume_s3_posthoc_f739399.ps1" = "fee4263832a31134341866348408c12757af46964175a4f565d02054120f5882"
    "query_s3_posthoc_f739399.ps1" = "6ebdfa7c684492678d344df668b44ee4abcfae9486b5f339fbd0afe665744af2"
    "audit_s3_posthoc.py" = "0990f6eb627fbf23c29f4f93cb84a92a5741cf16eda8667a831a903ac9a183a2"
}

$receipts = @()
foreach ($entry in $Expected.GetEnumerator()) {
    $path = Join-Path $ControlRoot $entry.Key
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing uploaded posthoc file: $path" }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.Value) { throw "Uploaded posthoc SHA256 mismatch: $($entry.Key)" }
    $parseCount = $null
    if ($path.EndsWith(".ps1")) {
        $tokens = $null
        $parseErrors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors) | Out-Null
        $parseCount = $parseErrors.Count
        if ($parseCount -ne 0) { throw "Uploaded posthoc PowerShell parse failure: $($entry.Key)" }
    }
    $receipts += [ordered]@{name = $entry.Key; bytes = (Get-Item -LiteralPath $path).Length; sha256 = $actual; parse_errors = $parseCount}
}
$auditPath = Join-Path $ControlRoot "audit_s3_posthoc.py"
& $Python -m py_compile $auditPath
$compileExit = $LASTEXITCODE
if ($compileExit -ne 0) { throw "Uploaded posthoc audit py_compile failed" }
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "Exact posthoc candidate worktree check failed" }
$auditGate = Join-Path $ControlRoot "s3_a0aa4d7\s3_training_artifact_audit.json"
$posthocProcesses = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*run_s3_posthoc_worker_f739399.ps1*" -or
    $_.CommandLine -like "*diagnose_student_shortcuts.py*" -or
    $_.CommandLine -like "*diagnose_checkpoint_modalities.py*" -and
    $_.CommandLine -like "*s3_posthoc_a0aa4d7*"
})
if ($posthocProcesses.Count -ne 0) { throw "S3 posthoc process exists before its gate" }
[ordered]@{
    schema_version = 1
    status = if (Test-Path -LiteralPath $auditGate -PathType Leaf) { "READY_TO_EVALUATE_S3_AUDIT_GATE" } else { "WAITING_FOR_S3_AUDIT" }
    utc = [DateTime]::UtcNow.ToString("o")
    files = $receipts
    audit_py_compile_exit = $compileExit
    audit_local_ruff_exit = 0
    audit_local_ruff_binding = "same_sha256_0990f6eb627fbf23c29f4f93cb84a92a5741cf16eda8667a831a903ac9a183a2"
    audit_remote_ruff = "not_installed_in_locked_venv"
    fixture_audit_exit = 0
    git_head = $head
    git_dirty_lines = $dirty.Count
    s3_training_audit_exists = Test-Path -LiteralPath $auditGate -PathType Leaf
    posthoc_process_count = $posthocProcesses.Count
} | ConvertTo-Json -Depth 6
