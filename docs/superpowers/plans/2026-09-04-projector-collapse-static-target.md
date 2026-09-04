# OV-OrthKD Projector-Collapse Static-Target Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconstruct missing provenance, make teacher-projector update semantics explicit and auditable, and run only preregistered read-only audits plus bounded C0/C1 controls without authorizing formal Full.

**Architecture:** Keep the canonical T=10 data/evaluator and existing model paths unchanged. Add small pure utilities for provenance classification, feature-loss decomposition, projector update-mode resolution, optimizer receipts, and applied-step accounting; wire them into the diagnostic trainer only through explicit config fields. Produce immutable diagnostic reports and receipts under a noncanonical namespace, with hard gates before any 800/3200-step control or test evaluation.

**Tech Stack:** Python 3, PyTorch/AdamW/GradScaler, PyYAML, pytest, Ruff, Git, PowerShell/SSH for the 5090 runtime.

**Spec:** User-provided `OV-OrthKD Projector-Collapse Root-Cause and Static-Target Control` instructions in the pasted diagnosis, together with the repository's `MM26_OVORTHKD_R2_CONFERENCE_REPRODUCTION_GATE_AND_BASELINE_TASK.md` and the existing `reports/formal_reproduction/student_shortcut_recovery` evidence.

## Global Constraints

- Preserve official `T_task=10`; never add any 10→16 label or metric conversion.
- Do not run formal Full, a second seed, or any test evaluation for configuration selection.
- Do not overwrite canonical teacher caches, checkpoints, or formal reports; use a diagnostic/noncanonical namespace only.
- Missing historical evidence is `UNKNOWN`; no guessed optimizer, scheduler, pretrained, projector, or sampling values.
- `static_zero_lr_keep_grad` means `requires_grad=True`, backward participation, global clipping participation, optimizer-group `lr=0` and `weight_decay=0`, unchanged parameter tensors, and allowed optimizer moments.
- Every action and result must be appended byte-identically to `扩刊/all.md` and `扩刊/OV-OrthKD-R2/all.md`.

---

### Task 1: Provenance inventory and report

**Files:**
- Create: `scripts/audit_projector_provenance.py`
- Create: `tests/test_projector_provenance.py`
- Create: `reports/formal_reproduction/student_shortcut_recovery/PROVENANCE_AUDIT.md`
- Create: `reports/formal_reproduction/student_shortcut_recovery/provenance_audit.json`

**Interfaces:**
- `audit_projector_provenance.collect_inventory(repo_root: Path, search_roots: list[Path]) -> dict[str, Any]`
- Each fact row contains `status` in `{FOUND, NOT_FOUND, AMBIGUOUS}`, evidence paths/commit IDs, and a redacted excerpt; secrets are removed before serialization.

- [ ] **Step 1: Write failing tests** for status vocabulary, secret redaction, and no-guess behavior when only a task-book mention is found.
- [ ] **Step 2: Run `pytest tests/test_projector_provenance.py -q`** and observe the missing module failure.
- [ ] **Step 3: Implement bounded Git/filesystem search** using `git log --all -S/-G`, refs/reflog, YAML/config/log/history/checkpoint metadata paths; classify task-book-only hits as `NOT_FOUND` and conflicting historical hits as `AMBIGUOUS`.
- [ ] **Step 4: Run the focused tests, then execute the inventory locally** and write JSON/Markdown receipts without reading checkpoint tensor payloads into the report.
- [ ] **Step 5: Independently inspect the report for redaction and statuses; record results in both ledgers.**

### Task 2: Feature-loss decomposition helpers

**Files:**
- Modify: `src/losses/ov_orthkd_loss.py`
- Create: `tests/test_feature_loss_decomposition.py`
- Create: `scripts/audit_feature_loss_decomposition.py`

**Interfaces:**
- `decompose_temporal_squared_error(student: Tensor, target: Tensor, mask: Tensor) -> dict[str, Tensor]` returns `mean_term`, `temporal_term`, `total`, and grouped masked sums for `k=0`, `1<=k<=9`, `k=10`, `overall`.
- The identity is exact for each valid row: `sum_t ||s_t-y_t||² = T||mean(s)-mean(y)||² + sum_t ||center(s_t)-center(y_t)||²`.

