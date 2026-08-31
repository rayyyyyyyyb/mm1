$ErrorActionPreference = "Stop"
$ExpectedCommit = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
$ExpectedAuditSha = "0990f6eb627fbf23c29f4f93cb84a92a5741cf16eda8667a831a903ac9a183a2"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-a0aa4d7"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s3_posthoc_a0aa4d7"
$ResultsDir = "E:\OV-OrthKD-R3\student_shortcut_control\s3_posthoc_a0aa4d7_results"
$TrainingAudit = "E:\OV-OrthKD-R3\student_shortcut_control\s3_a0aa4d7\s3_training_artifact_audit.json"
$AuditScript = "E:\OV-OrthKD-R3\student_shortcut_control\audit_s3_posthoc.py"
$AuditOutput = Join-Path $ResultsDir "s3_posthoc_artifact_audit.json"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"

if ((Get-FileHash -LiteralPath $AuditScript -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedAuditSha) { throw "S3 posthoc audit script SHA mismatch" }
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "S3 posthoc audit requires exact clean candidate" }
$state = Get-Content -LiteralPath (Join-Path $ControlDir "worker_state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($state.status -ne "completed" -or [int]$state.exit_code -ne 0) { throw "S3 posthoc worker is not completed" }
if (Test-Path -LiteralPath $AuditOutput) { throw "Fresh S3 posthoc audit refuses pre-existing output" }

Import-Module $ModulePath -Force
$arguments = @(
    $AuditScript,
    "--prediction", (Join-Path $ResultsDir "prediction_shortcut.json"),
    "--modality", (Join-Path $ResultsDir "checkpoint_modality.json"),
    "--training-audit", $TrainingAudit,
    "--repo", $RepoRoot,
    "--git", $Git,
    "--output", $AuditOutput
)
$stdout = Join-Path $ControlDir "artifact_audit.stdout.log"
$stderr = Join-Path $ControlDir "artifact_audit.stderr.log"
$code = Invoke-NativeProcessWithRedirect -FilePath $Python -ArgumentList $arguments -WorkingDirectory $RepoRoot -StandardOutputPath $stdout -StandardErrorPath $stderr
if ($code -ne 0) { throw "S3 posthoc artifact audit exited with code $code" }
$audit = Get-Content -LiteralPath $AuditOutput -Raw -Encoding UTF8 | ConvertFrom-Json
if ($audit.status -ne "PASS" -or $audit.git_commit -ne $ExpectedCommit -or [int]$audit.task_segments -ne 10) { throw "S3 posthoc artifact audit did not pass" }
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
