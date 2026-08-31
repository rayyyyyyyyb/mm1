$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s4_worker_74d211d.ps1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s4_74d211d"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s4-74d211d"
$VerificationPath = "E:\OV-OrthKD-R3\student_shortcut_control\candidate_s4_74d211d\verification_receipt.json"
$S3PosthocAuditPath = "E:\OV-OrthKD-R3\student_shortcut_control\s3_posthoc_a0aa4d7_results\s3_posthoc_artifact_audit.json"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "74d211d34ace74ce3b74ea082a7dfd0379b251fb"
$ExpectedS3Commit = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
$ExpectedConfigSha = "5b81218b55907a5dfb0419e62eff2128f0d08ce9301c97c081237f8c8f599b33"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "757710ca129c153b02d6c30c36658f84c53990c0fe27f032303a79a7edee26dd"

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

if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) {
    throw "Persistent module SHA256 mismatch"
}
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) {
    throw "S4 worker SHA256 mismatch"
}
$verification = Get-Content -LiteralPath $VerificationPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($verification.status -ne "PASS" -or $verification.expected_commit -ne $ExpectedCommit -or
    [int]$verification.pytest_exit -ne 0 -or [int]$verification.dirty_after -ne 0) {
    throw "S4 candidate verification did not satisfy the resume gate"
}
$s3Posthoc = Get-Content -LiteralPath $S3PosthocAuditPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($s3Posthoc.status -ne "PASS" -or $s3Posthoc.git_commit -ne $ExpectedS3Commit -or
    [int]$s3Posthoc.task_segments -ne 10) {
    throw "S3 posthoc audit did not satisfy the resume gate"
}
if (-not (Test-Path -LiteralPath $ControlDir -PathType Container)) {
    throw "Resume requires an existing S4 control directory"
}
$statePath = Join-Path $ControlDir "worker_state.json"
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { throw "Resume requires an S4 worker state" }
$stateBefore = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($stateBefore.status -eq "completed") { throw "S4 is already completed" }
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all | Where-Object { $_ -notlike "?? outputs/*" })
$configPath = Join-Path $RepoRoot "configs\diagnostics\recovery\ov_orthkd_s4_no_augment_seed42.yaml"
$configSha = Get-NormalizedTextSha256 -Path $configPath
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0 -or $configSha -ne $ExpectedConfigSha) {
    throw "Resume requires the exact S4 commit/config with no tracked changes"
}
$matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*run_s4_worker_74d211d.ps1*"
})
if ($matching.Count -ne 0) { throw "A conflicting training or S4 process is already running" }

Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath -ArgumentList @("-Resume")
$workerProcessId = [int]$created.ProcessId
Start-Sleep -Seconds 10
$process = Get-Process -Id $workerProcessId -ErrorAction SilentlyContinue
$stateAfter = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($null -eq $process) { throw "Persistent S4 resume worker exited during launch: $($stateAfter.message)" }
if ($stateAfter.status -ne "running" -or $stateAfter.current_phase -ne "s4_training") {
    throw "Persistent S4 resume worker did not report the expected running state"
}

$receipt = [ordered]@{
    schema_version = 1
    status = "running"
    resume = $true
    utc = [DateTime]::UtcNow.ToString("o")
    worker_process_id = $workerProcessId
    return_value = [int]$created.ReturnValue
    module_sha256 = $ExpectedModuleSha
    worker_sha256 = $ExpectedWorkerSha
    git_head = $ExpectedCommit
    config_sha256 = $ExpectedConfigSha
    state_before = $stateBefore
    state_after = $stateAfter
}
$receiptPath = Join-Path $ControlDir ("resume_launch_" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ") + ".json")
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
[ordered]@{
    receipt_path = $receiptPath
    receipt = $receipt
    process = @(Get-CimInstance Win32_Process -Filter "ProcessId=$workerProcessId" | Select-Object ProcessId, ParentProcessId, Name, CommandLine)
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 10
