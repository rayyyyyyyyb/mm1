# OV-OrthKD Collaboration Base

This package contains the core implementation of OV-OrthKD for research collaboration and method extension. The R2 branch adds a fail-closed conference-reproduction evidence chain while keeping the historical collaboration path separately labelled.

Paper: *If You Hear It, Help Find It: Orthogonal Knowledge Distillation for Open-Vocabulary Audio-Visual Event Localization* (ACM Multimedia 2026).

> **Current reproduction status (2026-08-25):** `READY_FOR_CONFERENCE_REPRO`. Official T=10 data, the 24,800-record teacher cache, exhaustive artifact audit, exact cache/manifest locks, one real-data structural preflight and the clean canonical evidence chain have passed on the RTX 5090. No formal student training, main-table run, ablation or paper metric reproduction has started; execution stops here until explicit user instruction. Read [CURRENT_STATUS.md](CURRENT_STATUS.md) before running the reproduction workflow.

The current stage report is [reports/R5_FINAL_RUNTIME_PROTOCOL_AND_READINESS_REPORT.md](reports/R5_FINAL_RUNTIME_PROTOCOL_AND_READINESS_REPORT.md).

The canonical runtime contract is `T_task=10, T_max=16, K_student=1, K_teacher=8, V_test=1`. The official data supplies one fixed JPG per one-second task segment; the student reads it once, InternVideo2 receives eight repeats of that same keyframe, and test uses one deterministic forward with no view averaging. `student.max_position_segments=16` is capacity only. No label, logit, teacher-feature, or metric path converts T=10 to T=16, and no 16-fps raw-video decode is executed.

Official WAVs are fitted deterministically to the same ten-second task window before their ten one-second slices are formed: shorter files are zero-padded and longer files are truncated. There is no temporal interpolation, resampling, last-sample repetition, or label transformation. The committed full audit records 23,844 unchanged, 954 zero-padded, and 2 truncated files with zero errors.

## Included

- Student architecture and query-conditioned audio-visual localization model.
- Camera-ready explicit decision/audio/query projections and the frozen historical shared-feature path.
- Asymmetric strong-visual/weak-audio distillation losses, with separate camera-ready and legacy formula classes.
- OV-AVEL dataset and manifest loaders.
- InternVideo2, BEATs, and CLAP teacher wrappers and artifact export pipeline.
- Training, preflight, evaluation, efficiency, and smoke-test scripts.
- Blocked canonical, bounded mock-smoke, representative baseline, and paper-setting configurations.
- Unit and vertical-slice tests.

## Not included

Datasets, pretrained weights, cached teacher features, experiment outputs, and third-party repositories are not redistributed. Obtain them from their official sources and review their licenses before use.

## Environment

Python 3.10 or newer is recommended. On RTX 5090, install the official CUDA 12.8 wheels into a clean environment before the remaining packages:

```bash
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
python -m pip check
python scripts/verify_cuda_runtime.py
```

For a Linux CUDA server, the setup helper can create a local virtual environment:

```bash
bash scripts/setup_server.sh --venv .venv --torch cu128
```

## Quick checks

```bash
python scripts/smoke_test.py
pytest -q
```

The strict camera-ready smoke configuration uses generated mock data and is never a paper result:

```bash
python scripts/create_mm26_smoke_fixture.py --root .
python scripts/preflight_ov_orthkd.py \
  --config configs/ov_orthkd_mm26_smoke.yaml \
  --output-dir outputs/r0_preflight \
  --probe-samples 4 \
  --max-eval-batches 2
```

## Data preparation

The files under `data/ov_ave/` are manifest templates, not dataset files. Follow the official acquisition information under `data/downloads/manual_sources/`, prepare local videos/audio, and build manifests:

```bash
python scripts/scaffold_workspace.py
python scripts/build_ov_avebench_source_manifests.py --help
python scripts/check_manifest.py --manifest data/ov_ave/train.jsonl --fail-on-missing
```

After manually obtaining the authorized official archive, the canonical path requires 7-Zip validation, safe extraction, metadata-to-file layout discovery, then source/export audits:

