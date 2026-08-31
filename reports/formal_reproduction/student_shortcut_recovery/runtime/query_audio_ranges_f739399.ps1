$Control = "E:\OV-OrthKD-R3\student_shortcut_control\audio_ranges_f739399"
$StatePath = Join-Path $Control "worker_state.json"
$ReceiptPath = Join-Path $Control "download_receipt.json"
$state = if (Test-Path -LiteralPath $StatePath) { Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
$receipt = if (Test-Path -LiteralPath $ReceiptPath) { Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
$partBytes = if ($null -ne $state) { @($state.parts | ForEach-Object { [long]$_.bytes }) } else { @() }
$process = if ($null -ne $state) { Get-Process -Id ([int]$state.process_id) -ErrorAction SilentlyContinue } else { $null }
[ordered]@{
    utc = [DateTime]::UtcNow.ToString("o")
    status = if ($null -ne $state) { [string]$state.status } else { $null }
    message = if ($null -ne $state) { [string]$state.message } else { $null }
    worker_process_id = if ($null -ne $state) { [int]$state.process_id } else { $null }
    worker_alive = $null -ne $process
    expected_bytes = if ($null -ne $state) { [long]$state.expected_bytes } else { $null }
    downloaded_bytes = [long](($partBytes | Measure-Object -Sum).Sum)
    part_bytes = $partBytes
    receipt_status = if ($null -ne $receipt) { [string]$receipt.status } else { $null }
    receipt_bytes = if ($null -ne $receipt) { [long]$receipt.bytes } else { $null }
    receipt_sha256 = if ($null -ne $receipt) { [string]$receipt.sha256 } else { $null }
    stderr = if (Test-Path -LiteralPath (Join-Path $Control "stderr.log")) { [string[]]@(Get-Content -LiteralPath (Join-Path $Control "stderr.log") -Tail 12 -Encoding UTF8) } else { $null }
} | ConvertTo-Json -Depth 4
