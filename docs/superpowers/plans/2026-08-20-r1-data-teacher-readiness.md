# R1 Data and Teacher Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Subagents are not used because the active developer instruction prohibits proactive delegation.

**Goal:** Establish an evidence-locked, fail-closed R1 boundary for official OV-AVEBench data, historical facts, real teacher artifacts, and one-step preflight readiness.

**Architecture:** Harden dataset and resume contracts first, then audit and lock official inputs, then recover historical/teacher evidence. Atomic artifact publication and deterministic receipts make caches independently auditable. P0 gates stop later real executions while still allowing a complete blocked report.

**Tech Stack:** Python 3.11, PyTorch 2.10/cu128, NumPy, Pillow, PyYAML, pytest, Git, PowerShell/Windows, RTX 5090.

**Spec:** `docs/superpowers/specs/2026-08-20-r1-data-teacher-readiness-design.md`

## Global Constraints

- Base SHA is exactly `d8e681b2d3597f0f089ee8f0b42ef12466ffb599`; branch is `repro/r1-data-teacher-readiness`.
- Execute R1-0 through R1-15 in order and stop later real execution at the first P0 gate failure.
- Never guess an archival fact, repository class, model variant, URL, or checkpoint.
- Never start formal student training, implement journal mechanisms, or set canonical `full_run_blocked` false.
- Run the real-data forward/backward preflight at most once.
- Keep datasets, third-party repos, checkpoints, teacher caches, local config, and outputs out of Git.
- Make exactly one final clean R1 commit, overriding the skill's usual frequent-commit advice.
- Append every action and result to the authoritative outer `扩刊/all.md`.

---

### Task 1: R1-0 exact baseline

**Files:** Runtime evidence under ignored remote `E:/OV-OrthKD-R1/outputs/r1_baseline`.

**Interfaces:** Consumes the exact base worktree and R0 cu128 venv; produces baseline exit codes and GPU identity.

- [x] Create local and remote R1 worktrees at the exact base and verify branch/HEAD/clean status.
- [x] Run `pip check`, `compileall`, full pytest, and `verify_cuda_runtime.py`; preserve output and correct only environment PATH issues.
- [x] Confirm final baseline is 60 passing tests and CUDA finite on RTX 5090.

### Task 2: R1-1 dataset integrity (RED/GREEN)

**Files:** Modify `src/data/ov_avel_dataset.py`; create `tests/test_r1_dataset_integrity.py`; modify `configs/ov_orthkd_mm26_repro.yaml`.

**Interfaces:** Produces `temporal_overflow_policy`, safe `teacher_path_overrides` mappings, strict tensor shapes, binary/finite validation, and exact seen/unseen normalization.

- [ ] Write focused failing tests for canonical overflow rejection, explicit uniform indices/noncanonical marker, no singleton feature/logit broadcast, accepted `[T,D]`/`[T]`/`[T,1]`, finite arrays, binary labels, safe numpy loading, safe image copying, hierarchy-preserving remap, traversal rejection, and close/open mapping.
- [ ] Run `python -m pytest -q tests/test_r1_dataset_integrity.py` and verify each new behavior fails for its intended missing contract.
- [ ] Implement `temporal_overflow_policy`, `_validate_binary_labels`, `_validate_finite_array`, `_remap_artifact_path`, strict feature/logit normalization, `allow_pickle=False`, and context-managed `Image.open(...).copy()`.
- [ ] Set canonical config `temporal_overflow_policy: error` and `loss.confidence_weighting: false` without changing the full-run guard.
- [ ] Rerun the dataset test module and relevant existing data tests to green.

### Task 3: R1-1 exact resume and eval-only (RED/GREEN)

**Files:** Create `src/utils/reproduction_fingerprint.py` and `tests/test_r1_checkpoint_resume.py`; modify `scripts/train_ov_orthkd.py`, `scripts/preflight_ov_orthkd.py`, and `src/data/ov_avel_dataset.py`.

**Interfaces:** Produces `build_reproduction_fingerprint`, `capture_rng_state`, `restore_rng_state`, loader generator state capture/restore, fingerprint-checked `maybe_resume`, and a diagnostic marker path.

