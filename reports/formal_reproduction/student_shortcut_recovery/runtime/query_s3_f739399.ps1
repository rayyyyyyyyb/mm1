$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s3_a0aa4d7"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-a0aa4d7"
$OutputDir = Join-Path $RepoRoot "outputs\diagnostic\recovery_s3_pretrained_seed42"
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
$receiptPath = Join-Path $ControlDir "pretrained_backbone_receipt.json"
$receipt = if (Test-Path -LiteralPath $receiptPath -PathType Leaf) {
    $value = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    [ordered]@{
        status = $value.status
        config_sha256 = $value.config.sha256
        visual_model = $value.backbones.visual.model_name
        visual_pretrained_sha256 = $value.backbones.visual.pretrained_state_sha256
        visual_random_sha256 = $value.backbones.visual.random_state_sha256
        audio_model = $value.backbones.audio.model_name
        audio_pretrained_sha256 = $value.backbones.audio.pretrained_state_sha256
        audio_random_sha256 = $value.backbones.audio.random_state_sha256
    }
} else { $null }
$historyPath = Join-Path $OutputDir "history.jsonl"
$history = if (Test-Path -LiteralPath $historyPath -PathType Leaf) {
    $lines = @(Get-Content -LiteralPath $historyPath -Encoding UTF8)
    [ordered]@{
        records = $lines.Count
        latest = if ($lines.Count -gt 0) { $lines[-1] | ConvertFrom-Json } else { $null }
    }
} else { $null }
$diagnosticsPath = Join-Path $OutputDir "training_diagnostics.jsonl"
$diagnostics = if (Test-Path -LiteralPath $diagnosticsPath -PathType Leaf) {
    $lines = @(Get-Content -LiteralPath $diagnosticsPath -Encoding UTF8)
    [ordered]@{
        records = $lines.Count
        latest = if ($lines.Count -gt 0) { $lines[-1] | ConvertFrom-Json } else { $null }
    }
} else { $null }
$stderr = @{}
foreach ($name in @("pretrained_receipt", "s3")) {
    $path = Join-Path $ControlDir "$name.stderr.log"
    $stderr[$name] = if (Test-Path -LiteralPath $path -PathType Leaf) {
        [ordered]@{
            bytes = (Get-Item -LiteralPath $path).Length
            tail = [string[]]@(Get-Content -LiteralPath $path -Tail 12 -Encoding UTF8)
        }
    } else { $null }
}
[ordered]@{
    utc = [DateTime]::UtcNow.ToString("o")
    state = $state
    worker_process = $worker
    children = $children
    pretrained_receipt = $receipt
    history = $history
    training_diagnostics = $diagnostics
    final_metrics_exists = Test-Path -LiteralPath (Join-Path $OutputDir "final_metrics.json") -PathType Leaf
    stderr = $stderr
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 12
