# 网页端审查入口：固定门控与论文式加性融合的因果实验

日期：2026-08-27

分支：`repro/causal-fusion-diagnostics`

运行代码：`d5d13c2a9c913d35addbc3b496d76988008bd613`（exact clean）

阶段状态：`DIAGNOSTIC_COMPLETE_STUDENT_COLLAPSE_UNRESOLVED`

## 先读结论

网页端提出的两项首要 Student-only 因果实验已经严格完成，但两项单变量修改都没有恢复健康的逐段时间定位：

- 固定视觉/音频 gate 为 0.5/0.5，确实消除了 gate 饱和并让两个 encoder 都保留非零梯度；然而最终预测几乎完全常数化，AP/AUROC 反而明显下降。因此学习式 gate 饱和不是唯一根因。
- 仅将 `concat + token_fusion` 换成论文公式的加性融合，确实绕过了 `token_fusion`，但 learned gate 到第 3 epoch 仍完全饱和，最终平均样本内 logit 标准差甚至降到 `1.53e-6`。因此 concat-MLP 是真实的论文—实现差异，却不是这次时间塌缩的单独充分原因。

S0、S1、S2 都在阈值 0.5 下给出完全相同的官方 segment F1 `0.540393` 和 event F1 `0.577434`。目前不能开始新的正式 Full 复现；下一步仍应保持 Student-only，一次只测试预训练、augmentation 和 exposure/step400 等候选因素。

## 三组严格单变量结果

三组均为 seed 42、官方 `T_task=10`、3 epochs、每 epoch 400 batches、1,200 optimizer steps、Student-only BCE。scheduler 保留原 Student-only 的 `CosineAnnealingLR(T_max=30)`，没有为了 3 epoch 诊断改为 `T_max=3`。

| 运行 | 唯一科学变量 | 最佳 val AP | test AP | test AUROC | F1@0.5 | 校准阈值判正率 | test 平均样本内 logit std |
|---|---|---:|---:|---:|---:|---:|---:|
| S0 | learned gate + concat-MLP（当前控制） | 0.733159 | 0.748745 | 0.636135 | 0.540393 | 0.987371 | 3.236e-3 |
| S1 | 仅 gate 改为固定 0.5/0.5 | 0.688405 | 0.699079 | 0.570246 | 0.540393 | 0.999966 | 1.318e-5 |
| S2 | 仅 fusion 改为 paper additive | 0.722456 | 0.733884 | 0.613523 | 0.540393 | 0.971478 | 1.527e-6 |

相对 S0：

- S1 test AP `-0.049666`、AUROC `-0.065889`；
- S2 test AP `-0.014860`、AUROC `-0.022612`。

这些 AP 仍是全局 segment micro 排序，不应被解释成健康的逐视频时间定位。prediction audit 显示 S2 的全局 logit std 为 `0.014025`，但平均样本内 std 只有 `1.527e-6`，说明剩余排序主要来自样本/query 之间的整体 offset，而不是同一视频 10 个时间段之间的差异。

## 退化轨迹给出的因果信息

最后一个 observation-only 诊断点（epoch 3 的首批次）：

| 运行 | visual/audio gate | 饱和率 | temporal std | 正/负 logit mean | visual/audio encoder grad |
|---|---|---:|---:|---|---|
| S0 | `~0 / 1` | 1.0 | 0.002377 | 0.700957 / 0.701953 | 0 / 0.002375 |
| S1 | 0.5 / 0.5 | 0.0 | 0.001482 | 0.559238 / 0.559277 | 4.23e-6 / 2.89e-5 |
| S2 | 0.999150 / 0.000850 | 1.0 | 0.005737 | 1.262148 / 1.259375 | 4.00e-5 / 2.42e-6 |

S1 证明“极端 gate”可以被去掉，但 temporal collapse 仍存在。S2 则把塌缩方向从 S0 的音频侧翻到视觉侧，同时 `token_fusion_grad` 在三次诊断中均精确为 0，证明 paper-additive 分支实际生效；它没有暗中继续走 concat MLP。

## 关于“源码是否没分别计算视频/音频融合参数”

这个说法仍不准确。旧重建源码已经为每个任务时间段计算两个 gate logits，softmax 后得到 `alpha_v`、`alpha_a`，再分别乘到视觉和音频 token。原先真正的差异发生在加权之后：

- 旧控制：`concat(alpha_v*v, alpha_a*a, q) -> token_fusion MLP -> Transformer`；
- 论文式 S2：`alpha_v*v + alpha_a*a + q -> Transformer`。

本分支让两种路径成为显式、可校验且未知值 fail-fast 的 `fusion_mode`；`gate_mode` 同样显式。见 [src/models/ov_orthkd.py](../../../src/models/ov_orthkd.py)、[tests/test_paper_faithfulness.py](../../../tests/test_paper_faithfulness.py) 和三份 [causal configs](../../../configs/diagnostics/causal)。

## 已修复并独立验证的代码面

