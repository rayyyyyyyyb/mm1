# Canonical Seed42 Formal Reproduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在精确提交 `31b86c0d60c4bf2ed028edf1385ed5d2c9e89153` 和 RTX 5090 已审计资产上，完成第一份且唯一的 canonical OV-OrthKD seed42 正式训练、全量评估与 provenance 审计。

**Architecture:** 正式 run 使用独立 detached clean Git worktree，并用 junction 只读复用主 5090 仓库中的已锁定数据、checkpoint 和教师缓存。训练进程由工作树外的控制状态与本目录控制脚本启动和监控；训练原始输出留在 5090，完成后只回收小型 JSON/YAML/Markdown 和日志摘要。

**Tech Stack:** PowerShell 7/Windows PowerShell、Git worktree、Python 3.11.9、PyTorch 2.10.0+cu128、CUDA 12.8、pytest、RTX 5090。

**Spec:** `扩刊/OV_OrthKD_MM26_FORMAL_REPRODUCTION_PLAN_20260825.md`

## Global Constraints

- Git HEAD 必须为 `31b86c0d60c4bf2ed028edf1385ed5d2c9e89153`，正式启动时工作树必须 clean。
- 协议固定为 `T_task=10, T_max=16, K_student=1, K_teacher=8, V_test=1`。
- 只运行 `configs/ov_orthkd_mm26_repro_ready.yaml`；只允许覆盖 `--output-dir`。
- 禁止再次运行真实 preflight、教师导出、全量 cache audit 或资产下载。
- 禁止任何训练/评估截断、blocked/incompatible override、early stop 或参数覆盖。
- 第一份 seed42 canonical 结果必须原样永久保存；不为追论文数值而换 seed 或调参。
- 本阶段不实现、不启动任何 controlled ablation。

---

### Task 1: 建立正式隔离工作树

**Files:**
- Create on 5090: `E:/OV-OrthKD-R3/formal-canonical-31b86c0/`
- Reuse read-only assets: `E:/OV-OrthKD-R3/repo/{external,weights,data/...}`

**Interfaces:**
- Consumes: R5 exact commit 与主仓库中已审计资产。
- Produces: detached、clean、8 个 junction 完整的正式运行根目录。

- [ ] **Step 1: 检查目标路径不存在且 Git object 可解析**

Run: `git -C E:/OV-OrthKD-R3/repo rev-parse 31b86c0d60c4bf2ed028edf1385ed5d2c9e89153`

Expected: 输出精确 40-hex SHA，目标工作树路径不存在。

- [ ] **Step 2: 创建 detached worktree**

Run: `git -C E:/OV-OrthKD-R3/repo worktree add --detach E:/OV-OrthKD-R3/formal-canonical-31b86c0 31b86c0d60c4bf2ed028edf1385ed5d2c9e89153`

Expected: HEAD 指向精确 SHA。

- [ ] **Step 3: 创建 8 个资产 junction**

Targets: `external`、`weights`、`data/official`、`data/teacher_cache`、`data/downloads/hf_cache`、`data/downloads/incoming`、`data/ov_ave/source`、`data/ov_ave/exported`。

Expected: 每个 link 的 `LinkType=Junction`，target 都位于 `E:/OV-OrthKD-R3/repo`。

- [ ] **Step 4: 验证基线**

Run: `git status --porcelain --untracked-files=all`

Expected: 0 行；junction count=8。

### Task 2: 运行 Phase 1 cold gates

**Files:**
- Read: complete exact worktree
- Write only ignored caches: Python bytecode/pytest cache

**Interfaces:**
- Consumes: Task 1 clean worktree。
- Produces: pip/CUDA/pytest/diff/status 五项退出码。

- [ ] **Step 1: 验证依赖**

Run: `E:/OV-OrthKD-R0/env/.venv/Scripts/python.exe -m pip check`

Expected: `No broken requirements found`，exit 0。

- [ ] **Step 2: 验证 RTX 5090 CUDA**

Run: `python scripts/verify_cuda_runtime.py`

Expected: GPU 为 RTX 5090、CUDA 可用、FP16 输出 finite、exit 0。

- [ ] **Step 3: 完整测试**

Run: `python -m pytest -q`

Expected: 388 tests 全通过、exit 0；不得运行真实 preflight。

- [ ] **Step 4: 再验 Git**

Run: `git diff --check` 与 `git status --porcelain --untracked-files=all`

Expected: 两者 exit 0，status 0 行。

### Task 3: 验证正式控制器

