$ErrorActionPreference = "Stop"

$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$Repository = "E:\OV-OrthKD-R3\repo"
$SourceWorktree = "E:\OV-OrthKD-R3\zero-training-c181ffb"
$Candidate = "E:\OV-OrthKD-R3\student-shortcut-s8-60100c6"
$Bundle = "E:\OV-OrthKD-R3\student_shortcut_control\s8_60100c6.bundle"
$ReceiptPath = "E:\OV-OrthKD-R3\student_shortcut_control\s8_60100c6_prepare.json"
$ExpectedCommit = "60100c6fff95b313ae92bc91b10a3be7135dc437"
$ExpectedBundleSha = "f0a9675b1122086f5a8e0302f389c98826cb9b668d5403d19cc6c8bc7da61868"

if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Bundle).Hash.ToLowerInvariant() -ne $ExpectedBundleSha) {
    throw "S8 candidate bundle SHA256 mismatch"
}
if (Test-Path -LiteralPath $Candidate) {
    throw "S8 candidate already exists: $Candidate"
}
if (Test-Path -LiteralPath $ReceiptPath) {
    throw "S8 prepare receipt already exists: $ReceiptPath"
}

& $Git -C $Repository bundle verify $Bundle
if ($LASTEXITCODE -ne 0) { throw "git bundle verify failed with exit $LASTEXITCODE" }
& $Git -C $Repository fetch $Bundle $ExpectedCommit
if ($LASTEXITCODE -ne 0) { throw "git fetch from bundle failed with exit $LASTEXITCODE" }
& $Git -C $Repository worktree add --detach $Candidate $ExpectedCommit
if ($LASTEXITCODE -ne 0) { throw "git worktree add failed with exit $LASTEXITCODE" }

$Junctions = @(
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
$JunctionReceipt = @()
foreach ($Relative in $Junctions) {
    $Source = Join-Path $SourceWorktree $Relative
    $Destination = Join-Path $Candidate $Relative
    $SourceItem = Get-Item -LiteralPath $Source -Force
    if ($SourceItem.LinkType -ne "Junction" -or @($SourceItem.Target).Count -ne 1) {
        throw "S8 source asset is not an exact junction: $Source"
    }
    $SourceTarget = [string]@($SourceItem.Target)[0]
    if (Test-Path -LiteralPath $Destination) {
        throw "S8 candidate asset path unexpectedly exists: $Destination"
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    New-Item -ItemType Junction -Path $Destination -Target $SourceTarget | Out-Null
    $DestinationItem = Get-Item -LiteralPath $Destination -Force
    if (
        $DestinationItem.LinkType -ne "Junction" -or
        @($DestinationItem.Target).Count -ne 1 -or
        [string]@($DestinationItem.Target)[0] -ne $SourceTarget
    ) {
        throw "S8 candidate junction verification failed: $Destination"
    }
    $JunctionReceipt += [ordered]@{
        relative_path = $Relative
        target = $SourceTarget
        link_type = [string]$DestinationItem.LinkType
    }
}

$Head = (& $Git -C $Candidate rev-parse HEAD).Trim()
$Dirty = @(& $Git -C $Candidate status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0 -or $Head -ne $ExpectedCommit -or $Dirty.Count -ne 0) {
    throw "S8 candidate Git identity/cleanliness verification failed"
}
$Receipt = [ordered]@{
    schema_version = 1
    status = "PASS"
    candidate = $Candidate
    commit = $Head
    dirty_count = $Dirty.Count
    bundle_sha256 = $ExpectedBundleSha
    junctions = $JunctionReceipt
    prepared_utc = [DateTime]::UtcNow.ToString("o")
}
$Receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
$Receipt | ConvertTo-Json -Depth 8
