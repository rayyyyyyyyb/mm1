#!/usr/bin/env bash
set -euo pipefail

VENV_DIR=".venv"
PYTHON_BIN="python3"
TORCH_CHANNEL="cu128"
WITH_DOWNLOAD_TOOLS=0
WITH_EXPORT_DEPS=0
RUN_SMOKE=1

usage() {
  cat <<'EOF'
Usage:
  bash scripts/setup_server.sh [options]

Options:
  --venv <path>                Virtualenv directory. Default: .venv
  --python <python-bin>        Python executable to create the venv. Default: python3
  --torch <cpu|cu121|cu124|cu128>  PyTorch wheel channel. Default: cu128
  --with-download-tools        Install `gdown` and `huggingface_hub` for dataset downloads
  --with-export-deps           Install extra packages used by teacher export
  --skip-smoke                 Skip the repository smoke test at the end
  --help                       Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --venv)
      VENV_DIR="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --torch)
      TORCH_CHANNEL="$2"
      shift 2
      ;;
    --with-download-tools)
      WITH_DOWNLOAD_TOOLS=1
      shift
      ;;
    --with-export-deps)
      WITH_EXPORT_DEPS=1
      shift
      ;;
    --skip-smoke)
      RUN_SMOKE=0
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

case "$TORCH_CHANNEL" in
  cpu)
    TORCH_INDEX="https://download.pytorch.org/whl/cpu"
    ;;
  cu121)
    TORCH_INDEX="https://download.pytorch.org/whl/cu121"
    ;;
  cu124)
    TORCH_INDEX="https://download.pytorch.org/whl/cu124"
    ;;
  cu128)
    TORCH_INDEX="https://download.pytorch.org/whl/cu128"
    ;;
  *)
    echo "Unsupported torch channel: $TORCH_CHANNEL" >&2
    exit 1
    ;;
esac

"$PYTHON_BIN" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip setuptools wheel
python -m pip install torch torchvision torchaudio --index-url "$TORCH_INDEX"
python -m pip install -r requirements.txt

if [[ "$WITH_DOWNLOAD_TOOLS" -eq 1 ]]; then
  python -m pip install "gdown>=5,<6" "huggingface_hub[cli]>=0.30,<1"
fi

if [[ "$WITH_EXPORT_DEPS" -eq 1 ]]; then
  python -m pip install \
    "av>=12,<15" \
    "decord>=0.6,<1" \
    "fvcore>=0.1.5,<1" \
    "librosa>=0.10,<1" \
    "opencv-python>=4.10,<5" \
    "pandas>=2,<3" \
    "soundfile>=0.12,<1" \
    "termcolor>=2.4,<3" \
    "torchlibrosa>=0.1,<1"
fi

python -m pip check
if [[ "$RUN_SMOKE" -eq 1 ]]; then
  python scripts/smoke_test.py
fi
