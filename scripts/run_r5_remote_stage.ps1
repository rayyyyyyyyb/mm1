param(
    [ValidateSet("FocusedTests", "AudioTests", "FullTests", "TeacherSmoke", "AudioWindowAudit", "ProbeExport", "StartExport", "StartSidecarExport", "StopExport", "QuarantineExport", "ExportStatus", "CompactStatus", "FailureStatus", "ExportAll", "AuditFull")]
    [string]$Action = "FocusedTests",
    [ValidateSet("val", "test")]
    [string]$SidecarSplit = "val"
)

$ErrorActionPreference = "Stop"
$RepoRoot = "E:\OV-OrthKD-R3\repo"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$MinGit = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd"

foreach ($required in @($RepoRoot, $Python, $MinGit)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required R5 path is missing: $required"
    }
}

$env:Path = "$MinGit;$env:Path"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:TOKENIZERS_PARALLELISM = "false"
Set-Location -LiteralPath $RepoRoot

function Invoke-LockedPython {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Locked Python command failed with exit code ${LASTEXITCODE}: $Arguments"
    }
}

if ($Action -eq "FocusedTests") {
    Invoke-LockedPython -m pytest -q `
        tests/test_r5_final_runtime_protocol.py `
        tests/test_atomic_artifacts.py `
        tests/test_r5_remote_export_supervision.py `
        tests/test_r5_teacher_identity_binding.py `
        tests/test_r1_atomic_export.py `
        tests/test_r2_audit_config_contract.py `
        tests/test_r2_canonical_readiness_gate.py `
        tests/test_r2_teacher_export_scaling.py `
        tests/test_r2_teacher_export_lock_binding.py `
        tests/test_r3_conference_reconstruction.py `
        tests/test_r3_internvideo_raw_video.py `
        tests/test_r3_remaining_defects.py `
        tests/test_r4_t10_temporal_protocol.py `
        tests/test_r3_reconstruction_locks.py `
        tests/test_r2_teacher_wrapper_safety.py `
        tests/test_teacher_identity.py `
        tests/test_r5_audio_task_window_audit.py `
        tests/test_reproduction_audit.py
    exit 0
}

if ($Action -eq "TeacherSmoke") {
    Invoke-LockedPython scripts/inspect_teacher_identity.py `
        --config configs/ov_orthkd_mm26_repro.yaml `
        --source-manifest data/ov_ave/source/train.jsonl `
        --record-index 0 `
        --device cuda `
        --repeat 2 `
        --fail-on-unresolved `
        --output reports/teachers/teacher_identity.json `
        --repeatability-output reports/teachers/smoke_repeatability.json
    exit 0
}

if ($Action -eq "AudioWindowAudit") {
    & $Python scripts/audit_ovave_audio_task_windows.py `
        --path-root . `
        --train-manifest data/ov_ave/source/train.jsonl `
        --val-manifest data/ov_ave/source/val.jsonl `
        --test-manifest data/ov_ave/source/test.jsonl `
        --output reports/data/official_audio_task_window_audit.json |
        Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Audio task-window audit failed with exit code $LASTEXITCODE"
    }
    $audit = Get-Content -LiteralPath `
        "reports\data\official_audio_task_window_audit.json" -Raw |
        ConvertFrom-Json
    [ordered]@{
        status = $audit.status
        record_count = $audit.record_count
        split_counts = $audit.split_counts
        waveform_fit_counts = $audit.waveform_fit_counts
        zero_padding_samples = $audit.zero_padding_samples
        truncated_samples = $audit.truncated_samples
        shortest_waveform = $audit.shortest_waveform
        longest_waveform = $audit.longest_waveform
        errors = @($audit.errors).Count
    } | ConvertTo-Json -Depth 6 -Compress
    exit 0
}

if ($Action -eq "FullTests") {
    Invoke-LockedPython -m pytest -q
    exit 0
}

