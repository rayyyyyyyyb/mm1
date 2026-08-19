# OV-OrthKD / ACM MM 2026 原会议复现：R0 工程加固、代码修正与完整执行路线

> 目标仓库：`https://github.com/rayyyyyyyyb/mm1`
> 审计分支：`main`
> 审计基线提交：`dca9f052fbe4a1e9d7982f24bdcec3edf1363fd4`
> 当前阶段：**先复现原会议版 OV-OrthKD，不实现 VP-AdaOrthKD 扩刊机制**
> 执行角色：Codex 在本地仓库修改、测试、提交；研究负责人随后将提交推送，供下一轮审计。

---

## 0. 给 Codex 的直接执行指令

请把本文件当作本轮唯一任务书。先完整阅读，再执行，不要只做局部字符串替换。

本轮的目标不是跑出最终论文数字，而是完成 **R0：paper-faithful reproduction hardening**，使现有协作代码具备可靠复现原会议版的资格。必须：

1. 从基线提交创建独立分支；
2. 修复本文列出的已确认论文—代码不一致；
3. 增加严格数据/教师工件检查、确定性训练、可追溯日志和论文一致性测试；
4. 保留旧接口所需的最小兼容性，但新的论文复现配置必须使用修正后的路径；
5. 不下载完整数据、不导出完整教师工件、不启动完整训练；
6. 只允许运行单元测试、mock smoke test、CPU/GPU 一批次 preflight；
7. 最后生成 `reports/R0_REPRO_HARDENING_REPORT.md`，记录所有修改、测试命令、输出和仍未解决的归档问题；
8. 提交前执行本文末尾的双重检查清单。

建议分支：

```bash
git fetch --all --tags --prune
git checkout main
git pull --ff-only
git rev-parse HEAD
# 必须确认输出为 dca9f052fbe4a1e9d7982f24bdcec3edf1363fd4；若仓库已有后续提交，记录实际 SHA，禁止强行 reset 丢失工作。
git checkout -b repro/r0-paper-faithfulness
```

本轮禁止实现以下扩刊内容：可靠性路由器、三状态 Visual-Dec/Audio-Dec/No-Teacher、语义—边界可靠性、选择性正交门控、OOF 教师探针。那些属于会议版复现通过后的下一阶段。

---

# 1. 审计结论

当前仓库是一个结构完整、可以进行 mock vertical slice 的研究协作底座，但它并不是已经封存的原会议实验归档。仓库 README 自己也说明：数据、预训练权重、教师缓存和实验输出均未包含，配置中的路径、batch size 与训练 schedule 需要本地适配。

因此现在不能直接执行：

```bash
python scripts/train_ov_orthkd.py --config configs/ov_orthkd_paper_setting.yaml
```

然后把结果称为论文复现。当前至少存在以下**已确认问题**：

| 级别 | 问题 | 当前实现 | 论文要求/复现要求 |
|---|---|---|---|
| P0 | camera-ready 与协作代码的决策路径不一致 | `segment_head(encoded_tokens)` 直接读取共享特征 | 论文叙事和框图显示 visual/decision-aligned projection 支撑定位头；但尚不确定历史结果实际使用哪一版，必须保留 legacy 与 camera-ready 双模式 |
| P0 | camera-ready 与协作代码的文本损失不一致 | `cos / 0.07` 后使用 `BCEWithLogitsLoss` | 论文式为先把 cosine 从 $[-1,1]$ 映射到 $[0,1]$，再做 BCE；历史运行公式尚需归档确认，必须保留双模式 |
| P0 | 融合公式存在未解决差异 | 当前代码把加权视觉、音频和文本 concat 后过 MLP，gate 还读取两个 validity bit | 论文式写为 $\alpha_v\tilde v+\alpha_a\tilde a+\tilde q$ 后接 TransformerLayer；该层的历史实现细节未知，R0 只记录并阻止 canonical full run，不凭猜测重写 |
| P0 | 伪造弱教师 logits | 缺少音频 logits 时，由视觉 logits 加随机噪声构造 | 原会议默认没有 audio-logit KD；复现不能生成虚构教师信号 |
| P0 | 缺教师工件时静默置零 | 教师 feature/text 缺失时返回零张量和零 mask | 正式复现必须 fail fast，不能把缺文件误当成“合法无监督片段” |
| P0 | 5090 安装脚本不兼容 | 仅支持 `cu121/cu124` | RTX 5090 / Blackwell 应使用支持 `sm_120` 的 CUDA 12.8+ PyTorch wheel |
| P1 | 训练可复现性不足 | 未设置 deterministic、worker seed、DataLoader generator | 至少需固定 RNG、worker seed，并完整记录运行环境 |
| P1 | 复现证据不足 | 仅保存 `best.pt` 与简单 runtime JSON | 需保存 last/best、history、prediction、manifest/checkpoint hash、git 状态 |
| P1 | 评价不完整 | 主训练只报全体 AP/AUROC/F1@0.5 | 还需 seen/unseen、验证集阈值校准 F1 和逐样本预测导出 |
| P1 | teacher export 的 `--limit` 有陷阱 | 只导出前 N 条，但输出 manifest 保留后续未导出记录 | smoke export 必须使用物理截断的 source manifest，或修复为截断输出 |
| P2 | latency 计时错误 | GPU 前后未 `torch.cuda.synchronize()` | 后续效率复现必须同步；R0 可顺手修复 |

另外有若干**不能凭猜测填补的归档问题**：

1. OV-AVEBench 官方定义每个 10 秒视频为 $T=10$ 个 1 秒片段；会议论文实现表中又写了 16 temporal segments。现有 manifest builder 按标注长度构造序列，而配置 `max_segments: 16` 只是上限，并不会把 10 插值为 16。必须从历史 manifest/checkpoint/实验日志确认实际训练序列，禁止自行复制标签到 16 段。
2. 配置名写 `InternVideo2-Base (CLIP-B14 line)`，但 wrapper 实际导入 `InternVideo2_CLIP_small`。必须确认原实验使用的模型类与三个 checkpoint；禁止根据名字随便下载一个 InternVideo2 权重。
3. 论文写 “step400 schedule with early stopping”，但当前代码使用 epoch-level `CosineAnnealingLR`；`step400` 的准确含义、gamma、按 iteration 还是 epoch 更新、early-stop patience 尚未归档。
4. 学生 backbone 是否从 ImageNet/FCMAE 权重初始化、训练增强的精确组合、视觉 $L_2$ 是 feature-dimension sum 还是 mean，需要从原始运行配置或 checkpoint 恢复。
5. query-aware fusion 的历史实现究竟是论文公式中的加法融合 $\alpha_v\tilde v+\alpha_a\tilde a+\tilde q$ 后接 `TransformerLayer`，还是当前协作代码中的加权 token concat + MLP，且 gate 是否应读取 validity bits，必须从历史代码、checkpoint 参数名或运行包确认。

R0 必须把这些问题显式记录为 `BLOCKED_ARCHIVAL_FACTS`，不能为了让脚本“能跑”而默默发明参数。

---

# 2. camera-ready 论文定义需要冻结的规范计算图

下面的计算图是 **camera-ready 论文定义的规范实现**。它用于新增 `camera_ready_explicit_paths` 模式及 paper-faithfulness 测试；它不等于已经证明历史出表代码就是这一版。为了避免用论文叙事覆盖未知的历史实现，R0 同时保留 `legacy_collaboration` 模式，并在历史 checkpoint、原始运行配置和融合实现被恢复前阻止 canonical full run。

正式的 camera-ready 复现配置必须表达下面的固定角色：

```text
video frames -> ConvNeXtV2-Tiny --┐
                                  ├-> query-aware AV fusion -> 4-layer temporal Transformer -> shared f_s
spectrograms -> EfficientNetV2-B2 ┘                                         |
CLAP query embedding ------------------------------------------------------|
                                                                             |
                             ┌-> decision/visual-aligned projection h_v -> localization head -> segment logits
shared f_s -----------------├-> audio-aligned auxiliary projection h_a
                             └-> query-aligned projection h_q

InternVideo2 feature -- L2 --> h_v
BEATs feature -------- cosine --> h_a
CLAP text prototype -- mapped cosine BCE --> h_q
orthogonality -------- cos^2(h_v, h_a)
GT labels ------------ BCEWithLogits --> segment logits
```

