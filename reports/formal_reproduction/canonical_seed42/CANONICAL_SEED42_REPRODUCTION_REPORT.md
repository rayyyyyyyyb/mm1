# OV-OrthKD MM26 canonical seed42 正式复现报告

## 结论

canonical seed42 已完成 30/30 epochs、12,000 个 optimizer steps，以及 best-checkpoint 全量 validation/test 评估。worker exit code 为 0，最终机械 artifact audit 为 `PASS`、errors=0。

本次运行完整、协议与产物可审计，但**没有复现论文主数值**：test AP 为 0.741946，对论文 0.816 低 0.074054；AUROC 和官方 OV-AVEL segment F1@0.5 也明显偏低。因此不能将本次结果描述为论文数值复现成功。

此外，锁定配置要求报告 `ovavel_segment_f1_at_validation_selected_threshold`，而当前正式 evaluator 只输出 `binary_micro_f1_at_threshold`。报告保留实际 binary 指标，但不把它冒充论文 calibrated segment F1。

## 固定运行身份

- Git commit：`31b86c0d60c4bf2ed028edf1385ed5d2c9e89153`
- Git status：0 行
- claim：`paper_specified_reconstruction`
- config：`configs/ov_orthkd_mm26_repro_ready.yaml`
- seed：42
- output：`E:\OV-OrthKD-R3\formal-canonical-31b86c0\outputs\formal\mm26_canonical_seed42`
- 命令：`python scripts/train_ov_orthkd.py --config configs/ov_orthkd_mm26_repro_ready.yaml --output-dir outputs/formal/mm26_canonical_seed42`
- 启动：`2026-08-25T17:17:23.4681267Z`
- 完成：`2026-08-25T21:37:15.2900977Z`
- wall time：4:19:51.822
- incompatible marker：不存在

## 协议

| 项目 | 正式值 |
|---|---:|
| 任务时间段 `T_task` | 10 |
| 模型容量 `T_max` | 16 |
| 学生每段帧数 `K_student` | 1 |
| 教师每段帧数 `K_teacher` | 8（重复关键帧） |
| 测试视图 `V_test` | 1 |
| temporal resampling | false |
| epochs | 30 |
| 每 epoch train batches | 400 |
| global steps | 12,000 |

所有 validation/test prediction 均通过逐样本检查：每个样本恰好 10 个 segment，segment index 顺序精确为 0…9，没有 10→16 插值、复制或标签重采样。

## 训练摘要

- best epoch：1（checkpoint 内 zero-based epoch 0）
- best validation AP：0.7302036939345478
- final global step：12,000
- final learning rate：0.0
- epoch 累计 elapsed：14,424.447 秒
- max peak allocated GPU memory：6,566.866 MiB
- best checkpoint：565,912,209 bytes，SHA256 `01cdb036ec11768ced94331742490d62c1f62bf842b2b2ee03134101dba1f392`
- last checkpoint：565,912,209 bytes，SHA256 `5d021135744364b006bb6d8060499901846cb0c695ebf1f6935c0f2ba627d4ca`
- checkpoint reproduction fingerprint：`a9298aa8e02c4423894894ce79caca46a9a8605336134b63170a5a55f411faa9`

## Test 结果与论文对照

| Group | Metric | Paper | Reproduction | Δ |
|---|---|---:|---:|---:|
| Total | AP | 0.816 | 0.741946 | -0.074054 |
| Total | AUROC | 0.750 | 0.633875 | -0.116125 |
| Total | OV-AVEL segment F1@0.5 | 0.596 | 0.540393 | -0.055607 |
| Total | Accuracy | 0.705 | 0.621100 | -0.083900 |
| Unseen | AP | 0.584 | 0.722398 | +0.138398 |
| Unseen | Accuracy | 0.672 | 0.624783 | -0.047217 |
| Unseen | OV-AVEL segment F1@0.5 | 0.584 | 0.540544 | -0.043456 |
| Seen | Accuracy | 0.765 | 0.611899 | -0.153101 |
| Seen | OV-AVEL segment F1@0.5 | 0.625 | 0.540018 | -0.084982 |
| Total | Calibrated segment F1 | 0.781 | 未输出 | 不可比较 |

