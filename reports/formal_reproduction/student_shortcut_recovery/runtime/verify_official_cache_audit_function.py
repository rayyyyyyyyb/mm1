#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.audit_root.resolve()))
    from audit_s3_training import audit_official_cache_receipt

    result = audit_official_cache_receipt(args.receipt)
    print(
        json.dumps(
            {
                "status": "PASS",
                "receipt_sha256": result["sha256"],
                "roles": sorted(result["assets"]),
                "asset_sha256": {
                    role: result["assets"][role]["sha256"]
                    for role in sorted(result["assets"])
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
