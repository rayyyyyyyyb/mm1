# Student shortcut recovery：网页审查交接

日期：2026-09-01

当前状态：**S7 仍是预注册因果失败；其后的 A–F zero/near-zero-training 审计完整通过，并仅授权 S8 identity + fixed-equal-gate 单变量诊断。正式 Full 复现继续暂停。**

这份入口供独立审阅者直接从 GitHub 网页核对。A0 是无训练的 checkpoint 捷径/模态诊断；S3 是相对三轮 S0 仅打开学生预训练的单变量诊断；S4 仅关闭现有训练图像增强；S7 仅将学生 temporal path 从 Transformer 改为 identity passthrough。所有运行均严格保持官方 `T_task=10`，没有任何 10→16 标签、logit 或指标转换；`T_max=16` 仅为位置编码容量。

## 先看结论

最新 A–F 证据见 [ZERO_TRAINING_AUDITS.md](ZERO_TRAINING_AUDITS.md)。全量 58,200 张 JPG 并非相同/损坏；reconstructed step zero 的 visual-backbone/projected temporal std 为 `0.218586/0.066350`，到 step 400 已降为 `0.004290/0.001516`。fusion 静态三块权重范数近似相等，但 step 800 visual/audio/query Jacobian 为 `0.001385/0.393753/1.142958`。即使强制纯视觉，visual-zero mixed AP drop 也只有 `0.000066`，说明事后 gate 不能恢复已塌缩表示。音频 donor/shuffle 则把 mixed pairwise concordance 从 `0.667107` 降到 `0.505–0.520`，证明音频仍携带样本时序信息。canonical Full projector probe 还证明现有 mean reduction 将 loss 与梯度精确缩小 256×，而一次 disposable sum-reduction AdamW step 可正常改变 clone，不触碰源 checkpoint。

S7 best-checkpoint test AP/AUROC/F1@0.5 为 `0.758605/0.669173/0.530286`，相对 S0 为 `+0.009861/+0.033038/-0.010107`。数值不是整体跑偏：全局排序确有改善，0.5 阈值下的全正塌缩也缓解。但预先规定必须在 step 400 和 800 同时通过的因果门槛在两点均失败：shuffle AP drop 仅为 `0.005508/0.010488`，both-zero AP drop 仅为 `0.010096/0.003133`。因此不能把 temporal Transformer 判为主要塌缩源。

S7 step 1200 的 visual-zero AP 与原始 AP 仅差 `7.95e-8`；audio-zero/both-zero AP 为 `0.733598/0.733402`。视觉内容仍完全没有可测贡献，内容依赖几乎全部来自音频。mean-centered AP 与 per-query macro AP 均超过 S0，但这只满足“更强恢复”辅门槛，不足以推翻早期 checkpoint 的因果失败。完整数字和门槛见 [S7_RESULTS.md](S7_RESULTS.md)。

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
- S7 runtime：`a7f0dc06d6a98493c0d03f1caa2059e31c50b648`；focused `16 passed`、compileall exit 0、5090 全量 `477 passed in 354.75s`。
- S7 配置 canonical-LF SHA256：`26e3f21504d7ce3f9a5498b8c89073fc910db80cbdf058c4b6a397b8735518b6`。
- S7 candidate verification receipt：`ce10e08506e7382bedfc16442c4d46f30834b2f20b0b90d54148100193ae7cf9`。
- S7 training/posthoc audits：均为 PASS，SHA256 分别为 `6583c7f403041be961bba5a40dd7f7e4c8f8d38fd1fee2c7548396b5b6e30dc2` 与 `1207c255ccbd918cb5c2899f7da929170c8020f63becd7548e29c473f9671956`。
- S7 exposure：seed 42，3 epochs × 400 batches，global step 1200；唯一科学变化为 `student.temporal_path_mode=identity_passthrough`。
- validation/test prediction 分别含 57,980/58,200 个有序 segment，每个样本严格为索引 `0..9`。
- training AP、保存 NPZ AP 与 strict checkpoint rerun AP 在 `1e-12` 内一致；运行前后 Git HEAD exact、dirty=0。

## S0/S3/S4/S7 对比

| Run | 唯一科学变化 | Test AP | AUROC | F1@0.5 | 内容/时序诊断 |
|---|---|---:|---:|---:|---|
| S0 | reconstructed Student-only | 0.748745 | 0.636135 | 0.540393 | 全正；both-zero AP 0.743670 |
| S3 | `pretrained false→true` | 0.745689 | 0.652332 | 0.540393 | 音频主导；both-zero AP 0.736156 |
| S4 | `train_augment true→false` | 0.703470 | 0.596009 | 0.540393 | 更快塌缩；both-zero AP 0.749499 |
| S7 | `temporal Transformer→identity` | 0.758605 | 0.669173 | 0.530286 | 排序改善但视觉仍为零贡献；both-zero AP 0.733402 |

S3 说明“只开学生预训练”不充分；S4 说明“完全关闭现有增强”不但不充分，而且使塌缩更严重；S7 说明 bypass temporal Transformer 能改善排序，却不能恢复健康的视听时序依赖。三者都没有给出启动正式 Full 的依据。

## 建议阅读顺序

1. [A–F zero/near-zero-training 审计、解释与 S8 决策](ZERO_TRAINING_AUDITS.md)
2. [A–F 独立 artifact audit](evidence/zero_training/zero_training_artifact_audit.json)
3. [S7 完整结果、因果门槛与结论](S7_RESULTS.md)
4. [S7 checkpoint trajectory](evidence/s7/posthoc/s7_checkpoint_trajectory.json)
5. [S7 independent posthoc audit](evidence/s7/posthoc/s7_posthoc_artifact_audit.json)
6. [S7 training audit](evidence/s7/control/s7_training_artifact_audit.json)
7. [S4 完整结果与恢复门槛](S4_RESULTS.md)
8. [S3 完整结果与恢复门槛](S3_RESULTS.md)
9. [A0 四组捷径与模态基线](A0_RESULTS.md)
10. [实现、运行器与独立审计说明](IMPLEMENTATION_AUDIT.md)
11. [小型证据清单](evidence/README.md) 与 [执行脚本清单](runtime/README.md)

## 希望独立审阅者重点判断

1. S7 在 early checkpoint 明确失败、但 best AP/AUROC 改善的组合证据，是否足以排除把 temporal Transformer 作为下一项主要修复对象？
2. 视觉置零在 S7 仍完全无代价、gate 在 step 800 为 `0.001115/0.998885`，下一项是否应优先隔离 gate/fusion 的音频饱和，而不是修改 temporal encoder 的归一化方式？
3. both-zero 仍保留较高 AP、shuffle 影响很小，checkpoint selection 是否必须加入内容依赖门槛，避免只按 global validation AP 选出捷径模型？
4. 下一项 bounded control 应怎样设置单变量和预注册门槛，才能区分 gate 形成、query/position prior 与 decision head 三个剩余来源？

## 边界

本阶段在已完成 S7 之后只运行了 A–F 零/近零训练审计；没有启动 S8、S9、第二 seed 或正式 Full，也没有修改 canonical 配置、loss、evaluator、teacher cache 或 full-run guard。A–E 没有 optimizer；F 只更新未持久化的内存 clone。GitHub 不上传数据集、teacher/student checkpoints、timm cache、prediction NPZ、bundle、archive 或完整日志；对应 SHA256、bytes、shape、数量和审计结论由这里的小型 receipts 锁定，大资产仍保存在 5090。