- `fusion_mode` 和 `gate_mode` 真正进入 student constructor，未知值直接失败；
- paper additive 与 concat MLP 都有逐式单测；
- `visual_l2_reduction` 真正控制 feature 维度 mean/sum；
- teacher-target projector trainability 有显式开关，冻结参数不会进入 optimizer；
- query anchor 支持独立 loss projection 与共享 fusion projection；
- resolved config、独立 JSON、fingerprint 和 checkpoint 都记录实际构建行为；
- S0/S1/S2 同 seed 的完整 state dict 初始化逐 tensor 相同；固定 gate 保留兼容 gate 模块但 forward 不给它梯度，加性融合保留兼容 `token_fusion` 模块但 forward 不给它梯度；
- 非 canonical 诊断仍机械强制 metric 输入 `T=10`。

实现代码主要位于 [src/models/ov_orthkd.py](../../../src/models/ov_orthkd.py)、[src/losses/ov_orthkd_loss.py](../../../src/losses/ov_orthkd_loss.py)、[scripts/train_ov_orthkd.py](../../../scripts/train_ov_orthkd.py)。设计与执行计划位于 [design](../../../docs/superpowers/specs/2026-08-27-causal-fusion-diagnostics-design.md) 和 [plan](../../../docs/superpowers/plans/2026-08-27-causal-fusion-diagnostics.md)。

## 验证证据与已公开失败

- exact clean `d5d13c2` 的 fresh compileall exit 0；全量 pytest `428 passed in 323.47s`、exit 0；
- S0 `training_diagnostics.jsonl` 与旧 Student-only SHA256 精确相同：`254c0a0f...d804`；S0 `final_metrics.json` 同样精确相同：`c223ed77...7488`；
- worker 最终 `completed`、exit 0、顺序 S0→S1→S2、相关进程 0；
- 三组 prediction audit 均 exit 0/PASS，validation/test 分别为 `5798×10`/`5820×10`；
- [causal_artifact_audit.json](causal_artifact_audit.json) 为 PASS，SHA256 `1de5f813dc848eb8f568d88ee54bbbeea98ff0f0cda8882ed8177b1de717edc8`；锁定配置差异、行为收据、参数数、有限数值、T=10 顺序、teacher-cache root 与每个远端产物的 bytes/SHA256；
- teacher-cache root：99,334 files、1,310,102,478 bytes、SHA256 `6707900b5d4acb39752baeea11cd1e90d8d3394600b1fa3a6cc3984223860244`。

没有隐藏失败：最初把诊断 scheduler `T_max` 错改为 3、fixed gate 少实例化模块、additive fusion 少实例化模块的三批无效运行均在产生最终因果证据前停止、归档并通过 TDD 修复。首次全量 pytest 因验证脚本漏加 MinGit PATH 得到 392 pass/36 fail，补回锁定 MinGit 后同一代码得到 428 pass。首次 prediction wrapper 的三个子任务实际生成相同 PASS JSON，但 PowerShell `Start-Process` 返回空 ExitCode；保留哈希后删除这些小型无收据副本，改为顺序直调，三组明确 exit 0 且输出哈希逐字节相同。

提交前 fresh 本机 compileall exit 0，但本机 Anaconda 在 pytest collection 导入 torch/NumPy 时于 `blas_fpe_check` fatal abort、exit 3，未执行测试断言；因此不把本机结果声称为通过。最终 evidence commit 仍须在5090锁定 venv 的新 clean worktree 上重跑全量测试后才可发布。

## 下一步建议与请网页端判断的问题

依据这批新证据，优先级应更新为：

1. S3：相对 S0 只改 `pretrained=true`；
2. S4：相对 S0 只关闭 augmentation；
3. S5：只改为 clip-consistent augmentation；
4. S6：一次只改变 exposure/batch/step400 解释；
5. Student-only 恢复健康时间对比后，才做 Visual-only 的 frozen-projector、共享 query anchor 与 L2 reduction 单变量实验。

本轮 S0/S1/S2 的所有 KD 权重都为 0，teacher projector 梯度与漂移均为 0；所以此时冻结 projector 不可能解释或修复 Student-only collapse。请网页端重点判断：下一组应先做 S3 还是 S4，以及是否应在这些候选前增加一个仅移除/弱化重复 query shortcut 的单变量控制。不得把任何候选结果追认为未公开的会议历史配置。

## 证据阅读顺序

1. 本文件；
2. [worker_state.json](worker_state.json)、[prediction_audit_receipt.json](prediction_audit_receipt.json)、[causal_artifact_audit.json](causal_artifact_audit.json)；
3. `control_runs/s0_learned_concat`、`s1_fixed_concat`、`s2_learned_additive` 内各自的 `final_metrics.json`、`prediction_audit.json`、`history.jsonl`、`training_diagnostics.jsonl`；
4. 每组 `implementation_behavior.json` 与 `resolved_config.yaml`；
5. 源码、配置和测试。

Git 不包含数据集、teacher cache、student/teacher checkpoint、prediction NPZ、PR-curve NPZ、ZIP、bundle 或 tqdm 进度日志。大资产的精确 bytes/SHA256 保留在 artifact audit；这里只提交网页审查所需的小型结构化证据。
