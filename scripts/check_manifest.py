#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect an OV-AVEL or fallback AV manifest")
    parser.add_argument("--manifest", type=str, required=True)
    parser.add_argument("--fail-on-missing", action="store_true")
    return parser.parse_args()


def load_manifest(path_str: str) -> List[Dict[str, Any]]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path_str}")
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Expected a JSON list.")
        return data

    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at line {line_no}") from exc
    return records


def _exists(path_str: str | None) -> bool:
    return bool(path_str) and Path(path_str).exists()


def _iter_path_strings(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, (str, Path)):
        yield str(value)
        return
    if isinstance(value, dict):
        path_value = value.get("path")
        if path_value:
            yield str(path_value)
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_path_strings(item)


def _missing_count(value: Any) -> int:
    return sum(0 if _exists(path_str) else 1 for path_str in _iter_path_strings(value))


def _missing_path_value(value: Any) -> bool:
    if isinstance(value, (str, Path)):
        return not _exists(str(value))
    return False


def _has_teacher_artifacts(record: Dict[str, Any]) -> bool:
    return any(
        record.get(field) is not None
        for field in (
            "strong_teacher_features",
            "strong_teacher_features_path",
            "strong_teacher_logits",
            "strong_teacher_logits_path",
            "weak_teacher_features",
            "weak_teacher_features_path",
            "text_embedding",
            "text_embedding_path",
        )
    )


def _has_audio_source(record: Dict[str, Any]) -> bool:
    if record.get("audio_path") or record.get("wav_path") or record.get("waveform_path"):
        return True
    for field in ("audio_segment_paths", "audio_paths", "audio_waveform_paths", "waveform_paths"):
        if record.get(field):
            return True
    return False


def summarize_ov_avel(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    domains = Counter()
    queries = Counter()
    total_segments = 0
    missing_frames = 0
    missing_specs = 0
    missing_audio_sources = 0
    missing_raw_videos = 0
    missing_strong_feat = 0
    missing_strong_logit = 0
    missing_weak_feat = 0
    missing_text = 0
    manifest_stage = "exported" if any(_has_teacher_artifacts(record) for record in records) else "source"

    for record in records:
        domains[record.get("domain", "unknown")] += 1
        queries[record.get("query", "unknown")] += 1
        segment_labels = record.get("segment_labels", [])
        total_segments += len(segment_labels)

        frame_value = (
            record.get("segment_frame_paths")
            or record.get("frame_groups")
            or record.get("frame_paths")
            or record.get("frames")
        )
        spec_value = (
            record.get("spectrogram_paths")
            or record.get("spectrograms")
            or record.get("audio_image_paths")
        )

        missing_frames += _missing_count(frame_value)
        missing_specs += _missing_count(spec_value)
        audio_value = (
            record.get("audio_path")
            or record.get("wav_path")
            or record.get("waveform_path")
            or record.get("audio_segment_paths")
            or record.get("audio_paths")
            or record.get("audio_waveform_paths")
            or record.get("waveform_paths")
        )
        if not _has_audio_source(record):
            missing_audio_sources += 1
        else:
            missing_audio_sources += _missing_count(audio_value)
        raw_video_value = (
            record.get("raw_video_path")
            or record.get("official_video_path")
            or record.get("video_path")
        )
        missing_raw_videos += 1 if raw_video_value is None else _missing_count(raw_video_value)

        strong_feat_value = record.get("strong_teacher_features") or record.get("strong_teacher_features_path")
        strong_logit_value = record.get("strong_teacher_logits") or record.get("strong_teacher_logits_path")
        weak_feat_value = record.get("weak_teacher_features") or record.get("weak_teacher_features_path")
        text_value = record.get("text_embedding") or record.get("text_embedding_path")

        if strong_feat_value is not None and _missing_path_value(strong_feat_value):
            missing_strong_feat += 1
        if strong_logit_value is not None and _missing_path_value(strong_logit_value):
            missing_strong_logit += 1
        if weak_feat_value is not None and _missing_path_value(weak_feat_value):
            missing_weak_feat += 1
        if text_value is not None and _missing_path_value(text_value):
            missing_text += 1

    return {
        "task": "ov_avel",
        "manifest_stage": manifest_stage,
        "num_records": len(records),
        "avg_segments": total_segments / max(len(records), 1),
        "top_domains": domains.most_common(10),
        "top_queries": queries.most_common(10),
        "missing_frames": missing_frames,
        "missing_spectrograms": missing_specs,
        "missing_audio_sources": missing_audio_sources,
        "missing_raw_videos": missing_raw_videos,
        "missing_strong_teacher_features": missing_strong_feat,
        "missing_strong_teacher_logits": missing_strong_logit,
        "missing_weak_teacher_features": missing_weak_feat,
        "missing_text_embeddings": missing_text,
    }


def summarize_fallback(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    domains = Counter(record.get("domain", "unknown") for record in records)
    labels = Counter(int(record.get("label", -1)) for record in records)
    missing_frames = sum(0 if _exists(record.get("frame_path")) else 1 for record in records)
    missing_specs = sum(0 if _exists(record.get("spectrogram_path")) else 1 for record in records)
    return {
        "task": "fallback_av_deepfake",
        "num_records": len(records),
        "label_distribution": dict(labels),
        "top_domains": domains.most_common(10),
        "missing_frames": missing_frames,
        "missing_spectrograms": missing_specs,
    }


def main() -> None:
    args = parse_args()
    records = load_manifest(args.manifest)
    if not records:
        raise ValueError("Manifest is empty.")

    if "segment_labels" in records[0]:
        summary = summarize_ov_avel(records)
        missing_total = (
            summary["missing_frames"]
            + summary["missing_spectrograms"]
            + summary["missing_audio_sources"]
            + summary["missing_strong_teacher_features"]
            + summary["missing_strong_teacher_logits"]
            + summary["missing_weak_teacher_features"]
            + summary["missing_text_embeddings"]
        )
    else:
        summary = summarize_fallback(records)
        missing_total = summary["missing_frames"] + summary["missing_spectrograms"]

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.fail_on_missing and missing_total > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