默认总损失：

$$
\mathcal L=
1.0\mathcal L_{sup}
+0.4\mathcal L_{v\text{-feat}}
+0.1\mathcal L_{a\text{-feat}}
+0.8\mathcal L_{text}
+0.5\mathcal L_{orth}.
$$

必须保持：

```yaml
alpha_strong_logit: 0.0
alpha_weak_logit: 0.0
```

也就是说，原会议主配置不使用 visual-logit KD，也没有 audio-logit KD。视觉 logits 只可以作为 analysis-only control 的真实离线工件存在，绝不能自动合成音频 logits。

---

# 3. R0 修改范围

## 3.1 必须新增或修改的文件

```text
src/models/ov_orthkd.py
src/losses/ov_orthkd_loss.py
src/losses/ov_orthkd_legacy_loss.py
src/data/ov_avel_dataset.py
scripts/train_ov_orthkd.py
scripts/preflight_ov_orthkd.py
scripts/evaluate_pr_f1.py
scripts/measure_efficiency.py
scripts/setup_server.sh
configs/ov_orthkd_mm26_repro.yaml
configs/ov_orthkd_mm26_smoke.yaml
scripts/audit_mm26_reproduction.py
scripts/verify_cuda_runtime.py
scripts/inspect_teacher_identity.py
tests/test_paper_faithfulness.py
tests/test_strict_reproduction_data.py
reports/R0_REPRO_HARDENING_REPORT.md
```

允许同步修改：

```text
src/models/__init__.py
src/losses/__init__.py
src/data/__init__.py
tests/test_ov_orthkd_pipeline.py
tests/test_teacher_export_and_preflight.py
README.md
```

不要修改或删除已有配置和 baseline；新增新的复现配置，避免破坏旧实验入口。

---

# 4. 模型结构修正

## 4.1 增加 camera-ready 显式路径，同时原样保留 legacy 行为

当前三个 student projector 位于 loss module 中，而定位头绕过了 visual/decision path。论文框图则显示 projection path 支撑定位头。由于历史结果究竟使用哪一版尚未归档，R0 **不得覆盖删除旧行为**：

1. 先把当前 `OVOrthKDLoss` 原样复制为 `OVOrthKDLegacyLoss`；
2. `path_mode=legacy_shared` 时，不创建或不优化新增 projection，定位头仍读取 shared feature，并搭配 legacy loss；
3. `path_mode=explicit_projected` 时，三条 projection 属于 student，定位头读取 decision feature，并搭配 camera-ready loss；
4. 两种模式都通过测试，输出 checkpoint 中记录 `implementation_mode`；
5. 新的 camera-ready 复现配置使用 explicit 模式，但 full run 仍因归档事实未解决而被拦截。

在 `src/models/ov_orthkd.py` 中加入：

```python
class ProjectionHead(nn.Module):
    def __init__(self, in_dim: int, out_dim: int, hidden_dim: int | None = None) -> None:
        super().__init__()
        hidden_dim = hidden_dim or out_dim
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, out_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)
```

给 `OVOrthKDStudent.__init__` 增加参数：

```python
projection_dim: int = 256,
path_mode: str = "explicit_projected",
```

并加入：

```python
if path_mode not in {"explicit_projected", "legacy_shared"}:
    raise ValueError(f"Unsupported path_mode: {path_mode}")

self.projection_dim = int(projection_dim)
self.path_mode = path_mode
if path_mode == "explicit_projected":
    self.decision_proj = ProjectionHead(fusion_dim, self.projection_dim)
    self.audio_aux_proj = ProjectionHead(fusion_dim, self.projection_dim)
    self.query_proj = ProjectionHead(fusion_dim, self.projection_dim)
    self.segment_head = nn.Linear(self.projection_dim, 1)
else:
    # 保持原协作代码的参数结构和行为；不要创建无梯度但会改变参数量的额外 heads。
    self.decision_proj = None
    self.audio_aux_proj = None
    self.query_proj = None
    self.segment_head = nn.Linear(fusion_dim, 1)
```

替换 forward 尾部：

```python
shared_features = self.temporal_encoder(
    fused_tokens,
    src_key_padding_mask=~sequence_mask.bool(),
)

if self.path_mode == "explicit_projected":
    assert self.decision_proj is not None
    assert self.audio_aux_proj is not None
    assert self.query_proj is not None
    decision_features = self.decision_proj(shared_features)
    audio_aux_features = self.audio_aux_proj(shared_features)
    query_features = self.query_proj(shared_features)
    segment_logits = self.segment_head(decision_features).squeeze(-1)
else:
    decision_features = None
    audio_aux_features = None
    query_features = None
    segment_logits = self.segment_head(shared_features).squeeze(-1)

return {
    "segment_logits": segment_logits,
    "shared_features": shared_features,
    "decision_features": decision_features,
    "audio_aux_features": audio_aux_features,
    "query_features": query_features,
    # 旧接口临时兼容；新代码不得再依赖这个模糊名称。
    "segment_features": shared_features,
    "visual_tokens": visual_tokens,
    "audio_tokens": audio_tokens,
    "text_tokens": text_token,
    "gate_logits": gate_logits,
    "gate_weights": gate_weights,
}
```

新复现配置必须设置：

```yaml
student:
  projection_dim: 256
  path_mode: explicit_projected
```

`legacy_shared` 是当前协作代码的可重现实验模式；`explicit_projected` 是 camera-ready equation/diagram 模式。两者必须命名清楚，禁止把 legacy 结果误标为 camera-ready，反之亦然。

---

# 5. 损失函数修正

## 5.1 设计原则

先把当前 `OVOrthKDLoss` 不改公式地迁移为 `OVOrthKDLegacyLoss`，保证现有协作实现可被完整重跑。然后实现新的 camera-ready `OVOrthKDLoss`：

1. camera-ready class 删除 `student_strong_proj/student_weak_proj/student_text_proj`；
2. forward 接收显式的三条学生路径；
3. 保留 strong/weak/text teacher projector；
4. 只有对应 alpha 大于 0 时才计算该项；
5. 某项已开启但所需工件或 mask 缺失时立即抛错；
6. 默认没有音频 logit KD；
7. 文本损失严格使用论文公式；
8. R0 暂时保留当前 `_masked_mean`，因为正式数据中 mask 全开时与固定 $T$ 归一只差常数；不要在复现原会议阶段提前套用扩刊版固定分母规则。

## 5.2 推荐的完整核心实现

以下代码可作为 `src/losses/ov_orthkd_loss.py` 的核心参考。Codex 可在保留类型提示、导出接口和必要兼容性的前提下实现等价版本。

