$ErrorActionPreference = "Stop"

$gitExe = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$repository = "E:\OV-OrthKD-R3\repo"
$candidate = "E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0"
$expectedCommit = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"
$candidatePrefix = "E:\OV-OrthKD-R3\"
$possibleJunctions = @(
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

$resolvedCandidate = (Resolve-Path -LiteralPath $candidate).Path
if ($resolvedCandidate -ne $candidate -or -not $resolvedCandidate.StartsWith($candidatePrefix)) {
    throw "Refusing unexpected cleanup target: $resolvedCandidate"
}
$head = (& $gitExe -C $candidate rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne $expectedCommit) {
    throw "Refusing cleanup of candidate with unexpected Git identity"
}

foreach ($relative in $possibleJunctions) {
    $path = Join-Path $candidate $relative
    if (Test-Path -LiteralPath $path) {
        $item = Get-Item -LiteralPath $path -Force
        if ($item.LinkType -ne "Junction") {
            throw "Refusing to remove non-junction path: $path"
        }
        [System.IO.Directory]::Delete($path, $false)
        if (Test-Path -LiteralPath $path) {
            throw "Failed to remove generated junction: $path"
        }
    }
}

& $gitExe -C $repository worktree remove $candidate
if ($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $candidate)) {
    throw "Failed to remove incomplete generated candidate worktree"
}
"REMOVED_INCOMPLETE_S7_CANDIDATE"
