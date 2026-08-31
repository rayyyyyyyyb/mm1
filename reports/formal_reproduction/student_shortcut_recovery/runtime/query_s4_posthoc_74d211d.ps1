$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s4_posthoc_74d211d"
$ResultsDir = "E:\OV-OrthKD-R3\student_shortcut_control\s4_posthoc_74d211d_results"
$statePath = Join-Path $ControlDir "worker_state.json"
$state = if (Test-Path -LiteralPath $statePath) {
    Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
} else { $null }
$worker = @()
$children = @()
if ($null -ne $state -and $null -ne $state.worker_process_id) {
    $workerId = [int]$state.worker_process_id
    $worker = @(Get-CimInstance Win32_Process -Filter "ProcessId=$workerId" | Select-Object ProcessId, ParentProcessId, Name, CommandLine)
    $children = @(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $workerId } | Select-Object ProcessId, ParentProcessId, Name, CommandLine)
}
$predictionPath = Join-Path $ResultsDir "prediction_shortcut.json"
$prediction = if (Test-Path -LiteralPath $predictionPath -PathType Leaf) {
    $value = Get-Content -LiteralPath $predictionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    [ordered]@{
        status = $value.status
        original_ap = $value.test.student_original_ap
        query_only_prior_ap = $value.test.query_only_prior.ap
        query_position_prior_ap = $value.test.query_position_prior.ap
        mean_centered_ap = $value.test.mean_centered_student.ap
        shuffle_mean_ap = $value.test.temporal_shuffle.ap_distribution.mean
    }
} else { $null }
$modalityPath = Join-Path $ResultsDir "checkpoint_modality.json"
$modality = if (Test-Path -LiteralPath $modalityPath -PathType Leaf) {
    $value = Get-Content -LiteralPath $modalityPath -Raw -Encoding UTF8 | ConvertFrom-Json
    [ordered]@{
        status = $value.status
        original_ap = $value.splits.test.modes.original.ap
        visual_zero_ap = $value.splits.test.modes.visual_zero.ap
        audio_zero_ap = $value.splits.test.modes.audio_zero.ap
        both_zero_ap = $value.splits.test.modes.both_zero.ap
    }
} else { $null }
$stderr = @{}
foreach ($name in @("prediction", "modality")) {
    $path = Join-Path $ControlDir "$name.stderr.log"
    $stderr[$name] = if (Test-Path -LiteralPath $path -PathType Leaf) {
        [ordered]@{
            bytes = (Get-Item -LiteralPath $path).Length
            tail = [string[]]@(Get-Content -LiteralPath $path -Tail 10 -Encoding UTF8)
        }
    } else { $null }
}
[ordered]@{
    utc = [DateTime]::UtcNow.ToString("o")
    state = $state
    worker_process = $worker
    children = $children
    prediction = $prediction
    modality = $modality
    stderr = $stderr
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 10
