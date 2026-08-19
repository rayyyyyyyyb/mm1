# OV-OrthKD / ACM MM 2026 原会议复现：R1 官方数据、历史事实、教师工件与实验前就绪任务书

> 目标仓库：`https://github.com/rayyyyyyyyb/mm1`
> 起始分支：`repro/r0-paper-faithfulness`
> 起始提交：`d8e681b2d3597f0f089ee8f0b42ef12466ffb599`
> 建议新分支：`repro/r1-data-teacher-readiness`
> 当前目标：完成**所有正式学生训练之前**的工程修正、官方数据准备、历史事实恢复、教师身份锁定、真实教师工件导出与全量审计。
> 明确边界：本轮不启动正式学生训练，不跑论文结果，不实现 VP-AdaOrthKD 扩刊机制。

---

# 0. 给 Codex 的直接执行指令

请把本文件作为本轮唯一主任务书，先完整阅读，再执行。不要只下载数据，也不要只修改一两个函数。本轮最终必须形成一条完整的“数据与教师证据链”，使下一轮能够在不猜参数、不补假工件、不混淆 mock 与正式结果的前提下直接进入会议版实验实现与训练。

必须遵守：

1. 从提交 `d8e681b2d3597f0f089ee8f0b42ef12466ffb599` 创建新分支；不得在 R0 分支上继续堆叠未审计修改。
2. 先运行并记录 R0 的现有测试矩阵，确认基线仍为 `60 passed` 或解释测试数量变化。
3. 修复本文列出的 R0 后置工程风险，所有修复必须先写失败测试再实现。
4. 下载并冻结官方 OV-AVEBench 元数据和预处理数据；所有外部资源必须记录来源、版本、字节数和 SHA256。
5. 不允许把官方元数据中的 `close/open` 原样当作最终评价分组；必须明确映射为 `seen/unseen` 并通过精确计数测试。
6. 不允许静默重采样时间轴，不允许把单条教师特征广播到全部片段，不允许用 basename 覆盖路径层级。
7. 系统化恢复六项 `BLOCKED_ARCHIVAL_FACTS`；没有直接证据时必须保持 unresolved，禁止按“最可能”填写。
8. 在确切教师类、上游仓库提交、checkpoint 名称和 checkpoint SHA256 被锁定之前，不得启动真实教师全量导出。
9. 教师身份锁定后，先做单样本和小型跨 split 真实 smoke，再进行可恢复、原子写入的全量教师工件导出。
10. 全量导出后必须执行 full artifact audit；任何缺失、维度不符、NaN/Inf、路径碰撞或 teacher-lock hash 不一致都必须非零退出。
11. 本轮最多运行一次真实数据的 forward/backward preflight；禁止运行正式 epoch、报告 AP/F1，或把 preflight 数字写成论文结果。
12. canonical 配置在本轮结束时仍保持 `full_run_blocked: true`。即便六项事实全部恢复，也只生成“建议解锁配置”，由下一轮审计批准后再正式解锁。
13. 最后生成 `reports/R1_DATA_TEACHER_READINESS_REPORT.md`，提交一个干净 commit，并返回 commit SHA、完整测试命令、退出码、数据锁、教师锁、缓存根哈希与仍未解决项。

建议开工命令：

```powershell
# 在仓库根目录执行
$ErrorActionPreference = "Stop"

git fetch --all --tags --prune
git checkout repro/r0-paper-faithfulness
git pull --ff-only
$head = (git rev-parse HEAD).Trim()
if ($head -ne "d8e681b2d3597f0f089ee8f0b42ef12466ffb599") {
    throw "Unexpected R0 head: $head"
}

git checkout -b repro/r1-data-teacher-readiness
python -m pip check
python -m compileall -q src scripts tests
python -m pytest -q
python scripts/verify_cuda_runtime.py --matrix-size 2048 --warmup 2 --iterations 5
```

若目标分支已经存在，禁止删除或 force reset；先记录其 SHA 和状态，再决定继续现有分支还是创建带日期后缀的新分支。

---

# 1. 对 R0 的审计结论

## 1.1 总体判定

R0 可以判定为：

> **工程加固阶段通过，但只通过 R0 本身；尚未达到正式会议复现实验就绪状态。**

R0 已经正确完成以下主体要求：

- camera-ready 显式三路径与 legacy 协作实现分离；
- camera-ready 定位头读取 decision projection；
- 文本损失改为 `(cos+1)/2` 后的 probability BCE，并解决 CUDA AMP 下的数值兼容；
- 删除伪造的弱音频 logits；
- 关闭 logit KD 时不要求不存在的 logits；
- strict artifact、路径根目录和维度检查；
- 确定性 RNG、worker generator、CUDA deterministic SDPA；
- best/last/history/resume、结构化预测、seen/unseen 与 validation-calibrated threshold；
- full-run fail-closed、非 canonical override 标记；
- teacher identity 静态审计、mock artifact audit、RTX 5090/cu128 运行证据；
- 未越界实现扩刊的自适应路由。

R0 提交报告中记录的最终矩阵为 `60 passed`，且两次 5090 CUDA preflight 的关键数值完全一致。本轮可以把该提交作为新的工程基线，但不能把报告里的 mock AP/F1 当作论文复现结果。

## 1.2 R0 仍然故意保留的阻塞项

以下六项仍是正式实验的硬阻塞：

1. 官方标签 $T=10$ 与论文实现表“16 temporal segments”的关系；
2. 精确 InternVideo2 类和三个 checkpoint；
3. “step400 schedule”、gamma/interval 和 early-stop patience；
4. 学生 pretrained 初始化与精确训练增强；
5. 视觉 feature $L_2$ 在 feature 维度上使用 sum 还是 mean；
6. 历史 fusion 是论文加法 + `TransformerLayer`，还是当前 concat-MLP token fusion，及 validity bits 的作用。

这些不是普通超参数调优问题，而是“到底复现哪一份历史实现”的事实问题。

---

# 2. 本轮新增发现：问题、级别与对应修改

| 级别 | 问题 | 风险 | 本轮修改 |
|---|---|---|---|
| P0 | `seq_len > max_segments` 时数据集可静默均匀抽样 | 真实时间轴被悄悄改变，报告仍声称未重采样 | 增加 `temporal_overflow_policy`；canonical 固定为 `error` |
| P0 | segment teacher tensor 允许单行并广播到 $T$ | clip-level 工件可伪装成 segment-level 教师监督 | segment feature/logit 必须严格为 `[T,D]` 或 `[T,1]`，禁止广播 |
| P0 | artifact override 只保留 basename | 不同 split/category 的同名文件可能碰撞并加载错教师目标 | 以 source root 的相对路径重映射，无法安全映射时直接报错 |
| P0 | 官方 `cls_type` 是 `close/open`，而评价使用 `seen/unseen` | 分组可全部落入 unknown，或开放类统计错误 | 显式 `close -> seen`、`open -> unseen`，加入精确分组计数测试 |
| P0 | eval-only 仍可能先构造 `UNRESOLVED` scheduler | 已有 checkpoint 也无法在 canonical 配置下纯评价 | train/evaluate/preflight 分离；eval-only 不构造 optimizer/scheduler |
| P1 | resume 未冻结并恢复完整 RNG/DataLoader generator 状态 | 从头可重复，但断点恢复后顺序可能变化 | checkpoint 保存/恢复 Python、NumPy、CPU/CUDA RNG 与 loader generators |
| P1 | resume 缺严格配置、manifest、teacher-lock 兼容检查 | 可能把不同实现或不同教师缓存续接到同一运行 | 保存 reproduction fingerprint，默认不兼容即拒绝 |
| P1 | runtime dataset 对 labels/数组 finite 的防线不够完整 | audit 通过后文件被替换或损坏时可能晚发现 | 加二值、shape、NaN/Inf、空数组检查 |
| P2 | PIL 文件未统一使用 context manager | 全量多 worker 读取可能积累文件句柄 | `with Image.open(...)` 后 `.copy()` |
| P2 | canonical config 中 `confidence_weighting: true` 虽当前权重为 0 | 以后打开 analysis logit KD 时可能意外偏离论文公式 | camera-ready 默认改为 false，分析配置单独显式开启 |

