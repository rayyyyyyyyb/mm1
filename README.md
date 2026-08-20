# OV-OrthKD Collaboration Base

This package contains the core implementation of OV-OrthKD for research collaboration and method extension. The R2 branch adds a fail-closed conference-reproduction evidence chain while keeping the historical collaboration path separately labelled.

Paper: *If You Hear It, Help Find It: Orthogonal Knowledge Distillation for Open-Vocabulary Audio-Visual Event Localization* (ACM Multimedia 2026).

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

The mock backend is only for pipeline validation. Full teacher export remains prohibited while the configured Base/B14 identity conflicts with the wrapper's actual `InternVideo2_CLIP_small` import or any checkpoint identity is unresolved.

## Reproduction modes

The mode mapping is one-to-one and checked at model construction:

- `camera_ready_explicit_paths` → `student.path_mode=explicit_projected` + `OVOrthKDLoss`; localization reads the decision projection, text uses mapped-cosine probability BCE, and orthogonality is squared cosine between decision and audio paths.
- `legacy_collaboration` → `student.path_mode=legacy_shared` + `OVOrthKDLegacyLoss`; this freezes the historical shared-head and temperature-logit text formula for compatibility.

Checkpoints and reports record the selected implementation mode. Cross-combining a mode, path, and loss is rejected.

## Training safety

```bash
python scripts/train_ov_orthkd.py --config configs/ov_orthkd_mm26_repro.yaml
```

The canonical command above intentionally stops before loading data. Formal claims first validate the versioned archive/layout/source/teacher/evaluator/export/preflight evidence chain, and `reproduction.full_run_blocked: true` then independently prohibits full training during R2. Nine archival facts remain unresolved. `--allow-blocked-reproduction` cannot bypass a formal canonical claim; it is limited to explicitly named diagnostic/noncanonical output namespaces and writes `NON_CANONICAL_UNRESOLVED_RUN.txt`.

The single permitted real-data preflight is also gated and must never emit formal AP/F1 results:

```bash
python scripts/preflight_ov_orthkd.py \
  --config configs/ov_orthkd_mm26_repro.local.yaml \
  --output-dir outputs/r2_real_preflight \
  --probe-samples 8 --max-eval-batches 1 \
  --real-data --optimizer-steps 1
```

Training records resolved config, Git state, environment, manifest hashes, history, structured predictions, best/last checkpoints, and global optimizer step. Evaluation calibrates a threshold on validation once and freezes it for total/seen/unseen test metrics. See `reports/R2_CONFERENCE_REPRODUCTION_READINESS_REPORT.md` for the current evidence and blockers.

## Collaboration note

This is a private research-collaboration package, not a complete archival release. Any extended manuscript should cite and clearly distinguish itself from the ACM Multimedia 2026 paper. See `SHARING_NOTICE.md`.
