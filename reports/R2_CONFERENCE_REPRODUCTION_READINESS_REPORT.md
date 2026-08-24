# R2 Conference Reproduction Readiness Report

Final status: `BLOCKED_BEFORE_CONFERENCE_REPRO`

Claim level: `paper_specified_reconstruction`
Variant: `conference_baseline`

## Readiness gates

| Gate | Result | Requirement |
|---|---:|---|
| `canonical_evidence_chain` | BLOCKED | The shared canonical validator must verify exact files, hashes, config bindings and Git state |
| `p0_p1_tests` | PASS | Required R2 regression tests must pass |
| `data_lock` | BLOCKED | Official archive and manifests must be frozen in the data lock |
| `preprocessing_lock` | PASS | Canonical official JPG/WAV preprocessing must be fully resolved |
| `official_archive_and_extraction` | PASS | Official archive SHA and safe extraction must pass |
| `layout_discovery` | PASS | Full official layout discovery must pass without warnings |
| `source_manifest_audit` | BLOCKED | 24,800 source records must pass 0-error/0-warning audit |
| `nine_archival_facts` | PASS | All nine facts require direct evidence or approved reconstruction |
| `teacher_lock_and_checkpoints` | BLOCKED | Three teachers and five checkpoints must be exact and hashed |
| `teacher_smoke_repeatability` | BLOCKED | Real teacher smoke and repeatability must pass |
| `full_exported_artifact_audit` | BLOCKED | 24,800 exported records and cache hash must pass |
| `official_evaluator_parity` | PASS | Official evaluator mapping and parity must be resolved |
| `real_one_step_preflight` | BLOCKED | Exactly one real-data optimizer step must pass |
| `exact_epoch_resume` | PASS | Exact multi-worker augmented resume test must pass |
| `canonical_full_run_guard` | PASS | full_run_blocked must remain true for R2 review |

## Blockers

- `canonical_evidence_chain`
- `data_lock`
- `source_manifest_audit`
- `teacher_lock_and_checkpoints`
- `teacher_smoke_repeatability`
- `full_exported_artifact_audit`
- `real_one_step_preflight`

## Execution boundary

No full conference training is authorized by this receipt. The canonical `full_run_blocked` guard remains true pending the next human review.

Final status: `BLOCKED_BEFORE_CONFERENCE_REPRO`
