$ErrorActionPreference = "Stop"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s9_b8ea747"
$OutputDir = "E:\OV-OrthKD-R3\student-shortcut-s9-b8ea747\outputs\diagnostic\recovery_s9_paper_additive_seed42"
$StatePath = Join-Path $ControlDir "worker_state.json"
$State = if (Test-Path -LiteralPath $StatePath) { Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
$Worker = if ($null -ne $State) { @(Get-CimInstance Win32_Process -Filter "ProcessId=$($State.worker_process_id)" | Select-Object ProcessId,ParentProcessId,Name,CommandLine) } else { @() }
function Read-JsonlTail {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $Lines = @(Get-Content -LiteralPath $Path -Encoding UTF8)
    return [ordered]@{ records=$Lines.Count; latest=if($Lines.Count){$Lines[-1]|ConvertFrom-Json}else{$null} }
}
$Artifacts = @()
foreach ($Name in @("s9_training_audit.json", "s9_zero_training_ae.json", "s9_zero_training_predictions.npz", "s9_posthoc_audit.json")) {
    $Path = Join-Path $ControlDir $Name
    if (Test-Path -LiteralPath $Path -PathType Leaf) { $Artifacts += Get-Item -LiteralPath $Path | Select-Object Name,Length,LastWriteTimeUtc }
}
$CurrentStderr = if ($null -ne $State -and $State.current_phase) { Join-Path $ControlDir ($State.current_phase + ".stderr.log") } else { $null }
[ordered]@{
    utc = [DateTime]::UtcNow.ToString("o")
    state = $State
    worker = $Worker
    history = Read-JsonlTail -Path (Join-Path $OutputDir "history.jsonl")
    training_diagnostics = Read-JsonlTail -Path (Join-Path $OutputDir "training_diagnostics.jsonl")
    diagnostic_checkpoints = if (Test-Path -LiteralPath (Join-Path $OutputDir "diagnostic_checkpoints")) { @(Get-ChildItem -LiteralPath (Join-Path $OutputDir "diagnostic_checkpoints") -Filter "step_*.pt" | Sort-Object Name | Select-Object Name,Length,LastWriteTimeUtc) } else { @() }
    final_metrics_exists = Test-Path -LiteralPath (Join-Path $OutputDir "final_metrics.json") -PathType Leaf
    artifacts = $Artifacts
    current_stderr = if ($CurrentStderr -and (Test-Path -LiteralPath $CurrentStderr)) { [ordered]@{bytes=(Get-Item -LiteralPath $CurrentStderr).Length;tail=[string[]]@(Get-Content -LiteralPath $CurrentStderr -Tail 12 -Encoding UTF8)} } else { $null }
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 14
