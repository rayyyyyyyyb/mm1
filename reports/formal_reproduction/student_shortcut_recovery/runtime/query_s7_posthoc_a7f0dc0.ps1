$ErrorActionPreference = "Stop"
$TrainingAudit = "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0\s7_training_artifact_audit.json"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s7_posthoc_a7f0dc0"
$Trajectory = "E:\OV-OrthKD-R3\student_shortcut_control\s7_posthoc_a7f0dc0_results\s7_checkpoint_trajectory.json"
$statePath = Join-Path $ControlDir "worker_state.json"
$state = if (Test-Path -LiteralPath $statePath) { Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
$worker = if ($null -ne $state) { @(Get-CimInstance Win32_Process -Filter "ProcessId=$($state.worker_process_id)" | Select-Object ProcessId,ParentProcessId,Name,CommandLine) } else { @() }
$stderrFiles = @("training_audit.stderr.log", "trajectory.stderr.log")
$stderr = @{}
foreach ($name in $stderrFiles) {
    $path = Join-Path $ControlDir $name
    $stderr[$name] = if (Test-Path -LiteralPath $path) {
        [ordered]@{ bytes=(Get-Item -LiteralPath $path).Length; tail=[string[]]@(Get-Content -LiteralPath $path -Tail 10 -Encoding UTF8) }
    } else { $null }
}
$trajectorySummary = $null
if (Test-Path -LiteralPath $Trajectory -PathType Leaf) {
    $report = Get-Content -LiteralPath $Trajectory -Raw -Encoding UTF8 | ConvertFrom-Json
    $trajectorySummary = [ordered]@{
        bytes = (Get-Item -LiteralPath $Trajectory).Length
        sha256 = (Get-FileHash -LiteralPath $Trajectory -Algorithm SHA256).Hash.ToLowerInvariant()
        best_step = $report.best_step
        causal_decision = $report.causal_decision
    }
}
[ordered]@{
    utc = [DateTime]::UtcNow.ToString("o")
    state = $state
    worker = $worker
    training_audit_exists = Test-Path -LiteralPath $TrainingAudit -PathType Leaf
    trajectory = $trajectorySummary
    stderr = $stderr
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 14
