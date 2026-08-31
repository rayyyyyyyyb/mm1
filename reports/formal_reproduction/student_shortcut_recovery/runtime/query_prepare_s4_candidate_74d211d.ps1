$ErrorActionPreference = "Stop"
$Control = "E:\OV-OrthKD-R3\student_shortcut_control\candidate_s4_74d211d"
$Worktree = "E:\OV-OrthKD-R3\student-shortcut-s4-74d211d"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$StatePath = Join-Path $Control "worker_state.json"
$ReceiptPath = Join-Path $Control "verification_receipt.json"
$state = if (Test-Path -LiteralPath $StatePath) { Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
$receipt = if (Test-Path -LiteralPath $ReceiptPath) { Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
$worker = if ($null -ne $state) { @(Get-CimInstance Win32_Process -Filter "ProcessId=$($state.worker_process_id)" | Select-Object ProcessId,ParentProcessId,Name,CommandLine) } else { @() }
$focused = Join-Path $Control "focused_pytest.log"
$pytest = Join-Path $Control "pytest.log"
[ordered]@{
    utc = [DateTime]::UtcNow.ToString("o")
    state = $state
    receipt = $receipt
    worker = $worker
    worktree_exists = Test-Path -LiteralPath $Worktree -PathType Container
    git_head = if (Test-Path -LiteralPath $Worktree) { (& $Git -C $Worktree rev-parse HEAD).Trim() } else { $null }
    git_dirty_lines = if (Test-Path -LiteralPath $Worktree) { @(& $Git -C $Worktree status --porcelain=v1 --untracked-files=all).Count } else { $null }
    focused_tail = if (Test-Path -LiteralPath $focused) { [string[]]@(Get-Content -LiteralPath $focused -Tail 8 -Encoding UTF8) } else { @() }
    pytest_tail = if (Test-Path -LiteralPath $pytest) { [string[]]@(Get-Content -LiteralPath $pytest -Tail 8 -Encoding UTF8) } else { @() }
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 10
