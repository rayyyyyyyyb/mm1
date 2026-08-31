# Canonical seed42 正式复现证据入口

> **2026-08-31 最新诊断：** Student shortcut recovery 的 A0、S3（仅开启学生预训练）和完整后验审计已经结束。S3 没有通过恢复门槛，正式 Full 继续暂停。请优先阅读 [S3 网页审查交接](student_shortcut_recovery/WEB_REVIEW_HANDOFF.md)；下文保留的是较早的 canonical seed42 正式运行记录。

本目录是给独立审阅者和诊断对话使用的网页入口。它把正式训练所用的完整代码树，与本次运行的小型结果、实际 resolved config、环境冻结、数据/教师/evaluator 身份哈希和最终审计收据放在同一个 Git commit 中。

最新的固定门控与论文式加性融合单变量实验已经完成，请先读 [causal fusion diagnostics 网页审查入口](causal_fusion_diagnostics/WEB_REVIEW_HANDOFF.md)。两项修改都未恢复健康的时间定位，正式 Full 复跑仍应暂停。

## 先读结论

canonical OV-OrthKD seed42 已完成 30 epochs / 12,000 optimizer steps，worker exit 0，full artifact audit `PASS`、errors=0；但论文数值没有复现。

| Metric | Paper Full | Reproduction | Delta |
|---|---:|---:|---:|
| AP | 0.816 | 0.741946 | -0.074054 |
| AUROC | 0.750 | 0.633875 | -0.116125 |
| OV-AVEL segment F1@0.5 | 0.596 | 0.540393 | -0.055607 |

当前 AP 约等于 Zhou official fine-tuning baseline，但 segment F1 低 0.028607；当前高于 Student-only，却低于 Visual feature only。`binary_micro_f1_at_0_5=0.7619655392` 与按 test 正类率计算的全正预测 F1 完全相等，因此不能把该 binary 指标当作成功定位的证据。

## 推荐阅读顺序

1. [发布与验证收据](PUBLISH_RECEIPT.md)
2. [数值与基线诊断](canonical_seed42/CANONICAL_SEED42_RESULT_DIAGNOSIS.md)
3. [完整正式运行报告](canonical_seed42/CANONICAL_SEED42_REPRODUCTION_REPORT.md)
4. [final metrics](canonical_seed42/canonical_seed42/final_metrics.json)
5. [30-epoch history](canonical_seed42/canonical_seed42/history.jsonl)
6. [实际 resolved config](canonical_seed42/canonical_seed42/resolved_config.yaml)
7. [最终 artifact audit](canonical_seed42/canonical_seed42/final_artifact_audit.json)
8. [运行环境与依赖冻结](canonical_seed42/canonical_seed42/cuda_environment.json)
9. [代码/manifest/lock/cache/evaluator 身份](canonical_seed42/canonical_seed42/README.md)
10. [正式 ready config](../../configs/ov_orthkd_mm26_repro_ready.yaml) 与 [全部 locks](../../configs/locks)
11. [启动控制器与 wrapper 事件说明](canonical_seed42/01_PRETRAINING_WRAPPER_INCIDENT.md)

## 代码与证据边界

该分支的父代码身份是 `31b86c0d60c4bf2ed028edf1385ed5d2c9e89153`。运行使用的模型、loss、loader、evaluator、训练器、配置和测试都在当前仓库中；`canonical_seed42/canonical_seed42/config_resolved.yaml` 是实际运行时解析后的配置快照。

GitHub 不包含数据集、教师 checkpoints/cache、student checkpoints、prediction NPZ 或完整进度日志。它们的精确 bytes/SHA256、shape、数量和审计结论记录在上传的小型 receipts 中。没有用占位文件代替大资产，也没有把未上传的大资产声称为 GitHub 内可复算内容。

## 独立诊断优先级

1. 核对当前 AP、unseen AP 和论文 AP 的聚合语义是否完全一致。
2. 检查 logits/probabilities 分布以及为什么 0.5 阈值产生全正预测。
3. 核对标签 mask、padding、sample offsets 与 T=10 evaluator 输入。
4. 在不改公共管线的前提下设计 Student-only/Visual-feature-only 控制运行，以区分公共训练问题和 Full distillation 分支问题。
5. 在根因明确前不要调参、重建教师 cache 或启动大规模消融。