注意：前五项必须在正式数据或教师工件进入仓库流程前修复；不能把它们留到训练后再排查。

---

# 3. R1 的冻结范围

本轮允许：

- 数据读取、安全、resume/eval-only、导出原子性和审计代码修改；
- 官方数据及第三方教师仓库/checkpoint 下载；
- source manifest、spectrogram、教师工件生成；
- 单样本、小批量、全量 artifact audit；
- 一次真实数据的一批 forward/backward preflight；
- 配置锁、数据锁、教师锁、环境锁、运行报告。

本轮禁止：

- 正式学生训练；
- 任何以 epoch 为单位的真实数据训练；
- 调 loss weight、阈值、scheduler 来追论文数字；
- 在验证/测试集上选训练超参数；
- 实现 VP-AdaOrthKD、可靠性路由器、OOF probe 或选择性正交化；
- 用“相近”checkpoint 替代未恢复的历史 checkpoint；
- 修改 camera-ready/legacy 方法语义来绕开归档事实；
- 将 raw data、checkpoint、teacher cache 提交到 Git。

---

# 4. 先修复 R0 后置工程风险

## 4.1 禁止 canonical 路径静默时间重采样

在 `src/data/ov_avel_dataset.py` 中增加明确策略：

```python
from typing import Literal

TemporalOverflowPolicy = Literal["error", "uniform"]


def select_temporal_indices(
    *,
    seq_len: int,
    max_segments: int,
    policy: TemporalOverflowPolicy,
    record_id: str,
) -> list[int]:
    if seq_len <= 0:
        raise ValueError(f"Record {record_id!r} has no temporal segments")
    if max_segments <= 0:
        raise ValueError(f"max_segments must be positive, got {max_segments}")
    if seq_len <= max_segments:
        return list(range(seq_len))

    if policy == "error":
        raise ValueError(
            f"Record {record_id!r} has {seq_len} segments, exceeding "
            f"max_segments={max_segments}. Canonical reproduction forbids "
            "implicit temporal resampling."
        )
    if policy != "uniform":
        raise ValueError(f"Unsupported temporal_overflow_policy: {policy!r}")

    indices = np.rint(
        np.linspace(0, seq_len - 1, num=max_segments, dtype=np.float64)
    ).astype(np.int64)
    if len(np.unique(indices)) != max_segments:
        raise RuntimeError(
            f"Uniform temporal selection produced duplicate indices for {record_id!r}: "
            f"{indices.tolist()}"
        )
    return indices.tolist()
```

配置增加：

```yaml
data:
  temporal_overflow_policy: "error"
```

要求：

- `ov_orthkd_mm26_repro.yaml` 必须为 `error`；
- mock/smoke 如需 `uniform`，必须在输出报告中写 `noncanonical_temporal_resampling: true`；
- audit 报告的 `resampling_performed_by_dataset` 不能写死，必须根据实际策略与实际记录统计生成。

## 4.2 禁止 segment teacher 工件广播

segment feature 的 canonical 形状必须严格为：

```text
strong_teacher_features: [T, 512]
weak_teacher_features:   [T, 768]
strong_teacher_logits:   [T] 或 [T, 1]，仅分析项
weak_teacher_logits:     [T] 或 [T, 1]，默认不存在且权重为 0
```

不得把 `[1,D]` 或 `[D]` 广播成 `[T,D]`。

推荐新增 helper：

```python
def validate_segment_feature_array(
    array: np.ndarray,
    *,
    expected_segments: int,
    expected_dim: int,
    field_name: str,
    record_id: str,
) -> np.ndarray:
    value = np.asarray(array)
    if value.ndim != 2:
        raise ValueError(
            f"Record {record_id!r} field {field_name!r} must have shape "
            f"[T,D], got {value.shape}"
        )
    expected = (expected_segments, expected_dim)
    if tuple(value.shape) != expected:
        raise ValueError(
            f"Record {record_id!r} field {field_name!r} expected {expected}, "
            f"got {tuple(value.shape)}; singleton broadcasting is forbidden"
        )
    if not np.isfinite(value).all():
        raise ValueError(
            f"Record {record_id!r} field {field_name!r} contains NaN or Inf"
        )
    return value.astype(np.float32, copy=False)


def validate_segment_logit_array(
    array: np.ndarray,
    *,
    expected_segments: int,
    field_name: str,
    record_id: str,
) -> np.ndarray:
    value = np.asarray(array)
    if value.ndim == 1 and value.shape == (expected_segments,):
        value = value[:, None]
    if value.ndim != 2 or value.shape != (expected_segments, 1):
        raise ValueError(
            f"Record {record_id!r} field {field_name!r} expected "
            f"[{expected_segments}] or [{expected_segments},1], got {value.shape}"
        )
    if not np.isfinite(value).all():
        raise ValueError(
            f"Record {record_id!r} field {field_name!r} contains NaN or Inf"
        )
    return value.astype(np.float32, copy=False)
```

文本 embedding 是另一种对象，可以接受 `[1024]`；如 wrapper 输出 `[1,1024]`，只允许显式 squeeze，不能沿时间轴广播后保存。

## 4.3 labels 与运行时有限值检查

```python
def validate_binary_labels(labels: object, *, record_id: str) -> np.ndarray:
    value = np.asarray(labels)
    if value.ndim != 1 or value.size == 0:
        raise ValueError(
            f"Record {record_id!r} labels must be a non-empty 1-D array, "
            f"got {value.shape}"
        )
    if not np.isfinite(value).all():
        raise ValueError(f"Record {record_id!r} labels contain NaN or Inf")
    if not np.all((value == 0) | (value == 1)):
        bad = np.unique(value[~((value == 0) | (value == 1))]).tolist()
        raise ValueError(
            f"Record {record_id!r} labels are not binary; invalid values={bad[:10]}"
        )
    return value.astype(np.float32, copy=False)
```

`np.load` 一律使用：

```python
np.load(path, allow_pickle=False)
```

## 4.4 修复 PIL 文件句柄

```python
def read_rgb_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB").copy()
```

不要返回仍依赖底层文件句柄的 lazy PIL 对象。

## 4.5 artifact override 必须保留相对层级

禁止：

```python
override_root / Path(original_path).name
```

推荐：

```python
def remap_path_under_root(
    original_path: Path,
    *,
    source_root: Path,
    target_root: Path,
) -> Path:
    source_root = source_root.resolve(strict=True)
    target_root = target_root.resolve(strict=False)
    original = original_path.resolve(strict=False)
    try:
        relative = original.relative_to(source_root)
    except ValueError as exc:
        raise ValueError(
            f"Cannot safely remap {original}; it is not under source root {source_root}"
        ) from exc
    candidate = (target_root / relative).resolve(strict=False)
    try:
        candidate.relative_to(target_root)
    except ValueError as exc:
        raise ValueError(f"Artifact remap escaped target root: {candidate}") from exc
    return candidate
```