- [ ] **Step 1: Write failing identity/mask/group tests.**
- [ ] **Step 2: Run focused tests and confirm failure.**
- [ ] **Step 3: Implement pure FP32-safe decomposition without changing the training loss default.**
- [ ] **Step 4: Add the fixed-batch audit runner that loads raw/init/best/last evidence and emits loss/gradient-ready JSON; never writes checkpoints.**
- [ ] **Step 5: Run focused tests, Ruff, and an independent numerical identity check; log outcomes.**

### Task 3: Explicit projector update modes

**Files:**
- Modify: `src/losses/ov_orthkd_loss.py`
- Modify: `scripts/train_ov_orthkd.py`
- Create: `src/utils/projector_update_modes.py`
- Create: `tests/test_projector_update_modes.py`

**Interfaces:**
- `resolve_projector_update_modes(loss_cfg: Mapping[str, Any]) -> dict[str, str]` supports `trainable`, `frozen_no_grad`, `static_zero_lr_keep_grad`; all-new-fields-missing falls back to the legacy boolean, while conflicting old/new fields raise `ValueError`.
- `apply_projector_update_modes(loss_module: nn.Module, modes: Mapping[str, str]) -> None` enforces `requires_grad` semantics and exposes mode metadata.
- `build_named_optimizer_groups(student, loss_module, train_cfg) -> list[dict[str, Any]]` returns named groups with parameter names/hash/count/lr/weight-decay/mode.

- [ ] **Step 1: Add failing tests** for all three modes, legacy fallback, conflict fail-closed, static tensor hash invariance, and trainable text/weak behavior.
- [ ] **Step 2: Run focused tests and confirm failure.**
- [ ] **Step 3: Implement mode resolution and apply it at model construction; preserve old behavior only when all three new keys are absent.**
- [ ] **Step 4: Replace the single anonymous AdamW parameter list with deterministic named groups; static groups use zero lr/weight decay but remain in backward/clip parameter list.**
- [ ] **Step 5: Run tests and independently compare baseline/static pre-step forward, loss, gradients, and group receipts.**

### Task 4: Applied-step, clipping, and AMP receipts

**Files:**
- Create: `src/utils/optimizer_receipts.py`
- Modify: `scripts/train_ov_orthkd.py`
- Create: `tests/test_optimizer_receipts.py`

**Interfaces:**
- `OptimizerStepReceipt` records attempted/applied/overflow steps, pre-clip global norm, clip coefficient, per-group norm/contribution, AMP scale, and clipped flag.
- `instrumented_optimizer_step(...) -> OptimizerStepReceipt` uses pre/post optimizer hooks and does not infer application from `global_step` alone.

- [ ] **Step 1: Write failing tests with a finite and an overflow-like scaler stub.**
- [ ] **Step 2: Run focused tests and confirm failure.**
- [ ] **Step 3: Implement hook-backed accounting, preserving the existing scheduler semantics and checkpoint compatibility.**
- [ ] **Step 4: Persist `optimizer_receipts.jsonl`, include receipts in diagnostic checkpoints, and ensure checkpoint `global_step` counts applied steps.**
- [ ] **Step 5: Run unit/integration tests and independent receipt-schema assertions.**

### Task 5: Read-only gradient/conflict/teacher-boundary audits

**Files:**
- Create: `scripts/audit_static_target_root_cause.py`
- Create: `tests/test_static_target_root_cause_audit.py`
- Create: `reports/formal_reproduction/student_shortcut_recovery/FEATURE_LOSS_DECOMPOSITION.md`
- Create: `reports/formal_reproduction/student_shortcut_recovery/GRADIENT_CONFLICT_AND_CLIP_AUDIT.md`
- Create: `reports/formal_reproduction/student_shortcut_recovery/AMP_APPLIED_STEP_AUDIT.md`
- Create: `reports/formal_reproduction/student_shortcut_recovery/TEACHER_BOUNDARY_SIGNAL_AUDIT.md`

