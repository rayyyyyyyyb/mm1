# Visual-only sum checkpoint：只读归因审计

日期：2026-09-04
分支：`repro/student-shortcut-recovery`
审计状态：`PASS`（仅表示 artifact/runtime 审计完成，不表示论文机制已复现）

## 范围与不可变约束

本审计针对已完成的 Visual-only、Eq. 9 风格 `sum` reduction、seed 42 运行的 `best.pt`（global step 3200，human epoch 8）和 `last.pt`（global step 12000）。它只做推理和 post-hoc intervention：不构造 optimizer、不执行反向更新、不写 checkpoint，也不解除 canonical Full guard。

所有评估仍严格使用官方 `T_task=10`：每个样本 10 个一秒任务片段，测试视图数为 1，没有任何 `10→16` 转换。归因干预只作用于测试集中同时含正、负标签的 1,941 个样本（19,410 个有效片段），阈值沿用 validation-calibrated `0.4358334281623338`；音频时序打乱使用 seed 42、100 次重复。

原始测试 archive 与 fresh best-checkpoint forward 的 logits 最大绝对差为 `2.38418579101563e-07`，因此干预与已保存结果在同一 checkpoint、同一数据顺序上对齐。

## 结果

全测试集的原始 archive 未被修改：global segment-micro AP `0.7545760852128325`、AUROC `0.6565048482408069`。mixed-label 子集上的干预结果如下（该子集数值不应与全测试集 AP 直接混用）。

| 模式 | AP | AUROC | segment F1 | 相对原始 AP | 相对原始 AUROC |
|---|---:|---:|---:|---:|---:|
| original | 0.608308899 | 0.553055128 | 0.350533935 | 0 | 0 |
| visual zero | 0.608176629 | 0.553026316 | 0.350835738 | -0.000132269 | -0.000028813 |
| audio zero | 0.613144814 | 0.555445774 | 0.351332399 | +0.004835916 | +0.002390646 |
| both zero | 0.612538733 | 0.555876867 | 0.351332399 | +0.004229834 | +0.002821740 |
| audio temporal shuffle | 0.607603335 | 0.549721341 | 0.350659157 | -0.000705563 | -0.003333787 |

`visual zero` 几乎不改变 mixed-label 决策（AP 下降约 `1.3e-4`，AUROC 下降约 `2.9e-5`），不能称为“视觉内容对 localization decision 有实质贡献”的证据。相反，置零音频或同时置零音频和视觉略微提高该子集的排序指标，说明当前模型的输入路径和校准仍存在 shortcut/offset 现象；这不是 Full 增益已经恢复的证据。音频时序打乱的 mean AP drop 为 `0.000661118`、mean AUROC drop 为 `0.003176299`（100 次、在每个 mixed sample 内打乱），表明音频时序扰动有可测但很小的影响。

诊断提供的 mixed-only pairwise concordance（pair-weighted）为：original `0.553534304`、visual zero `0.554686183`、audio zero `0.537829409`、both zero `0.534050683`、audio temporal shuffle `0.517699612`。该统计支持“视觉置零不改变排序、音频时序扰动更明显”的方向，但不能单独证明论文中的视觉 transfer 机制已复现。

## 训练轨迹与投影漂移

训练诊断中重复的 global step 400 只保留一条。学生 decision 的 per-dimension variance 从 step 0 的 `0.210280155` 降至 step 400 的 `0.000147812`、step 800 的 `0.000059261`；projected visual target variance 同期从 `0.160833234` 降至 `0.001309989` 和 `0.000505783`。strong teacher projector 相对初始化的漂移为 step 400 `0.133798836`、step 800 `0.050900320`。

在固定的第一个 mixed-label test batch 上，best checkpoint 的 decision/target variance 分别为 `4.74677e-05` / `8.28447e-05`，strong projector 相对漂移 `0.257007078`；last checkpoint 分别为 `8.55843e-06` / `8.14815e-06`，漂移 `0.315639318`。这些证据与“学生表示塌缩并且 target projector 是 moving target”的风险相容，但由于没有恢复历史 optimizer/provenance，不能把它写成唯一根因。

## 当前科学裁决与下一步门槛

本审计把 Visual-only sum 的运行和 artifact 判定为通过，但没有恢复完整的 `Student-only < Visual-only < Full` 关系，也没有证明视觉内容已经成为主要 localization decision 路径。正式 Full 训练继续暂停；本报告不授权下一项训练。

在重新考虑 bounded Full 之前，必须先固定并预注册至少以下差异：`teacher_target_projector_trainable` 是否应冻结、text anchor 是否复用 fusion 的同一 projected query、`pretrained` backbone 语义、论文 additive segment Transformer 与当前 concat MLP 的结构差异、`step400`/early-stopping provenance，以及 U-AP 的聚合定义。任何后续实验都必须保留官方 T=10、单测试视图和当前 canonical full-run guard。

## 证据文件

- 机器可读报告：[visual_sum_posthoc_report.json](./visual_sum_posthoc_report.json)
- 5090 stdout 镜像：[visual_sum_posthoc_stdout.log](./visual_sum_posthoc_stdout.log)
- 只读 runner：[`scripts/diagnose_visual_sum_posthoc.py`](../../../scripts/diagnose_visual_sum_posthoc.py)
- focused tests：[`tests/test_visual_sum_posthoc.py`](../../../tests/test_visual_sum_posthoc.py)

报告 JSON SHA256：`32c2d11e33da2e0c4390cf81dda33e03d398c1d67120d36f223c411c5d11da56`。
