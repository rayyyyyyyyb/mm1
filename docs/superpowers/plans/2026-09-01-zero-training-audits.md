# S7 Zero-Training Audits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce independently audited A–F zero/near-zero-training evidence from the locked S7 and canonical Full artifacts, then make a fail-closed S8 launch decision.

**Architecture:** Pure metric/pairing/image helpers live in one utility module, while two CLI programs bind them to S7 and Full checkpoints. The student forward path gains only default-disabled diagnostic controls, and a separate auditor recomputes artifact invariants before any S8 launch is allowed.

**Tech Stack:** Python 3.11, PyTorch, NumPy, scikit-learn, Pillow, pytest, Ruff, PowerShell 5.1, Git, Windows OpenSSH.

**Spec:** `docs/superpowers/specs/2026-09-01-zero-training-audits-design.md`

## Global Constraints

- Official task alignment is exactly ten one-second segments; no label/logit conversion is permitted.
- Existing S7 checkpoints and predictions are immutable inputs.
- No optimizer step may touch the loaded S7 or Full modules; F may update only disposable in-memory clones and writes no checkpoint.
- Single-class `k=0` and `k=10` strata expose undefined AUROC as `null` plus a reason.
- Reconstructed step zero must be labeled as reconstructed and matched to the stored step-zero diagnostic receipt.
- Runtime outputs refuse overwrite and use atomic temporary-file replacement.
- Checkpoints, NPZ arrays, official data, caches, and files larger than the publication threshold remain on the 5090.
- Formal Full, canonical guard state, S7 preregistration, and paper-table claims are unchanged.

---

### Task 1: Pure label-strata and intervention primitives

**Files:**
- Create: `src/utils/zero_training_diagnostics.py`
- Create: `tests/test_zero_training_diagnostics.py`

**Interfaces:**
- Produces: `validate_t10_predictions(predictions: Mapping[str, np.ndarray]) -> list[slice]`.
- Produces: `summarize_label_strata(predictions_by_mode: Mapping[str, Mapping[str, np.ndarray]], *, shuffle_repeats: int, seed: int, threshold: float) -> dict[str, Any]`.
- Produces: `mixed_pairwise_concordance(labels: np.ndarray, scores: np.ndarray, offsets: np.ndarray) -> dict[str, Any]`.
- Produces: `build_audio_donor_maps(ids: Sequence[str], queries: Sequence[str]) -> dict[str, np.ndarray]`.
- Produces: `temporally_shuffle_audio(batch: Mapping[str, Any], *, seed: int, sample_offset: int) -> dict[str, Any]`.

- [x] **Step 1: Write failing schema/strata tests**

Create a three-video `T=10` payload containing `k=0`, `k=4`, and `k=10`. Assert counts, mixed AP/AUROC, `null` single-class AUROC with reason, predicted-positive distributions, 25-seed mixed-only shuffle, and a hand-calculated positive/negative concordance. Assert `T=16`, malformed offsets, non-binary labels, and cross-mode metadata changes fail closed.

- [x] **Step 2: Run RED**

Run: `python -m pytest tests/test_zero_training_diagnostics.py -q`

Expected: collection fails with `ModuleNotFoundError: src.utils.zero_training_diagnostics`.

- [x] **Step 3: Implement the minimal strict metric core**

Use `average_precision_score`/`roc_auc_score` only when both classes exist. Shuffle scores independently within mixed samples with `np.random.default_rng(seed)` and report mean/std/min/max/drop for both AP and AUROC. Compute concordance over every positive-negative pair, counting ties as 0.5, with both pair-weighted and video-macro results.

- [x] **Step 4: Run GREEN for schema/strata**

Run: `python -m pytest tests/test_zero_training_diagnostics.py -q`

Expected: all current tests pass.

- [x] **Step 5: Add failing deterministic donor/audio-shuffle tests**