- [ ] Write failing tests proving eval-only never calls `build_scheduler`, incompatible fingerprint is rejected, explicit incompatible override writes a marker, RNG/loader states round-trip, and resumed epoch-boundary batch IDs/loss/parameters equal uninterrupted execution.
- [ ] Run the module and verify expected RED failures.
- [ ] Implement stable canonical serialization and SHA256 over relevant config/manifests/locks; include component hashes in the fingerprint record.
- [ ] Store/restore Python, NumPy, torch CPU/CUDA, and named loader-generator states in checkpoints; validate fingerprint before mutating runtime state.
- [ ] Refactor eval-only so it does not construct optimizer/scheduler/scaler; wire the same helpers into bounded preflight checkpoint restoration.
- [ ] Rerun resume tests and existing reproducibility/preflight tests to green.

### Task 4: R1-1 atomic artifact publication (RED/GREEN)

**Files:** Create `src/utils/atomic_artifacts.py` and `tests/test_r1_atomic_export.py`; modify `src/teachers/common.py`, `src/teachers/pipeline.py`, and `scripts/export_teacher_artifacts.py`.

**Interfaces:** Produces `atomic_save_array`, `atomic_write_jsonl`, `sha256_file`, `canonical_tree_hash`, receipt validation, resumable export, `.partial` manifest publication, and nonzero error handling.

- [ ] Write failing tests for interrupted array writes preserving old/absent targets, post-write shape/finite checks, lock/source hash invalidation, basename-safe artifact paths, resume validation, and final manifest publication only after complete success.
- [ ] Run the atomic test module and verify expected RED failures.
- [ ] Implement same-directory temp/fsync/replace helpers and deterministic canonical root hash.
- [ ] Extend export records/CLI with split, receipt JSONL, teacher-lock hash, resume, overwrite, and error JSONL; publish a final manifest only after all records and receipts validate.
- [ ] Rerun atomic and existing export tests to green.

### Task 5: R1-2 full regression and mock preflight

**Files:** Evidence under `reports/runtime/` and ignored remote outputs; no production behavior beyond Tasks 2–4.

**Interfaces:** Produces clean full-test and mock-preflight exit records before touching official data.

- [ ] Sync the local R1 working tree to the remote R1 repo without committing.
- [ ] Run `pip check`, `compileall`, full pytest, `scripts/smoke_test.py`, and the existing mock preflight on the 5090.
- [ ] Stop and debug any failure before official-data work.

### Task 6: R1-3 official metadata lock and audit (RED/GREEN)

**Files:** Create `scripts/audit_official_ov_avebench_metadata.py`, `tests/test_r1_official_metadata.py`, `reports/data/official_metadata_receipt.json`, `reports/data/official_metadata_audit.json`, and `reports/data/official_metadata_audit.md`; ignored `external/OV-AVEL` and copied raw metadata.

**Interfaces:** The audit consumes official CSV/JSON and produces exact count/group/class/ID/label histograms with errors and exit status.

- [ ] Write fixture-based failing tests for exact 24,800/train-val-test/67/46/21/count mappings, duplicate IDs, annotation bijection, label binary/length histograms, non-empty categories, and no open training rows.
- [ ] Implement the audit with `csv.DictReader` and JSON parsing; make `--fail-on-error` nonzero on any invariant violation.
- [ ] Clone `https://github.com/jasongief/OV-AVEL.git`, record exact commit/clean status, copy official metadata bytes, and record byte counts/SHA256/time in the receipt.
- [ ] Run the real full metadata audit and stop at P0 if any expected invariant differs.

### Task 7: R1-4 and R1-5 official preprocessed acquisition/layout

**Files:** Create `scripts/discover_ov_avebench_layout.py`, `reports/data/official_preprocessed_source.md`, download receipt/archive listing, and layout JSON/Markdown; external bytes remain ignored on the 5090.

**Interfaces:** Layout discovery consumes an immutable staging root and official metadata, then reports exact media coverage and a proposed dataset root without moving source bytes.