if ($Action -eq "AudioTests") {
    Invoke-LockedPython -m pytest -q `
        tests/test_r5_audio_task_window_audit.py `
        tests/test_r2_canonical_readiness_gate.py `
        -k audio_task_window
    exit 0
}

if ($Action -eq "ProbeExport") {
    New-Item -ItemType Directory -Force -Path `
        "data\ov_ave\exported", `
        "reports\teachers\receipts", `
        "reports\teachers\errors", `
        "reports\teachers\progress" | Out-Null
    Invoke-LockedPython scripts/export_teacher_artifacts.py `
        --config configs/ov_orthkd_mm26_repro.yaml `
        --source-manifest data/ov_ave/source/train.jsonl `
        --output-manifest data/ov_ave/exported/train.jsonl `
        --receipt-jsonl reports/teachers/receipts/train.jsonl `
        --error-jsonl reports/teachers/errors/train.jsonl `
        --progress-path reports/teachers/progress/train.json `
        --teacher-lock configs/locks/mm26_teacher_lock.yaml `
        --split train `
        --limit 1 `
        --resume
    exit 0
}

if ($Action -eq "StartExport") {
    $supervisor = Join-Path $RepoRoot "scripts\supervise_r5_teacher_export.ps1"
    $stateDir = Join-Path $RepoRoot "reports\teachers\supervisor"
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    $existing = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like "*supervise_r5_teacher_export.ps1*"
    }
    if ($existing) {
        $existing | Select-Object ProcessId, CommandLine | Format-List
        exit 0
    }
    $commandLine = (
        'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass ' +
        "-File `"$supervisor`" -MaxAttempts 100 -RetryDelaySeconds 60"
    )
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create `
        -Arguments @{CommandLine = $commandLine}
    if ($created.ReturnValue -ne 0) {
        throw "Win32_Process.Create failed with return value $($created.ReturnValue)"
    }
    Start-Sleep -Seconds 2
    if (-not (Get-Process -Id $created.ProcessId -ErrorAction SilentlyContinue)) {
        throw "Export supervisor PID $($created.ProcessId) exited immediately"
    }
    [ordered]@{
        status = "started"
        process_id = $created.ProcessId
        supervisor = $supervisor
    } | ConvertTo-Json
    exit 0
}

if ($Action -eq "StartSidecarExport") {
    $supervisor = Join-Path $RepoRoot "scripts\supervise_r5_teacher_split_export.ps1"
    $stateDir = Join-Path $RepoRoot "reports\teachers\supervisor-$SidecarSplit"
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    $existing = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like "*supervise_r5_teacher_split_export.ps1*" -and
        $_.CommandLine -like "*-Split $SidecarSplit*"
    }
    if ($existing) {
        $existing | Select-Object ProcessId, CommandLine | Format-List
        exit 0
    }
    $commandLine = (
        'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass ' +
        "-File `"$supervisor`" -Split $SidecarSplit -MaxAttempts 100 " +
        '-RetryDelaySeconds 60'
    )
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create `
        -Arguments @{CommandLine = $commandLine}
    if ($created.ReturnValue -ne 0) {
        throw "Win32_Process.Create failed with return value $($created.ReturnValue)"
    }
    Start-Sleep -Seconds 2
    if (-not (Get-Process -Id $created.ProcessId -ErrorAction SilentlyContinue)) {
        throw "$SidecarSplit sidecar supervisor PID $($created.ProcessId) exited immediately"
    }
    [ordered]@{
        status = "started"
        split = $SidecarSplit
        process_id = $created.ProcessId
        supervisor = $supervisor
    } | ConvertTo-Json
    exit 0
}

if ($Action -eq "StopExport") {
    $targets = @(
        Get-CimInstance Win32_Process | Where-Object {
            $_.CommandLine -like "*supervise_r5_teacher_export.ps1*" -or
            $_.CommandLine -like "*supervise_r5_teacher_split_export.ps1*" -or
            $_.CommandLine -like "*export_teacher_artifacts.py*"
        }
    )
    $targetIds = @($targets | ForEach-Object { $_.ProcessId })
    foreach ($target in ($targets | Sort-Object ProcessId -Descending)) {
        Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
    }
    [ordered]@{
        status = "stopped"
        process_ids = $targetIds
    } | ConvertTo-Json -Compress
    exit 0
}

if ($Action -eq "QuarantineExport") {
    $running = @(
        Get-CimInstance Win32_Process | Where-Object {
            $_.CommandLine -like "*supervise_r5_teacher_export.ps1*" -or
            $_.CommandLine -like "*supervise_r5_teacher_split_export.ps1*" -or
            $_.CommandLine -like "*export_teacher_artifacts.py*"
        }
    )
    if ($running.Count -ne 0) {
        throw "Cannot quarantine export products while exporter processes are active"
    }
    $quarantineName = "r5-pre-beats-task-window-fix-20260825"
    $moves = @(
        @("data\teacher_cache\mm26", "data\teacher_cache\quarantine\$quarantineName\mm26"),
        @("data\ov_ave\exported", "data\ov_ave\quarantine\$quarantineName\exported"),
        @("reports\teachers\receipts", "reports\teachers\quarantine\$quarantineName\receipts"),
        @("reports\teachers\errors", "reports\teachers\quarantine\$quarantineName\errors"),
        @("reports\teachers\progress", "reports\teachers\quarantine\$quarantineName\progress"),
        @("reports\teachers\supervisor", "reports\teachers\quarantine\$quarantineName\supervisor")
    )
    $moved = @()
    foreach ($move in $moves) {
        $source = [IO.Path]::GetFullPath((Join-Path $RepoRoot $move[0]))
        $destination = [IO.Path]::GetFullPath((Join-Path $RepoRoot $move[1]))
        if (-not $source.StartsWith($RepoRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Quarantine source escapes repository: $source"
        }
        if (-not $destination.StartsWith($RepoRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Quarantine destination escapes repository: $destination"
        }
        if (Test-Path -LiteralPath $source) {
            if (Test-Path -LiteralPath $destination) {
                throw "Quarantine destination already exists: $destination"
            }
            New-Item -ItemType Directory -Force -Path (Split-Path $destination -Parent) |
                Out-Null
            Move-Item -LiteralPath $source -Destination $destination
            $moved += [ordered]@{source = $source; destination = $destination}
        }
    }
    [ordered]@{status = "quarantined"; moved = $moved} |
        ConvertTo-Json -Depth 5 -Compress
    exit 0
}

if ($Action -eq "ExportStatus") {
    $stateDir = Join-Path $RepoRoot "reports\teachers\supervisor"
    $statePath = Join-Path $stateDir "state.json"
    if (Test-Path -LiteralPath $statePath) {
        Get-Content -LiteralPath $statePath -Raw
    } else {
        '{"status":"not_started"}'
    }
    foreach ($split in @("train", "val", "test")) {
        $progress = Join-Path $RepoRoot "reports\teachers\progress\$split.json"
        if (Test-Path -LiteralPath $progress) {
            Get-Content -LiteralPath $progress -Raw
        }
        $receiptDir = Join-Path $RepoRoot "data\teacher_cache\mm26\receipts\$split"
        $receiptCount = @(
            Get-ChildItem -LiteralPath $receiptDir -Filter "*.json" -File `
                -ErrorAction SilentlyContinue
        ).Count
        Write-Output "RECEIPTS_${split}=$receiptCount"
    }
    $cacheRoot = Join-Path $RepoRoot "data\teacher_cache\mm26"
    $cacheFiles = Get-ChildItem -LiteralPath $cacheRoot -File -Recurse `
        -ErrorAction SilentlyContinue
    Write-Output "CACHE_FILES=$(@($cacheFiles).Count)"
    Write-Output "CACHE_BYTES=$(($cacheFiles | Measure-Object -Property Length -Sum).Sum)"
    Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like "*supervise_r5_teacher_export.ps1*" -or
        $_.CommandLine -like "*supervise_r5_teacher_split_export.ps1*" -or
        $_.CommandLine -like "*export_teacher_artifacts.py*"
    } | Select-Object ProcessId, Name, CommandLine | Format-List
    foreach ($logName in @(
        "supervisor.stderr.log",
        "supervisor.stdout.log",
        "export.stderr.log",
        "export.stdout.log"
    )) {
        $logPath = Join-Path $stateDir $logName
        if (Test-Path -LiteralPath $logPath) {
            Write-Output "--- $logName ---"
            Get-Content -LiteralPath $logPath -Tail 40
        }
    }
    exit 0
}

if ($Action -eq "CompactStatus") {
    $stateDir = Join-Path $RepoRoot "reports\teachers\supervisor"
    $statePath = Join-Path $stateDir "state.json"
    $summary = [ordered]@{
        state = if (Test-Path -LiteralPath $statePath) {
            Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        } else {
            [ordered]@{status = "not_started"}
        }
        splits = [ordered]@{}
        cache_files = 0
        cache_bytes = 0
        sidecar_states = [ordered]@{}
        process_ids = @()
    }
    foreach ($split in @("train", "val", "test")) {
        $progress = Join-Path $RepoRoot "reports\teachers\progress\$split.json"
        $receiptDir = Join-Path $RepoRoot "data\teacher_cache\mm26\receipts\$split"
        $summary.splits[$split] = [ordered]@{
            progress = if (Test-Path -LiteralPath $progress) {
                Get-Content -LiteralPath $progress -Raw | ConvertFrom-Json
            } else {
                $null
            }
            receipts = @(
                Get-ChildItem -LiteralPath $receiptDir -Filter "*.json" -File `
                    -ErrorAction SilentlyContinue
            ).Count
        }
    }
    $cacheRoot = Join-Path $RepoRoot "data\teacher_cache\mm26"
    $cacheFiles = @(
        Get-ChildItem -LiteralPath $cacheRoot -File -Recurse `
            -ErrorAction SilentlyContinue
    )
    $summary.cache_files = $cacheFiles.Count
    $summary.cache_bytes = ($cacheFiles | Measure-Object -Property Length -Sum).Sum
    foreach ($split in @("val", "test")) {
        $sidecarState = Join-Path $RepoRoot "reports\teachers\supervisor-$split\state.json"
        $summary.sidecar_states[$split] = if (Test-Path -LiteralPath $sidecarState) {
            Get-Content -LiteralPath $sidecarState -Raw | ConvertFrom-Json
        } else {
            $null
        }
    }
    $summary.process_ids = @(
        Get-CimInstance Win32_Process | Where-Object {
            $_.CommandLine -like "*supervise_r5_teacher_export.ps1*" -or
            $_.CommandLine -like "*supervise_r5_teacher_split_export.ps1*" -or
            $_.CommandLine -like "*export_teacher_artifacts.py*"
        } | ForEach-Object { $_.ProcessId }
    )
    $summary | ConvertTo-Json -Depth 8 -Compress
    exit 0
}

if ($Action -eq "FailureStatus") {
    $stateDir = Join-Path $RepoRoot "reports\teachers\supervisor"
    $stderrPath = Join-Path $stateDir "export.stderr.log"
    $errors = @()
    if (Test-Path -LiteralPath $stderrPath) {
        $errors = @(
            Select-String -LiteralPath $stderrPath `
                -Pattern "^(RuntimeError|ValueError|OSError|FileNotFoundError|MemoryError|torch\.OutOfMemoryError):" `
                -Context 0,3 |
                ForEach-Object {
                    (@($_.Line) + @($_.Context.PostContext) -join " ").Trim()
                } |
                Select-Object -Unique
        )
    }
    [ordered]@{
        state = if (Test-Path -LiteralPath (Join-Path $stateDir "state.json")) {
            Get-Content -LiteralPath (Join-Path $stateDir "state.json") -Raw |
                ConvertFrom-Json
        } else {
            [ordered]@{status = "not_started"}
        }
        unique_exception_lines = $errors
    } | ConvertTo-Json -Depth 6 -Compress
    exit 0
}

if ($Action -eq "ExportAll") {
    New-Item -ItemType Directory -Force -Path `
        "data\ov_ave\exported", `
        "reports\teachers\receipts", `
        "reports\teachers\errors", `
        "reports\teachers\progress" | Out-Null
    foreach ($split in @("train", "val", "test")) {
        Invoke-LockedPython scripts/export_teacher_artifacts.py `
            --config configs/ov_orthkd_mm26_repro.yaml `
            --source-manifest "data/ov_ave/source/$split.jsonl" `
            --output-manifest "data/ov_ave/exported/$split.jsonl" `
            --receipt-jsonl "reports/teachers/receipts/$split.jsonl" `
            --error-jsonl "reports/teachers/errors/$split.jsonl" `
            --progress-path "reports/teachers/progress/$split.json" `
            --teacher-lock configs/locks/mm26_teacher_lock.yaml `
            --split $split `
            --resume
    }
    exit 0
}

if ($Action -eq "AuditFull") {
    Invoke-LockedPython scripts/audit_mm26_reproduction.py `
        --config configs/ov_orthkd_mm26_repro.yaml `
        --preprocessing-lock configs/locks/mm26_preprocessing_lock.yaml `
        --teacher-lock configs/locks/mm26_teacher_lock.yaml `
        --train-manifest data/ov_ave/exported/train.jsonl `
        --val-manifest data/ov_ave/exported/val.jsonl `
        --test-manifest data/ov_ave/exported/test.jsonl `
        --path-root . `
        --stage exported `
        --artifact-scan full `
        --expected-segments auto `
        --fail-on-warning `
        --output-json reports/mm26_exported_artifact_audit.json
    exit 0
}
