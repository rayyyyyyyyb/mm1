"""Read-only provenance inventory for the projector-collapse investigation.

The scanner deliberately treats repository task books and current diagnostic
configs as non-historical evidence.  It never infers a value from paper prose.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable


FACT_PATTERNS: dict[str, tuple[str, ...]] = {
    "strong_projector_update": ("strong_teacher_proj", "teacher_target_projector_trainable"),
    "visual_l2_reduction": ("visual_l2_reduction", "lambda_v_feat", "alpha_strong_feat"),
    "schedule_step400": ("step400", "step 400", "step_400"),
    "early_stop": ("early_stop", "early stop", "patience"),
    "student_pretrained": ("pretrained", "weights=", "weights ="),
    "query_anchor_mode": ("query_anchor_mode", "text_anchor"),
    "teacher_sampling": ("frame_sampling", "num_frames", "clip_len", "sampling_rate"),
    "reported_targets": ("0.778", "0.816", "45.78", "0.714"),
}

HISTORICAL_TYPES = {"config", "checkpoint_metadata", "training_log", "command_history", "git"}
TASK_BOOK_MARKERS = ("TASK.md", "任务书", "task book")
CURRENT_MARKERS = (
    "all.md",
    "reports/",
    "/reports/",
    "outputs/",
    "/outputs/",
    "diagnostic/",
    "/diagnostic/",
    "configs/",
    "/configs/",
    "src/",
    "/src/",
    "scripts/",
    "/scripts/",
    "tests/",
    "/tests/",
    "data/",
    "/data/",
    "weights/",
    "/weights/",
    ".tmp",
)
TEXT_SUFFIXES = {
    ".bat", ".cfg", ".conf", ".csv", ".ini", ".json", ".jsonl", ".log",
    ".md", ".ps1", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml",
}
SECRET_PATTERNS = (
    (re.compile(r"(?i)(token|password|passwd|secret|api[_ -]?key)\s*[:=]\s*[^\s,;]+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
)


def redact_text(value: str) -> str:
    result = value
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def classify_fact_evidence(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    historical = [row for row in evidence if row.get("source_type") in HISTORICAL_TYPES]
    values = sorted({str(row.get("value")) for row in historical if row.get("value") is not None})
    if not historical or not values:
        status = "NOT_FOUND"
    elif len(values) > 1:
        status = "AMBIGUOUS"
    else:
        status = "FOUND"
    result: dict[str, Any] = {
        "status": status,
        "historical_evidence": bool(historical),
        "values": values,
        "evidence": [
            {
                "path": str(row["path"]),
                "source_type": row.get("source_type"),
                "value": row.get("value"),
                "excerpt": redact_text(str(row.get("excerpt", ""))),
            }
            for row in evidence
        ],
    }
    if status == "FOUND" and values:
        result["value"] = values[0]
    return result


def _run_git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout


def _source_type(path: Path) -> str:
    lower = path.name.lower()
    if any(marker.lower() in lower for marker in TASK_BOOK_MARKERS):
        return "task_book"
    path_text = str(path).lower().replace("\\", "/")
    if any(marker in path_text for marker in CURRENT_MARKERS):
        return "current_diagnostic"
    if lower.endswith((".yaml", ".yml", ".json", ".toml", ".ini")):
        return "config"
    if lower.endswith((".pt", ".pth", ".ckpt", ".safetensors")):
        return "checkpoint_metadata"
    if lower.endswith((".log", ".jsonl", ".tfevents")):
        return "training_log"
    if "history" in lower or lower.endswith((".ps1", ".sh", ".bat")):
        return "command_history"
    if lower.endswith(".md"):
        return "documentation"
    if lower.endswith(".py"):
        return "source_code"
    return "other"


def _value_for_match(line: str, fact: str) -> str | None:
    patterns = FACT_PATTERNS[fact]
    for pattern in patterns:
        match = re.search(rf"{re.escape(pattern)}\s*[:=]\s*([^,#\s]+)", line, re.IGNORECASE)
        if match:
            return match.group(1).strip("'\"`")
    if fact == "reported_targets":
        found = [value for value in patterns if value in line]
        return ",".join(found) if found else None
    return None


def _scan_file(path: Path, repo_root: Path) -> Iterable[dict[str, Any]]:
    try:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            return []
        if path.stat().st_size > 8 * 1024 * 1024:
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return []
    source_type = _source_type(path)
    relative = str(path.resolve().relative_to(repo_root.resolve())) if path.resolve().is_relative_to(repo_root.resolve()) else str(path)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for fact in FACT_PATTERNS:
            if any(pattern.lower() in line.lower() for pattern in FACT_PATTERNS[fact]):
                rows.append(
                    {
                        "path": relative,
                        "source_type": source_type,
                        "value": _value_for_match(line, fact),
                        "excerpt": f"line {line_number}: {line[:500]}",
                    }
                )
    return rows


def collect_inventory(repo_root: Path, search_roots: list[Path] | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    roots = [repo_root] if search_roots is None else [root.resolve() for root in search_roots]
    evidence: dict[str, list[dict[str, Any]]] = {fact: [] for fact in FACT_PATTERNS}
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else root.rglob("*")
        for candidate in candidates:
            if not candidate.is_file() or candidate in seen:
                continue
            if ".git" in candidate.parts or "__pycache__" in candidate.parts:
                continue
            seen.add(candidate)
            rows = _scan_file(candidate, repo_root)
            for row in rows:
                # Current source, task books, and generated diagnostics are
                # useful context but cannot establish historical provenance;
                # omit their bulky excerpts from the machine-readable report.
                if row.get("source_type") not in HISTORICAL_TYPES:
                    continue
                line = row["excerpt"]
                for fact, patterns in FACT_PATTERNS.items():
                    if any(pattern.lower() in line.lower() for pattern in patterns):
                        evidence[fact].append(row)
    git_log = _run_git(repo_root, "log", "--all", "--oneline", "--decorate", "-n", "200")
    git_refs = _run_git(repo_root, "show-ref")
    git_reflog = _run_git(repo_root, "reflog", "--all", "--date=iso", "-n", "200")
    git_text = "\n".join((git_log, git_refs, git_reflog))
    for fact, patterns in FACT_PATTERNS.items():
        hits = [line[:500] for line in git_text.splitlines() if any(pattern.lower() in line.lower() for pattern in patterns)]
        evidence[fact].extend(
            {"path": "<git-history>", "source_type": "git", "value": None, "excerpt": hit}
            for hit in hits
        )
    facts = {fact: classify_fact_evidence(rows) for fact, rows in evidence.items()}
    return {
        "schema_version": 1,
        "repo_root": str(repo_root),
        "search_roots": [str(root) for root in roots],
        "facts": facts,
        "git_refs_count": len(git_refs.splitlines()),
        "git_reflog_lines": len(git_reflog.splitlines()),
        "policy": {
            "task_books_are_non_historical": True,
            "missing_values_are_unknown": True,
            "secrets_redacted": True,
        },
    }


def render_markdown(inventory: dict[str, Any]) -> str:
    lines = [
        "# Projector-Collapse Provenance Audit",
        "",
        "This is a read-only inventory. Task books and current diagnostic configs are not historical proof; missing values remain UNKNOWN.",
        "",
        "| Fact | Status | Value(s) | Historical evidence |",
        "|---|---|---|---|",
    ]
    for fact, row in inventory["facts"].items():
        values = ", ".join(row.get("values", [])) or "UNKNOWN"
        lines.append(f"| `{fact}` | **{row['status']}** | `{values}` | `{row['historical_evidence']}` |")
    lines.extend(["", "## Evidence", ""])
    for fact, row in inventory["facts"].items():
        lines.append(f"### {fact}")
        for evidence in row["evidence"][:30]:
            lines.append(f"- `{evidence['source_type']}` `{evidence['path']}`: {evidence['excerpt']}")
        if len(row["evidence"]) > 30:
            lines.append(f"- ({len(row['evidence']) - 30} additional hits omitted from the human-readable report; see JSON.)")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--search-root", action="append", type=Path, default=[])
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    roots = args.search_root or [args.repo_root]
    inventory = collect_inventory(args.repo_root, roots)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.output_md.write_text(render_markdown(inventory), encoding="utf-8")
    print(json.dumps({fact: row["status"] for fact, row in inventory["facts"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
