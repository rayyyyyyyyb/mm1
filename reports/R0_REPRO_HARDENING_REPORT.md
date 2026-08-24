# OV-OrthKD ACM MM 2026 R0 Reproduction Hardening Report

> Historical R0 snapshot. Current protocol interpretation is locked by `R4_T10_TEMPORAL_PROTOCOL_CORRECTION_REPORT.md`: the official task is T=10; 16 is student positional capacity or an explicitly synthetic efficiency input, not a label timeline.

Date: 2026-08-20
Repository: `https://github.com/rayyyyyyyyb/mm1`
Branch: `repro/r0-paper-faithfulness`
Audited base SHA: `dca9f052fbe4a1e9d7982f24bdcec3edf1363fd4`

## Outcome

`CONFIRMED_FIXED` — The R0 engineering hardening scope is implemented and verified on an NVIDIA GeForce RTX 5090. The camera-ready interpretation and the frozen collaboration baseline are separate, explicit modes; strict artifact handling, deterministic execution, bounded training, evaluation evidence, teacher/export audits, and CUDA 12.8 support are in place.

`BLOCKED_ARCHIVAL_FACT` — This is not a claim that the ACM MM 2026 result has been reproduced. The canonical configuration remains fail-closed because six historical facts and the exact teacher identities/checkpoints have not been recovered.

`NOT_EXECUTED` — No official dataset was downloaded, no real teacher cache was exported, and no real-data full or multi-seed training was started. Only unit tests, mock fixtures, bounded smoke/preflight runs, and CUDA/runtime measurements were executed.

At verification time, `HEAD` was still the audited base SHA plus the worktree changes described below. The delivery commit is intentionally the next and only branch commit; its SHA is available from the branch tip and the enclosing `all.md` after upload, avoiding an impossible self-reference inside the commit itself.

## P0/P1 disposition

| Priority | Finding | Status | R0 disposition |
|---|---|---|---|
| P0 | Localization head read shared features instead of the decision path | `CONFIRMED_FIXED` | `camera_ready_explicit_paths` maps only to `explicit_projected`; the head reads `decision_features`. `legacy_collaboration` maps only to the frozen `legacy_shared` implementation. |
| P0 | Text alignment used temperature-scaled logits BCE instead of mapped-cosine probability BCE | `CONFIRMED_FIXED` | Camera-ready loss uses `(cos + 1) / 2` followed by probability BCE. The term runs in FP32 outside CUDA autocast while preserving gradients and formula. Legacy behavior remains isolated. |
| P0 | Paper additive fusion/TransformerLayer conflicts with current concat-MLP fusion | `BLOCKED_ARCHIVAL_FACT` | R0 does not invent a replacement. The discrepancy is named in the canonical config and blocks canonical full training. |
| P0 | Missing weak-audio logits were fabricated from noisy visual logits | `CONFIRMED_FIXED` | Fabrication was removed. Weak logit KD defaults to zero and, if explicitly enabled, requires real weak logits and a non-empty mask. |
| P0 | Missing teacher features/text silently became valid zero targets | `CONFIRMED_FIXED` | Strict reproduction mode fails with record id and field/path context. Disabled loss terms do not require unused artifacts. |
| P0 | Server helper lacked an RTX 5090-compatible CUDA wheel option | `CONFIRMED_FIXED` | `scripts/setup_server.sh` supports `cu128`. The actual 5090 environment uses torch/vision/audio `2.10.0/0.25.0/2.10.0+cu128`. |
| P1 | RNG, workers, loaders, and CUDA kernels were not reproducibly controlled | `CONFIRMED_FIXED` | Host/CUDA RNGs, worker seeds, and independent loader generators are fixed. Deterministic mode is strict, uses `CUBLAS_WORKSPACE_CONFIG=:4096:8`, disables flash/memory-efficient SDPA, and permits only math SDPA. Two independent CUDA preflights produced exactly equal key metrics. |
| P1 | Checkpoints and runtime evidence were incomplete | `CONFIRMED_FIXED` | Training records resolved config, runtime, Git state, dependency/manifests hashes, history, global optimizer step, and best/last/resume state. Runtime evidence from the 5090 is committed under `reports/runtime/`. |
| P1 | Evaluation omitted grouped metrics, calibrated thresholding, and structured predictions | `CONFIRMED_FIXED` | Validation calibrates one threshold; test reuses it unchanged. Total/seen/unseen metrics, validation/test NPZ predictions, PR arrays, and final metrics share one production helper for training and eval-only paths. |
| P1 | Teacher export `--limit` retained unprocessed manifest records | `CONFIRMED_FIXED` | The default physically truncates output to processed records. Copying unprocessed records requires the explicit compatibility flag. |

