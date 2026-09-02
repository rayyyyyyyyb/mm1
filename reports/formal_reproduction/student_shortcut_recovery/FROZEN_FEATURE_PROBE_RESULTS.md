# Frozen-feature probe audit：S8 主点与 S9 轨迹

日期：2026-09-02
审计类型：只读冻结表示审计（不是学生训练实验）
远端：5090，输出目录 `E:\OV-OrthKD-R3\frozen-probe-24eb3f6\outputs\diagnostic\frozen_feature_probe_audit_24eb3f6`

## 结论先行

- Artifact/runtime：`PASS`。四个 checkpoint 均完成特征提取、probe、单次 test 评估和 100 次 within-video shuffle；远端进程以退出码 `0` 结束。
- S8 step 1200（预注册 primary）：`VISUAL_INFORMATION_NOT_DECODABLE`。AQP 正对照通过，VQP 相对 QP 的三个增量分别为 C `+0.000955`、mixed AP `-0.002180`、mixed AUROC `-0.000906`。
- S9 轨迹：step 400 `INCONCLUSIVE`，step 800 `INCONCLUSIVE`，step 1200 `VISUAL_INFORMATION_NOT_DECODABLE`。正对照 AQP 在三个点均通过。
- 因此网页端的 S9 科学 FAIL 结论得到独立冻结 probe 支持：不能把失败归因于“只换 concat readout 就能恢复视觉”；S9 additive 训练后期的视觉信息本身已无法由学生表示稳定解码。
- 本审计不授权任何后续训练：`formal_student_training_started=false`、`formal_full_authorized=false`。不得启动 Visual-only、第二随机种子、延长 schedule、canonical loss 修改或正式 Full。

## 机制层复核

probe 结果与 S9 的训练轨迹共同支持“additive 改变了视觉路径优化动力学，并在后期诱发视觉时间表示坍缩”，而不只是支持“下游 concat readout 没有读取一个健康视觉表示”：

| checkpoint | S8 visual-backbone std | S9 visual-backbone std | S8 projected std | S9 projected std |
|---|---:|---:|---:|---:|
| step 0 | 0.218586 | 0.218586 | 0.066350 | 0.066350 |
| step 400 | 0.162155 | 0.135207 | 0.093735 | 0.059420 |
| step 800 | 0.163354 | 0.077180 | 0.082353 | 0.033636 |
| step 1200 | 0.138895 | 0.005928 | 0.056053 | 0.000853 |

输入 JPG 的 within-video temporal std 约为 `0.484911` 且在各状态不变，因此不能把末点坍缩解释为原始图片重复。S9 step 1200 的视觉/音频/查询 input-Jacobian 为 `0.814824/0.814824/1.629648`；这与 `0.5v+0.5a+q` 的结构系数一致，只说明人工扰动的局部导数非零，不说明真实视觉 token 在时间上有足够位移或与标签对齐。对应地，训练诊断中视觉 encoder 梯度在 step 400/800 为 `0.037198/0.033984`，音频 encoder 梯度为 `0.520859/0.246927`，视觉路径持续弱于音频路径。

因此当前最稳妥的根因排序是：随机初始化与短 exposure/统一学习率不利于视觉边界学习；三路投影直接相加且该控制旁路 temporal Transformer，缺少有效的 post-sum 对齐；Student-only BCE 与全局 AP 选择允许 audio/query shortcut；真正的 visual-teacher KD、teacher target projector 与 Full loss reduction 仍未被本审计验证。以上是机制解释，不把任何单层宣称为唯一根因，也不改变论文完整 additive + temporal Transformer 的待验证状态。

## 锁定协议

协议文件：`configs/diagnostics/recovery/ov_orthkd_frozen_feature_probe.yaml`
协议 SHA256：`8425b39e3b0b8b8439f836b2c04bc26026167d42ebebb5979cfabe156127ff86`

- 官方任务时间轴固定为 `T_task=10`，每个视频 10 个一秒 segment；`temporal_conversion=forbidden`。
- 每个 token 为 384 维；QP/VQP/AQP 使用相同的四块、1536 维 disposable logistic head：
  - QP：`[zero, q, zero, p]`
  - VQP：`[v, q, v*q, p]`
  - AQP：`[a, q, a*q, p]`
