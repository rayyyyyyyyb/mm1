$ErrorActionPreference = "Stop"
$ExpectedCommit = "74d211d34ace74ce3b74ea082a7dfd0379b251fb"
$ExpectedAuditSha = "8f094eba8ac9c8c2d6b6b83f1855d7ad7a4976d1996334f339787d9d6fe06907"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s4-74d211d"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s4_74d211d"
$TrainingOutput = Join-Path $RepoRoot "outputs\diagnostic\recovery_s4_no_augment_seed42"
$AuditScript = "E:\OV-OrthKD-R3\student_shortcut_control\audit_s4_training.py"
$AuditOutput = Join-Path $ControlDir "s4_training_artifact_audit.json"
$CandidateVerification = "E:\OV-OrthKD-R3\student_shortcut_control\candidate_s4_74d211d\verification_receipt.json"
$S3TrainingAudit = "E:\OV-OrthKD-R3\student_shortcut_control\s3_a0aa4d7\s3_training_artifact_audit.json"
$S3PosthocAudit = "E:\OV-OrthKD-R3\student_shortcut_control\s3_posthoc_a0aa4d7_results\s3_posthoc_artifact_audit.json"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"

if ((Get-FileHash -LiteralPath $AuditScript -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedAuditSha) {
    throw "S4 training audit script SHA256 mismatch"
}
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) {
    throw "S4 training audit requires the exact clean candidate"
}
$state = Get-Content -LiteralPath (Join-Path $ControlDir "worker_state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($state.status -ne "completed" -or [int]$state.exit_code -ne 0 -or
    @($state.completed_phases).Count -ne 1 -or $state.completed_phases[0] -ne "s4_training") {
    throw "S4 worker is not completed"
}
if (Test-Path -LiteralPath $AuditOutput) { throw "Fresh S4 training audit refuses pre-existing output" }

Import-Module $ModulePath -Force
$arguments = @(
    $AuditScript,
    "--repo", $RepoRoot,
    "--git", $Git,
    "--control", $ControlDir,
    "--output", $TrainingOutput,
    "--audit-output", $AuditOutput,
    "--candidate-verification", $CandidateVerification,
    "--s3-training-audit", $S3TrainingAudit,
    "--s3-posthoc-audit", $S3PosthocAudit
)
$stdout = Join-Path $ControlDir "training_audit.stdout.log"
$stderr = Join-Path $ControlDir "training_audit.stderr.log"
$code = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $arguments -WorkingDirectory $RepoRoot -StandardOutputPath $stdout -StandardErrorPath $stderr
if ($code -ne 0) { throw "S4 training artifact audit exited with code $code" }
$audit = Get-Content -LiteralPath $AuditOutput -Raw -Encoding UTF8 | ConvertFrom-Json
if ($audit.status -ne "PASS" -or $audit.git_commit -ne $ExpectedCommit -or
    [int]$audit.task_segments -ne 10 -or
    $audit.sole_scientific_change_from_s0 -ne "data.train_augment_true_to_false") {
    throw "S4 training artifact audit did not pass"
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
    final_metrics = $audit.final_metrics
    prediction_receipts = $audit.predictions
} | ConvertTo-Json -Depth 7