```python
from __future__ import annotations

from typing import Dict, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from src.models.ov_orthkd import ProjectionHead


def _masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    if values.shape != mask.shape:
        raise ValueError(f"values/mask shape mismatch: {values.shape} vs {mask.shape}")
    mask = mask.to(dtype=values.dtype)
    denom = mask.sum().clamp_min(1.0)
    return (values * mask).sum() / denom


def _zero(reference: torch.Tensor) -> torch.Tensor:
    return reference.new_zeros(())


def _require_tensor(value: torch.Tensor | None, name: str) -> torch.Tensor:
    if value is None:
        raise ValueError(f"Required tensor is missing while its loss is enabled: {name}")
    return value


def paper_text_alignment_terms(
    student_query_features: torch.Tensor,
    projected_text_target: torch.Tensor,
    segment_labels: torch.Tensor,
    eps: float = 1e-6,
) -> torch.Tensor:
    """Equation-aligned text loss terms.

    cos in [-1, 1] -> probability in [0, 1] -> binary cross entropy.
    """
    if projected_text_target.ndim != 2:
        raise ValueError(
            f"projected_text_target must be [B, D], got {projected_text_target.shape}"
        )
    target = projected_text_target[:, None, :].expand_as(student_query_features)
    cosine = F.cosine_similarity(student_query_features, target, dim=-1)
    probability = ((cosine + 1.0) * 0.5).clamp(min=eps, max=1.0 - eps)
    return F.binary_cross_entropy(probability, segment_labels, reduction="none")


class OVOrthKDLoss(nn.Module):
    def __init__(
        self,
        strong_teacher_dim: int,
        weak_teacher_dim: int,
        text_dim: int,
        projection_dim: int = 256,
        temperature: float = 2.0,
        alpha_bce: float = 1.0,
        alpha_strong_logit: float = 0.0,
        alpha_weak_logit: float = 0.0,
        alpha_strong_feat: float = 0.4,
        alpha_weak_feat: float = 0.1,
        alpha_text_align: float = 0.8,
        alpha_orth: float = 0.5,
        text_alignment_mode: str = "paper_probability",
        confidence_weighting: bool = True,
        confidence_scale: float = 2.0,
    ) -> None:
        super().__init__()
        self.temperature = float(temperature)
        self.alpha_bce = float(alpha_bce)
        self.alpha_strong_logit = float(alpha_strong_logit)
        self.alpha_weak_logit = float(alpha_weak_logit)
        self.alpha_strong_feat = float(alpha_strong_feat)
        self.alpha_weak_feat = float(alpha_weak_feat)
        self.alpha_text_align = float(alpha_text_align)
        self.alpha_orth = float(alpha_orth)
        if text_alignment_mode not in {"paper_probability", "legacy_logit_temperature"}:
            raise ValueError(f"Unsupported text_alignment_mode: {text_alignment_mode}")
        self.text_alignment_mode = text_alignment_mode
        self.confidence_weighting = bool(confidence_weighting)
        self.confidence_scale = float(confidence_scale)

        self.strong_teacher_proj = ProjectionHead(strong_teacher_dim, projection_dim)
        self.weak_teacher_proj = ProjectionHead(weak_teacher_dim, projection_dim)
        self.text_teacher_proj = ProjectionHead(text_dim, projection_dim)

    def forward(
        self,
        *,
        student_segment_logits: torch.Tensor,
        student_decision_features: torch.Tensor,
        student_audio_aux_features: torch.Tensor,
        student_query_features: torch.Tensor,
        segment_labels: torch.Tensor,
        sequence_mask: torch.Tensor,
        strong_teacher_logits: torch.Tensor | None = None,
        strong_teacher_features: torch.Tensor | None = None,
        weak_teacher_logits: torch.Tensor | None = None,
        weak_teacher_features: torch.Tensor | None = None,
        text_embeddings: torch.Tensor | None = None,
        strong_teacher_logit_mask: torch.Tensor | None = None,
        strong_teacher_feature_mask: torch.Tensor | None = None,
        weak_teacher_logit_mask: torch.Tensor | None = None,
        weak_teacher_feature_mask: torch.Tensor | None = None,
        text_valid: torch.Tensor | None = None,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        sequence_mask = sequence_mask.to(dtype=student_segment_logits.dtype)
        segment_labels = segment_labels.to(dtype=student_segment_logits.dtype)

        bce_terms = F.binary_cross_entropy_with_logits(
            student_segment_logits,
            segment_labels,
            reduction="none",
        )
        bce_loss = _masked_mean(bce_terms, sequence_mask)

        strong_logit_loss = _zero(student_segment_logits)
        if self.alpha_strong_logit > 0:
            teacher_logits = _require_tensor(strong_teacher_logits, "strong_teacher_logits")
            logit_mask = _require_tensor(
                strong_teacher_logit_mask, "strong_teacher_logit_mask"
            ).to(dtype=student_segment_logits.dtype)
            teacher_logits = teacher_logits.squeeze(-1)
            teacher_probs = torch.sigmoid(teacher_logits / self.temperature)
            student_logits_t = student_segment_logits / self.temperature
            terms = F.binary_cross_entropy_with_logits(
                student_logits_t, teacher_probs, reduction="none"
            ) * (self.temperature**2)
            if self.confidence_weighting:
                confidence = torch.sigmoid(
                    teacher_logits.abs() * self.confidence_scale
                )
                logit_mask = logit_mask * confidence
            strong_logit_loss = _masked_mean(terms, sequence_mask * logit_mask)

        weak_logit_loss = _zero(student_segment_logits)
        if self.alpha_weak_logit > 0:
            teacher_logits = _require_tensor(weak_teacher_logits, "weak_teacher_logits")
            logit_mask = _require_tensor(
                weak_teacher_logit_mask, "weak_teacher_logit_mask"
            ).to(dtype=student_segment_logits.dtype)
            teacher_logits = teacher_logits.squeeze(-1)
            teacher_probs = torch.sigmoid(teacher_logits / self.temperature)
            student_logits_t = student_segment_logits / self.temperature
            terms = F.binary_cross_entropy_with_logits(
                student_logits_t, teacher_probs, reduction="none"
            ) * (self.temperature**2)
            weak_logit_loss = _masked_mean(terms, sequence_mask * logit_mask)

        strong_feat_loss = _zero(student_segment_logits)
        strong_mask_for_orth: torch.Tensor | None = None
        if self.alpha_strong_feat > 0 or self.alpha_orth > 0:
            strong_features = _require_tensor(
                strong_teacher_features, "strong_teacher_features"
            )
            strong_mask_for_orth = _require_tensor(
                strong_teacher_feature_mask, "strong_teacher_feature_mask"
            ).to(dtype=student_segment_logits.dtype)
            strong_target = self.strong_teacher_proj(strong_features.detach())
            if self.alpha_strong_feat > 0:
                # 保留当前实现的 feature-dimension mean，直到历史代码确认是否为 sum。
                strong_terms = (
                    student_decision_features - strong_target
                ).pow(2).mean(dim=-1)
                strong_feat_loss = _masked_mean(
                    strong_terms, sequence_mask * strong_mask_for_orth
                )

        weak_feat_loss = _zero(student_segment_logits)
        weak_mask_for_orth: torch.Tensor | None = None
        if self.alpha_weak_feat > 0 or self.alpha_orth > 0:
            weak_features = _require_tensor(
                weak_teacher_features, "weak_teacher_features"
            )
            weak_mask_for_orth = _require_tensor(
                weak_teacher_feature_mask, "weak_teacher_feature_mask"
            ).to(dtype=student_segment_logits.dtype)
            weak_target = self.weak_teacher_proj(weak_features.detach())
            if self.alpha_weak_feat > 0:
                weak_terms = 1.0 - F.cosine_similarity(
                    student_audio_aux_features, weak_target, dim=-1
                )
                weak_feat_loss = _masked_mean(
                    weak_terms, sequence_mask * weak_mask_for_orth
                )

        text_align_loss = _zero(student_segment_logits)
        if self.alpha_text_align > 0:
            text_embeddings = _require_tensor(text_embeddings, "text_embeddings")
            text_valid = _require_tensor(text_valid, "text_valid").to(
                dtype=student_segment_logits.dtype
            )
            text_target = self.text_teacher_proj(text_embeddings.detach())
            if self.text_alignment_mode == "paper_probability":
                text_terms = paper_text_alignment_terms(
                    student_query_features=student_query_features,
                    projected_text_target=text_target,
                    segment_labels=segment_labels,
                )
            else:
                # 只用于受控复跑当前协作实现；canonical camera-ready 配置禁止使用。
                expanded = text_target[:, None, :].expand_as(student_query_features)
                text_logits = F.cosine_similarity(
                    student_query_features, expanded, dim=-1
                ) / 0.07
                text_terms = F.binary_cross_entropy_with_logits(
                    text_logits, segment_labels, reduction="none"
                )
            text_align_loss = _masked_mean(
                text_terms,
                sequence_mask * text_valid[:, None],
            )

        orth_loss = _zero(student_segment_logits)
        if self.alpha_orth > 0:
            if strong_mask_for_orth is None or weak_mask_for_orth is None:
                raise RuntimeError("Orthogonality requires both teacher feature masks")
            orth_terms = F.cosine_similarity(
                student_decision_features,
                student_audio_aux_features,
                dim=-1,
            ).pow(2)
            orth_loss = _masked_mean(
                orth_terms,
                sequence_mask * strong_mask_for_orth * weak_mask_for_orth,
            )

        total_loss = (
            self.alpha_bce * bce_loss
            + self.alpha_strong_logit * strong_logit_loss
            + self.alpha_weak_logit * weak_logit_loss
            + self.alpha_strong_feat * strong_feat_loss
            + self.alpha_weak_feat * weak_feat_loss
            + self.alpha_text_align * text_align_loss
            + self.alpha_orth * orth_loss
        )

        stats = {
            "bce": float(bce_loss.detach().cpu()),
            "strong_logit": float(strong_logit_loss.detach().cpu()),
            "weak_logit": float(weak_logit_loss.detach().cpu()),
            "strong_feat": float(strong_feat_loss.detach().cpu()),
            "weak_feat": float(weak_feat_loss.detach().cpu()),
            "text_align": float(text_align_loss.detach().cpu()),
            "orth": float(orth_loss.detach().cpu()),
            "total": float(total_loss.detach().cpu()),
        }
        return total_loss, stats
```

