# R2 Conference Reproduction Readiness Design

Date: 2026-08-20

Authoritative input: `MM26_OVORTHKD_R2_CONFERENCE_REPRODUCTION_GATE_AND_BASELINE_TASK.md`

Base: `6e4ea32c8e3cd84c07bc45d6e3ea3528d3fa9986`

Branch: `repro/r2-conference-reproduction-readiness`

## Outcome boundary

R2 makes the conference reproduction path auditable and mechanically gated. It does not start a full student run, implement the journal extension, infer unresolved archival facts, or clear `full_run_blocked`.

The final status is exactly one of:

- `READY_TO_IMPLEMENT_CONFERENCE_EXPERIMENTS`
- `BLOCKED_BEFORE_CONFERENCE_EXPERIMENTS`

The official archive is not currently present. Therefore implementation and synthetic contract tests proceed, while every real-data dependent stage remains explicitly blocked unless an authorized archive appears.

## Architecture

### Shared split contract

`src/data/split_types.py` is the sole parser for seen/unseen labels. It accepts the top-level field and the historical metadata forms, including `meta.cls_type`, normalizes only documented spellings, and rejects contradictions. Manifest building, dataset loading, audit, evaluation, and teacher export consume that helper.

### Canonical readiness gate

`src/utils/canonical_readiness.py` validates five lock files plus the exported artifact audit. Validation is content based: paths, SHA256 values, statuses, official counts, teacher identities/checkpoints, evaluator identity/parity, cache root, and absence of unresolved markers. `claim_level=archival_exact` requires this validation even when a boolean blocker is false. Preflight remains the only bounded execution mode permitted while the repository's canonical guard stays enabled.

The reproduction fingerprint incorporates canonical inputs rather than configuration text alone: lock hashes, audit hash, evaluator identity, cache root, git state, mode, and variant.

### Metrics

`src/evaluation/ovavel_metrics.py` exposes explicit binary, per-query foreground, OV-AVEL segment, and OV-AVEL event F1 fields, retaining AP/AUROC. A fixture is calculated from the locked official evaluator at its pinned repository commit and checked against the local implementation. Metric names never collapse distinct definitions into a generic `f1`.

### Preprocessing and manifests

The canonical manifest builder references official PNG/WAV assets and never invents JPEG mel inputs. Frame ordering is natural and insufficient frames are rejected instead of silently repeated. External path serialization is explicit (`relative_to_path_root` or `absolute`) and JSONL output is atomic. Legacy generated JPEG-mel behavior, where retained, is labeled noncanonical.

Safe archive extraction uses staging, rejects traversal, links, duplicate destinations, and suspicious decompression ratios, and promotes a validated tree atomically. Layout discovery inventories candidate metadata, PNG, and WAV assets without inventing mappings.

### Teacher export

Artifacts are namespaced by split. Each successful record receives one atomic receipt; aggregate JSONL receipts are consolidated once at the end. Resume reads the per-record receipts. Query text embeddings are content addressed and shared across records. Loaders bind checkpoints to locked hashes before deserialization and use safe NumPy/Pillow handling.

### Determinism, resume, and model construction

CUDA determinism environment variables are set before importing PyTorch. DataLoader persistent workers are explicit and default off. Checkpoints include early-stop state and all generators/RNG states needed for epoch-boundary equivalence. Tests compare uninterrupted and resumed training with multiple workers and augmentation. Feature-dimension probing temporarily enters evaluation mode and restores both module mode and BatchNorm buffers.

### Audits and evidence

Artifact loading disables pickle and validates NPZ keys. Audit dimensions and segment counts are configuration driven, uses the shared split parser, and records actual resampling evidence. Static evidence includes resolved config, claim level, git state, dependency/CUDA facts, manifest/lock/cache/evaluator/variant hashes. Historical checkpoint inspection uses `weights_only=True` and reports only safe structural metadata.

## Failure semantics

Missing official data, unresolved archival facts, unresolved teacher checkpoints, absent full export, any audit warning/error, evaluator mismatch, or dirty canonical git state prevents readiness. A blocked result is a valid R2 deliverable when it identifies the exact blockers and preserves the full-run guard.

## Verification

Every behavior change starts with a failing focused test. The final verification sequence is compile, complete pytest, lock/report consistency checks, remote CUDA smoke, clean-tree check, and exact commit/branch verification. No real forward/backward step is attempted without all upstream locks and official data; if it becomes possible, it may run at most once.
