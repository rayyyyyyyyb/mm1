Set-StrictMode -Version Latest

function ConvertTo-WindowsCommandArgument {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ($Value.Contains('"')) {
        throw "Persistent process arguments cannot contain a double quote: $Value"
    }
    return '"' + $Value + '"'
}

function Start-PersistentPowerShellScript {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [string[]]$ArgumentList = @()
    )

    $resolvedScript = [IO.Path]::GetFullPath($ScriptPath)
    if (-not (Test-Path -LiteralPath $resolvedScript -PathType Leaf)) {
        throw "Persistent PowerShell script is missing: $resolvedScript"
    }
    $parts = @(
        "powershell.exe",
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (ConvertTo-WindowsCommandArgument -Value $resolvedScript)
    )
    foreach ($argument in $ArgumentList) {
        $parts += ConvertTo-WindowsCommandArgument -Value ([string]$argument)
    }
    $commandLine = $parts -join " "
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $commandLine
    }
    if ($created.ReturnValue -ne 0) {
        throw "Win32_Process.Create failed with return value $($created.ReturnValue)"
    }
    return $created
}

function Invoke-NativeProcessWithRedirect {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$StandardOutputPath,
        [Parameter(Mandatory = $true)][string]$StandardErrorPath
    )

    $resolvedFile = [IO.Path]::GetFullPath($FilePath)
    $resolvedWorkingDirectory = [IO.Path]::GetFullPath($WorkingDirectory)
    $resolvedStandardOutput = [IO.Path]::GetFullPath($StandardOutputPath)
    $resolvedStandardError = [IO.Path]::GetFullPath($StandardErrorPath)
    if (-not (Test-Path -LiteralPath $resolvedFile -PathType Leaf)) {
        throw "Native executable is missing: $resolvedFile"
    }
    if (-not (Test-Path -LiteralPath $resolvedWorkingDirectory -PathType Container)) {
        throw "Native working directory is missing: $resolvedWorkingDirectory"
    }
    if ($resolvedStandardOutput -eq $resolvedStandardError) {
        throw "Native stdout and stderr paths must differ"
    }
    foreach ($parent in @(
        (Split-Path -Parent $resolvedStandardOutput),
        (Split-Path -Parent $resolvedStandardError)
    ) | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            throw "Native redirect directory is missing: $parent"
        }
    }

    $process = Start-Process `
        -FilePath $resolvedFile `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $resolvedWorkingDirectory `
        -NoNewWindow `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $resolvedStandardOutput `
        -RedirectStandardError $resolvedStandardError
    return [int]$process.ExitCode
}

function Assert-CanonicalPreTrainingRecovery {
    param(
        [Parameter(Mandatory = $true)][string]$OutputDirectory,
        [Parameter(Mandatory = $true)][string]$WorkerStatePath,
        [Parameter(Mandatory = $true)][string]$StandardOutputPath,
        [Parameter(Mandatory = $true)][string]$StandardErrorPath,
        [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedCacheHash
    )

    $allowedFiles = @(
        "claim_level.txt",
        "config_resolved.yaml",
        "cuda_environment.json",
        "experiment_variant.json",
        "git_state.json",
        "lock_hashes.json",
        "manifest_hashes.json",
        "official_evaluator_hash.json",
        "requirements_freeze.txt",
        "resolved_config.yaml",
        "runtime.json",
        "teacher_cache_hash.json",
        "train.log"
    ) | Sort-Object
    if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) {
        throw "Pre-training recovery output directory is missing: $OutputDirectory"
    }
    $directories = @(Get-ChildItem -LiteralPath $OutputDirectory -Directory -Force)
    if ($directories.Count -ne 0) {
        throw "Pre-training recovery forbids output subdirectories"
    }
    $actualFiles = @(
        Get-ChildItem -LiteralPath $OutputDirectory -File -Force |
            ForEach-Object Name |
            Sort-Object
    )
    $difference = @(Compare-Object -ReferenceObject $allowedFiles -DifferenceObject $actualFiles)
    if ($difference.Count -ne 0) {
        throw "Pre-training recovery output does not match the 13-file static evidence allowlist"
    }

    foreach ($path in @($WorkerStatePath, $StandardOutputPath, $StandardErrorPath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Pre-training recovery evidence is missing: $path"
        }
    }
    if ((Get-Item -LiteralPath $StandardOutputPath).Length -ne 0 -or
        (Get-Item -LiteralPath $StandardErrorPath).Length -ne 0) {
        throw "Pre-training recovery requires empty wrapper stdout and stderr files"
    }
    $workerState = Get-Content -LiteralPath $WorkerStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($workerState.status -ne "failed" -or [int]$workerState.exit_code -ne 1 -or
        [string]$workerState.message -notmatch "RemoteException: .*INFO: Using device: cuda") {
        throw "Pre-training recovery worker failure does not match the PowerShell stderr wrapper signature"
    }

    $cacheReceiptPath = Join-Path $OutputDirectory "teacher_cache_hash.json"
    $cacheReceipt = Get-Content -LiteralPath $cacheReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not [bool]$cacheReceipt.exists -or [int]$cacheReceipt.schema_version -ne 1 -or
        [int]$cacheReceipt.files -ne 99334 -or [int64]$cacheReceipt.bytes -ne 1310102478 -or
        [string]$cacheReceipt.sha256 -ne $ExpectedCacheHash) {
        throw "Pre-training recovery teacher cache receipt does not match the canonical lock"
    }
    $trainLogLines = @(Get-Content -LiteralPath (Join-Path $OutputDirectory "train.log") -Encoding UTF8)
    if ($trainLogLines.Count -ne 1 -or
        [string]$trainLogLines[0] -notmatch "^\[.+\] INFO: Using device: cuda$") {
        throw "Pre-training recovery requires exactly the first pre-loader informational log line"
    }

    return [pscustomobject][ordered]@{
        status = "validated_pretraining_wrapper_failure"
        file_count = $actualFiles.Count
        cache_sha256 = [string]$cacheReceipt.sha256
        optimizer_steps = 0
    }
}

function Read-JsonLinesFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return
    }
    foreach ($line in @(Get-Content -LiteralPath $Path -Encoding UTF8)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$line)) {
            Write-Output ([string]$line | ConvertFrom-Json)
        }
    }
}

Export-ModuleMember -Function `
    Start-PersistentPowerShellScript, `
    Invoke-NativeProcessWithRedirect, `
    Assert-CanonicalPreTrainingRecovery, `
    Read-JsonLinesFile
