param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [Parameter(Mandatory = $true)]
    [string]$Aria2Path
)

$ErrorActionPreference = 'Stop'
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
$Aria2Path = [System.IO.Path]::GetFullPath($Aria2Path)
if (-not (Test-Path -LiteralPath $Aria2Path -PathType Leaf)) {
    throw "aria2 executable does not exist: $Aria2Path"
}

$revision = '607a30d783dfa663caf39e06633721c8d4cfcd7e'
$expectedBytes = 548105171
$expectedSha256 = '248dfc3911869ec493c76e65bf2fcf7f615828b0254c12b473182f0f81d3a707'
$officialUrl = "https://huggingface.co/openai-community/gpt2/resolve/$revision/model.safetensors?download=true"
$mirrorUrl = "https://hf-mirror.com/openai-community/gpt2/resolve/$revision/model.safetensors?download=true"
$targetDir = Join-Path $RepoRoot "data\downloads\incoming\gpt2_$($revision.Substring(0, 8))"
$target = Join-Path $targetDir 'model.safetensors'
$control = $target + '.aria2'
$receiptPath = Join-Path $RepoRoot 'reports\downloads\gpt2_model_download.json'
New-Item -ItemType Directory -Force -Path $targetDir,(Split-Path $receiptPath) | Out-Null

$startedAt = [DateTime]::UtcNow.ToString('o')
$preexistingBytes = if (Test-Path -LiteralPath $target) { (Get-Item $target).Length } else { 0 }
$resumeUsed = $preexistingBytes -gt 0 -or (Test-Path -LiteralPath $control)
$alreadyVerified = $false
if (Test-Path -LiteralPath $target -PathType Leaf) {
    $existing = Get-Item -LiteralPath $target
    if ($existing.Length -eq $expectedBytes) {
        $existingSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
        $alreadyVerified = $existingSha -eq $expectedSha256
    }
}

if (-not $alreadyVerified) {
    & $Aria2Path $mirrorUrl $officialUrl `
        "--dir=$targetDir" '--out=model.safetensors' `
        '--continue=true' '--max-tries=0' '--retry-wait=5' '--timeout=120' `
        '--connect-timeout=120' '--split=8' '--max-connection-per-server=8' `
        '--min-split-size=1M' '--file-allocation=none' '--auto-file-renaming=false' `
        '--allow-overwrite=true' '--check-integrity=true' `
        "--checksum=sha-256=$expectedSha256"
    if ($LASTEXITCODE -ne 0) {
        throw "Pinned GPT-2 model download failed with exit code $LASTEXITCODE"
    }
}

$item = Get-Item -LiteralPath $target -ErrorAction Stop
$actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
if ($item.Length -ne $expectedBytes -or $actualSha256 -ne $expectedSha256) {
    throw "GPT-2 model mismatch: bytes=$($item.Length), sha256=$actualSha256"
}

$receipt = [ordered]@{
    schema_version = 1
    status = 'passed'
    repository = 'openai-community/gpt2'
    revision = $revision
    filename = 'model.safetensors'
    path = $item.FullName
    bytes = $item.Length
    sha256 = $actualSha256
    official_url = $officialUrl
    alternate_urls = @($mirrorUrl)
    started_at = $startedAt
    finished_at = [DateTime]::UtcNow.ToString('o')
    preexisting_bytes = $preexistingBytes
    resume_used = $resumeUsed
    resumptions = if ($resumeUsed) { 1 } else { 0 }
}
$temporary = $receiptPath + '.tmp'
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporary -Encoding UTF8
Move-Item -LiteralPath $temporary -Destination $receiptPath -Force
$receipt | ConvertTo-Json -Depth 6
