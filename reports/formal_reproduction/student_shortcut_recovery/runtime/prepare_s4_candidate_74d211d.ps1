$ErrorActionPreference = "Stop"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$Repository = "E:\OV-OrthKD-R3\repo"
$Bundle = "E:\OV-OrthKD-R3\student_shortcut_control\s4_candidate_74d211d_from_a0aa.bundle"
$Source = "E:\OV-OrthKD-R3\student-shortcut-a0aa4d7"
$Worktree = "E:\OV-OrthKD-R3\student-shortcut-s4-74d211d"
$Control = "E:\OV-OrthKD-R3\student_shortcut_control\candidate_s4_74d211d"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Expected = "74d211d34ace74ce3b74ea082a7dfd0379b251fb"
$ExpectedBundleSha = "022da67939d5f6e3b45fa5979041761027a8c79971f37932eba439d429fdcdf0"
$StatePath = Join-Path $Control "worker_state.json"
$Links = @(
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

function Write-State {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][string]$Phase,
        [Nullable[int]]$ExitCode,
        [Parameter(Mandatory = $true)][string]$Message
    )
    New-Item -ItemType Directory -Force -Path $Control | Out-Null
    $state = [ordered]@{
        schema_version = 1
        status = $Status
        worker_process_id = $PID
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
        expected_commit = $Expected
        phase = $Phase
        exit_code = $ExitCode
        message = $Message
    }
    $temporary = "$StatePath.tmp.$PID"
    $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $StatePath -Force
}

function Invoke-NativeMerged {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$LogPath
    )
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $FilePath @ArgumentList *> $LogPath
        return [int]$LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