说明：每步把 stats 转成 Python float 会触发 GPU 同步。R0 可保留以降低改动风险；后续正式训练若发现吞吐明显下降，可改为每 N 步聚合 tensor，再同步一次，但不得改变损失本身。

## 5.3 调用处必须改为显式路径

`train_ov_orthkd.py` 与 `preflight_ov_orthkd.py` 中改为：

```python
loss, stats = loss_module(
    student_segment_logits=outputs["segment_logits"],
    student_decision_features=outputs["decision_features"],
    student_audio_aux_features=outputs["audio_aux_features"],
    student_query_features=outputs["query_features"],
    segment_labels=labels,
    sequence_mask=sequence_mask,
    strong_teacher_logits=strong_teacher_logits,
    strong_teacher_features=strong_teacher_features,
    weak_teacher_logits=weak_teacher_logits,
    weak_teacher_features=weak_teacher_features,
    text_embeddings=text_embeddings,
    strong_teacher_logit_mask=strong_teacher_logit_mask,
    strong_teacher_feature_mask=strong_teacher_feature_mask,
    weak_teacher_logit_mask=weak_teacher_logit_mask,
    weak_teacher_feature_mask=weak_teacher_feature_mask,
    text_valid=text_valid,
)
```

变量命名统一：不要继续把 weak feature mask 和 weak logit mask 混成一个 `weak_teacher_mask`。`build_model_and_loss` 必须根据 `reproduction.implementation_mode` 选择 `OVOrthKDLegacyLoss` 或 camera-ready `OVOrthKDLoss`，并拒绝交叉搭配。

---

# 6. 删除伪造音频 logits

从训练脚本中彻底删除下面的逻辑及相关注释：

```python
if loss_module.alpha_weak_logit > 0 and weak_teacher_logit_mask.sum() == 0:
    weak_teacher_logits = strong_teacher_logits.clone()
    noise = torch.randn_like(weak_teacher_logits) * 0.5
    weak_teacher_logits = weak_teacher_logits + noise
    weak_teacher_logit_mask = strong_teacher_logit_mask
```

替换成 fail-fast：

```python
if loss_module.alpha_weak_logit > 0 and float(weak_teacher_logit_mask.sum()) <= 0:
    raise RuntimeError(
        "alpha_weak_logit > 0, but the batch contains no real weak-teacher logits. "
        "Synthetic logits are forbidden in paper reproduction."
    )
```

论文复现配置必须显式包含：

```yaml
loss:
  alpha_strong_logit: 0.0
  alpha_weak_logit: 0.0
```

---

# 7. 严格数据和教师工件模式

## 7.1 新增参数

给 `QueryConditionedOVAvelDataset` 增加：

```python
path_root: str = "."
required_artifacts: Sequence[str] | None = None
```

初始化：

```python
self.path_root = Path(path_root).expanduser().resolve()
self.required_artifacts = set(required_artifacts or [])
```

统一路径解析：

```python
def _resolve_path(self, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = self.path_root / path
    return path.resolve()
```

所有 frame、spectrogram、audio/teacher `.npy`、text embedding 的相对路径都必须通过 `_resolve_path`，不能依赖启动脚本时的当前工作目录。

## 7.2 缺工件时 fail fast

新增：

```python
def _artifact_required(self, field_name: str) -> bool:
    return field_name in self.required_artifacts
```

在 `_load_teacher_tensor` 中，`array is None` 时：

```python
if array is None:
    if self._artifact_required(field_name):
        raise FileNotFoundError(
            f"Required artifact '{field_name}' is missing for record "
            f"{record.get('id', '<unknown>')}: {value}"
        )
    return (
        torch.zeros(target_len, expected_dim, dtype=torch.float32),
        torch.zeros(target_len, dtype=torch.float32),
    )
```

在 `_load_text_embedding` 中同理检查 `text_embedding`。

新复现配置：

```yaml
data:
  path_root: "."
  allow_missing_modalities: false
  strict_alignment: true
  required_artifacts:
    - strong_teacher_features
    - weak_teacher_features
    - text_embedding
```

因为默认 `alpha_strong_logit=0`，`strong_teacher_logits` 不应作为主训练强制工件；但教师导出与 analysis control 仍应生成并审计它。

## 7.3 DataLoader 确定性

加入：

```python
import random


def seed_worker(worker_id: int) -> None:
    del worker_id
    worker_seed = torch.initial_seed() % (2**32)
    np.random.seed(worker_seed)
    random.seed(worker_seed)
```

创建 generator：

```python
generator = torch.Generator()
generator.manual_seed(int(config.get("seed", 42)))
```

三个 DataLoader 均传入：

```python
worker_init_fn=seed_worker,
generator=generator,
```

验证/test 不 shuffle，但仍应固定 worker seed，确保 transform 或第三方库没有隐式随机性。

---

# 8. 训练脚本可复现性和证据链

## 8.1 确定性设置

把 `set_seed` 扩展为：

```python
def set_seed(seed: int, deterministic: bool = True) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    if deterministic:
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        torch.use_deterministic_algorithms(True, warn_only=True)
    else:
        torch.backends.cudnn.benchmark = True
```

配置：

```yaml
training:
  deterministic: true
```

调用：

```python
set_seed(
    int(config.get("seed", 42)),
    deterministic=bool(config.get("training", {}).get("deterministic", True)),
)
```

## 8.2 修复 early-stop 配置读取

当前实现只在 CLI 提供值时生效。改为：

```python
raw_patience = (
    args.early_stop_patience
    if args.early_stop_patience is not None
    else train_cfg.get("early_stop_patience")
)
early_stop_patience = None if raw_patience is None else max(1, int(raw_patience))

early_stop_min_delta = (
    float(args.early_stop_min_delta)
    if args.early_stop_min_delta is not None
    else float(train_cfg.get("early_stop_min_delta", 0.0))
)
```

同时把 argparse 的 `--early-stop-min-delta` 默认值改为 `None`，否则无法区分“用户没传”和“用户显式传 0”。

## 8.3 `max_train_steps` 语义

当前实现的 `max_train_steps` 是“每个 epoch 最多跑多少 batch”，不是全局 step。请改名/兼容为：

```yaml
training:
  max_batches_per_epoch: null
  max_optimizer_steps: null
```

并维护 `global_step`。CLI 旧参数 `--max-train-steps` 可保留为 deprecated alias，但日志必须写明解释。不要把论文的 `step400` 自动等同于任一字段；该事实尚未恢复。

## 8.4 Scheduler 配置化，但不猜论文参数

支持至少：

```yaml
training:
  scheduler:
    type: cosine
```

和：

```yaml
training:
  scheduler:
    type: step
    step_size: 400
    gamma: 0.1
    interval: optimizer_step
```

但是 `configs/ov_orthkd_mm26_repro.yaml` 中应标注 scheduler 为 `UNRESOLVED`，并由 `validate_repro_config` 或训练前检查拒绝完整训练，直到恢复原始 schedule。Smoke 配置可以用 cosine，仅验证流水线。

推荐实现：

