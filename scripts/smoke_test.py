#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tests.test_ov_orthkd_pipeline import test_ov_orthkd_vertical_slice


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        test_ov_orthkd_vertical_slice(Path(temp_dir))
    print("OV-OrthKD smoke test passed.")


if __name__ == "__main__":
    main()