- [ ] Extract download URLs only from the pinned/current README and cross-check provenance.
- [ ] Download to `E:/OV-OrthKD-R1/downloads/official_preprocessed`, record URL source page/time/bytes/SHA256, and never record tokens/cookies.
- [ ] Test archives before extraction; reject absolute paths, `..`, collisions, bad archive exit, and insufficient disk; extract only to staging.
- [ ] Implement and run layout discovery for per-split wav/video/image counts, frame histograms, sampled wav properties, missing/orphan IDs, normalization/case/Windows collisions, duplicate contents, and recommended root.
- [ ] Stop if the package cannot be obtained or layout/media coverage is not safely established.

### Task 8: R1-6 and R1-7 deterministic source manifests/data lock

**Files:** Modify `scripts/build_ov_avebench_source_manifests.py` and `scripts/audit_mm26_reproduction.py`; create smoke/full source reports and `configs/locks/mm26_data_lock.yaml`.

**Interfaces:** The builder emits `segment_frame_paths`, `segment_frame_groups`, exact preprocessing metadata, deterministic spectrograms and manifests; the data lock binds official sources, layout, manifests, and preprocessing.

- [ ] Add failing fixture tests where needed for deterministic output, preserved frame groups, explicit preprocessing, close/open normalization, and no teacher placeholders.
- [ ] Implement all explicit audio/spectrogram/frame-selection parameters and deterministic writes.
- [ ] Build 8 records per split twice; verify manifest/spectrogram hashes, readable media, label/path alignment, and unchanged source data.
- [ ] Build all 24,800 source records, run source audit with zero warnings, and populate a resolved data lock only if every gate passes; otherwise emit a blocked lock with precise evidence.

### Task 9: R1-8 systematic archival fact recovery

**Files:** Create `scripts/recover_mm26_archival_facts.py`, `scripts/inspect_historical_checkpoint.py`, `configs/locks/mm26_archival_facts.yaml`, `reports/archival/mm26_archival_evidence.json`, and `reports/archival/MM26_ARCHIVAL_FACT_RECOVERY.md`.

**Interfaces:** Recovery consumes explicit bounded roots/refs and emits evidence entries with path/commit, source SHA256, locator, extracted fact, confidence, and reviewer note for exactly six fact keys.

- [ ] Search all Git refs/objects/reflogs/old worktrees and explicitly scoped local/5090 project/history/run roots for the task-book patterns.
- [ ] Inspect only trusted checkpoints with `weights_only=True` first and report structural facts separately from unsupported inferences.
- [ ] Resolve a fact only from direct evidence or two independent corroborating sources; otherwise keep null/unresolved.
- [ ] Compute overall lock status and apply the P0 gate before teacher recovery/execution.

### Task 10: R1-9 teacher identity/checkpoint lock (RED/GREEN)

**Files:** Create `tests/test_r1_teacher_lock.py` and `configs/locks/mm26_teacher_lock.yaml`; modify `scripts/inspect_teacher_identity.py` as required; create teacher evidence reports.

**Interfaces:** Teacher lock entries bind official repo URL/commit, imported module/class, variant/preprocessing, checkpoint URL/bytes/SHA256, and cross-reference archival/data lock hashes.

- [ ] Write failing tests for required lock schema, actual-class mismatch, missing checkpoint hash/bytes/source, BEATs variant ambiguity, CLAP version/normalization ambiguity, and cache invalidation when lock bytes change.
- [ ] Recover exact InternVideo2, BEATs, and CLAP identities only from direct historical evidence; preserve the Base/B14 versus `InternVideo2_CLIP_small` conflict as unresolved unless evidence genuinely resolves it.
- [ ] Hash every verified checkpoint and set overall status resolved only when every teacher and preprocessing input is exact.
- [ ] Run teacher-lock tests and enforce the P0 gate.

### Task 11: R1-10 and R1-11 exact teacher environment/real smoke

**Files:** Third-party repos/checkpoints/venv remain ignored; create runtime and teacher smoke receipts/reports.

