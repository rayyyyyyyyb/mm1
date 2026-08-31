$Control = "E:\OV-OrthKD-R3\student_shortcut_control\s3_a0aa4d7"
$Output = "E:\OV-OrthKD-R3\student-shortcut-a0aa4d7\outputs\diagnostic\recovery_s3_pretrained_seed42"
$state = Get-Content -LiteralPath (Join-Path $Control "worker_state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$diagnosticPath = Join-Path $Output "training_diagnostics.jsonl"
$diagnosticLines = @()
if (Test-Path -LiteralPath $diagnosticPath) {
    $diagnosticLines = @(Get-Content -LiteralPath $diagnosticPath -Encoding UTF8)
}
$diagnostic = if ($diagnosticLines.Count) { $diagnosticLines[-1] | ConvertFrom-Json } else { $null }
$historyPath = Join-Path $Output "history.jsonl"
$historyLines = @()
if (Test-Path -LiteralPath $historyPath) {
    $historyLines = @(Get-Content -LiteralPath $historyPath -Encoding UTF8)
}
$history = if ($historyLines.Count) { $historyLines[-1] | ConvertFrom-Json } else { $null }
$stderrTail = @()
if (Test-Path -LiteralPath (Join-Path $Control "s3.stderr.log")) {
    $stderrTail = @(
        Get-Content -LiteralPath (Join-Path $Control "s3.stderr.log") -Tail 4 -Encoding UTF8
    )
}
$compactDiagnostic = if ($null -ne $diagnostic) {
    [ordered]@{
        epoch = [int]$diagnostic.epoch
        batch_index = [int]$diagnostic.batch_index
        global_step_before_update = [int]$diagnostic.global_step_before_update
        logit_mean = [double]$diagnostic.temporal_logits.logits.mean
        logit_std = [double]$diagnostic.temporal_logits.logits.std
        positive_logit_mean = [double]$diagnostic.temporal_logits.positive.mean
        negative_logit_mean = [double]$diagnostic.temporal_logits.negative.mean
        within_sample_logit_std_mean = [double]$diagnostic.temporal_logits.within_sample_logit_std.mean
        visual_gate_mean = [double]$diagnostic.gates.visual.mean
        gate_entropy_mean = [double]$diagnostic.gates.entropy.mean
        gate_saturation_rate = [double]$diagnostic.gates.saturation_rate_at_0_95
        visual_encoder_grad = [double]$diagnostic.gradient_l2_before_clip.student_visual_encoder
        audio_encoder_grad = [double]$diagnostic.gradient_l2_before_clip.student_audio_encoder
        temporal_encoder_grad = [double]$diagnostic.gradient_l2_before_clip.student_temporal_encoder
        segment_head_grad = [double]$diagnostic.gradient_l2_before_clip.student_segment_head
    }
} else { $null }
[ordered]@{
    utc = [DateTime]::UtcNow.ToString("o")
    state = $state
    diagnostic_records = $diagnosticLines.Count
    latest_diagnostic = $compactDiagnostic
    history_records = $historyLines.Count
    latest_history = $history
    final_metrics_exists = Test-Path -LiteralPath (Join-Path $Output "final_metrics.json")
    stderr_tail = [string[]]$stderrTail
    gpu = @(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)
} | ConvertTo-Json -Depth 8
