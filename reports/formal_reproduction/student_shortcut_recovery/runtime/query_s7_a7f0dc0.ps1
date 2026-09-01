$ErrorActionPreference = "Stop"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0"
$OutputDir = "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0\outputs\diagnostic\recovery_s7_temporal_identity_seed42"
$StatePath = Join-Path $ControlDir "worker_state.json"
$state = if (Test-Path -LiteralPath $StatePath) { Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
$worker = if ($null -ne $state) { @(Get-CimInstance Win32_Process -Filter "ProcessId=$($state.worker_process_id)" | Select-Object ProcessId,ParentProcessId,Name,CommandLine) } else { @() }
$historyPath = Join-Path $OutputDir "history.jsonl"
$history = if (Test-Path -LiteralPath $historyPath -PathType Leaf) {
    $lines = @(Get-Content -LiteralPath $historyPath -Encoding UTF8)
    [ordered]@{ records = $lines.Count; latest = if ($lines.Count) { $lines[-1] | ConvertFrom-Json } else { $null } }
} else { $null }
$diagnosticsPath = Join-Path $OutputDir "training_diagnostics.jsonl"
$diagnostics = if (Test-Path -LiteralPath $diagnosticsPath -PathType Leaf) {
    $lines = @(Get-Content -LiteralPath $diagnosticsPath -Encoding UTF8)
    [ordered]@{ records = $lines.Count; latest = if ($lines.Count) { $lines[-1] | ConvertFrom-Json } else { $null } }
} else { $null }
$checkpointDir = Join-Path $OutputDir "diagnostic_checkpoints"
$diagnosticCheckpoints = if (Test-Path -LiteralPath $checkpointDir -PathType Container) {
    @(Get-ChildItem -LiteralPath $checkpointDir -Filter "step_*.pt" | Sort-Object Name | Select-Object Name,Length,LastWriteTimeUtc)
} else { @() }
$stderrPath = Join-Path $ControlDir "s7.stderr.log"
[ordered]@{
    utc = [DateTime]::UtcNow.ToString("o")
    state = $state
    worker = $worker
    history = $history
    training_diagnostics = $diagnostics
    diagnostic_checkpoints = $diagnosticCheckpoints
    final_metrics_exists = Test-Path -LiteralPath (Join-Path $OutputDir "final_metrics.json") -PathType Leaf
    stderr = if (Test-Path -LiteralPath $stderrPath) { [ordered]@{ bytes=(Get-Item -LiteralPath $stderrPath).Length; tail=[string[]]@(Get-Content -LiteralPath $stderrPath -Tail 12 -Encoding UTF8) } } else { $null }
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 12
