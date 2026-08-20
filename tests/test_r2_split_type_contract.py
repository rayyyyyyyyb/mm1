from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pytest

from scripts.audit_mm26_reproduction import audit_reproduction
from scripts.train_ov_orthkd import _batch_split_type
from src.data import QueryConditionedOVAvelDataset
try:
    from src.data.split_types import normalize_split_type, split_type_from_record
except ModuleNotFoundError:
    normalize_split_type = None
    split_type_from_record = None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("close", "seen"), ("seen", "seen"), ("open", "unseen"), ("unseen", "unseen")],
)
def test_normalize_split_type_maps_only_documented_official_labels(raw: str, expected: str) -> None:
    assert normalize_split_type is not None, "R2 shared split-type helper is missing"
    assert normalize_split_type(raw) == expected


def test_split_type_from_record_reads_historical_meta_cls_type() -> None:
    assert split_type_from_record is not None, "R2 shared split-type helper is missing"
    assert split_type_from_record({"meta": {"cls_type": "open"}}) == "unseen"


def test_split_type_from_record_rejects_contradictory_fields() -> None:
    assert split_type_from_record is not None, "R2 shared split-type helper is missing"
    with pytest.raises(ValueError, match="Contradictory split type"):
        split_type_from_record({"split_type": "seen", "meta": {"cls_type": "open"}})


def test_official_partition_counts_map_to_exact_seen_unseen_counts() -> None:
    assert split_type_from_record is not None, "R2 shared split-type helper is missing"
    official_partitions = [
        ("train", "close", 13182),
        ("val", "close", 1651),
        ("val", "open", 4147),
        ("test", "close", 1664),
        ("test", "open", 4156),
    ]
    counts: Counter[tuple[str, str]] = Counter()
    for split, cls_type, count in official_partitions:
        for _ in range(count):
            counts[(split, split_type_from_record({"meta": {"cls_type": cls_type}}))] += 1

    assert counts == {
        ("train", "seen"): 13182,
        ("val", "seen"): 1651,
        ("val", "unseen"): 4147,
        ("test", "seen"): 1664,
        ("test", "unseen"): 4156,
    }


def _write_manifest(path: Path, record: dict[str, object]) -> None:
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


def _minimal_record(record_id: str, cls_type: str) -> dict[str, object]:
    return {
        "id": record_id,
        "query": "query",
        "segment_labels": [1, 0],
        "segment_frame_paths": [],
        "spectrogram_paths": [],
        "meta": {"cls_type": cls_type},
    }


def test_dataset_uses_shared_meta_cls_type_contract(tmp_path: Path) -> None:
    manifest = tmp_path / "data.jsonl"
    _write_manifest(manifest, _minimal_record("sample", "open"))
    dataset = QueryConditionedOVAvelDataset(
        manifest_path=str(manifest),
        path_root=str(tmp_path),
        image_size=8,
        max_segments=2,
        augment=False,
        allow_missing_modalities=True,
        strict_alignment=True,
        strong_teacher_dim=3,
        weak_teacher_dim=4,
        text_dim=5,
    )

    assert dataset[0]["split_type"] == "unseen"


def test_audit_uses_shared_meta_cls_type_contract(tmp_path: Path) -> None:
    manifests = {}
    for split, cls_type in (("train", "close"), ("val", "open"), ("test", "open")):
        manifests[split] = tmp_path / f"{split}.jsonl"
        _write_manifest(manifests[split], _minimal_record(split, cls_type))

    report = audit_reproduction(
        train_manifest=manifests["train"],
        val_manifest=manifests["val"],
        test_manifest=manifests["test"],
        path_root=tmp_path,
        stage="source",
        artifact_scan="none",
        sample_count=0,
        expected_segments="auto",
    )

    assert report["split_type_counts"] == {"seen": 1, "unseen": 2}
    assert not [error for error in report["errors"] if error["code"] == "missing_split_type"]


def test_evaluation_batch_parser_uses_shared_meta_cls_type_contract() -> None:
    assert _batch_split_type({"meta": [{"cls_type": "open"}]}, 0) == "unseen"


def test_evaluation_batch_parser_preserves_unknown_non_split_domains() -> None:
    assert _batch_split_type({"domain": ["ov_avebench"]}, 0) == "unknown"