Assert same-query donors have different IDs and identical queries, different-query donors never share a query, both maps are permutations, singleton same-query groups fail closed, temporal shuffle preserves every non-audio field, and spectrogram/audio-valid tensors receive the same within-sample permutation.

- [x] **Step 6: Implement donor maps and temporal shuffle, then run GREEN**

Run: `python -m pytest tests/test_zero_training_diagnostics.py -q`

Expected: all Task 1 tests pass with no warnings.

- [x] **Step 7: Commit Task 1**

Commit message: `feat: add zero-training diagnostic primitives`.

### Task 2: Exact model diagnostic controls

**Files:**
- Modify: `src/models/ov_orthkd.py`
- Modify: `tests/test_paper_faithfulness.py`

**Interfaces:**
- Extends: `OVOrthKDStudent.forward(..., forced_gate_weights: tuple[float, float] | None = None)`.
- Produces output: `visual_backbone_features: torch.Tensor` with shape `[B,T,D_visual]`.

- [x] **Step 1: Write failing gate/backbone tests**

Assert `(0.25,0.75)` appears literally on both-valid segments, missing-modality segments renormalize to the available modality, `(0,1)` and `(1,0)` are exact, invalid length/negative/non-finite/non-unit-sum ratios raise `ValueError`, and the returned backbone tensor is the exact input consumed by `visual_proj`.

- [x] **Step 2: Run RED**

Run: `python -m pytest tests/test_paper_faithfulness.py -k 'forced_gate or backbone_features' -q`

Expected: failures show the missing `forced_gate_weights` argument/output.

- [x] **Step 3: Implement minimal default-disabled controls**

Compute `visual_backbone_features = self.visual_encoder(frame)` once and pass it through `visual_proj`. When an override is present, create the ratio tensor on the visual-token device/dtype, multiply by validity, renormalize, use equal weights only when both modalities are missing, and set receipt logits from the effective weights. The `None` branch remains byte-for-byte equivalent in mathematical operations to the previous branch.

- [x] **Step 4: Run GREEN and default-path regression**

Run: `python -m pytest tests/test_paper_faithfulness.py tests/test_s7_temporal_identity.py tests/test_ov_orthkd_pipeline.py -q`

Expected: all tests pass; default versus explicit temporal mode still has identical output keys/tensors.

- [x] **Step 5: Commit Task 2**

Commit message: `feat: expose exact checkpoint diagnostic controls`.

### Task 3: S7 A–E runtime

**Files:**
- Create: `scripts/diagnose_s7_zero_training.py`
- Create: `tests/test_s7_zero_training_audit.py`

**Interfaces:**
- CLI consumes `--repo`, `--git`, `--training-output`, `--training-audit`, `--output`, `--prediction-output`, `--expected-commit`, `--device`, `--shuffle-repeats`, and `--image-examples`.
- Produces compact schema-1 JSON plus a remote-only compressed NPZ containing aligned logits for independent recomputation.

- [x] **Step 1: Write failing tests for zero-step provenance and content hashing**

Use temporary ten-frame RGB fixtures. Assert all ten SHA256 values are bound into a canonical digest, exact duplicates are counted, adjacent pixel mean-absolute-differences are non-negative, and a duplicate example is retained. Assert a reconstructed model receipt that disagrees with stored step-zero segment-head weight/bias is rejected.

- [x] **Step 2: Run RED**

Run: `python -m pytest tests/test_s7_zero_training_audit.py -q`

Expected: import failure for the new runtime helpers.

- [x] **Step 3: Implement content/provenance helpers and run GREEN**

The compact report keeps ten hashes for deterministic example videos and a canonical digest/count summary for the full test split. It labels the model `reconstructed_zero_step`, records seed/builder/config hashes, and binds the matching stored step-zero receipt.

- [x] **Step 4: Add failing tests for timeline, gate grid, fusion/Jacobian, and audio modes**

Use a tiny student and loader to assert the exact four-state timeline labels, five forced ratios, original+visual-zero pairing, three audio interventions, concat input blocks `[visual,audio,query]`, finite Jacobian norms, no parameter/optimizer mutation, immutable labels/queries/positions, and output-collision refusal.

