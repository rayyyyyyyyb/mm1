# OV-OrthKD Teacher-Signal and Shortcut-Agreement Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the invalid norm-based teacher-alignment audit with a train-fit/validation-eval, query-conditioned probe; audit teacher sampling, visual mean-component dominance, and pretrained representations; run only preregistered bounded controls whose gates pass.

**Architecture:** Keep the official T=10 loader, labels, evaluator, canonical teacher cache, and Full guard unchanged. Put the corrected teacher metrics and probe design in small pure utilities, use disposable sklearn readouts and temporary feature arrays for read-only phases, and isolate every optional control behind explicit validation-only configuration and receipt checks.

**Tech Stack:** Python 3.11 locked venv on RTX 5090, PyTorch, NumPy, scikit-learn, YAML, pytest, Ruff, and existing OV-AVEBench loaders/teacher utilities.

**Spec:** `C:\Users\lwz20\.codex\attachments\72c9ac88-c907-42c2-9377-9a2935b3e050\pasted-text.txt`

## Global Constraints

- Official task timeline is exactly `T_task=10`; no `10→16` conversion, interpolation, replication, or relabeling.
- Formal Full, second seed, 3,200-step extension, and test evaluation remain forbidden.
- Existing canonical teacher cache, checkpoints, and reports are immutable; Phase B uses a separate temporary cache only.
- Old A4 outputs remain available but are labelled `NORM_HEURISTIC_ONLY` and `QUERY_ALIGNMENT_NOT_TESTED`.
- Phase A, B, C, and D are read-only; controls are validation-only, seed 42, exactly 800 applied updates, and never auto-extended.
- Every command/result is appended byte-identically to `扩刊/all.md` and `扩刊/OV-OrthKD-R2/all.md`.

### Task 1: Correct query-conditioned teacher probe and transition metrics (Phase A)

**Files:**
- Create: `src/utils/teacher_signal_probe.py`
- Modify: `scripts/audit_teacher_label_alignment.py`
- Create: `tests/test_teacher_signal_probe.py`
- Modify: `tests/test_teacher_label_alignment.py`
- Create: `reports/formal_reproduction/student_shortcut_recovery/TEACHER_SIGNAL_CLOSURE_AUDIT.md`

**Interfaces:**
- `build_common_space(visual, query, *, output_dim, seed) -> (visual_common, query_common, receipt)` uses fixed train-independent random maps with explicit dimensions and seed.
- `build_interaction_design(visual_common, query_common, positions, mode) -> ndarray` returns equal-capacity QP `[0,q,0,p]` or interaction `[v,q,v*q,p]` designs.
- `fit_probe_and_score(train_x, train_y, eval_x, eval_y, sample_ids, query_ids, offsets, seed) -> dict` fits a disposable logistic probe on train segments and reports global/mixed AP/AUROC, per-query macro, tie-aware concordance, 100 within-video shuffles, and transition/onset/offset metrics.
- `derive_all_transitions(labels, mask) -> dict` reports every adjacent transition and continuity/multi-window counts; no first/last-only shortcut is permitted.

- [x] Write failing tests proving query embeddings and query IDs are separate, ties score `0.5`, all transitions are retained, and `[v,q,v*q,p]` is not a norm score.
- [x] Implement the common-space interaction probe and train-fit/validation-eval metrics without constructing a student optimizer.
- [x] Add direct-logit temporal shift sweep for offsets `{-2,-1,0,+1,+2}` and fail/report `TEMPORAL_INDEX_ALIGNMENT_FAILURE` when the best offset is not zero.
- [x] Run the corrected audit on locked train/validation manifests for raw, centered raw, initial static projected, centered static projected, QP, raw+query interaction, projected+query interaction, and cached direct logits.
- [x] Reclassify the old A4 report as heuristic-only and record Phase A status from measured probe gates.

### Task 2: Temporary real-multiframe teacher sampling diagnostic (Phase B)

**Files:**
- Create: `scripts/audit_teacher_sampling.py`
- Create: `tests/test_teacher_sampling_audit.py`
- Create: `configs/diagnostics/recovery/teacher_sampling_closure_seed42.yaml`
- Create: `reports/formal_reproduction/student_shortcut_recovery/TEACHER_SAMPLING_CLOSURE_AUDIT.md`

**Interfaces:**
- `select_stratified_mixed_records(manifest, count, seed) -> list[record]` deterministically selects 512–1024 mixed validation samples.
- `sample_segment_frames(video_path, segment_index, frame_count, policy) -> frames` validates real timestamps and produces uniform-in-segment frames.
- `compare_sampling_receipts(repeat_features, multiframe_features, labels, queries, offsets) -> dict` reuses Phase A probe/metric semantics and includes cache/source hashes.

- [x] Write tests for deterministic stratification, exact one-second boundaries, and rejection of missing/raw non-video inputs.
- [x] Implement a separate temporary-cache runner; never write canonical teacher cache or checkpoints.
- [x] Check raw-video availability and InternVideo2 preprocessing provenance on 5090; if unavailable, emit `BLOCKED_BY_TEACHER_FRAME_SAMPLING` with evidence rather than fabricate features.
- [x] Wire the positive raw-video branch through true uniform-center decoding, source/frame hashes, and the locked InternVideo2 teacher; fail closed when the locked teacher config or separate canonical train receipt is unavailable.
- [x] If inputs exist, compare repeat-keyframe×8 against true uniform 8-frame sampling with identical checkpoint/transform/query/timeline and report direct-logit, learned probe, shuffle, transition, and geometry metrics when raw videos are available; otherwise fail closed.