try {
    if ((Get-FileHash -LiteralPath $Bundle -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedBundleSha) {
        throw "Bundle SHA256 mismatch"
    }
    if ((Test-Path -LiteralPath $Worktree) -or (Test-Path -LiteralPath $Control)) {
        throw "S4 candidate target is not fresh"
    }
    New-Item -ItemType Directory -Path $Control | Out-Null
    Write-State -Status "running" -Phase "bundle_and_worktree" -ExitCode $null -Message "verifying bundle and constructing exact detached S4 worktree"
    $bundleExit = Invoke-NativeMerged -FilePath $Git -ArgumentList @("-C", $Repository, "bundle", "verify", $Bundle) -LogPath (Join-Path $Control "bundle_verify.log")
    if ($bundleExit -ne 0) { throw "Bundle verify failed: $bundleExit" }
    $fetchExit = Invoke-NativeMerged -FilePath $Git -ArgumentList @("-C", $Repository, "fetch", $Bundle, "HEAD") -LogPath (Join-Path $Control "bundle_fetch.log")
    if ($fetchExit -ne 0) { throw "Bundle fetch failed: $fetchExit" }
    $catFileExit = Invoke-NativeMerged -FilePath $Git -ArgumentList @("-C", $Repository, "cat-file", "-e", "$Expected`^{commit}") -LogPath (Join-Path $Control "cat_file.log")
    if ($catFileExit -ne 0) { throw "Expected commit was not imported" }
    $worktreeExit = Invoke-NativeMerged -FilePath $Git -ArgumentList @("-C", $Repository, "worktree", "add", "--detach", $Worktree, $Expected) -LogPath (Join-Path $Control "worktree_add.log")
    if ($worktreeExit -ne 0) { throw "Worktree add failed: $worktreeExit" }

    foreach ($relative in $Links) {
        $sourceItem = Get-Item -LiteralPath (Join-Path $Source $relative) -Force
        if ($sourceItem.LinkType -ne "Junction" -or @($sourceItem.Target).Count -ne 1) {
            throw "Invalid source junction: $relative"
        }
        $targetPath = Join-Path $Worktree $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetPath) | Out-Null
        $made = New-Item -ItemType Junction -Path $targetPath -Target ([string]@($sourceItem.Target)[0])
        if ($made.LinkType -ne "Junction") { throw "Junction create failed: $relative" }
    }

    $env:Path = "$(Split-Path -Parent $Git);$env:Path"
    $headBefore = (& $Git -C $Worktree rev-parse HEAD).Trim()
    $dirtyBefore = @(& $Git -C $Worktree status --porcelain=v1 --untracked-files=all).Count
    if ($headBefore -ne $Expected -or $dirtyBefore -ne 0) {
        throw "New S4 candidate worktree is not exact and clean"
    }

    Write-State -Status "running" -Phase "focused_regression" -ExitCode $null -Message "running S4 config and real loader augmentation tests"
    $focusedLog = Join-Path $Control "focused_pytest.log"
    Push-Location -LiteralPath $Worktree
    try {
        $focusedExit = Invoke-NativeMerged -FilePath $Python -ArgumentList @("-m", "pytest", "-q", "tests\test_student_recovery_configs.py", "tests\test_s4_augmentation_control.py") -LogPath $focusedLog
    } finally {
        Pop-Location
    }
    if ($focusedExit -ne 0) { throw "Focused S4 regression exited with code $focusedExit" }

    Write-State -Status "running" -Phase "full_verification" -ExitCode $null -Message "running compileall and the complete repository test suite"
    $compileLog = Join-Path $Control "compileall.log"
    $pytestLog = Join-Path $Control "pytest.log"
    Push-Location -LiteralPath $Worktree
    try {
        $compileExit = Invoke-NativeMerged -FilePath $Python -ArgumentList @("-m", "compileall", "-q", "scripts", "src", "tests") -LogPath $compileLog
        $pytestExit = Invoke-NativeMerged -FilePath $Python -ArgumentList @("-m", "pytest", "-q") -LogPath $pytestLog
    } finally {
        Pop-Location
    }
    $headAfter = (& $Git -C $Worktree rev-parse HEAD).Trim()
    $dirtyAfter = @(& $Git -C $Worktree status --porcelain=v1 --untracked-files=all).Count
    if ($compileExit -ne 0 -or $pytestExit -ne 0 -or $headAfter -ne $Expected -or $dirtyAfter -ne 0) {
        throw "Full S4 candidate verification did not pass"
    }
    $receipt = [ordered]@{
        schema_version = 1
        status = "PASS"
        completed_at_utc = [DateTime]::UtcNow.ToString("o")
        expected_commit = $Expected
        bundle_sha256 = $ExpectedBundleSha
        head_before = $headBefore
        dirty_before = $dirtyBefore
        focused_pytest_exit = $focusedExit
        focused_pytest_log_bytes = (Get-Item -LiteralPath $focusedLog).Length
        focused_pytest_log_sha256 = (Get-FileHash -LiteralPath $focusedLog -Algorithm SHA256).Hash.ToLowerInvariant()
        focused_pytest_tail = [string[]]@(Get-Content -LiteralPath $focusedLog -Tail 8 -Encoding UTF8)
        compileall_exit = $compileExit
        compileall_log_bytes = (Get-Item -LiteralPath $compileLog).Length
        compileall_log_sha256 = (Get-FileHash -LiteralPath $compileLog -Algorithm SHA256).Hash.ToLowerInvariant()
        pytest_exit = $pytestExit
        pytest_log_bytes = (Get-Item -LiteralPath $pytestLog).Length
        pytest_log_sha256 = (Get-FileHash -LiteralPath $pytestLog -Algorithm SHA256).Hash.ToLowerInvariant()
        pytest_tail = [string[]]@(Get-Content -LiteralPath $pytestLog -Tail 8 -Encoding UTF8)
        head_after = $headAfter
        dirty_after = $dirtyAfter
    }
    $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Control "verification_receipt.json") -Encoding UTF8
    Write-State -Status "completed" -Phase "completed" -ExitCode 0 -Message "exact S4 candidate passed focused and full verification"
    exit 0
} catch {
    Write-State -Status "failed" -Phase "failed" -ExitCode 1 -Message $_.Exception.ToString()
    exit 1
}
