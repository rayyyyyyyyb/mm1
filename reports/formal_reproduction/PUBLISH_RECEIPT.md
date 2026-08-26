# Canonical seed42 GitHub 发布收据

发布日期：2026-08-26

## Git 身份

- repository：`https://github.com/rayyyyyyyyb/mm1`
- branch：`repro/canonical-seed42-results`
- formal-run source commit：`31b86c0d60c4bf2ed028edf1385ed5d2c9e89153`
- evidence publication commit：`28da2c7808f8bf747b13315c73f9e5821a23c38a`
- evidence commit stat：36 files changed、3,343 insertions、68 deletions

## Fresh verification

- RTX 5090 locked environment：`388 passed in 387.04s`、pytest exit 0
- locked MinGit：`2.55.0.windows.5`
- formal evidence source/index byte identity：17/17
- final artifact audit：`PASS`、errors=0
- JSON/YAML parse：75/75
- PowerShell parser：7 files、0 errors
- compileall：exit 0
- `git diff --cached --check`：exit 0
- staged `src/scripts/configs/tests` changes：0
- files larger than 5 MiB：0
- forbidden dataset/checkpoint/cache/prediction extensions：0
- secret-like material matches：0

本机 Python 环境缺少 `timm`，本地 pytest 在 collection 阶段产生 16 个 import errors、exit 1；该失败没有被写成代码通过。5090 第一次 fresh pytest 因命令遗漏 MinGit PATH 得到 `352 passed, 36 failed`、exit 1；补回锁定 MinGit 后从头完整重跑得到上述 388-pass 结果。

## Web readback

推送 evidence commit 后，使用未登录公开访问分别读取并确认：

1. branch tree：`https://github.com/rayyyyyyyyb/mm1/tree/repro/canonical-seed42-results`
2. evidence landing page：`https://github.com/rayyyyyyyyb/mm1/blob/repro/canonical-seed42-results/reports/formal_reproduction/README.md`
3. raw final metrics：`https://raw.githubusercontent.com/rayyyyyyyyb/mm1/repro/canonical-seed42-results/reports/formal_reproduction/canonical_seed42/canonical_seed42/final_metrics.json`

branch tree 显示新分支和更新后的正式运行状态；landing page 正常渲染；raw final metrics 返回 126 行实际 JSON，包含 validation/test total/seen/unseen 指标，不是 Git LFS 指针或占位内容。

## 未上传边界

未上传 OV-AVEBench 数据、教师 checkpoint/cache、`best.pt`、`last.pt`、prediction NPZ 或完整训练进度流。其身份、数量、bytes、SHA256、shape 与审计状态由已上传的小型 receipts 记录。
