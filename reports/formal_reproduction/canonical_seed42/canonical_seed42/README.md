# Canonical OV-OrthKD seed42 小型证据

本目录只保存正式复现的可审计小型证据、配置和指标。大型资产继续保留在 RTX 5090：

- 不包含 `best.pt` / `last.pt`；
- 不包含 validation/test prediction NPZ；
- 不包含数据集、教师 checkpoint 或教师 cache；
- 不包含完整训练 stderr 进度流。

正式远端 output：

`E:\OV-OrthKD-R3\formal-canonical-31b86c0\outputs\formal\mm26_canonical_seed42`

唯一 Git commit：

`31b86c0d60c4bf2ed028edf1385ed5d2c9e89153`

`final_artifact_audit.json` 是独立审计器对 history、checkpoint 元数据、全部预测 shape/T=10、cache/evaluator/Git/protocol 和所有文件 SHA 的机械验收结果。