```bash
python scripts/safe_extract_archive.py \
  --archive /path/to/official-archive \
  --output-dir data/raw/ov_avebench_preprocessed \
  --receipt reports/data/official_archive_extraction_receipt.json
python scripts/discover_ovave_layout.py \
  --dataset-root data/raw/ov_avebench_preprocessed \
  --meta-csv data/raw/ov_avebench/ovave_dataset_meta.csv \
  --output-json reports/data/preprocessed_layout_discovery.json \
  --output-md reports/data/preprocessed_layout_discovery.md
```

Before any real run, audit source/exported manifests with the locked config and warning failures enabled:

```bash
python scripts/audit_mm26_reproduction.py \
  --config configs/ov_orthkd_mm26_repro.local.yaml \
  --preprocessing-lock configs/locks/mm26_preprocessing_lock.yaml \
  --teacher-lock configs/locks/mm26_teacher_lock.yaml \
  --train-manifest data/ov_ave/train.jsonl \
  --val-manifest data/ov_ave/val.jsonl \
  --test-manifest data/ov_ave/test.jsonl \
  --path-root . --stage exported --artifact-scan full \
  --expected-segments auto --fail-on-warning \
  --output-json reports/mm26_exported_artifact_audit.json
```

## Teacher artifact export

Configure exact, archived InternVideo2, BEATs, and CLAP repositories and checkpoints in a local config. Do not substitute similarly named weights. Inventory the repository SHAs, checkpoint hashes/keys, model classes and a one-record smoke before export:

```bash
python scripts/inspect_teacher_identity.py \
  --config configs/ov_orthkd_mm26_repro.local.yaml \
  --source-manifest data/ov_ave_smoke/source/train_source.jsonl \
  --output reports/teachers/teacher_identity.json \
  --repeat 2 --fail-on-unresolved
python scripts/export_teacher_artifacts.py --help
```

The mock backend is only for pipeline validation. The exact Base/B14 composition, pinned `InternVideo2_CLIP_small` upstream class, five checkpoint files, canonical keyframe input mode and output shapes are locked by `configs/locks/mm26_teacher_lock.yaml`. Real exports bind every schema-3 per-record receipt to an immutable `teacher_identity_sha256`; mutable progress/final-audit fields cannot invalidate a completed record, while any checkpoint or preprocessing change does. Run full export only from the passed official source manifests.

## Reproduction modes

The mode mapping is one-to-one and checked at model construction:

- `camera_ready_explicit_paths` → `student.path_mode=explicit_projected` + `OVOrthKDLoss`; localization reads the decision projection, text uses mapped-cosine probability BCE, and orthogonality is squared cosine between decision and audio paths.
- `legacy_collaboration` → `student.path_mode=legacy_shared` + `OVOrthKDLegacyLoss`; this freezes the historical shared-head and temperature-logit text formula for compatibility.

Checkpoints and reports record the selected implementation mode. Cross-combining a mode, path, and loss is rejected.

## Training safety

```bash
python scripts/train_ov_orthkd.py --config configs/ov_orthkd_mm26_repro.yaml
```

The canonical command above intentionally stops before loading data. Formal claims first validate the versioned archive/layout/source/teacher/evaluator/export/preflight evidence chain, and `reproduction.full_run_blocked: true` independently prohibits full training during the preparation stage. `--allow-blocked-reproduction` cannot bypass a formal canonical claim; it is limited to explicitly named diagnostic/noncanonical output namespaces and writes `NON_CANONICAL_UNRESOLVED_RUN.txt`.

The single permitted real-data preflight is also gated and must never emit formal AP/F1 results:

```bash
python scripts/preflight_ov_orthkd.py \
  --config configs/ov_orthkd_mm26_repro.local.yaml \
  --output-dir outputs/r2_real_preflight \
  --probe-samples 8 --max-eval-batches 1 \
  --real-data --optimizer-steps 1
```

Training records resolved config, Git state, environment, manifest hashes, history, structured predictions, best/last checkpoints, and global optimizer step. Evaluation calibrates a threshold on validation once and freezes it for total/seen/unseen test metrics. See `reports/R4_T10_TEMPORAL_PROTOCOL_CORRECTION_REPORT.md` for the current evidence and remaining gates.

## Collaboration note

This is a private research-collaboration package, not a complete archival release. Any extended manuscript should cite and clearly distinguish itself from the ACM Multimedia 2026 paper. See `SHARING_NOTICE.md`.
