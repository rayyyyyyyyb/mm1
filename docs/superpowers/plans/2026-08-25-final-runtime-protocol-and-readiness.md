# Final Runtime Protocol and Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Freeze the approved `T_task=10, T_max=16, K_student=1, K_teacher=8, V_test=1` runtime contract, remove every active contradictory statement, and complete the remaining teacher-export and one-step readiness evidence without starting formal training.

**Architecture:** A shared runtime-contract validator gates formal entry points. Teacher artifacts bind to an immutable identity digest rather than the mutable whole lock. The existing atomic per-record receipt/resume pipeline performs full split exports, followed by exhaustive audit, one real preflight and canonical readiness generation.

**Tech stack:** Python 3, PyTorch, pytest, YAML/JSON locks and receipts, PowerShell/SSH on the Windows RTX 5090 host.

**Design:** `docs/superpowers/specs/2026-08-25-final-runtime-protocol-and-readiness-design.md`

## Global constraints

- Use official ten one-second segments end-to-end; never introduce `10 -> 16` resampling.
- Treat 16 only as student positional capacity, 8 only as repeated teacher frames, and test as one deterministic view.
- Write a failing behavior test before each production fix and run that focused test after the fix.
- Record every action/result in both applicable `all.md` ledgers.
- Keep datasets, checkpoints and teacher caches off Git; do not start formal student training.

### Task 1: Enforce the final runtime contract

**Files:** `src/utils/temporal_protocol.py`, `src/train_ov_orthkd.py`, `scripts/preflight_ov_orthkd.py`, `scripts/canonical_readiness.py`, `configs/ov_orthkd_mm26_repro.yaml`, `tests/test_r5_final_runtime_protocol.py`

1. Add behavior tests that mutate each of the five quantities, teacher frame expansion and test aggregation and expect formal validation to fail.
2. Run the focused tests and preserve the RED exit code.
3. Add the central validator and call it from formal training, canonical readiness and real preflight.
4. Record the exact contract in the preflight shape receipt.
5. Run the focused tests to GREEN and inspect the diff independently.

### Task 2: Remove the teacher-lock export cycle

**Files:** `src/utils/reproduction_locks.py`, `src/teachers/artifact_pipeline.py`, `src/teachers/export_teacher_artifacts.py`, `scripts/audit_teacher_artifacts.py`, `scripts/canonical_readiness.py`, `tests/test_r5_teacher_identity_binding.py`

1. Add tests proving mutable export-status changes preserve the digest while checkpoint/preprocessing mutations change it, and that resume validation uses the immutable digest.
2. Run the focused tests to RED.
3. Implement canonical teacher identity projection/digest, smoke-passed export admission and schema-3 receipt bindings.
4. Include and verify the identity digest in full audit/readiness evidence.
5. Run focused and affected teacher/export tests to GREEN and inspect the diff independently.

### Task 3: Correct active documentation and locks

**Files:** main config, four locks, `CURRENT_STATUS.md`, README, active reports/docs, new R5 approval/report, tests that consume readiness/config behavior.

1. Create the R5 user-approved archival evidence with the five exact quantities and explicit prohibited interpretations.
2. Update active configuration bindings, evaluator semantics and hashes; mark older 16-fps diagnostic language as superseded/non-executed.
3. Preserve historical evidence while adding explicit supersession notes.
4. Run lock/hash/readiness tests and a repository-wide semantic search; independently inspect every remaining `16`/`fps`/view reference.

### Task 4: Verify code locally and on the 5090

1. Run all focused protocol, lock, exporter, audit, preflight and readiness tests locally where dependencies permit.
2. Sync tracked code only to `E:/OV-OrthKD-R3/repo`; preserve remote datasets, weights and caches.
3. Run the full pytest suite in the locked 5090 environment and record its exact exit code/count/duration.

### Task 5: Complete full teacher export and audit

1. Launch train/validation/test export through a persistent PowerShell runner with atomic per-record receipts and resume enabled.
2. Monitor progress by receipts/manifests/logs; on interruption restart the same runner so completed records are verified and skipped.
3. Run exhaustive artifact audit after all splits complete; compute split manifest hashes and the final cache-root SHA256.
4. Update data/teacher locks only from produced evidence and prove `teacher_identity_sha256` remains unchanged.

### Task 6: Run the single preflight and finalize readiness

1. Build an evidence-complete candidate config that remains blocked from formal full training.
2. Invoke the real-data preflight exactly once with one optimizer step; record all input, feature, label, logits and metric shapes.
3. If and only if preflight and canonical gates pass, generate the ready config and final R5 report; otherwise preserve the blocked state and exact blockers.
4. Run fresh full verification, commit one clean change set, push the branch and return commit SHA, diff stat, test exit codes, locks, cache root and final status.
