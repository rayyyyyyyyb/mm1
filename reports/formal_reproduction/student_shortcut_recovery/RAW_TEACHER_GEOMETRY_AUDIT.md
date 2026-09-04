# Raw InternVideo2 → Projected Target → Student Decision Geometry Audit

日期：2026-09-04
分支：`repro/student-shortcut-recovery`
审计级别：`noncanonical_raw_teacher_geometry_audit`
最终状态：`PASS`（仅表示只读审计完成；不表示论文机制或正式 Full 已复现）

## 结论

这次只读审计把外部诊断中的“moving-target projector + shared-path co-collapse”假设变成了可核验的证据链：

1. 原始 InternVideo2 strong-teacher cache 在三种状态下完全不变，且在同一 mixed-label 测试子集上保留明显的段内时间变化（within-video temporal std `0.252719637636`，centered temporal variance `0.0977765758764`）。因此不能把当前失败归因于原始 OV-AVEBench 视频缓存已经没有 temporal information。
2. `strong_teacher_proj` 的输出从初始化的 temporal std `0.166309534272` 降到 best 的 `0.004978480397`，再降到 last 的 `0.001356926132`；对应的 student decision temporal std 从 `0.0533049144325` 降到 `0.000276187498020` 和 `2.05679401e-06`。这与“投影目标和学生决策共同收缩”一致。
3. projector 的第一层 effective rank 从初始化 `199.551360` 降至 best `133.964056`、last `101.760511`；最终 Linear 的 bias-to-input-component RMS ratio 从 `1.036714` 升到 `1.871587`、`2.318456`。这支持 bias-dominated moving-target 的高优先级嫌疑，但不单独证明唯一因果。
4. 线性 probe 的标签相关性也随投影状态下降：raw teacher（初始化基准）AP/AUROC 为 `0.666471618 / 0.604069902`；best projected target 为 `0.656138737 / 0.601364496`；last projected target 为 `0.616660079 / 0.551476073`。因此不能把 projector 视为只做无损维度变换。
5. `step400` checkpoint 在部署目录不存在，报告明确标记 `checkpoint_not_available`；没有用 best/last 或训练日志插值、猜测 step400 数值。

这项证据支持：下一步若继续实验，应先预注册并单变量核验 target projector 的冻结/初始化语义，同时保持 Full 暂停。它不授权修改训练代码、启动正式 Full 或声称 Visual-only 机制已经恢复。

## 锁定输入与协议

- 官方时间轴：`task_segments=10`；所有 shape 和指标都落在 10 个一秒任务段上，`temporal_conversion=forbidden`。
- 评估子集：`1,941` 个 `0 < positive labels < 10` 的 mixed-label 视频，`19,410` 个有效任务段。
- checkpoint：best 为 epoch index `7` / global step `3200`；last 为 epoch index `29` / global step `12000`。两者均通过 strict student/loss state loading 和配置哈希校验。
- 原始 cache：三 split 的 `strong_teacher_features.npy` 均为 `[10,512]` float32；锁文件声明 `99,334` 个文件、`1,310,102,478` bytes，cache-root SHA256 为 `6707900b5d4acb39752baeea11cd1e90d8d3394600b1fa3a6cc3984223860244`。
- 审计行为：没有构造 optimizer、没有执行 optimizer step、没有写 checkpoint；报告中的 `formal_full_training_authorized` 与 `next_experiment_authorized` 均为 `false`。

输入文件 SHA256：resolved config `85bc89f1891fc0abc060bdd79cd74a8f9ed13ea28fc55555f15194e5dfe18777`；best checkpoint `a821a1df6ed5ef0f8c824cb15bd25be3394acb29a0594832c9a6037b49dbd293`；last checkpoint `791ac8c9c4d5ad2a86f69c24cd845271be211aa6228733cfb9f48732e716b231`；test prediction archive `be1726c36935c115a1a41fa22868fe0a3fff086246450c2c184b61e45cba2b55`；train manifest `cb30035c533d56d44469d063ba11720ae3660266535ede670db6b6f53bdc7666`。所有 checkpoint 均为 strict load，未通过 state-dict 之外的隐式参数恢复。

## 几何结果

下表的 `temporal std` 是对每个视频有效 temporal rows 的特征维均值再取视频平均；`centered var` 是先减去每个视频的 temporal mean 后的全体有效 row 方差均值。raw teacher 在所有状态相同是预期的，因为它来自只读锁定 cache。

| state | checkpoint step | raw std | projected-target std | student-decision std | raw centered var | projected centered var | decision centered var |
|---|---:|---:|---:|---:|---:|---:|---:|
| initialization | — | 0.252719638 | 0.166309534 | 0.0533049144 | 0.097776576 | 0.0390328161 | 0.00400814863 |
| step400 | unavailable | — | — | — | — | — | — |
| best | 3200 | 0.252719638 | 0.00497848040 | 0.000276187498 | 0.097776576 | 0.0000423105852 | 0.000000411301 |
| last | 12000 | 0.252719638 | 0.00135692613 | 0.00000205679 | 0.097776576 | 0.00000249701 | 0.0000000000107477 |

