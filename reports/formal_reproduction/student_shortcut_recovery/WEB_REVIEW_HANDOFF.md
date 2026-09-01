# Student shortcut recovery：网页审查交接

日期：2026-09-02

当前状态：**S9 paper-additive 单变量诊断已经完成。训练、A–E 与独立 posthoc 产物审计均 PASS；但预注册科学判定为 FAIL：visual-zero mixed AP/AUROC 略升，ΔC 仅 `0.000056`，未恢复视觉内容的标签对齐贡献。没有授权任何下一实验或正式 Full。**

这份入口供独立审阅者直接从 GitHub 网页核对。A0 是无训练的 checkpoint 捷径/模态诊断；S3 是相对三轮 S0 仅打开学生预训练的单变量诊断；S4 仅关闭现有训练图像增强；S7 仅将学生 temporal path 从 Transformer 改为 identity passthrough；S8 相对 S7 仅将 gate 从 learned softmax 改为从初始化起固定 `0.5/0.5`；S9 相对 S8 仅将 fusion 从 concat MLP 改为 paper-additive。所有运行均严格保持官方 `T_task=10`，没有任何 10→16 标签、logit 或指标转换；`T_max=16` 仅为位置编码容量。

## 先看结论：S9

完整结果见 [S9_RESULTS.md](S9_RESULTS.md)。S9 的唯一科学变化是 `student.fusion_mode=concat_mlp_query_conditioned→paper_additive_query_conditioned`，保持 fixed `0.5/0.5` gate、identity temporal path、seed42、Student-only BCE 和三轮 400-batch exposure。test AP/AUROC 为 `0.774657/0.679398`，相对 S8 仅 `+0.004896/+0.004912`；这不是科学成功门槛。

在 1,941 个 mixed-label 视频上，原始 AP/C 为 `0.657439/0.636175`，visual-zero AP/C 为 `0.657447/0.636118`。因此 `ΔAP=-0.0000082`、`ΔAUROC=-0.0000045`、`ΔC=+0.0000562`，同时两个 ranking 效应非正，严格触发预注册 FAIL。音频置零 AP 降 `0.035235`，原始 temporal shuffle AP drop 为 `0.035437`，说明审计本身能测到内容/时序依赖，但 additive readout 没有让视觉内容成为有效排序依据。A–E 与 posthoc artifact integrity 均 PASS；科学 FAIL 不等于运行或证据损坏。

S9 的 5090 独立再审计与正式 posthoc 字节一致，且两者都写入 `next_experiment_authorized=false`、`formal_full_training_authorized=false`。这只能拒绝当前 additive 控制，不能把某个具体 downstream 层宣称为唯一根因。

## S8 背景结论

S8 证据见 [S8_RESULTS.md](S8_RESULTS.md)。S8 best test AP/AUROC、binary micro F1@0.5、官方 segment/event F1@0.5 分别为 `0.769761/0.674486/0.687314/0.537494/0.502510`；相对 S7，AP/AUROC/segment F1 分别为 `+0.011156/+0.005313/+0.007208`。这说明数值仍在正常范围且全局排序继续改善，不是训练崩溃。

更关键的是表征层恢复：S8 step 1200 的 visual-backbone/projected temporal std 为 `0.138895/0.056053`，分别约为 S7 的 `40.7x/53.3x`；visual Jacobian 从 S7 的 `0.004885` 提升到 `0.274656`，step-800 visual-encoder gradient 也由约 `1.96e-5` 提升至 `0.041727`。但在 1,941 个 mixed 样本上，visual-zero AP 仅从 `0.649065` 变为 `0.648434`，下降 `0.000632`；audio-zero/both-zero 则下降 `0.030958/0.031151`，100 次样本内 temporal shuffle 平均下降 `0.034302`。因此固定 gate 确实阻止了视觉 backbone 表征塌缩，却没有让视觉内容成为最终排序的有效依据；剩余问题位于 concat fusion/decision 将视觉表征转化为标签相关决策的过程中。

S8 没有预注册可用于自动判成功的数值阈值，因此审计没有事后发明阈值。正式 post-hoc audit 为 PASS，但明确写入 `automatic_scientific_success_claimed=false`、`next_experiment_authorized=false` 和 `formal_full_training_authorized=false`。这不是“审计失败”，而是“产物可信、科学结果落在证据模式 2”。

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
- S8 scientific runtime：`60100c6fff95b313ae92bc91b10a3be7135dc437`；相对 S7 唯一科学变化为 `student.gate_mode=learned_softmax→fixed_equal`。
- S8 配置 canonical-LF SHA256：`9175ae127d602741f8e6357366b093dafec433d3a578d096be8d49ae2ad1c505`；compileall exit 0，5090 全量 `536 passed in 346.15s`。
- S8 training/A–E/post-hoc audits：均为 PASS，SHA256 分别为 `7aa1108a8f536f720735edec5183d9846d52e8b28ce7236db2f5121354bc6a11`、`54baa6c27b286226bce5698ef0a3e56456aadf739c577915d5a57c82af55ca7d`、`7784887d05199ae4d70a81c29d497d4a9cd6c689a0746d56aa459b83df4e0d5b`。
- S8 post-hoc reader fix：`6f39172120ab877c246d3fd6fbd1a4699a6f2871`；真实 schema 回归测试 `3 passed`、隔离 cross-suite `107 passed`、干净候选全量 `536 passed in 347.58s`。恢复只补跑 post-hoc，未重训、未重跑 A–E。
- S9 scientific/runtime commit：`b8ea747dd792c939251152ead734d1826c26980d` / `31497d58eb5d17e60cbebc6afa1bef5bcecb37a7`；相对 S8 唯一科学变化为 `student.fusion_mode=concat_mlp_query_conditioned→paper_additive_query_conditioned`。
- S9 配置 canonical-LF SHA256：`61942acb92fe0a9a1a87a828764073303761328783b515c606e97d8f10e26cbe`；exact candidate full suite `555 passed in 372.02s`，exit 0。
- S9 training/A–E/posthoc audits：均为 artifact PASS，SHA256 分别为 `a0a1b35fae2a5c5cf352e406b57e8f2d7cdd7828fe837f19f0230f7b03f0a7c4`、`54391fa046dd7ec2900bc613aabcb6f1200fa59e8d18b3a2b0d8da2ac6dae264`、`a9a3040738f5a1b2e003838c36960e10b0dbae77a88e3d1a3170d75aa4f7a740`；独立再审计与正式 posthoc SHA 完全一致。
- S9 worker exit code=0，阶段顺序为 `s9_training→training_audit→s9_ae→posthoc_audit`；A–E 17 modes、5,820 samples/58,200 T=10 segments、100 shuffles。科学分类严格为 FAIL，原因 `all_visual_effects_below_preregistered_fail_thresholds`，`next_experiment_authorized=false`、`formal_full_training_authorized=false`。
- validation/test prediction 分别含 57,980/58,200 个有序 segment，每个样本严格为索引 `0..9`。
- training AP、保存 NPZ AP 与 strict checkpoint rerun AP 在 `1e-12` 内一致；运行前后 Git HEAD exact、dirty=0。