冻结 validation 阈值为 0.6659861520031973。实际 test `binary_micro_f1_at_threshold` 为 0.7635884131306417；这是 binary micro F1，不是锁定映射所称的 calibrated OV-AVEL segment F1，故不计算论文差值。

其他实际 test 指标：

- Total binary micro F1@0.5：0.7619655392469687
- Total query foreground macro F1@0.5：0.6558727361761897
- Total event F1@0.5：0.5774341351660939（supplemental）
- Seen AP：0.7892745152007632
- Unseen AUROC：0.6018936857329866

## Prediction 审计

| Artifact | Samples | Segments | Seen | Unseen | 每样本任务段 | SHA256 |
|---|---:|---:|---:|---:|---:|---|
| best validation | 5,798 | 57,980 | 1,651 | 4,147 | 10 | `17bc66fd7d8fc5a1445d5b35e32acca9f65d5d00afbd8547d02788ea9246bfc0` |
| final validation | 5,798 | 57,980 | 1,651 | 4,147 | 10 | `17bc66fd7d8fc5a1445d5b35e32acca9f65d5d00afbd8547d02788ea9246bfc0` |
| test | 5,820 | 58,200 | 1,664 | 4,156 | 10 | `e78338c52577fd44a2fe07cd9150b2a2a32721cc0996f68a9dfbb37d0c95e2d5` |

best validation 与最终重新加载 best 后的 validation prediction 逐字节 SHA 相同，证明最终评估确实使用保存的 best checkpoint。

## Provenance 与完整性

- teacher cache：99,334 files、1,310,102,478 bytes、SHA256 `6707900b5d4acb39752baeea11cd1e90d8d3394600b1fa3a6cc3984223860244`
- official evaluator：source exists、matches lock；expected/actual SHA256 均为 `013949f6371dc11a93f4e5b1df448601b98cf5590e7651d103600f981a4ded19`
- final metrics SHA256：`ebd0a4fc886813b2dd4820a1b3f5bf041baade29b96ec1cafa5f97ea88b1c2df`
- history SHA256：`f9ec5f29d81b0c0fc64da2cc5bdea2c5773384dba3c96a32f79cf10c89273c9b`
- final artifact audit SHA256：`8d6880516bfeef9fcd489f90b3d23ec875b253df2af076866b73fee7b3d11633`
- audit receipt 本地/5090 SHA 匹配；同步的小型正式文件逐项与 audit manifest SHA 匹配。

## 验证退出码

- cold gate `pip check`：0
- CUDA runtime verification：0
- exact-worktree full pytest：0，`388 passed in 329.83s`
- `git diff --check`：0
- 本地 control tests 4/4：全部 0
- 5090 control tests 4/4：全部 0
- formal worker：0
- final artifact audit：0，status `PASS`、errors 0

审计器首次运行因未显式传入 5090 的 MinGit 路径而以 exit 1 停止，未生成 PASS receipt、未修改 formal output；增加 `--git` 参数并传入锁定 MinGit 后完整重跑为 exit 0。

## 启动包装事件

第一次持久 worker 在任何 data loader、模型或 optimizer 创建前，被 PowerShell 5.1 将正常 stderr INFO 误判为终止异常；history/checkpoint 均不存在，optimizer steps=0。该现场已逐文件保存在 5090 外置 control archive。TDD 修复 native redirect 后，以同一 commit/config/output/seed 的 mode=start 受控恢复；正式结果没有使用 incompatible resume 或参数覆盖。详见 `01_PRETRAINING_WRAPPER_INCIDENT.md`。

## 最终判定与停止点

- 运行与 artifact 完整性：`CANONICAL_RUN_COMPLETED_AND_ARTIFACT_AUDIT_PASSED`
- 论文数值：`PAPER_NUMERICAL_REPRODUCTION_NOT_ACHIEVED`
- evaluator 报告覆盖：`CALIBRATED_SEGMENT_F1_MISSING`
- 消融：未启动

下一步应先审查 canonical 数值差距以及 calibrated segment F1 的生产输出定义；在此之前不启动 R6 controlled ablation，也不把 binary calibrated F1 写成论文 calibrated segment F1。
