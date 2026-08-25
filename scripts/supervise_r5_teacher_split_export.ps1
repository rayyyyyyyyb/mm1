param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("val", "test")]
    [string]$Split,
    [int]$MaxAttempts = 100,
    [int]$RetryDelaySeconds = 60
)

$ErrorActionPreference = "Continue"
$RepoRoot = "E:\OV-OrthKD-R3\repo"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$MinGit = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd"
$StateDir = Join-Path $RepoRoot "reports\teachers\supervisor-$Split"
$StatePath = Join-Path $StateDir "state.json"
$AttemptLog = Join-Path $StateDir "attempts.jsonl"
$ExportStdout = Join-Path $StateDir "export.stdout.log"
$ExportStderr = Join-Path $StateDir "export.stderr.log"

foreach ($required in @($RepoRoot, $Python, $MinGit)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required R5 sidecar path is missing: $required"
    }
}

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$env:Path = "$MinGit;$env:Path"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:TOKENIZERS_PARALLELISM = "false"
Set-Location -LiteralPath $RepoRoot

function Write-State {
    param(
        [string]$Status,
        [int]$Attempt,
        [int]$ExitCode,
        [string]$Message
    )
    $state = [ordered]@{
        schema_version = 1
        status = $Status
        split = $Split
        attempt = $Attempt
        max_attempts = $MaxAttempts
        last_exit_code = $ExitCode
        message = $Message
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    $partial = "$StatePath.partial"
    Set-Content -LiteralPath $partial -Value ($state | ConvertTo-Json -Depth 5) -Encoding UTF8
    Move-Item -LiteralPath $partial -Destination $StatePath -Force
    Add-Content -LiteralPath $AttemptLog -Value ($state | ConvertTo-Json -Compress)
}

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    Write-State -Status "running" -Attempt $attempt -ExitCode 0 `
        -Message "resumable $Split sidecar export attempt started"
    & $Python scripts/export_teacher_artifacts.py `
        --config configs/ov_orthkd_mm26_repro.yaml `
        --source-manifest "data\ov_ave\source\$Split.jsonl" `
        --output-manifest "data\ov_ave\exported\$Split.jsonl" `
        --receipt-jsonl "reports\teachers\receipts\$Split.jsonl" `
        --error-jsonl "reports\teachers\errors\$Split.jsonl" `
        --progress-path "reports\teachers\progress\$Split.json" `
        --teacher-lock configs/locks/mm26_teacher_lock.yaml `
        --split $Split `
        --resume `
        1>> $ExportStdout 2>> $ExportStderr
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        Write-State -Status "completed" -Attempt $attempt -ExitCode 0 `
            -Message "$Split sidecar export completed"
        exit 0
    }
    Write-State -Status "retry_wait" -Attempt $attempt -ExitCode $code `
        -Message "$Split sidecar export failed; retry will validate receipts and resume"
    Start-Sleep -Seconds $RetryDelaySeconds
}

Write-State -Status "failed" -Attempt $MaxAttempts -ExitCode $LASTEXITCODE `
    -Message "$Split sidecar maximum retry attempts exhausted"
exit 1