```python
def build_scheduler(optimizer, train_cfg, epochs, steps_per_epoch):
    cfg = train_cfg.get("scheduler", {})
    kind = str(cfg.get("type", "cosine")).lower()
    if kind == "cosine":
        return CosineAnnealingLR(optimizer, T_max=epochs), "epoch"
    if kind == "step":
        from torch.optim.lr_scheduler import StepLR
        step_size = int(cfg["step_size"])
        gamma = float(cfg.get("gamma", 0.1))
        interval = str(cfg.get("interval", "epoch"))
        return StepLR(optimizer, step_size=step_size, gamma=gamma), interval
    if kind in {"unresolved", "blocked"}:
        raise RuntimeError(
            "Paper reproduction scheduler is unresolved. Recover the archived setting "
            "before launching a full run."
        )
    raise ValueError(f"Unsupported scheduler type: {kind}")
```

Smoke 配置不要使用 unresolved。

## 8.5 保存完整运行证据

每次运行至少输出：

```text
runtime.json
resolved_config.yaml
git_state.json
requirements_freeze.txt
manifest_hashes.json
history.jsonl
best.pt
last.pt
best_validation_predictions.npz
test_predictions.npz
final_metrics.json
train.log
```

`runtime.json` 至少包含：

```python
{
    "python": sys.version,
    "platform": platform.platform(),
    "torch": torch.__version__,
    "torch_cuda": torch.version.cuda,
    "cudnn": torch.backends.cudnn.version(),
    "cuda_available": torch.cuda.is_available(),
    "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "gpu_capability": torch.cuda.get_device_capability(0) if torch.cuda.is_available() else None,
    "gpu_count": torch.cuda.device_count(),
    "seed": seed,
    "deterministic": deterministic,
}
```

`git_state.json`：

```python
{
    "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "branch": subprocess.check_output(["git", "branch", "--show-current"], text=True).strip(),
    "status_porcelain": subprocess.check_output(["git", "status", "--porcelain"], text=True),
    "diff_stat": subprocess.check_output(["git", "diff", "--stat"], text=True),
}
```

manifest 使用流式 SHA256：

```python
def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
```

每个 epoch 往 `history.jsonl` 追加一行，包含 epoch、global_step、learning rate、所有 loss 分量、val metrics、是否保存 best、耗时和 peak memory。

`last.pt` 每个 epoch 覆盖保存；`best.pt` 由 validation AP 选择。完整训练结束后必须重新加载 `best.pt` 再评价 val/test，不能直接使用内存中最后一个 epoch 的模型。

---

# 9. 评价修正

## 9.1 预测导出

评价函数应同时收集：

```text
sample id
query/category
seen/unseen type
segment index
label
logit
probability
sequence mask
```

建议 NPZ 字段：

```python
ids, queries, split_types, sample_offsets, segment_indices, labels, logits, probabilities
```

不要只保存 flatten 后的数组而丢失样本与类别信息。

## 9.2 必报指标

对 total、seen、unseen 分别计算：

```text
accuracy
segment F1 at threshold 0.5
segment AP
segment AUROC
positive rate
sample count
segment count
```

阈值校准流程：

1. 只在 validation 全集上选择最佳 F1 阈值；
2. 固定该阈值；
3. 一次性应用到 test；
4. 不能在 test 上重新选阈值；
5. 保存 validation threshold 和 PR 曲线。

论文对齐目标参考：

```text
Test AP       0.816
Test AUROC    0.750
F1@0.5        0.596
Calibrated F1 0.781
Unseen F1@0.5 0.584
Seen F1@0.5   0.625
Total F1@0.5  0.596
```

这些是目标值，不是代码正确性的单一判据；教师 checkpoint、schedule 或分段协议不同都可能造成明显偏差。

## 9.3 效率计时

`measure_efficiency.py` 在 warmup 前后和正式计时前后加入：

```python
if device.type == "cuda":
    torch.cuda.synchronize()
```

推荐用 `torch.cuda.Event`：

```python
starter = torch.cuda.Event(enable_timing=True)
ender = torch.cuda.Event(enable_timing=True)
starter.record()
for _ in range(iterations):
    with torch.inference_mode():
        _ = model(...)
ender.record()
torch.cuda.synchronize()
avg_ms = starter.elapsed_time(ender) / iterations
```

正式效率应分别报告实际数据 $T=10$ 和论文表格使用的 $T=16$（若最终确认论文确实用 16），不能把二者混为一个结果。

---

# 10. 新增论文一致性测试

创建 `tests/test_paper_faithfulness.py`。

## 10.1 定位头必须读取 decision path

```python
def test_localization_head_reads_decision_projection():
    model = build_tiny_test_student(path_mode="explicit_projected")
    captured = {}

    def hook(_module, inputs):
        captured["head_input"] = inputs[0].detach().clone()

    handle = model.segment_head.register_forward_pre_hook(hook)
    outputs = model(**make_tiny_batch())
    handle.remove()

    assert torch.allclose(captured["head_input"], outputs["decision_features"])
    assert captured["head_input"].shape[-1] == model.projection_dim
```

## 10.2 文本损失公式手算

```python
def test_paper_text_alignment_uses_mapped_cosine_probability():
    student = torch.tensor([[[0.0, 1.0], [0.0, -1.0]]])
    text = torch.tensor([[1.0, 0.0]])
    labels = torch.tensor([[1.0, 0.0]])

    terms = paper_text_alignment_terms(student, text, labels)
    expected = torch.full_like(terms, torch.log(torch.tensor(2.0)))
    assert torch.allclose(terms, expected, atol=1e-6)
```

这两个 student vector 与 text 正交，cosine 为 0，映射概率为 0.5，所以 BCE 必须为 $\log 2$。这能直接抓住原实现 `cos/0.07 + BCEWithLogits` 的错误。

## 10.3 关闭 logit KD 时不要求 logits

```python
def test_disabled_logit_kd_does_not_require_teacher_logits():
    loss_module = make_loss(alpha_strong_logit=0.0, alpha_weak_logit=0.0)
    loss, stats = loss_module(
        strong_teacher_logits=None,
        weak_teacher_logits=None,
        # 其余 feature/text/GT 张量完整
        **make_loss_batch(),
    )
    assert torch.isfinite(loss)
    assert stats["strong_logit"] == 0.0
    assert stats["weak_logit"] == 0.0
```

## 10.4 开启某项但缺工件时必须报错

分别测试：

```text
alpha_strong_feat > 0 but strong feature missing
alpha_weak_feat > 0 but weak feature missing
alpha_text_align > 0 but text embedding missing
alpha_orth > 0 but either feature/mask missing
alpha_weak_logit > 0 but real weak logits missing
```

必须匹配清晰错误信息。

## 10.5 严格数据模式

创建 manifest 缺 `weak_teacher_features_path`：

```python
with pytest.raises(FileNotFoundError, match="weak_teacher_features"):
    _ = dataset[0]
```

同时测试非严格 baseline 配置仍可返回零 tensor，不破坏旧 smoke 功能。

## 10.6 路径解析

从非仓库 CWD 启动测试，manifest 中使用相对路径；设置 `path_root` 后仍能正确读取。

## 10.7 禁止合成弱 logits

对训练脚本做源代码或行为测试，确保不存在：

```text
jittered strong teacher logits
torch.randn_like(weak_teacher_logits)
weak_teacher_logits = strong_teacher_logits.clone()
```

行为测试优先于脆弱的字符串测试。

---

# 11. 新复现配置

## 11.1 `configs/ov_orthkd_mm26_repro.yaml`

