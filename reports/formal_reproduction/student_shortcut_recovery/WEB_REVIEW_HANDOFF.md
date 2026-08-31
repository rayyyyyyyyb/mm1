# Student shortcut recovery：网页审查交接

日期：2026-08-31

当前状态：**S3 与 S4 均未通过恢复门槛；正式 Full 复现继续暂停。**

这份入口供独立审阅者直接从 GitHub 网页核对。A0 是无训练的 checkpoint 捷径/模态诊断；S3 是相对三轮 S0 仅将 `student.pretrained` 从 `false` 改为 `true` 的单变量诊断；S4 是相对 S0 仅将 `data.train_augment` 从 `true` 改为 `false` 的单变量诊断。三者均严格保持官方 `T_task=10`，没有任何 10→16 标签、logit 或指标转换；`T_max=16` 仅为位置编码容量。

## 先看结论

S3 best-checkpoint test AP/AUROC/F1@0.5 为 `0.745689/0.652332/0.540393`。预训练短暂增加了时间变化，但最终仍在 0.5 阈值下全预测为正，视觉置零没有代价，双模态全置零仍保留 98.72% AP；恢复的变化主要来自音频，未恢复健康的视听时序定位。

S4 test AP/AUROC/F1@0.5 为 `0.703470/0.596009/0.540393`，相对 S0 分别变化 `-0.045274/-0.040126/0`。关闭现有训练图像增强后：

- step 400 的视觉/音频 gate 已变为 `0.002146/0.997854`，gate saturation 为 `1.0`；
- 视觉/音频 encoder gradient 降到 `2.24e-7/0.002410`；
- 原始 test logit 的样本内时间标准差仅 `2.48e-5`，是 S0 的 0.77%；
- query+position prior AP `0.719324`，高于模型原始 AP `0.703470`；
- 100 次样本内时间打乱后平均 AP 反而升至 `0.704645`；
- visual-zero AP `0.703225`，基本不变；audio-zero AP `0.750441`、both-zero AP `0.749499`，均明显高于原始 AP；
- 四种 content-ablation 模式在 0.5 阈值下仍全部预测为正。

因此，S4 不是数值略有误差，而是更强的内容无关捷径：输入 encoder 仍产生变化，但 shared/decision/head 路径把它压缩掉，学习到的音频内容甚至降低了全局排序 AP。当前证据排除的不是“所有增强”，而仅是“完全关闭现有空间增强可以修复问题”这一假设。canonical `data.train_augment=true` 应保持不变。

## 精确运行与审计身份

- A0 runtime：`f739399463c082cd670dff56e43c710d4fa6f283`；5090 全量 `457 passed`。
- S3 runtime：`a0aa4d7ad4b98455e26a2fe6ff2537a321293233`；5090 全量 `458 passed`。
- S4 runtime：`74d211d34ace74ce3b74ea082a7dfd0379b251fb`；focused `5 passed`、compileall exit 0、5090 全量 `461 passed in 335.90s`。
- S4 配置 canonical-LF SHA256：`5b81218b55907a5dfb0419e62eff2128f0d08ce9301c97c081237f8c8f599b33`。
- S4 candidate verification receipt：`f5cba2ea8d7504717ca3bdf458eb633c178ba34f956f5162d5759f284665fcf3`。
- S4 training artifact audit：PASS，SHA256 `6f28df765bd436cf38db8fe0a38a239ce3d967518a934d214ebeee5416faa962`。
- S4 posthoc artifact audit：PASS，SHA256 `1a9751cbafe3f8504105063150f33cc09214abafb7768e88a1ba4f5c765dfe80`。
- S4 exposure：seed 42，3 epochs × 400 batches，global step 1200；`student.pretrained=false`，所有 KD 权重为 0。
- validation/test prediction 分别含 57,980/58,200 个有序 segment，每个样本严格为索引 `0..9`。
- training AP、保存 NPZ AP 与 strict checkpoint rerun AP 在 `1e-12` 内一致；运行前后 Git HEAD exact、dirty=0。

## S0/S3/S4 对比

| Run | 唯一科学变化 | Test AP | AUROC | F1@0.5 | 内容/时序诊断 |
|---|---|---:|---:|---:|---|
| S0 | reconstructed Student-only | 0.748745 | 0.636135 | 0.540393 | 全正；both-zero AP 0.743670 |
| S3 | `pretrained false→true` | 0.745689 | 0.652332 | 0.540393 | 音频主导；both-zero AP 0.736156 |
| S4 | `train_augment true→false` | 0.703470 | 0.596009 | 0.540393 | 更快塌缩；both-zero AP 0.749499 |

S3 说明“只开学生预训练”不充分；S4 说明“完全关闭现有增强”不但不充分，而且使塌缩更严重。两者都没有给出启动正式 Full 的依据。

## 建议阅读顺序

1. [S4 完整结果与恢复门槛](S4_RESULTS.md)
2. [S3 完整结果与恢复门槛](S3_RESULTS.md)
3. [A0 四组捷径与模态基线](A0_RESULTS.md)
4. [实现、运行器与独立审计说明](IMPLEMENTATION_AUDIT.md)
5. [S4 training audit](evidence/s4/control/s4_training_artifact_audit.json)
6. [S4 prediction-shortcut JSON](evidence/s4/posthoc/prediction_shortcut.json)
7. [S4 content-ablation/path-scale JSON](evidence/s4/posthoc/checkpoint_modality.json)
8. [S4 posthoc audit](evidence/s4/posthoc/s4_posthoc_artifact_audit.json)
9. [S4 resolved config](evidence/s4/training/resolved_config.yaml) 与 [三轮 history](evidence/s4/training/history.jsonl)
10. [小型证据清单](evidence/README.md) 与 [执行脚本清单](runtime/README.md)

## 希望独立审阅者重点判断

1. 在 S4 已排除“完全关闭增强”的情况下，下一项是否应优先隔离 gate/shared-path 的快速坍缩，而不是直接启动 clip-consistent augmentation 或延长训练？
2. 是否应先用一个有明确可证伪门槛的 bounded control 限制 gate 偏置或冻结/分阶段训练，再要求 temporal shuffle 和双模态置零造成显著性能损失？
3. query+position prior 与 both-zero 已超过 S4 原始 AP，当前 checkpoint selection 是否应增加内容依赖门槛，而不是仅按 global validation AP 选 best？
4. 在不猜历史代码的前提下，S5（clip-consistent augmentation）或 S6（exposure/scheduler）哪个只能在 gate/content-dependence 问题被隔离后再运行？

## 边界

本阶段没有启动 S5、S6、Visual-only 或正式 Full，也没有修改 canonical 配置、训练器、模型、loss、evaluator、teacher cache 或 full-run guard。GitHub 不上传数据集、teacher/student checkpoints、timm cache、prediction NPZ、bundle、archive 或完整日志；对应 SHA256、bytes、shape、数量和审计结论由这里的小型 receipts 锁定，大资产仍保存在 5090。
