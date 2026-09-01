$ErrorActionPreference = "Stop"

$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$Repository = "E:\OV-OrthKD-R3\repo"
$SourceWorktree = "E:\OV-OrthKD-R3\zero-training-c181ffb"
$Candidate = "E:\OV-OrthKD-R3\student-shortcut-s9-b8ea747"
$Bundle = "E:\OV-OrthKD-R3\student_shortcut_control\s9_b8ea747.bundle"
$ReceiptPath = "E:\OV-OrthKD-R3\student_shortcut_control\s9_b8ea747_prepare.json"
$ExpectedCommit = "b8ea747dd792c939251152ead734d1826c26980d"
$ExpectedBundleSha = "74877219e5757c21d39f3a576d5a053f1d32ca1979431f1934f9e7c982f39310"

if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Bundle).Hash.ToLowerInvariant() -ne $ExpectedBundleSha) {
    throw "S9 bundle SHA mismatch"
}
if (Test-Path -LiteralPath $Candidate) { throw "S9 candidate already exists" }
if (Test-Path -LiteralPath $ReceiptPath) { throw "S9 prepare receipt already exists" }

& $Git -C $Repository bundle verify $Bundle
if ($LASTEXITCODE -ne 0) { throw "bundle verify failed: $LASTEXITCODE" }
& $Git -C $Repository fetch $Bundle $ExpectedCommit
if ($LASTEXITCODE -ne 0) { throw "bundle fetch failed: $LASTEXITCODE" }
& $Git -C $Repository worktree add --detach $Candidate $ExpectedCommit
if ($LASTEXITCODE -ne 0) { throw "worktree add failed: $LASTEXITCODE" }

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
        throw "Source is not exact junction: $Source"
    }
    $SourceTarget = [string]@($SourceItem.Target)[0]
    if (Test-Path -LiteralPath $Destination) {
        throw "Candidate asset exists: $Destination"
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    New-Item -ItemType Junction -Path $Destination -Target $SourceTarget | Out-Null
    $DestinationItem = Get-Item -LiteralPath $Destination -Force
    if (
        $DestinationItem.LinkType -ne "Junction" -or
        @($DestinationItem.Target).Count -ne 1 -or
        [string]@($DestinationItem.Target)[0] -ne $SourceTarget
    ) {
        throw "Junction verification failed: $Destination"
    }
    $JunctionReceipt += [ordered]@{
        relative_path = $Relative
        target = $SourceTarget
        link_type = [string]$DestinationItem.LinkType
    }
}

$Head = (& $Git -C $Candidate rev-parse HEAD).Trim()
$Dirty = @(& $Git -C $Candidate status --porcelain=v1 --untracked-files=all)
if ($Head -ne $ExpectedCommit -or $Dirty.Count -ne 0) {
    throw "Candidate identity/cleanliness failed: $Head dirty=$($Dirty.Count)"
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