### Task 3: Stratified shortcut-agreement audit (Phase C)

**Files:**
- Create: `scripts/audit_shortcut_agreement.py`
- Create: `tests/test_shortcut_agreement.py`
- Create: `reports/formal_reproduction/student_shortcut_recovery/SHORTCUT_AGREEMENT_CLOSURE_AUDIT.md`

**Interfaces:**
- `stratified_batches(records, strata, batches_per_stratum, batch_size, seed) -> list[batch]` selects at least 32 independent batches for `k=0`, `1<=k<=9`, and `k=10`.
- `collect_loss_components(...) -> dict` records BCE, weighted visual/text losses, mean/centered decomposition, per-module gradient norms, same-parameter cosines, pre/post-clip norms, and virtual AdamW deltas without state mutation.
- `summarize_shortcut_agreement(receipts) -> dict` separately reports all-strata and mixed-only results and classifies `VISUAL_MEAN_COMPONENT_DOMINANCE_CONFIRMED` only from the measured mean/centered and clipping gate; it does not infer multi-loss directional agreement.

- [x] Write tests for stratum disjointness, mean-plus-centered identity, no parameter/RNG mutation, and tie-aware mixed aggregation.
- [x] Implement read-only collection with all required receipts and no optimizer step/checkpoint write.
- [x] Run on 5090 with mixed-label batches included; compare mean versus centered gradient ratios and update clipping across strata.
- [x] Record visual mean-component dominance without overclaiming multi-loss directional agreement.

### Task 4: Separate visual/audio pretrained fields and zero-training audit (Phase D)

**Files:**
- Modify: `src/models/ov_orthkd.py`
- Modify: `scripts/train_ov_orthkd.py`
- Modify: `scripts/audit_pretrained_backbones.py`
- Create: `tests/test_separate_pretrained_fields.py`
- Create: `configs/diagnostics/recovery/ov_orthkd_visual_only_c2_visual_pretrained_probe.yaml`
- Create: `reports/formal_reproduction/student_shortcut_recovery/PRETRAINED_REPRESENTATION_AUDIT.md`

**Interfaces:**
- `resolve_modality_pretrained(student_cfg) -> tuple[bool,bool]` uses `visual_pretrained` and `audio_pretrained`; legacy `pretrained` is used only when both new keys are absent.
- `OVOrthKDStudent(..., visual_pretrained=False, audio_pretrained=False)` constructs each encoder independently while preserving legacy calls.
- `build_pretrained_backbone_report` emits independent visual/audio receipts and refuses ambiguous mixed legacy/new settings.

- [x] Write failing tests for legacy fallback, independent overrides, and rejection of malformed fields.
- [x] Implement independent fields and receipts without changing existing default configs (`pretrained: false`).
- [x] Run zero-training QP/VQP probes for random visual, timm-pretrained visual, current C2 visual, and audio positive control on mixed validation data.
- [x] Mark D2 eligible only if the frozen pretrained visual probe passes its preregistered superiority gate; do not train during Phase D.

### Task 5: Conditional bounded controls and final handoff

**Files:**
- Create: `scripts/run_teacher_signal_controls.py`
- Create: `tests/test_teacher_signal_controls.py`
- Create/update: `reports/formal_reproduction/student_shortcut_recovery/TEACHER_SIGNAL_CLOSURE_FINAL.md`
- Update: `reports/formal_reproduction/student_shortcut_recovery/projector_collapse_summary.json`
- Update: both `all.md` ledgers

- [x] Add fail-closed authorization checks for D1 centered visual loss, D2 visual-pretrained, and D3 `loss.alpha_strong_logit`; each control changes exactly one registered variable relative to C2.
- [x] Run only eligible controls, each at seed 42, 800 applied updates, validation-only, with step receipts and no automatic extension.
- [x] Apply the allowed final-state naming table and keep Full/test/second-seed/3200 guards active regardless of outcomes.
- [x] Independently run local and locked-5090 tests, compileall, Ruff on changed files, JSON/report consistency, staged artifact-size checks, and `git diff --check`.
- [x] Commit and push only source, compact evidence, configs, reports, and ledgers; leave large data/cache/checkpoint artifacts on 5090.

### 2026-09-09 E0 scientific-state and D3 correction

- [x] Narrow Phase A to current-T10 direct-logit health, feature decodability,
  and unresolved archival Table 2 probe equivalence.
- [x] Rename Phase C to visual mean-component dominance.
- [x] Register D3 at `loss.alpha_strong_logit` and authorize it only from the
  Phase A direct-logit concordance/shift/shuffle gate.
- [x] Add positive authorization, exact single-diff, nonzero loss/gradient,
  and 800-applied-step/no-test receipt tests.
- [x] Mark D1 failed, D2 asset-blocked/unexecuted, and D3 repaired but
  positive-weight-provenance-blocked/unexecuted.
- [x] Replace the overbroad final state with
  `NO_EXECUTED_BOUNDED_CONTROL_RECOVERS_BOUNDARY` and keep formal Full on hold.
