$ErrorActionPreference = "Stop"
$ExpectedCommit = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "31414e2b7e8b7437d4332678a99ce6ce446063e9f0eb4067bfc24a48f36728be"
$ExpectedTrainingAuditScriptSha = "7c768b7039e9740949ae8214a9a860fa43e14dfe4e4a5318a7a2065303e530c3"
$ExpectedTrajectoryScriptSha = "efd36105f131dd4096c3ee35dfc1cba19bc175975f1931e7c9d1f749ffe5425a"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s7_posthoc_worker_a7f0dc0.ps1"
$TrainingAuditScript = "E:\OV-OrthKD-R3\student_shortcut_control\audit_s7_training.py"
$TrajectoryScript = "E:\OV-OrthKD-R3\student_shortcut_control\diagnose_s7_checkpoint_trajectory.py"
$TrainingControl = "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s7_posthoc_a7f0dc0"
$ResultsDir = "E:\OV-OrthKD-R3\student_shortcut_control\s7_posthoc_a7f0dc0_results"

foreach ($locked in @(
    @($ModulePath, $ExpectedModuleSha),
    @($WorkerPath, $ExpectedWorkerSha),
    @($TrainingAuditScript, $ExpectedTrainingAuditScriptSha),
    @($TrajectoryScript, $ExpectedTrajectoryScriptSha)
)) {
    if (-not (Test-Path -LiteralPath $locked[0] -PathType Leaf)) { throw "Missing locked S7 posthoc file: $($locked[0])" }
    $actual = (Get-FileHash -LiteralPath $locked[0] -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $locked[1]) { throw "Locked S7 posthoc SHA256 mismatch: $($locked[0])" }
}
$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "S7 posthoc launch requires exact clean commit" }
$trainingStatePath = Join-Path $TrainingControl "worker_state.json"
$trainingState = Get-Content -LiteralPath $trainingStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    $trainingState.status -ne "completed" -or
    [int]$trainingState.exit_code -ne 0 -or
    @($trainingState.completed_phases) -join "," -ne "s7_training"
) {
    throw "S7 training is not completed"
}
if (Test-Path -LiteralPath $ControlDir) { throw "Fresh S7 posthoc launch refuses existing control directory" }
if (Test-Path -LiteralPath $ResultsDir) { throw "Fresh S7 posthoc launch refuses existing results directory" }
$matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*" -or
    $_.CommandLine -like "*run_s7_worker_a7f0dc0.ps1*" -or
    $_.CommandLine -like "*run_s7_posthoc_worker_a7f0dc0.ps1*" -or
    $_.CommandLine -like "*diagnose_s7_checkpoint_trajectory.py*" -or
    $_.CommandLine -like "*audit_s7_training.py*"
})
if ($matching.Count -ne 0) { throw "Conflicting S7 training/posthoc processes are running" }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ControlDir) | Out-Null
New-Item -ItemType Directory -Path $ControlDir | Out-Null
Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath
$workerProcessId = [int]$created.ProcessId
Start-Sleep -Seconds 10
$process = Get-Process -Id $workerProcessId -ErrorAction SilentlyContinue
$statePath = Join-Path $ControlDir "worker_state.json"
$state = if (Test-Path -LiteralPath $statePath) { Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
if ($null -eq $state) { throw "Persistent S7 posthoc worker did not create state" }
if ($null -eq $process -and $state.status -ne "completed") {
    throw "Persistent S7 posthoc worker exited during launch: $($state.message)"
}
$healthyRunning = (
    $state.status -eq "running" -and
    $state.current_phase -in @("training_audit", "checkpoint_trajectory")
)
$healthyCompleted = ($state.status -eq "completed" -and [int]$state.exit_code -eq 0)
if (-not $healthyRunning -and -not $healthyCompleted) {
    throw "Persistent S7 posthoc worker did not report a healthy state"
}

$receipt = [ordered]@{
    schema_version = 1
    status = $state.status
    utc = [DateTime]::UtcNow.ToString("o")
    launch_method = "Win32_Process.Create_via_verified_PersistentProcess_module"
    worker_process_id = $workerProcessId
    return_value = [int]$created.ReturnValue
    git_commit = $ExpectedCommit
    module_sha256 = $ExpectedModuleSha
    worker_sha256 = $ExpectedWorkerSha
    training_audit_script_sha256 = $ExpectedTrainingAuditScriptSha
    trajectory_script_sha256 = $ExpectedTrajectoryScriptSha
    training_state_sha256 = (Get-FileHash -LiteralPath $trainingStatePath -Algorithm SHA256).Hash.ToLowerInvariant()
    phases = @("training_audit", "checkpoint_trajectory")
}
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $ControlDir "launch.json") -Encoding UTF8
[ordered]@{
    receipt = $receipt
    state = $state
    process = @(Get-CimInstance Win32_Process -Filter "ProcessId=$workerProcessId" | Select-Object ProcessId,ParentProcessId,Name,CommandLine)
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 8
