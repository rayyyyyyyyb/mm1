$Control = "E:\OV-OrthKD-R3\student_shortcut_control\s3_a0aa4d7"
$Output = "E:\OV-OrthKD-R3\student-shortcut-a0aa4d7\outputs\diagnostic\recovery_s3_pretrained_seed42"
$state = Get-Content -LiteralPath (Join-Path $Control "worker_state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$matching = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*train_ov_orthkd.py*recovery_s3_pretrained_seed42*"
})
$processRows = @()
foreach ($item in $matching) {
    $process = Get-Process -Id ([int]$item.ProcessId) -ErrorAction SilentlyContinue
    $processRows += [ordered]@{
        process_id = [int]$item.ProcessId
        parent_process_id = [int]$item.ParentProcessId
        executable = [string]$item.Name
        cpu_seconds = if ($null -ne $process) { [double]$process.CPU } else { $null }
        working_set_bytes = if ($null -ne $process) { [long]$process.WorkingSet64 } else { $null }
        read_operation_count = [uint64]$item.ReadOperationCount
        read_transfer_count = [uint64]$item.ReadTransferCount
        write_operation_count = [uint64]$item.WriteOperationCount
        write_transfer_count = [uint64]$item.WriteTransferCount
    }
}
$files = if (Test-Path -LiteralPath $Output -PathType Container) {
    @(Get-ChildItem -LiteralPath $Output -File -Force | Select-Object Name, Length, LastWriteTimeUtc)
} else { @() }
[ordered]@{
    utc = [DateTime]::UtcNow.ToString("o")
    state = $state
    processes = $processRows
    output_files = $files
    stderr_tail = if (Test-Path -LiteralPath (Join-Path $Control "s3.stderr.log")) { [string[]]@(Get-Content -LiteralPath (Join-Path $Control "s3.stderr.log") -Tail 12 -Encoding UTF8) } else { @() }
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 8