**Files:**
- Source: `扩刊/复现/run_canonical_seed42.ps1`
- Source: `扩刊/复现/run_canonical_seed42_worker.ps1`
- Source: `扩刊/复现/PersistentProcess.psm1`
- Test: `扩刊/复现/tests/Test-PersistentProcess.ps1`
- Deploy: `E:/OV-OrthKD-R3/formal_control/run_canonical_seed42.ps1`
- Create state: `E:/OV-OrthKD-R3/formal_control/mm26_canonical_seed42/launch_state.json`

**Interfaces:**
- Consumes: exact worktree、locked Python、ready config。
- Produces: fail-closed `Validate/Start/Resume/Status` 控制入口，以及脱离 SSH job 的 WMI worker。

- [ ] **Step 1: PowerShell parser 检查**

Expected: 0 parser errors。

- [ ] **Step 2: 运行 `-Action Validate`**

Expected: exact HEAD、clean tree、config 存在、无重复训练进程。

- [ ] **Step 3: 运行持久进程行为测试**

Run: `tests/Test-PersistentProcess.ps1`，随后从第二个 SSH session 检查诊断 PID 与 marker。

Expected: `Win32_Process.Create` return 0，PID 跨 SSH session 存活，测试后精确停止 PID 并删除临时目录。

- [ ] **Step 4: 运行 `-Action Status`**

Expected: 首次启动前状态为 `not_started`，不创建 checkpoint 或 metrics。

### Task 4: 启动唯一 canonical seed42

**Files:**
- Create on 5090: `outputs/formal/mm26_canonical_seed42/`
- Create control log/state outside worktree output.

**Interfaces:**
- Consumes: Task 2 全部 exit 0、Task 3 validate 通过。
- Produces: 一个持久化 Python 正式训练进程与唯一 output namespace。

- [ ] **Step 1: 启动**

Run: `run_canonical_seed42.ps1 -Action Start`

Exact child command: `python scripts/train_ov_orthkd.py --config configs/ov_orthkd_mm26_repro_ready.yaml --output-dir outputs/formal/mm26_canonical_seed42`

Expected: 返回一个存活 PID；命令不含任何其他 CLI override。

- [ ] **Step 2: 早期 fail-fast 检查**

Run: `run_canonical_seed42.ps1 -Action Status`

Expected: readiness 未失败、进程存活、`runtime.json`/`resolved_config.yaml`/static evidence 开始出现；如 Python 非零退出且无 `last.pt`，停止并诊断，不自动重启。

### Task 5: 持续监控与安全恢复

**Files:**
- Read: `train.log`、`history.jsonl`、`last.pt`、`best.pt`、控制 state。

**Interfaces:**
- Consumes: Task 4 正式进程。
- Produces: 每 epoch 的 step、loss、validation、显存、wall time 状态快照。

- [ ] **Step 1: 每个状态周期读取控制器状态**

Expected: 最多 30 epochs、每 epoch 最多 400 optimizer batches、global step 最多 12,000。

- [ ] **Step 2: 检查故障条件**

Stop conditions: readiness/fingerprint mismatch、NaN/Inf、OOM、非零退出、Git 变 dirty、T 不等于 10、出现 incompatible marker。

- [ ] **Step 3: 仅对可证明的外部中断恢复**

Run: `run_canonical_seed42.ps1 -Action Resume`

Expected: 必须存在同一 output 的 `last.pt`，使用同 config、同 SHA、同 output；禁止 incompatible override。

### Task 6: 完成后机械验收与回收

**Files:**
- Read on 5090: full output directory
- Copy to local: `扩刊/复现/canonical_seed42/` 中的小型 receipt、config、metrics、history 和日志尾部
- Create: `扩刊/复现/CANONICAL_SEED42_REPRODUCTION_REPORT.md`

**Interfaces:**
- Consumes: 完成的正式 run。
- Produces: 可审计的 paper/reference/delta 报告；不含大型 checkpoint/prediction/data/cache。

- [ ] **Step 1: 验证 required evidence 文件全部存在**

Expected: runtime/config/Git/claim/fingerprint/manifest/lock/cache/evaluator/history/best/last/predictions/final metrics 全部存在。

- [ ] **Step 2: 验证 provenance invariants**

Expected: exact HEAD、dirty=false、claim=`paper_specified_reconstruction`、T=10/16/1/8/1、cache SHA=`6707900b...0244`、evaluator matches lock。

- [ ] **Step 3: 生成结果表**

Expected: 总体/seen/unseen AP、AUROC、F1@0.5、calibrated F1、Acc，以及 paper value 与 absolute delta；不设置事后成功阈值。

- [ ] **Step 4: 回收小型文件并停止**

Do not copy: `best.pt`、`last.pt`、prediction NPZ、数据、checkpoint、teacher cache、完整大型日志。

Expected: 本地报告与 `扩刊/all.md` 更新完成；不启动任何消融。