## S0/S3/S4/S7/S8/S9 对比

| Run | 唯一科学变化 | Test AP | AUROC | F1@0.5 | 内容/时序诊断 |
|---|---|---:|---:|---:|---|
| S0 | reconstructed Student-only | 0.748745 | 0.636135 | 0.540393 | 全正；both-zero AP 0.743670 |
| S3 | `pretrained false→true` | 0.745689 | 0.652332 | 0.540393 | 音频主导；both-zero AP 0.736156 |
| S4 | `train_augment true→false` | 0.703470 | 0.596009 | 0.540393 | 更快塌缩；both-zero AP 0.749499 |
| S7 | `temporal Transformer→identity` | 0.758605 | 0.669173 | 0.530286 | 排序改善但视觉仍为零贡献；both-zero AP 0.733402 |
| S8 | `learned gate→fixed 0.5/0.5` | 0.769761 | 0.674486 | 0.537494 | 视觉表征恢复但 visual-zero mixed AP drop 仅 0.000632 |
| S9 | `concat MLP→paper additive` | 0.774657 | 0.679398 | 0.525174 | artifact PASS；visual-zero mixed AP/C 不降，科学判定 FAIL |

S3 说明“只开学生预训练”不充分；S4 说明“完全关闭现有增强”不但不充分，而且使塌缩更严重；S7 说明 bypass temporal Transformer 能改善排序，却不能恢复视觉路径；S8 说明固定等权 gate 能恢复视觉表征和梯度，但 concat fusion/decision 仍没有把视觉内容用于最终排名；S9 进一步显示在保持 S8 其余条件不变时，替换为论文式 additive readout 仍未产生视觉因果效应。这些诊断都没有给出启动正式 Full 的依据。

## 建议阅读顺序

1. [S9 完整结果、预注册门槛与当前边界](S9_RESULTS.md)
2. [S9 independent posthoc audit](evidence/s9/posthoc/s9_posthoc_audit.json)
3. [S9 independent posthoc re-audit](evidence/s9/posthoc/s9_posthoc_reaudit.json)
4. [S9 full A–E evidence](evidence/s9/posthoc/s9_zero_training_ae.json)
5. [S9 training audit](evidence/s9/control/s9_training_audit.json)
6. [S8 完整结果、三种证据模式与背景](S8_RESULTS.md)
7. [A–F zero/near-zero-training 审计与前置决策](ZERO_TRAINING_AUDITS.md)
8. [A–F 独立 artifact audit](evidence/zero_training/zero_training_artifact_audit.json)
9. [S7 完整结果、因果门槛与结论](S7_RESULTS.md)
10. [S4 完整结果与恢复门槛](S4_RESULTS.md)
11. [S3 完整结果与恢复门槛](S3_RESULTS.md)
12. [A0 四组捷径与模态基线](A0_RESULTS.md)
13. [实现、运行器与独立审计说明](IMPLEMENTATION_AUDIT.md)
14. [小型证据清单](evidence/README.md) 与 [执行脚本清单](runtime/README.md)

## 希望独立审阅者重点判断

1. S9 已在 additive readout 下仍显示 visual-zero 近乎不变；在不改变 canonical loss 或启动 Full 的边界内，下一项是否应做零训练 readout/linear-probe，以区分 representation 与 label alignment？
2. S9 的 forced visual concordance=`0.550823`、forced-visual shuffle AP drop=`0.001726`，是否支持先审查 visual teacher/projector target 对齐，而不是继续改变 fusion 算子？
3. 是否同意 S9 的严格科学 FAIL 与 artifact PASS 分离表述，并在任何后续执行前给出唯一、可审计、带阈值的人工授权？

## 边界

本阶段已完成 A–F 后获授权的 S8 与 S9 bounded controls；没有启动 Visual-only、第二 seed、延长训练或正式 Full，也没有修改 canonical 配置、loss、evaluator、teacher cache 或 full-run guard。S9 只改变 fusion operator，训练与 A–E/posthoc 均完成；科学结果严格为 FAIL，且任何后续/Full 授权字段均为 false。GitHub 不上传数据集、teacher/student checkpoints、timm cache、prediction NPZ、bundle、archive 或完整日志；对应 SHA256、bytes、shape、数量和审计结论由这里的小型 receipts 锁定，大资产仍保存在 5090。
