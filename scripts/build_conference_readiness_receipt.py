#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.canonical_readiness import (
    OFFICIAL_SPLIT_COUNTS,
    OFFICIAL_SPLIT_SEEN_UNSEEN_COUNTS,
    REQUIRED_ARCHIVAL_FACTS,
    REQUIRED_READINESS_PATHS,
    REQUIRED_SCHEMA_VERSIONS,
    EXPECTED_CHECKPOINT_ROLES,
    validate_canonical_readiness,
)


READY_STATUS = "READY_FOR_CONFERENCE_REPRO"
BLOCKED_STATUS = "BLOCKED_BEFORE_CONFERENCE_REPRO"


DEFAULT_INPUTS = {
    "data_lock": "configs/locks/mm26_data_lock.yaml",
    "preprocessing_lock": "configs/locks/mm26_preprocessing_lock.yaml",
    "archive_receipt": "reports/data/official_archive_extraction_receipt.json",
    "layout_discovery": "reports/data/preprocessed_layout_discovery.json",
    "source_audit": "reports/mm26_source_manifest_audit.json",
    "archival_lock": "configs/locks/mm26_archival_facts.yaml",
    "teacher_lock": "configs/locks/mm26_teacher_lock.yaml",
    "teacher_identity": "reports/teachers/teacher_identity.json",
    "smoke_repeatability": "reports/teachers/smoke_repeatability.json",
    "exported_audit": "reports/mm26_exported_artifact_audit.json",
    "evaluator_lock": "configs/locks/mm26_evaluator_lock.yaml",
    "real_preflight": "reports/runtime/r3_real_preflight.json",
    "verification": "reports/runtime/r2_verification.json",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_document(value: str | Path | Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(value, Mapping):
        return dict(value), {"path": None, "exists": True, "sha256": None}
    raw_path = Path(value).expanduser()
    path = raw_path.resolve()
    evidence = {
        "path": raw_path.as_posix() if not raw_path.is_absolute() else str(path),
        "exists": path.is_file(),
        "sha256": _sha256(path) if path.is_file() else None,
    }
    if not path.is_file():
        return {}, evidence
    try:
        if path.suffix.lower() == ".json":
            loaded = json.loads(path.read_text(encoding="utf-8"))
        else:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        return {"_load_error": str(exc)}, evidence
    if not isinstance(loaded, Mapping):
        return {"_load_error": "document top level is not a mapping"}, evidence
    return dict(loaded), evidence


def _status(document: Mapping[str, Any]) -> str:
    return str(document.get("status", "")).strip().lower()


def _require(passed: bool, details: str) -> dict[str, Any]:
    return {"passed": bool(passed), "details": details}


def _is_sha256(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _positive_int(value: Any) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def _resolve_from_root(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def _validate_canonical_input_chain(
    config: Mapping[str, Any],
    inputs: Mapping[str, str | Path | Mapping[str, Any]],
) -> tuple[bool, str | None]:
    reproduction = config.get("reproduction", {})
    readiness = reproduction.get("readiness", {}) if isinstance(reproduction, Mapping) else {}
    if not isinstance(readiness, Mapping):
        return False, "reproduction.readiness must be a mapping"
    project_root_value = reproduction.get("project_root")
    if not isinstance(project_root_value, (str, Path)) or not str(project_root_value).strip():
        return False, "reproduction.project_root is required for readiness path binding"
    project_root = _resolve_from_root(PROJECT_ROOT, project_root_value)
    for name in REQUIRED_READINESS_PATHS:
        provided = inputs.get(name)
        configured = readiness.get(name)
        if isinstance(provided, Mapping):
            return False, f"canonical input {name} must be a file path, not an in-memory mapping"
        if provided is None or configured is None:
            return False, f"canonical input {name} is missing from inputs or config readiness"
        configured_path = _resolve_from_root(project_root, str(configured))
        provided_path = Path(provided).expanduser().resolve()
        if provided_path != configured_path:
            return (
                False,
                f"canonical input {name} does not match config readiness: "
                f"provided {provided_path}, configured {configured_path}",
            )
    try:
        receipt = validate_canonical_readiness(config)
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        return False, str(exc)
    if receipt.get("status") != "ready":
        return False, f"canonical validator returned non-ready status: {receipt.get('status')!r}"
    return True, None


def build_conference_readiness(
    config: Mapping[str, Any],
    inputs: Mapping[str, str | Path | Mapping[str, Any]],
) -> dict[str, Any]:
    missing_inputs = sorted(set(DEFAULT_INPUTS) - set(inputs))
    if missing_inputs:
        raise ValueError("Missing readiness inputs: " + ", ".join(missing_inputs))
    documents: dict[str, dict[str, Any]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for name in DEFAULT_INPUTS:
        documents[name], evidence[name] = _load_document(inputs[name])

    canonical_chain_ready, canonical_validation_error = _validate_canonical_input_chain(
        config,
        inputs,
    )

    reproduction = config.get("reproduction", {})
    if not isinstance(reproduction, Mapping):
        reproduction = {}
    claim_level = str(reproduction.get("claim_level", "unspecified"))

    archive = documents["archive_receipt"]
    archive_ready = (
        archive.get("schema_version") == REQUIRED_SCHEMA_VERSIONS["archive_receipt"]
        and
        _status(archive) == "passed"
        and _is_sha256(archive.get("archive_sha256"))
        and str(archive.get("extraction_status", "")).lower() == "passed"
        and archive.get("archive_test") == "passed"
        and archive.get("content_magic_valid") is True
        and isinstance(archive.get("archive_listing"), Mapping)
        and _is_sha256(archive.get("archive_listing", {}).get("sha256"))
    )
    data_lock = documents["data_lock"]
    locked_archive_sha = data_lock.get("archive_sha256")
    if locked_archive_sha is None and isinstance(data_lock.get("official_archive"), Mapping):
        locked_archive_sha = data_lock["official_archive"].get("sha256")
    data_lock_ready = (
        data_lock.get("schema_version") == REQUIRED_SCHEMA_VERSIONS["data_lock"]
        and
        _status(data_lock) == "ready"
        and _is_sha256(locked_archive_sha)
        and locked_archive_sha == archive.get("archive_sha256")
    )
    preprocessing_lock = documents["preprocessing_lock"]
    preprocessing_ready = (
        preprocessing_lock.get("schema_version") == REQUIRED_SCHEMA_VERSIONS["preprocessing_lock"]
        and
        _status(preprocessing_lock) == "resolved"
        and preprocessing_lock.get("mode") == "canonical_official_jpg_wav"
        and preprocessing_lock.get("frame_policy") == "natural_sorted_no_repeat"
        and preprocessing_lock.get("canonical_visual_extension") == ".jpg"
    )
    layout = documents["layout_discovery"]
    layout_ready = (
        layout.get("schema_version") == REQUIRED_SCHEMA_VERSIONS["layout_discovery"]
        and
        _status(layout) == "passed"
        and layout.get("split_counts") == OFFICIAL_SPLIT_COUNTS
        and layout.get("errors") == []
        and layout.get("warnings") == []
        and layout.get("metadata_bijection_verified") is True
        and layout.get("missing_clip_ids") in ({}, {split: [] for split in OFFICIAL_SPLIT_COUNTS})
        and layout.get("extra_clip_ids") in ({}, {split: [] for split in OFFICIAL_SPLIT_COUNTS})
        and layout.get("duplicate_clip_ids") == []
        and layout.get("duplicate_logical_basenames") == []
        and layout.get("zero_byte_files") == []
    )
    source = documents["source_audit"]
    source_hashes = source.get("source_manifest_sha256", {})
    source_ready = (
        source.get("schema_version") == REQUIRED_SCHEMA_VERSIONS["source_audit"]
        and
        _status(source) == "passed"
        and source.get("stage") == "source"
        and source.get("artifact_scan") == "none"
        and source.get("record_count") == 24800
        and source.get("split_counts") == OFFICIAL_SPLIT_COUNTS
        and source.get("errors") == []
        and source.get("warnings") == []
        and source.get("split_seen_unseen_counts") == OFFICIAL_SPLIT_SEEN_UNSEEN_COUNTS
        and isinstance(source.get("manifest_bytes"), Mapping)
        and set(source.get("manifest_bytes", {})) == set(OFFICIAL_SPLIT_COUNTS)
        and all(int(value) > 0 for value in source.get("manifest_bytes", {}).values())
        and isinstance(source_hashes, Mapping)
        and set(source_hashes) == set(OFFICIAL_SPLIT_COUNTS)
        and all(_is_sha256(value) for value in source_hashes.values())
    )

    archival = documents["archival_lock"]
    facts = archival.get("facts", {})
    accepted_fact_statuses = {"resolved"}
    if claim_level == "paper_specified_reconstruction":
        accepted_fact_statuses.add("approved_reconstruction_assumption")
    facts_ready = (
        isinstance(facts, Mapping)
        and set(facts) == REQUIRED_ARCHIVAL_FACTS
        and all(
            isinstance(fact, Mapping)
            and _status(fact) in accepted_fact_statuses
            and fact.get("selected_value", fact.get("value")) not in (None, "")
            and bool(fact.get("evidence"))
            and (
                _status(fact) != "approved_reconstruction_assumption"
                or fact.get("approved_by") == "user"
            )
            for fact in facts.values()
        )
    )
    archival_ready = (
        archival.get("schema_version") == REQUIRED_SCHEMA_VERSIONS["archival_lock"]
        and _status(archival) == "resolved"
        and facts_ready
    )

    teacher = documents["teacher_lock"]
    teachers = teacher.get("teachers", {})
    teacher_identities_ready = isinstance(teachers, Mapping)
    if teacher_identities_ready:
        for name, expected_roles in EXPECTED_CHECKPOINT_ROLES.items():
            identity = teachers.get(name, {})
            checkpoints = identity.get("checkpoint_files", []) if isinstance(identity, Mapping) else []
            roles = [
                str(checkpoint.get("role", ""))
                for checkpoint in checkpoints
                if isinstance(checkpoint, Mapping)
            ] if isinstance(checkpoints, list) else []
            if not (
                isinstance(identity, Mapping)
                and _status(identity) == "resolved"
                and bool(identity.get("repository", identity.get("repository_url")))
                and len(str(identity.get("commit", identity.get("repository_commit", "")))) == 40
                and bool(identity.get("imported_class"))
                and identity.get("working_tree_clean") is True
                and bool(identity.get("module", identity.get("module_path")))
                and bool(identity.get("preprocessing", identity.get("input_preprocessing")))
                and _positive_int(identity.get("output_dim"))
                and identity.get("determinism_tolerance") is not None
                and isinstance(checkpoints, list)
                and len(roles) == len(checkpoints)
                and len(roles) == len(set(roles))
                and set(roles) == expected_roles
                and all(
                    isinstance(checkpoint, Mapping)
                    and _positive_int(checkpoint.get("bytes"))
                    and bool(checkpoint.get("role"))
                    and bool(checkpoint.get("source_url_or_archive"))
                    and bool(checkpoint.get("filename"))
                    and _is_sha256(checkpoint.get("sha256"))
                    and bool(checkpoint.get("top_level_keys"))
                    and checkpoint.get("pretrained_or_finetuned") not in (None, "")
                    for checkpoint in checkpoints
                )
            ):
                teacher_identities_ready = False
                break
    real_smoke = teacher.get("real_smoke", {})
    full_export = teacher.get("full_export", {})
    full_export_ready = (
        isinstance(full_export, Mapping)
        and _status(full_export) == "passed"
        and full_export.get("records") == 24800
        and full_export.get("errors") == 0
        and len(str(full_export.get("cache_root_sha256", ""))) == 64
    )
    teacher_lock_ready = (
        teacher.get("schema_version") == REQUIRED_SCHEMA_VERSIONS["teacher_lock"]
        and
        _status(teacher) == "ready"
        and teacher_identities_ready
        and isinstance(real_smoke, Mapping)
        and _status(real_smoke) == "passed"
        and full_export_ready
    )
    identity = documents["teacher_identity"]
    repeatability = documents["smoke_repeatability"]
    teacher_smoke_ready = (
        identity.get("schema_version") == REQUIRED_SCHEMA_VERSIONS["teacher_identity"]
        and
        _status(identity) == "pass"
        and identity.get("errors") == []
        and _status(identity.get("smoke", {})) in {"pass", "passed"}
        and repeatability.get("schema_version") == REQUIRED_SCHEMA_VERSIONS["smoke_repeatability"]
        and _status(repeatability) == "pass"
        and repeatability.get("all_finite") is not False
    )

    exported = documents["exported_audit"]
    exported_ready = (
        exported.get("schema_version") == REQUIRED_SCHEMA_VERSIONS["exported_audit"]
        and
        _status(exported) == "passed"
        and exported.get("stage") == "exported"
        and exported.get("artifact_scan") == "full"
        and exported.get("record_count") == 24800
        and exported.get("split_counts") == OFFICIAL_SPLIT_COUNTS
        and exported.get("errors") == []
        and exported.get("warnings") == []
        and exported.get("split_seen_unseen_counts") == OFFICIAL_SPLIT_SEEN_UNSEEN_COUNTS
        and _is_sha256(exported.get("cache_root_sha256"))
        and exported.get("cache_root_sha256") == full_export.get("cache_root_sha256")
    )
    evaluator = documents["evaluator_lock"]
    parity = evaluator.get("parity", {})
    evaluator_ready = (
        evaluator.get("schema_version") == REQUIRED_SCHEMA_VERSIONS["evaluator_lock"]
        and
        _status(evaluator) == "resolved"
        and isinstance(parity, Mapping)
        and _status(parity) == "passed"
        and _is_sha256(parity.get("fixture_sha256"))
        and _is_sha256(parity.get("receipt_sha256"))
        and _status(evaluator.get("paper_f1_at_0_5_mapping", {})) == "resolved"
        and _status(evaluator.get("validation_calibrated_f1_mapping", {})) == "resolved"
    )
    preflight = documents["real_preflight"]
    preflight_ready = (
        preflight.get("schema_version") == REQUIRED_SCHEMA_VERSIONS["real_preflight"]
        and
        _status(preflight) == "passed"
        and preflight.get("real_data") is True
        and preflight.get("optimizer_steps") == 1
        and preflight.get("invocation_count_this_stage") == 1
        and preflight.get("formal_metrics_emitted") is False
        and preflight.get("forward_completed") is True
        and preflight.get("backward_completed") is True
        and preflight.get("checkpoint_resume_completed") is True
        and preflight.get("losses_finite") is True
    )
    verification = documents["verification"]
    p0_p1_ready = _status(verification) == "passed" and verification.get("p0_p1_tests") == "passed"
    exact_resume_ready = _status(verification) == "passed" and verification.get("exact_resume") == "passed"
    full_run_guard = reproduction.get("full_run_blocked") is True

    requirements = {
        "canonical_evidence_chain": _require(
            canonical_chain_ready,
            "The shared canonical validator must verify exact files, hashes, config bindings and Git state",
        ),
        "p0_p1_tests": _require(p0_p1_ready, "Required R2 regression tests must pass"),
        "data_lock": _require(data_lock_ready, "Official archive and manifests must be frozen in the data lock"),
        "preprocessing_lock": _require(
            preprocessing_ready, "Canonical official JPG/WAV preprocessing must be fully resolved"
        ),
        "official_archive_and_extraction": _require(archive_ready, "Official archive SHA and safe extraction must pass"),
        "layout_discovery": _require(layout_ready, "Full official layout discovery must pass without warnings"),
        "source_manifest_audit": _require(source_ready, "24,800 source records must pass 0-error/0-warning audit"),
        "nine_archival_facts": _require(archival_ready, "All nine facts require direct evidence or approved reconstruction"),
        "teacher_lock_and_checkpoints": _require(teacher_lock_ready, "Three teachers and five checkpoints must be exact and hashed"),
        "teacher_smoke_repeatability": _require(teacher_smoke_ready, "Real teacher smoke and repeatability must pass"),
        "full_exported_artifact_audit": _require(exported_ready, "24,800 exported records and cache hash must pass"),
        "official_evaluator_parity": _require(evaluator_ready, "Official evaluator mapping and parity must be resolved"),
        "real_one_step_preflight": _require(preflight_ready, "Exactly one real-data optimizer step must pass"),
        "exact_epoch_resume": _require(exact_resume_ready, "Exact multi-worker augmented resume test must pass"),
        "canonical_full_run_guard": _require(full_run_guard, "full_run_blocked must remain true for R2 review"),
    }
    blockers = [name for name, requirement in requirements.items() if not requirement["passed"]]
    ready = not blockers
    return {
        "schema_version": 1,
        "status": READY_STATUS if ready else BLOCKED_STATUS,
        "ready": ready,
        "claim_level": claim_level,
        "variant": str(reproduction.get("variant", "unspecified")),
        "requirements": requirements,
        "blockers": blockers,
        "input_evidence": evidence,
        "canonical_validation_error": canonical_validation_error,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# R2 Conference Reproduction Readiness Report",
        "",
        f"Final status: `{report['status']}`",
        "",
        f"Claim level: `{report['claim_level']}`",
        f"Variant: `{report['variant']}`",
        "",
        "## Readiness gates",
        "",
        "| Gate | Result | Requirement |",
        "|---|---:|---|",
    ]
    for name, item in report["requirements"].items():
        lines.append(f"| `{name}` | {'PASS' if item['passed'] else 'BLOCKED'} | {item['details']} |")
    lines.extend(["", "## Blockers", ""])
    if report["blockers"]:
        lines.extend(f"- `{name}`" for name in report["blockers"])
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Execution boundary",
            "",
            "No full conference training is authorized by this receipt. The canonical `full_run_blocked` guard remains true pending the next human review.",
            "",
            f"Final status: `{report['status']}`",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the fail-closed R2 conference readiness receipt")
    parser.add_argument("--config", default="configs/ov_orthkd_mm26_repro.yaml")
    for name, default in DEFAULT_INPUTS.items():
        parser.add_argument("--" + name.replace("_", "-"), default=default)
    parser.add_argument("--output-json", default="reports/mm26_conference_readiness.json")
    parser.add_argument("--output-report", default="reports/R2_CONFERENCE_REPRODUCTION_READINESS_REPORT.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    inputs = {name: getattr(args, name) for name in DEFAULT_INPUTS}
    report = build_conference_readiness(config, inputs)
    output_json = Path(args.output_json)
    output_report = Path(args.output_report)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output_report.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["ready"] else 1)


if __name__ == "__main__":
    main()
