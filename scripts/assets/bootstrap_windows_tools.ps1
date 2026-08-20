param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$ToolsRoot = 'E:\OV-OrthKD-R3\tools',
    [string]$PythonPath = 'E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe',
    [string]$GitPath = 'E:\OV-OrthKD-R0\env\Git\cmd\git.exe'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$downloadRoot = Join-Path $ToolsRoot 'downloads'
$quarantineRoot = Join-Path $ToolsRoot 'quarantine'
New-Item -ItemType Directory -Force -Path $ToolsRoot,$downloadRoot,$quarantineRoot | Out-Null
$ariaDownloadPath = (Get-ChildItem -LiteralPath $ToolsRoot -Recurse -Filter aria2c.exe | Select-Object -First 1).FullName
if (-not $ariaDownloadPath) { throw 'Verified aria2c executable is missing' }

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Move-BadDownload([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
        $target = Join-Path $quarantineRoot ((Split-Path -Leaf $Path) + '.' + $stamp)
        Move-Item -LiteralPath $Path -Destination $target
    }
}

function Get-VerifiedDownload(
    [string]$Url,
    [string]$ExpectedSha256,
    [string]$Destination
) {
    $expected = $ExpectedSha256.ToLowerInvariant()
    if (Test-Path -LiteralPath $Destination) {
        if ((Get-Sha256 $Destination) -eq $expected) { return $Destination }
        Move-BadDownload $Destination
    }
    $partial = $Destination + '.partial'
    $partialParent = Split-Path -Parent $partial
    $partialLeaf = Split-Path -Leaf $partial
    & $ariaDownloadPath `
        --continue=true `
        --max-tries=0 `
        --retry-wait=15 `
        --connect-timeout=30 `
        --timeout=120 `
        --lowest-speed-limit=0 `
        --max-file-not-found=5 `
        --auto-file-renaming=false `
        --allow-overwrite=true `
        --file-allocation=none `
        --remote-time=true `
        --check-integrity=true `
        --max-connection-per-server=4 `
        --split=4 `
        --min-split-size=1M `
        "--dir=$partialParent" `
        "--out=$partialLeaf" `
        $Url
    if ($LASTEXITCODE -ne 0) { throw "aria2 failed for ${Url} with exit code $LASTEXITCODE" }
    $actual = Get-Sha256 $partial
    if ($actual -ne $expected) {
        Move-BadDownload $partial
        throw "SHA256 mismatch for ${Url}: expected $expected, got $actual"
    }
    Move-Item -LiteralPath $partial -Destination $Destination
    return $Destination
}

function New-ToolRecord(
    [string]$Path,
    [string]$Version,
    [string]$Source,
    [string]$DistributionSha256 = ''
) {
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        status = 'verified'
        version = $Version.Trim()
        path = $item.FullName
        bytes = $item.Length
        sha256 = Get-Sha256 $item.FullName
        source = $Source
        distribution_sha256 = if ($DistributionSha256) { $DistributionSha256.ToLowerInvariant() } else { $null }
    }
}

$jqVersion = '1.8.2'
$jqSha256 = 'a6fc67fedaf9128a3309a1e2ebb8b986aeccf70122ee46d2cb4849e423f0c627'
$jqRoot = Join-Path $ToolsRoot ('jq-' + $jqVersion)
New-Item -ItemType Directory -Force -Path $jqRoot | Out-Null
$jqPath = Get-VerifiedDownload `
    'https://github.com/jqlang/jq/releases/download/jq-1.8.2/jq-windows-amd64.exe' `
    $jqSha256 (Join-Path $jqRoot 'jq.exe')

$sevenZipVersion = '26.02'
$sevenZipSha256 = '56b8cc9f4971cef253644fafe54063ed7fdca551d4dee0f8c6baa81b855acd72'
$sevenZipRoot = Join-Path $ToolsRoot ('7zip-' + $sevenZipVersion)
New-Item -ItemType Directory -Force -Path $sevenZipRoot | Out-Null
$sevenZipPath = Get-VerifiedDownload `
    'https://github.com/ip7z/7zip/releases/download/26.02/7zr.exe' `
    $sevenZipSha256 (Join-Path $sevenZipRoot '7zr.exe')

$ffmpegUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
$ffmpegShaUrl = $ffmpegUrl + '.sha256'
$ffmpegSha256 = (Invoke-RestMethod -Uri $ffmpegShaUrl).Trim().ToLowerInvariant()
if ($ffmpegSha256 -notmatch '^[0-9a-f]{64}$') { throw 'Invalid FFmpeg SHA256 response' }
$ffmpegZip = Get-VerifiedDownload $ffmpegUrl $ffmpegSha256 `
    (Join-Path $downloadRoot 'ffmpeg-release-essentials.zip')
$ffmpegRoot = Join-Path $ToolsRoot ('ffmpeg-' + $ffmpegSha256.Substring(0, 12))
if (-not (Test-Path -LiteralPath $ffmpegRoot)) {
    $extractRoot = $ffmpegRoot + '.partial.' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
    Expand-Archive -LiteralPath $ffmpegZip -DestinationPath $extractRoot
    Move-Item -LiteralPath $extractRoot -Destination $ffmpegRoot
}
$ffmpegPath = (Get-ChildItem -LiteralPath $ffmpegRoot -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName
if (-not $ffmpegPath) { throw 'FFmpeg executable not found after verified extraction' }

$ariaPath = $ariaDownloadPath
$curlPath = (Get-Command curl.exe -ErrorAction Stop).Source
$gitLfsPath = (Get-ChildItem -LiteralPath (Split-Path (Split-Path $GitPath)) -Recurse -Filter git-lfs.exe | Select-Object -First 1).FullName
if (-not $gitLfsPath) { throw 'Git LFS executable is missing from Git for Windows' }

$tools = [ordered]@{}
$tools.aria2 = New-ToolRecord $ariaPath ((& $ariaPath --version | Select-Object -First 1)) `
    'https://github.com/aria2/aria2/releases/tag/release-1.37.0'
$tools.curl = New-ToolRecord $curlPath ((& $curlPath --version | Select-Object -First 1)) 'windows-system://curl'
$tools.ffmpeg = New-ToolRecord $ffmpegPath ((& $ffmpegPath -version | Select-Object -First 1)) `
    $ffmpegUrl $ffmpegSha256
$tools.git_lfs = New-ToolRecord $gitLfsPath ((& $GitPath lfs version | Select-Object -First 1)) `
    'https://github.com/git-lfs/git-lfs/releases/tag/v3.7.1'
$tools.jq = New-ToolRecord $jqPath ((& $jqPath --version | Select-Object -First 1)) `
    'https://github.com/jqlang/jq/releases/tag/jq-1.8.2' $jqSha256
$tools.python = New-ToolRecord $PythonPath ((& $PythonPath --version 2>&1 | Select-Object -First 1)) `
    'local-verified-environment://OV-OrthKD-R0'
$sevenVersionOutput = (& $sevenZipPath 2>&1 | Select-String -Pattern '^7-Zip' | Select-Object -First 1).Line
$tools.seven_zip = New-ToolRecord $sevenZipPath $sevenVersionOutput `
    'https://github.com/ip7z/7zip/releases/tag/26.02' $sevenZipSha256

$receipt = [ordered]@{
    schema_version = 1
    status = 'ready'
    platform = 'windows'
    generated_at = [DateTime]::UtcNow.ToString('o')
    tools = $tools
    replacements = [ordered]@{
        tmux = @{ status = 'replaced'; by = 'windows_cim_background_process' }
        rsync = @{ status = 'replaced'; by = 'scp_and_hash_verified_copy' }
        wget = @{ status = 'replaced'; by = 'windows_curl' }
    }
}
$reportPath = Join-Path $RepoRoot 'reports\downloads\tool_versions.json'
New-Item -ItemType Directory -Force -Path (Split-Path $reportPath) | Out-Null
$temporary = $reportPath + '.tmp'
$receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporary -Encoding UTF8
Move-Item -LiteralPath $temporary -Destination $reportPath -Force
$receipt | ConvertTo-Json -Depth 10
