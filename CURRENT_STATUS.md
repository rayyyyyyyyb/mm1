# OV-OrthKD 当前状态与复现接续指南

更新日期：2026-08-25
分支：`repro/r5-final-runtime-protocol-and-readiness`
最终状态：`READY_FOR_CONFERENCE_REPRO`

## 一句话结论

复现前准备已完成：官方数据/教师 checkpoint、T=10 协议、24,800 条 source/WAV/teacher artifact 全量审计、三教师真实 smoke、唯一一次真实一步 preflight 和 clean canonical readiness 全部通过。状态已达到可正式开始会议复现，但正式学生训练、主表和消融均尚未启动，当前停下等待用户指令。

## 已锁定的 temporal 协议

- 唯一运行口径为 `T_task=10, T_max=16, K_student=1, K_teacher=8, V_test=1`；五个量分别表示任务时间轴、模型容量、学生输入帧数、教师重复帧数和测试视图数，禁止互相替代。
- 官方 OV-AVEBench task timeline 固定为 10 个一秒 temporal segments。
- 真实 label、student logits、visual/audio teacher temporal features 和 metric 输入均为 T=10；禁止 10→16 插值、复制、重采样或重新标注。
- `student.max_position_segments=16` 只是 positional capacity，不是任务长度。
- 每个视频的官方视觉观测严格为 10 张 JPG；学生每段固定读取唯一关键帧，训练只做水平翻转和 ColorJitter 空间增强。
- InternVideo2 `num_frames=8` 表示把每个一秒 segment 的同一张官方 keyframe 重复 8 次，不是 8 张独立帧。
- validation/test 固定单次前向：`V_test=1`，无 multi-crop、multi-clip、multi-view 或视图平均。
- canonical 运行中 raw-video diagnostic 明确 `enabled=false, executed=false`；不存在实际 16-fps 解码过程。
- 论文中的 “16 fps / 16 temporal segments / per-16-seg clip” 作为写作与术语混淆处理，不改变官方 T=10 实验协议。

## 已完成并可复核

- 两个官方 archive 和五个教师 checkpoint 均已下载到 5090、锁定 bytes/SHA256，并通过 archive/checkpoint 验证。
- 官方 preprocessed 数据全量布局：24,800 samples、248,000 JPG、24,800 WAV，split 13,182/5,798/5,820，全部 label/frame count 为 10。
- canonical source manifests 已生成并全量审计通过：0 errors、0 warnings、0 duplicate、0 split overlap、0 temporal resampling。
- 24,800 条官方 WAV 已逐文件审计：23,844 条恰为 10 秒、954 条按官方学生路径语义尾部补零到 10 秒、2 条截断到 10 秒；全部 16 kHz，0 errors，且不做时间插值、重采样或末样本复制。学生与 BEATs 教师都在同一个固定 10 秒任务窗口上处理十个一秒段。
- source manifest SHA256：
  - train `296e087bee10c2ef40ac647fa6d19ae355296366f4f281bca3b58dfd1663d9a0`
  - val `deebdc384b6d12d9794b923b4c4387205bc33c819aac06cc92bb1c0febb5fa16`
  - test `d2d7ec2a7b45651fb620d826edcef3d18c8eac861732f12af538bbb4a794a814`
- 真实 train 样本 `EpxQKLhAP0s` 上三教师 repeat-2 smoke 通过：InternVideo2 `[10,512]` + logits `[10]`、BEATs `[10,768]`、CLAP `[1024]`；全部 finite、逐位一致、最大绝对差 0。
- RTX 5090 canonical T=10 student efficiency receipt：29.631 ms/clip、33.748 clips/s。T=16 收据已明确改标为 synthetic positional-capacity analysis，不是论文任务协议。
- raw archive 的 13 个零字节 MP4 和 1,019 个短流仍完整记录，但仅属于 optional diagnostic；canonical JPG/WAV 主线不读取、填充或替换它们。

## 最终封板证据

1. teacher cache 已完成 `24,800/24,800`；main/val/test supervisors 均 attempt 1、exit 0。
2. full artifact audit 扫描 24,800 条 artifact 和 24,800 条 receipt，0 errors、0 warnings；cache tree 为 99,334 files / 1,310,102,478 bytes / `6707900b5d4acb39752baeea11cd1e90d8d3394600b1fa3a6cc3984223860244`。
3. 唯一真实 preflight 已运行恰好一次且通过：1 optimizer step、forward/backward/checkpoint-resume 全通过、无正式指标输出；所有 task 维度均为 T=10。
4. canonical readiness receipt 为 `READY_FOR_CONFERENCE_REPRO`、blockers=[]、git_dirty=false；`configs/ov_orthkd_mm26_repro_ready.yaml` 已生成且只解除 full-run guard。
5. 正式学生训练仍为 0；准备阶段到此停止。

## 等待用户指令后的下一阶段

1. 当前不要再次运行真实 preflight，也不要修改已锁定的 data/teacher/cache 身份。
2. 用户明确下达正式复现指令后，才使用 ready config 启动学生训练。
3. 正式运行继续严格保持 T=10、单测试视图和当前 evaluator mapping，并记录所有 checkpoint、日志和指标收据。

## Web 审阅入口

- 本阶段总报告：[`reports/R5_FINAL_RUNTIME_PROTOCOL_AND_READINESS_REPORT.md`](reports/R5_FINAL_RUNTIME_PROTOCOL_AND_READINESS_REPORT.md)
- R4 历史修正报告：[`reports/R4_T10_TEMPORAL_PROTOCOL_CORRECTION_REPORT.md`](reports/R4_T10_TEMPORAL_PROTOCOL_CORRECTION_REPORT.md)
- source audit：[`reports/mm26_source_manifest_audit.json`](reports/mm26_source_manifest_audit.json)
- official WAV task-window audit：[`reports/data/official_audio_task_window_audit.json`](reports/data/official_audio_task_window_audit.json)
- teacher identity：[`reports/teachers/teacher_identity.json`](reports/teachers/teacher_identity.json)
- repeatability：[`reports/teachers/smoke_repeatability.json`](reports/teachers/smoke_repeatability.json)
- data/download/teacher/archival/preprocessing locks：[`configs/locks`](configs/locks)
- 最终 readiness：[`reports/mm26_conference_readiness.json`](reports/mm26_conference_readiness.json)
- 稿件精确替换文字：[`docs/MM26_TEMPORAL_PROTOCOL_TEXT_CORRECTIONS.md`](docs/MM26_TEMPORAL_PROTOCOL_TEXT_CORRECTIONS.md)
- 最终用户批准证据：[`reports/archival/R5_USER_APPROVED_FINAL_RUNTIME_PROTOCOL.md`](reports/archival/R5_USER_APPROVED_FINAL_RUNTIME_PROTOCOL.md)

## 数据与仓库边界

GitHub 只上传代码、配置、测试和小型审计收据。`data/` 中的正式数据、source/export manifests、下载断点，`weights/`、teacher cache、outputs/logs/runs、Cookie/HAR/token/signed URL 都留在 5090，不上传。

5090 工作路径：`E:/OV-OrthKD-R3/repo`。
