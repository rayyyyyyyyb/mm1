$ErrorActionPreference = "Stop"

$ExpectedCommit = "c181ffb3297ff480a0d01186c626acce7c66afff"
$RepoRoot = "E:\OV-OrthKD-R3\zero-training-c181ffb"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$ControlRoot = "E:\OV-OrthKD-R3\zero_training_control\c181ffb"
$WorkerControl = Join-Path $ControlRoot "worker"
$Results = Join-Path $ControlRoot "results"
$PreflightReceipt = Join-Path $ControlRoot "preflight_receipt.json"
$PrepareReceipt = Join-Path $ControlRoot "prepare_receipt.json"
$VerificationReceipt = Join-Path $ControlRoot "verification\verification_receipt.json"
$PrepareScript = "E:\OV-OrthKD-R3\zero_training_control\prepare_zero_training_candidate_c181ffb.ps1"
$VerifyScript = "E:\OV-OrthKD-R3\zero_training_control\verify_zero_training_candidate_c181ffb.ps1"
$WorkerScript = "E:\OV-OrthKD-R3\zero_training_control\run_zero_training_worker_c181ffb.ps1"
$QueryScript = "E:\OV-OrthKD-R3\zero_training_control\query_zero_training_c181ffb.ps1"

$ExpectedRawSha = [ordered]@{
    $PrepareScript = "4394515070cf9048cfa75eb9c24f16580ae52692f39a7cb4620079df15e6d127"
    $VerifyScript = "e5ebb4bf5becaf0e5f8bde48da98a838300482d2dfcd6adaf85ed4adf3cd2ddf"
    $PrepareReceipt = "ed5f3fb11dce56a4c36ab682f2ca4fed69b71f1715491995a20815b3217ea3d2"
    $VerificationReceipt = "a4816b7e2d72572f9a9a218fa531f7b392b6066a4e2dd34d7f217393abb2fbb5"
    $ModulePath = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
    $Python = "21bb438c0d4a6f1f164b9a646f6ee000340185e5871180aec06db8d3f07c0082"
    $Git = "78211c7ed73988da93a6d8a33d47ec6187f464d7ea2a9a00c182bbd7a1ecf30f"
}
$ExpectedNormalizedSha = [ordered]@{
    (Join-Path $RepoRoot "scripts\diagnose_s7_zero_training.py") = "e09d0cc91f465510506e793f635a73720c7b1a3ef2759c5bce3f25c1d1f7a30a"
    (Join-Path $RepoRoot "scripts\diagnose_full_projector_probe.py") = "30bef63e83e9187ae031c6c0b367e5e89533119aad06ea6a448cc65d345ffc02"
    (Join-Path $RepoRoot "scripts\audit_zero_training_evidence.py") = "8bae0c501e5c56aff634a3e18404a5c09d405034660a7efc94382935e4411e41"
    $WorkerScript = "e572bd314a1188b0a9f5eb9a7511d2cfdd4b10565fe4b586aac090b2b49a5a18"
    $QueryScript = "d0c797f489d1fc69d60ecfb681a3508f808ab6211dffdcaa3acdd92d92c3e82a"
}
$LockedSources = [ordered]@{
    "E:\OV-OrthKD-R3\student_shortcut_control\s7_a7f0dc0\s7_training_artifact_audit.json" = "6583c7f403041be961bba5a40dd7f7e4c8f8d38fd1fee2c7548396b5b6e30dc2"
    "E:\OV-OrthKD-R3\student_shortcut_control\s7_posthoc_a7f0dc0_results\s7_checkpoint_trajectory.json" = "74fd36bafd08d0d30e0e165c886e02b84fa94ac092b359399714d71e360be992"
    "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0\outputs\diagnostic\recovery_s7_temporal_identity_seed42\resolved_config.yaml" = "6453f0c0c2bf9d09c8ac19089ffff60a5bf044be2cee5b76fa0750406889d366"
    "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0\outputs\diagnostic\recovery_s7_temporal_identity_seed42\best.pt" = "60cfb52dfb366e315feeee3e704c996793636ba8b802e7b7d92072ba19bbf572"
    "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0\outputs\diagnostic\recovery_s7_temporal_identity_seed42\diagnostic_checkpoints\step_000400.pt" = "c4c591b4f4a4cdfbe0586939de803db8c27901a9c4c5be47ec3f55c59cf75c26"
    "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0\outputs\diagnostic\recovery_s7_temporal_identity_seed42\diagnostic_checkpoints\step_000800.pt" = "d100d89f7e816005f85a4e4b66f9b1d34c2dd71b5cfd3723ec05dbb48ad445e0"
    "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0\outputs\diagnostic\recovery_s7_temporal_identity_seed42\diagnostic_checkpoints\step_001200.pt" = "1a65c41b23ac854ec7568ec308ef444469a21130a115e25c24c7f98e38e2c958"
    "E:\OV-OrthKD-R3\formal-canonical-31b86c0\outputs\formal\mm26_canonical_seed42\resolved_config.yaml" = "9d7ed87ac27303596f70463f56bba95a0bee687bc328f2ec0f14930dc2e66dc7"
    "E:\OV-OrthKD-R3\formal-canonical-31b86c0\outputs\formal\mm26_canonical_seed42\best.pt" = "01cdb036ec11768ced94331742490d62c1f62bf842b2b2ee03134101dba1f392"
}
$ExpectedJunctions = [ordered]@{
    "external" = "E:\OV-OrthKD-R3\repo\external"
    "weights" = "E:\OV-OrthKD-R3\repo\weights"
    "proposed_method" = "E:\OV-OrthKD-R3\repo\external\OV-AVEL\proposed_method"
    "data\official" = "E:\OV-OrthKD-R3\repo\data\official"
    "data\teacher_cache" = "E:\OV-OrthKD-R3\repo\data\teacher_cache"
    "data\downloads\hf_cache" = "E:\OV-OrthKD-R3\repo\data\downloads\hf_cache"
    "data\downloads\incoming" = "E:\OV-OrthKD-R3\repo\data\downloads\incoming"
    "data\ov_ave\exported" = "E:\OV-OrthKD-R3\repo\data\ov_ave\exported"
    "data\ov_ave\source" = "E:\OV-OrthKD-R3\repo\data\ov_ave\source"
}

