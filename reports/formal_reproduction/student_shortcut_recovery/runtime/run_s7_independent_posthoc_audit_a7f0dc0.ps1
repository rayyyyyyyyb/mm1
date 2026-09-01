$ErrorActionPreference = "Stop"
$ExpectedCommit = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"
$ExpectedAuditorSha = "31ca63c83e49d121d6d2e850c1bb85ac647833af0a55b7770733e6fc63694826"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Auditor = "E:\OV-OrthKD-R3\student_shortcut_control\audit_s7_posthoc.py"
$TrainingAudit = "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0\s7_training_artifact_audit.json"
$Control = "E:\OV-OrthKD-R3\student_shortcut_control\s7_posthoc_a7f0dc0"
$Trajectory = "E:\OV-OrthKD-R3\student_shortcut_control\s7_posthoc_a7f0dc0_results\s7_checkpoint_trajectory.json"
$Output = "E:\OV-OrthKD-R3\student_shortcut_control\s7_posthoc_a7f0dc0_results\s7_posthoc_artifact_audit.json"

foreach ($required in @($Python, $Auditor, $TrainingAudit, $Control, $Trajectory)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Missing required S7 independent-audit path: $required"
    }
}
$actualAuditorSha = (Get-FileHash -LiteralPath $Auditor -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualAuditorSha -ne $ExpectedAuditorSha) {
    throw "S7 independent auditor SHA256 mismatch"
}
$state = Get-Content -LiteralPath (Join-Path $Control "worker_state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    $state.status -ne "completed" -or
    [int]$state.exit_code -ne 0 -or
    $state.git_commit -ne $ExpectedCommit -or
    @($state.completed_phases) -join "," -ne "training_audit,checkpoint_trajectory"
) {
    throw "S7 posthoc worker has not completed its two phases"
}
if (Test-Path -LiteralPath $Output) {
    throw "S7 independent audit output already exists"
}

$env:PYTHONDONTWRITEBYTECODE = "1"
& $Python $Auditor `
    --training-audit $TrainingAudit `
    --trajectory $Trajectory `
    --control $Control `
    --output $Output
if ($LASTEXITCODE -ne 0) {
    throw "S7 independent posthoc audit failed with exit code $LASTEXITCODE"
}
$report = Get-Content -LiteralPath $Output -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    $report.status -ne "PASS" -or
    $report.claim_level -ne "noncanonical_s7_posthoc_artifact_audit" -or
    $report.git_commit -ne $ExpectedCommit -or
    $report.sources.auditor.sha256 -ne $ExpectedAuditorSha
) {
    throw "S7 independent posthoc audit output failed its receipt check"
}
[ordered]@{
    status = $report.status
    claim_level = $report.claim_level
    git_commit = $report.git_commit
    output = $Output
    bytes = (Get-Item -LiteralPath $Output).Length
    sha256 = (Get-FileHash -LiteralPath $Output -Algorithm SHA256).Hash.ToLowerInvariant()
    causal_decision = $report.causal_decision_recomputed
} | ConvertTo-Json -Depth 10
