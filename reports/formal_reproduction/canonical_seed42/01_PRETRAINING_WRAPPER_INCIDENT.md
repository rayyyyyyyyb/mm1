# Canonical seed42 正式训练前 wrapper 事件

## 结论

第一次持久 worker 在训练入口写出第一条正常 `Using device: cuda` 日志时，被 Windows PowerShell 5.1 的 native stderr 行为误判为终止异常。中断点位于 data loader、模型、loss 和 optimizer 创建之前，正式 optimizer steps 为 0。该事件不是 CUDA、数据、教师缓存、模型或训练配置失败，也没有产生 checkpoint、history、prediction 或 metrics。

修复只作用于 worktree 外的运行控制层：保留 Python 原始命令和 exact Git commit 不变，将 native stdout/stderr 交给独立 OS 重定向，并以真实进程 exit code 判定结果。正式仓库内容没有修改。

## 固定身份

- Git commit：`31b86c0d60c4bf2ed028edf1385ed5d2c9e89153`
- config：`configs/ov_orthkd_mm26_repro_ready.yaml`
- output：`outputs/formal/mm26_canonical_seed42`
- seed：42
- claim：`paper_specified_reconstruction`
- 第一次持久 worker：PID 28212
- 第一次 Python：PID 28404 / 实际 PID 27068
- 失败时间：`2026-08-25T17:05:02.4209691Z`

## 零训练步证据

- `train.log` 恰好一行：`Using device: cuda`。
- `history.jsonl` 不存在。
- `best.pt`、`last.pt` 不存在。
- `final_metrics.json` 不存在。
- `INCOMPATIBLE_RESUME.txt` 不存在。
- wrapper stdout/stderr 文件均为 0 bytes。
- 源码顺序：该 INFO 位于 data loader、模型和 optimizer 构建之前；`scaler.step(optimizer)` 位于后续 epoch/batch 循环内。
- fail-closed 恢复 guard 对真实现场给出：`validated_pretraining_wrapper_failure`、file_count=13、optimizer_steps=0。

## 已完成的完整性工作

中断前，第一次运行已完成教师 cache 全量树复算：

- files：99,334
- bytes：1,310,102,478
- SHA256：`6707900b5d4acb39752baeea11cd1e90d8d3394600b1fa3a6cc3984223860244`

static evidence writer 同时暴露一项 locator 兼容问题：它读取 evaluator lock 的上游身份字段 `source_file`，而 canonical validator 使用锁定的 `source.path`。正式 worktree 已用只读 junction 将上游身份布局映射到同一份官方 checkout；源文件 SHA256 为 `013949f6371dc11a93f4e5b1df448601b98cf5590e7651d103600f981a4ded19`，Git status 保持 0 行。未修改 exact commit。

## TDD 证据

- `Test-NativeRedirect.ps1`：生产函数缺失时 RED exit 1；实现后本地和 5090 均 PASS/exit 0。
- `Test-PreTrainingRecoveryGuard.ps1`：生产 guard 缺失时 RED exit 1；实现后本地和 5090 均 PASS/exit 0；加入 `history.jsonl` 的负例会被拒绝。
- `Test-PersistentProcess.ps1`：本地和 5090 均 PASS/exit 0，测试 PID 在 finally 中精确停止。
- 六个 PowerShell 控制/测试文件 parser errors 全为 0。

## 证据保全与恢复

第一次现场已保存到 5090 外置目录：

`E:\OV-OrthKD-R3\formal_control\mm26_canonical_seed42\pretraining_wrapper_failure_20260825T170502Z`

其中 17 个原始文件均在 manifest 中记录 bytes 和 SHA256，另含 manifest 自身，共 18 个文件；manifest 明确记录 optimizer_steps=0。正式 output 没有被整体删除，也未以 incompatible 或 blocked override 绕过。

受控恢复在 `2026-08-25T17:17:23.4681267Z` 以同一个 mode=start 命令启动：worker PID 11940、Python PID 16640 / 实际 PID 6352。没有改变 seed、config、资产、output、batch、epoch、step、early-stop 或 evaluator 参数。

## 后续验收

只有在恢复运行新写出的 `official_evaluator_hash.json` 同时满足 `source_exists=true` 和 `matches_lock=true`，并且 cache receipt 继续精确匹配时，才接受进入正式训练。训练完成后仍需按指导机械审计全部 provenance、history、checkpoint、prediction 和 final metrics。
