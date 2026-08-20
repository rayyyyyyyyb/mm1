param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [string]$PythonPath = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe",
    [string]$Aria2Path = "E:\OV-OrthKD-R3\tools\aria2-1.37.0\aria2-1.37.0-win-64bit-build1\aria2c.exe"
)

$ErrorActionPreference = "Stop"
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable does not exist: $PythonPath"
}

$requirements = @(
    "decord==0.6.0",
    "soundfile==0.12.1",
    "librosa==0.10.1",
    "torchlibrosa==0.1.0",
    "peft==0.20.0",
    "transformers==4.45.1",
    "huggingface-hub==0.36.2"
)

Write-Output "Installing pinned direct teacher dependencies."
& $PythonPath -m pip install --disable-pip-version-check --no-input --timeout 120 --retries 100 `
    --prefer-binary --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple @requirements
if ($LASTEXITCODE -ne 0) {
    throw "Pinned teacher dependency installation failed with exit code $LASTEXITCODE"
}

$revision = "607a30d783dfa663caf39e06633721c8d4cfcd7e"
$cacheRoot = Join-Path $RepoRoot "data\downloads\hf_cache"
$snapshotRoot = Join-Path $cacheRoot "models--openai-community--gpt2\snapshots\$revision"
$hfExe = Join-Path (Split-Path -Parent $PythonPath) "hf.exe"
if (-not (Test-Path -LiteralPath $hfExe -PathType Leaf)) {
    throw "Hugging Face CLI does not exist: $hfExe"
}
$env:HF_ENDPOINT = "https://hf-mirror.com"
$hfArguments = @(
    "download", "openai-community/gpt2",
    "config.json",
    "generation_config.json",
    "merges.txt",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "--revision", $revision,
    "--cache-dir", $cacheRoot,
    "--max-workers", "8"
)

Write-Output "Downloading the six small files from the exact GPT-2 revision."
& $hfExe @hfArguments
if ($LASTEXITCODE -ne 0) {
    throw "Pinned GPT-2 metadata/tokenizer download failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $Aria2Path -PathType Leaf)) {
    throw "aria2 executable does not exist: $Aria2Path"
}
New-Item -ItemType Directory -Force -Path $snapshotRoot | Out-Null
$modelUrl = "https://huggingface.co/openai-community/gpt2/resolve/$revision/model.safetensors?download=true"
$modelMirrorUrl = "https://hf-mirror.com/openai-community/gpt2/resolve/$revision/model.safetensors?download=true"
Write-Output "Downloading GPT-2 model.safetensors with resumable eight-way aria2 transfer."
& $Aria2Path $modelMirrorUrl $modelUrl `
    "--dir=$snapshotRoot" "--out=model.safetensors" `
    "--continue=true" "--max-tries=0" "--retry-wait=5" "--timeout=120" `
    "--connect-timeout=120" "--split=8" "--max-connection-per-server=8" `
    "--min-split-size=1M" "--file-allocation=none" "--auto-file-renaming=false" `
    "--allow-overwrite=true" "--check-integrity=true" `
    "--checksum=sha-256=248dfc3911869ec493c76e65bf2fcf7f615828b0254c12b473182f0f81d3a707"
if ($LASTEXITCODE -ne 0) {
    throw "Pinned GPT-2 model download failed with exit code $LASTEXITCODE"
}

$receipt = Join-Path $RepoRoot "reports\downloads\teacher_environment.json"
& $PythonPath (Join-Path $RepoRoot "scripts\assets\audit_teacher_environment.py") `
    --gpt2-root $snapshotRoot --output $receipt
if ($LASTEXITCODE -ne 0) {
    throw "Teacher environment audit failed with exit code $LASTEXITCODE"
}

& $PythonPath -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "pip check failed with exit code $LASTEXITCODE"
}

Write-Output "Teacher environment bootstrap and audit completed."
