# MM26 OV-OrthKD R2：原会议论文复现前最终就绪门与基线任务书

> **适用仓库**：`https://github.com/rayyyyyyyyb/mm1`
> **唯一 R2 起点**：`6e4ea32c8e3cd84c07bc45d6e3ea3528d3fa9986`
> **建议分支**：`repro/r2-conference-reproduction-readiness`
> **本阶段范围**：只为 ACM MM 2026 原会议论文 OV-OrthKD 的复现做最终准备；**禁止实现 VP-AdaOrthKD 或任何期刊扩展机制**。
> **允许的最终状态**：`READY_TO_IMPLEMENT_CONFERENCE_EXPERIMENTS` 或 `BLOCKED_BEFORE_CONFERENCE_EXPERIMENTS`。

---

## 0. Codex 必须先接受的结论

当前 R1 分支完成了大量必要的工程加固，但它的正式报告状态仍是：

```text
BLOCKED_BEFORE_R2
```

这不是措辞问题。当前仓库仍然没有：

- 官方预处理音视频数据；
- 真实 train/val/test source manifest；
- 已锁定身份和 SHA256 的 InternVideo2、BEATs、CLAP；
- 真实教师工件缓存；
- 真实数据一批次 forward/backward；
- 可解除 `full_run_blocked` 的完整证据链。

此外，本轮审计发现若干 R1 尚未覆盖的 P0/P1 问题。它们必须先修正，否则即使数据和教师下载完成，也可能得到“能跑、但 seen/unseen 分组错误、指标定义不一致或缓存相互覆盖”的假复现。

本任务书的目标不是启动 30 epoch 训练，而是完成：

```text
代码最后加固
→ 官方数据人工下载与锁定
→ 数据布局和预处理冻结
→ 历史事实恢复/显式重建假设
→ 教师身份与 checkpoint 锁定
→ 真实教师工件导出与全量审计
→ 真实一步 preflight 与断点一致性
→ 会议实验配置骨架与最终运行门
```

---

## 1. 复现声明必须分成三档

在代码和报告中新增：

```yaml
reproduction:
  claim_level: archival_exact
```

允许值仅为：

1. `archival_exact`
   - 所有历史事实由旧代码、旧日志、旧 checkpoint、原实验机器或作者直接证据恢复；
   - 才能称为“原会议实验的精确归档复现”。

2. `paper_specified_reconstruction`
   - 无法恢复某些历史事实，但根据 camera-ready 论文、官方 benchmark 和明确记录的最小假设重建；
   - 可以称为“按论文规格重建复现”；
   - 不得声称与历史运行逐配置一致。

3. `noncanonical_diagnostic`
   - mock、smoke、接口测试、随意 checkpoint、未锁定教师或 `--allow-blocked-reproduction`；
   - 不能进入论文结果表。

如果历史证据长期缺失，不要无限期停工。可以在用户明确批准后，把具体事实标记为：

```yaml
status: approved_reconstruction_assumption
approved_by: user
reason: "..."
```

随后以 `paper_specified_reconstruction` 运行，但所有输出目录、报告和表格必须带该标签。

---

# Part A：先修复当前代码中的 P0 问题

## 2. P0：当前 manifest builder 与 dataset 的 seen/unseen 接口不闭合

### 2.1 问题

当前 `scripts/build_ov_avebench_source_manifests.py` 只写：

```json
"meta": {
  "cls_type": "close" 或 "open"
}
```

但 `src/data/ov_avel_dataset.py` 读取：

- 顶层 `split_type`；
- `meta.split_type`；
- `meta.seen_unseen`；
- `meta.novelty`；

并没有读取 `meta.cls_type`。

结果是：由当前 builder 生成的真实 manifest 会被加载成：

```text
split_type = unknown
```

随后：

- seen 指标为空；
- unseen 指标为空；
- audit 报 `missing_split_type`；
- Table 5 的 seen/unseen 结果无法可信复现。

### 2.2 新增统一 helper

新增文件：

```text
src/data/split_types.py
```

建议完整实现：

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_RAW_TO_CANONICAL = {
    "close": "seen",
    "open": "unseen",
    "seen": "seen",
    "unseen": "unseen",
}