- train augmentation 关闭、loader 固定顺序、student `eval` + `inference_mode`；无 optimizer、无 backward、无 checkpoint write。
- alpha 只在 train 拟合、validation mixed pair-weighted concordance → mixed AP → mixed AUROC → 更强正则的顺序选择；test 只评估一次。
- alpha 网格 `{1e-5, 1e-4, 1e-3, 1e-2}`；100 次 within-video shuffle，seed `42`。
- 正常/成功门槛：`ΔC>=0.020` 且 (`ΔAP>=0.010` 或 `ΔAUROC>=0.010`)；AQP 为正对照。失败门槛：三项增量分别低于 `0.010/0.005/0.005`，或至少两项非正。

## 数据覆盖与来源锁

四个 checkpoint 的每个 split 均为相同官方 loader 顺序：

| split | 视频样本 | 任务段 | token shape | augmentation | shuffle |
|---|---:|---:|---|---|---|
| train | 13,182 | 131,820 | `[N,10,384]` | false | false |
| val | 5,798 | 57,980 | `[N,10,384]` | false | false |
| test | 5,820 | 58,200 | `[N,10,384]` | false | false |

所有 split 元数据、labels、offsets、base feature SHA256 已写入各 checkpoint 的 evidence JSON；约 1.5 GB/checkpoint 的 feature memmap 仅保留在 5090，没有上传 GitHub。

## Checkpoint 锁

| checkpoint | role | step | checkpoint SHA256 | resolved config SHA256 | outcome |
|---|---|---:|---|---|---|
| S8 step 1200 | primary | 1200 | `96b2f7833edb1054b661721b05afd8d32b39c1beb52d413dd957db69ea7eb33c` | `7ecf17f07da6f6d5c661824a93b5da335cd050d6a066684ed085a60b3af8b212` | `VISUAL_INFORMATION_NOT_DECODABLE` |
| S9 step 400 | trajectory | 400 | `c049c9a1e80efeb4be47512899d97bda1b93699aa15efef343672f45e14f8bad` | `6bb7520ae858b19c45d7be9cff22980b941a9dee3726cdd4d494cb1e285630a1` | `INCONCLUSIVE` |
| S9 step 800 | trajectory | 800 | `d49c4a56455a4ae98908b709ecc109c97e95c1ba3630eb4d90ecdfce38406441` | `6bb7520ae858b19c45d7be9cff22980b941a9dee3726cdd4d494cb1e285630a1` | `INCONCLUSIVE` |
| S9 step 1200 | trajectory | 1200 | `86191c355ef28f1b836e8a1c7d058ad4b65eec932e2fb2992f8a196bb73d3e36` | `6bb7520ae858b19c45d7be9cff22980b941a9dee3726cdd4d494cb1e285630a1` | `VISUAL_INFORMATION_NOT_DECODABLE` |

## Mixed-label probe 结果

以下是 test split 的 mixed-label 指标；门控使用 mixed AP/AUROC 和 pair-weighted concordance（不是全局 AP 字段）。括号内为相对 QP 的增量。

