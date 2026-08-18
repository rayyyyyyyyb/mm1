VENV ?= .venv
TORCH ?= cu124
CONFIG ?= configs/ov_orthkd_paper_setting.yaml
MANIFEST ?= data/ov_ave/train.jsonl
PYTHON ?= $(VENV)/bin/python

.PHONY: setup scaffold preflight smoke test check-manifest train train-debug

setup:
	bash scripts/setup_server.sh --venv $(VENV) --torch $(TORCH)

scaffold:
	$(PYTHON) scripts/scaffold_workspace.py

preflight:
	$(PYTHON) scripts/preflight_ov_orthkd.py --config $(CONFIG) --output-dir outputs/preflight

smoke:
	$(PYTHON) scripts/smoke_test.py

test:
	$(PYTHON) -m pytest -q

check-manifest:
	$(PYTHON) scripts/check_manifest.py --manifest $(MANIFEST) --fail-on-missing

train:
	$(PYTHON) scripts/train_ov_orthkd.py --config $(CONFIG)

train-debug:
	$(PYTHON) scripts/train_ov_orthkd.py --config $(CONFIG) --max-train-steps 2 --max-eval-batches 2