- [x] **Step 5: Implement A–E orchestration**

At reconstructed step zero and checkpoint steps 400/800/1200, collect raw-pixel/backbone/projected temporal summaries, concat linear Frobenius blocks, and first-test-batch input Jacobians. At best step run the five-ratio original/visual-zero sweep and deterministic audio interventions. Reuse Task 1 for strata and store all intervention logits in the remote-only NPZ.

- [x] **Step 6: Run GREEN and CLI checks**

Run: `python -m pytest tests/test_s7_zero_training_audit.py tests/test_zero_training_diagnostics.py tests/test_paper_faithfulness.py -q`

Run: `python scripts/diagnose_s7_zero_training.py --help`

Expected: tests and help exit 0.

- [x] **Step 7: Commit Task 3**

Commit message: `feat: add S7 zero-training audit runtime`.

### Task 4: Disposable Full projector probe

**Files:**
- Create: `scripts/diagnose_full_projector_probe.py`
- Create: `tests/test_full_projector_probe.py`

**Interfaces:**
- Produces: `probe_strong_projector(*, projector, decision_features, teacher_features, mask, learning_rate) -> dict[str, Any]`.
- CLI consumes exact Full config/checkpoint and one real train batch; it writes only compact JSON.

- [x] **Step 1: Write failing literal-gradient tests**

Use a deterministic two-dimensional projector fixture. Assert the strong projector receives nonzero gradient, student-decision gradient is finite/nonzero, sum loss and both gradient norms equal feature-dimension times mean counterparts, source module/state remain byte-identical, the clone state changes after one AdamW step, and target variance before/after is recorded.

- [x] **Step 2: Run RED**

Run: `python -m pytest tests/test_full_projector_probe.py -q`

Expected: import failure for `diagnose_full_projector_probe`.

- [x] **Step 3: Implement clone-only probe**

Deep-copy only `strong_teacher_proj`; clone the detached decision tensor as a leaf parameter. Compute mean and sum reductions in separate fresh graphs. Apply one resolved-LR AdamW step only to a new projector/decision pair, hash before/after states, then discard them. Assert the loaded source projector hash is unchanged before writing output.

- [x] **Step 4: Run GREEN and help check**

Run: `python -m pytest tests/test_full_projector_probe.py tests/test_paper_faithfulness.py -q`

Run: `python scripts/diagnose_full_projector_probe.py --help`

Expected: all exit 0.

- [x] **Step 5: Commit Task 4**

Commit message: `feat: add disposable Full projector probe`.

### Task 5: Independent evidence auditor and remote controls

**Files:**
- Create: `scripts/audit_zero_training_evidence.py`
- Create: `tests/test_zero_training_evidence_audit.py`
- Create under `reports/formal_reproduction/student_shortcut_recovery/runtime/`: prepare, verify, worker, launch, query, resume, and preflight scripts named for the implementation commit after it exists.

**Interfaces:**
- Auditor consumes A–E JSON, intervention NPZ, F JSON, S7 training audit, S7 trajectory, exact repo, and git executable.
- Produces a schema-1 PASS/FAIL artifact-integrity receipt; it does not emit a scientific success claim.

- [x] **Step 1: Write failing tamper tests**

Construct compact fixtures and assert PASS for valid evidence. Independently mutate `task_segments` to 16, change a donor query, alter a gate ratio, fabricate concordance, claim a saved step-zero checkpoint, change a source SHA, inject NaN, or mark the clone step as persistent; each mutation must fail.

- [x] **Step 2: Run RED**

Run: `python -m pytest tests/test_zero_training_evidence_audit.py -q`

Expected: import failure for the auditor.

- [x] **Step 3: Implement independent recomputation and run GREEN**

Recompute label histogram, mixed AP/AUROC/shuffle/concordance from NPZ arrays, validate exact mode set and offsets, verify source hashes/commit/clean status, and require the F source-state before/after hash equality plus disposable-clone declaration.

