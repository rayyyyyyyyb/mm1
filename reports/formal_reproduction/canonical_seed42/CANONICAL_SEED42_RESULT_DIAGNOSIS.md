# Canonical seed42 数值诊断与基线对比

## 结论

本次结果不是“数值正常、只与论文略有随机差异”。运行本身完整、所有数值 finite、artifact audit 通过，而且模型学到了一定排序信号；但作为论文完整 OV-OrthKD 的正式复现，核心指标已经明显偏离预期范围，不能归因于普通 seed 或数值波动。

最简洁的判定是：

- 不是随机输出或程序崩溃；
- 不是成功复现论文 Full；
- 当前性能大致落在 Student-only 与官方 Zhou fine-tuning baseline 附近；
- 明显低于更简单的 Visual feature only，也没有出现论文所声称的完整蒸馏增益；
- `binary_micro_f1` 的高值主要来自几乎全正预测，不能作为成功证据。

## 与论文 Table 4 的直接对比

| 参照 | AP | AUROC | F1@0.5 | 当前相对 AP | 当前相对 AUROC | 当前相对 F1 |
|---|---:|---:|---:|---:|---:|---:|
| ImageBind zero-shot | 0.592 | 0.534 | 0.467 | +0.149946 | +0.099875 | +0.073393 |
| Video-LLaMA2 | 0.489 | 0.455 | 0.391 | +0.252946 | +0.178875 | +0.149393 |
| Zhou et al. official fine-tuning | 0.745 | 0.650 | 0.569 | -0.003054 | -0.016125 | -0.028607 |
| Student-only | 0.714 | 0.612 | 0.523 | +0.027946 | +0.021875 | +0.017393 |
| Visual feature only | 0.778 | 0.701 | 0.568 | -0.036054 | -0.067125 | -0.027607 |
| OV-OrthKD Full | 0.816 | 0.750 | 0.596 | -0.074054 | -0.116125 | -0.055607 |
| **本次 canonical seed42** | **0.741946** | **0.633875** | **0.540393** | — | — | — |

因此，当前 AP 与 Zhou 官方 fine-tuning baseline 很接近，但 AUROC 和核心 segment F1 已低于它；相对 Student-only 有小幅提升，却被 Visual feature only 明显超过。完整 OV-OrthKD 本应在 Visual feature only 之上再增加 0.038 AP，而当前反而低 0.036 AP。

## 为什么不是正常随机波动

论文 Fig. 4 对每个 orthogonality weight 使用五个 seed，并报告约 `±0.003 AP` 的标准差。当前 Full AP 与论文相差 `0.074054`，约为该波动尺度的 24.7 倍。该比较不是严格的同分布显著性检验，但足以排除“仅仅换了一个 seed 或 GPU 浮点差异”的解释。

训练曲线也不是围绕论文值正常收敛：

- 最佳 validation AP `0.730204` 出现在第 1 个 epoch（checkpoint 内 zero-based epoch 0）；
- 后续 29 个 epoch 从未刷新最佳值，后续最高 AP 仅 `0.720020`；
- 最终 validation AP 为 `0.718524`；
- validation 在 30 个 epoch 中有 29 个 epoch 的预测正类率精确为 `1.0`，另一个 epoch 为 `0.999828`。

这说明当前 Full recipe 没有呈现论文中完整蒸馏机制应有的优化收益。

## binary F1 的表面高分

test 标签正类率为 `0.6154639175`。如果把所有 segment 都预测为正类，则：

- accuracy = `0.6154639175`；
- binary micro F1 = `2p/(1+p) = 0.7619655392`。

本次实际 `binary_micro_f1_at_0_5` 恰好为 `0.7619655392`，与全正预测基线逐位一致。validation 历史也记录了近乎或完全 `predicted_positive_rate=1.0`。即使使用 validation 选出的阈值 `0.665986`，test 仍有 `98.7251%` segment 被预测为正类。

因此 `0.762–0.764` 的 binary micro F1 主要反映数据中正类占比，而不是可靠的时间定位能力。真正协议对齐的 OV-AVEL segment F1@0.5 只有 `0.540393`，低于 Zhou baseline 的 `0.569`、Visual feature only 的 `0.568` 和论文 Full 的 `0.596`。

## Seen / Unseen 异常模式

当前 unseen AP 为 `0.722398`，高于论文 Full 报告的 `0.584`，但 unseen accuracy/F1 分别只有 `0.624783/0.540544`，低于论文的 `0.672/0.584`；seen accuracy/F1 也分别低 `0.153101/0.084982`。

这种“unseen AP 异常偏高，但阈值指标全面偏低”的组合不能直接解释为 unseen 泛化更强。它更像是排序分数、阈值校准、split/AP 汇总语义或标签/预测分布之间存在尚未定位的差异，必须继续审计，不能挑选 unseen AP 单项宣称优于论文。

## 当前可下的科学结论

1. 数据、T=10 协议、运行时长和产物完整性已经通过审计。
2. 模型不是完全没有信号：AP/AUROC 高于 Student-only 论文行和两个较弱外部 baseline。
3. 但完整 OV-OrthKD 的主要数值没有复现；表现低于 Visual feature only，核心机制增益缺失。
4. 阈值输出存在接近全正预测的退化，当前 binary micro F1 不能用于证明成功。
5. 论文 calibrated segment F1 仍未由生产 evaluator 输出，因此不能把现有 calibrated binary F1 与论文 `0.781` 对比。
6. 当前状态应保持 `PAPER_NUMERICAL_REPRODUCTION_NOT_ACHIEVED`，不能进入大规模消融或把本次结果写成正常 seed 波动。

下一轮应先完成 evaluator/AP 汇总语义、logit 分布与标签对齐、以及同一实现下 Student-only/Visual-feature-only 控制实验的诊断设计；在根因明确前不调整超参数碰运气。