**Interfaces:**
- One fixed-batch runner emits BCE, weighted visual, weighted text gradients by named module, pairwise gradient cosine, clipping distribution, AMP receipts, raw/query/centered probes, within-video concordance, and transition-boundary metrics.
- The runner is read-only and rejects missing/ambiguous source artifacts instead of substituting values.

- [ ] **Step 1: Write tests for fixed-batch determinism, module coverage, T=10 shape checks, and fail-closed missing evidence.**
- [ ] **Step 2: Run tests and confirm failure.**
- [ ] **Step 3: Implement the audit using existing loaders/probes and the decomposition helper; separate global micro, per-query macro, mixed subset, within-video, and boundary results.**
- [ ] **Step 4: Run on the 5090 against disposable output paths only; fetch reports and hashes.**
- [ ] **Step 5: Independently review numerical identities and report links; append both ledgers.**

### Task 6: Paired C0/C1 bounded-control runner

**Files:**
- Create: `configs/diagnostics/recovery/ov_orthkd_visual_only_sum_feature_seed42_c0_800.yaml`
- Create: `configs/diagnostics/recovery/ov_orthkd_visual_only_sum_feature_seed42_c1_static_800.yaml`
- Create: `scripts/run_static_target_control.py`
- Create: `tests/test_static_target_control.py`
- Create: `reports/formal_reproduction/student_shortcut_recovery/PROJECTOR_CONTROL_IMPLEMENTATION_RECEIPT.md`
- Create: `reports/formal_reproduction/student_shortcut_recovery/STATIC_TARGET_800STEP_RESULTS.md`

**Interfaces:**
- `run_paired_control(c0_config: Path, c1_config: Path, output_root: Path, steps: int = 800) -> dict[str, Any]` runs C0/C1 from identical seed and loader order, forbids test evaluation, and validates hard gates before declaring a result.
- C1 gates are exactly those specified by the user: unchanged strong-projector hash, projected-target std ≥0.15, decision std ≥0.003, projected→decision distance correlation ≥0.20, centered/total ratio ≥0.005, mixed concordance gain ≥0.02, AP not >0.02 below C0, no unexplained AMP skip, complete receipts.

- [ ] **Step 1: Write failing config-diff/gate tests and a test that test evaluation is rejected.**
- [ ] **Step 2: Run focused tests and confirm failure.**
- [ ] **Step 3: Implement paired-run orchestration with atomic noncanonical outputs and no canonical cache/checkpoint writes.**
- [ ] **Step 4: Run only after Tasks 1–5 pass; if any gate fails, stop without 3200-step extension.**
- [ ] **Step 5: Independently inspect C0/C1 config diff, hashes, receipts, and gate calculations; record final scientific state.**

### Task 7: Documentation, final verification, commit, and push

**Files:**
- Create/modify: `reports/formal_reproduction/student_shortcut_recovery/projector_collapse_summary.json`
- Modify: both `all.md` ledgers

- [ ] **Step 1: Generate a concise summary with one allowed final state: `STATIC_TARGET_MECHANISM_PASS`, `STATIC_TARGET_MECHANISM_FAIL`, `BLOCKED_BY_TEACHER_SIGNAL`, `BLOCKED_BY_GRADIENT_CONFLICT`, or `BLOCKED_BY_RUNTIME_INTEGRITY`.**
- [ ] **Step 2: Run the full relevant pytest suites, compileall, Ruff, `git diff --check`, and independent report/receipt assertions.**
- [ ] **Step 3: Review the complete staged diff for T=10 preservation, no Full authorization, no large assets, secret redaction, and ledger byte identity.**
- [ ] **Step 4: Commit one clean commit and push `repro/student-shortcut-recovery`; verify remote SHA and worktree cleanliness.**
- [ ] **Step 5: Append commit SHA, diff stat, every exit code, lock/hash values, final state, and repository URL to both ledgers.**
