# OV-OrthKD Collaboration Base

This package contains the core implementation of OV-OrthKD for research collaboration and method extension.

Paper: *If You Hear It, Help Find It: Orthogonal Knowledge Distillation for Open-Vocabulary Audio-Visual Event Localization* (ACM Multimedia 2026).

## Included

- Student architecture and query-conditioned audio-visual localization model.
- Asymmetric strong-visual/weak-audio distillation losses.
- OV-AVEL dataset and manifest loaders.
- InternVideo2, BEATs, and CLAP teacher wrappers and artifact export pipeline.
- Training, preflight, evaluation, efficiency, and smoke-test scripts.
- Representative baseline and paper-setting configurations.
- Unit and vertical-slice tests.

## Not included

Datasets, pretrained weights, cached teacher features, experiment outputs, and third-party repositories are not redistributed. Obtain them from their official sources and review their licenses before use.

## Environment

Python 3.10 or newer is recommended. Install PyTorch and torchvision separately for the CUDA runtime on the target machine, then install the remaining packages:

```bash
pip install -r requirements.txt
```

For a Linux CUDA server, the setup helper can create a local virtual environment:

```bash
bash scripts/setup_server.sh --venv .venv --torch cu124
```

## Quick checks

```bash
python scripts/smoke_test.py
pytest -q
```

## Data preparation

The files under `data/ov_ave/` are manifest templates, not dataset files. Follow the official acquisition information under `data/downloads/manual_sources/`, prepare local videos/audio, and build manifests:

```bash
python scripts/scaffold_workspace.py
python scripts/build_ov_avebench_source_manifests.py --help
python scripts/check_manifest.py --manifest data/ov_ave/train.jsonl --fail-on-missing
```

## Teacher artifact export

Configure the official InternVideo2, BEATs, and CLAP repositories and checkpoints, then inspect available arguments:

```bash
python scripts/export_teacher_artifacts.py --help
python scripts/preflight_ov_orthkd.py --config configs/ov_orthkd_paper_setting.yaml --output-dir outputs/preflight
```

The mock backend is provided for pipeline validation without downloading teacher checkpoints.

## Training

```bash
python scripts/train_ov_orthkd.py --config configs/ov_orthkd_paper_setting.yaml
```

`configs/ov_orthkd_paper_setting.yaml` records the loss weights stated in the camera-ready paper. The other configurations are representative baselines and starting points for independent extensions. Paths, batch sizes, and schedules should be adapted to the local environment.

## Collaboration note

This is a private research-collaboration package, not a complete archival release. Any extended manuscript should cite and clearly distinguish itself from the ACM Multimedia 2026 paper. See `SHARING_NOTICE.md`.
