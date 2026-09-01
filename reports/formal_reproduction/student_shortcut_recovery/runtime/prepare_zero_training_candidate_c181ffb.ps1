$ErrorActionPreference = "Stop"

$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$Repository = "E:\OV-OrthKD-R3\repo"
$SourceWorktree = "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0"
$Candidate = "E:\OV-OrthKD-R3\zero-training-c181ffb"
$Bundle = "E:\OV-OrthKD-R3\zero_training_control\zero_training_c181ffb.bundle"
$ControlRoot = "E:\OV-OrthKD-R3\zero_training_control\c181ffb"
$ExpectedCommit = "c181ffb3297ff480a0d01186c626acce7c66afff"
$ExpectedBundleSha256 = "3810e473a8e80f8e5e93cb8de03ce0d49340f499cd867b0a1a8262c9e9a8be20"

if (-not (Test-Path -LiteralPath $Bundle -PathType Leaf)) {
    throw "Candidate bundle is missing: $Bundle"
}
if ((Get-FileHash -LiteralPath $Bundle -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedBundleSha256) {
    throw "Candidate bundle SHA256 mismatch"
}
if (Test-Path -LiteralPath $Candidate) {
    throw "Candidate worktree already exists: $Candidate"
}
if (Test-Path -LiteralPath $ControlRoot) {
    throw "Zero-training control root already exists: $ControlRoot"
}
foreach ($required in @($Git, $Repository, $SourceWorktree)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required prepare path is missing: $required"
    }
}

& $Git -C $Repository bundle verify $Bundle
if ($LASTEXITCODE -ne 0) { throw "git bundle verify failed with exit $LASTEXITCODE" }
& $Git -C $Repository fetch $Bundle $ExpectedCommit
if ($LASTEXITCODE -ne 0) { throw "git fetch from bundle failed with exit $LASTEXITCODE" }
& $Git -C $Repository worktree add --detach $Candidate $ExpectedCommit
if ($LASTEXITCODE -ne 0) { throw "git worktree add failed with exit $LASTEXITCODE" }

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
    $source = Join-Path $SourceWorktree $relative
    $destination = Join-Path $Candidate $relative
    $sourceItem = Get-Item -LiteralPath $source -Force
    if ($sourceItem.LinkType -ne "Junction" -or @($sourceItem.Target).Count -ne 1) {
        throw "Source asset is not a single-target junction: $source"
    }
    $sourceTarget = [string]@($sourceItem.Target)[0]
    if (Test-Path -LiteralPath $destination) {
        throw "Candidate asset path unexpectedly exists: $destination"
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
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

$head = (& $Git -C $Candidate rev-parse HEAD).Trim()
$dirty = @(& $Git -C $Candidate status --porcelain=v1 --untracked-files=all)
if ($head -ne $ExpectedCommit -or $dirty.Count -ne 0) {
    throw "Prepared candidate is not exact and clean"
}
New-Item -ItemType Directory -Path $ControlRoot | Out-Null
$receipt = [ordered]@{
    schema_version = 1
    status = "PASS"
    candidate = $Candidate
    commit = $head
    dirty_count = $dirty.Count
    bundle_sha256 = $ExpectedBundleSha256
    junctions = $junctionReceipt
    prepared_utc = [DateTime]::UtcNow.ToString("o")
}
$receiptPath = Join-Path $ControlRoot "prepare_receipt.json"
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
$receipt | ConvertTo-Json -Depth 8