每个状态的 pairwise temporal-distance Pearson correlation（pair-count weighted）如下：

| state | raw → projected | projected → decision | raw → decision |
|---|---:|---:|---:|
| initialization | 0.973615847 | 0.443214230 | 0.450706427 |
| best | 0.771424485 | 0.113398024 | 0.136380210 |
| last | 0.894432447 | 0.108100021 | 0.114238806 |

这不是标签正负 pairwise concordance；后者的学生 logits 结果已在 [VISUAL_SUM_POSTHOC_ATTRIBUTION.md](VISUAL_SUM_POSTHOC_ATTRIBUTION.md) 中审计。本报告对 raw/projected teacher 使用透明 train-split linear probe 的 AP/AUROC 作为 label-aligned signal 检查，并明确不运行 in-sample student-decision probe。

## Projector spectrum 与 bias 证据

| state | Linear layer | input → output | effective rank | weight RMS | bias L2 |
|---|---|---:|---:|---:|---:|
| initialization | `net.0` | 512 → 256 | 199.551360 | 0.0255323053 | 0.420667897 |
| initialization | `net.3` | 256 → 256 | 154.728801 | 0.0360696665 | 0.603029495 |
| best | `net.0` | 512 → 256 | 133.964056 | 0.0226588428 | 0.540392970 |
| best | `net.3` | 256 → 256 | 150.469523 | 0.0333951312 | 0.603678000 |
| last | `net.0` | 512 → 256 | 101.760511 | 0.0205368772 | 0.575934536 |
| last | `net.3` | 256 → 256 | 150.038022 | 0.0330811915 | 0.604086434 |

最终 Linear 的 `bias-to-weight-RMS` ratio 为 initialization `1.04490413`、best `1.12980167`、last `1.14129511`；按实际输入 component RMS 归一化的 bias ratio 为 `1.03671380`、`1.87158730`、`2.31845551`。

## Label-aligned linear probes

Probe 严格使用 train manifest 的 131,820 个官方任务段拟合，mixed-label 子集的 19,410 个任务段评估；标准化、`SGDClassifier(log_loss, l2, alpha=1e-4, max_iter=2000, average=True, random_state=42)` 和 global micro aggregation 均由既有透明 probe helper receipt 记录。

| feature source | state | eval AP | eval AUROC | probe iterations |
|---|---|---:|---:|---:|
| raw teacher `[512]` | initialization baseline | 0.666471618 | 0.604069902 | 165 |
| projected target `[256]` | best | 0.656138737 | 0.601364496 | 125 |
| projected target `[256]` | last | 0.616660079 | 0.551476073 | 153 |

Student decision 的 train-split probe 本次标记为 `not_run`，原因是禁止以同一 checkpoint 的 in-sample/full-train forward 伪造独立证据；其段内几何、checkpoint state hash 和已有 test-logit attribution 已分别报告。

## Provenance receipts

- Runner：`scripts/diagnose_raw_teacher_geometry.py`
- Tests：`tests/test_raw_teacher_geometry.py`
- Machine-readable report：[raw_teacher_geometry_report.json](raw_teacher_geometry_report.json)
- 被拒绝的首轮报告（记录 best/last probe 复用 bug，不用于科学结论）：[raw_teacher_geometry_report_rejected_best_probe_reuse.json](raw_teacher_geometry_report_rejected_best_probe_reuse.json)
- stdout receipt：[raw_teacher_geometry_stdout.log](raw_teacher_geometry_stdout.log)
- stderr receipt：[raw_teacher_geometry_stderr.log](raw_teacher_geometry_stderr.log)（0 bytes）
- 最终 report SHA256：`e800999d77864b1d27800ce39650351eebc5d7471f41d80809551213682dbd26`
- runner SHA256：`c05e2333ef8ad7d3ad6a530c1501c13e14de2bfa2a4709a988f12d5c7f49dd03`
- 5090 任务：`OVOrthKD_RawTeacherGeometry_Seed42`，Task Scheduler `LastTaskResult=0`；完成后 GPU 空闲。

## Decision boundary

本审计只确认了“raw teacher 仍有可读 temporal/label signal，但 trainable projector 与 student decision 在 best/last 进一步收缩”的事实。它没有恢复论文声称的视觉决策机制，也没有解决 target projector 的历史初始化/冻结语义、shared query anchor、pretrained backbone、融合结构和原始 schedule 等 provenance 缺口。因此：

- 不启动正式 Full；
- 不把 last/best probe 或当前 Visual-only 数值写成论文机制复现；
- 下一步优先级是基于本报告证据预注册 projector freeze/initialization 的单变量 bounded control，前提是另行审核其历史依据；
- 当前最终科学状态仍为 `BLOCKED_BEFORE_R2`。
