# R1 Data and Teacher Readiness Report

Final status: `BLOCKED_BEFORE_R2`

## 1. Start and end commits

- Required and verified R1 base: `d8e681b2d3597f0f089ee8f0b42ef12466ffb599`.
- Branch: `repro/r1-data-teacher-readiness`.
- End commit: the single commit containing this report. Its exact SHA is returned in the final handoff; embedding a commit's own SHA in its tree would change that SHA.
- Official metadata upstream: `https://github.com/jasongief/OV-AVEL.git` at `b5fe1d685d0c6d0d6fd80312b5ccde79f9b73ea6`, full six-commit history and clean checkout.

## 2. R0 post-fix disposition

- Canonical temporal overflow now fails closed. Deterministic uniform selection is explicit and marks the sample noncanonical.
- Segment features must be exactly `[T,D]`; logits must be `[T]` or `[T,1]`. Singleton rows are never broadcast.
- Labels must be nonempty, finite, and binary. Teacher/text arrays must be finite and NumPy object/pickle payloads are rejected.
- PIL images are copied inside a context manager, closing the underlying handle.
- Artifact root overrides preserve relative hierarchy and reject traversal; sanitized output ID collisions fail before writing.
- Official `close/open` maps exactly to `seen/unseen`.
- Eval-only returns before optimizer/scheduler/scaler construction.
- Checkpoints include reproduction fingerprint, Python/NumPy/torch CPU/CUDA RNG states, DataLoader generator states, epoch, best score, and global step. Incompatible resume fails before state load unless an explicit noncanonical marker is written.
- Teacher export uses same-directory atomic writes, post-write reload/shape/finite validation, per-record receipts, lock hashes, fail-closed resume, `.partial` manifest publication, and deterministic cache-root hashing.
- Canonical `loss.confidence_weighting: false`; `reproduction.full_run_blocked: true` remains unchanged.

## 3. Modified and added files

- Repository policy/task: `.gitignore`, `MM26_OVORTHKD_R1_DATA_TEACHER_READINESS_TASK.md`, and root `all.md`.
- Configuration/locks: `configs/ov_orthkd_mm26_repro.yaml` and all three `configs/locks/mm26_*.yaml` files.
- Implementation: `scripts/audit_official_ov_avebench_metadata.py`, `scripts/export_teacher_artifacts.py`, `scripts/preflight_ov_orthkd.py`, `scripts/train_ov_orthkd.py`, `src/data/ov_avel_dataset.py`, `src/teachers/common.py`, `src/teachers/pipeline.py`, and `src/utils/{__init__,atomic_artifacts,reproduction_fingerprint,reproduction_locks}.py`.
- Tests: `tests/test_r1_{dataset_integrity,checkpoint_resume,atomic_export,official_metadata,teacher_lock}.py`, plus updates to `tests/test_strict_reproduction_data.py` and `tests/test_teacher_export_and_preflight.py`.
- Evidence/design: `docs/superpowers/{specs,plans}/2026-08-20-r1-data-teacher-readiness*.md`, `reports/data/*`, `reports/archival/*`, `reports/teachers/*`, `reports/runtime/r1_*`, and this report.
- Excluded by Git: official raw data, `external/OV-AVEL`, all teacher repositories/checkpoints, caches, local configs, and outputs.

## 4. Tests and command exits

Final fresh matrix on the RTX 5090 candidate tree:

| Command | Exit | Result |
|---|---:|---|
| `python -m pip check` | 0 | `No broken requirements found.` |
| `python -m compileall -q src scripts tests` | 0 | no diagnostics |
| `python -m pytest -q` | 0 | `100 passed in 16.69s` |
| `python scripts/verify_cuda_runtime.py --matrix-size 2048 --warmup 2 --iterations 5` | 0 | CUDA available; matrix result finite |
| `python scripts/smoke_test.py` | 0 | `OV-OrthKD smoke test passed.` |
| `python scripts/audit_official_ov_avebench_metadata.py ... --fail-on-error` | 0 | `status=passed`, errors=0 |
| `python scripts/train_ov_orthkd.py --config configs/ov_orthkd_mm26_repro.yaml` | 1 (expected) | guard rejected before data/output creation |

R1 targeted TDD evidence included expected RED failures followed by: data tests `25 passed`; resume/reproducibility `23 passed`; atomic export `8 passed`; cross preflight/resume/atomic `17 passed`; official metadata `3 passed`; teacher lock `4 passed`. The initial baseline with portable Git absent from the SSH `PATH` was environmental (`57 passed, 3 failed`); after placing the already-installed portable Git on `PATH`, the unchanged base passed all `60` tests.

