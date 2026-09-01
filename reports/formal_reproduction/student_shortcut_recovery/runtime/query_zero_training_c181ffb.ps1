$ErrorActionPreference = "Stop"

$ControlRoot = "E:\OV-OrthKD-R3\zero_training_control\c181ffb"
$WorkerControl = Join-Path $ControlRoot "worker"
$Results = Join-Path $ControlRoot "results"
$StatePath = Join-Path $WorkerControl "worker_state.json"
$state = if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
    Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
}
else { $null }
$worker = if ($null -ne $state) {
    @(Get-CimInstance Win32_Process -Filter "ProcessId=$($state.worker_process_id)" | Select-Object ProcessId, ParentProcessId, Name, CommandLine)
}
else { @() }
$artifacts = if (Test-Path -LiteralPath $Results -PathType Container) {
    @(Get-ChildItem -LiteralPath $Results -File | Sort-Object Name | Select-Object Name, Length, LastWriteTimeUtc)
}
else { @() }
$logs = if (Test-Path -LiteralPath $WorkerControl -PathType Container) {
    @(Get-ChildItem -LiteralPath $WorkerControl -File -Filter "*.log" | Sort-Object Name | ForEach-Object {
        [ordered]@{
            name = $_.Name
            bytes = $_.Length
            tail = [string[]]@(Get-Content -LiteralPath $_.FullName -Tail 8 -Encoding UTF8)
        }
    })
}
else { @() }

[ordered]@{
    utc = [DateTime]::UtcNow.ToString("o")
    state = $state
    worker = $worker
    artifacts = $artifacts
    logs = $logs
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 12
