$ErrorActionPreference = "Stop"

$testRoot = [IO.Path]::GetFullPath("E:\OV-OrthKD-R3\d2-gate-test-c0dca35")
$repo = [IO.Path]::GetFullPath((Join-Path $testRoot "repo"))
$verification = Join-Path $testRoot "verification"
$shared = "E:\OV-OrthKD-R3\repo"
$git = "E:\OV-OrthKD-R0\env\Git\cmd\git.exe"

if (-not $repo.StartsWith($testRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Resolved repo is outside the intended test root: $repo"
}
if (-not (Test-Path -LiteralPath $git -PathType Leaf)) {
    throw "Git executable is missing: $git"
}

New-Item -ItemType Directory -Path $verification -Force | Out-Null

$targets = [ordered]@{
    "data\downloads" = Join-Path $shared "data\downloads"
    "data\official" = Join-Path $shared "data\official"
    "data\teacher_cache" = Join-Path $shared "data\teacher_cache"
    "data\ov_ave\exported" = Join-Path $shared "data\ov_ave\exported"
    "data\ov_ave\source" = Join-Path $shared "data\ov_ave\source"
    "weights" = Join-Path $shared "weights"
    "external" = Join-Path $shared "external"
    "proposed_method" = Join-Path $shared "external\OV-AVEL\proposed_method"
}

foreach ($target in $targets.Values) {
    if (-not (Test-Path -LiteralPath $target)) {
        throw "Shared target is missing: $target"
    }
}

$downloadPath = Join-Path $repo "data\downloads"
$backupRoot = Join-Path $verification "deployment_backup"
$backupPath = Join-Path $backupRoot "downloads_tracked"
if (Test-Path -LiteralPath $downloadPath) {
    $downloadItem = Get-Item -LiteralPath $downloadPath
    if (-not ($downloadItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
        if (Test-Path -LiteralPath $backupPath) {
            throw "Refusing existing backup path: $backupPath"
        }
        Move-Item -LiteralPath $downloadPath -Destination $backupPath
    }
}

foreach ($entry in $targets.GetEnumerator()) {
    $destination = Join-Path $repo $entry.Key
    if (Test-Path -LiteralPath $destination) {
        $item = Get-Item -LiteralPath $destination
        if (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Refusing non-link destination: $destination"
        }
    }
    else {
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        New-Item -ItemType Junction -Path $destination -Target $entry.Value | Out-Null
    }
}

$before = [ordered]@{}
Get-ChildItem -LiteralPath (Join-Path $backupPath "manual_sources") -File | ForEach-Object {
    $before[$_.Name] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$after = [ordered]@{}
Get-ChildItem -LiteralPath (Join-Path $downloadPath "manual_sources") -File | ForEach-Object {
    $after[$_.Name] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
foreach ($name in $before.Keys) {
    if ($after[$name] -ne $before[$name]) {
        throw "Shared/manual source hash mismatch: $name"
    }
}

$status = @(& $git -C $repo status --short)
if ($LASTEXITCODE -ne 0) {
    throw "git status failed with exit code $LASTEXITCODE"
}
if ($status.Count -ne 0) {
    throw "Candidate worktree is not clean after linking: $($status -join '; ')"
}

$links = @(
    foreach ($entry in $targets.GetEnumerator()) {
        $destination = Join-Path $repo $entry.Key
        $item = Get-Item -LiteralPath $destination
        [ordered]@{
            relative_path = $entry.Key
            link_type = $item.LinkType
            target = [string]$item.Target
        }
    }
)

$archive = Join-Path (Split-Path -Parent $testRoot) "d2_gate_candidate_c0dca35.zip"
$receipt = [ordered]@{
    schema_version = 1
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    test_root = $testRoot
    candidate_archive_sha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    manual_source_hashes_before = $before
    manual_source_hashes_after = $after
    links = $links
    git_status_lines = $status
}
$receiptPath = Join-Path $verification "deployment_receipt.json"
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
$receipt | ConvertTo-Json -Depth 6
