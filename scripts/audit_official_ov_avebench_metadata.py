#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path_str: str | Path, content: str) -> None:
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


OFFICIAL_COUNTS = {
    "records": 24800,
    "splits": {"test": 5820, "train": 13182, "val": 5798},
    "groups": {"close": 16497, "open": 8303},
    "split_groups": {
        "test/close": 1664,
        "test/open": 4156,
        "train/close": 13182,
        "val/close": 1651,
        "val/open": 4147,
    },
    "classes": 67,
    "classes_by_group": {"close": 46, "open": 21},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the pinned official OV-AVEBench metadata")
    parser.add_argument("--meta-csv", required=True)
    parser.add_argument("--annotation-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--fail-on-error", action="store_true")
    return parser.parse_args()


def _sorted_counter(counter: Counter[Any], *, tuple_keys: bool = False) -> dict[str, int]:
    if tuple_keys:
        return {"/".join(str(value) for value in key): int(count) for key, count in sorted(counter.items())}
    return {str(key): int(count) for key, count in sorted(counter.items())}


class _Issues:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}

    def add(self, code: str, message: str, example: Any | None = None) -> None:
        issue = self.values.setdefault(code, {"code": code, "message": message, "count": 0, "examples": []})
        issue["count"] += 1
        if example is not None and len(issue["examples"]) < 10:
            issue["examples"].append(example)

    def output(self) -> list[dict[str, Any]]:
        return [self.values[key] for key in sorted(self.values)]


def _parse_labels(raw: Any) -> list[Any]:
    labels = ast.literal_eval(raw) if isinstance(raw, str) else raw
    if not isinstance(labels, list):
        raise ValueError("label must decode to a list")
    return labels