The required source-stage, teacher-identity, exported-stage, and real-data preflight commands were `NOT_EXECUTED_GATE_BLOCKED`: R1-4 is a P0 gate and the task book forbids executing R1-5 through R1-14 after it fails.

## 5. RTX 5090 environment

- Host: `DESKTOP-LPN6MT3`; Windows `10.0.26200`; Python `3.11.9`.
- GPU: NVIDIA GeForce RTX 5090, driver `610.88`, `32607 MiB`, compute capability `12.0`.
- PyTorch `2.10.0+cu128`; CUDA runtime `12.8`; cuDNN `91002`; torchvision `0.25.0+cu128`; NumPy `2.4.6`; PyYAML `6.0.3`; timm `1.0.28`.
- Environment lock: `reports/runtime/r1_environment_lock.json`; SHA256 `7142186e0fc89f4a51e1e4d1dfbf3ddfbf2f7077e0037a028a621dc993d196f2`.

## 6. Official metadata lock and exact audit

- Pinned official source: [OV-AVEL README at the locked commit](https://github.com/jasongief/OV-AVEL/blob/b5fe1d685d0c6d0d6fd80312b5ccde79f9b73ea6/README.md#L21).
- CSV: `989749` bytes; SHA256 `f916b2a7fbaed53c95c6124efe3f11189766a2516805406639578c9a5fd4fb9d`.
- Annotation: `2999439` bytes; SHA256 `4a1b170095c0427b1ca3e6f178ced2b0dd1efbf753959f03905fe33c6f01f009`.
- Records: train `13182`, val `5798`, test `5820`, total `24800`.
- Groups: close/seen `16497`, open/unseen `8303`; classes: total `67`, close `46`, open `21`.
- Split/group: train-close `13182`; val-close `1651`; val-open `4147`; test-close `1664`; test-open `4156`; train-open `0`.
- Annotation/CSV bijection errors, duplicate IDs, and category mismatches: all `0`.
- Label length histogram: `{10: 24800}`; values `{0: 94597, 1: 153403}`; positive-segment histogram `{0:6019,1:352,2:749,3:809,4:822,5:912,6:921,7:929,8:1116,9:1389,10:10782}`.
- Metadata receipt SHA256: `37e63d9154460604e4b1afbcbfac9527761365e0e04feca13bd3c47c306026e9`; audit SHA256: `61668a80977bd86dc224cd9803503bacffd4d0ef1267f5723966966928b57a67`.

## 7. Official preprocessed download receipt and layout

- The pinned official SharePoint URL redirects anonymous Chrome-UA access to Microsoft login. Default download probes returned HTTP 403; the migrated legacy shares API returned HTTP 308 with `User migrated`; Microsoft Graph item/content endpoints returned HTTP 401.
- No authorized in-app browser session was available. No credentials/tokens were read or recorded and no third-party mirror was used.
- Receipt: `reports/data/official_preprocessed_download_receipt.json`; SHA256 `2fa0247acf1b8d6eba2b857debc9f46df4916fe9b50aa170ee1ad820bf65c193`.
- State: `BLOCKED_AUTHENTICATION_REQUIRED`; downloaded files `[]`; archive listing and extraction both false.
- Layout discovery: `NOT_EXECUTED_GATE_BLOCKED`; dataset root, frame histogram, and WAV sample-rate histogram are `null`.

## 8. Source manifests and preprocessing statistics

- Smoke source manifest: `NOT_EXECUTED_GATE_BLOCKED`; SHA256 `null`.
- Full train/val/test source manifests: `NOT_EXECUTED_GATE_BLOCKED`; all SHA256 values `null`.
- Real segment/frame/audio statistics: `null`; only the official annotation length histogram in section 6 is resolved.
- Frame grouping, audio segmentation, spectrogram parameters, and deterministic preprocessing specification remain `null` and were not inferred from library defaults.
- Data lock: `configs/locks/mm26_data_lock.yaml`; SHA256 `e182a44512ed6961d5f630e08acb5f384f17b73fd9e4e378af98b647c549eae4`; overall status `blocked`.

## 9. Six archival facts

Recovery execution was stopped before R1-8 by the R1-4 P0 gate. `configs/locks/mm26_archival_facts.yaml` has SHA256 `0e80cbccc59eeb46dbe943638cb4c34cc5e5472f663a84a2f8ff7f43eb46c2f2`; evidence is empty rather than guessed.

| Fact | Status | Evidence/value |
|---|---|---|
| temporal protocol | unresolved/blocked | `[]` / `null` |
| exact InternVideo identity | unresolved/blocked | `[]` / `null` |
| scheduler and early stop | unresolved/blocked | `[]` / `null` |
| student initialization and augmentation | unresolved/blocked | `[]` / `null` |
| visual L2 reduction | unresolved/blocked | `[]` / `null` |
| query-aware fusion | unresolved/blocked | `[]` / `null` |

## 10. Teacher locks

- Teacher lock: `configs/locks/mm26_teacher_lock.yaml`; SHA256 `49d1e772738fa51b31ee67663727890cc1b0c7836471dbfd21e3f023ec68e69d`.
- InternVideo2: unresolved; repository, commit, module, imported class, Base/B14-vs-Small variant, and checkpoints are `null`/empty.
- BEATs: unresolved; repository, commit, class, pretrained/finetuned variant, and checkpoint are `null`/empty.
- CLAP: unresolved; repository, commit, class, version, normalize behavior, and checkpoint are `null`/empty.
- No teacher repository or checkpoint was downloaded after the gate.

## 11. Checkpoint SHA256 values

- InternVideo2 checkpoint SHA256: `null`.
- BEATs checkpoint SHA256: `null`.
- CLAP checkpoint SHA256: `null`.
- This is intentionally blocked: no historical evidence was available to authorize checkpoint selection, so no parameter, class, version, or hash was guessed.

## 12. Teacher smoke exports

- Real single-object smoke: `NOT_EXECUTED_GATE_BLOCKED`; records `0`.
- Real cross-split/seen-unseen repeat smoke: `NOT_EXECUTED_GATE_BLOCKED`; records `0`.
- Mock-only engineering preflight did pass on the 5090 with finite loss `1.6225866079330444`, one optimizer step, and peak memory `1345.25927734375 MiB`; it is explicitly not a real-data result or paper metric.

## 13. Full teacher export

- Status: `NOT_EXECUTED_GATE_BLOCKED`.
- Records: `0`.
- Missing/errors: not scanned (`null`), not falsely reported as zero.
- Receipt count: `0`.
- Cache root SHA256: `null`.

## 14. Full artifact audit

- Status: `NOT_EXECUTED_GATE_BLOCKED`.
- Missing, stale-lock, collision, shape, finite, and warning counts: `null` because no full real cache exists.
- `audit_mm26_reproduction.py --stage exported --artifact-scan full --fail-on-warning` was not run after the P0 gate.

## 15. Real one-batch preflight

- Status: `NOT_EXECUTED_GATE_BLOCKED`.
- Real-data invocations: `0` (within the at-most-one limit).
- Optimizer steps: `0`; finite: not applicable; peak memory: not applicable.
- No result or metric was produced. The mock engineering check remains explicitly non-result.

## 16. R2 recommendation and minimum unblock actions

Canonical is **not** ready to be proposed for R2. `full_run_blocked: true` remains active and `reports/READY_FOR_R2_REVIEW.md` was not created.

Minimum remaining actions, in required order:

1. The user/data owner must provide an authorized Microsoft session or an official, access-authorized replacement URL for the exact pinned OV-AVEBench preprocessed archive.
2. Resume at R1-4: download, hash, list, safely extract, discover layout, build smoke/full source manifests, and resolve all preprocessing fields in the data lock.
3. Only after the data gate passes, run the prescribed Git/local-run/checkpoint evidence search for all six archival facts; the paper authors or experiment owner must supply direct evidence where the search remains empty.
4. From that evidence, lock exact InternVideo2, BEATs, and CLAP repositories/classes/variants/checkpoints and hashes; do not infer them from names.
5. Then and only then perform real smoke, full atomic export, full artifact audit, and at most one real-data one-step preflight before a separate R2 review can consider guard removal.

## 17. NOT_EXECUTED declaration

- No formal student training was started.
- No paper result or paper metric was produced.
- No extension/camera-ready mechanism was implemented.
- No canonical full-run guard was disabled or bypassed.
- R1-5 through R1-14 real execution remained stopped by the R1-4 P0 authentication gate.

Final status: `BLOCKED_BEFORE_R2`
