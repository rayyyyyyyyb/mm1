# 当前正式复现状态

- 更新时间：2026-08-26
- 阶段：canonical OV-OrthKD seed42 已完成并完成最终机械验收
- 唯一起点：`31b86c0d60c4bf2ed028edf1385ed5d2c9e89153`
- 正式命令：`python scripts/train_ov_orthkd.py --config configs/ov_orthkd_mm26_repro_ready.yaml --output-dir outputs/formal/mm26_canonical_seed42`
- worker：`completed`，exit code 0
- epochs：30/30
- global optimizer steps：12,000
- best epoch：1（zero-based checkpoint epoch 0）
- best validation AP：0.7302036939345478
- formal wall time：4:19:51.822
- epoch 累计训练/验证时间：14,424.447 秒
- peak allocated GPU memory：6,566.866 MiB
- final LR：0.0
- Git：exact HEAD，status 0 行
- claim：`paper_specified_reconstruction`
- incompatible marker：不存在
- cache：99,334 files / 1,310,102,478 bytes / SHA256 `6707900b5d4acb39752baeea11cd1e90d8d3394600b1fa3a6cc3984223860244`
- evaluator：source exists、matches lock，SHA256 `013949f6371dc11a93f4e5b1df448601b98cf5590e7651d103600f981a4ded19`
- protocol：`T_task=10, T_max=16, K_student=1, K_teacher=8, V_test=1`
- prediction audit：validation 5,798×10，test 5,820×10；所有样本 segment index 精确为 0…9
- full artifact audit：`PASS` / exit 0 / errors 0
- final artifact audit SHA256：`8d6880516bfeef9fcd489f90b3d23ec875b253df2af076866b73fee7b3d11633`
- 消融：0，保持停止

## 正式 test 结果

- Total AP：0.7419461390325246
- Total AUROC：0.6338748098301057
- Total OV-AVEL segment F1@0.5：0.5403934127616343
- Total accuracy（冻结 validation 阈值）：0.6210996563573883
- Unseen AP：0.7223984508490624
- Unseen accuracy：0.6247834456207892
- Unseen segment F1@0.5：0.5405437869811062
- Seen AP：0.7892745152007632
- Seen accuracy：0.6118990384615385
- Seen segment F1@0.5：0.5400178386894439
- validation-selected threshold：0.6659861520031973
- calibrated binary micro F1：0.7635884131306417

## 判定

- `CANONICAL_RUN_COMPLETED_AND_ARTIFACT_AUDIT_PASSED`
- `PAPER_NUMERICAL_REPRODUCTION_NOT_ACHIEVED`
- calibrated segment F1 存在报告缺口：锁定映射要求 `ovavel_segment_f1_at_validation_selected_threshold`，但正式 evaluator 只输出 calibrated binary micro F1；两者不得互相替代。
- 不启动消融，等待对 canonical 数值差距和 calibrated segment F1 输出缺口的复核指令。
