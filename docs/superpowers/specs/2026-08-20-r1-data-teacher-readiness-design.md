# R1 Data and Teacher Readiness Design

## Objective

Starting only from `d8e681b2d3597f0f089ee8f0b42ef12466ffb599`, make the repository fail closed around real OV-AVEBench data, historical-paper facts, teacher identities, checkpoints, artifact publication, and epoch-boundary resume. Produce auditable locks and a final R1 report without starting formal student training, implementing journal mechanisms, or changing `reproduction.full_run_blocked: true`.

## Authority and stopping rule

The authoritative requirements are `../MM26_OVORTHKD_R1_DATA_TEACHER_READINESS_TASK.md` and the user's explicit execution order. The branch is `repro/r1-data-teacher-readiness`; the isolated worktree is this directory. Any P0 failure halts later real execution. An unresolved archival fact or teacher/checkpoint identity prohibits real teacher installation/export and the one-step real-data preflight. Missing evidence remains `unresolved`; likely values are never substituted.

## Data contract

`QueryConditionedOVAvelDataset` gains an explicit temporal overflow policy. `error` is canonical and rejects `seq_len > max_segments`; `uniform` deterministically selects unique, monotone indices and marks the sample noncanonical. Teacher features accept only finite `[T,D]`; teacher logits accept finite `[T]` or `[T,1]`; singleton rows are never broadcast. Labels must be non-empty, finite, and binary. Numpy files are loaded with `allow_pickle=False`, and images are copied while their file handles are inside a context manager.

Artifact overrides use an explicit source-root/target-root remap and preserve the source-relative hierarchy. The source path must be contained by the declared source root, and the remapped result must remain contained by the target root. This prevents basename collisions and path traversal. Official `close/open` values are normalized exactly to `seen/unseen`.

## Reproducible resume contract

The checkpoint records Python, NumPy, CPU/CUDA torch RNG state, each DataLoader generator state, global step, and a reproduction fingerprint. The fingerprint is a stable hash over semantically relevant resolved configuration, manifest bytes, and available lock bytes; runtime/output-only fields are excluded. Resume restores all state before the next epoch iterator is created. A mismatch fails by default. An explicit diagnostic override is allowed only when it writes an incompatible-resume marker; it never changes the canonical guard.

Eval-only returns before constructing optimizer, scheduler, scaler, or loading optimizer state. This prevents an unresolved scheduler from blocking evaluation.

## External evidence and locks

Official metadata is cloned from `jasongief/OV-AVEL`, pinned to an exact commit, copied byte-for-byte, hashed, and audited with Python CSV/JSON parsers. The audit validates exact totals, split/group/class counts, global IDs, annotation bijection, binary label histograms, non-empty categories, and train-without-open.

The preprocessed release is accepted only from URLs present in the pinned official README or current project README. Downloads retain receipts and safe archive listings before extraction. Layout discovery is read-only and reports frame/audio coverage, histograms, collisions, orphans, and a proposed root. Source manifest generation preserves both student middle frames and all teacher frame groups, freezes every spectrogram parameter, and is checked for deterministic bytes.

`mm26_data_lock.yaml`, `mm26_archival_facts.yaml`, and `mm26_teacher_lock.yaml` are the chain of custody. Historical facts may be resolved only by direct evidence or two independent corroborating sources. Teacher locks require exact repository URL/commit, actual imported class, exact variant, preprocessing, checkpoint source, byte size, and SHA256. Lock status is derived from required fields, never asserted optimistically.

## Atomic teacher cache

Arrays are written to a same-directory temporary file, flushed/fsynced, atomically replaced, reopened with `allow_pickle=False`, and checked for expected shape and finiteness before a receipt is published. Receipts bind record ID, split, source-manifest SHA256, teacher-lock SHA256, artifact relative path/shape/bytes/SHA256. Resume skips only when every binding and artifact check matches. A stale entry fails closed unless the caller explicitly requests overwrite/quarantine.

The exported manifest is assembled as `.partial` and replaces the final manifest only after all records succeed. Failures leave the old final intact (or absent), retain diagnostics, and exit nonzero. Root hashes use sorted `relative_path|bytes|sha256` rows and hash that canonical stream.

## Gate-controlled execution

Code and unit tests for all safety mechanisms are implemented regardless of external availability. Actual execution proceeds R1-0 through R1-15 in order. Real teacher repo/checkpoint installation starts only after resolved archival and teacher locks; full export requires every enumerated gate; the real forward/backward preflight may run at most once and only after a clean full artifact audit. If a gate blocks, later real actions are recorded `NOT_EXECUTED_GATE_BLOCKED` and the final status is `BLOCKED_BEFORE_R2`.

## Deliverables

The branch contains focused utilities for fingerprints/atomic writes, the five required R1 test modules, official metadata/layout/archival/checkpoint/sample tools, all three lock files, machine-readable evidence, and `reports/R1_DATA_TEACHER_READINESS_REPORT.md`. External repositories, raw data, checkpoints, caches, local absolute-path config, and outputs remain ignored. `扩刊/all.md` remains the chronological outer log and is copied into the R1 repository immediately before the single clean commit.
