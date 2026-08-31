$ErrorActionPreference = "Stop"
$ExpectedCommit = "74d211d34ace74ce3b74ea082a7dfd0379b251fb"
$ExpectedAuditSha = "2cefbec83cbeec7ba38e3c9ede6a02973faefc417cb09dc69195c3354fca236f"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s4-74d211d"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s4_posthoc_74d211d"
$ResultsDir = "E:\OV-OrthKD-R3\student_shortcut_control\s4_posthoc_74d211d_results"
$TrainingAudit = "E:\OV-OrthKD-R3\student_shortcut_control\s4_74d211d\s4_training_artifact_audit.json"
$AuditScript = "E:\OV-OrthKD-R3\student_shortcut_control\audit_s4_posthoc.py"
$AuditOutput = Join-Path $ResultsDir "s4_posthoc_artifact_audit.json"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"

if ((Get-FileHash -LiteralPath $AuditScript -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedAuditSha) {
    throw "S4 posthoc audit script SHA256 mismatch"
}
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) {
    throw "S4 posthoc audit requires the exact clean candidate"
}
$state = Get-Content -LiteralPath (Join-Path $ControlDir "worker_state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($state.status -ne "completed" -or [int]$state.exit_code -ne 0 -or
    @($state.completed_phases).Count -ne 2 -or
    $state.completed_phases[0] -ne "prediction" -or $state.completed_phases[1] -ne "modality") {
    throw "S4 posthoc worker is not completed"
}
if (Test-Path -LiteralPath $AuditOutput) { throw "Fresh S4 posthoc audit refuses pre-existing output" }

Import-Module $ModulePath -Force
$arguments = @(
    $AuditScript,
    "--prediction", (Join-Path $ResultsDir "prediction_shortcut.json"),
    "--modality", (Join-Path $ResultsDir "checkpoint_modality.json"),
    "--training-audit", $TrainingAudit,
    "--launch-receipt", (Join-Path $ControlDir "launch.json"),
    "--repo", $RepoRoot,
    "--git", $Git,
    "--output", $AuditOutput
)
$stdout = Join-Path $ControlDir "artifact_audit.stdout.log"
$stderr = Join-Path $ControlDir "artifact_audit.stderr.log"
$code = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $arguments -WorkingDirectory $RepoRoot -StandardOutputPath $stdout -StandardErrorPath $stderr
if ($code -ne 0) { throw "S4 posthoc artifact audit exited with code $code" }
$audit = Get-Content -LiteralPath $AuditOutput -Raw -Encoding UTF8 | ConvertFrom-Json
if ($audit.status -ne "PASS" -or $audit.git_commit -ne $ExpectedCommit -or [int]$audit.task_segments -ne 10) {
    throw "S4 posthoc artifact audit did not pass"
}
[ordered]@{
    schema_version = 1
    status = "PASS"
    audit_exit = $code
    audit_path = $AuditOutput
    audit_bytes = (Get-Item -LiteralPath $AuditOutput).Length
    audit_sha256 = (Get-FileHash -LiteralPath $AuditOutput -Algorithm SHA256).Hash.ToLowerInvariant()
    stdout_bytes = (Get-Item -LiteralPath $stdout).Length
    stderr_bytes = (Get-Item -LiteralPath $stderr).Length
    git_head = $head
    git_dirty_lines = $dirty.Count
    test = $audit.test
} | ConvertTo-Json -Depth 6
