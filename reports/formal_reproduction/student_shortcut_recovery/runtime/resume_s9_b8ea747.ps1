$ErrorActionPreference = "Stop"
$ModulePath = "E:\OV-OrthKD-R3\formal_control\PersistentProcess.psm1"
$WorkerPath = "E:\OV-OrthKD-R3\student_shortcut_control\run_s9_worker_b8ea747.ps1"
$ControlDir = "E:\OV-OrthKD-R3\student_shortcut_control\s9_b8ea747"
$RepoRoot = "E:\OV-OrthKD-R3\student-shortcut-s9-b8ea747"
$VerificationPath = "E:\OV-OrthKD-R3\student_shortcut_control\s9_b8ea747_verification\verification_receipt.json"
$Git = "E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe"
$ExpectedCommit = "b8ea747dd792c939251152ead734d1826c26980d"
$ExpectedConfigSha = "61942acb92fe0a9a1a87a828764073303761328783b515c606e97d8f10e26cbe"
$ExpectedModuleSha = "3105384926f66900f57b767984fd029aec968792564420f0bd665cf011bf42e5"
$ExpectedWorkerSha = "2e8909674b3b56ca6ae4d408e3d14c43f72927af8e32f6deac9f43329799dd4b"
$ExpectedVerificationSha = "e2071da533d757ec627b9e55c2998f334c5a3385f209b4d2509d73944ac9acc7"

function Get-NormalizedTextSha256 {
    param([string]$Path)
    $Text=[IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8).Replace("`r`n","`n");$Sha=[Security.Cryptography.SHA256]::Create()
    try{return([BitConverter]::ToString($Sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace("-","").ToLowerInvariant()}finally{$Sha.Dispose()}
}
if ((Get-FileHash -LiteralPath $ModulePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedModuleSha) { throw "Persistent module SHA256 mismatch" }
if ((Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedWorkerSha) { throw "S9 worker SHA256 mismatch" }
if ((Get-FileHash -LiteralPath $VerificationPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedVerificationSha) { throw "S9 verification SHA256 mismatch" }
$Verification=Get-Content -LiteralPath $VerificationPath -Raw -Encoding UTF8|ConvertFrom-Json
if($Verification.status-ne"PASS"-or $Verification.commit_after-ne$ExpectedCommit-or[int]$Verification.pytest_exit-ne 0-or[int]$Verification.dirty_after-ne 0){throw "S9 verification did not satisfy resume gate"}
if(-not(Test-Path -LiteralPath $ControlDir -PathType Container)){throw "Resume requires existing S9 control directory"}
$StatePath=Join-Path $ControlDir "worker_state.json";if(-not(Test-Path -LiteralPath $StatePath -PathType Leaf)){throw "Resume requires S9 worker state"}
$StateBefore=Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8|ConvertFrom-Json;if($StateBefore.status-eq"completed"){throw "S9 already completed"}
$Head=(&$Git -C $RepoRoot rev-parse HEAD).Trim();$Dirty=@(&$Git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
$ConfigSha=Get-NormalizedTextSha256 -Path (Join-Path $RepoRoot "configs\diagnostics\recovery\ov_orthkd_s9_paper_additive_seed42.yaml")
if($Head-ne$ExpectedCommit-or$Dirty.Count-ne 0-or$ConfigSha-ne$ExpectedConfigSha){throw "Resume requires exact clean S9 commit/config"}
$Matching=@(Get-CimInstance Win32_Process|Where-Object{$_.CommandLine-like"*train_ov_orthkd.py*"-or$_.CommandLine-like"*diagnose_s7_zero_training.py*"-or$_.CommandLine-like"*run_s9_worker_b8ea747.ps1*"})
if($Matching.Count-ne 0){throw "A conflicting training/A-E/S9 process is already running"}
Import-Module $ModulePath -Force;$Created=Start-PersistentPowerShellScript -ScriptPath $WorkerPath -ArgumentList @("-Resume");$WorkerProcessId=[int]$Created.ProcessId
Start-Sleep -Seconds 10;$Process=Get-Process -Id $WorkerProcessId -ErrorAction SilentlyContinue;$StateAfter=Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8|ConvertFrom-Json
if($null-eq$Process){throw "Persistent S9 resume worker exited: $($StateAfter.message)"};if($StateAfter.status-ne"running"){throw "S9 resume did not report running state"}
$Receipt=[ordered]@{schema_version=1;status="running";resume=$true;utc=[DateTime]::UtcNow.ToString("o");worker_process_id=$WorkerProcessId;return_value=[int]$Created.ReturnValue;module_sha256=$ExpectedModuleSha;worker_sha256=$ExpectedWorkerSha;git_head=$ExpectedCommit;config_sha256=$ExpectedConfigSha;state_before=$StateBefore;state_after=$StateAfter}
$ReceiptPath=Join-Path $ControlDir ("resume_launch_"+[DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")+".json");$Receipt|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
[ordered]@{receipt_path=$ReceiptPath;receipt=$Receipt;process=@(Get-CimInstance Win32_Process -Filter "ProcessId=$WorkerProcessId"|Select-Object ProcessId,ParentProcessId,Name,CommandLine);gpu=@(&nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits)}|ConvertTo-Json -Depth 12
