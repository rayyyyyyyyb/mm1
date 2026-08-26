# OV-OrthKD 当前正式复现状态

更新日期：2026-08-26

结果发布分支：`repro/canonical-seed42-results`

正式运行代码起点：`31b86c0d60c4bf2ed028edf1385ed5d2c9e89153`

正式配置：`configs/ov_orthkd_mm26_repro_ready.yaml`

## 最终判定

- 运行与产物：`CANONICAL_RUN_COMPLETED_AND_ARTIFACT_AUDIT_PASSED`
- 论文数值：`PAPER_NUMERICAL_REPRODUCTION_NOT_ACHIEVED`
- evaluator 覆盖：`CALIBRATED_SEGMENT_F1_MISSING`
- 消融与第二 seed：未启动

canonical OV-OrthKD seed42 已在 RTX 5090 上完成 30/30 epochs、12,000 optimizer steps，worker exit code 0；最终 artifact audit 为 `PASS`、errors=0。数据、教师缓存、T=10 shape、Git、evaluator、checkpoint 元数据和正式小型文件均通过机械审计。

但本次不是论文主数值的成功复现，也不是普通 seed 波动。

## 核心结果

| Group | Metric | Paper | Reproduction | Delta |
|---|---|---:|---:|---:|
| Total | AP | 0.816 | 0.741946 | -0.074054 |
| Total | AUROC | 0.750 | 0.633875 | -0.116125 |
| Total | OV-AVEL segment F1@0.5 | 0.596 | 0.540393 | -0.055607 |
| Total | Accuracy | 0.705 | 0.621100 | -0.083900 |
| Unseen | AP | 0.584 | 0.722398 | +0.138398 |
| Unseen | OV-AVEL segment F1@0.5 | 0.584 | 0.540544 | -0.043456 |
| Seen | OV-AVEL segment F1@0.5 | 0.625 | 0.540018 | -0.084982 |

论文 Fig. 4 报告的五-seed AP 标准差约为 `±0.003`；当前 Full AP 缺口 `0.074054` 约为该波动尺度的 24.7 倍，不能用随机种子或浮点差异解释。

## 与关键基线的关系

| Reference | AP | AUROC | Segment F1@0.5 | 当前相对差值 |
|---|---:|---:|---:|---|
| Student-only | 0.714 | 0.612 | 0.523 | `+0.027946 / +0.021875 / +0.017393` |
| Visual feature only | 0.778 | 0.701 | 0.568 | `-0.036054 / -0.067125 / -0.027607` |
| Zhou official fine-tuning | 0.745 | 0.650 | 0.569 | `-0.003054 / -0.016125 / -0.028607` |
| OV-OrthKD Full | 0.816 | 0.750 | 0.596 | `-0.074054 / -0.116125 / -0.055607` |

当前比 Student-only 稍好，但低于更简单的 Visual feature only；只在 AP 上接近 Zhou official baseline，核心 segment F1 低于它。这说明完整蒸馏机制的论文增益没有出现。

## 已确认的阈值退化

test 标签正类率为 `0.6154639175`。全正预测的 binary micro F1 为 `2p/(1+p)=0.7619655392`，与本次 `binary_micro_f1_at_0_5=0.7619655392` 逐位相同。30 个 validation epoch 中 29 个预测正类率精确为 1.0，另一个为 0.999828；validation 选择阈值后，test 仍有 98.7251% segment 被预测为正类。

因此 binary micro F1 的表面高值不能证明时间定位成功。生产 evaluator 也没有输出锁定名称 `ovavel_segment_f1_at_validation_selected_threshold`，不得把当前 calibrated binary F1 冒充论文 calibrated segment F1 `0.781`。

## 正式运行协议与身份

- `T_task=10, T_max=16, K_student=1, K_teacher=8, V_test=1`
- no 10→16 label/logit/feature/metric conversion
- seed 42、batch size 4、30 epochs、400 train batches/epoch
- AdamW、LR `2e-4`、CosineAnnealingLR `T_max=30`
- best checkpoint 由 validation AP 选择；best epoch 为第 1 epoch（内部 epoch 0）
- teacher cache：99,334 files、1,310,102,478 bytes、SHA256 `6707900b5d4acb39752baeea11cd1e90d8d3394600b1fa3a6cc3984223860244`
- 正式运行没有使用 incompatible resume、截断参数、early stop、第二次 preflight 或消融

## Web 诊断入口

1. [正式复现结果包说明](reports/formal_reproduction/README.md)
2. [完整正式运行报告](reports/formal_reproduction/canonical_seed42/CANONICAL_SEED42_REPRODUCTION_REPORT.md)
3. [数值与基线诊断](reports/formal_reproduction/canonical_seed42/CANONICAL_SEED42_RESULT_DIAGNOSIS.md)
4. [final metrics](reports/formal_reproduction/canonical_seed42/canonical_seed42/final_metrics.json)
5. [30-epoch history](reports/formal_reproduction/canonical_seed42/canonical_seed42/history.jsonl)
6. [最终 artifact audit](reports/formal_reproduction/canonical_seed42/canonical_seed42/final_artifact_audit.json)
7. [实际 resolved config](reports/formal_reproduction/canonical_seed42/canonical_seed42/resolved_config.yaml)
8. [正式 ready config](configs/ov_orthkd_mm26_repro_ready.yaml)
9. [全部正式 locks](configs/locks)

## 数据与仓库边界

GitHub 包含完整代码、配置、locks、测试以及本次运行的小型诊断证据。以下大型或受授权约束的内容只保留在 5090，不上传：

- OV-AVEBench 数据和 source/export manifests；
- InternVideo2、BEATs、CLAP checkpoints；
- 99,334-file teacher cache；
- `best.pt`、`last.pt`；
- validation/test prediction NPZ；
- 完整训练 stderr 进度流。

这些未上传文件的 bytes、SHA256、shape、数量与审计状态均记录在 result package 的小型 receipts 中。

## 下一步边界

在继续正式实验前，先审计 evaluator/AP 聚合语义、logit/概率分布和标签对齐，并设计同一代码管线下的 Student-only 与 Visual-feature-only 控制实验。根因未明确前，不通过改 LR、阈值或 loss 权重碰运气，也不启动大规模消融。