配置改为：

```yaml
data:
  artifact_override:
    enabled: false
    source_root: null
    target_root: null
```

若现有命令只提供单一 override root，必须扩展为 source/target 两个根。无法恢复相对路径的旧 manifest 应 fail fast，不允许猜 basename。

## 4.6 冻结官方 `close/open -> seen/unseen` 映射

官方 CSV 当前字段是：

```text
split, cls_name, cls_type, vid_name
```

其中 `cls_type` 使用 `close/open`，不是 `seen/unseen`。source manifest builder 必须执行：

```python
_CLASS_TYPE_TO_SPLIT_TYPE = {
    "close": "seen",
    "open": "unseen",
}


def normalize_split_type(raw_value: str, *, record_id: str) -> str:
    key = raw_value.strip().lower()
    try:
        return _CLASS_TYPE_TO_SPLIT_TYPE[key]
    except KeyError as exc:
        raise ValueError(
            f"Record {record_id!r} has unsupported cls_type={raw_value!r}"
        ) from exc
```

必须加入真实元数据精确计数测试：

```text
总记录：24,800
train：13,182
val：5,798
 test：5,820

close/seen 类：46 类，共 16,497 条
open/unseen 类：21 类，共 8,303 条

train：seen 13,182；unseen 0
val：seen 1,651；unseen 4,147
test：seen 1,664；unseen 4,156
```

若当前 builder 已经正确映射，不要重复改逻辑；保留现有实现并补上述 regression test。

## 4.7 eval-only 不得依赖 scheduler

把训练入口分为三种 operation：

```text
train
evaluate
preflight
```

伪代码：

```python
operation = "evaluate" if args.eval_only else "train"
validate_repro_config(config, operation=operation, output_dir=output_dir)

loaders = build_dataloaders(...)
model = build_model(...)
loss_fn = build_loss(...)

if args.eval_only:
    checkpoint = load_checkpoint_for_evaluation(...)
    validate_checkpoint_fingerprint(...)
    save_evaluation_artifacts(...)
    return 0

optimizer = build_optimizer(...)
scheduler = build_scheduler(...)  # 只在 train 分支执行
```

评价 historical checkpoint 时，`scheduler.type: UNRESOLVED` 不应阻断纯评价；但 checkpoint 必须有完整 fingerprint，且 unresolved 方法事实不得被评价入口自动改写。

## 4.8 checkpoint 恢复完整随机状态

推荐：

```python
def capture_rng_state(loader_generators: dict[str, torch.Generator]) -> dict[str, object]:
    return {
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch_cpu": torch.get_rng_state(),
        "torch_cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
        "loader_generators": {
            name: generator.get_state()
            for name, generator in loader_generators.items()
        },
    }


def restore_rng_state(
    state: dict[str, object],
    loader_generators: dict[str, torch.Generator],
) -> None:
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch_cpu"])
    if torch.cuda.is_available():
        cuda_states = state.get("torch_cuda", [])
        if len(cuda_states) != torch.cuda.device_count():
            raise RuntimeError(
                "CUDA RNG state count differs from current device count; "
                "canonical resume is not safe"
            )
        torch.cuda.set_rng_state_all(cuda_states)
    for name, generator in loader_generators.items():
        if name not in state["loader_generators"]:
            raise KeyError(f"Missing DataLoader generator state: {name}")
        generator.set_state(state["loader_generators"][name])
```

本轮只承诺 epoch-boundary exact resume。若中途停止在一个 epoch 内，不得声称 bitwise resume，除非额外保存 sampler/batch cursor。

## 4.9 checkpoint reproduction fingerprint

新增 canonical JSON 子集并计算 SHA256：

```text
implementation_mode
path_mode
model/backbone names
fusion_dim / projection_dim / temporal layers/heads
loss formula modes and weights
pretrained/augmentation
scheduler and early stopping
manifest SHA256
source data lock SHA256
teacher lock SHA256
teacher artifact index root SHA256
Git commit and dirty status
```

resume 默认比较 fingerprint；不一致立即报错。可以提供显式：

```text
--allow-incompatible-resume
```

但一旦使用必须写：

```text
NON_CANONICAL_INCOMPATIBLE_RESUME.txt
```

并禁止把该运行列入正式结果。

## 4.10 canonical 配置清理

在 camera-ready 默认配置中：

```yaml
loss:
  confidence_weighting: false
```

若要研究 analysis-only visual logit KD，创建独立配置，不在主复现配置中暗中启用 confidence weighting。

---

# 5. 本轮必须新增的测试

至少新增：

```text
tests/test_r1_dataset_integrity.py
tests/test_r1_checkpoint_resume.py
tests/test_r1_official_metadata.py
tests/test_r1_teacher_lock.py
tests/test_r1_atomic_export.py
```

必须覆盖：

1. `seq_len > max_segments` 且 canonical policy 为 `error` 时抛错；
2. 显式 `uniform` 时索引单调、唯一、数量正确，并被标记 noncanonical；
3. `[1,D]` segment teacher feature 不能广播；
4. `[T,D]` feature 正常；
5. `[T]` 与 `[T,1]` logit 正常；
6. NaN/Inf teacher artifact 立即失败；
7. 非二值、空 labels 立即失败；
8. 两个相同 basename、不同相对目录的 artifact 不碰撞；
9. path traversal 不能逃逸 override root；
10. `close/open` 精确映射为 `seen/unseen`；
11. official metadata 精确 split/class/group 计数；
12. eval-only 不调用 scheduler builder；
13. checkpoint fingerprint 不匹配默认拒绝；
14. epoch-boundary resume 与 uninterrupted run 的 batch ID、loss、参数完全一致；
15. 原子写入中断后正式目标文件不存在或仍保持旧完整版本；
16. teacher-lock hash 变化会使已有 artifact cache 失效；
17. full export manifest 只有全部成功后才从 `.partial` 原子发布。

正式测试中不要依赖当前工作目录、互联网或真实大 checkpoint；用临时目录和小数组构造。

---

# 6. Windows RTX 5090 环境复核

R0 已在 Windows 5090 上建立 cu128 环境。本轮不要重装 torch，先验证：

```powershell
python --version
python -m pip check
python -m pip show torch torchvision torchaudio
python scripts/verify_cuda_runtime.py --matrix-size 2048 --warmup 2 --iterations 5
nvidia-smi
```

把输出保存到：

```text
reports/runtime/r1_python.txt
reports/runtime/r1_pip_check.txt
reports/runtime/r1_cuda_runtime.json
reports/runtime/r1_nvidia_smi.txt
```

第三方教师依赖安装前后都必须重新执行以上矩阵。禁止让 BEATs、CLAP 或 InternVideo 的 requirements 自动降级/替换当前 PyTorch。

---

# 7. 官方元数据下载与版本锁定

## 7.1 克隆官方元数据仓库

