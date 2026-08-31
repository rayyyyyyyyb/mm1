$ErrorActionPreference = "Stop"
$ExpectedCommit = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
$ExpectedAuditSha = "bf2f1e26b57ff4ccccd248d8e0d292800b50019d94593190e231115fe5bb4f1f"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-a0aa4d7"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s3_a0aa4d7"
$TrainingOutput = Join-Path $RepoRoot "outputs\diagnostic\recovery_s3_pretrained_seed42"
$AuditScript = "E:\OV-OrthKD-R3\student_shortcut_control\audit_s3_training.py"
$AuditOutput = Join-Path $ControlDir "s3_training_artifact_audit.json"
$OfficialCacheReceipt = "E:\OV-OrthKD-R3\student_shortcut_control\timm_direct_f739399\official_cache_receipt.json"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"

if ((Get-FileHash -LiteralPath $AuditScript -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedAuditSha) { throw "S3 training audit script SHA mismatch" }
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "S3 training audit requires exact clean candidate" }
$state = Get-Content -LiteralPath (Join-Path $ControlDir "worker_state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($state.status -ne "completed" -or [int]$state.exit_code -ne 0) { throw "S3 worker is not completed" }
if (Test-Path -LiteralPath $AuditOutput) { throw "Fresh S3 training audit refuses pre-existing output" }

Import-Module $ModulePath -Force
$arguments = @(
    $AuditScript,
    "--repo", $RepoRoot,
    "--git", $Git,
    "--control", $ControlDir,
    "--output", $TrainingOutput,
    "--audit-output", $AuditOutput,
    "--official-cache-receipt", $OfficialCacheReceipt
)
$stdout = Join-Path $ControlDir "training_audit.stdout.log"
$stderr = Join-Path $ControlDir "training_audit.stderr.log"
$code = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $arguments -WorkingDirectory $RepoRoot -StandardOutputPath $stdout -StandardErrorPath $stderr
if ($code -ne 0) { throw "S3 training artifact audit exited with code $code" }
$audit = Get-Content -LiteralPath $AuditOutput -Raw -Encoding UTF8 | ConvertFrom-Json
if ($audit.status -ne "PASS" -or $audit.git_commit -ne $ExpectedCommit -or [int]$audit.task_segments -ne 10) { throw "S3 training artifact audit did not pass" }
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
