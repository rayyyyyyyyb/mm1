# Static-target coupling audit and clean-control plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Determine whether C1 failed because the zero-LR projector polluted global clipping, because student losses have intrinsic directional conflict, or because the teacher target is not query/label aligned, using only read-only evidence before any new training.

**Architecture:** Reuse the locked 5090 data loader, C0/C1 checkpoints, and T=10 evaluator. Add small read-only audit runners that emit deterministic JSON receipts; keep model/loss equations unchanged until all Phase-A gates are evaluated. Only if teacher alignment is adequate and the clean clipping equivalence check passes, add a positive-LR-only clipping scope and run one C2 800-applied-step validation control.

**Tech Stack:** Python 3.11 locked venv, PyTorch autograd, NumPy/scikit-learn metrics, YAML configs, pytest, Ruff.

**Spec:** `C:\Users\lwz20\.codex\attachments\a4ff61e9-dd41-4d53-becc-cc6ebaf1abeb\pasted-text.txt`

## Global Constraints

- Official task timeline is exactly `T_task=10`; `max_position_segments=16` remains capacity only.
- Phase A is read-only: no optimizer step, checkpoint write, cache overwrite, test evaluation, second seed, 3200-step extension, or Full training.
- A1 compares C0 last@applied-step-800 and C1 last@applied-step-800 on the same validation archive protocol; best-vs-best remains a separate model-selection view.
- A3 may call `autograd.grad` on fixed train batches but must not mutate parameters, buffers, RNG state, optimizer state, or checkpoints.
- C2, if authorized, is exactly 800 applied updates on validation only and differs from C1 only in clipping scope.
- Every action and result is appended byte-identically to `扩刊/all.md` and `扩刊/OV-OrthKD-R2/all.md`.

### Task 1: Fixed-budget last-checkpoint validation (A1)

**Files:**
- Create: `scripts/audit_static_target_fixed_budget.py`
- Test: `tests/test_static_target_fixed_budget.py`
- Report: `reports/formal_reproduction/student_shortcut_recovery/FIXED_BUDGET_LAST_COMPARISON.md`

**Interfaces:**
- `summarize_fixed_budget(predictions: Mapping[str, np.ndarray]) -> dict[str, Any]` validates official ten-segment offsets, computes AP/AUROC/predicted-positive rate, mixed pairwise concordance, and deterministic temporal-shuffle deltas.
- CLI accepts two existing validation NPZ archives and writes JSON only; it never constructs a model or optimizer.

- [x] Write tests for malformed offsets, exact ten-segment validation, and deterministic concordance/shuffle output.
- [x] Run the focused test and observe the expected missing-function failure before implementation.
- [x] Implement the pure summary helper by reusing `src.utils.zero_training_diagnostics.mixed_pairwise_concordance` and the existing formal prediction validator.
- [x] Run the focused test to green.
- [x] On 5090, run `train_ov_orthkd.py --eval-only --resume <C0 last.pt>` and the equivalent C1 command with `evaluation.run_test=false`, then run the new summary on both last archives. Preserve existing best archives unchanged.
- [x] Record last-vs-last and best-vs-best metrics and exit codes in the report and both ledgers.

### Task 2: Runtime feature-loss decomposition (A2)

**Files:**
- Create: `scripts/audit_feature_loss_runtime.py`
- Test: `tests/test_feature_loss_runtime.py`
- Report: `reports/formal_reproduction/student_shortcut_recovery/FEATURE_LOSS_RUNTIME_DECOMPOSITION.md`

**Interfaces:**
- `decompose_runtime_batch(student, loss_module, batch, device) -> dict[str, Any]` computes normalized `L_mean` and `L_centered`, exact identity residual, positive-label groups `k=0`, `1<=k<=9`, `k=10`, and `overall`.
- `module_gradient_receipts(...) -> dict[str, dict[str, float]]` reports gradient norms for visual encoder/projection, fusion, temporal encoder, decision projection, and segment head for each component.
- CLI loads initialization, C0 best/last, and C1 best/last, uses one fixed train-batch receipt, and writes no state.

- [x] Add tests using a tiny deterministic module and tensor batch to check component sums, groups, and no parameter mutation.
- [x] Run tests red, implement minimal pure decomposition/gradient receipt functions, and run tests green.
- [x] Run the read-only CLI once per requested state in the locked 5090 environment; verify state hashes before/after and write the report.

### Task 3: Same-student-parameter per-loss gradient conflict (A3)

**Files:**
- Create: `scripts/audit_per_loss_gradient_conflict.py`
- Test: `tests/test_per_loss_gradient_conflict.py`
- Report: `reports/formal_reproduction/student_shortcut_recovery/PER_LOSS_GRADIENT_CONFLICT_AUDIT.md`

**Interfaces:**
- `collect_loss_gradients(student, loss_module, batch, device) -> dict[str, dict[str, Any]]` computes `L_BCE`, `0.4*L_visual`, and `0.8*L_text` with `autograd.grad(..., allow_unused=True)` on the same fixed batch.
- `summarize_pairwise_cosines(receipts) -> dict[str, Any]` reports per-shared-module norms, BCE/visual, text/visual, BCE/text cosine mean/median/negative fraction, and finite-value counts.

