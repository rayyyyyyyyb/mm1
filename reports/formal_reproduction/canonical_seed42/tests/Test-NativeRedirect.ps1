$ErrorActionPreference = "Stop"
$modulePath = Join-Path (Split-Path -Parent $PSScriptRoot) "PersistentProcess.psm1"
Import-Module $modulePath -Force

$testRoot = Join-Path $env:TEMP ("ov-orthkd-native-redirect-" + [Guid]::NewGuid().ToString("N"))
$childPath = Join-Path $testRoot "child.ps1"
$stdoutPath = Join-Path $testRoot "stdout.log"
$stderrPath = Join-Path $testRoot "stderr.log"

try {
    New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
    @'
[Console]::Out.WriteLine("expected stdout")
[Console]::Error.WriteLine("expected informational stderr")
exit 0
'@ | Set-Content -LiteralPath $childPath -Encoding UTF8

    $exitCode = Invoke-NativeProcessWithRedirect `
        -FilePath (Join-Path $PSHOME "powershell.exe") `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $childPath
        ) `
        -WorkingDirectory $testRoot `
        -StandardOutputPath $stdoutPath `
        -StandardErrorPath $stderrPath

    if ($exitCode -ne 0) {
        throw "Expected child exit code 0, got $exitCode"
    }
    if ((Get-Content -LiteralPath $stdoutPath -Raw) -notmatch "expected stdout") {
        throw "Expected redirected stdout was not preserved"
    }
    if ((Get-Content -LiteralPath $stderrPath -Raw) -notmatch "expected informational stderr") {
        throw "Expected redirected stderr was not preserved"
    }
    Write-Output "NATIVE_REDIRECT_TEST=PASS"
} finally {
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
