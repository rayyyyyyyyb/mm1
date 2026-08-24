# OV-OrthKD 当前状态与复现接续指南

更新日期：2026-08-24

分支：`repro/r3-assets-download-and-readiness`

最终状态：`BLOCKED_BEFORE_CONFERENCE_REPRO`

## 一句话结论

代码、RTX 5090 环境、五项教师权重、两个官方 OV-AVEBench 压缩包、安全解压和全量审计已经完成；正式会议复现仍被作者发布的 raw archive 中 13 个零字节 MP4，以及 1,019 个短于当前锁定十秒协议的视频流阻塞。不得用 YouTube 重切、第三方镜像、重复帧、静音填充或预处理 JPG/WAV 冒充官方 raw MP4。

## 已完成且可复核的事实

- 五项教师 checkpoint 均已下载、锁定 SHA256 并通过结构检查和真实 wrapper strict-load：InternVideo2 B14、InternVideo2 CLIP-B14、MobileCLIP-B-LT、BEATs Iter3+ AS2M、Microsoft CLAP 2023。
- 官方 preprocessed archive：24,618,769,924 bytes，SHA256 `ebecec9915052beffbba7ae1debd7b45cfef7b70fd7866196b964ab8542a413e`。
- 官方 raw archive：38,147,170,955 bytes，SHA256 `ac9c8fc6e8b905ed414082132d6c2f8c81f5a8aad5d2c996e7512a40ff12b1bc`。
- preprocessed 安全解压：272,800 files，27,959,350,079 bytes，tree SHA256 `7a2c848fcdfe5118b3ac1de23eaa7b9121c4e3a98f98d0112b3c6e6b72d75e60`。
- raw 安全解压：24,836 files，38,365,245,540 bytes，tree SHA256 `33e467c428432c5b67876350cd3f3bac0e267730f56ee71631e8864bf2077a89`。
- preprocessed 全量布局：24,800 samples，13,182/5,798/5,820 train/val/test；248,000 JPG + 24,800 WAV；metadata bijection 成立；missing/extra/duplicate/zero-byte/errors/warnings 全为 0。
- raw 全量 ffprobe：24,800 个正式 ID 完整匹配；25 个 macOS AppleDouble sidecar 被排除；13 个正式 MP4 为零字节；1,019 个非空视频流短于 10.0 秒。
- canonical source-manifest builder 在首个零字节视频处退出 1，且没有发布任何 partial manifest。
- 最新完整测试：`319 passed in 309.73s`，退出码 0，stderr 为空。
- `python -m compileall -q src scripts tests`、`python -m pip check`、五项权重验证和 RTX 5090 CUDA 12.8 FP16 验证均退出 0。

## 尚未运行的阶段

- 正式 real-teacher 全量 cache：`0/24,800`，所以 cache root SHA256 不存在。
- 真实数据的一步 optimizer preflight：调用次数 `0`。
- 正式学生训练：未启动。
- `configs/ov_orthkd_mm26_repro_ready.yaml`：有意保持不存在。
- `configs/ov_orthkd_mm26_repro.yaml` 中 `full_run_blocked`：仍为 `true`。

这些不是遗漏，而是 raw 数据未通过前必须保持的 fail-closed 边界。

## 当前外部阻塞项

1. 从 OV-AVEL 作者获得修正后的官方 raw archive，或 13 个精确原始 MP4 与作者校验值。
2. 从作者获得 1,019 个短视频的官方处理协议，或作者发布的修正源文件。

VGGSound metadata 只能确认来源身份和候选开始时间，不能授权重新下载后冒充作者发布字节；其中 `di01T0hGboU` 还有两个候选时间戳，仓库没有猜测。

可直接提交给作者的完整说明位于 [`reports/data/OVAVEBENCH_RAW_VIDEO_AUTHOR_REQUEST.md`](reports/data/OVAVEBENCH_RAW_VIDEO_AUTHOR_REQUEST.md)。建议在官方仓库创建 issue：<https://github.com/jasongief/OV-AVEL/issues/new>。

## 作者材料到达后的严格顺序

1. 保持两个原始下载 archive 不变，把作者修正文件放进未跟踪的 quarantine overlay。
2. 为作者文件建立 declaration，并运行 `scripts/verify_ovave_raw_replacements.py`；必须是完整唯一的 13 项集合、作者控制的 locator、重新计算的 SHA256、非零字节、音视频流可解码且时长合规。
3. 按作者正式说明锁定短视频协议；不得自行选择 padding、repeat、loop 或替代源。
4. 重新运行完整 raw layout audit，要求零 error/zero-byte/short-policy violation。
5. 重新构建并全量审计 train/val/test source manifests。
6. 依次运行真实教师 smoke/repeatability、24,800 条全量教师导出和 artifact audit，生成 cache root SHA256。
7. 最多运行一次真实数据的一步 forward/backward preflight。
8. 重新生成 canonical readiness receipt；只有完整证据链为 READY 后才能进入下一次人工 review。不得在本阶段直接启动正式学生训练。

## Web 审阅入口

- 阶段总报告：[`reports/R3_ASSET_DOWNLOAD_AND_READINESS_REPORT.md`](reports/R3_ASSET_DOWNLOAD_AND_READINESS_REPORT.md)
- 最终 readiness：[`reports/mm26_conference_readiness.json`](reports/mm26_conference_readiness.json)
- data lock：[`configs/locks/mm26_data_lock.yaml`](configs/locks/mm26_data_lock.yaml)
- download lock：[`configs/locks/mm26_download_lock.yaml`](configs/locks/mm26_download_lock.yaml)
- archival lock：[`configs/locks/mm26_archival_facts.yaml`](configs/locks/mm26_archival_facts.yaml)
- teacher lock：[`configs/locks/mm26_teacher_lock.yaml`](configs/locks/mm26_teacher_lock.yaml)
- raw 全量审计：[`reports/data/raw_video_layout_discovery.json`](reports/data/raw_video_layout_discovery.json)
- raw 恢复清单：[`reports/data/ovave_raw_video_recovery_manifest.json`](reports/data/ovave_raw_video_recovery_manifest.json)
- 预处理全量审计收据：[`reports/data/preprocessed_filesystem_layout_receipt.json`](reports/data/preprocessed_filesystem_layout_receipt.json)

## 数据与仓库边界

GitHub 仓库只包含代码、配置、锁、测试、小型审计收据以及不含媒体字节的结构化报告。下列内容由 `.gitignore` 排除且仅保留在 5090：

- `data/` 下的正式数据、解压树、下载断点、quarantine 和临时状态；
- `weights/`、checkpoint、teacher cache；
- outputs、logs、runs 和 evaluation results；
- Cookie、HAR、signed URL、token、浏览器认证状态。

5090 主工作路径为 `E:/OV-OrthKD-R3/repo`。正式数据和环境留在 5090，不应上传到 GitHub。

## 审阅者需要判断的问题

1. 是否认可当前对 13 个零字节 MP4 的 fail-closed 处理和作者替换边界？
2. 是否存在可引用的作者证据，能够唯一确定 1,019 个短视频的正式 temporal boundary policy？
3. 在上述两项解除前，是否同意继续禁止 source manifests、teacher cache、preflight 和正式训练？
4. 作者证据到位后，是否按“raw audit → source audit → teacher export → artifact audit → one-step preflight → review”顺序进入下一阶段？
