$ErrorActionPreference = "Stop"
$ExpectedCommit = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "31414e2b7e8b7437d4332678a99ce6ce446063e9f0eb4067bfc24a48f36728be"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s7_posthoc_worker_a7f0dc0.ps1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s7_posthoc_a7f0dc0"

if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) { throw "Persistent module SHA256 mismatch" }
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) { throw "S7 posthoc worker SHA256 mismatch" }
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "S7 posthoc resume requires exact clean commit" }
if (-not (Test-Path -LiteralPath $ControlDir -PathType Container)) { throw "S7 posthoc resume requires existing control directory" }
$statePath = Join-Path $ControlDir "worker_state.json"
$stateBefore = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($stateBefore.status -eq "completed") { throw "S7 posthoc is already completed" }
$matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*run_s7_posthoc_worker_a7f0dc0.ps1*" -or
    $_.CommandLine -like "*diagnose_s7_checkpoint_trajectory.py*" -or
    $_.CommandLine -like "*audit_s7_training.py*"
})
if ($matching.Count -ne 0) { throw "S7 posthoc processes are already running" }

Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath -ArgumentList @("-Resume")
$workerProcessId = [int]$created.ProcessId
Start-Sleep -Seconds 10
$process = Get-Process -Id $workerProcessId -ErrorAction SilentlyContinue
$stateAfter = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($null -eq $process -and $stateAfter.status -ne "completed") {
    throw "Persistent S7 posthoc resume worker exited: $($stateAfter.message)"
}
if ($stateAfter.status -notin @("running", "completed")) {
    throw "Persistent S7 posthoc resume did not report running/completed"
}

$receipt = [ordered]@{
    schema_version = 1
    status = $stateAfter.status
    resume = $true
    utc = [DateTime]::UtcNow.ToString("o")
    worker_process_id = $workerProcessId
    return_value = [int]$created.ReturnValue
    module_sha256 = $ExpectedModuleSha
    worker_sha256 = $ExpectedWorkerSha
    git_commit = $ExpectedCommit
    state_before = $stateBefore
    state_after = $stateAfter
}
$receiptPath = Join-Path $ControlDir ("resume_launch_" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ") + ".json")
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
[ordered]@{
    receipt_path = $receiptPath
    receipt = $receipt
    process = if ($null -ne $process) { @(Get-CimInstance Win32_Process -Filter "ProcessId=$workerProcessId" | Select-Object ProcessId,ParentProcessId,Name,CommandLine) } else { @() }
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 10