```yaml
seed: 42

project:
  name: "ov_orthkd_mm26_reproduction"
  stage: "conference_reproduction"

reproduction:
  paper: "ACM MM 2026 OV-OrthKD"
  base_commit: "dca9f052fbe4a1e9d7982f24bdcec3edf1363fd4"
  full_run_blocked: true
  # 仅允许：camera_ready_explicit_paths | legacy_collaboration
  implementation_mode: "camera_ready_explicit_paths"
  blocked_archival_facts:
    - "T=10 official labels versus 16 temporal segments stated in camera-ready implementation table"
    - "exact InternVideo2 model class and three checkpoint identities"
    - "meaning of step400 schedule, scheduler gamma/interval, early-stop patience"
    - "student pretrained initialization and exact train augmentation"
    - "visual feature L2 reduction: sum versus mean"
    - "paper additive fusion + TransformerLayer versus current concat-MLP token fusion"

task:
  name: "open_vocabulary_audio_visual_event_localization"
  label_mode: "query_conditioned_binary"

teachers:
  strong_visual:
    name: "UNRESOLVED: exact InternVideo2 checkpoint required"
    backend: "internvideo2_clip_b14"
    export: "segment_logits + segment_features"
  weak_audio:
    name: "BEATs pretrained"
    backend: "beats"
    export: "segment_features_only"
  text_prototype:
    name: "Microsoft CLAP text encoder"
    backend: "clap"
    export: "query_embeddings"

data:
  path_root: "."
  train_manifest: "data/ov_ave/train.jsonl"
  val_manifest: "data/ov_ave/val.jsonl"
  test_manifest: "data/ov_ave/test.jsonl"
  image_size: 224
  batch_size: 12
  num_workers: 8
  pin_memory: true
  max_segments: 16  # capacity upper bound; actual observed segment length must be audited
  allow_missing_modalities: false
  strict_alignment: true
  required_artifacts:
    - strong_teacher_features
    - weak_teacher_features
    - text_embedding
  strong_teacher_dim: 512
  weak_teacher_dim: 768
  strong_teacher_logit_dim: 1
  weak_teacher_logit_dim: 1
  text_dim: 1024
  train_augment: true  # provisional until archived config is recovered

student:
  visual_backbone: "convnextv2_tiny.fcmae_ft_in22k_in1k"
  audio_backbone: "tf_efficientnetv2_b2.in1k"
  fusion_dim: 384
  projection_dim: 256
  path_mode: "explicit_projected"
  temporal_layers: 4
  temporal_heads: 8
  temporal_dropout: 0.1
  pretrained: false  # provisional until archived config is recovered

loss:
  projection_dim: 256
  temperature: 2.0
  alpha_bce: 1.0
  alpha_strong_logit: 0.0
  alpha_weak_logit: 0.0
  alpha_strong_feat: 0.4
  alpha_weak_feat: 0.1
  alpha_text_align: 0.8
  alpha_orth: 0.5
  text_alignment_mode: "paper_probability"
  confidence_weighting: true
  confidence_scale: 2.0

training:
  deterministic: true
  epochs: 30
  learning_rate: 0.0002
  weight_decay: 0.0001
  grad_clip: 1.0
  mixed_precision: true
  max_batches_per_epoch: null
  max_optimizer_steps: null
  early_stop_patience: null
  early_stop_min_delta: 0.0
  scheduler:
    type: "UNRESOLVED"

logging:
  log_dir: "outputs/ov_orthkd_mm26_reproduction"
  save_last: true
  save_predictions: true
  save_environment: true
```

`build_model_and_loss` 必须进行唯一映射，不允许任意交叉组合：

```text
camera_ready_explicit_paths -> student.path_mode=explicit_projected + OVOrthKDLoss
legacy_collaboration        -> student.path_mode=legacy_shared      + OVOrthKDLegacyLoss
```

若配置中的 `implementation_mode`、`student.path_mode` 或 loss class 不一致，程序必须在构建阶段报错。camera-ready 配置固定使用 `text_alignment_mode: paper_probability`；`legacy_logit_temperature` 只允许出现在受控的公式比较测试中，完整 legacy 复跑由独立的 `OVOrthKDLegacyLoss` 负责。

完整训练入口必须检测：

```yaml
reproduction.full_run_blocked: true
```

除非显式 `--allow-blocked-reproduction`，否则拒绝运行超过 smoke/preflight 的训练。即使允许，也必须在输出目录写醒目的 `NON_CANONICAL_UNRESOLVED_RUN.txt`。

## 11.2 `configs/ov_orthkd_mm26_smoke.yaml`

复制上述方法结构，但：

```yaml
reproduction:
  full_run_blocked: false

data:
  train_manifest: "data/ov_ave_smoke/train.jsonl"
  val_manifest: "data/ov_ave_smoke/val.jsonl"
  test_manifest: "data/ov_ave_smoke/test.jsonl"
  batch_size: 2
  num_workers: 0
  train_augment: false
  allow_missing_modalities: false

student:
  pretrained: false

training:
  epochs: 2
  max_batches_per_epoch: 2
  scheduler:
    type: cosine

logging:
  log_dir: "outputs/ov_orthkd_mm26_smoke"
```

Smoke manifest 使用 mock 教师工件，不得冒充真实结果。

---

# 12. 5090 环境准备

RTX 5090 是 Blackwell、计算能力 `sm_120`。现有 `setup_server.sh` 默认 `cu124`，必须增加 `cu128` 或更新的 CUDA 12.8+ wheel 通道。

## 12.1 修改 setup helper

usage：

```bash
--torch <cpu|cu121|cu124|cu128>
```

case 增加：

```bash
cu128)
  TORCH_INDEX="https://download.pytorch.org/whl/cu128"
  ;;
```

建议本机：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r requirements.txt
python -m pip check
```

不要先装 cu124 再覆盖；从干净 venv 开始。

## 12.2 新增 `scripts/verify_cuda_runtime.py`

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import platform
import sys
import time

import torch


def main() -> None:
    report = {
        "python": sys.version,
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
    }
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available")

    device = torch.device("cuda:0")
    report.update(
        {
            "gpu": torch.cuda.get_device_name(0),
            "capability": torch.cuda.get_device_capability(0),
            "cudnn": torch.backends.cudnn.version(),
        }
    )
    if tuple(report["capability"]) < (12, 0):
        print("Warning: target machine is not the expected RTX 5090 / sm_120 environment")

    x = torch.randn(2048, 2048, device=device, dtype=torch.float16)
    torch.cuda.synchronize()
    start = time.perf_counter()
    y = x @ x
    torch.cuda.synchronize()
    report["matmul_ms"] = (time.perf_counter() - start) * 1000.0
    report["finite"] = bool(torch.isfinite(y).all().item())
    report["mean_abs"] = float(y.abs().mean().item())
    report["allocated_gb"] = torch.cuda.memory_allocated() / (1024**3)
    report["reserved_gb"] = torch.cuda.memory_reserved() / (1024**3)

    print(json.dumps(report, indent=2))
    if not report["finite"]:
        raise RuntimeError("CUDA matmul produced non-finite values")


if __name__ == "__main__":
    main()
```

运行：

```bash
python scripts/verify_cuda_runtime.py | tee outputs/cuda_runtime_check.json
```

实际安装成功后冻结：

```bash
python -m pip freeze | sort > requirements-lock-5090.txt
nvidia-smi > nvidia-smi.txt
```

---

# 13. 数据集下载与 manifest 构建

## 13.1 获取官方文件

克隆官方元数据仓库：

```bash
mkdir -p external data/raw/ov_avebench_preprocessed

git clone --depth 1 https://github.com/jasongief/OV-AVEL.git external/OV-AVEL

cp external/OV-AVEL/meta_anno_files/released_ovavel_dataset_anno.json \
  data/raw/ov_avebench_preprocessed/
cp external/OV-AVEL/meta_anno_files/ovave_dataset_meta.csv \
  data/raw/ov_avebench_preprocessed/
```

预处理音频/视觉数据需要从官方 README 的 SharePoint 链接手动下载。不要使用不明镜像。下载后先查看压缩包目录：

```bash
find data/downloads -maxdepth 3 -type f -printf '%p\n' | sort | head -100
```

解压后，目标结构应被整理为：

```text
data/raw/ov_avebench_preprocessed/
├── released_ovavel_dataset_anno.json
├── ovave_dataset_meta.csv
└── ovave_dataset_preprocessed/
    ├── train/
    │   ├── audio/<category>/<clip_id>.wav
    │   └── video/<category>/<clip_id>/*.png
    ├── val/
    └── test/
```

不要在不检查压缩包根目录的情况下直接 `mv *`，避免多套同名文件夹互相覆盖。

## 13.2 先构建小样本

```bash
python scripts/build_ov_avebench_source_manifests.py \
  --dataset-root data/raw/ov_avebench_preprocessed/ovave_dataset_preprocessed \
  --annotation-json data/raw/ov_avebench_preprocessed/released_ovavel_dataset_anno.json \
  --meta-csv data/raw/ov_avebench_preprocessed/ovave_dataset_meta.csv \
  --output-dir data/ov_ave_smoke/source \
  --spectrogram-dir data/raw/ov_avebench_preprocessed/generated_specs_smoke \
  --image-size 224 \
  --sample-rate 16000 \
  --n-mels 128 \
  --limit-per-split 8
```