function Get-NormalizedTextSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8).Replace("`r`n", "`n")
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text)))).Replace("-", "").ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Assert-RawHashes {
    param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$Files)
    foreach ($path in $Files.Keys) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Locked file is missing: $path" }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $Files[$path]) { throw "Locked file SHA256 mismatch: $path :: $actual" }
    }
}

if (Test-Path -LiteralPath $PreflightReceipt) { throw "Preflight receipt already exists" }
if ((Test-Path -LiteralPath $WorkerControl) -or (Test-Path -LiteralPath $Results)) {
    throw "Preflight refuses existing worker/results directories"
}
Assert-RawHashes -Files $ExpectedRawSha
Assert-RawHashes -Files $LockedSources
foreach ($path in $ExpectedNormalizedSha.Keys) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Normalized source is missing: $path" }
    $actual = Get-NormalizedTextSha256 -Path $path
    if ($actual -ne $ExpectedNormalizedSha[$path]) { throw "Normalized source SHA256 mismatch: $path :: $actual" }
}

$prepare = Get-Content -LiteralPath $PrepareReceipt -Raw -Encoding UTF8 | ConvertFrom-Json
$verification = Get-Content -LiteralPath $VerificationReceipt -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    $prepare.status -ne "PASS" -or
    $prepare.commit -ne $ExpectedCommit -or
    [int]$prepare.dirty_count -ne 0 -or
    @($prepare.junctions).Count -ne 9
) { throw "Prepare receipt did not satisfy the gate" }
if (
    $verification.status -ne "PASS" -or
    $verification.commit_before -ne $ExpectedCommit -or
    $verification.commit_after -ne $ExpectedCommit -or
    [int]$verification.dirty_before -ne 0 -or
    [int]$verification.dirty_after -ne 0 -or
    [int]$verification.compileall_exit -ne 0 -or
    [int]$verification.pytest_exit -ne 0
) { throw "Verification receipt did not satisfy the gate" }

$head = (& $Git -C $RepoRoot rev-parse HEAD).Trim()
$dirty = @(& $Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) { throw "Candidate is not exact and clean" }
$junctionReceipt = @()
foreach ($relative in $ExpectedJunctions.Keys) {
    $path = Join-Path $RepoRoot $relative
    $item = Get-Item -LiteralPath $path -Force
    if (
        $item.LinkType -ne "Junction" -or
        @($item.Target).Count -ne 1 -or
        [string]@($item.Target)[0] -ne $ExpectedJunctions[$relative]
    ) { throw "Candidate junction mismatch: $relative" }
    $junctionReceipt += [ordered]@{
        relative_path = $relative
        target = [string]@($item.Target)[0]
        link_type = [string]$item.LinkType
    }
}

foreach ($script in @(
    "scripts\diagnose_s7_zero_training.py",
    "scripts\diagnose_full_projector_probe.py",
    "scripts\audit_zero_training_evidence.py"
)) {
    & $Python (Join-Path $RepoRoot $script) --help 1> $null 2> $null
    if ($LASTEXITCODE -ne 0) { throw "CLI help failed: $script" }
}
$cudaIdentity = @(& $Python -c "import json, torch; assert torch.cuda.is_available(); print(json.dumps({'torch':torch.__version__,'cuda':torch.version.cuda,'device':torch.cuda.get_device_name(0),'capability':list(torch.cuda.get_device_capability(0))}))")
if ($LASTEXITCODE -ne 0 -or $cudaIdentity.Count -ne 1) { throw "CUDA identity probe failed" }
$cuda = $cudaIdentity[0] | ConvertFrom-Json
if ($cuda.device -ne "NVIDIA GeForce RTX 5090") { throw "Unexpected GPU: $($cuda.device)" }
$conflicts = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*diagnose_s7_zero_training.py*" -or
    $_.CommandLine -like "*diagnose_full_projector_probe.py*" -or
    $_.CommandLine -like "*audit_zero_training_evidence.py*" -or
    $_.CommandLine -like "*run_zero_training_worker_c181ffb.ps1*"
})
if ($conflicts.Count -ne 0) { throw "Conflicting zero-training process is already running" }

$receipt = [ordered]@{
    schema_version = 1
    status = "READY"
    claim_level = "execution_preflight_only"
    git_commit = $ExpectedCommit
    git_dirty_count = $dirty.Count
    python_version = (& $Python --version 2>&1 | Out-String).Trim()
    python_sha256 = $ExpectedRawSha[$Python]
    git_sha256 = $ExpectedRawSha[$Git]
    cuda = $cuda
    prepare_receipt_sha256 = $ExpectedRawSha[$PrepareReceipt]
    verification_receipt_sha256 = $ExpectedRawSha[$VerificationReceipt]
    worker_normalized_sha256 = $ExpectedNormalizedSha[$WorkerScript]
    query_normalized_sha256 = $ExpectedNormalizedSha[$QueryScript]
    source_sha256 = $LockedSources
    junctions = $junctionReceipt
    active_conflict_count = $conflicts.Count
    outputs_absent = $true
    checked_utc = [DateTime]::UtcNow.ToString("o")
}
$receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $PreflightReceipt -Encoding UTF8
$receipt | ConvertTo-Json -Depth 10
