# Student Shortcut Recovery Implementation Plan

> **Execution note:** implement sequentially in this session with red-green-refactor checkpoints. Subagent delegation is disabled by the active project instruction, so the required independent review is performed as a separate clean review pass.

**Goal:** Quantify query/sample shortcuts, measure real modality dependence, and test pretrained student backbones as one isolated recovery variable without starting formal Full training.

**Architecture:** Add two read-only diagnostic CLIs around existing manifest, prediction, loader, model and metric contracts. Keep the canonical trainer/model behavior unchanged. Derive one S3 configuration mechanically from S0 and receipt actual timm construction before launch.

**Tech Stack:** Python 3.11, NumPy, scikit-learn, PyTorch 2.10, timm, PyYAML, pytest, PowerShell, RTX 5090.

**Spec:** `docs/superpowers/specs/2026-08-31-student-shortcut-recovery-design.md`

## Global constraints

- Official metric timeline stays exactly `T_task=10`; `T_max=16` stays positional capacity.
- A0 tools are observation-only and cannot change training state.
- S3 changes only `student.pretrained` after identity/output normalization.
- No formal Full, S4, S5, S6, seed sweep or hyperparameter sweep in this plan.
- Large assets remain on the 5090.
- Record failures as well as successes in both ledgers.

---

### Task 1: Prediction-only A0 controls

**Files:**
- Create: `tests/test_student_shortcut_diagnostics.py`
- Create: `scripts/diagnose_student_shortcuts.py`

- [ ] Write literal synthetic tests for empirical query prior, unseen-query global fallback, query-position fallback, per-sample mean centering and deterministic within-sample shuffle.
- [ ] Run the focused test and retain the expected import failure as RED evidence.
- [ ] Implement strict JSONL/NPZ validation and the minimal pure functions required by the tests.
- [ ] Add CLI/report tests covering source hashes, schema, seed/repetition receipt and diagnostic claim label.
- [ ] Run focused GREEN tests and mutation-check sample-boundary and label/score permutation assertions.

### Task 2: Checkpoint modality and path-scale A0 controls

**Files:**
- Create: `tests/test_checkpoint_modality_diagnostics.py`
- Create: `scripts/diagnose_checkpoint_modalities.py`

- [ ] Write dummy-model/dummy-loader tests that prove visual/audio/both zero only content tensors and preserve all validity masks.
- [ ] Write exact tests for `[B,10]` fail-closed alignment, prediction metrics, tensor scale summaries and non-finite/missing outputs.
- [ ] Run focused RED and retain the expected import failure.
- [ ] Implement the diagnostic collector using existing config, loader, model and evaluator helpers without editing canonical forward/training behavior.
- [ ] Add checkpoint/config/Git receipts and write JSON atomically only after all modes pass.
- [ ] Run focused GREEN and cross-regression tests for canonical temporal guards.

### Task 3: Execute and audit real A0

**Files:**
- Create outside Git: `扩刊/复现/student_shortcut_recovery/`
- Create: `reports/formal_reproduction/student_shortcut_recovery/A0_RESULTS.md`
- Create: small JSON receipts under the same report directory.

- [ ] Commit the A0 implementation, build an incremental bundle, create an exact clean detached 5090 worktree and copy the nine verified asset junctions.
- [ ] Run prediction-only and checkpoint diagnostics for Student-only, Visual-only, canonical Full and S0 wherever exact source assets exist.
- [ ] Require exit 0, exact source hashes, official `T=10`, finite metrics and no matching training process before accepting a run.
- [ ] Compare query prior, query-position prior, centered AP, shuffled AP, zero-modality deltas and path-scale evidence; label missing inputs `UNAVAILABLE`.
- [ ] Copy back only small reports/receipts and independently audit their JSON schemas and hashes.

### Task 4: S3 configuration and pretrained receipt

**Files:**
- Create: `configs/diagnostics/recovery/ov_orthkd_s3_pretrained_seed42.yaml`
- Create: `tests/test_student_recovery_configs.py`
- Create: `tests/test_pretrained_backbone_receipt.py`
- Create: `scripts/audit_pretrained_backbones.py`

- [ ] Write a config-diff test proving the sole scientific difference from S0 is `student.pretrained`.
- [ ] Write mocked timm tests proving `True` reaches both encoder constructions, resolved pretrained metadata is captured, and failed downloads do not fall back.
- [ ] Run focused RED.
- [ ] Add the S3 config and minimal read-only backbone receipt implementation.
- [ ] Run focused GREEN plus model/builder/config regression tests.
- [ ] On the 5090, compare same-seed pretrained and random encoder-state SHA256 values and require both modality hashes to differ before launch.

### Task 5: Execute and audit S3

**Files:**
- Create outside Git: 5090 S3 output and `扩刊/复现/student_shortcut_recovery/s3/` small evidence.
- Modify: `reports/formal_reproduction/student_shortcut_recovery/A0_RESULTS.md`
- Create: `reports/formal_reproduction/student_shortcut_recovery/S3_RESULTS.md`

- [ ] Run S3 alone from an exact clean commit: seed 42, three epochs, 400 batches/epoch, scheduler `T_max=30`.
- [ ] Monitor persistent worker/process/GPU/log progress and preserve resumable state; do not run another experiment concurrently.
- [ ] Require three histories, three first-batch diagnostics, step 1,200, finite full validation/test predictions, exact `T=10`, behavior receipt and checkpoint/prediction hashes.
- [ ] Run A0 prediction and modality diagnostics on S3 and compare with S0/Student-only using localization-sensitive evidence.
- [ ] Stop before S4/S5/S6 or formal Full regardless of outcome.

### Task 6: Independent review, verification and publication

**Files:**
- Create: `reports/formal_reproduction/student_shortcut_recovery/IMPLEMENTATION_AUDIT.md`
- Modify: both `all.md` ledgers.

- [ ] Review every new line against the design without editing during the first review pass.
- [ ] Verify no trainer/model behavior, temporal conversion, canonical guard or formal config changed unintentionally.
- [ ] Run `compileall`, JSON/YAML parsing, `git diff --check`, all focused tests and full pytest on the exact candidate in the locked 5090 environment.
- [ ] Scan Git for datasets, caches, checkpoints, NPZ/ZIP/bundle/log assets, secrets and oversized files.
- [ ] Mirror required small evidence into the outer reproduction folder, verify file-by-file SHA256 equality, create a clean commit and push the branch.
