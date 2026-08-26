# OV-OrthKD 当前正式复现状态

更新日期：2026-08-26

结果发布分支：`repro/canonical-seed42-results`

当前诊断分支：`repro/root-cause-diagnostics`

正式运行代码起点：`31b86c0d60c4bf2ed028edf1385ed5d2c9e89153`

正式配置：`configs/ov_orthkd_mm26_repro_ready.yaml`

## 最终判定

- 运行与产物：`CANONICAL_RUN_COMPLETED_AND_ARTIFACT_AUDIT_PASSED`
- 论文数值：`PAPER_NUMERICAL_REPRODUCTION_NOT_ACHIEVED`
- evaluator 覆盖：原运行缺失；post-hoc 官方 segment 公式已补算，未来输出代码已修复
- 同管线控制：Student-only / Visual-only 配置已机械锁定，尚未启动

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

因此 binary micro F1 的表面高值不能证明时间定位成功。对保存预测应用 validation 冻结阈值和官方 query/background segment 公式后，test calibrated segment F1 仅为 `0.544939`，不是论文 `0.781`；该补算修复了报告缺口，但没有解释主性能差距。

## 根因诊断进度

- Visual direct logits 已覆盖全部 validation/test T=10 cache：test AP `0.780220`、AUROC `0.716227`，接近论文 Table 2 的 `0.776/0.716`。
- 透明 reconstruction linear probe（论文未公开 probe 优化细节）得到 visual test `0.815682/0.735034`、audio test `0.790812/0.732781` AP/AUROC。它们不是 archival-exact Table 2 数值，但证明当前教师特征包含充足可分边界信号。
- test global-micro AP 为 `0.741946`，per-query macro AP 为 `0.638631`，说明聚合语义会显著影响 AP；现有会议 AP mapping 仍是 reconstruction assumption。
- test 每个样本 10 个 logits 的平均段内标准差仅 `0.001085`，中位数约 `0.000072`。当前 student 主要产生近似样本级常数分数，没有学到可靠的 10 段内部时间边界。
- Student-only / Visual-only 均已配置相同的只读前期数值诊断：只采样 epoch 1--3 的首 batch，记录 logits、门控、路径/teacher-target 方差与有效秩、pre-clip 梯度和 projector 漂移；它不修改 forward、loss、optimizer、best selection 或 evaluator。
- Zhou 官方输出重评分 Gate 暂时无法执行：锁定 OV-AVEL 上游仓库没有发布 fine-tuning checkpoint 或 prediction，`.checkpoints/readme.txt` 只有 62 bytes。不得用本模型预测替代。

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
10. [根因诊断 review 与 Gate 结果](reports/formal_reproduction/root_cause_diagnostics/01_GATE_RESULTS.md)
11. [prediction aggregation audit](reports/formal_reproduction/root_cause_diagnostics/prediction_aggregation_audit.json)
12. [teacher visual probe receipt](reports/formal_reproduction/root_cause_diagnostics/teacher_visual_probe.json)
13. [teacher audio probe receipt](reports/formal_reproduction/root_cause_diagnostics/teacher_audio_probe.json)

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

下一道门是先运行严格同源 Student-only，再运行保留 text 的 Visual-feature-only。根因未明确前，不改默认 fusion、预训练、scheduler 或 loss 权重，不启动第二 seed 或大规模消融。