- [ ] **Step 4: Create fail-closed remote scripts**

Adapt the existing S7 candidate/runtime pattern. Bind the eventual exact implementation commit, all local/remote script SHA256 values, existing S7 training/posthoc audit SHA256 values, S7 checkpoint/config hashes, canonical Full config/checkpoint hashes, nine resource junction targets, locked venv, GPU identity, atomic phases, and refusal to overwrite outputs.

- [ ] **Step 5: Verify runtime scripts**

Run local Python `py_compile`, focused pytest, Ruff, and PowerShell parser checks. Upload scripts, compare every SHA, and run remote `--help`/preflight without launching the worker.

- [ ] **Step 6: Run complete locked repository tests and commit**

Run remote `python -m compileall -q .` and full `python -m pytest -q` at the exact implementation commit. Commit message: `feat: lock zero-training evidence audit`.

### Task 6: Execute A–F, audit, and publish compact evidence

**Files:**
- Create: `reports/formal_reproduction/student_shortcut_recovery/ZERO_TRAINING_AUDITS.md`
- Create compact evidence under `reports/formal_reproduction/student_shortcut_recovery/evidence/zero_training/`.
- Update recovery README, web handoff, evidence/runtime inventories, root report indexes, and `all.md`.

- [ ] **Step 1: Launch one persistent A–F worker after READY preflight**

Record process identity and exact phase. Do not start S8 in the same worker.

- [ ] **Step 2: Monitor by state/CPU/GPU/artifact growth**

Use condition-based polling no more frequently than useful phase transitions. If interrupted, use only the locked resume script and reuse only already-PASS atomic phases.

- [ ] **Step 3: Run independent artifact audit**

Require PASS, exact source hashes, `T=10`, finite outputs, immutable loaded checkpoints, and clean candidate worktree.

- [ ] **Step 4: Independently inspect scientific interpretation**

Check whether raw JPGs vary, reconstructed step-zero visual features are healthy, where visual variance collapses, whether forced gate restores visual-zero sensitivity, whether fusion Jacobians suppress vision, what the audio swaps retain, and whether the Full target clone moves.

- [ ] **Step 5: Publish only compact evidence**

Copy JSON/YAML/TXT receipts and reports below the publication size threshold. Exclude checkpoint, NPZ, data, cache, bundle, archive, and raw logs. Verify JSON/YAML parsing, links, secret scan, forbidden extension scan, and exact evidence hashes.

- [ ] **Step 6: Commit and push evidence**

Commit message: `docs: publish zero-training audit evidence`. Verify local HEAD, upstream, and GitHub remote SHA equality and a clean worktree.

### Task 7: Conditional S8 decision and execution

**Files:**
- Conditional create: `configs/diagnostics/recovery/ov_orthkd_s8_identity_fixed_gate_seed42.yaml`
- Conditional create: S8 tests/runtime/report/evidence following the S7 pattern.

- [ ] **Step 1: Evaluate the preregistered blocker gate**

Block S8 if A–F integrity is not PASS, official frame content is corrupt/identical, reconstructed step zero cannot be supported, `T!=10`, or any source/checkpoint hash is unresolved. Otherwise authorize only the identity+fixed-equal cell.

- [ ] **Step 2: If authorized, perform config TDD**

Write a failing test proving S8 differs from S7 only at `student.gate_mode`, then add the config and make the test pass. Preserve seed, 3×400 exposure, random initialization, augmentation, concat fusion, identity temporal path, Student-only BCE, data/evaluator locks, and checkpoint schedule.

- [ ] **Step 3: Run full verification and persistent S8**

Prepare an exact detached 5090 worktree, run full tests, launch one persistent worker, monitor to completion, and run mixed-only/visual/Jacobian posthoc gates.

- [ ] **Step 4: Independently audit and report**

Do not reinterpret S7. Classify S8 using the design’s three outcomes and stop before S9 or any Full rerun.
