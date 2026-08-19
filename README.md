# OV-OrthKD Collaboration Base

This package contains the core implementation of OV-OrthKD for research collaboration and method extension. The R0 hardening work keeps the historical collaboration path available while adding a separately labelled camera-ready path and a strict reproduction evidence chain.

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

Before real training, run the source/export audit with the appropriate stage and scan level:

```bash
python scripts/audit_mm26_reproduction.py \
  --train-manifest data/ov_ave/train.jsonl \
  --val-manifest data/ov_ave/val.jsonl \
  --test-manifest data/ov_ave/test.jsonl \
  --path-root . --stage exported --artifact-scan full \
  --expected-segments auto --output-json reports/mm26_exported_artifact_audit.json
```

## Teacher artifact export

Configure exact, archived InternVideo2, BEATs, and CLAP repositories and checkpoints in a local config. Do not substitute similarly named weights. Inventory the repository SHAs, checkpoint hashes/keys, model classes and a one-record smoke before export:

```bash
python scripts/inspect_teacher_identity.py \
  --config configs/ov_orthkd_mm26_repro.local.yaml \
  --source-manifest data/ov_ave_smoke/source/train_source.jsonl \
  --output reports/teacher_identity.json
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

The canonical command above intentionally stops before loading data because `reproduction.full_run_blocked: true`. Six archival facts remain unresolved: temporal length, exact InternVideo2 identities, schedule/early stopping, student initialization/augmentation, visual L2 reduction, and the paper-versus-current fusion block. `--allow-blocked-reproduction` exists only for explicitly labelled diagnostics and writes `NON_CANONICAL_UNRESOLVED_RUN.txt`; it must not be reported as a canonical result.

Training records resolved config, Git state, environment, manifest hashes, history, structured predictions, best/last checkpoints, and global optimizer step. Evaluation calibrates a threshold on validation once and freezes it for total/seen/unseen test metrics. See `reports/R0_REPRO_HARDENING_REPORT.md` for the R0 evidence and remaining blockers.

## Collaboration note

This is a private research-collaboration package, not a complete archival release. Any extended manuscript should cite and clearly distinguish itself from the ACM Multimedia 2026 paper. See `SHARING_NOTICE.md`.