def canonicalize_split_type(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    return _RAW_TO_CANONICAL.get(normalized)


def normalize_record_split_type(
    record: Mapping[str, Any],
    *,
    strict: bool = True,
) -> str:
    meta_value = record.get("meta", {})
    meta = meta_value if isinstance(meta_value, Mapping) else {}

    raw_candidates = [
        record.get("split_type"),
        record.get("seen_unseen"),
        record.get("novelty"),
        meta.get("split_type"),
        meta.get("seen_unseen"),
        meta.get("novelty"),
        meta.get("cls_type"),
    ]
    canonical = [
        mapped
        for mapped in (canonicalize_split_type(value) for value in raw_candidates)
        if mapped is not None
    ]

    if not canonical:
        if strict:
            raise ValueError(
                "Missing valid seen/unseen metadata. Expected one of "
                "split_type, seen_unseen, novelty, or meta.cls_type."
            )
        return "unknown"

    unique = sorted(set(canonical))
    if len(unique) != 1:
        raise ValueError(f"Conflicting seen/unseen metadata: {unique}")
    return unique[0]
```

### 2.3 修改 manifest builder

在 `_build_record()` 中：

```python
from src.data.split_types import canonicalize_split_type

cls_type = row["cls_type"].strip().lower()
split_type = canonicalize_split_type(cls_type)
if split_type is None:
    raise ValueError(f"Unsupported cls_type={cls_type!r} for clip {clip_id}")
```

返回记录时同时写入顶层字段：

```python
{
    "id": clip_id,
    "query": category,
    "split_type": split_type,
    ...,
    "meta": {
        "split": split,
        "category": category,
        "cls_type": cls_type,
        "split_type": split_type,
        "source": "released_ovavel_dataset_anno.json",
    },
}
```

### 2.4 修改 dataset loader

替换现有手写读取：

```python
split_type = normalize_record_split_type(record, strict=True)
```

canonical 配置不得返回 `unknown`。

### 2.5 修改 audit

`audit_mm26_reproduction.py` 必须调用同一 helper，而不是复制另一套字段选择逻辑。

### 2.6 必加回归测试

新增：

```text
tests/test_r2_split_type_contract.py
```

至少验证：

```text
close → seen
open → unseen
meta.cls_type 可被识别
顶层与 meta 冲突时 fail fast
```

官方元数据精确计数必须为：

```text
train seen   = 13182
train unseen = 0
val seen     = 1651
val unseen   = 4147
test seen    = 1664
test unseen  = 4156
```

---

## 3. P0：`full_run_blocked` 只是一个可手改布尔值，canonical gate 不够强

### 3.1 问题

当前 `validate_repro_config()` 在：

```yaml
full_run_blocked: false
```

时直接返回。也就是说，只需修改一个布尔值，即可绕开：

- data lock；
- teacher lock；
- archival fact lock；
- evaluator lock；
- preprocessing lock；
- 教师缓存全量 audit；
- checkpoint SHA256；
- manifest SHA256。

这不足以保护正式会议结果。

### 3.2 新增 readiness 配置

在 canonical 配置中加入：

```yaml
reproduction:
  claim_level: archival_exact
  full_run_blocked: true
  readiness:
    data_lock: configs/locks/mm26_data_lock.yaml
    archival_lock: configs/locks/mm26_archival_facts.yaml
    teacher_lock: configs/locks/mm26_teacher_lock.yaml
    preprocessing_lock: configs/locks/mm26_preprocessing_lock.yaml
    evaluator_lock: configs/locks/mm26_evaluator_lock.yaml
    exported_artifact_audit: reports/mm26_exported_artifact_audit.json
    readiness_receipt: reports/mm26_conference_readiness.json
```

### 3.3 新增文件

```text
src/utils/canonical_readiness.py
```

其职责必须包括：

1. 读取五个 lock 与 exported audit；
2. 验证每个文件存在；
3. 验证 schema version；
4. 验证 status；
5. 验证所有声明的文件 SHA256 与实际文件一致；
6. 验证 train/val/test 数量；
7. 验证教师 checkpoint 和上游仓库 commit；
8. 验证缓存无缺失、无 shape 错误、无 NaN/Inf、无 collision；
9. 验证 evaluator 与官方 evaluator 的固定 commit/SHA；
10. 验证未出现 `UNRESOLVED`、`BLOCKED`、`NOT_EXECUTED` 等占位状态；
11. 返回完整 readiness receipt，而不是简单 True/False。

建议接口：

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class CanonicalReadiness:
    ready: bool
    claim_level: str
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    lock_paths: dict[str, Path]
    lock_sha256: dict[str, str]
    cache_root_sha256: str | None


def validate_canonical_readiness(
    config: Mapping[str, Any],
    *,
    path_root: str | Path,
) -> CanonicalReadiness:
    ...
```

### 3.4 运行规则

- `full_run_blocked: true`：始终禁止完整训练；
- `full_run_blocked: false`：仍必须通过 `validate_canonical_readiness()`；
- `--allow-blocked-reproduction`：只能建立 `noncanonical_diagnostic` 目录；
- `--allow-blocked-reproduction` 绝不能生成名为 `best_conference.pt`、`paper_results.json` 等正式产物；
- eval-only 也必须验证 checkpoint fingerprint 和 lock hashes，但不构造 optimizer/scheduler。

### 3.5 fingerprint 必须包含 lock

当前函数支持 `lock_paths`，但训练脚本调用时未传入。

修改为：

```python
lock_paths = resolve_readiness_lock_paths(config)
reproduction_fingerprint = build_reproduction_fingerprint(
    config,
    lock_paths=lock_paths,
)
```

fingerprint 还应包含：

- exported artifact audit SHA256；
- teacher cache root SHA256；
- 官方 evaluator SHA256；
- 当前 Git HEAD；
- implementation mode；
- experiment variant ID。

### 3.6 必加测试

```text
tests/test_r2_canonical_readiness_gate.py
```

测试：

- 单纯将 `full_run_blocked` 改为 false 仍会失败；
- 缺任一 lock 会失败；
- lock 内容被篡改会失败；
- checkpoint hash 不符会失败；
- artifact audit 有 warning 也会失败；
- 所有 fixture 完整时才通过。

---

## 4. P0：当前 `f1` 是全局二分类 micro F1，不能直接冒充官方 Seg. F1

### 4.1 问题

当前：

```python
f1_score(flattened_labels, flattened_predictions)
```

把所有样本的所有时间片段压成一条长向量。

而官方 OV-AVEL 代码定义了：

- accuracy；
- segment-level F1；
- event-level F1。

其 segment F1 是对每条样本的活动类别做 F1，再做样本级平均；event F1 按连续事件和 IoU 阈值计算。

当前全局二分类 F1 可能对应论文内部的 `F1@0.5`，也可能不对应。没有归档证据前，不能把它直接命名为官方 `Seg. F1`。

### 4.2 输出中显式分名

至少输出：

```text
binary_micro_f1_at_0_5
query_fg_f1_macro_at_0_5
ovavel_segment_f1_at_0_5
ovavel_event_f1_at_0_5
```

并保留：

```text
segment_ap
segment_auroc
```

### 4.3 新增 metric 文件

```text
src/evaluation/ovavel_metrics.py
```

建议核心实现：

```python
from __future__ import annotations

from collections.abc import Iterable
import numpy as np


def stable_sigmoid(logits: np.ndarray) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float64)
    output = np.empty_like(values)
    positive = values >= 0
    output[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    negative_exp = np.exp(values[~positive])
    output[~positive] = negative_exp / (1.0 + negative_exp)
    return output


def _binary_f1(pred: np.ndarray, gt: np.ndarray) -> float:
    pred = np.asarray(pred, dtype=np.int64)
    gt = np.asarray(gt, dtype=np.int64)
    tp = int(np.sum((pred == 1) & (gt == 1)))
    fp = int(np.sum((pred == 1) & (gt == 0)))
    fn = int(np.sum((pred == 0) & (gt == 1)))
    denom = 2 * tp + fp + fn
    return 1.0 if denom == 0 else float(2 * tp / denom)


def ovavel_segment_f1_query_background(
    pred_fg: np.ndarray,
    gt_fg: np.ndarray,
) -> float:
    pred_fg = np.asarray(pred_fg, dtype=np.int64).reshape(-1)
    gt_fg = np.asarray(gt_fg, dtype=np.int64).reshape(-1)
    if pred_fg.shape != gt_fg.shape or pred_fg.size == 0:
        raise ValueError("pred/gt must be nonempty and have identical shapes")

    pred = np.stack([pred_fg, 1 - pred_fg], axis=0)
    gt = np.stack([gt_fg, 1 - gt_fg], axis=0)
    tp = np.sum(pred * gt, axis=1)
    fn = np.sum((1 - pred) * gt, axis=1)
    fp = np.sum(pred * (1 - gt), axis=1)
    active = ((tp + fp) != 0) | ((tp + fn) != 0)
    if not np.any(active):
        return 1.0
    scores = 2 * tp[active] / (2 * tp[active] + fp[active] + fn[active])
    return float(np.mean(scores))


def _events(mask: np.ndarray) -> list[tuple[int, int]]:
    values = np.asarray(mask, dtype=np.int64).reshape(-1)
    events: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(values.tolist() + [0]):
        if value == 1 and start is None:
            start = index
        elif value == 0 and start is not None:
            events.append((start, index))
            start = None
    return events


def _interval_iou(left: tuple[int, int], right: tuple[int, int]) -> float:
    intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return 0.0 if union <= 0 else float(intersection / union)


def ovavel_event_f1(
    pred_fg: np.ndarray,
    gt_fg: np.ndarray,
    *,
    iou_threshold: float = 0.5,
) -> float:
    pred_events = _events(pred_fg)
    gt_events = _events(gt_fg)
    if not pred_events and not gt_events:
        return 1.0

    # 与官方 evaluator 的非排他式匹配语义保持一致：
    # 每个预测事件只要与任一 GT 的 IoU 达阈值即计 TP；
    # 每个 GT 只要与任一预测事件匹配就不计 FN。
    tp = sum(
        any(_interval_iou(pred, gt) >= iou_threshold for gt in gt_events)
        for pred in pred_events
    )
    fp = len(pred_events) - tp
    fn = sum(
        not any(_interval_iou(pred, gt) >= iou_threshold for pred in pred_events)
        for gt in gt_events
    )
    denom = 2 * tp + fp + fn
    return 1.0 if denom == 0 else float(2 * tp / denom)
```

对完整 predictions 使用 `sample_offsets` 恢复每条样本，再做样本平均。

### 4.4 官方 evaluator parity lock

新增：

```text
configs/locks/mm26_evaluator_lock.yaml
```

至少包含：

```yaml
schema_version: 1
status: blocked
upstream_repo: https://github.com/jasongief/OV-AVEL
upstream_commit: b5fe1d685d0c6d0d6fd80312b5ccde79f9b73ea6
source_file: proposed_method/ImageBind-main/utils/eval_metrics.py
source_sha256: null
paper_f1_at_0_5_mapping: unresolved
validation_calibrated_f1_mapping: unresolved
```

新增固定 synthetic cases，分别由官方 evaluator 与本地实现计算，逐项比较。

不要在 test 时联网。将测试输入和官方期望值保存为：

```text
tests/fixtures/official_ovavel_metric_cases.json
```

同时保存生成 receipt 和上游 SHA。

### 4.5 表格字段约束

任何自动表格都必须显示完整字段名，不能只写 `F1`：

```text
AP
AUROC
Binary micro F1@0.5
Official-compatible Seg. F1@0.5
Event F1@0.5
Val-calibrated binary F1
```

当历史论文列的具体 evaluator 尚未恢复时，报告中应并列给出，不得选择最有利的一个冒充论文值。

---

## 5. P0：当前 source manifest builder 预设了一套未被论文锁定的音视频预处理

### 5.1 当前危险假设

当前 builder 会：

- 对帧文件做普通字典序排序；
- 把所有帧平均切成 10 组；
- 帧少于片段时重复最近帧；
- 把整条 wav 等分为 10 段；
- 使用 `n_fft=1024, hop=256, n_mels=128`；
- 每段单独 `power_to_db(ref=np.max)`；
- 映射到 RGB JPEG 224×224；
- 学生音频分支再用 ImageNet mean/std 归一化。

这些不是 camera-ready 论文明确给出的完整历史规格。官方 benchmark 已经提供预处理 `.wav` 与 `.png`，所以在看清官方目录布局前，不应该重新发明一套 JPEG mel 管线。

### 5.2 立即调整职责

把现有脚本拆成两层：

1. **official layout manifest**
   - 只发现和引用官方 `.png` / `.wav`；
   - 不生成 spectrogram；
   - 不重复帧；
   - 不重采样时间轴。

2. **student audio preprocessing**
   - 在历史规格恢复后，由独立 backend 在线或离线生成；
   - 每个参数写入 preprocessing lock。

现有 spectrogram 生成代码保留，但改名/标记为：

```text
noncanonical_legacy_generated_jpeg_mel
```

canonical 配置不能默认调用它。

### 5.3 自然排序

新增：

```python
import re
from pathlib import Path


def natural_path_key(path: Path) -> tuple[object, ...]:
    return tuple(
        int(token) if token.isdigit() else token.lower()
        for token in re.split(r"(\d+)", path.name)
    )
```

所有帧路径使用：

```python
sorted(paths, key=natural_path_key)
```

### 5.4 canonical 禁止静默重复帧

若实际 layout 要求每个片段一张 png，则严格要求：

```text
每个 clip = T 张 png
```

若 InternVideo2 教师每段需要 8 帧，则其帧组来自明确的 raw-frame/视频采样协议，不能从单张官方 png 复制 8 次后称为原始教师输入，除非历史实现确实如此。

### 5.5 外部数据盘路径

当前 `_relpath(...).relative_to(repo_root)` 在数据集位于仓库外部磁盘时会失败。

给 builder 增加：

```text
--path-mode relative_to_path_root | absolute
--path-root <root>
```

manifest 应优先保存相对于 `data.path_root` 的路径，而不是强制相对于 Git 仓库。

### 5.6 原子写 manifest

不要直接覆盖正式 JSONL。使用：

```text
train_source.jsonl.partial
→ fsync
→ os.replace(..., train_source.jsonl)
```

### 5.7 新增 preprocessing lock

```text
configs/locks/mm26_preprocessing_lock.yaml
```

必须包含：

```yaml
schema_version: 1
status: blocked
visual:
  source: official_png | raw_video
  temporal_segments: null
  frame_selection: null
  resize: null
  crop: null
  normalization: null
  augmentation: null
student_audio:
  source: official_wav
  sample_rate: null
  segment_duration_seconds: null
  representation: null
  n_fft: null
  hop_length: null
  win_length: null
  n_mels: null
  f_min: null
  f_max: null
  power_to_db_reference: null
  image_or_tensor_shape: null
  normalization: null
teachers:
  internvideo2_frame_sampling: null
  beats_waveform_preprocessing: null
```

以下两项应加入 archival blockers：

- exact visual frame sampling；
- exact student audio preprocessing。

---

## 6. P0：教师导出 receipt 当前是 O(N²) 写放大，且跨 split 有覆盖风险

### 6.1 O(N²) 问题

当前每导出一条 record，都会把 `published_receipts` 的全部内容重新写入整个 JSONL。

24,800 条记录下，这会导致大量无意义的重复写入，Windows/SSD 上尤其慢，且中断恢复成本高。

### 6.2 跨 split 覆盖问题

当前工件路径：

```text
artifact_root/<safe_record_id>/...
```

没有 split。若 train/val/test 中存在相同 ID，或后续更换数据版本出现同 ID，就可能覆盖。

### 6.3 新路径规范

改为：

```text
data/teacher_cache/mm26/
  train/<safe_id>/...
  val/<safe_id>/...
  test/<safe_id>/...
```

所有 path helper 接受 `split`：

```python
def record_artifact_dir(
    artifact_root: str | Path,
    split: str,
    record_name: str,
) -> Path:
    canonical_split = str(split).strip().lower()
    if canonical_split not in {"train", "val", "test"}:
        raise ValueError(f"Unsupported split: {split!r}")
    return Path(artifact_root) / canonical_split / safe_record_id(record_name)
```

### 6.4 每条 receipt 独立原子写

建议目录：

```text
receipts/train/<safe_id>.json
receipts/val/<safe_id>.json
receipts/test/<safe_id>.json
```

每条成功后只写自己的 JSON；最终全部完成后，再按排序生成一次：

```text
receipts/all_receipts.jsonl
```

中断恢复时只扫描 receipt 目录，不反复重写累计 JSONL。

### 6.5 error receipt

错误同样使用每条文件或 append-only 日志，不能每次重写整个累计数组。

### 6.6 text query 共享缓存

OV-AVEBench 只有 67 个类别。可以建立：

```text
text_by_query/<query_hash>.npy
```

record receipt 指向共享 embedding，并记录 query 字符串和 hash，避免同一文本写 24,800 份。

若为保持旧 manifest 接口需要 record-level 文件，可使用 hard link/copy，但 cache root 统计应区分逻辑工件和物理文件。

### 6.7 导出验收

full export 后必须验证：

```text
records = 24800
train = 13182
val = 5798
test = 5820
missing = 0
shape_errors = 0
non_finite = 0
stale_lock = 0
path_collisions = 0
receipt_errors = 0
```

---

# Part B：修复 P1 的确定性、模型构造和安全问题

## 7. P1：断点恢复未保存 early-stop 状态，persistent workers 也破坏严格复现

### 7.1 保存 early-stop 状态

当前 resume 后：

```python
epochs_without_improvement = 0
```

这会改变早停行为。

在 checkpoint payload 中增加：

```python
"epochs_without_improvement": int(epochs_without_improvement),
```

`maybe_resume()` 返回：

```python
start_epoch, best_metric, global_step, epochs_without_improvement
```

### 7.2 canonical 关闭 persistent workers

在配置中加入：

```yaml
data:
  persistent_workers: false
```

DataLoader 使用：

```python
persistent_workers = bool(data_cfg.get("persistent_workers", False)) and num_workers > 0
```

理由：worker 内部 torchvision 随机状态并未被 checkpoint 保存。关闭 persistent workers 后，每个 epoch 的 worker 由已保存的 loader generator 可重复初始化。

### 7.3 CUBLAS 环境变量必须在 CUDA 初始化前设置

当前先执行：

```python
torch.cuda.is_available()
```

再在 `set_seed()` 中设置 `CUBLAS_WORKSPACE_CONFIG`，顺序太晚。

推荐新增 launcher：

```text
scripts/launch_deterministic.py
```

或在 `train_ov_orthkd.py` 顶部、导入 torch 前设置：

```python
import os
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
```

服务器 shell 也明确导出：

```bash
export CUBLAS_WORKSPACE_CONFIG=:4096:8
```

PowerShell：

```powershell
$env:CUBLAS_WORKSPACE_CONFIG = ':4096:8'
```

### 7.4 严格 resume 集成测试

新增：

```text
tests/test_r2_exact_epoch_resume.py
```

比较：

```text
连续训练 3 epoch
vs
训练 1 epoch → 保存 → 恢复训练 2 epoch
```

要求：

- `num_workers >= 2`；
- train augmentation 开启；
- 模型参数逐元素相同；
- optimizer/scheduler/scaler 相同；
- history 相同；
- global step 相同；
- early-stop counter 相同。

如果 Windows 多进程 fixture 不稳定，可将该测试标记为 integration，并在 5090 机器真实执行，但不得只用 `num_workers=0` 的单元测试替代。

---

## 8. P1：模型构造时的 feature-dim probe 可能污染 BatchNorm running stats

当前 backbone 在默认 train mode 下对全零图做一次 forward。

修改：

```python
def _infer_feature_dim(self) -> int:
    declared = getattr(self.backbone, "num_features", None)
    if declared is not None:
        return int(declared)

    was_training = self.backbone.training
    try:
        self.backbone.eval()
        with torch.inference_mode():
            probe = torch.zeros(1, 3, 224, 224)
            features = self.backbone(probe)
        return int(features.shape[-1])
    finally:
        self.backbone.train(was_training)
```

测试：模型构造前后，任何 BatchNorm `running_mean` / `running_var` 不得因 probe 改变。

---

## 9. P1：教师 wrapper 的文件和确定性问题

### 9.1 InternVideo2 图片句柄

替换：

```python
image = Image.open(path).convert("RGB")
```

为：

```python
with Image.open(path) as image:
    rgb = image.convert("RGB").copy()
array = np.asarray(rgb, dtype=np.uint8)
```

### 9.2 BEATs `.npy/.npz`

当前 `np.load(path)` 未设置 `allow_pickle=False`，且 `.npz` 会返回 `NpzFile`，不能直接 `np.asarray`。

建议：

```python
def _load_waveform_array(path: Path) -> np.ndarray:
    suffix = path.suffix.lower()
    if suffix == ".npy":
        array = np.load(path, allow_pickle=False)
    elif suffix == ".npz":
        with np.load(path, allow_pickle=False) as bundle:
            keys = list(bundle.keys())
            if keys != ["waveform"]:
                raise ValueError(
                    f"Expected exactly one npz key named 'waveform', got {keys}"
                )
            array = bundle["waveform"]
    else:
        raise ValueError(f"Unsupported waveform array extension: {path}")
    normalized = np.asarray(array, dtype=np.float32)
    if normalized.dtype == object or not np.isfinite(normalized).all():
        raise ValueError(f"Unsafe or non-finite waveform array: {path}")
    return normalized.reshape(-1)
```

### 9.3 checkpoint 安全

所有第三方 checkpoint 必须先：

- 来自锁定的官方来源；
- 计算 SHA256；
- 与 teacher lock 一致；
- 再允许 `torch.load`。

若 checkpoint 与 `weights_only=True` 兼容则优先使用。若必须 `weights_only=False`，必须在代码中明确说明它只对 SHA 锁定的可信官方文件使用。

### 9.4 CLAP/所有教师重复导出

real smoke 中，同一输入连续导出至少两次：

```text
features/logits shape 完全相同
所有值 finite
max_abs_diff <= 锁定阈值
```

优先要求 bitwise identical；若上游算子只能做到数值确定，阈值和原因写入 teacher lock。

---

## 10. P1：audit 仍有硬编码和不安全读取

修改 `scripts/audit_mm26_reproduction.py`：

1. 所有 `np.load` 使用 `allow_pickle=False`；
2. `.npz` 必须校验 key；
3. split type 使用统一 helper；
4. `configured_max_segments` 从 config 读取；
5. `resampling_performed_by_dataset` 根据每条记录的实际 evidence 汇总；
6. expected dims 从 config/teacher lock 读取，不硬编码 512/768/1024；
7. 输出每个 split 的 seen/unseen 数量；
8. 输出 source 与 exported manifest 的 SHA；
9. canonical full scan 下 warning 也导致非零退出。

新增参数：

```text
--config configs/ov_orthkd_mm26_repro.local.yaml
--preprocessing-lock ...
--teacher-lock ...
--fail-on-warning
```

---

## 11. P1：static evidence 不完整

`write_static_run_evidence()` 除 manifest 外还必须保存：

```text
config_resolved.yaml
claim_level.txt
git_state.json
manifest_hashes.json
lock_hashes.json
teacher_cache_hash.json
official_evaluator_hash.json
experiment_variant.json
requirements_freeze.txt
cuda_environment.json
```

Git 状态要求：

- canonical run 必须 clean；
- dirty run 自动降级为 `noncanonical_diagnostic`；
- local config 中的绝对路径可以被 ignore，但 resolved config 仍保存到输出目录。

---

# Part C：官方数据的人工下载与完整锁定

## 12. 为什么必须人工下载

R1 已验证官方 SharePoint 匿名访问会跳转 Microsoft 登录，自动下载收到 403/401。不要继续用脚本暴力探测，也不要使用不明镜像。

用户需在浏览器中：

1. 打开官方 `jasongief/OV-AVEL` README；
2. 点击 preprocessed audio/visual 数据链接；
3. 使用有权限的 Microsoft 会话下载；
4. 将原始压缩包复制到本地工作区。

不要把登录 cookie、token 或账号信息写进仓库、MD 或日志。

### 12.1 Windows PowerShell 准备

```powershell
Set-Location <MM1_REPO_ROOT>
New-Item -ItemType Directory -Force data\downloads\official | Out-Null
New-Item -ItemType Directory -Force data\raw\ov_avebench_preprocessed | Out-Null

# 将浏览器下载的真实文件名替换到这里
$Archive = Resolve-Path "$env:USERPROFILE\Downloads\<OFFICIAL_ARCHIVE_NAME>"
Copy-Item $Archive data\downloads\official\ -Force
$LocalArchive = Resolve-Path "data\downloads\official\$($Archive.Path | Split-Path -Leaf)"

Get-Item $LocalArchive | Format-List FullName,Length,LastWriteTimeUtc
Get-FileHash -Algorithm SHA256 $LocalArchive
```

### 12.2 验证不是登录 HTML

```powershell
Format-Hex -Path $LocalArchive -Count 16
```

并用 7-Zip 测试：

```powershell
7z t $LocalArchive
7z l -slt $LocalArchive | Out-File -Encoding utf8 reports\data\official_archive_listing.txt
```

若 7-Zip 不能识别、文件很小或内容为 HTML/XML 登录页，立即停止。

### 12.3 安全解压

实现并使用：

```text
scripts/safe_extract_archive.py
```

必须拒绝：

- `../` 路径穿越；
- 绝对路径；
- symlink/hardlink 逃逸；
- 重复文件覆盖；
- 超大解压比例异常。

示例命令：

```powershell
python scripts/safe_extract_archive.py `
  --archive $LocalArchive `
  --output-dir data\raw\ov_avebench_preprocessed `
  --receipt reports\data\official_archive_extraction_receipt.json
```

### 12.4 Linux 等价命令

```bash
mkdir -p data/downloads/official data/raw/ov_avebench_preprocessed reports/data
sha256sum data/downloads/official/* | tee reports/data/official_archive_sha256.txt
7z t data/downloads/official/<ARCHIVE>
7z l -slt data/downloads/official/<ARCHIVE> > reports/data/official_archive_listing.txt
python scripts/safe_extract_archive.py \
  --archive data/downloads/official/<ARCHIVE> \
  --output-dir data/raw/ov_avebench_preprocessed \
  --receipt reports/data/official_archive_extraction_receipt.json
```

---

## 13. 解压后先发现布局，不要立即生成 manifest

新增：

```text
scripts/discover_ovave_layout.py
```

输出：

```text
reports/data/preprocessed_layout_discovery.json
reports/data/preprocessed_layout_discovery.md
```

必须全量统计：

- 顶层目录；
- train/val/test 是否存在；
- 每个 split/category/clip 文件数；
- `.png/.jpg/.wav/.npy/.npz` 数量；
- PNG 尺寸、通道和命名模式；
- 每个 clip 的视觉片段数量直方图；
- WAV sample rate、通道数、时长直方图；
- CSV 记录是否一一有文件；
- 额外文件和缺失文件；
- 重复 basename；
- 大小为 0 的文件；
- 自然排序前后是否不同。

期望的元数据记录数仍是：

```text
train 13182
val 5798
test 5820
```

只有 layout discovery 通过后，才能决定 manifest 应引用何种路径。

---

## 14. 构建 source manifest

### 14.1 先 smoke

每个 split 选择至少：

- seen 正样本；
- seen 全背景样本；
- unseen 正样本（val/test）；
- 不同正片段长度；
- 文件名含数字、下划线等边界情况。

输出：

```text
data/ov_ave_smoke/source/train_source.jsonl
data/ov_ave_smoke/source/val_source.jsonl
data/ov_ave_smoke/source/test_source.jsonl
```

### 14.2 再全量

```text
data/ov_ave/source/train_source.jsonl
data/ov_ave/source/val_source.jsonl
data/ov_ave/source/test_source.jsonl
```

### 14.3 source audit

```powershell
python scripts/audit_mm26_reproduction.py `
  --config configs/ov_orthkd_mm26_repro.local.yaml `
  --train-manifest data/ov_ave/source/train_source.jsonl `
  --val-manifest data/ov_ave/source/val_source.jsonl `
  --test-manifest data/ov_ave/source/test_source.jsonl `
  --path-root . `
  --stage source `
  --artifact-scan none `
  --expected-segments auto `
  --output-json reports/mm26_source_manifest_audit.json `
  --fail-on-warning
```

source audit 必须为 0 error / 0 warning 后才继续。

---

# Part D：恢复历史事实，或显式批准论文规格重建

## 15. 需要恢复的事实扩展为九项

1. 官方 T=10 与论文表中 16 temporal segments 的关系；
2. exact InternVideo2 model/class/checkpoints；
3. `step400` scheduler 与 early stop；
4. student pretrained initialization 与 augmentation；
5. visual L2 是 feature-dim sum 还是 mean；
6. paper additive fusion + TransformerLayer 与当前 concat-MLP fusion；
7. visual frame sampling；
8. student audio preprocessing；
9. paper `F1@0.5`、Table 5 `Seg. F1`、calibrated F1 的具体 evaluator。

### 15.1 Git/文件证据搜索

在所有旧代码目录执行：

```bash
git log --all --decorate --oneline
git branch -a
git tag -l
git reflog --all
git log --all -S "step400" -- .
git log --all -S "InternVideo2_CLIP" -- .
git log --all -S "lambda_orth" -- .
git log --all -S "early_stop" -- .
git log --all -S "n_mels" -- .
```

Windows 查找旧文件：

```powershell
Get-ChildItem -Path <OLD_PROJECT_ROOTS> -Recurse -File -ErrorAction SilentlyContinue |
  Where-Object { $_.Extension -in '.yaml','.yml','.json','.py','.sh','.ps1','.pt','.pth','.ckpt','.log' } |
  Select-Object FullName,Length,LastWriteTimeUtc |
  Export-Csv reports\archival\old_file_inventory.csv -NoTypeInformation
```

搜索关键字：

```powershell
Get-ChildItem -Path <OLD_PROJECT_ROOTS> -Recurse -File -ErrorAction SilentlyContinue |
  Select-String -Pattern 'step400|InternVideo2|BEATs|CLAP|early.stop|n_mels|hop_length|projection_dim|lambda_orth|F1@0.5' |
  Out-File reports\archival\keyword_hits.txt
```

还要检查：

- W&B run config；
- TensorBoard hparams；
- shell/PowerShell history；
- Slurm 脚本；
- 原服务器 outputs；
- `best.pt` / `last.pt` 内嵌 config；
- 合作者本地目录；
- 论文作图 CSV/JSON；
- rebuttal/实验记录。

### 15.2 安全 checkpoint inventory

新增：

```text
scripts/inspect_historical_checkpoint.py
```

只读取可信本地 checkpoint，输出：

- 顶层 keys；
- config；
- model parameter names/shapes；
- optimizer/scheduler state 类型；
- epoch/global step；
- hash。

不要把完整参数或私人路径提交进 Git。

### 15.3 无法恢复时的批准流程

每个未恢复事实必须写：

```yaml
status: approved_reconstruction_assumption
selected_value: ...
evidence:
  - camera-ready section/table
alternatives_considered:
  - ...
risk: ...
approved_by: user
```

此时 `claim_level` 自动降为：

```text
paper_specified_reconstruction
```

---

# Part E：教师身份与 checkpoint 锁定

## 16. 不得直接根据名字下载“最像的 checkpoint”

当前存在明确冲突：

```text
config 声明：InternVideo2-Base / CLIP-B14
wrapper 实际 import：InternVideo2_CLIP_small
```

在这个冲突解决前，禁止全量视觉教师导出。

### 16.1 teacher lock 每个教师必须记录

```yaml
repository_url:
repository_commit:
working_tree_clean:
module_path:
imported_class:
checkpoint_source_url_or_archive:
checkpoint_filename:
checkpoint_bytes:
checkpoint_sha256:
checkpoint_top_level_keys:
pretrained_or_finetuned:
input_preprocessing:
output_dim:
determinism_tolerance:
```

InternVideo2 还需要三个 checkpoint 分别记录：

- vision；
- text；
- extra CLIP。

### 16.2 identity inspection

```powershell
python scripts/inspect_teacher_identity.py `
  --config configs/ov_orthkd_mm26_repro.local.yaml `
  --source-manifest data/ov_ave_smoke/source/train_source.jsonl `
  --output reports/teachers/teacher_identity.json `
  --fail-on-unresolved `
  --repeat 2
```

必须确认：

- wrapper 声明类与实际 import 类一致；
- checkpoint key 与类相符；
- feature dim：视觉 512、音频 768、文本 1024，或由归档证据修正配置；
- 同输入重复输出稳定；
- 无 NaN/Inf；
- 不导出 audio logits。

### 16.3 teacher repos/checkpoints 不提交 Git

只提交：

- URL；
- commit；
- 文件名；
- size；
- SHA256；
- license/来源 receipt。

---

# Part F：真实教师工件导出

## 17. 导出顺序

严格按：

```text
单教师单样本
→ 三教师单样本
→ smoke train/val/test
→ 重复导出一致性
→ full train
→ full val
→ full test
→ full artifact audit
```

### 17.1 smoke 输出

```text
data/teacher_cache/mm26_smoke/
reports/teachers/smoke_export_summary.json
reports/teachers/smoke_repeatability.json
```

### 17.2 full 输出

```text
data/teacher_cache/mm26/train/...
data/teacher_cache/mm26/val/...
data/teacher_cache/mm26/test/...
```

### 17.3 导出要求

- 每条 array 同目录 `.tmp` → flush/fsync → `os.replace`；
- 保存后重新 load，验证 shape/finite/hash；
- resume 只接受 source manifest hash、teacher lock hash、工件 hash 都一致的 receipt；
- 任何 stale receipt 立即停止；
- 最终 manifest 只在全 split 成功后发布；
- 计算 canonical tree hash；
- 记录总字节数与文件数。

### 17.4 exported manifest

建议：

```text
data/ov_ave/exported/train.jsonl
data/ov_ave/exported/val.jsonl
data/ov_ave/exported/test.jsonl
```

config 最终指向 exported manifest，不直接指 source manifest。

### 17.5 full audit

```powershell
python scripts/audit_mm26_reproduction.py `
  --config configs/ov_orthkd_mm26_repro.local.yaml `
  --train-manifest data/ov_ave/exported/train.jsonl `
  --val-manifest data/ov_ave/exported/val.jsonl `
  --test-manifest data/ov_ave/exported/test.jsonl `
  --path-root . `
  --stage exported `
  --artifact-scan full `
  --expected-segments auto `
  --output-json reports/mm26_exported_artifact_audit.json `
  --fail-on-warning
```

---

# Part G：真实一步 preflight 与最终运行门

## 18. 真实 preflight

本阶段最多执行一次正式数据的一步优化：

```powershell
python scripts/preflight_ov_orthkd.py `
  --config configs/ov_orthkd_mm26_repro.local.yaml `
  --output-dir outputs/r2_real_preflight `
  --probe-samples 8 `
  --max-eval-batches 1 `
  --real-data `
  --optimizer-steps 1
```

必须验证：

- 真实数据，不是 mock；
- batch 中 seen/unseen 字段正确；
- $T$ 与 lock 一致；
- student 输入 shape；
- 三种教师工件 shape；
- 所有 loss finite；
- forward/backward/optimizer step 完成；
- 所有应有参数收到梯度；
- disabled logit losses 精确为 0；
- checkpoint 保存、恢复、再 forward；
- 峰值显存；
- 无正式 AP/F1 结果输出。

输出：

```text
reports/runtime/r2_real_preflight.json
```

---

## 19. 最终 readiness receipt

新增：

```text
scripts/build_conference_readiness_receipt.py
```

它读取所有 lock/audit/preflight，生成：

```text
reports/mm26_conference_readiness.json
reports/R2_CONFERENCE_REPRODUCTION_READINESS_REPORT.md
```

`READY_TO_IMPLEMENT_CONFERENCE_EXPERIMENTS` 必须同时满足：

- 本任务所有 P0/P1 测试通过；
- 官方数据已下载、hash、解压、layout audit；
- source manifest 0 error/0 warning；
- 九项历史事实已 resolved，或用户批准为 reconstruction assumption；
- claim level 明确；
- teacher lock ready；
- real teacher smoke ready；
- full export 24,800 条；
- exported audit 0 error/0 warning；
- cache root SHA 非空；
- evaluator parity ready；
- real one-step preflight ready；
- exact resume test ready；
- `full_run_blocked` 仍保持 true，等待下一轮人工审计后再解除。

否则最终状态必须是：

```text
BLOCKED_BEFORE_CONFERENCE_EXPERIMENTS
```

---

# Part H：下一轮要实现的原会议实验矩阵

## 20. 第一研究阶段严格是会议复现，不是扩刊

下一轮实验代码应优先覆盖：

### 20.1 基础进展链

```text
Student-only
Visual feature only
Full OV-OrthKD
```

目标用于复现论文 Table 4：

```text
Student-only:        AP 0.714, AUROC 0.612, F1@0.5 0.523, Calib F1 0.719
Visual feature only: AP 0.778, AUROC 0.701, F1@0.5 0.568, Calib F1 0.774
OV-OrthKD:           AP 0.816, AUROC 0.750, F1@0.5 0.596, Calib F1 0.781
```

这些值只能作为对照目标，不能写入生成结果。

### 20.2 监督放置消融

```text
Visual only
Visual + Orth.
Decision KD
Symmetric transfer
w/o text
OV-OrthKD full
```

论文目标：

```text
Visual only:       U-AP 0.492, AP 0.778
Visual + Orth.:    U-AP 0.488, AP 0.777
Decision KD:       U-AP 0.501, AP 0.745
Symmetric transfer:U-AP 0.505, AP 0.737
w/o text:          U-AP 0.086, AP 0.485
OV-OrthKD:         U-AP 0.584, AP 0.816
```

### 20.3 注意：这些变体不能只靠随意改 loss weight

下一轮应建立显式 variant registry：

```text
configs/experiments/mm26/
  student_only.yaml
  visual_feature_only.yaml
  visual_plus_orth.yaml
  decision_kd.yaml
  symmetric_transfer.yaml
  without_text.yaml
  ov_orthkd_full.yaml
```

每个配置必须记录：

- 路径结构；
- 定位头读取位置；
- 每个教师进入的路径；
- loss 权重；
- 是否使用 audio logits；
- 是否使用文本对齐；
- evaluator；
- seed；
- base config hash。

`Decision KD` 和 `Symmetric transfer` 的精确定义必须先从历史事实恢复；禁止用“看起来合理”的实现替代后直接对比论文数字。

### 20.4 seed 策略

历史 seed set 未恢复时：

- 首先跑锁定的单 seed reconstruction；
- 再增加独立 robustness seeds，明确标记为新增实验；
- 不得把新 seed 平均值说成论文原值。

建议新增 robustness：

```text
42, 43, 44
```

但这不是原会议 seed 声明。

### 20.5 实验顺序

正式运行顺序：

```text
1. Student-only 单 seed
2. Visual feature only 单 seed
3. Full OV-OrthKD 单 seed
4. 检查进展链是否合理
5. Table 3 六个消融
6. seen/unseen 与 calibrated threshold
7. 多 seed robustness
8. orth weight 五 seed sweep
9. role swap / alt teachers / corruption / transfer / efficiency
```

不要一开始并行跑所有配置。先建立最短正确闭环。

---

# Part I：Codex 实施顺序与禁止事项

## 21. 建议分支和提交

```bash
git checkout repro/r1-data-teacher-readiness
git pull --ff-only
git rev-parse HEAD
# 必须为 6e4ea32c8e3cd84c07bc45d6e3ea3528d3fa9986

git checkout -b repro/r2-conference-reproduction-readiness
```

建议拆为清晰提交：

```text
fix: close seen-unseen manifest contract
fix: enforce canonical readiness locks
feat: add official-compatible OV-AVEL metrics
fix: freeze source preprocessing contract
fix: make teacher export scalable and split-safe
fix: exact resume and deterministic construction
feat: add data layout and safe extraction tooling
feat: lock teachers evaluator and preprocessing
feat: complete real artifact readiness evidence
```

## 22. 禁止事项

本阶段禁止：

- 实现自适应监督路由；
- 实现选择性正交；
- 修改会议主线以追求更高分；
- 随机选择教师 checkpoint；
- 使用第三方数据镜像；
- 通过 `--allow-blocked-reproduction` 生成会议结果；
- 未锁定 evaluator 时只报告最有利 F1；
- 将 10 段标签插值/复制成 16 段；
- 将单张 png 复制 8 次后默认称为历史 InternVideo 输入；
- 在数据或工件不完整时启动完整 epoch；
- 把 mock preflight 写成真实结果。

---

# Part J：测试与双重检查

## 23. 必须运行的测试矩阵

```powershell
python -m pip check
python -m compileall -q src scripts tests
python -m pytest -q
python scripts/verify_cuda_runtime.py --matrix-size 2048 --warmup 2 --iterations 5
python scripts/smoke_test.py
```

新增定向测试：

```powershell
python -m pytest -q tests/test_r2_split_type_contract.py
python -m pytest -q tests/test_r2_canonical_readiness_gate.py
python -m pytest -q tests/test_r2_ovavel_metrics_parity.py
python -m pytest -q tests/test_r2_preprocessing_contract.py
python -m pytest -q tests/test_r2_teacher_export_scaling.py
python -m pytest -q tests/test_r2_exact_epoch_resume.py
python -m pytest -q tests/test_r2_model_construction_state.py
```

## 24. 第一轮自检：代码逻辑

Codex 必须逐项回答：

- builder 生成的 val/test seen/unseen 数量是否精确？
- dataset、audit、evaluation 是否共用同一个 split helper？
- 改一个 `full_run_blocked` 布尔值能否绕过锁？必须不能。
- fingerprint 是否真的包含五个 lock 和 artifact audit？
- F1 输出是否使用完整名字？
- metric parity 是否锁定官方 evaluator commit/SHA？
- manifest 是否不再默认生成未锁定的 JPEG mel？
- teacher cache 是否带 split？
- receipt 写入是否不再 O(N²)？
- resume 是否恢复 early-stop counter？
- canonical persistent workers 是否关闭？
- backbone feature probe 是否不改变 BN buffers？

## 25. 第二轮自检：真实工件证据

- 官方 archive SHA 是否非空？
- 7-Zip 测试是否通过？
- layout audit 是否全量？
- source manifest 是否 24,800 条？
- 九项事实是否都有 resolved/approved evidence？
- teacher checkpoint SHA 是否非空且实际匹配？
- smoke repeatability 是否通过？
- full teacher export 是否 24,800 条？
- exported audit 是否 0/0？
- cache root hash 是否非空？
- real preflight 是否恰好一批次、一步 optimizer？
- 是否没有正式训练结果？

---

## 26. 最终交付物

Codex 完成本任务后必须提交：

```text
reports/R2_CONFERENCE_REPRODUCTION_READINESS_REPORT.md
reports/mm26_conference_readiness.json
reports/data/official_archive_extraction_receipt.json
reports/data/preprocessed_layout_discovery.json
reports/mm26_source_manifest_audit.json
reports/mm26_exported_artifact_audit.json
reports/teachers/teacher_identity.json
reports/teachers/smoke_repeatability.json
reports/runtime/r2_real_preflight.json
configs/locks/mm26_data_lock.yaml
configs/locks/mm26_archival_facts.yaml
configs/locks/mm26_teacher_lock.yaml
configs/locks/mm26_preprocessing_lock.yaml
configs/locks/mm26_evaluator_lock.yaml
```

并返回：

```text
commit SHA
git diff --stat
pytest 总数和退出码
官方 archive SHA256
train/val/test manifest SHA256
五个 lock SHA256
三个/五个教师 checkpoint SHA256
teacher cache root SHA256
source/exported audit 状态
real preflight 状态
最终 READY/BLOCKED 状态
```

---

## 27. 可直接交给 Codex 的总指令

```text
请完整阅读 MM26_OVORTHKD_R2_CONFERENCE_REPRODUCTION_GATE_AND_BASELINE_TASK.md。

以提交 6e4ea32c8e3cd84c07bc45d6e3ea3528d3fa9986 为唯一 R2 起点，
创建 repro/r2-conference-reproduction-readiness 分支。

本阶段只服务于原 ACM MM 2026 OV-OrthKD 会议论文复现，禁止实现期刊扩展。

严格按任务书完成：
1. 修复 seen/unseen manifest 合同；
2. 建立不可由单个布尔值绕过的 canonical readiness gate；
3. 区分并锁定 micro F1、官方 segment F1、event F1 和 calibrated F1；
4. 在官方数据布局发现前停止自定义 spectrogram 假设；
5. 修复教师导出 O(N²) receipt 和跨 split 覆盖；
6. 修复 exact resume、persistent workers、CUBLAS 初始化和 BN probe；
7. 在用户手动提供官方 SharePoint 压缩包后完成 hash、safe extract、layout audit 和 manifest；
8. 恢复九项历史事实，无法恢复时只能在用户明确批准后作为 paper-specified reconstruction；
9. 锁定精确 InternVideo2/BEATs/CLAP repo、class、checkpoint 和 SHA256；
10. 完成真实 smoke、全量原子导出、full audit 和一次真实一步 preflight；
11. 保持 full_run_blocked=true，等待下一轮人工审计；
12. 不启动完整会议训练。

最终状态只能是 READY_TO_IMPLEMENT_CONFERENCE_EXPERIMENTS 或
BLOCKED_BEFORE_CONFERENCE_EXPERIMENTS。

完成后提交干净 commit，并返回任务书第 26 节要求的所有证据。
```

---

# 28. 最终原则

第一研究阶段的目标不是“先把扩刊代码写出来再说”，而是：

> **先建立一条可验证、可审计、可以解释与会议数字差异来源的原会议复现链。**

只有 Student-only → Visual feature only → Full OV-OrthKD 的基础进展链成立，并且 Table 3 监督放置消融能被合理复现后，才进入 VP-AdaOrthKD 扩刊工程。否则扩刊任何提升都无法判断来自新方法，还是来自数据、教师、指标或旧会议实现偏差。
