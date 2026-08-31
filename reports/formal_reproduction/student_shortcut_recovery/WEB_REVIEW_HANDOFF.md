# Student shortcut recovery：网页审查交接

日期：2026-08-31

当前状态：**S3 未通过恢复门槛；正式 Full 复现继续暂停。**

这份入口供独立审阅者直接从 GitHub 网页核对。A0 是无训练的捷径/模态诊断；S3 是相对三轮 S0 只把 `student.pretrained` 从 `false` 改为 `true` 的单变量诊断。两者都严格保持官方 `T_task=10`；没有任何 10→16 标签、logit 或指标转换。`T_max=16` 仍仅为位置编码容量。

## 先看结论

S3 的 best-checkpoint test AP/AUROC/F1@0.5 是 `0.745689/0.652332/0.540393`，数值没有离开常见范围，但不能据此认为模型恢复：

- 0.5 阈值下 58,200 个 test segments 全部预测为正；
- 相对 S0，AP 下降 `0.003056`，AUROC 上升 `0.016197`，F1 完全不变；
- 100 次样本内时间打乱后 AP 只下降 `0.003657`；
- 视觉输入置零后 AP 几乎不变，音频置零只下降 `0.009385`；
- 视觉和音频同时置零后 AP 仍为 `0.736156`，保留原 AP 的 98.72%；
- mean-centered AP 和 per-query macro AP 均比 S0 更差。

预训练确实使 best checkpoint 的样本内 logit 标准差变为 S0 的 22.23 倍，但这种变化主要来自音频。视觉 projected-token 的 test temporal std 只有 `3.09e-5`，视觉置零不产生代价；音频置零后 logit temporal std 降到 `1.60e-6`。训练第二轮后，首 batch logit temporal std 又从 `0.186587` 降到 `0.002026`，视觉 gate 饱和且 visual gradient 极小。

因此当前根因不是官方 T=10 协议、label-logit 对齐或 evaluator；现有证据指向训练早期重新形成的、以音频和 query/sample/position offset 为主的学生捷径，同时视觉路径基本失效。S3 不能作为修改 canonical `pretrained=false` 的依据。

## 精确运行与审计身份

- A0 scientific runtime：`f739399463c082cd670dff56e43c710d4fa6f283`；5090 全量测试 `457 passed`。
- S3 scientific runtime：`a0aa4d7ad4b98455e26a2fe6ff2537a321293233`；5090 全量测试 `458 passed`。
- S3 exposure：seed 42，3 epochs × 400 batches，global step 1200。
- S3 training artifact audit：PASS，SHA256 `5058f78a8a9dfef354158d956205987550e0a745b3fe3f8f3cb79d8de7edbf71`。
- S3 posthoc artifact audit：PASS，SHA256 `6dc432dfccf142ed80902328755402cd140170894be3a44c7130b8b93b69ee44`。
- Official timm cache receipt：PASS，SHA256 `edecae3ae9ba5fbc7102883d1c1d667df71810facb2731d2ec34503a81bca255`。
- 两项预训练 backbone 均证明 `pretrained=True` 的实际 state hash 不同于同 seed 随机构造结果；没有下载失败后的随机回退。
- validation/test prediction 分别含 57,980/58,200 个有序 segment；每个样本严格为索引 `0..9`。
- training AP、保存 NPZ AP 与 strict checkpoint rerun AP 在 `1e-12` 内一致。

## 建议阅读顺序

1. [S3 完整结果和恢复门槛](S3_RESULTS.md)
2. [A0 四组捷径与模态基线](A0_RESULTS.md)
3. [实现、运行器和独立审计说明](IMPLEMENTATION_AUDIT.md)
4. [S3 training audit](evidence/s3/s3_training_artifact_audit.json)
5. [S3 prediction-shortcut JSON](evidence/s3/posthoc/prediction_shortcut.json)
6. [S3 content-ablation/path-scale JSON](evidence/s3/posthoc/checkpoint_modality.json)
7. [S3 posthoc audit](evidence/s3/posthoc/s3_posthoc_artifact_audit.json)
8. [S3 resolved config](evidence/s3/resolved_config.yaml) 与 [三轮 history](evidence/s3/history.jsonl)
9. [本次小型证据清单](evidence/README.md)
10. [执行脚本清单](runtime/README.md)

## 希望独立审阅者回答的问题

1. 在不改变官方 T=10、teacher cache 和 evaluator 的前提下，下一项单变量 S4（仅关闭现有训练图像增强、保持 `pretrained=false`）是否仍是最有信息量的实验？
2. 当前每个 temporal segment 只有一张官方关键帧，而训练 transform 对十张图分别调用；应先比较完全关闭增强，还是直接测试 clip-consistent augmentation？
3. visual projected-token temporal std 近零究竟更符合逐段增强/编码器学习失败、gate 抑制，还是当前视觉输入归一化/冻结策略的问题？请以仓库源码为依据，不推测历史实现。
4. best checkpoint 固定在 epoch 1、后续迅速塌缩时，应优先验证训练 exposure/scheduler，还是先解决内容依赖性？

## 边界

本阶段没有启动 S4、S5、S6、Visual-only、正式 Full，也没有修改 canonical 配置。GitHub 不上传数据集、teacher/student checkpoints、timm cache、prediction NPZ、bundle 或完整日志；对应 bytes、SHA256、shape、数量和审计结论由这里的小型 receipts 锁定。大资产仍保存在 5090。