No in-scope item is classified as `CONFIRMED_REMAINING_BUG` after the final verification matrix. The archival blocks below are unresolved evidence questions, not silently accepted implementation defaults.

## Mode and loss invariants

- `CONFIRMED_FIXED` — `camera_ready_explicit_paths` → `explicit_projected` + `OVOrthKDLoss`.
- `CONFIRMED_FIXED` — `legacy_collaboration` → `legacy_shared` + `OVOrthKDLegacyLoss`.
- `CONFIRMED_FIXED` — strong visual features align only to the decision projection; weak audio features align only to the audio auxiliary projection; text aligns only to the query projection.
- `CONFIRMED_FIXED` — camera-ready orthogonality is squared cosine between decision and audio auxiliary paths.
- `CONFIRMED_FIXED` — strong-logit and weak-logit KD default to zero in the reproduction config.
- `CONFIRMED_FIXED` — `path_root` resolves manifest and artifact paths; strict files fail fast; `weak_teacher_feature_mask` is canonical and the old mask name is only an identical compatibility alias.
- `CONFIRMED_FIXED` — legacy tests and the original vertical slice explicitly select legacy mode, preventing accidental semantic migration.
- `CONFIRMED_FIXED` — no VP-AdaOrthKD/adaptive-routing extension was introduced in R0.

## Training and evaluation safety

- `CONFIRMED_FIXED` — `full_run_blocked: true` and `scheduler.type: UNRESOLVED` stop the canonical entry point before output creation, data loading, model construction, or training. The observed raw exit code was 1 with the archival-block message.
- `CONFIRMED_FIXED` — an explicit override creates `NON_CANONICAL_UNRESOLVED_RUN.txt`; an overridden run cannot be mistaken for canonical evidence.
- `CONFIRMED_FIXED` — epoch, batch, optimizer-step, and evaluation limits have distinct semantics; the deprecated `--max-train-steps` alias is recorded as such.
- `CONFIRMED_FIXED` — cosine and step schedulers expose and honor epoch/optimizer-step interval; unknown scheduling remains blocked.
- `CONFIRMED_FIXED` — best/last checkpoints, history, resume epoch/best metric, early stopping, and global optimizer step are covered by tests and bounded mock execution.
- `CONFIRMED_FIXED` — structured predictions retain `split_type`, so total/seen/unseen groups are populated rather than silently empty.

## Audits and provenance

`CONFIRMED_FIXED` — The mock exported-artifact audit inspected all 12 bounded records and 12 artifact bundles: train/val/test each contain 4 records; 4 categories split into 2 seen and 2 unseen; 24 segments contain 12 positive and 12 negative labels; there are no duplicate ids, split overlaps, path errors, artifact errors, dimension errors, or non-finite values. The report explicitly shows that canonical split counts do not match because this is mock-only data. See `reports/mm26_smoke_artifact_audit.json`.

`BLOCKED_ARCHIVAL_FACT` — Static teacher identity inspection exited nonzero by design. It records the declared wrapper/upstream classes and dimensions, but five checkpoint paths and three upstream repositories are unresolved, and `InternVideo2-Base / CLIP-B14` conflicts with the wrapper's `InternVideo2_CLIP_small`. Static inventory therefore does not authorize a real teacher export. See `reports/teacher_identity_static.json`.

The artifact audit supports source/exported stages, duplicate/overlap and label/segment/path validation, streaming manifest hashes, configurable sample/full finite checks, expected 512/1/768/1024 artifact dimensions, `configured_max_segments: 16`, and the explicit statement `resampling_performed_by_dataset: false`.

## RTX 5090 verification

Environment evidence:

| Field | Observed value |
|---|---|
| Python | 3.11.9 |
| PyTorch | 2.10.0+cu128 |
| torchvision / torchaudio | 0.25.0+cu128 / 2.10.0+cu128 |
| CUDA / cuDNN | 12.8 / 91002 |
| GPU | NVIDIA GeForce RTX 5090 |
| Compute capability | 12.0 (`sm_120`) |
| FP16 2048² matmul | finite; 0.096512 ms average over 5 timed iterations |
| Dependency check | no broken requirements |

The dependency lock was scanned before inclusion and contains no `file://`, `@ file`, or local direct-reference paths.

Final commands and results:

