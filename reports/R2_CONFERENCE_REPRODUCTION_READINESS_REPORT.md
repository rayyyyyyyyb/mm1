# R2 Conference Reproduction Readiness Report

Final status: `BLOCKED_BEFORE_CONFERENCE_EXPERIMENTS`

Claim level: `archival_exact`
Variant: `conference_baseline`

## Readiness gates

| Gate | Result | Requirement |
|---|---:|---|
| `canonical_evidence_chain` | BLOCKED | Shared canonical validator must verify exact files, hashes, config bindings and Git state |
| `p0_p1_tests` | PASS | Required R2 regression tests must pass |
| `data_lock` | BLOCKED | Official archive and manifests must be frozen in the data lock |
| `preprocessing_lock` | BLOCKED | Canonical official PNG/WAV preprocessing must be fully resolved |
| `official_archive_and_extraction` | BLOCKED | Official archive SHA and safe extraction must pass |
| `layout_discovery` | BLOCKED | Full official layout discovery must pass without warnings |
| `source_manifest_audit` | BLOCKED | 24,800 source records must pass 0-error/0-warning audit |
| `nine_archival_facts` | BLOCKED | All nine facts require direct evidence or approved reconstruction |
| `teacher_lock_and_checkpoints` | BLOCKED | Three teachers and five checkpoints must be exact and hashed |
| `teacher_smoke_repeatability` | BLOCKED | Real teacher smoke and repeatability must pass |
| `full_exported_artifact_audit` | BLOCKED | 24,800 exported records and cache hash must pass |
| `official_evaluator_parity` | BLOCKED | Official evaluator mapping and parity must be resolved |
| `real_one_step_preflight` | BLOCKED | Exactly one real-data optimizer step must pass |
| `exact_epoch_resume` | PASS | Exact multi-worker augmented resume test must pass |
| `canonical_full_run_guard` | PASS | full_run_blocked must remain true for R2 review |

## Blockers

- `canonical_evidence_chain`
- `data_lock`
- `preprocessing_lock`
- `official_archive_and_extraction`
- `layout_discovery`
- `source_manifest_audit`
- `nine_archival_facts`
- `teacher_lock_and_checkpoints`
- `teacher_smoke_repeatability`
- `full_exported_artifact_audit`
- `official_evaluator_parity`
- `real_one_step_preflight`

## Execution boundary

No full conference training is authorized by this receipt. The canonical `full_run_blocked` guard remains true pending the next human review.

## Scope and provenance

- Unique R2 base: `6e4ea32c8e3cd84c07bc45d6e3ea3528d3fa9986`.
- Branch: `repro/r2-conference-reproduction-readiness`.
- Claim level: `archival_exact`; experiment variant: `conference_baseline`.
- This stage implements conference-reproduction readiness only. It does not implement the journal-extension mechanism or start a full conference training epoch.
- The authoritative R2 task book is committed at the repository root; after trailing-whitespace-only normalization, its normalized SHA256 is `bd7f8e76721e089531374bcd8f95587b310e40c94e4a4daf37b182356d24c6f1`.

## Engineering gates completed

- Unified `close/open` and `seen/unseen` through one split helper used by builder, dataset, audit and evaluation.
- Added a content-validating canonical gate that cannot be bypassed by changing only `full_run_blocked`.
- Bound the complete normalized experiment configuration (all experiment-affecting values, excluding only location/output fields) to archival lock SHA256 `51b7e7d64f85df029c8cce4f0319264149ca5aef69c3ecdd9eb50078c45cfda4`; each resolved fact additionally binds an exact config-path/value map and recomputable file or Git evidence.
- Fixed the code-root trust boundary: readiness files and Git cleanliness are anchored to the root derived from the running source, and a configured `project_root` must resolve to that exact directory.
- Formal entrypoints now reject eval-only without a compatible checkpoint, incompatible-resume overrides, partial evaluation, and all truncated batch/optimizer-step training before data/model/output construction; every permitted CLI hyperparameter override is written into the fingerprinted config first.
- Locked distinct binary micro, per-query foreground, official OV-AVEL segment/event and calibrated metric field names; four frozen official evaluator fixtures pass parity.
- Replaced canonical invented JPEG-mel assumptions with official PNG/WAV, natural ordering, no-repeat, safe extraction, layout discovery and atomic manifest tooling. The legacy generated path remains explicitly noncanonical.
- Changed teacher export to split-safe per-record receipts, content-addressed query text, O(N) aggregation and atomic resume validation.
- Restored early-stop state, disabled canonical persistent workers, moved CUBLAS configuration before torch import, preserved backbone mode/BN state and passed a real multi-worker augmented exact-resume integration test.
- Added hash-before-load teacher wrappers, safe NumPy/NPZ readers, `weights_only=True` checkpoint loading, strict frame counts, repeat-2 teacher output comparison, config-driven full audit, complete static evidence and a value-free historical checkpoint inspector.

