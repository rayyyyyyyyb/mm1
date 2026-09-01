$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s7_worker_a7f0dc0.ps1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0"
$VerificationPath = "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0_verification\verification_receipt.json"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"
$ExpectedConfigSha = "26e3f21504d7ce3f9a5498b8c89073fc910db80cbdf058c4b6a397b8735518b6"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "1ef0988ca6ec8e8d20464fa3dc44671b00499111fdb2cce077efbcad87bac99b"
$ExpectedVerificationSha = "ce10e08506e7382bedfc16442c4d46f30834b2f20b0b90d54148100193ae7cf9"

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

if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) { throw "Persistent module SHA256 mismatch" }
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) { throw "S7 worker SHA256 mismatch" }
if ((Get-FileHash -LiteralPath $VerificationPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedVerificationSha) { throw "S7 verification SHA256 mismatch" }
$verification = Get-Content -LiteralPath $VerificationPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($verification.status -ne "PASS" -or $verification.commit_after -ne $ExpectedCommit -or [int]$verification.pytest_exit -ne 0 -or [int]$verification.dirty_after -ne 0) {
    throw "S7 candidate verification did not satisfy the resume gate"
}
if (-not (Test-Path -LiteralPath $ControlDir -PathType Container)) { throw "Resume requires an existing S7 control directory" }
$statePath = Join-Path $ControlDir "worker_state.json"
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { throw "Resume requires an S7 worker state" }
$stateBefore = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($stateBefore.status -eq "completed") { throw "S7 is already completed" }
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
$configPath = Join-Path $RepoRoot "configs\diagnostics\recovery\ov_orthkd_s7_temporal_identity_seed42.yaml"
$configSha = Get-NormalizedTextSha256 -Path $configPath
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0 -or $configSha -ne $ExpectedConfigSha) {
    throw "Resume requires the exact clean S7 commit/config"
}
$matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*run_s7_worker_a7f0dc0.ps1*"
})
if ($matching.Count -ne 0) { throw "A conflicting training or S7 process is already running" }

Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath -ArgumentList @("-Resume")
$workerProcessId = [int]$created.ProcessId
Start-Sleep -Seconds 10
$process = Get-Process -Id $workerProcessId -ErrorAction SilentlyContinue
$stateAfter = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($null -eq $process) { throw "Persistent S7 resume worker exited during launch: $($stateAfter.message)" }
if ($stateAfter.status -ne "running" -or $stateAfter.current_phase -ne "s7_training") {
    throw "Persistent S7 resume worker did not report the expected running state"
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
