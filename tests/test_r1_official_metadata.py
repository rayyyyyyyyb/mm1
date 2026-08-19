from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.audit_official_ov_avebench_metadata import audit_official_metadata


def _write_official_sized_fixture(meta_csv: Path, annotation_json: Path) -> None:
    close_classes = [f"close_{index:02d}" for index in range(46)]
    open_classes = [f"open_{index:02d}" for index in range(21)]
    partitions = [
        ("train", "close", 13182, close_classes),
        ("val", "close", 1651, close_classes),
        ("val", "open", 4147, open_classes),
        ("test", "close", 1664, close_classes),
        ("test", "open", 4156, open_classes),
    ]
    annotations = {}
    with meta_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["split", "cls_name", "cls_type", "vid_name"])
        writer.writeheader()
        global_index = 0
        for split, group, count, classes in partitions:
            for partition_index in range(count):
                video_id = f"video_{global_index:05d}"
                category = classes[partition_index % len(classes)]
                writer.writerow(
                    {
                        "split": split,
                        "cls_name": category,
                        "cls_type": group,
                        "vid_name": video_id,
                    }
                )
                labels = [1 if offset <= partition_index % 10 else 0 for offset in range(10)]
                annotations[video_id] = {"category": category, "label": repr(labels)}
                global_index += 1
    annotation_json.write_text(json.dumps(annotations), encoding="utf-8")


def test_exact_official_split_class_group_and_label_counts(tmp_path: Path) -> None:
    meta_csv = tmp_path / "meta.csv"
    annotation_json = tmp_path / "annotations.json"
    _write_official_sized_fixture(meta_csv, annotation_json)

    report = audit_official_metadata(meta_csv, annotation_json)

    assert report["status"] == "passed"
    assert report["errors"] == []
    assert report["counts"] == {
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
    assert report["label_length_histogram"] == {"10": 24800}
    assert report["duplicate_video_ids"] == []
    assert report["csv_only_ids"] == []
    assert report["annotation_only_ids"] == []


def _write_small_fixture(meta_csv: Path, annotation_json: Path) -> None:
    with meta_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["split", "cls_name", "cls_type", "vid_name"])
        writer.writeheader()
        writer.writerow({"split": "train", "cls_name": "dog", "cls_type": "close", "vid_name": "a"})
        writer.writerow({"split": "val", "cls_name": "cat", "cls_type": "open", "vid_name": "b"})
    annotation_json.write_text(
        json.dumps(
            {
                "a": {"category": "dog", "label": "[1, 0]"},
                "b": {"category": "cat", "label": "[0, 1]"},
            }
        ),
        encoding="utf-8",
    )


def test_audit_reports_duplicate_ids_and_annotation_bijection(tmp_path: Path) -> None:
    meta_csv = tmp_path / "meta.csv"
    annotation_json = tmp_path / "annotations.json"
    _write_small_fixture(meta_csv, annotation_json)
    with meta_csv.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow(["test", "dog", "close", "a"])
    annotations = json.loads(annotation_json.read_text(encoding="utf-8"))
    annotations["orphan"] = {"category": "bird", "label": "[1, 0]"}
    annotation_json.write_text(json.dumps(annotations), encoding="utf-8")

    report = audit_official_metadata(meta_csv, annotation_json, enforce_official_counts=False)
    codes = {error["code"] for error in report["errors"]}

    assert report["status"] == "failed"
    assert "duplicate_video_id" in codes
    assert "annotation_id_bijection" in codes
    assert report["annotation_only_ids"] == ["orphan"]


def test_audit_rejects_nonbinary_labels_category_mismatch_and_open_train(tmp_path: Path) -> None:
    meta_csv = tmp_path / "meta.csv"
    annotation_json = tmp_path / "annotations.json"
    _write_small_fixture(meta_csv, annotation_json)
    rows = list(csv.DictReader(meta_csv.open(encoding="utf-8", newline="")))
    rows[0]["cls_type"] = "open"
    with meta_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["split", "cls_name", "cls_type", "vid_name"])
        writer.writeheader()
        writer.writerows(rows)
    annotations = json.loads(annotation_json.read_text(encoding="utf-8"))
    annotations["a"] = {"category": "not dog", "label": "[0, 2]"}
    annotation_json.write_text(json.dumps(annotations), encoding="utf-8")

    report = audit_official_metadata(meta_csv, annotation_json, enforce_official_counts=False)
    codes = {error["code"] for error in report["errors"]}

    assert "open_class_in_train" in codes
    assert "category_mismatch" in codes
    assert "nonbinary_label" in codes