先审计 smoke source manifest；通过后再构建全量：

```bash
python scripts/build_ov_avebench_source_manifests.py \
  --dataset-root data/raw/ov_avebench_preprocessed/ovave_dataset_preprocessed \
  --annotation-json data/raw/ov_avebench_preprocessed/released_ovavel_dataset_anno.json \
  --meta-csv data/raw/ov_avebench_preprocessed/ovave_dataset_meta.csv \
  --output-dir data/ov_ave/source \
  --spectrogram-dir data/raw/ov_avebench_preprocessed/generated_specs \
  --image-size 224 \
  --sample-rate 16000 \
  --n-mels 128
```

注意：官方数据已经按 10 个 1 秒片段提供中间帧。现有 builder 会把一个 clip 文件夹里的所有图片均分成 `len(labels)` 个组，再选每组中间帧。R0 不要擅自改数据语义；但 `audit_mm26_reproduction.py` 必须记录每个 clip 的原始帧数量、分组结果和 label 长度。若官方文件夹恰好已有 10 张中间帧，则每组应是一张；若不是，必须在正式训练前确认会议实验到底使用了哪些帧。

---

# 14. 新增严格审计脚本

创建 `scripts/audit_mm26_reproduction.py`，参数至少支持：

```text
--train-manifest
--val-manifest
--test-manifest
--path-root
--stage source|exported
--artifact-scan none|sample|full
--sample-count
--output-json
--expected-segments auto|10|16
--fail-on-warning
```

## 14.1 必查项

全量 manifest：

```text
train records = 13,182
val records   = 5,798
test records  = 5,820
total         = 24,800
categories    = 67
seen classes  = 46
unseen classes= 21
```

还要检查：

1. 每条记录 id 非空；
2. 三个 split 内部无重复；
3. 三个 split 之间无 id 重叠；
4. labels 非空、只含 0/1；
5. 统计所有 label 长度及分布；
6. `segment_frame_paths`、spectrogram/audio segment 与 labels 严格对齐；
7. 所有路径存在；
8. query/category/seen-unseen 元数据完整；
9. 不存在 NaN/Inf；
10. 输出 manifest SHA256；
11. exported 阶段检查：
    - strong visual features `[T, 512]`；
    - strong visual logits `[T]` 或 `[T,1]`；
    - weak audio features `[T, 768]`；
    - text embedding `[1024]`；
12. 输出缺失工件、维度不匹配、异常数值和首批示例；
13. 任何 P0 错误必须非零退出。

## 14.2 T=10 / T=16 停止条件

审计报告必须有：

```json
{
  "segment_length_histogram": {"10": 24800},
  "configured_max_segments": 16,
  "resampling_performed_by_dataset": false
}
```

若原始标注全部是 10 段，而没有历史 16 段 manifest 或明确重采样协议，则：

- 保留真实 $T=10$；
- `max_segments=16` 只作为 positional capacity；
- 禁止为了匹配论文表格自行插值到 16；
- 把论文中的“16 temporal segments”记录为待作者确认的实现/写作差异。

---

# 15. 教师仓库与权重准备

## 15.1 第三方仓库

```bash
mkdir -p external checkpoints/internvideo2 checkpoints/beats checkpoints/clap

git clone --recursive https://github.com/OpenGVLab/InternVideo.git external/InternVideo
git clone --depth 1 https://github.com/microsoft/unilm.git external/unilm
git clone --depth 1 https://github.com/microsoft/CLAP.git external/CLAP
```

预期 wrapper 路径：

```yaml
teacher_export:
  internvideo2_repo_root: "external/InternVideo/InternVideo2/multi_modality"
  beats_repo_root: "external/unilm/beats"
  clap_repo_root: "external/CLAP"
```

安装各自依赖前先查看其官方 requirements；不要让第三方仓库无提示地降级当前 PyTorch。推荐：

```bash
python -m pip install --no-deps -e external/CLAP
python -m pip check
```

缺什么再显式安装什么，最后重新跑 CUDA 验证和仓库 tests。

## 15.2 必须恢复的 checkpoint 身份

不要在本任务书中猜 checkpoint URL。正式导出前必须得到：

```text
InternVideo2 model class
InternVideo2 vision checkpoint path + SHA256
InternVideo2 text checkpoint path + SHA256
InternVideo2 extra CLIP checkpoint path + SHA256
InternVideo2 num_frames per segment
BEATs pretrained checkpoint path + SHA256
CLAP checkpoint path + SHA256
CLAP version (expected wrapper default is 2023) + SHA256
```

优先搜索：

```bash
find "$HOME" /data /workspace -type f \
  \( -iname '*internvideo*' -o -iname '*beats*.pt' -o -iname '*clap*.pt' -o -iname '*clap*.pth' \) \
  2>/dev/null | sort > candidate_teacher_checkpoints.txt
```

如团队有旧服务器、NAS、W&B、TensorBoard 或实验压缩包，先恢复原文件。找不到时再联系原实验执行者确认；不能用“最相近名字”替代。

## 15.3 `inspect_teacher_identity.py`

脚本应打印并保存：

```text
wrapper class
upstream class
upstream repo git SHA
checkpoint absolute path
checkpoint SHA256
checkpoint top-level keys
feature dimension
num_frames
CLAP version
BEATs finetuned_model flag
one smoke sample output shape / finite / norm statistics
```

特别检查：配置写 Base/B14，但 wrapper 导入 `InternVideo2_CLIP_small`。在这一点解决前禁止全量 InternVideo2 export。

---

# 16. 教师工件导出

## 16.1 Smoke：必须先物理截断 manifest

当前 `--limit` 会把未导出的后续记录原样写入输出 manifest，因此这个输出不能用于训练。R0 应修复 export pipeline，增加：

```text
--truncate-output-on-limit
```

或直接规定当 `limit` 非空时只写 `updated_records`，不复制后续记录。为兼容旧行为，可新增显式 `copy_unprocessed_records` 参数，默认 false。

在修复前，smoke 使用：

```bash
mkdir -p data/ov_ave_smoke/export_source
for split in train val test; do
  head -n 8 "data/ov_ave/source/${split}_source.jsonl" \
    > "data/ov_ave_smoke/export_source/${split}_source.jsonl"
done
```

然后：

```bash
python scripts/export_teacher_artifacts.py \
  --config configs/ov_orthkd_mm26_repro.local.yaml \
  --source-manifest data/ov_ave_smoke/export_source/train_source.jsonl \
  --output-manifest data/ov_ave_smoke/train.jsonl \
  --artifact-dir data/teacher_cache/mm26_smoke/train \
  --device cuda \
  --overwrite
```

val/test 同理。

## 16.2 全量导出

只有在 teacher identity 和 smoke export 通过后才执行：

```bash
for split in train val test; do
  python scripts/export_teacher_artifacts.py \
    --config configs/ov_orthkd_mm26_repro.local.yaml \
    --source-manifest "data/ov_ave/source/${split}_source.jsonl" \
    --output-manifest "data/ov_ave/${split}.jsonl" \
    --artifact-dir "data/teacher_cache/mm26/${split}" \
    --device cuda
done
```

导出时建议分 split、可恢复、已存在工件跳过，并周期性输出进度和 ETA。不要用 `--overwrite` 重跑已验证的全量缓存，除非 checkpoint/hash 改变。

导出后：

```bash
python scripts/audit_mm26_reproduction.py \
  --train-manifest data/ov_ave/train.jsonl \
  --val-manifest data/ov_ave/val.jsonl \
  --test-manifest data/ov_ave/test.jsonl \
  --path-root . \
  --stage exported \
  --artifact-scan full \
  --expected-segments auto \
  --output-json reports/mm26_exported_artifact_audit.json
```

---

# 17. R0 本轮实际运行命令

本轮只执行以下内容：

