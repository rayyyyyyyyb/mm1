#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_s8_results import (  # noqa: E402
    assert_finite,
    extract_s8_primary_metrics,
    read_json,
    run_git,
    sha256_file,
)
from scripts.audit_zero_training_evidence import (  # noqa: E402
    audit_identity_ae_evidence,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independent S8 identity+fixed-equal posthoc artifact audit"
    )
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--git", type=Path, required=True)
    parser.add_argument("--ae-report", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--training-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    temporary = output.with_name(output.name + ".tmp")
    if output.exists() or temporary.exists():
        raise FileExistsError(f"Refusing to overwrite S8 posthoc audit: {output}")
    repo = args.repo.resolve()
    head = run_git(args.git.resolve(), repo, "rev-parse", "HEAD")
    status = run_git(
        args.git.resolve(),
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    ae_report = read_json(args.ae_report)
    training_audit = read_json(args.training_audit)
    if training_audit.get("claim_level") != "noncanonical_s8_training_artifact_integrity":
        raise ValueError("Supplied training audit is not the independent S8 audit")
    integrity = audit_identity_ae_evidence(
        ae_report=ae_report,
        prediction_archive=args.predictions,
        training_audit=training_audit,
        expected_commit=args.expected_commit,
        expected_gate_mode="fixed_equal",
        git_head=head,
        git_status=status,
    )
    primary = extract_s8_primary_metrics(
        ae_report, training_audit["training_diagnostics"]
    )
    report = {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": "artifact_integrity_and_exact_metrics_only",
        "task_segments": 10,
        "expected_gate_mode": "fixed_equal",
        "git_commit": args.expected_commit,
        "sources": {
            "ae_report": {
                "path": str(args.ae_report.resolve()),
                "bytes": args.ae_report.stat().st_size,
                "sha256": sha256_file(args.ae_report),
            },
            "prediction_archive": {
                "path": str(args.predictions.resolve()),
                "bytes": args.predictions.stat().st_size,
                "sha256": sha256_file(args.predictions),
            },
            "training_audit": {
                "path": str(args.training_audit.resolve()),
                "bytes": args.training_audit.stat().st_size,
                "sha256": sha256_file(args.training_audit),
            },
        },
        "integrity_audit": integrity,
        "primary_metrics": primary,
        "approved_evidence_patterns": [
            "visual sensitivity increases: temporal Transformer and learned gate interacted",
            "visual tokens vary but visual-zero remains inert: concat MLP suppresses vision",
            "visual tokens remain near constant: visual encoder/projection/input path remains causal",
        ],
        "scientific_outcome_threshold_preregistered": False,
        "automatic_scientific_success_claimed": False,
        "next_experiment_authorized": False,
        "formal_full_training_authorized": False,
    }
    assert_finite(report, "report")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