```powershell
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force external, data\downloads, data\raw\ov_avebench | Out-Null

if (-not (Test-Path external\OV-AVEL\.git)) {
    git clone --depth 1 https://github.com/jasongief/OV-AVEL.git external\OV-AVEL
}

$officialSha = (git -C external\OV-AVEL rev-parse HEAD).Trim()
$officialStatus = git -C external\OV-AVEL status --porcelain
if ($officialStatus) { throw "Official OV-AVEL checkout is dirty" }

Copy-Item external\OV-AVEL\meta_anno_files\released_ovavel_dataset_anno.json `
    data\raw\ov_avebench\released_ovavel_dataset_anno.json -Force
Copy-Item external\OV-AVEL\meta_anno_files\ovave_dataset_meta.csv `
    data\raw\ov_avebench\ovave_dataset_meta.csv -Force

Get-FileHash data\raw\ov_avebench\released_ovavel_dataset_anno.json -Algorithm SHA256
Get-FileHash data\raw\ov_avebench\ovave_dataset_meta.csv -Algorithm SHA256
```

不要只记录“main”；必须记录 `$officialSha`。生成：

```text
reports/data/official_metadata_receipt.json
```

字段至少包括：

```json
{
  "upstream_repository": "jasongief/OV-AVEL",
  "upstream_commit": "...",
  "downloaded_at_utc": "...",
  "files": [
    {"path": "...", "bytes": 0, "sha256": "..."}
  ]
}
```

## 7.2 元数据先验审计

在下载大数据之前先运行：

```powershell
python scripts/audit_official_ov_avebench_metadata.py `
  --meta-csv data/raw/ov_avebench/ovave_dataset_meta.csv `
  --annotation-json data/raw/ov_avebench/released_ovavel_dataset_anno.json `
  --output-json reports/data/official_metadata_audit.json `
  --output-md reports/data/official_metadata_audit.md `
  --fail-on-error
```

脚本必须检查：

- CSV 精确 24,800 条数据记录；
- split 精确为 train/val/test；
- `vid_name` 全局唯一；
- 67 类，close 46 类，open 21 类；
- 精确 split/group 计数；
- annotation key 与 CSV `vid_name` 一一对应；
- 每条 labels 为一维二值序列；
- label 长度直方图；
- positive segment 数直方图；
- query/category 非空；
- train 中不存在 open/unseen 类；
- annotation 中不存在 CSV 外孤儿记录。

注意：不要使用 `wc -l` 作为 CSV 行数的唯一依据，因为文件末尾换行会影响结果；使用标准 CSV 解析器。

---

# 8. 官方预处理数据下载

## 8.1 只使用仓库内已记录的官方链接

先从当前仓库 README 和刚锁定的官方 OV-AVEL README 中提取下载说明：

```powershell
Select-String -Path README.md, external\OV-AVEL\README.md `
  -Pattern "preprocessed|SharePoint|OneDrive|raw video|download" `
  -Context 2,4
```

主复现首先下载**官方预处理视觉/音频包**。SharePoint/OneDrive 公共文件夹经常需要浏览器确认或逐文件下载，不要依赖未经验证的第三方镜像，也不要把登录 cookie/token 写进仓库。

建议：

1. 从已锁定 commit 的 `external/OV-AVEL/README.md` 复制官方预处理数据链接，并与当前仓库 README 的说明交叉核对；
2. 在远端 Windows 浏览器打开；
3. 下载到 `E:\OV-OrthKD-R1\downloads\official_preprocessed\`；
4. 不要直接解压到最终目录；先建立 receipt 和 archive listing。

若下载结果是多个 archive/文件夹，全部列入 receipt。不得因为文件名相似而覆盖。

## 8.2 下载 receipt

PowerShell：

```powershell
$DownloadRoot = "E:\OV-OrthKD-R1\downloads\official_preprocessed"
$files = Get-ChildItem $DownloadRoot -File -Recurse | Sort-Object FullName
if (-not $files) { throw "No downloaded files found under $DownloadRoot" }

