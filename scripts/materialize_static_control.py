"""Materialize one static-target diagnostic wrapper without running training."""
from __future__ import annotations

import argparse
from pathlib import Path

from scripts.run_static_target_control import materialize_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wrapper", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    path = materialize_config(args.wrapper, args.repo_root, args.output_dir)
    print(path)


if __name__ == "__main__":
    main()
