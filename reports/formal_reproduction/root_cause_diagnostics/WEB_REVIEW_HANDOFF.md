# 网页端独立审查入口：控制实验、融合实现与当前根因证据

日期：2026-08-27

分支：`repro/root-cause-diagnostics`

## 先读结论

当前 Full、Student-only、Visual-only 三项同管线运行均已完成。它们不是“数值基本正常、只差一点”：当前 Full 没有复现论文主结果，Visual-only 也显著低于论文对照；Student-only 反而略高于当前 Full。三项运行在阈值 0.5 下得到完全相同的官方 segment F1，且预测几乎全为正类。

当前证据把问题定位到重建实现中的共享学生/优化路径，尤其是学习式模态 gate 的早期饱和，以及可训练 teacher-target projector 与学生表征共同进入低方差解。但这仍是当前重建代码的因果诊断，不是对未公开历史源码的断言。

## 用户提出的融合问题：精确回答

“源码没有分别对视频和音频计算融合参数”这一说法不准确。当前源码确实为每个任务时间段输出两个 gate logits，经 softmax 得到独立的视觉和音频权重，再分别乘到两个模态 token：

- `src/models/ov_orthkd.py:107-111`：`modality_gate` 最终输出 2 维；
- `src/models/ov_orthkd.py:179-186`：softmax 得到 `gate_weights`，分别构造 `weighted_visual` 和 `weighted_audio`；
- `src/models/ov_orthkd.py:218`：权重被保留在 forward 输出，诊断器据此记录饱和轨迹。

真正的论文—源码差异发生在“加权以后”：

| 项目 | 论文方法页公式 | 当前源码 |
|---|---|---|
| gate 输入 | 投影后的视觉、音频、查询 | 同三项，外加 `frame_valid`、`audio_valid` 两个标志 |
| gate 输出 | 每段独立的视觉/音频两权重 | 每段独立的视觉/音频两权重 |
| 融合 | `alpha_v * v + alpha_a * a + q` | `concat(alpha_v * v, alpha_a * a, q)` |
| Transformer 前处理 | 上述相加结果直接送入 Transformer layer | 拼接后再经过可学习 `token_fusion`（LayerNorm + Linear + GELU + Dropout），加位置编码，再送入 temporal Transformer |

对应源码为 `src/models/ov_orthkd.py:112-117` 与 `src/models/ov_orthkd.py:187-193`。因此网页端需要判断的不是“有没有两权重”，而是：当前 `concat + token_fusion` 是否有任何历史代码或作者证据支持；若没有，它只能算重建选择，不能被当成论文加法融合的精确实现。

## 三项正式/控制运行结果

| 变体 | 论文 AP | 当前 AP | 论文 AUROC | 当前 AUROC | 论文 F1 | 当前 F1@0.5 |
|---|---:|---:|---:|---:|---:|---:|
| Student-only | 0.714 | 0.748745 | 0.612 | 0.636135 | 0.523 | 0.540393 |
| Visual-only | 0.778 | 0.725309 | 0.701 | 0.617160 | 0.568 | 0.540393 |
| Full | 0.816 | 0.741946 | 0.750 | 0.633875 | 0.596 | 0.540393 |

Student-only 在 epoch 1 / step 400 最佳；Visual-only 在 epoch 5 / step 2,000 最佳；两者均完整运行 30 epochs / 12,000 optimizer steps，worker exit 0。Full 的完整证据在相邻 `canonical_seed42/` 目录。

## 可复核的退化轨迹

Student-only 前三个 epoch 首批次：

- 样本内 temporal logit std：`0.121423 -> 0.010901 -> 0.002377`；
- gate saturation rate：`0 -> 0.525 -> 1.0`；
- epoch 3 visual gate mean 约 `6.84e-11`，visual encoder gradient 为 0。

Visual-only 前三个 epoch 首批次：

- visual gate mean：`0.477567 -> 0.091324 -> 0.999887`；
- gate saturation rate：`0 -> 0.75 -> 1.0`；
- 样本内 temporal logit std：`0.121423 -> 0.093889 -> 0.004494`；
- epoch 3 visual/audio encoder grad 约为 `8.29e-6 / 2.81e-11`。

Visual-only 同期：

- strong feature loss：epoch 1 `0.061268`，epoch 2 `0.008183`，epoch 3 `0.002404`，epoch 30 `0.0000324`；
- student decision variance：`0.208858 -> 0.003376 -> 0.000375`；
- projected strong target variance：`0.160833 -> 0.005860 -> 0.001864`；
- strong/text teacher projector relative drift 到 epoch 3 已为 `0.1315 / 0.1465`。

优化器在 `scripts/train_ov_orthkd.py:1352-1357` 同时接收 `student.parameters()` 和 `loss_module.parameters()`；三个 teacher projector 定义在 `src/losses/ov_orthkd_loss.py:87-89`，所以这些目标投影层确实参与训练。

## 审查材料顺序

1. 本文件；
2. `02_CONTROL_RESULTS_AND_FUSION_AUDIT.md`；
3. `CONTROL_COMPARISON_STATUS.md`；
4. `control_runs/student_only/final_metrics.json` 与 `control_runs/visual_only/final_metrics.json`；
5. 两个 `history.jsonl`；
6. 两个 `training_diagnostics.jsonl`；
7. 两个 `config_resolved.yaml`；
8. `student_only_prediction_audit.json`、`visual_only_prediction_audit.json`；
9. `src/models/ov_orthkd.py`、`src/losses/ov_orthkd_loss.py`、`scripts/train_ov_orthkd.py`；
10. `tests/test_training_diagnostics.py` 及诊断配置。

## 请网页端重点作出的判断

1. `concat + token_fusion` 是否与论文的加法融合存在不可忽略的结构差异；
2. 在没有历史源码证据时，下一次单变量因果实验应先测试“论文加法融合”，还是先测试“固定等权 gate”；
3. teacher-target projector 是否应冻结，且必须与 gate/fusion 变更分开做单变量实验；
4. 当前三项结果是否足以排除 evaluator、T=10 协议和教师资产作为首要根因；
5. Zhou 官方 output/checkpoint 缺失时，还能进行哪些不冒充历史事实的验证。

不要把任何候选修改直接称为“会议论文正式实现”。下一次运行应一次只改一个变量，保持官方 `T_task=10`、数据/教师/evaluator locks、seed、优化器和训练步数不变。

## 未上传的大资产边界

GitHub 不包含数据集、teacher cache、teacher/student checkpoints、预测 NPZ、PR-curve NPZ、ZIP、bundle 或 2.2 MB 的 tqdm stderr。仓库包含全部小型结构化指标、30-epoch history、前三 epoch 诊断轨迹、resolved config、环境/锁定哈希和用于生成这些证据的完整代码。大资产的精确 SHA256 与尺寸写在运行报告和 receipts 中。