```bash
source .venv/bin/activate

python -m pip check
python scripts/verify_cuda_runtime.py

python -m compileall -q src scripts tests
pytest -q
python scripts/smoke_test.py

# 使用 mock 工件或 tests 临时目录进行一批次 preflight；不得把 mock 结果写成论文结果。
python scripts/preflight_ov_orthkd.py \
  --config configs/ov_orthkd_mm26_smoke.yaml \
  --output-dir outputs/r0_preflight \
  --probe-samples 4 \
  --max-eval-batches 2

# 静态检查
git diff --check
git status --short
git diff --stat
```

若本地尚未放置 smoke manifests，Codex 应由测试 fixture 或 mock export pipeline 自动生成，不要因此下载完整数据。

---

# 18. 后续完整复现阶段

## R0：代码和证据链加固（本轮）

通过标准：

```text
all tests pass
paper-faithfulness tests pass
strict missing-artifact tests pass
5090 CUDA test pass
mock preflight forward/backward/resume/eval pass
no full dataset training launched
```

## R1：官方数据准备

通过标准：

```text
24,800 records
13,182 / 5,798 / 5,820 exact split counts
67 categories, 46 seen, 21 unseen
all files exist
segment-length histogram documented
manifest hashes fixed
```

## R2：真实教师工件

通过标准：

```text
all teacher identities and checkpoint hashes documented
one-sample and 8-sample smoke export passes
full train/val/test export passes
all feature/logit/text shapes and finite checks pass
```

## R3：单 seed 正式训练

先恢复所有 `BLOCKED_ARCHIVAL_FACTS`，将 `full_run_blocked` 设为 false，再执行：

```bash
CUDA_VISIBLE_DEVICES=0 python scripts/train_ov_orthkd.py \
  --config configs/ov_orthkd_mm26_repro.local.yaml \
  --output-dir outputs/mm26_repro/seed42
```

训练结束后：

```bash
python scripts/train_ov_orthkd.py \
  --config outputs/mm26_repro/seed42/resolved_config.yaml \
  --resume outputs/mm26_repro/seed42/best.pt \
  --eval-only \
  --output-dir outputs/mm26_repro/seed42/eval_best
```

并运行校准 F1/PR：

```bash
python scripts/evaluate_pr_f1.py \
  --model ov_orthkd=outputs/mm26_repro/seed42/best.pt \
  --output-dir outputs/mm26_repro/seed42/pr_f1
```

## R4：多 seed 和会议消融

单 seed 无明显协议错误后，再运行至少 5 个种子：

```text
42, 43, 44, 45, 46
```

报告 mean ± std，并复现：

```text
Student-only
Visual feature only
Visual + Orth
Decision KD analysis control
Symmetric/shared transfer control
w/o text
Full OV-OrthKD
Role swap
```

每个配置只能改变声称改变的组件，必须共享同一数据、教师缓存、初始化策略、scheduler 和评价代码。

---

# 19. 偏差排查顺序

若单 seed 与论文 AP 相差超过约 0.01，先不要盲目调超参数。按以下顺序排查：

1. 实际序列是 $T=10$ 还是 16；
2. 历史结果对应 legacy shared-head 还是 camera-ready explicit decision-head；
3. 历史文本损失是 temperature-logit BCE 还是论文 mapped-probability BCE；
4. query-aware fusion 是当前 concat-MLP 还是论文 additive + TransformerLayer；
5. InternVideo2 类和 checkpoint 是否完全一致；
6. localization head 在所声明模式下是否读取正确路径；
7. text loss 在所声明模式下是否使用正确公式；
8. BEATs/CLAP checkpoint 和预处理；
9. student backbone `pretrained`；
10. train augmentation；
11. scheduler 的 step400 含义；
12. early-stop patience 与 checkpoint selection；
13. visual L2 feature reduction 的 sum/mean；
14. spectrogram 生成参数与 1 秒裁剪；
15. seen/unseen 元数据映射；
16. validation/test threshold 是否泄漏。

上述容差只是工程预警线，不是统计学结论。只有完全锁定协议后，才讨论模型随机波动。

---

# 20. Codex 最终交付物

本轮 Codex 完成后必须给出：

```text
1. git diff --stat
2. 修改文件清单
3. 每个 P0/P1 问题的修复映射
4. 全部测试命令及退出码
5. CUDA runtime JSON
6. pytest 摘要
7. mock preflight 摘要
8. 尚未恢复的 BLOCKED_ARCHIVAL_FACTS
9. reports/R0_REPRO_HARDENING_REPORT.md
10. 一个干净 git commit
```

建议 commit message：

```text
repro: harden paper-faithful OV-OrthKD baseline
```

提交命令：

```bash
git add src scripts configs tests reports README.md
git diff --cached --check
git commit -m "repro: harden paper-faithful OV-OrthKD baseline"
git rev-parse HEAD
```

不要提交：

```text
.venv/
data/raw/
data/teacher_cache/
outputs/
third-party checkpoints
requirements-freeze 中可能含有本地 file:// 隐私路径的未经检查版本
```

---

# 21. 第一次自检：方法与代码一致性

提交前逐项回答 YES：

- [ ] `camera_ready_explicit_paths` 映射到 `explicit_projected + OVOrthKDLoss`，主定位头输入是 `decision_features`；`legacy_collaboration` 映射到 `legacy_shared + OVOrthKDLegacyLoss`，保持原 shared-head，且两种模式的输出、checkpoint 与报告标签不混用。
- [ ] visual teacher feature 只对齐 decision path。
- [ ] BEATs feature 只对齐 audio auxiliary path。
- [ ] CLAP text 只对齐 query path。
- [ ] camera-ready 模式的文本 cosine 先做 `(cos + 1) / 2` 再用 probability BCE；legacy 模式单独测试并明确标记。
- [ ] orthogonality 是 `cos^2(decision, audio_aux)`。
- [ ] 默认 strong logit KD 为 0。
- [ ] 默认 weak/audio logit KD 为 0。
- [ ] 代码中不存在伪造/加噪弱教师 logits。
- [ ] 开启任何蒸馏项但工件缺失时会 fail fast。
- [ ] 新复现配置不允许缺视觉、音频输入。
- [ ] 所有相对路径由 `path_root` 解析。
- [ ] 新接口在 train、preflight、evaluate、tests 中一致。
- [ ] 旧 baseline 配置没有被删除或无意改写。
- [ ] R0 没有实现扩刊自适应路由。

---

# 22. 第二次自检：复现与运行安全

- [ ] 基线 SHA 和当前工作 SHA 已记录。
- [ ] `python -m compileall -q src scripts tests` 通过。
- [ ] `pytest -q` 全部通过。
- [ ] `git diff --check` 无 whitespace error。
- [ ] `python -m pip check` 通过。
- [ ] RTX 5090 capability 显示 `(12, 0)`，CUDA matmul finite。
- [ ] PyTorch wheel 是 CUDA 12.8 或更新版本，不是 cu124。
- [ ] DataLoader worker 和 generator 已固定 seed。
- [ ] runtime、git state、config、manifest hash 可以追溯。
- [ ] best 和 last checkpoint 的语义明确。
- [ ] test 阈值不在 test 上调参。
- [ ] `--limit` 导出不会产生半成品训练 manifest。
- [ ] 完整训练被 `BLOCKED_ARCHIVAL_FACTS` 正确拦截。
- [ ] 报告明确说明尚未执行真实数据/教师完整复现。

---

# 23. 本轮停止条件

以下任一情况发生时，Codex 应停止并在报告中给出证据，而不是绕过：

1. 当前仓库 SHA 与本任务书基线不同且存在未合并重要修改；
2. 模型改为 explicit decision path 后旧测试/接口无法安全迁移；
3. 第三方包要求把 PyTorch 降到不支持 RTX 5090 的版本；
4. 某项 paper-faithfulness test 无法在不改变论文定义的情况下通过；
5. 需要猜测 InternVideo2 checkpoint、scheduler 或 16 段重采样协议；
6. CUDA 出现 `no kernel image`, `sm_120 not compatible` 或非有限 matmul；
7. smoke 数据/工件被误用为正式结果。

报告必须区分：

```text
CONFIRMED_FIXED
CONFIRMED_REMAINING_BUG
BLOCKED_ARCHIVAL_FACT
NOT_EXECUTED
```

这能保证下一轮审计不会把“脚本能运行”误认为“论文已复现”。