**Interfaces:** Runs only when archival/data/teacher locks are resolved; produces import identities and repeatable per-teacher/per-split real outputs.

- [ ] Clone each locked repository and checkout its exact commit; install without changing the existing torch/torchvision/torchaudio versions.
- [ ] Rerun environment/CUDA/full repository tests after dependency installation.
- [ ] Run single-teacher real smoke and repeated cross-split seen/unseen smoke; require shapes, finite/nonzero outputs, and repeatability tolerance.
- [ ] If the preceding lock gate is blocked, record every item as `NOT_EXECUTED_GATE_BLOCKED` without downloading speculative repos/checkpoints.

### Task 12: R1-12 and R1-13 full export/audit

**Files:** Ignored teacher cache/manifests/receipts; create `reports/teachers/mm26_full_export_audit.json` only if gated execution occurs.

**Interfaces:** Consumes resolved locks and passed smoke; produces 24,800 receipts, published manifests, split roots, and total cache root.

- [ ] Confirm all seven task-book full-export gates and disk-space estimate before execution.
- [ ] Export train/val/test with resume but without first-run overwrite; abort nonzero on any record and retain old/absent final manifests.
- [ ] Audit all arrays/receipts/manifests for exact counts, dimensions, finiteness, collisions, stale hashes, missing files, and sorted canonical root hashes.
- [ ] If any preceding gate is blocked, record zero exports and `cache_root_sha256: null` rather than fabricating a cache result.

### Task 13: R1-14 one allowed real-data preflight

**Files:** Ignored `outputs/r1_real_data_preflight`; report references only.

**Interfaces:** May consume only a clean full artifact audit and produces exactly one optimizer step marked `preflight_only: true`, `paper_result: false`.

- [ ] Verify all prior P0 gates and that the recorded real-preflight invocation count is zero.
- [ ] Run the command exactly once, validate finite losses/gradients, checkpoint restore, timing, shapes, and peak memory, then record the invocation count as one.
- [ ] If gated out, record `optimizer_steps: 0` and `NOT_EXECUTED_GATE_BLOCKED`; do not run a diagnostic substitute on real data.

### Task 14: R1-15 report and guard verification

**Files:** Create `reports/R1_DATA_TEACHER_READINESS_REPORT.md`; create resolved proposal/`READY_FOR_R2_REVIEW.md` only if every gate resolved; update README where needed.

**Interfaces:** Report gathers exact commits, exit codes, locks/hashes, data/teacher/export/preflight facts, explicit non-executions, and one legal final status.

- [ ] Write the 17 required report sections, minimal remaining actions, and `NOT_EXECUTED` statements.
- [ ] Run both task-book self-checklists against code/data semantics and the teacher evidence chain.
- [ ] Run canonical training command and confirm it fails before data load/output creation because the full-run guard remains true.
- [ ] Select only `READY_FOR_R2_REVIEW` when all locks and audits resolve; otherwise select `BLOCKED_BEFORE_R2`.

### Task 15: Final verification, single commit, and GitHub upload

**Files:** Copy authoritative `../all.md` and the R1 task book into the R1 repository immediately before commit; all tracked R1 deliverables.

**Interfaces:** Produces a clean commit/push and the final SHA/diff/test/lock/cache response.

- [ ] Use `superpowers:verification-before-completion`; run `pip check`, `compileall`, full pytest, CUDA runtime, smoke, applicable real audits, `git diff --check`, guard rejection, and repository status/stat.
- [ ] Copy the latest chronological `all.md`, append final pre-commit actions, and verify no secrets, absolute local paths in tracked locks, datasets, checkpoints, caches, local config, or outputs are staged.
- [ ] Create exactly one commit on `repro/r1-data-teacher-readiness`, push that branch to `https://github.com/rayyyyyyyyb/mm1`, and verify the remote ref equals the local SHA.
- [ ] Return branch/base/commit, full diff stat, every test command and exit code, data/archival/teacher lock summaries and SHA256s, cache root SHA256 or null, real preflight count, unresolved items, GitHub URL, and the legal final status.
