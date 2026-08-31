$ErrorActionPreference = "Stop"
$Python = "E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe"
$Script = "E:\OV-OrthKD-R3\student_shortcut_control\download_audio_ranges_f739399.py"
$Control = "E:\OV-OrthKD-R3\student_shortcut_control\audio_ranges_f739399"
$Target = "E:\OV-OrthKD-R3\student_shortcut_control\model_cache\torch\hub\checkpoints\tf_efficientnetv2_b2-847de54e.pth"
$ExpectedScriptSha = "1bfa9f4606482b352ace96f29ac6fcfeb403e92e30903d5dddb32531b6d19668"
$Stdout = Join-Path $Control "stdout.log"
$Stderr = Join-Path $Control "stderr.log"
if ((Get-FileHash -LiteralPath $Script -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedScriptSha) { throw "Parallel audio downloader SHA mismatch" }
New-Item -ItemType Directory -Force -Path $Control | Out-Null
& $Python $Script --target $Target --control $Control --connections 8 --retries 20 1> $Stdout 2> $Stderr
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) { throw "Parallel audio downloader exited with code $exitCode" }
exit 0
