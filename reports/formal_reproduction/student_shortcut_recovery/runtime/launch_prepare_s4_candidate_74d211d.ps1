$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\prepare_s4_candidate_74d211d.ps1"
$Control = "E:\OV-OrthKD-R3\student_shortcut_control\candidate_s4_74d211d"
$Worktree = "E:\OV-OrthKD-R3\student-shortcut-s4-74d211d"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "7de00073c4d2c69585e3523722fd4f1980635b3054e6f9664e5df58e3a04bf15"

if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) { throw "Persistent module SHA mismatch" }
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) { throw "S4 candidate worker SHA mismatch" }
if ((Test-Path -LiteralPath $Control) -or (Test-Path -LiteralPath $Worktree)) { throw "Fresh S4 candidate launcher refuses existing targets" }
Import-Module $ModulePath -Force
$created = Start-PersistentPowerShellScript -ScriptPath $WorkerPath
$workerProcessId = [int]$created.ProcessId
Start-Sleep -Seconds 3
$statePath = Join-Path $Control "worker_state.json"
$state = if (Test-Path -LiteralPath $statePath) { Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
if ($null -eq $state -or $state.status -ne "running") { throw "S4 candidate worker did not report running" }
[ordered]@{
    status = "running"
    utc = [DateTime]::UtcNow.ToString("o")
    worker_process_id = $workerProcessId
    return_value = [int]$created.ReturnValue
    module_sha256 = $ExpectedModuleSha
    worker_sha256 = $ExpectedWorkerSha
    state = $state
} | ConvertTo-Json -Depth 7
