# OV-OrthKD 正式复现归档

本目录保存正式复现阶段的小型计划、状态、控制脚本、审计报告和可公开结果摘要。大型数据、checkpoint、教师缓存、训练输出、预测数组和日志主体只保留在 RTX 5090，不进入 GitHub。

唯一代码起点：

- 分支：`repro/r5-final-runtime-protocol-and-readiness`
- commit：`31b86c0d60c4bf2ed028edf1385ed5d2c9e89153`
- 正式配置：`configs/ov_orthkd_mm26_repro_ready.yaml`
- 当前唯一获准 run：canonical OV-OrthKD，seed 42

目录文件：

- `00_CANONICAL_SEED42_EXECUTION_PLAN.md`：Phase 0–4 执行和验收计划。
- `CURRENT_STATUS.md`：当前运行状态和最后一次机械证据。
- `01_PRETRAINING_WRAPPER_INCIDENT.md`：正式 optimizer 之前的 wrapper 事件、证据保全、TDD 修复和受控恢复说明。
- `CANONICAL_SEED42_REPRODUCTION_REPORT.md`：30 epochs 最终指标、论文差值、完整性证据和停止判定。
- `CANONICAL_SEED42_RESULT_DIAGNOSIS.md`：与 Student-only、Visual feature only、Zhou official baseline 和论文 Full 的数值对照，以及近全正预测退化的机械推导。
- `audit_canonical_seed42.py`：独立 full artifact audit 脚本。
- `canonical_seed42/`：从 5090 回收的小型正式 evidence；不含 checkpoint、prediction、数据或教师 cache。
- `run_canonical_seed42.ps1`：5090 上的 fail-closed 启动、恢复和状态控制器。
- `run_canonical_seed42_worker.ps1`：由 WMI 持久启动、实际调用锁定 Python 的 worker。
- `PersistentProcess.psm1`：脱离 SSH job 的进程原语和 fail-closed 恢复 guard。
- `tests/`：持久进程、native redirect 和零训练步恢复门禁行为测试。

正式协议固定为 `T_task=10, T_max=16, K_student=1, K_teacher=8, V_test=1`。本阶段不启动消融，不重新运行真实 preflight，不重新导出教师缓存。

当前正式结果为 AP `0.741946`、AUROC `0.633875`、OV-AVEL segment F1@0.5 `0.540393`；运行和 artifact audit 完成通过，但论文 Full `0.816/0.750/0.596` 的数值没有复现。开始诊断时请先阅读数值诊断和 `canonical_seed42/final_artifact_audit.json`，不要只看 binary micro F1。
