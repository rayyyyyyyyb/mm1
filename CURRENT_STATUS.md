# OV-OrthKD 当前状态与复现接续指南

更新日期：2026-08-24
分支：`repro/r4-keyframe-readiness-and-experiment-prep`
最终状态：`BLOCKED_BEFORE_CONFERENCE_REPRO`

## 一句话结论

官方数据、教师 checkpoint、T=10 协议修正、24,800 条 source manifest 全量审计和三教师真实 repeat-2 smoke 已通过。当前不再等待作者解释 raw MP4：canonical 主线使用官方每秒关键帧与 WAV；距离正式会议复现还差全量教师 cache、full artifact audit、唯一一次真实一步 preflight 和人工 readiness review。

## 已锁定的 temporal 协议

- 官方 OV-AVEBench task timeline 固定为 10 个一秒 temporal segments。
- 真实 label、student logits、visual/audio teacher temporal features 和 metric 输入均为 T=10；禁止 10→16 插值、复制、重采样或重新标注。
- `student.max_position_segments=16` 只是 positional capacity，不是任务长度。
- 历史 InternVideo2 wrapper 和配置证明 `num_frames=8`。canonical 输入以每个一秒 segment 的单张官方 keyframe 重复到 8 帧；没有代码证据支持“每秒固定解码 16 帧”。
- `temporal_sampling_fps=16` 只保留在默认关闭的 raw-video diagnostic 中。
- 论文中的 “16 fps / 16 temporal segments / per-16-seg clip” 作为写作与术语混淆处理，不改变官方 T=10 实验协议。

## 已完成并可复核

- 两个官方 archive 和五个教师 checkpoint 均已下载到 5090、锁定 bytes/SHA256，并通过 archive/checkpoint 验证。
- 官方 preprocessed 数据全量布局：24,800 samples、248,000 JPG、24,800 WAV，split 13,182/5,798/5,820，全部 label/frame count 为 10。
- canonical source manifests 已生成并全量审计通过：0 errors、0 warnings、0 duplicate、0 split overlap、0 temporal resampling。
- source manifest SHA256：
  - train `296e087bee10c2ef40ac647fa6d19ae355296366f4f281bca3b58dfd1663d9a0`
  - val `deebdc384b6d12d9794b923b4c4387205bc33c819aac06cc92bb1c0febb5fa16`
  - test `d2d7ec2a7b45651fb620d826edcef3d18c8eac861732f12af538bbb4a794a814`
- 真实 train 样本 `EpxQKLhAP0s` 上三教师 repeat-2 smoke 通过：InternVideo2 `[10,512]` + logits `[10]`、BEATs `[10,768]`、CLAP `[1024]`；全部 finite、逐位一致、最大绝对差 0。
- RTX 5090 canonical T=10 student efficiency receipt：29.631 ms/clip、33.748 clips/s。T=16 收据已明确改标为 synthetic positional-capacity analysis，不是论文任务协议。
- raw archive 的 13 个零字节 MP4 和 1,019 个短流仍完整记录，但仅属于 optional diagnostic；canonical JPG/WAV 主线不读取、填充或替换它们。

## 尚未完成

1. teacher cache 仍为 `0/24,800`；需运行可恢复、逐记录有 receipt 的全量导出。
2. exported manifests 和所有 artifacts 尚未完成 full audit，因此 cache root SHA256 仍不存在。
3. 真实数据一步 forward/backward preflight 尚未运行，调用次数保持 0；必须等完整 cache audit 通过后且最多运行一次。
4. `configs/ov_orthkd_mm26_repro_ready.yaml` 仍有意不存在；canonical readiness receipt 尚不能 READY。
5. 正式学生训练未启动，`reproduction.full_run_blocked: true` 保持不变。

## 下一步严格顺序

1. 从已审计 source manifests 可恢复地导出 24,800 条 InternVideo2/BEATs/CLAP artifacts。
2. 对 exported manifests 和 cache 全量逐文件审计，锁定 cache root SHA256。
3. 运行且只运行一次真实数据单 optimizer-step preflight，核对 shape receipt 中所有 temporal 张量均为 T=10。
4. 生成 ready config/readiness receipt，运行全测试并做人工审阅。
5. 只有人工审阅确认 `READY_FOR_CONFERENCE_REPRO` 后，才按实验计划启动正式复现。

## Web 审阅入口

- 本阶段总报告：[`reports/R4_T10_TEMPORAL_PROTOCOL_CORRECTION_REPORT.md`](reports/R4_T10_TEMPORAL_PROTOCOL_CORRECTION_REPORT.md)
- source audit：[`reports/mm26_source_manifest_audit.json`](reports/mm26_source_manifest_audit.json)
- teacher identity：[`reports/teachers/teacher_identity.json`](reports/teachers/teacher_identity.json)
- repeatability：[`reports/teachers/smoke_repeatability.json`](reports/teachers/smoke_repeatability.json)
- data/download/teacher/archival/preprocessing locks：[`configs/locks`](configs/locks)
- 当前 fail-closed readiness：[`reports/mm26_conference_readiness.json`](reports/mm26_conference_readiness.json)
- 稿件精确替换文字：[`docs/MM26_TEMPORAL_PROTOCOL_TEXT_CORRECTIONS.md`](docs/MM26_TEMPORAL_PROTOCOL_TEXT_CORRECTIONS.md)

## 数据与仓库边界

GitHub 只上传代码、配置、测试和小型审计收据。`data/` 中的正式数据、source/export manifests、下载断点，`weights/`、teacher cache、outputs/logs/runs、Cookie/HAR/token/signed URL 都留在 5090，不上传。

5090 工作路径：`E:/OV-OrthKD-R3/repo`。
