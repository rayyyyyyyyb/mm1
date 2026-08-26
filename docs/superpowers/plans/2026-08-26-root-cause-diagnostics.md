# OV-OrthKD Root-Cause Diagnostic Plan

> Execute in order. Preserve the completed seed42 output and its source commit. Every run in this plan is a diagnostic control until a separate review promotes a recipe.

**Goal:** Determine whether the missing paper gain originates in evaluation, teacher assets, the shared student recipe, or Full-specific distillation, then prepare evidence-backed candidate fixes without fitting choices to the paper score.

**Fixed protocol:** Official OV-AVEBench `T_task=10`; `T_max=16` is positional capacity; one official keyframe per task segment for the student; visual teacher receives the repeated-keyframe `K_teacher=8` input already locked; one test view. No 10→16 transformation.

**Evidence hierarchy:** released historical code/checkpoint/output > locked official assets and receipts > paper equations/text > approved reconstruction assumption > new diagnostic hypothesis. The public `ScottBlizzard/OV-OrthKD` repository currently contains only a README, so paper/code mismatches remain candidate A/B factors rather than recovered history.

---

## Task 1: Freeze the review verdict and asset gates

- Record the attachment's supported claims, corrections, and unsupported assumptions.
- Record the exact visual-direct-logit audit against Table 2.
- Record Gate 1 as asset-blocked unless the exact Zhou official prediction/checkpoint is found; never substitute our prediction.
- Verify no formal seed42 byte is modified.

## Task 2: Repair and extend prediction-only diagnostics (TDD)

**Files:**

- Modify: `src/evaluation/ovavel_metrics.py`
- Modify: `scripts/train_ov_orthkd.py`
- Create: `scripts/diagnose_formal_predictions.py`
- Modify: `tests/test_reproduction_evaluation.py`
- Create: `tests/test_root_cause_diagnostics.py`

**RED:** Add tests requiring an official query/background segment F1 at an arbitrary frozen threshold and requiring the prediction audit to distinguish global-micro, per-sample macro, and per-query macro AP.

**GREEN:** Implement a separately named thresholded metric without weakening the fixed `@0.5` helper. Add the validation-selected segment F1 to evaluation reports. Implement a read-only NPZ audit with logit distributions and explicit aggregation semantics.

**Verify:** Focused tests, old evaluator parity tests, then full suite on the locked 5090 environment.

## Task 3: Build transparent teacher-cache diagnostics (TDD)

**Files:**

- Create: `scripts/diagnose_teacher_cache.py`
- Modify: `tests/test_root_cause_diagnostics.py`

**RED:** Fixture manifests must detect missing arrays, shape mismatch, non-finite values, and reproduce known direct-logit AP/AUROC.

**GREEN:** Implement full-split direct-logit audit and a separately labeled deterministic reconstruction probe. The probe receipt must expose preprocessing, optimizer, seed, regularization, convergence and aggregation details because the paper only says “light linear probe.”

**Verify:** Unit tests and real val/test direct-logit run. Run visual/audio probes only after the receipt schema and direct audit pass.

## Task 4: Generate exact-current-pipeline control configs (TDD)

**Files:**

- Create: `configs/diagnostics/ov_orthkd_mm26_student_only_seed42.yaml`
- Create: `configs/diagnostics/ov_orthkd_mm26_visual_only_seed42.yaml`
- Modify: `tests/test_reproduction_configs.py`

Derive both from the actual seed42 resolved config, changing only variant, output namespace, and intended loss switches. Student-only disables all teacher/text/orth losses. Visual-only keeps text alignment enabled and disables audio feature/logit and orth losses. Do not use the legacy `strong_feat_only` template.

**Verify:** Machine-check every non-allowlisted leaf equals the seed42 resolved config; run construction/preflight smoke without producing a formal claim.

## Task 5: Add opt-in early-epoch numerical instrumentation (TDD)

**Files:**

- Create: `src/utils/training_diagnostics.py`
- Modify: `scripts/train_ov_orthkd.py`
- Modify: `tests/test_root_cause_diagnostics.py`

Log only when explicitly enabled: logit/probability quantiles, positive/negative means, within-sample temporal variation, gates, decision/audio/query path norms/variance/effective rank, teacher-projector output statistics, named parameter-group gradient norms, head bias/weight norm, and teacher-projector parameter drift. Keep diagnostics out of model decisions and checkpoint selection.

## Task 6: Execute the low-cost gates on RTX 5090

- Run the prediction audit on immutable validation/test NPZ.
- Run visual direct logits and transparent visual/audio probes on locked cache.
- Publish small JSON/Markdown receipts under `reports/formal_reproduction/root_cause_diagnostics/` and mirror them into `扩刊/复现/root_cause_diagnostics/`.
- Decision gate: if teacher signals fail, stop before student training and diagnose export/preprocessing; if they pass, continue.

## Task 7: Execute current-pipeline Student-only and Visual-only controls

- Use a clean committed diagnostic worktree on 5090 and new output namespaces.
- Run Student-only first, then Visual-only; keep seed/data/student/batch/scheduler/evaluator identical to seed42 Full.
- Monitor persistent processes and validate all artifacts. Do not alter the completed Full output.
- Compare with paper controls only after comparing all three controls under identical current code lineage.

## Task 8: Prepare, but do not silently promote, candidate A/B fixes

Only after Tasks 1–7:

1. paper additive fusion vs current concat-MLP;
2. shared inference query projection vs loss-side text target projector;
3. trainable vs frozen teacher-side feature projectors;
4. pretrained false/true;
5. current 400-batch epoch vs full-loader/400-step validation interval;
6. KD augmentation on/off and visual L2 reduction.

Each factor must be opt-in, fingerprinted, tested, and changed one at a time. No candidate becomes canonical solely because it moves toward `0.816`.

## Task 9: Verification and handoff

- Run fresh full tests on the locked 5090 environment.
- Run artifact/schema/diff/sensitive-data/large-file checks.
- Update `CURRENT_STATUS.md`, reports, and both `all.md` ledgers.
- Commit and push a clean diagnostic branch; do not upload checkpoints, predictions, datasets, or teacher caches.