- [x] Test cosine and zero-gradient handling with a tiny shared linear module.
- [x] Run red, implement detached gradient collection with strict state/RNG invariance checks, then run green.
- [x] Run on fixed train batches only; classify `INTRINSIC_GRADIENT_CONFLICT` only if median visual pair cosine is below `-0.2` and both gradient norms are non-negligible. Otherwise retain `GRADIENT_CONFLICT_NOT_YET_IDENTIFIED`.

### Task 4: Teacher label/boundary alignment (A4)

**Files:**
- Create: `scripts/audit_teacher_label_alignment.py`
- Test: `tests/test_teacher_label_alignment.py`
- Report: `reports/formal_reproduction/student_shortcut_recovery/TEACHER_LABEL_ALIGNMENT_AUDIT.md`

**Interfaces:**
- `derive_boundaries(labels: np.ndarray, mask: np.ndarray) -> dict[str, np.ndarray]` deterministically derives onset/offset from official T=10 labels and valid mask.
- `evaluate_representations(representations, labels, boundaries, queries, offsets) -> dict[str, Any]` reports mixed AP/AUROC, per-query macro, positive-vs-negative concordance, onset/offset AUROC, and query-position baseline deltas for raw, centered raw, static projected, centered static projected, and each representation concatenated with query.

- [x] Test boundary derivation at sequence edges, masked rows, and all-negative/all-positive samples.
- [x] Run red, implement validation-only representation evaluation with no guessed annotations, and run green.
- [x] Verify raw-video hash multiplicity versus query IDs, run the audit on locked validation/train feature arrays, and classify alignment only from measured centered-teacher-plus-query gain.

### Task 5: Optimizer-state-aware virtual replay (A5)

**Files:**
- Create: `scripts/audit_optimizer_virtual_replay.py`
- Test: `tests/test_optimizer_virtual_replay.py`
- Report: `reports/formal_reproduction/student_shortcut_recovery/OPTIMIZER_VIRTUAL_REPLAY_AUDIT.md`

**Interfaces:**
- `replay_virtual_update(parameters, optimizer_state, gradients, *, clip_scope) -> dict[str, Any]` clones tensors and AdamW moments in memory and computes parameter deltas for `current_global_all_grad_clip` and `updating_parameters_only_clip` without writing state.
- `summarize_virtual_deltas(...)` reports per-student-module gradient norm, delta norm, pairwise delta cosine, and norm ratio.

- [x] Test one-step AdamW replay against a real optimizer on a tiny model and verify input state is unchanged.
- [x] Run red, implement exact bias-correction/weight-decay replay from the checkpoint optimizer state, and run green.
- [x] Replay fixed C1 batches only; record whether clipping-tax removal materially changes student deltas.

### Task 6: Clean clipping scope and 10-step equivalence (conditional C2)

**Files:**
- Modify: `src/utils/optimizer_receipts.py`
- Modify: `scripts/train_ov_orthkd.py`
- Create: `configs/diagnostics/recovery/ov_orthkd_visual_only_sum_feature_seed42_c2_static_positive_lr_clip_800.yaml`
- Create: `scripts/check_static_clip_equivalence.py`
- Test: `tests/test_positive_lr_clip_scope.py`

**Interfaces:**
- `clip_gradients_with_receipt(parameters, groups, max_norm, clip_parameters=None)` clips only `clip_parameters` when supplied, while receipts continue to report every group.
- `gradient_clipping.scope` values are `all_parameters` (existing behavior) and `optimizer_groups_with_positive_lr`; unknown values fail closed.
- The equivalence checker runs ten deterministic batches comparing C2 static mode with `frozen_no_grad` for target outputs, student losses, pre/post-clip student gradients, and student parameters; only static-projector receipts may differ.

- [x] Add a failing test proving a zero-LR group is excluded from the clipping norm while positive-LR groups are unchanged.
- [x] Run red, implement scope selection and explicit receipts, and run green.
- [x] Run the 10-step equivalence check before any C2 training; abort if any student tensor differs.
- [x] Only if A4 does not block and equivalence passes, run one C2 800-applied-step validation-only control with the existing gates.

### Task 7: Final classification and handoff

**Files:**
- Create/update: `reports/formal_reproduction/student_shortcut_recovery/STATIC_TARGET_COUPLING_FINAL.md`
- Update: `reports/formal_reproduction/student_shortcut_recovery/projector_collapse_summary.json`
- Update: both `all.md` ledgers

- [x] Apply the naming table from the review: `CLIP_COUPLING_CAUSAL`, `INTRINSIC_STUDENT_LOSS_CONFLICT`, `BLOCKED_BY_TEACHER_LABEL_ALIGNMENT`, `STATIC_TARGET_NOT_SUFFICIENT`, or `MECHANISM_FAIL`; never use `BLOCKED_BY_GRADIENT_CONFLICT` without A3 evidence.
- [x] Keep formal Full, second seed, 3200-step extension, and test evaluation blocked unless a separate user instruction authorizes them.
- [x] Run locked focused tests, compileall, Ruff, diff check, and verify no large artifacts are staged.
- [x] Commit and push only source, compact evidence, configs, reports, and ledgers.
