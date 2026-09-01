$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s8_worker_60100c6.ps1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s8_60100c6"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s8-60100c6"
$VerificationPath = "E:\OV-OrthKD-R3\student_shortcut_control\s8_60100c6_verification\verification_receipt.json"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "60100c6fff95b313ae92bc91b10a3be7135dc437"
$ExpectedConfigSha = "9175ae127d602741f8e6357366b093dafec433d3a578d096be8d49ae2ad1c505"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "0956fcbef0be3e7b4a14476e1f60a0556d9f72ebc81f04ce4a48eb3f2a2daa4e"
$ExpectedVerificationSha = "80aa29b284c2ab5ae4ec91277f7f7d53c178d18a6c4fe2f84e438cdbd0e12223"

function Get-NormalizedTextSha256 {
    param([string]$Path)
    $Text=[IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8).Replace("`r`n","`n");$Sha=[Security.Cryptography.SHA256]::Create()
    try{return([BitConverter]::ToString($Sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace("-","").ToLowerInvariant()}finally{$Sha.Dispose()}
}
if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) { throw "Persistent module SHA256 mismatch" }
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) { throw "S8 worker SHA256 mismatch" }
if ((Get-FileHash -LiteralPath $VerificationPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedVerificationSha) { throw "S8 verification SHA256 mismatch" }
$Verification=Get-Content -LiteralPath $VerificationPath -Raw -Encoding UTF8|ConvertFrom-Json
if($Verification.status-ne"PASS"-or $Verification.commit_after-ne$ExpectedCommit-or[int]$Verification.pytest_exit-ne 0-or[int]$Verification.dirty_after-ne 0){throw "S8 verification did not satisfy resume gate"}
if(-not(Test-Path -LiteralPath $ControlDir -PathType Container)){throw "Resume requires existing S8 control directory"}
$StatePath=Join-Path $ControlDir "worker_state.json";if(-not(Test-Path -LiteralPath $StatePath -PathType Leaf)){throw "Resume requires S8 worker state"}
$StateBefore=Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8|ConvertFrom-Json;if($StateBefore.status-eq"completed"){throw "S8 already completed"}
$Head=(&$Git -C $RepoRoot rev-parse HEAD).Trim();$Dirty=@(&$Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
$ConfigSha=Get-NormalizedTextSha256 -Path (Join-Path $RepoRoot "configs\diagnostics\recovery\ov_orthkd_s8_identity_fixed_gate_seed42.yaml")
if($Head-ne$ExpectedCommit-or$Dirty.Count-ne 0-or$ConfigSha-ne$ExpectedConfigSha){throw "Resume requires exact clean S8 commit/config"}
$Matching=@(Get-CimInstance Win32_Process|Where-Object{$_.CommandLine-like"*train_ov_orthkd.py*"-or$_.CommandLine-like"*diagnose_s7_zero_training.py*"-or$_.CommandLine-like"*run_s8_worker_60100c6.ps1*"})
if($Matching.Count-ne 0){throw "A conflicting training/A-E/S8 process is already running"}
Import-Module $ModulePath -Force;$Created=Start-PersistentPowerShellScript -ScriptPath $WorkerPath -ArgumentList @("-Resume");$WorkerProcessId=[int]$Created.ProcessId
Start-Sleep -Seconds 10;$Process=Get-Process -Id $WorkerProcessId -ErrorAction SilentlyContinue;$StateAfter=Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8|ConvertFrom-Json
if($null-eq$Process){throw "Persistent S8 resume worker exited: $($StateAfter.message)"};if($StateAfter.status-ne"running"){throw "S8 resume did not report running state"}
$Receipt=[ordered]@{schema_version=1;status="running";resume=$true;utc=[DateTime]::UtcNow.ToString("o");worker_process_id=$WorkerProcessId;return_value=[int]$Created.ReturnValue;module_sha256=$ExpectedModuleSha;worker_sha256=$ExpectedWorkerSha;git_head=$ExpectedCommit;config_sha256=$ExpectedConfigSha;state_before=$StateBefore;state_after=$StateAfter}
$ReceiptPath=Join-Path $ControlDir ("resume_launch_"+[DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")+".json");$Receipt|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
[ordered]@{receipt_path=$ReceiptPath;receipt=$Receipt;process=@(Get-CimInstance Win32_Process -Filter "ProcessId=$WorkerProcessId"|Select-Object ProcessId,ParentProcessId,Name,CommandLine);gpu=@(&nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)}|ConvertTo-Json -Depth 12