| Command | Exit | Result |
|---|---:|---|
| `python -m pip check` | 0 | `No broken requirements found.` |
| `python -m compileall -q src scripts tests` | 0 | no output |
| `python -m pytest -q` | 0 | `60 passed in 14.87s` |
| `python scripts/verify_cuda_runtime.py --matrix-size 2048 --warmup 2 --iterations 5` | 0 | CUDA available, `sm_120`, finite FP16 result |
| `python scripts/smoke_test.py` | 0 | `OV-OrthKD smoke test passed.` |
| `python scripts/create_mm26_smoke_fixture.py --root .` | 0 | 4 mock-only records per split, T=2 |
| strict CUDA preflight | 0 | forward/backward/eval/save/resume passed; no warning; peak 1345.26 MiB |
| repeated strict CUDA preflight | 0 | loss and val/test/resume metrics exactly equal |
| CUDA efficiency T=10 | 0 | 29.689651 ms; 33.681770 clips/s |
| CUDA efficiency T=16 | 0 | 30.271228 ms; 33.034669 clips/s |
| canonical training guard | expected 1 | blocked before any run output was created |
| `git diff --check` | 0 | no whitespace errors; informational Windows line-ending notices only |

The strict preflight used the production builders and camera-ready mode. It probed train/validation manifests, performed an AMP forward/backward optimizer step, evaluated validation/test, saved a bounded resume checkpoint on the server, and restored epoch 1/best AP. Final deterministic values were loss `1.6225866079330444`, validation AP `0.5845238095238094`, test AP `0.5595238095238095`, and resumed best metric `0.5845238095238094`. The 188.95 MB checkpoint remains on the 5090 and is not committed.

Machine-readable command results and raw evidence are in `reports/runtime/verification_commands.jsonl`, `cuda_runtime_check.json`, `preflight_cuda.json`, `preflight_cuda_repeat.json`, `pytest_full.log`, `requirements-lock-5090.txt`, and `nvidia-smi.txt`.

## BLOCKED_ARCHIVAL_FACTS

1. `BLOCKED_ARCHIVAL_FACT` — Official labels are T=10, while the camera-ready implementation table states 16 temporal segments. No historical manifest or resampling protocol has been recovered; R0 preserves observed T and treats 16 only as capacity.
2. `BLOCKED_ARCHIVAL_FACT` — The exact InternVideo2 model class and three checkpoint identities are unknown; the current Base/B14 declaration conflicts with a Small-class wrapper.
3. `BLOCKED_ARCHIVAL_FACT` — The meaning of “step400 schedule,” scheduler gamma/interval, and early-stop patience is unknown.
4. `BLOCKED_ARCHIVAL_FACT` — Student pretrained initialization and the exact training augmentation recipe are unknown.
5. `BLOCKED_ARCHIVAL_FACT` — Visual feature L2 reduction as feature-dimension sum versus mean is unknown; R0 retains the existing mean pending evidence.
6. `BLOCKED_ARCHIVAL_FACT` — Historical query-aware fusion may be paper additive fusion plus `TransformerLayer` or current concat-MLP token fusion, including the role of validity bits.

## NOT_EXECUTED

- Official OV-AVEBench download, full canonical count audit, and real T=10/T=16 protocol recovery.
- InternVideo2, BEATs, or CLAP repository/checkpoint download; real teacher identity smoke; full teacher export.
- Real-data full training, the five-seed run, official checkpoint evaluation, PR/F1 comparison, or paper-number reproduction.
- Any operation that re-labels mock outputs as official results.

These remain prohibited until all six archival facts and teacher identities are recovered and reviewed.

## Changed-file inventory

Existing files modified:

- `README.md`
- `scripts/evaluate_pr_f1.py`
- `scripts/export_teacher_artifacts.py`
- `scripts/measure_efficiency.py`
- `scripts/preflight_ov_orthkd.py`
- `scripts/setup_server.sh`
- `scripts/train_ov_orthkd.py`
- `src/data/__init__.py`
- `src/data/ov_avel_dataset.py`
- `src/losses/__init__.py`
- `src/losses/ov_orthkd_loss.py`
- `src/models/__init__.py`
- `src/models/ov_orthkd.py`
- `src/teachers/pipeline.py`
- `tests/test_ov_orthkd_pipeline.py`
- `tests/test_teacher_export_and_preflight.py`

New implementation/config/test files:

- `configs/ov_orthkd_mm26_repro.yaml`
- `configs/ov_orthkd_mm26_smoke.yaml`
- `scripts/audit_mm26_reproduction.py`
- `scripts/create_mm26_smoke_fixture.py`
- `scripts/inspect_teacher_identity.py`
- `scripts/verify_cuda_runtime.py`
- `src/losses/ov_orthkd_legacy_loss.py`
- `tests/test_paper_faithfulness.py`
- `tests/test_reproduction_audit.py`
- `tests/test_reproduction_configs.py`
- `tests/test_reproduction_evaluation.py`
- `tests/test_strict_reproduction_data.py`
- `tests/test_teacher_identity.py`
- `tests/test_training_reproducibility.py`

Design, plan, audit log, task specification, report, and runtime evidence are included with the delivery. Generated datasets, outputs, checkpoints, third-party weights, environments, and caches are excluded.
