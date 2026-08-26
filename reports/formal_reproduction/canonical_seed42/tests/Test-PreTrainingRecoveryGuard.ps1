$ErrorActionPreference = "Stop"
$modulePath = Join-Path (Split-Path -Parent $PSScriptRoot) "PersistentProcess.psm1"
Import-Module $modulePath -Force

$testRoot = Join-Path $env:TEMP ("ov-orthkd-pretraining-recovery-" + [Guid]::NewGuid().ToString("N"))
$outputDir = Join-Path $testRoot "output"
$workerStatePath = Join-Path $testRoot "worker_state.json"
$stdoutPath = Join-Path $testRoot "stdout.log"
$stderrPath = Join-Path $testRoot "stderr.log"
$expectedCacheHash = "6707900b5d4acb39752baeea11cd1e90d8d3394600b1fa3a6cc3984223860244"

try {
    New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
    $allowed = @(
        "claim_level.txt",
        "config_resolved.yaml",
        "cuda_environment.json",
        "experiment_variant.json",
        "git_state.json",
        "lock_hashes.json",
        "manifest_hashes.json",
        "official_evaluator_hash.json",
        "requirements_freeze.txt",
        "resolved_config.yaml",
        "runtime.json"
    )
    foreach ($name in $allowed) {
        Set-Content -LiteralPath (Join-Path $outputDir $name) -Value "fixture" -Encoding ASCII
    }
    [ordered]@{
        path = "fixture"
        exists = $true
        schema_version = 1
        files = 99334
        bytes = 1310102478
        sha256 = $expectedCacheHash
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $outputDir "teacher_cache_hash.json") -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $outputDir "train.log") `
        -Value "[2026-08-26 01:05:02,404] INFO: Using device: cuda" -Encoding UTF8
    [ordered]@{
        status = "failed"
        exit_code = 1
        message = "System.Management.Automation.RemoteException: [2026-08-26 01:05:02,404] INFO: Using device: cuda"
    } | ConvertTo-Json | Set-Content -LiteralPath $workerStatePath -Encoding UTF8
    New-Item -ItemType File -Path $stdoutPath, $stderrPath | Out-Null

    $result = Assert-CanonicalPreTrainingRecovery `
        -OutputDirectory $outputDir `
        -WorkerStatePath $workerStatePath `
        -StandardOutputPath $stdoutPath `
        -StandardErrorPath $stderrPath `
        -ExpectedCacheHash $expectedCacheHash
    if ($result.file_count -ne 13) {
        throw "Expected exactly 13 static evidence files"
    }

    Set-Content -LiteralPath (Join-Path $outputDir "history.jsonl") -Value "{}" -Encoding ASCII
    $rejectedHistory = $false
    try {
        Assert-CanonicalPreTrainingRecovery `
            -OutputDirectory $outputDir `
            -WorkerStatePath $workerStatePath `
            -StandardOutputPath $stdoutPath `
            -StandardErrorPath $stderrPath `
            -ExpectedCacheHash $expectedCacheHash | Out-Null
    } catch {
        $rejectedHistory = $true
    }
    if (-not $rejectedHistory) {
        throw "Recovery guard accepted a history file"
    }
    Write-Output "PRETRAINING_RECOVERY_GUARD_TEST=PASS"
} finally {
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
