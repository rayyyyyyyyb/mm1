$ErrorActionPreference = "Stop"

$gitExe = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$repository = "E:\OV-OrthKD-R3\repo"
$sourceWorktree = "E:\OV-OrthKD-R3\student-shortcut-s4-74d211d"
$candidate = "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0"
$bundle = "E:\OV-OrthKD-R3\student_shortcut_control\a7f0dc0_s7_candidate.bundle"
$expectedCommit = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"
$expectedBundleSha256 = "2a9c1cc290ac1b6f1c66bf195b6e0ca1d5b00f5b261edc1c6f140025352d436c"

if ((Get-FileHash -Algorithm SHA256 -LiteralPath $bundle).Hash.ToLowerInvariant() -ne $expectedBundleSha256) {
    throw "Candidate bundle SHA256 mismatch"
}
if (Test-Path -LiteralPath $candidate) {
    throw "Candidate worktree already exists: $candidate"
}

& $gitExe -C $repository bundle verify $bundle
if ($LASTEXITCODE -ne 0) {
    throw "git bundle verify failed with exit $LASTEXITCODE"
}
& $gitExe -C $repository fetch $bundle $expectedCommit
if ($LASTEXITCODE -ne 0) {
    throw "git fetch from bundle failed with exit $LASTEXITCODE"
}
& $gitExe -C $repository worktree add --detach $candidate $expectedCommit
if ($LASTEXITCODE -ne 0) {
    throw "git worktree add failed with exit $LASTEXITCODE"
}

$junctions = @(
    "external",
    "weights",
    "proposed_method",
    "data\official",
    "data\teacher_cache",
    "data\downloads\hf_cache",
    "data\downloads\incoming",
    "data\ov_ave\exported",
    "data\ov_ave\source"
)
$junctionReceipt = @()
foreach ($relative in $junctions) {
    $source = Join-Path $sourceWorktree $relative
    $destination = Join-Path $candidate $relative
    $sourceItem = Get-Item -LiteralPath $source -Force
    if ($sourceItem.LinkType -ne "Junction" -or @($sourceItem.Target).Count -ne 1) {
        throw "Source asset is not a junction: $source"
    }
    $sourceTarget = [string]@($sourceItem.Target)[0]
    if (Test-Path -LiteralPath $destination) {
        throw "Candidate asset path unexpectedly exists: $destination"
    }
    $destinationParent = Split-Path -Parent $destination
    New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    New-Item -ItemType Junction -Path $destination -Target $sourceTarget | Out-Null
    $destinationItem = Get-Item -LiteralPath $destination -Force
    if (
        $destinationItem.LinkType -ne "Junction" -or
        @($destinationItem.Target).Count -ne 1 -or
        [string]@($destinationItem.Target)[0] -ne $sourceTarget
    ) {
        throw "Candidate junction verification failed: $destination"
    }
    $junctionReceipt += [ordered]@{
        relative_path = $relative
        target = $sourceTarget
        link_type = [string]$destinationItem.LinkType
    }
}

$head = (& $gitExe -C $candidate rev-parse HEAD).Trim()
$dirty = @(& $gitExe -C $candidate status --short)
if ($LASTEXITCODE -ne 0 -or $head -ne $expectedCommit -or $dirty.Count -ne 0) {
    throw "Candidate Git identity/cleanliness verification failed"
}

$receipt = [ordered]@{
    status = "PASS"
    candidate = $candidate
    commit = $head
    dirty_count = $dirty.Count
    bundle_sha256 = $expectedBundleSha256
    junctions = $junctionReceipt
    prepared_utc = [DateTime]::UtcNow.ToString("o")
}
$receiptPath = "E:\OV-OrthKD-R3\student_shortcut_control\s7_candidate_prepare_receipt.json"
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
$receipt | ConvertTo-Json -Depth 8
