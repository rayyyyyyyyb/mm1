$ErrorActionPreference = "Stop"
$modulePath = Join-Path (Split-Path -Parent $PSScriptRoot) "PersistentProcess.psm1"
Import-Module $modulePath -Force

$testRoot = Join-Path $env:TEMP ("ov-orthkd-json-lines-" + [Guid]::NewGuid().ToString("N"))
$historyPath = Join-Path $testRoot "history.jsonl"

try {
    New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
    Set-Content -LiteralPath $historyPath -Value '{"epoch":0,"global_step":400}' -Encoding UTF8
    $one = @(Read-JsonLinesFile -Path $historyPath)
    if ($one.Count -ne 1 -or $one[0].epoch -ne 0 -or $one[0].global_step -ne 400) {
        throw "Single-record JSONL was not preserved as one parsed record"
    }

    Add-Content -LiteralPath $historyPath -Value '{"epoch":1,"global_step":800}' -Encoding UTF8
    $two = @(Read-JsonLinesFile -Path $historyPath)
    if ($two.Count -ne 2 -or $two[-1].epoch -ne 1 -or $two[-1].global_step -ne 800) {
        throw "Multi-record JSONL did not preserve record order"
    }
    Write-Output "JSON_LINES_READER_TEST=PASS"
} finally {
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