| checkpoint | probe | mixed AP | mixed AUROC | C | shuffle AP drop | shuffle AUROC drop | selected alpha |
|---|---|---:|---:|---:|---:|---:|---:|
| S8-1200 | QP | 0.623612 | 0.568014 | 0.554026 | 0.001332 | 0.001462 | 0.01 |
| S8-1200 | VQP | 0.621432 (-0.002180) | 0.567109 (-0.000906) | 0.554981 (+0.000955) | 0.001604 | 0.002472 | 0.01 |
| S8-1200 | AQP | 0.689172 (+0.065560) | 0.650082 (+0.082068) | 0.720880 (+0.166854) | 0.017474 | 0.026560 | 0.01 |
| S9-400 | QP | 0.624890 | 0.571687 | 0.551835 | 0.001136 | 0.001295 | 0.001 |
| S9-400 | VQP | 0.630583 (+0.005693) | 0.576163 (+0.004475) | 0.560684 (+0.008850) | 0.001858 | 0.002474 | 0.01 |
| S9-400 | AQP | 0.705226 (+0.080336) | 0.671044 (+0.099357) | 0.727847 (+0.176013) | 0.019069 | 0.028209 | 0.01 |
| S9-800 | QP | 0.617901 | 0.560719 | 0.554026 | 0.001121 | 0.001206 | 0.01 |
| S9-800 | VQP | 0.624726 (+0.006825) | 0.565187 (+0.004467) | 0.558156 (+0.004130) | 0.002148 | 0.002252 | 0.01 |
| S9-800 | AQP | 0.692507 (+0.074606) | 0.666063 (+0.105343) | 0.742962 (+0.188936) | 0.018981 | 0.031469 | 0.01 |
| S9-1200 | QP | 0.625917 | 0.570061 | 0.552874 | 0.001363 | 0.001403 | 0.01 |
| S9-1200 | VQP | 0.624184 (-0.001733) | 0.565806 (-0.004254) | 0.564702 (+0.011828) | 0.002116 | 0.002561 | 0.01 |
| S9-1200 | AQP | 0.691516 (+0.065599) | 0.667545 (+0.097484) | 0.723408 (+0.170534) | 0.017577 | 0.029302 | 0.01 |

QP/VQP/AQP 的 probe test 结果均来自同一个官方 19,410 mixed-label segment 子集（1,941 视频）；shuffle 只在每个视频内部重排 score，不改 labels 或 segment 边界。

## 独立核验

- 5090 主审计进程退出码：`0`；`summary.json.status=PASS`。
- 审计后远端进程检查：`AUDIT_PROCESS_EXITED`，匹配 `audit_frozen_feature_probes.py` 的进程数为 `0`。
- 四个结果 JSON 的远端/本地 SHA256 完全一致：
  - `s8_step1200.json` `AB9BA542ECFB1E134E7309C178265870A8195E9F739E8C0C0388A37EEFB67304`
  - `s9_step400.json` `8147DCB907AC0FFAAD14CE2EB008D5E21DA52EC5DA01722C4458DF2DFBFF1C33`
  - `s9_step800.json` `932C4A587FD7BF4D05C775FBA63DC1CBB0D4114ADFB473B1A6B7E67779BD18D8`
  - `s9_step1200.json` `3A9C5099EDF083921F0319A3D412D06FA8248D53ED979ECD68E80A5402359B4A`
  - `summary.json` `6B5544DA351F20B5E5120126F4B15578C2F71908436A8DEB1610DA1FA692ED41`
- 本地独立复算脚本检查：所有 JSON `allow_nan=False` 可序列化；四点 `state_unchanged=true`；split counts、T=10、384 维、delta 重算全部通过，输出 `LOCAL_VERIFY PASS`。
- 本审计读取 checkpoint 时严格校验嵌入 config SHA；此前使用错误 source config 的启动被拒绝并退出码 `1`，没有生成科学结果。

## 边界与下一步

这项审计只回答“冻结的学生 visual token 是否包含可由同容量 readout 解码的 label-aligned 信息”。它不能单独证明某个具体下游层是唯一原因，也不能把 S9 identity-temporal 控制外推为论文完整 additive + temporal Transformer 架构。

当前默认裁决保持：

```text
artifact_runtime_status = PASS
scientific_primary_status = VISUAL_INFORMATION_NOT_DECODABLE
next_training_experiment_authorized = false
formal_full_training_authorized = false
```

任何后续 readout control、visual-teacher KD 或 Visual-only bounded control 都必须先取得新的人工授权并重新预注册；本报告不构成训练授权。

证据文件：[summary.json](evidence/frozen_feature_probe/summary.json)、[S8 step1200](evidence/frozen_feature_probe/s8_step1200.json)、[S9 step400](evidence/frozen_feature_probe/s9_step400.json)、[S9 step800](evidence/frozen_feature_probe/s9_step800.json)、[S9 step1200](evidence/frozen_feature_probe/s9_step1200.json)。
