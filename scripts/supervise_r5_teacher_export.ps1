param(
    [int]$MaxAttempts = 100,
    [int]$RetryDelaySeconds = 60
)

$ErrorActionPreference = "Continue"
$RepoRoot = "E:\OV-OrthKD-R3\repo"
$Runner = Join-Path $RepoRoot "scripts\run_r5_remote_stage.ps1"
$StateDir = Join-Path $RepoRoot "reports\teachers\supervisor"
$StatePath = Join-Path $StateDir "state.json"
$AttemptLog = Join-Path $StateDir "attempts.jsonl"
$ExportStdout = Join-Path $StateDir "export.stdout.log"
$ExportStderr = Join-Path $StateDir "export.stderr.log"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

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
        attempt = $Attempt
        max_attempts = $MaxAttempts
        last_exit_code = $ExitCode
        message = $Message
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
        runner = $Runner
    }
    $json = $state | ConvertTo-Json -Depth 5
    $partial = "$StatePath.partial"
    Set-Content -LiteralPath $partial -Value $json -Encoding UTF8
    Move-Item -LiteralPath $partial -Destination $StatePath -Force
    Add-Content -LiteralPath $AttemptLog -Value ($state | ConvertTo-Json -Compress)
}

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    Write-State -Status "running" -Attempt $attempt -ExitCode 0 -Message "resumable export attempt started"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Runner -Action ExportAll `
        1>> $ExportStdout 2>> $ExportStderr
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        Write-State -Status "completed" -Attempt $attempt -ExitCode 0 -Message "all three split exports completed"
        exit 0
    }
    Write-State -Status "retry_wait" -Attempt $attempt -ExitCode $code -Message "export failed; the next attempt will validate receipts and resume"
    Start-Sleep -Seconds $RetryDelaySeconds
}

Write-State -Status "failed" -Attempt $MaxAttempts -ExitCode $LASTEXITCODE -Message "maximum retry attempts exhausted"
exit 1
