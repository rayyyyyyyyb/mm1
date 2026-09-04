# Visual-sum Post-hoc Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Run a read-only attribution audit on the completed Visual-only sum checkpoint before authorizing any Full training.

**Architecture:** Add one focused runner, `scripts/diagnose_visual_sum_posthoc.py`, that loads the resolved config and best/last checkpoints strictly, reuses the existing T=10 evaluator and content-ablation semantics, and evaluates only the test mixed-label subset for intervention cost. The runner also audits the saved full-test original prediction archive, audio temporal-shuffle response, mixed-label pairwise concordance, per-query/seen/unseen AP, and target-projector trajectory evidence without constructing an optimizer or writing checkpoints.

**Tech Stack:** Python 3, PyTorch, NumPy, scikit-learn, PyYAML, pytest, existing OV-AVEBench loader/model/evaluator utilities.

**Spec:** External web review pasted on 2026-09-04; current repository branch `repro/student-shortcut-recovery` and completed 30-epoch `Visual-only sum` run.

## Global Constraints

- Preserve the official `T=10` task segments; no 10→16 conversion or metric reshaping.
- The audit is post-hoc and read-only: no optimizer construction, optimizer step, checkpoint write, or training.
- Keep the canonical Full guard blocked; do not start formal Full training.
- Use the already completed best checkpoint for intervention predictions; use the last checkpoint only for end-of-run geometry evidence.
- For intervention cost, evaluate the test samples with `0 < sum(label) < 10`; labels, IDs, queries, split types, offsets, and segment indices must remain unchanged across modes.
- Use validation-calibrated threshold only for a reported secondary metric; fixed `0.5` remains the primary comparison.
- Record every action/result in both `扩刊/all.md` and `扩刊/OV-OrthKD-R2/all.md`, keeping them byte-identical.

### Task 1: Lock the post-hoc contracts with tests

**Files:**
- Create: `tests/test_visual_sum_posthoc.py`
- Create: `scripts/diagnose_visual_sum_posthoc.py` (after the failing tests)

**Interfaces:**
- `apply_posthoc_mode(batch, mode, seed, sample_offset) -> dict[str, Any]`
- `summarize_projector_drift(initial, current) -> dict[str, float]`
- `summarize_intervention_metrics(predictions, threshold) -> dict[str, Any]`
- `select_mixed_sample_indices(predictions) -> list[int]`

- [ ] **Step 1: Write failing tests**

  - Assert each content mode changes only frame/spectrogram values and preserves validity/masks.
  - Assert audio temporal shuffle is deterministic for the same seed/offset, changes order for a multi-segment sample, and preserves all alignment fields.
  - Assert mixed-index selection returns exactly samples with both positive and negative labels and rejects non-T=10 payloads.
  - Assert metric summarization emits total/seen/unseen global AP/AUROC and per-query AP plus mixed pairwise concordance.
  - Assert projector drift reports zero for equal state dictionaries and positive L2 drift for a changed tensor, while rejecting key/shape mismatches.

- [ ] **Step 2: Run the focused tests and verify the expected missing-interface failures**

  Run: `python -m pytest -q tests/test_visual_sum_posthoc.py`

  Expected: collection or assertion failures because the new runner interfaces do not yet exist.

### Task 2: Implement the read-only attribution runner

**Files:**
- Modify: `scripts/diagnose_visual_sum_posthoc.py`

**Interfaces:**
- CLI arguments: `--config`, `--best-checkpoint`, `--last-checkpoint`, `--test-predictions`, `--training-diagnostics`, `--output`, `--device`, `--shuffle-seed`.
- Output JSON contains source receipts, strict state-load receipts, official T=10 protocol, full original archive metrics, mixed-label intervention metrics for `original`, `visual_zero`, `audio_zero`, `both_zero`, and `audio_temporal_shuffle`, deltas from original, path scales, and epoch/step geometry trajectory.

- [ ] **Step 1: Implement pure mode transformation and payload validation**

  Reuse `apply_content_ablation`, `temporally_shuffle_audio`, `validate_temporal_alignment`, and `audit_prediction_payload`. The runner must reject any payload with non-binary labels, non-finite logits, unequal offsets, or segment indices other than `0..9` per sample.

- [ ] **Step 2: Implement mixed-subset collection**

  Build a deterministic `DataLoader` sampler from the saved test archive’s mixed-label IDs. Run the five modes with `torch.no_grad()`, strict shape checks, and one shared alignment payload. Never alter `frame_valid`, `audio_valid`, `sequence_mask`, labels, or segment boundaries for content-zero modes; temporal shuffle may only reorder spectrogram/audio-valid along the existing ten task segments.

- [ ] **Step 3: Implement metric and trajectory summaries**

  Compute fixed-threshold total/seen/unseen AP, AUROC, official segment/event F1, per-query macro AP, mixed-label pairwise concordance, and 100-repeat within-sample score shuffle. Parse unique `global_step_before_update` rows from `training_diagnostics.jsonl`; compute last-checkpoint geometry and initial→current strong-teacher-projector drift without an optimizer.

- [ ] **Step 4: Add fail-closed output and mutation guards**

  Refuse existing output or temporary files, assert best/last embedded configs exactly match the resolved config, strict-load student and loss states, assert the best state hash is unchanged after inference, and write the report atomically.

### Task 3: Verify locally and deploy the exact runner

**Files:**
- Modify: `reports/formal_reproduction/student_shortcut_recovery/VISUAL_ONLY_SUM_CONTROL_PLAN.md` (record execution protocol/result link after the run)
- Create: `reports/formal_reproduction/student_shortcut_recovery/VISUAL_SUM_POSTHOC_PLAN.md`

- [ ] **Step 1: Run focused tests and compile checks**

  Run: `python -m pytest -q tests/test_visual_sum_posthoc.py`; `python -m compileall -q scripts/diagnose_visual_sum_posthoc.py`.

- [ ] **Step 2: Run the full test suite**

  Run: `python -m pytest -q`.

- [ ] **Step 3: Upload only code/config/report scripts to the 5090 deployment**

  Keep official data, teacher cache, and `.pt` checkpoints on the 5090. Verify uploaded runner SHA256 equals the local SHA256 before execution.

### Task 4: Execute and audit the post-hoc result

- [ ] **Step 1: Run the runner through a persistent Task Scheduler action**

  Use the existing elevated `LXT` task pattern so SSH disconnects cannot kill the read-only process; do not change the checkpoint or scientific configuration.

- [ ] **Step 2: Independently inspect the JSON**

  Verify exit code `0`, report status `PASS`, exact 10-segment counts, mode-alignment invariants, finite metrics, source hashes, and mutation guard. Check whether mixed visual-zero AP/AUROC/F1 drops are substantive before considering any bounded Full run.

- [ ] **Step 3: Retrieve small report/log artifacts and update both ledgers**

  Record remote task state, report SHA256, all intervention metrics/deltas, trajectory values, and the resulting authorization decision. Keep ledgers byte-identical.

- [ ] **Step 4: Commit and push the code/report/ledger changes**

  Run `git diff --check`, focused/full tests, verify clean branch and remote SHA, then push `repro/student-shortcut-recovery`.