## Official data state

- Official metadata remains locked at 24,800 records: train 13,182; val 5,798; test 5,820; 67 classes; all released labels have T=10.
- No authorized manually downloaded official preprocessed archive was present locally or in the task-scoped R2 directory on the 5090 host.
- Archive filename, bytes and SHA256: `null`; archive test/listing and safe extraction: `NOT_EXECUTED_GATE_BLOCKED`.
- Train/val/test source manifest SHA256: `null` / `null` / `null`.
- Source audit and exported full audit: `NOT_EXECUTED_GATE_BLOCKED`; their `errors`/`warnings` are deliberately `null`, not false zero-error claims.

## Archival, evaluator and teacher state

- All Git refs/tags/reflogs, scoped local project files and task-scoped 5090 R0/R1/R2 outputs/checkpoints were searched. The only checkpoints found were collaboration-generated mock/preflight artifacts and were excluded as historical evidence.
- All nine archival facts remain `unresolved`; no reconstruction assumption was explicitly approved by the user.
- Official evaluator source is pinned at OV-AVEL commit `b5fe1d685d0c6d0d6fd80312b5ccde79f9b73ea6`, source SHA256 `013949f6371dc11a93f4e5b1df448601b98cf5590e7651d103600f981a4ded19`, and parity passes. The paper-field mapping remains unresolved, so the evaluator lock remains blocked.
- InternVideo2 has an unresolved declared/imported class conflict. InternVideo2 vision/text/extra, BEATs and CLAP checkpoint SHA256 values are all `null`; no nearest-name checkpoint was selected or downloaded.
- Real teacher smoke, repeatability and full 24,800-record export were not executed. Teacher cache root SHA256 is `null`.
- Real-data one-step preflight invocation count is exactly 0 because its prerequisite gates never passed. `reports/runtime/r2_real_preflight.json` records `optimizer_steps=0` and emits no formal metric.

## Final 5090 verification

| Command/gate | Exit | Result |
|---|---:|---|
| `python -m pip check` | 0 | No broken requirements found |
| `python -m compileall -q src scripts tests` | 0 | passed |
| `python -m pytest -q` | 0 | 191 passed in 86.69s |
| exact-resume focused integration | 0 | 3 passed in 48.82s |
| `verify_cuda_runtime.py --matrix-size 2048 --warmup 2 --iterations 5` | 0 | RTX 5090, torch 2.10.0+cu128, CUDA 12.8, finite=true |
| `python scripts/smoke_test.py` | 0 | passed |
| canonical training entry | 1 (expected) | structured readiness rejection; formal output absent before and after |
| readiness builder | 1 (expected) | generated the fail-closed BLOCKED receipt with 12 blockers, including `canonical_evidence_chain` |
| independent frozen-tree code review | 0 findings | `Ready to merge: Yes`; no remaining code blocker |

## Lock SHA256

- Data: `a655c9a1afcc53704f273f0d2efff41ca65300c55fcba4fc544a58c01867e303`.
- Archival: `4f6b947b78438793bf7cb0791d01f8f728b848c75768ae16e2b2fc7a3e1569dd`.
- Teacher: `ff7ac9eaae1caa602e5d34de80f2ba986c6c2760671a0e5be4c07d21636faa0c`.
- Preprocessing: `a389446990064a0b1a412b7de6ec668a18a8111fc32d6a262bbfb5b3f0aa93cc`.
- Evaluator: `54de7d974e676973d172d9bad523c173115804f0a4cfe8fc89c31c0e30775a62`.

## Minimum unblock sequence

1. Manually provide the authorized official archive, then hash/test/extract it and run full layout discovery.
2. Build and audit 24,800 source manifests with zero errors and warnings.
3. Supply direct historical evidence for nine facts, or explicitly approve named reconstruction assumptions and downgrade the claim accordingly.
4. Resolve exact teacher repositories/classes/preprocessing and all five checkpoint hashes; then run repeat-2 smoke, full export and full artifact audit.
5. Only after all preceding gates pass, run the single permitted real-data optimizer-step preflight and submit the new receipt for human review. Keep `full_run_blocked: true` until that review.

Final status: `BLOCKED_BEFORE_CONFERENCE_EXPERIMENTS`