$receipt = foreach ($file in $files) {
    $hash = Get-FileHash $file.FullName -Algorithm SHA256
    [pscustomobject]@{
        relative_path = $file.FullName.Substring($DownloadRoot.Length).TrimStart('\')
        bytes = $file.Length
        sha256 = $hash.Hash.ToLowerInvariant()
        last_write_time_utc = $file.LastWriteTimeUtc.ToString('o')
    }
}
$receipt | ConvertTo-Json -Depth 5 | Set-Content `
    reports\data\official_preprocessed_download_receipt.json -Encoding UTF8
```

另写 `reports/data/official_preprocessed_source.md`，只记录公开来源页、下载时间、是否需要浏览器交互；不要记录 cookie、临时授权 query 或账户信息。

## 8.3 解压前检查

若是 7z/zip/tar：

```powershell
7z t <archive-path>
7z l -slt <archive-path> | Set-Content reports\data\archive_listing.txt -Encoding UTF8
```

检查：

- archive 测试退出码为 0；
- 没有绝对路径；
- 没有 `..` 路径穿越；
- 没有两个 archive 向同一目标路径写不同内容；
- 文件扩展名和规模合理；
- 解压后仍有足够空间。

解压到 staging：

```powershell
$Stage = "E:\OV-OrthKD-R1\staging\ov_avebench_preprocessed"
New-Item -ItemType Directory -Force $Stage | Out-Null
7z x <archive-path> "-o$Stage"
```

不要使用含糊的 `mv *` 或 `Copy-Item -Force` 把多个根目录合并。

## 8.4 数据布局发现

新增：

```text
scripts/discover_ov_avebench_layout.py
```

执行：

```powershell
python scripts/discover_ov_avebench_layout.py `
  --root E:/OV-OrthKD-R1/staging/ov_avebench_preprocessed `
  --meta-csv data/raw/ov_avebench/ovave_dataset_meta.csv `
  --output-json reports/data/preprocessed_layout_discovery.json `
  --output-md reports/data/preprocessed_layout_discovery.md
```

报告必须包括：

- 每个 split 下 wav 数、视频目录数、PNG/JPG 数；
- 每个 clip 的 frame count 直方图；
- wav sample rate、声道数、时长的抽样与异常；
- CSV 记录中缺 visual/audio 的 ID；
- 数据中不属于 CSV 的孤儿 ID；
- category 路径命名与 CSV 字符串归一化规则；
- 大小写冲突；
- Windows 非法/规范化路径冲突；
- 是否存在重复文件内容；
- 实际建议的 `dataset_root`，但不得自动移动数据。

只有布局报告人工/下一步逻辑确认后，才建立稳定目录或 junction：

```text
data/raw/ov_avebench/ovave_dataset_preprocessed
```

原始下载和 staging 保持只读，避免后续脚本污染来源。

## 8.5 raw videos 是否必须下载

不要一开始盲目下载全部 raw videos。先回答：

1. 官方预处理视觉目录每个 1 秒 segment 有多少帧？
2. 历史 InternVideo2 导出是否每 segment 需要 8 个真实帧，还是从预处理帧重复/采样？
3. source manifest 是否保留 `segment_frame_groups`，还是只保留每 segment 中间帧？
4. 论文中的 16 fps、teacher `num_frames=8` 与当前预处理包如何对应？

若预处理包无法满足已恢复的历史 teacher 输入协议，才按照已锁定官方 OV-AVEL README 中的 raw-video 链接下载 raw video，并建立独立 receipt。不得悄悄复制一张 PNG 八次来冒充真实 8-frame 输入，除非历史实现证据明确如此。

---

# 9. source manifest 构建与输入预处理审计

## 9.1 先构建小型 source manifest

```powershell
python scripts/build_ov_avebench_source_manifests.py `
  --dataset-root data/raw/ov_avebench/ovave_dataset_preprocessed `
  --annotation-json data/raw/ov_avebench/released_ovavel_dataset_anno.json `
  --meta-csv data/raw/ov_avebench/ovave_dataset_meta.csv `
  --output-dir data/ov_ave_smoke/source `
  --spectrogram-dir data/generated/ov_ave_specs_smoke `
  --image-size 224 `
  --sample-rate 16000 `
  --n-mels 128 `
  --limit-per-split 8
```

必须先检查 24 条 smoke：

- train/val/test 均存在；
- seen/unseen 映射正确；
- labels 与所有 segment 路径长度一致；
- frame path 实际存在且可解码；
- wav 可读取；
- spectrogram 可读取；
- 相同输入重复构建时 source manifest 和生成 spectrogram hash 相同；
- builder 没有修改 source data；
- 没有 teacher artifact 字段被错误填成零路径。

## 9.2 冻结音频与频谱参数

source builder 必须把以下参数写入 manifest metadata/data lock，而不是只留在命令历史：

```text
sample_rate
segment duration / sample range
channel downmix rule
short audio pad rule
long audio crop rule
n_fft
win_length
hop_length
window
n_mels
f_min / f_max
power or magnitude
log transform / floor
normalization
spectrogram image conversion and channel replication
student image normalization
```

如果当前代码没有全部显式参数，先从历史实现恢复；恢复不到的项目列入新的 preprocessing block，不得让库默认值静默决定。

## 9.3 冻结视觉帧选择

source manifest 建议同时保留：

```json
{
  "segment_frame_paths": ["student-middle-frame-per-segment"],
  "segment_frame_groups": [["all-available-frames-for-segment"]],
  "frame_selection_policy": "...",
  "raw_frame_count": 0
}
```

若现有 schema 只支持 `segment_frame_paths`，在教师协议恢复前不得丢弃原始 frame group 信息。

## 9.4 全量构建

smoke 完全通过后：

```powershell
python scripts/build_ov_avebench_source_manifests.py `
  --dataset-root data/raw/ov_avebench/ovave_dataset_preprocessed `
  --annotation-json data/raw/ov_avebench/released_ovavel_dataset_anno.json `
  --meta-csv data/raw/ov_avebench/ovave_dataset_meta.csv `
  --output-dir data/ov_ave/source `
  --spectrogram-dir data/generated/ov_ave_specs `
  --image-size 224 `
  --sample-rate 16000 `
  --n-mels 128
```

随后：

```powershell
python scripts/audit_mm26_reproduction.py `
  --train-manifest data/ov_ave/source/train_source.jsonl `
  --val-manifest data/ov_ave/source/val_source.jsonl `
  --test-manifest data/ov_ave/source/test_source.jsonl `
  --path-root . `
  --stage source `
  --artifact-scan none `
  --expected-segments 10 `
  --fail-on-warning `
  --output-json reports/data/mm26_source_manifest_audit.json
```

若真实 annotation 的长度不是全部 10，以真实报告为准并保持 blocked；禁止修改标签去迎合预期。

## 9.5 数据锁

生成：

```text
configs/locks/mm26_data_lock.yaml
```

建议 schema：

```yaml
schema_version: 1
status: resolved
upstream:
  repository: jasongief/OV-AVEL
  commit: "..."
metadata:
  csv_sha256: "..."
  annotation_sha256: "..."
preprocessed_download:
  receipt_sha256: "..."
layout:
  dataset_root: "data/raw/ov_avebench/ovave_dataset_preprocessed"
  frame_count_histogram: {}
  wav_sample_rate_histogram: {}
manifest:
  train_sha256: "..."
  val_sha256: "..."
  test_sha256: "..."
  counts: {train: 13182, val: 5798, test: 5820}
  segment_length_histogram: {"10": 24800}
preprocessing:
  spec_version: 1
  parameters: {}
```

不要在提交文件中写绝对 `E:\...` 路径；绝对路径放入被 `.gitignore` 的 local config。

---

# 10. 系统化恢复六项历史事实

新增：

```text
scripts/recover_mm26_archival_facts.py
configs/locks/mm26_archival_facts.yaml
reports/archival/MM26_ARCHIVAL_FACT_RECOVERY.md
reports/archival/mm26_archival_evidence.json
```

## 10.1 搜索 Git 历史

```powershell
# 当前仓库全部 refs
$patterns = @(
  "step400", "early_stop", "patience", "InternVideo2_CLIP",
  "vision_ckpt", "text_ckpt", "extra_ckpt", "pretrained",
  "train_augment", "fusion_mlp", "TransformerLayer", "max_segments",
  "lambda_v", "strong_feat", "MSELoss", "L2"
)

foreach ($pattern in $patterns) {
    "===== $pattern ====="
    git log --all --oneline -S $pattern -- .
    git grep -n -I $pattern $(git rev-list --all) 2>$null
}
```

检查：

- 所有 branch/tag；
- reflog 和旧 worktree；
- 被删除但仍在 Git 对象中的配置；
- 原实验压缩包；
- notebook、shell history、PowerShell history；
- W&B/TensorBoard/run directory；
- 旧服务器/NAS；
- 合作者保存的 resolved config。

## 10.2 搜索可信本地实验文件

不要递归扫描整块 5TB 磁盘不加限制。先扫描明确项目目录：

```powershell
$roots = @(
  "E:\OV-OrthKD-R0",
  "E:\OV-OrthKD",
  "$HOME\Documents",
  "$HOME\Downloads"
) | Where-Object { Test-Path $_ }

$extensions = @("*.yaml", "*.yml", "*.json", "*.toml", "*.ini", "*.log", "*.txt", "*.pt", "*.pth", "*.ckpt")
foreach ($root in $roots) {
    Get-ChildItem $root -Recurse -File -Include $extensions -ErrorAction SilentlyContinue |
      Where-Object { $_.Length -lt 20GB } |
      Select-Object FullName, Length, LastWriteTimeUtc
}
```

对 checkpoint 只处理团队可信文件。优先：

```python
checkpoint = torch.load(path, map_location="cpu", weights_only=True)
```

只有可信历史 checkpoint 且 `weights_only=True` 无法读取时，才评估是否使用普通 pickle load。

## 10.3 可以从 checkpoint 推断什么

可以帮助判断：

- `segment_head.weight` 的输入维度；
- 是否存在 `decision_proj/audio_aux_proj/query_proj`；
- fusion 是 concat MLP 还是其他参数结构；
- positional embedding capacity；
- optimizer/scheduler state；
- embedded resolved config；
- teacher checkpoint 路径和运行命令。

不能仅凭：

- positional embedding 长度证明实际训练 $T$；
- state dict 证明数据增强；
- 最终权重证明 $L_2$ reduction；
- 文件名证明 checkpoint 身份。

## 10.4 历史事实锁 schema

```yaml
schema_version: 1
status: blocked
facts:
  temporal_protocol:
    status: unresolved
    value: null
    evidence: []
  internvideo_identity:
    status: unresolved
    value: null
    evidence: []
  scheduler_and_early_stop:
    status: unresolved
    value: null
    evidence: []
  student_initialization_and_augmentation:
    status: unresolved
    value: null
    evidence: []
  visual_l2_reduction:
    status: unresolved
    value: null
    evidence: []
  query_aware_fusion:
    status: unresolved
    value: null
    evidence: []
```

每条 evidence 至少有：

```text
source path or Git commit
source SHA256
line/key/path
extracted fact
confidence: direct|corroborating|inference
reviewer note
```

只有 `direct` 或两个互相独立的 `corroborating` 证据才允许改为 resolved。推断不能单独解锁 canonical 实验。

---

# 11. 教师身份锁定

## 11.1 当前已知但不能视为已解决的事实

R0 静态审计表明：

- 当前 InternVideo wrapper 实际导入 `InternVideo2_CLIP_small`；
- 配置声明却是 `InternVideo2-Base / CLIP-B14`；
- wrapper 接受 vision/text/extra 三个 checkpoint；
- visual alignment dimension 当前声明为 512；
- BEATs feature dimension 当前声明为 768；
- CLAP text dimension 当前声明为 1024；
- CLAP wrapper 当前配置 version 为 2023；
- 这些只是 wrapper/config 声明，不等于历史 checkpoint 已确认。

## 11.2 teacher lock

新增：

```text
configs/locks/mm26_teacher_lock.yaml
```

建议 schema：

```yaml
schema_version: 1
status: blocked
strong_visual:
  wrapper_class: "src.teachers.internvideo2_teacher.InternVideo2ClipB14Teacher"
  upstream:
    repository: null
    commit: null
    class: null
  checkpoints:
    vision: {relative_path: null, bytes: null, sha256: null}
    text: {relative_path: null, bytes: null, sha256: null}
    extra: {relative_path: null, bytes: null, sha256: null}
  preprocessing:
    num_frames: null
    spatial_size: null
    normalization: null
    temporal_sampling: null
  output:
    feature_dim: 512
    logit_dim: 1
weak_audio:
  wrapper_class: "src.teachers.beats_teacher.BEATsAudioTeacher"
  upstream: {repository: null, commit: null, class: null}
  checkpoint: {relative_path: null, bytes: null, sha256: null}
  checkpoint_variant: null
  finetuned_model: null
  preprocessing: {}
  output: {feature_dim: 768}
text:
  wrapper_class: "src.teachers.clap_teacher.ClapTextTeacher"
  upstream: {repository: null, commit: null, class: null}
  checkpoint: {relative_path: null, bytes: null, sha256: null}
  version: null
  normalize: null
  preprocessing: {}
  output: {embedding_dim: 1024}
```

教师锁必须包含**实际类名、仓库 commit、checkpoint SHA256、预处理和输出维度**。只写“BEATs pretrained”或“CLAP 2023”不够。

## 11.3 不允许猜的 checkpoint 选择

BEATs、CLAP 和 InternVideo 都有多个 checkpoint。论文只写模型家族时，不能自动选择最新、最大或名称最接近的一项。

优先顺序：

1. 历史 resolved config；
2. 历史 checkpoint 内嵌配置；
3. 原导出缓存的 metadata；
4. 原运行命令/日志；
5. 原实验执行者书面确认；
6. 以上均无时，canonical 维持 blocked。

可以另行生成：

```text
NON_CANONICAL_PAPER_SPEC_RECONSTRUCTION_PROPOSAL.md
```

列出建议替代 checkpoint，但不得自动执行，也不得把它称为原会议复现。

---

# 12. 第三方仓库与 checkpoint 获取

只有 teacher lock 中的类/版本已经有直接证据后，才执行下载。

## 12.1 克隆到精确 commit

示例流程，不要把 `<...>` 原样执行：

```powershell
New-Item -ItemType Directory -Force external, checkpoints | Out-Null

git clone --recursive <official-internvideo-repository> external\InternVideo
git -C external\InternVideo checkout <locked-commit>
git -C external\InternVideo submodule update --init --recursive

git clone <official-unilm-repository> external\unilm
git -C external\unilm checkout <locked-commit>

git clone <official-clap-repository> external\CLAP
git -C external\CLAP checkout <locked-commit>
```

记录每个 repo：

```powershell
git -C <repo> rev-parse HEAD
git -C <repo> status --porcelain
git -C <repo> submodule status --recursive
```

## 12.2 依赖安装

安装前：

```powershell
python -m pip freeze | Sort-Object | Set-Content reports\runtime\before_teacher_deps.txt
```

优先：

```powershell
python -m pip install --no-deps -e external\CLAP
```

对缺少依赖逐个显式安装，不运行会自动替换 torch 的总 requirements。安装后：

```powershell
python -m pip check
python -m pytest -q
python scripts/verify_cuda_runtime.py --matrix-size 2048 --warmup 2 --iterations 5
python -m pip freeze | Sort-Object | Set-Content reports\runtime\after_teacher_deps.txt
```

若三套依赖无法在同一环境共存，使用三个独立 teacher-export venv，并通过 `.npy`/JSONL 接口交换；不要为了省事把主训练环境弄成无法复现的混合状态。

## 12.3 checkpoint 下载 receipt

每个 checkpoint 下载后立即：

```powershell
Get-Item <checkpoint>
Get-FileHash <checkpoint> -Algorithm SHA256
```

生成：

```text
reports/teachers/checkpoint_download_receipt.json
```

字段：官方来源页、上游 commit、文件名、字节数、SHA256、下载时间。公开来源 URL 可以记录；临时 signed URL、cookie 和 token 不得记录。

---

# 13. 真实教师单样本与跨 split smoke

## 13.1 单对象 smoke

每个教师先独立运行，不先启动组合 pipeline：

```powershell
python scripts/inspect_teacher_identity.py `
  --config configs/ov_orthkd_mm26_repro.local.yaml `
  --teacher strong_visual `
  --real-smoke-manifest data/ov_ave_smoke/source/train_source.jsonl `
  --output-json reports/teachers/strong_visual_identity_and_smoke.json `
  --require-resolved `
  --require-smoke
```

BEATs/CLAP 同理。

检查：

- 实际 imported class 与 teacher lock 一致；
- repo HEAD 与 lock 一致；
- checkpoint SHA 一致；
- model 为 eval，参数不求梯度；
- output shape 精确；
- finite；
- norm 非零；
- 两个不同 segment/两个不同 query 的输出不是全部相同；
- 输入预处理参数完整记录；
- GPU 峰值和耗时记录但不作为论文效率。

## 13.2 跨 split smoke

创建**物理截断** manifest，例如每 split 8 条：

```powershell
python scripts/sample_jsonl_manifest.py `
  --input data/ov_ave/source/train_source.jsonl `
  --output data/ov_ave_smoke/export_source/train_source.jsonl `
  --count 8 --seed 42
```

要求样本覆盖：

- train seen；
- val seen 与 unseen；
- test seen 与 unseen；
- 正边界在不同位置；
- 至少一个声音主导类别；
- 至少一个视觉明显类别。

连续导出两次到不同目录，比较：

```text
shape 完全相同
所有值 finite
max_abs_diff <= 明确容差
cosine similarity 接近 1
teacher-lock hash 完全相同
```

若不能 bitwise 一致，记录具体 nondeterministic op 和容差依据，不能直接忽略。

---

# 14. 教师导出必须原子、可恢复、可追溯

## 14.1 原子 `.npy` 写入

```python
from pathlib import Path
import os
import uuid
import numpy as np


def atomic_save_npy(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as handle:
            np.save(handle, array, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
```

写完后重新读取并检查 shape/finite，再写 receipt。不要先在正式 manifest 中发布路径，再慢慢生成文件。

## 14.2 artifact receipt

每条成功记录写 JSONL：

```json
{
  "record_id": "...",
  "split": "train",
  "source_manifest_sha256": "...",
  "teacher_lock_sha256": "...",
  "artifacts": {
    "strong_teacher_features": {"path": "...", "shape": [10,512], "sha256": "..."},
    "strong_teacher_logits": {"path": "...", "shape": [10,1], "sha256": "..."},
    "weak_teacher_features": {"path": "...", "shape": [10,768], "sha256": "..."},
    "text_embedding": {"path": "...", "shape": [1024], "sha256": "..."}
  }
}
```

默认不生成 weak audio logits。

## 14.3 resume 规则

已存在工件只有在以下条件全部满足时才能 skip：

- receipt 存在；
- teacher lock hash 相同；
- source manifest hash 相同；
- 文件存在；
- SHA256 相同；
- shape 与 finite 检查通过。

否则视为 stale/corrupt，移入 quarantine 或显式 `--overwrite` 重做；不得默默复用。

## 14.4 manifest 发布

写入：

```text
train.jsonl.partial
```

全部成功后：

```python
os.replace(partial_manifest, final_manifest)
```

任何失败时 final manifest 不更新，错误写入 `export_errors.jsonl`，进程非零退出。

---

# 15. 全量教师工件导出

只有以下 gate 全部通过后执行：

```text
[ ] data lock resolved
[ ] archival temporal/teacher preprocessing protocol resolved
[ ] teacher lock resolved
[ ] real single-teacher smoke passed
[ ] cross-split repeated smoke passed
[ ] disk space check passed
[ ] export atomic/resume tests passed
[ ] all repository tests passed
```

先估算空间。仅 float32 数组理论下限约为：

```text
visual [24800,10,512]：约 0.47 GiB
audio  [24800,10,768]：约 0.71 GiB
text   [24800,1024]：约 0.095 GiB
visual logits：约 0.001 GiB
```

还要加原始数据、checkpoint、临时文件、NTFS 小文件开销和至少一份重导缓冲。运行前记录磁盘空闲。

正式命令：

```powershell
foreach ($split in @("train", "val", "test")) {
    python scripts/export_teacher_artifacts.py `
      --config configs/ov_orthkd_mm26_repro.local.yaml `
      --source-manifest "data/ov_ave/source/${split}_source.jsonl" `
      --output-manifest "data/ov_ave/${split}.jsonl" `
      --artifact-dir "data/teacher_cache/mm26/${split}" `
      --receipt-jsonl "data/teacher_cache/mm26/${split}_receipt.jsonl" `
      --device cuda `
      --resume
    if ($LASTEXITCODE -ne 0) { throw "Teacher export failed for $split" }
}
```

不要在第一次全量导出使用 `--overwrite`。

---

# 16. 全量 artifact audit 与根哈希

```powershell
python scripts/audit_mm26_reproduction.py `
  --train-manifest data/ov_ave/train.jsonl `
  --val-manifest data/ov_ave/val.jsonl `
  --test-manifest data/ov_ave/test.jsonl `
  --path-root . `
  --stage exported `
  --artifact-scan full `
  --expected-segments 10 `
  --fail-on-warning `
  --teacher-lock configs/locks/mm26_teacher_lock.yaml `
  --data-lock configs/locks/mm26_data_lock.yaml `
  --output-json reports/teachers/mm26_full_export_audit.json
```

必须得到：

- 24,800 records；
- 三 split 精确计数；
- 67 类；
- 46 seen / 21 unseen；
- 无 ID 重复、无 split overlap；
- labels、frame、spectrogram、teacher arrays 严格对齐；
- 0 missing artifact；
- 0 shape error；
- 0 NaN/Inf；
- 0 path collision；
- 0 stale teacher-lock hash；
- 全量 receipt 数等于记录数；
- 每 split manifest SHA256；
- 每 split artifact Merkle/root SHA256；
- 总 cache root SHA256。

根哈希可按排序后的：

```text
relative_path|bytes|sha256
```

逐行再做一次 SHA256，避免把数万条 hash 全塞进最终 Markdown。

---

# 17. 实验前真实数据 preflight

本轮最后只允许一次 bounded preflight：

```powershell
python scripts/preflight_ov_orthkd.py `
  --config configs/ov_orthkd_mm26_repro.local.yaml `
  --output-dir outputs/r1_real_data_preflight `
  --probe-samples 8 `
  --max-eval-batches 1
```

它可以：

- 构造真实 DataLoader；
- 读取真实教师工件；
- 一次 forward；
- 一次 backward 和 optimizer step；
- 检查所有 loss finite、路径梯度存在；
- 保存临时 checkpoint 并恢复；
- 输出 shape、显存和时间。

它不可以：

- 跑完整验证/测试；
- 校准 threshold；
- 报正式 AP/F1；
- 运行超过一个 optimizer step；
- 修改 canonical `full_run_blocked`。

输出必须标记：

```json
{
  "preflight_only": true,
  "paper_result": false,
  "optimizer_steps": 1
}
```

---

# 18. canonical 解锁规则

本轮不得直接把主配置改成：

```yaml
full_run_blocked: false
```

即便全部事实恢复，也只新增：

```text
configs/ov_orthkd_mm26_repro.resolved-proposal.yaml
reports/READY_FOR_R2_REVIEW.md
```

其中 proposal 必须引用：

```text
R1 commit SHA
data lock SHA256
archival facts lock SHA256
teacher lock SHA256
artifact cache root SHA256
environment lock SHA256
```

下一轮审计确认后，才允许复制为正式训练配置。

---

# 19. 建议文件清单

本轮建议新增/修改：

```text
src/data/ov_avel_dataset.py
scripts/train_ov_orthkd.py
scripts/preflight_ov_orthkd.py
scripts/export_teacher_artifacts.py
scripts/build_ov_avebench_source_manifests.py
scripts/audit_mm26_reproduction.py
scripts/audit_official_ov_avebench_metadata.py
scripts/discover_ov_avebench_layout.py
scripts/recover_mm26_archival_facts.py
scripts/inspect_historical_checkpoint.py
scripts/sample_jsonl_manifest.py
src/utils/reproduction_fingerprint.py
src/utils/atomic_artifacts.py
configs/ov_orthkd_mm26_repro.yaml
configs/locks/mm26_data_lock.yaml
configs/locks/mm26_archival_facts.yaml
configs/locks/mm26_teacher_lock.yaml
configs/ov_orthkd_mm26_repro.resolved-proposal.yaml  # 仅全部满足时生成
reports/R1_DATA_TEACHER_READINESS_REPORT.md
reports/READY_FOR_R2_REVIEW.md                      # 仅全部满足时生成
tests/test_r1_dataset_integrity.py
tests/test_r1_checkpoint_resume.py
tests/test_r1_official_metadata.py
tests/test_r1_teacher_lock.py
tests/test_r1_atomic_export.py
```

外部数据、第三方仓库、checkpoint、cache、local config 和 outputs 必须继续被 Git 忽略。

---

# 20. 完整执行顺序

严格按顺序：

```text
R1-0  固定 R0 commit，跑现有 60 项测试和 5090 CUDA 检查
R1-1  写新失败测试，修复时间抽样/广播/路径碰撞/finite/eval/resume
R1-2  再跑全部单元测试和 mock preflight
R1-3  克隆并锁定官方元数据仓库，执行元数据精确审计
R1-4  通过官方链接下载预处理数据，建立 receipt，安全解压到 staging
R1-5  发现真实布局，检查 frame/wav 完整性
R1-6  构建 smoke source manifest，验证确定性和 seen/unseen
R1-7  构建全量 source manifest，执行 full source audit，生成 data lock
R1-8  搜索 Git/历史运行包，恢复六项 archival facts
R1-9  恢复并锁定三类教师的精确身份和 checkpoint
R1-10 克隆教师仓库到精确 commit，安装依赖并回归测试
R1-11 单教师真实 smoke + 跨 split 重复 smoke
R1-12 全量 teacher export，生成 receipts 和 cache root hash
R1-13 full exported artifact audit
R1-14 一次真实数据一批次 preflight
R1-15 生成 R1 report、proposal、双重自检、单一 commit
```

任一 P0 gate 失败时立刻停止后续步骤，不要把“继续跑看看”当作排障方法。

---

# 21. 最终测试矩阵

```powershell
python -m pip check
python -m compileall -q src scripts tests
python -m pytest -q
python scripts/verify_cuda_runtime.py --matrix-size 2048 --warmup 2 --iterations 5
python scripts/smoke_test.py

git diff --check
git status --short
git diff --stat
```

额外必须运行：

```powershell
python scripts/audit_official_ov_avebench_metadata.py ... --fail-on-error
python scripts/audit_mm26_reproduction.py ... --stage source --fail-on-warning
python scripts/inspect_teacher_identity.py ... --require-resolved --require-smoke
python scripts/audit_mm26_reproduction.py ... --stage exported --artifact-scan full --fail-on-warning
```

canonical guard 仍应按预期拒绝正式训练：

```powershell
python scripts/train_ov_orthkd.py --config configs/ov_orthkd_mm26_repro.yaml
# 预期非零退出，且在创建正式输出和读取训练数据之前阻断。
```

---

# 22. 第一次自检：代码与数据语义

提交前逐项回答：

- [ ] official `close/open` 是否明确映射到 `seen/unseen`？
- [ ] 精确 split/class/group 计数是否通过？
- [ ] annotation 与 CSV 是否一一对应？
- [ ] 标签是否全部二值，长度分布是否记录？
- [ ] `max_segments` 是否只是 capacity，canonical 是否禁止隐式抽样？
- [ ] segment teacher feature 是否严格 `[T,D]`，没有 singleton broadcast？
- [ ] artifact override 是否保留相对目录，碰撞测试是否通过？
- [ ] frame grouping 和 audio segmentation 是否完整写入 data lock？
- [ ] 所有生成 spectrogram 是否确定性？
- [ ] 预处理参数是否没有依赖未记录的库默认值？
- [ ] eval-only 是否完全不构造 scheduler？
- [ ] resume 是否恢复 RNG 和 loader generator？
- [ ] fingerprint 不一致是否 fail closed？

---

# 23. 第二次自检：教师与证据链

- [ ] 每个 teacher repo 是否固定到 commit？
- [ ] 实际 imported class 是否与 lock 一致？
- [ ] 所有 checkpoint 是否有字节数和 SHA256？
- [ ] InternVideo Base/B14 与 Small 冲突是否真正解决？
- [ ] BEATs 是哪一个 pretrained/finetuned variant 是否明确？
- [ ] CLAP 版本、checkpoint 和 normalize 是否明确？
- [ ] visual frame sampling、audio waveform slicing、text preprocessing 是否明确？
- [ ] real smoke 是否覆盖多个 split/seen-unseen？
- [ ] 重复导出是否在容差内一致？
- [ ] full export 是否原子、可恢复、无 partial manifest 发布？
- [ ] receipt 数是否等于 24,800？
- [ ] full artifact audit 是否 0 error/0 warning？
- [ ] teacher lock、data lock、cache root hash 是否互相引用？
- [ ] 任何 mock/preflight 指标是否都明确标记非论文结果？
- [ ] canonical full run 是否仍被阻断？

---

# 24. R1 最终报告必须包含

`reports/R1_DATA_TEACHER_READINESS_REPORT.md` 至少包括：

1. 起始/结束 commit；
2. R0 后置问题的逐项 disposition；
3. 所有修改文件；
4. 测试命令、退出码和摘要；
5. 5090 环境；
6. 官方元数据 repo SHA、文件 SHA 和精确计数；
7. 预处理下载 receipt 和布局；
8. source manifest hash 与 segment/frame/audio 统计；
9. 六项 archival facts 的 resolved/blocked 状态和证据；
10. 三类 teacher lock；
11. checkpoint SHA256；
12. smoke export 结果；
13. full export 记录数、错误数、cache root hash；
14. full artifact audit；
15. 真实一批次 preflight；
16. canonical 是否可建议进入 R2；
17. `NOT_EXECUTED`：明确没有正式训练、没有论文指标、没有扩刊机制。

结论只能是二选一：

```text
READY_FOR_R2_REVIEW
```

或：

```text
BLOCKED_BEFORE_R2
```

若 blocked，必须列出最小剩余动作和需要谁提供的信息，不能以“数据已下载”掩盖教师或历史事实未解决。

---

# 25. Codex 最终返回格式

```text
Branch:
Commit SHA:
Base SHA:
Git diff --stat:

R0 post-fixes:
- ...

Data lock:
- upstream commit:
- metadata SHA256:
- annotation SHA256:
- source manifest SHA256s:
- counts:
- segment histogram:

Archival facts:
- temporal protocol: resolved/blocked
- InternVideo identity: resolved/blocked
- scheduler: resolved/blocked
- initialization/augmentation: resolved/blocked
- L2 reduction: resolved/blocked
- fusion: resolved/blocked

Teacher lock:
- InternVideo repo/class/checkpoints/hashes:
- BEATs repo/variant/checkpoint/hash:
- CLAP repo/version/checkpoint/hash:

Teacher cache:
- records:
- missing/errors:
- root SHA256:

Tests:
- command / exit / result

Real-data preflight:
- optimizer steps:
- finite:
- peak memory:
- explicitly non-result:

Final status:
- READY_FOR_R2_REVIEW or BLOCKED_BEFORE_R2

Unresolved items:
- ...
```

---

# 26. 本轮最重要的停止条件

任何一项成立都必须停止正式教师全量导出或 R2：

- 官方数据计数不符；
- `close/open` 分组映射不明确；
- annotation/CSV ID 不一致；
- segment 长度或 frame grouping 不明确；
- teacher input 需要 raw frames，但只有中间帧且无历史重复证据；
- InternVideo 类冲突仍在；
- checkpoint hash 不明确；
- BEATs/CLAP variant 不明确；
- singleton teacher artifact 被广播；
- teacher smoke 出现全零、NaN/Inf、shape 错误；
- full export 有任何 missing/stale/collision；
- 六项 archival facts 任一 unresolved；
- 需要通过修改测试集或 test threshold 来“对齐论文”；
- 需要关闭 strict guard 才能继续。

这个阶段的成功标准不是“脚本终于开始训练”，而是：

> **下一轮正式实验的每一份输入、每一项方法事实和每一个教师目标都有可核验来源；一旦训练结果偏离论文，可以定位到模型/优化，而不是继续怀疑数据和缓存。**