def audit_official_metadata(
    meta_csv: str | Path,
    annotation_json: str | Path,
    *,
    enforce_official_counts: bool = True,
) -> dict[str, Any]:
    meta_path = Path(meta_csv).resolve()
    annotation_path = Path(annotation_json).resolve()
    issues = _Issues()

    with meta_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required_fields = {"split", "cls_name", "cls_type", "vid_name"}
        if reader.fieldnames is None or set(reader.fieldnames) != required_fields:
            issues.add(
                "csv_schema",
                "CSV fields must be exactly split, cls_name, cls_type, vid_name",
                reader.fieldnames,
            )
        rows = list(reader)

    annotations = json.loads(annotation_path.read_text(encoding="utf-8"))
    if not isinstance(annotations, dict):
        raise ValueError("Official annotation JSON must be an object keyed by vid_name")

    split_counts: Counter[str] = Counter()
    group_counts: Counter[str] = Counter()
    split_group_counts: Counter[tuple[str, str]] = Counter()
    id_counts: Counter[str] = Counter()
    classes: set[str] = set()
    classes_by_group: defaultdict[str, set[str]] = defaultdict(set)
    row_by_id: dict[str, dict[str, str]] = {}

    for row_index, row in enumerate(rows, start=2):
        split = str(row.get("split", "")).strip()
        group = str(row.get("cls_type", "")).strip()
        category = str(row.get("cls_name", "")).strip()
        video_id = str(row.get("vid_name", "")).strip()
        if split not in {"train", "val", "test"}:
            issues.add("invalid_split", "split must be train, val, or test", {"row": row_index, "value": split})
        if group not in {"close", "open"}:
            issues.add("invalid_group", "cls_type must be close or open", {"row": row_index, "value": group})
        if not category:
            issues.add("empty_category", "cls_name must be non-empty", {"row": row_index})
        if not video_id:
            issues.add("empty_video_id", "vid_name must be non-empty", {"row": row_index})
        if split == "train" and group == "open":
            issues.add("open_class_in_train", "train must not contain open/unseen records", video_id)
        split_counts[split] += 1
        group_counts[group] += 1
        split_group_counts[(split, group)] += 1
        id_counts[video_id] += 1
        if id_counts[video_id] > 1:
            issues.add("duplicate_video_id", "vid_name must be globally unique", video_id)
        classes.add(category)
        classes_by_group[group].add(category)
        row_by_id.setdefault(video_id, row)

    class_group_membership: defaultdict[str, set[str]] = defaultdict(set)
    for group, group_classes in classes_by_group.items():
        for category in group_classes:
            class_group_membership[category].add(group)
    for category, groups in class_group_membership.items():
        if len(groups) != 1:
            issues.add("class_group_overlap", "a class must belong to exactly one group", {"category": category, "groups": sorted(groups)})

    csv_ids = set(row_by_id)
    annotation_ids = {str(value) for value in annotations}
    csv_only = sorted(csv_ids - annotation_ids)
    annotation_only = sorted(annotation_ids - csv_ids)
    if csv_only or annotation_only:
        issues.add(
            "annotation_id_bijection",
            "CSV vid_name and annotation keys must be a bijection",
            {"csv_only": csv_only[:10], "annotation_only": annotation_only[:10]},
        )

    length_histogram: Counter[int] = Counter()
    positive_histogram: Counter[int] = Counter()
    label_value_histogram: Counter[int] = Counter()
    for video_id in sorted(csv_ids & annotation_ids):
        item = annotations[video_id]
        if not isinstance(item, dict):
            issues.add("annotation_schema", "annotation entry must be an object", video_id)
            continue
        annotation_category = str(item.get("category", "")).strip()
        if not annotation_category:
            issues.add("empty_annotation_category", "annotation category must be non-empty", video_id)
        expected_category = str(row_by_id[video_id].get("cls_name", "")).strip()
        if annotation_category != expected_category:
            issues.add(
                "category_mismatch",
                "annotation category must equal CSV cls_name",
                {"vid_name": video_id, "csv": expected_category, "annotation": annotation_category},
            )
        try:
            labels = _parse_labels(item.get("label"))
        except (SyntaxError, ValueError, TypeError) as exc:
            issues.add("invalid_label", "label must be a parseable non-empty list", {"vid_name": video_id, "error": str(exc)})
            continue
        if not labels:
            issues.add("empty_label", "label sequence must be non-empty", video_id)
            continue
        length_histogram[len(labels)] += 1
        if any(not isinstance(value, (int, float)) or value not in (0, 1) for value in labels):
            issues.add("nonbinary_label", "labels must contain only binary 0/1 values", video_id)
            continue
        integer_labels = [int(value) for value in labels]
        label_value_histogram.update(integer_labels)
        positive_histogram[sum(integer_labels)] += 1

    counts = {
        "records": len(rows),
        "splits": _sorted_counter(split_counts),
        "groups": _sorted_counter(group_counts),
        "split_groups": _sorted_counter(split_group_counts, tuple_keys=True),
        "classes": len(classes),
        "classes_by_group": {
            group: len(classes_by_group.get(group, set())) for group in ("close", "open")
        },
    }
    if enforce_official_counts:
        for key in ("records", "splits", "groups", "split_groups", "classes", "classes_by_group"):
            if counts[key] != OFFICIAL_COUNTS[key]:
                issues.add(
                    "official_count_mismatch",
                    f"official {key} count does not match the locked expectation",
                    {"field": key, "expected": OFFICIAL_COUNTS[key], "actual": counts[key]},
                )
        if _sorted_counter(length_histogram) != {"10": 24800}:
            issues.add(
                "official_label_length_mismatch",
                "official labels must all have length 10",
                _sorted_counter(length_histogram),
            )

    errors = issues.output()
    return {
        "schema_version": 1,
        "status": "passed" if not errors else "failed",
        "meta_csv": {
            "path": meta_path.as_posix(),
            "bytes": meta_path.stat().st_size,
            "sha256": sha256_file(meta_path),
        },
        "annotation_json": {
            "path": annotation_path.as_posix(),
            "bytes": annotation_path.stat().st_size,
            "sha256": sha256_file(annotation_path),
        },
        "counts": counts,
        "label_length_histogram": _sorted_counter(length_histogram),
        "positive_segment_histogram": _sorted_counter(positive_histogram),
        "label_value_histogram": _sorted_counter(label_value_histogram),
        "duplicate_video_ids": sorted(video_id for video_id, count in id_counts.items() if count > 1),
        "csv_only_ids": csv_only,
        "annotation_only_ids": annotation_only,
        "errors": errors,
    }


def _render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "# Official OV-AVEBench Metadata Audit",
        "",
        f"- Status: `{report['status']}`",
        f"- Records: `{counts['records']}`",
        f"- Splits: `{json.dumps(counts['splits'], sort_keys=True)}`",
        f"- Groups: `{json.dumps(counts['groups'], sort_keys=True)}`",
        f"- Classes: `{counts['classes']}`",
        f"- Classes by group: `{json.dumps(counts['classes_by_group'], sort_keys=True)}`",
        f"- Label length histogram: `{json.dumps(report['label_length_histogram'], sort_keys=True)}`",
        f"- Positive segment histogram: `{json.dumps(report['positive_segment_histogram'], sort_keys=True)}`",
        f"- Duplicate IDs: `{len(report['duplicate_video_ids'])}`",
        f"- CSV-only IDs: `{len(report['csv_only_ids'])}`",
        f"- Annotation-only IDs: `{len(report['annotation_only_ids'])}`",
        "",
        "## Errors",
        "",
    ]
    if report["errors"]:
        lines.extend(f"- `{error['code']}` ({error['count']}): {error['message']}" for error in report["errors"])
    else:
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    report = audit_official_metadata(args.meta_csv, args.annotation_json)
    atomic_write_text(args.output_json, json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    atomic_write_text(args.output_md, _render_markdown(report))
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    if args.fail_on_error and report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
