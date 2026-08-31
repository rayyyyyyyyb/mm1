$ErrorActionPreference = "Stop"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s4-74d211d"
$ControlRoot = "E:\OV-OrthKD-R3\student_shortcut_control"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "74d211d34ace74ce3b74ea082a7dfd0379b251fb"
$Expected = [ordered]@{
    "audit_s4_training.py" = "8f094eba8ac9c8c2d6b6b83f1855d7ad7a4976d1996334f339787d9d6fe06907"
    "run_s4_training_artifact_audit_74d211d.ps1" = "e88b7aacbd35f617c62c64a295a0ccf48428efdf1d56f7c93f6c58c5f9f90d87"
    "run_s4_posthoc_worker_74d211d.ps1" = "359af5713509e818c0908200ad894cf33014b23572743564ddaf61efce46c748"
    "launch_s4_posthoc_74d211d.ps1" = "aaa38d2524450aa641b302e241311cb6fc1e2a6e4671917008a07078d0b7ed40"
    "resume_s4_posthoc_74d211d.ps1" = "b707d6a882e7d282382fb4068c89d0444ce3c616c9af7e165e5945902400160b"
    "query_s4_posthoc_74d211d.ps1" = "bd094a9d0a2780a4ffcacd92d38bd5403f5dd885edb5514a60efa771087f1b6d"
    "audit_s4_posthoc.py" = "2cefbec83cbeec7ba38e3c9ede6a02973faefc417cb09dc69195c3354fca236f"
    "run_s4_posthoc_artifact_audit_74d211d.ps1" = "c471f3a4c2390ced69be3dce5f162753bc0093cbab84778b3cd71000aa47b647"
}

$receipts = @()
foreach ($entry in $Expected.GetEnumerator()) {
    $path = Join-Path $ControlRoot $entry.Key
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing uploaded S4 audit file: $path" }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.Value) { throw "Uploaded S4 audit SHA256 mismatch: $($entry.Key)" }
    $parseCount = $null
    if ($path.EndsWith(".ps1")) {
        $tokens = $null
        $parseErrors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors) | Out-Null
        $parseCount = $parseErrors.Count
        if ($parseCount -ne 0) { throw "Uploaded S4 audit PowerShell parse failure: $($entry.Key)" }
    }
    $receipts += [ordered]@{
        name = $entry.Key
        bytes = (Get-Item -LiteralPath $path).Length
        sha256 = $actual
        parse_errors = $parseCount
    }
}

& $Python -m py_compile (Join-Path $ControlRoot "audit_s4_training.py") (Join-Path $ControlRoot "audit_s4_posthoc.py")
$compileExit = $LASTEXITCODE
if ($compileExit -ne 0) { throw "Uploaded S4 audit Python py_compile failed" }
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "Exact S4 candidate worktree check failed" }

$trainingStatePath = Join-Path $ControlRoot "s4_74d211d\worker_state.json"
$trainingState = if (Test-Path -LiteralPath $trainingStatePath -PathType Leaf) {
    Get-Content -LiteralPath $trainingStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
} else { $null }
$trainingAuditPath = Join-Path $ControlRoot "s4_74d211d\s4_training_artifact_audit.json"
$posthocProcesses = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*run_s4_posthoc_worker_74d211d.ps1*" -or
    $_.CommandLine -like "*diagnose_student_shortcuts.py*" -or
    $_.CommandLine -like "*diagnose_checkpoint_modalities.py*"
})
if ($posthocProcesses.Count -ne 0) { throw "S4 posthoc process exists before its gate" }

$gateStatus = if ($null -eq $trainingState -or $trainingState.status -ne "completed") {
    "WAITING_FOR_S4_TRAINING"
} elseif (-not (Test-Path -LiteralPath $trainingAuditPath -PathType Leaf)) {
    "READY_TO_RUN_S4_TRAINING_AUDIT"
} else {
    $trainingAudit = Get-Content -LiteralPath $trainingAuditPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($trainingAudit.status -ne "PASS" -or $trainingAudit.git_commit -ne $ExpectedCommit -or
        [int]$trainingAudit.task_segments -ne 10) {
        throw "Existing S4 training audit does not satisfy the posthoc gate"
    }
    "READY_TO_LAUNCH_S4_POSTHOC"
}
[ordered]@{
    schema_version = 1
    status = $gateStatus
    utc = [DateTime]::UtcNow.ToString("o")
    files = $receipts
    audit_py_compile_exit = $compileExit
    audit_local_ruff_exit = 0
    git_head = $head
    git_dirty_lines = $dirty.Count
    training_state = $trainingState
    training_audit_exists = Test-Path -LiteralPath $trainingAuditPath -PathType Leaf
    posthoc_process_count = $posthocProcesses.Count
} | ConvertTo-Json -Depth 8
