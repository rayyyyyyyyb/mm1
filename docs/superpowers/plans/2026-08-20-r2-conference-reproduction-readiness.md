# R2 Conference Reproduction Readiness Implementation Plan

> Execute in order. Use test-driven development for behavior changes and preserve `full_run_blocked: true` throughout.

**Goal:** Produce an auditable conference-reproduction readiness gate and baseline implementation from exact R1 commit `6e4ea32c8e3cd84c07bc45d6e3ea3528d3fa9986`, with either a mechanically justified ready status or an explicit blocked status.

**Design:** Centralize cross-cutting contracts (split parsing, readiness validation, OV-AVEL metrics), make preprocessing and export crash-safe, then harden deterministic training and audits. Real-data stages are conditional on an authorized official archive.

**Stack:** Python 3.11, PyTorch, NumPy, pytest, YAML/JSON/JSONL, Git, Windows RTX 5090 environment.

---

## Task 1: Seen/unseen manifest contract

**Files:** `src/data/split_types.py`, manifest builder, dataset, audit, evaluation, `tests/test_r2_split_type_contract.py`.

1. Add failing tests for `meta.cls_type`, aliases, contradictions, and exact seen/unseen counts.
2. Implement the shared parser and migrate every consumer.
3. Make the builder write canonical top-level and metadata `split_type` fields.
4. Run focused tests remotely.

## Task 2: Non-bypassable canonical readiness gate

**Files:** `src/utils/canonical_readiness.py`, fingerprint utility, train entrypoint, canonical config, lock fixtures, `tests/test_r2_canonical_readiness_gate.py`.

1. Add failing tests showing that a false boolean cannot bypass missing/blocked locks.
2. Validate the five locks and exported audit, including content hashes and official counts.
3. Extend fingerprints with all canonical evidence and git/mode/variant state.
4. Add claim-level/readiness paths to config while retaining the full-run guard.
5. Run focused tests remotely.

## Task 3: Explicit OV-AVEL metrics and evaluator parity

**Files:** `src/evaluation/ovavel_metrics.py`, evaluation/train code, evaluator fixture and lock, `tests/test_r2_ovavel_metrics_parity.py`.

1. Create a fixture from the pinned official evaluator and write failing parity/name tests.
2. Implement binary micro, query foreground macro, segment, and event F1.
3. Replace ambiguous metric output fields and preserve AP/AUROC.
4. Pin evaluator repository commit and source SHA256 in its lock.
5. Run focused tests remotely.

## Task 4: Canonical preprocessing and safe archive handling

**Files:** manifest builder, `scripts/safe_extract_official_archive.py`, `scripts/discover_ov_avebench_layout.py`, preprocessing lock, `tests/test_r2_preprocessing_contract.py`.

1. Add failing tests for natural sorting, insufficient frames, path modes, official PNG/WAV references, atomic writes, and unsafe archives.
2. Remove generated JPEG-mel behavior from canonical mode and label legacy mode.
3. Implement staged safe extraction and read-only layout discovery.
4. Run focused tests remotely.

## Task 5: Scalable, resumable teacher export

**Files:** teacher common/pipeline/CLI modules, `tests/test_r2_teacher_export_scaling.py`.

1. Add failing tests for split namespacing, per-record receipts, one-time consolidation, and shared query embeddings.
2. Implement atomic per-record receipts and O(N) consolidation.
3. Make resume consume individual receipts and reuse content-addressed text artifacts.
4. Run focused tests remotely.

## Task 6: Determinism, safe wrappers, and audit evidence

**Files:** train entrypoint, dataset loader, model, teacher wrappers, audit/evaluation scripts, historical checkpoint inspector, R2 deterministic/model tests.

1. Add failing exact-resume and BatchNorm-state tests.
2. Persist/restore early-stop and generator state; set determinism before PyTorch import; make persistent workers explicit.
3. Preserve BatchNorm state during shape probes.
4. Harden Pillow/NumPy/checkpoint loads and add checkpoint hash binding.
5. Make audit dimensions, segments, resampling, split counts, and source/export hashes evidence based.
6. Extend static evidence and add safe historical checkpoint inspection.
7. Run focused tests, then the entire suite remotely.

## Task 7: Locks, blocked real-data stages, and final readiness decision

**Files:** five locks, required JSON/Markdown reports, `reports/R2_CONFERENCE_REPRODUCTION_READINESS_REPORT.md`, `all.md`.

1. Record the official-archive absence without network probing or invented facts.
2. Expand archival lock to all nine facts and retain unresolved statuses where evidence is absent.
3. Record exact teacher repository/class/checkpoint state; never guess missing checkpoints.
4. Generate explicit not-run/blocked receipts for source audit, teacher smoke/export, exported audit, and real preflight.
5. Build the final readiness receipt from the validators and assert the only allowed final status.
6. Copy the authoritative task book and chronological outer log into the repository.
7. Run compile, full tests, CUDA smoke, report consistency, and git diff review.
8. Commit the complete clean R2 stage, push the branch to GitHub, and verify the web-visible commit and branch URL.
