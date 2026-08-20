from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms

from src.data.split_types import split_type_from_record
from src.data.audio_preprocessing import AudioPreprocessingSpec, load_official_wav_for_student


IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def _load_manifest(manifest_path: str) -> List[Dict[str, Any]]:
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON list in {manifest_path}")
        return data

    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {manifest_path}:{line_no}") from exc
    return records


def _ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _build_frame_transform(image_size: int, augment: bool) -> transforms.Compose:
    ops: List[Any] = [transforms.Resize((image_size, image_size))]
    if augment:
        ops.extend(
            [
                transforms.RandomHorizontalFlip(p=0.5),
                transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.02),
            ]
        )
    ops.extend([transforms.ToTensor(), transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD)])
    return transforms.Compose(ops)


def _build_spectrogram_transform(image_size: int) -> transforms.Compose:
    return transforms.Compose(
        [
            transforms.Resize((image_size, image_size)),
            transforms.ToTensor(),
            transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )


class QueryConditionedOVAvelDataset(Dataset):
    def __init__(
        self,
        manifest_path: str,
        image_size: int = 224,
        max_segments: int = 16,
        augment: bool = False,
        allow_missing_modalities: bool = True,
        strict_alignment: bool = True,
        strong_teacher_dim: int = 1024,
        weak_teacher_dim: int = 768,
        strong_teacher_logit_dim: int = 1,
        weak_teacher_logit_dim: int = 1,
        text_dim: int = 512,
        path_root: str = ".",
        required_artifacts: Sequence[str] | None = None,
        teacher_path_overrides: Dict[str, Any] | None = None,
        temporal_overflow_policy: str = "error",
        preprocessing_mode: str = "legacy_manifest_spectrograms",
        audio_preprocessing: Mapping[str, Any] | None = None,
    ) -> None:
        self.path_root = Path(path_root).expanduser().resolve()
        manifest = Path(manifest_path).expanduser()
        if not manifest.is_absolute():
            manifest = self.path_root / manifest
        self.records = _load_manifest(str(manifest.resolve()))
        self.frame_transform = _build_frame_transform(image_size, augment=augment)
        self.spec_transform = _build_spectrogram_transform(image_size)
        self.image_size = image_size
        self.max_segments = max_segments
        if self.max_segments < 1:
            raise ValueError("max_segments must be at least 1")
        self.temporal_overflow_policy = str(temporal_overflow_policy).lower()
        if self.temporal_overflow_policy not in {"error", "uniform"}:
            raise ValueError(
                "temporal_overflow_policy must be 'error' or explicit noncanonical 'uniform'"
            )
        self.allow_missing_modalities = allow_missing_modalities
        self.strict_alignment = strict_alignment
        self.strong_teacher_dim = strong_teacher_dim
        self.weak_teacher_dim = weak_teacher_dim
        self.strong_teacher_logit_dim = strong_teacher_logit_dim
        self.weak_teacher_logit_dim = weak_teacher_logit_dim
        self.text_dim = text_dim
        self.required_artifacts = set(required_artifacts or [])
        self.teacher_path_overrides = teacher_path_overrides or {}
        self.preprocessing_mode = str(preprocessing_mode)
        self.audio_spec = (
            AudioPreprocessingSpec.from_mapping(audio_preprocessing or {})
            if self.preprocessing_mode == "canonical_official_png_wav"
            else None
        )

    def __len__(self) -> int:
        return len(self.records)

    def _empty_image(self) -> Image.Image:
        return Image.new("RGB", (self.image_size, self.image_size))

    def _resolve_path(self, value: str | Path) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.path_root / path
        return path.resolve()

    def _artifact_required(self, field_name: str) -> bool:
        return field_name in self.required_artifacts

    def _read_image(self, path_str: str | None) -> tuple[Image.Image, float]:
        if path_str:
            path = self._resolve_path(path_str)
            if path.exists():
                with Image.open(path) as image:
                    return image.convert("RGB").copy(), 1.0
        if not self.allow_missing_modalities:
            resolved = self._resolve_path(path_str) if path_str else None
            raise FileNotFoundError(f"Missing modality file: {path_str} (resolved: {resolved})")
        return self._empty_image(), 0.0

    def _select_indices(self, seq_len: int) -> List[int]:
        if seq_len <= self.max_segments:
            return list(range(seq_len))
        if self.temporal_overflow_policy == "error":
            raise ValueError(
                f"seq_len={seq_len} exceeds max_segments={self.max_segments} under canonical error policy"
            )
        indices = np.linspace(0, seq_len - 1, num=self.max_segments, dtype=int).tolist()
        if len(indices) != self.max_segments or len(set(indices)) != len(indices):
            raise RuntimeError("Uniform temporal selection did not produce unique indices")
        if any(left >= right for left, right in zip(indices, indices[1:])):
            raise RuntimeError("Uniform temporal selection did not produce monotone indices")
        return indices

    def _remap_artifact_path(self, value: str, override: Any, field_name: str) -> str:
        if not isinstance(override, dict):
            raise ValueError(
                f"Override for {field_name} must define source_root and target_root"
            )
        if set(override) != {"source_root", "target_root"}:
            raise ValueError(
                f"Override for {field_name} must contain exactly source_root and target_root"
            )
        source_root = self._resolve_path(override["source_root"])
        target_root = self._resolve_path(override["target_root"])
        source_path = self._resolve_path(value)
        try:
            relative = source_path.relative_to(source_root)
        except ValueError as exc:
            raise ValueError(
                f"Artifact path for {field_name} is outside declared source_root: {source_path}"
            ) from exc
        remapped = (target_root / relative).resolve()
        try:
            remapped.relative_to(target_root)
        except ValueError as exc:
            raise ValueError(
                f"Remapped artifact path for {field_name} escapes target_root: {remapped}"
            ) from exc
        return str(remapped)

    def _normalize_paths(self, paths: Sequence[Any], target_len: int) -> List[str | None]:
        if self.strict_alignment and len(paths) not in (0, target_len):
            raise ValueError(f"Expected 0 or {target_len} paths, but received {len(paths)}.")
        normalized = list(paths[:target_len])
        if len(normalized) < target_len:
            normalized.extend([None] * (target_len - len(normalized)))
        return normalized

    def _normalize_segment_frame_paths(self, value: Any, target_len: int) -> List[str | None]:
        groups = _ensure_list(value)
        if self.strict_alignment and len(groups) not in (0, target_len):
            raise ValueError(f"Expected 0 or {target_len} frame groups, but received {len(groups)}.")

        normalized: List[str | None] = []
        for item in groups[:target_len]:
            if isinstance(item, list):
                candidates = [str(path) for path in item if path]
                if not candidates:
                    normalized.append(None)
                else:
                    normalized.append(candidates[len(candidates) // 2])
            elif item:
                normalized.append(str(item))
            else:
                normalized.append(None)

        if len(normalized) < target_len:
            normalized.extend([None] * (target_len - len(normalized)))
        return normalized

    def _load_image_sequence(
        self,
        paths: Sequence[str | None],
        indices: Sequence[int],
        transform: transforms.Compose,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        images: List[torch.Tensor] = []
        valids: List[torch.Tensor] = []
        for idx in indices:
            image, valid = self._read_image(paths[idx] if idx < len(paths) else None)
            images.append(transform(image))
            valids.append(torch.tensor(valid, dtype=torch.float32))
        return torch.stack(images, dim=0), torch.stack(valids, dim=0)

    def _load_canonical_student_audio(
        self,
        record: Mapping[str, Any],
        source_len: int,
        indices: Sequence[int],
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if self.audio_spec is None:
            raise RuntimeError("canonical audio preprocessing spec is missing")
        if source_len != self.audio_spec.segments:
            raise ValueError(
                f"official labels must contain {self.audio_spec.segments} segments, got {source_len}"
            )
        value = (
            record.get("wav_path")
            or record.get("audio_path")
            or record.get("official_wav_path")
        )
        if not isinstance(value, str) or not value:
            if not self.allow_missing_modalities:
                raise FileNotFoundError("canonical record is missing official WAV path")
            empty = torch.zeros(
                len(indices),
                self.audio_spec.student_channels,
                *self.audio_spec.student_size,
                dtype=torch.float32,
            )
            return empty, torch.zeros(len(indices), dtype=torch.float32)
        path = self._resolve_path(value)
        if not path.is_file():
            if not self.allow_missing_modalities:
                raise FileNotFoundError(f"Missing official WAV: {path}")
            empty = torch.zeros(
                len(indices),
                self.audio_spec.student_channels,
                *self.audio_spec.student_size,
                dtype=torch.float32,
            )
            return empty, torch.zeros(len(indices), dtype=torch.float32)
        tensor = load_official_wav_for_student(path, self.audio_spec)
        expected_shape = (
            self.audio_spec.segments,
            self.audio_spec.student_channels,
            *self.audio_spec.student_size,
        )
        if tuple(tensor.shape) != expected_shape or not bool(torch.isfinite(tensor).all()):
            raise ValueError(
                f"canonical student audio must be finite with shape {expected_shape}, got {tuple(tensor.shape)}"
            )
        return tensor[list(indices)], torch.ones(len(indices), dtype=torch.float32)

    def _load_ndarray(self, value: Any) -> np.ndarray | None:
        if value is None:
            return None
        if isinstance(value, str):
            path = self._resolve_path(value)
            if not path.exists():
                if self.allow_missing_modalities:
                    return None
                raise FileNotFoundError(f"Missing feature file: {value} (resolved: {path})")
            if path.suffix == ".npy":
                return np.load(path, allow_pickle=False)
            if path.suffix == ".npz":
                with np.load(path, allow_pickle=False) as data:
                    if "arr_0" in data:
                        return data["arr_0"]
                    first_key = next(iter(data.keys()))
                    return data[first_key]
            raise ValueError(f"Unsupported feature extension: {value}")
        return np.asarray(value, dtype=np.float32)

    def _select_array_rows(
        self,
        array: np.ndarray,
        source_len: int,
        indices: Sequence[int],
        expected_dim: int,
        field_name: str,
    ) -> np.ndarray:
        is_logit = field_name.endswith("_logits")
        if is_logit:
            if expected_dim != 1:
                raise ValueError(f"Logit dimension must be 1, got {expected_dim}")
            if array.ndim == 1:
                array = array[:, None]
            elif array.ndim != 2 or array.shape[1] != 1:
                raise ValueError(f"Expected logits shaped [T] or [T,1], got {list(array.shape)}")
        elif array.ndim != 2:
            raise ValueError(f"Expected features shaped [T,D], got {list(array.shape)}")

        if array.shape[0] == 1 and source_len > 1:
            raise ValueError(
                f"Refusing singleton teacher row broadcast from 1 to {source_len} segments"
            )
        if array.shape[0] != source_len:
            raise ValueError(
                f"Expected teacher sequence length {source_len}, received {array.shape[0]}"
            )
        if array.shape[1] != expected_dim:
            raise ValueError(
                f"Expected feature dimension {expected_dim}, received {array.shape[1]}"
            )
        return array[list(indices)]

    def _load_teacher_tensor(
        self,
        record: Dict[str, Any],
        field_name: str,
        source_len: int,
        indices: Sequence[int],
        expected_dim: int,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        value = record.get(field_name)
        if value is None:
            value = record.get(f"{field_name}_path")

        # Robust override check: match exact field_name or the base teacher name (strong_teacher/weak_teacher)
        base_name = field_name.replace("_features", "").replace("_logits", "")
        best_override_key = field_name if field_name in self.teacher_path_overrides else (
            base_name if base_name in self.teacher_path_overrides else None
        )

        if isinstance(value, str) and best_override_key:
            value = self._remap_artifact_path(
                value,
                self.teacher_path_overrides[best_override_key],
                field_name,
            )

        try:
            array = self._load_ndarray(value)
        except FileNotFoundError as exc:
            if self._artifact_required(field_name):
                raise FileNotFoundError(
                    f"Required artifact {field_name} is missing for record "
                    f"{record.get('id', '<unknown>')}: {value}"
                ) from exc
            raise
        if array is None:
            if self._artifact_required(field_name):
                raise FileNotFoundError(
                    f"Required artifact {field_name} is missing for record "
                    f"{record.get('id', '<unknown>')}: {value}"
                )
            return (
                torch.zeros(len(indices), expected_dim, dtype=torch.float32),
                torch.zeros(len(indices), dtype=torch.float32),
            )

        try:
            normalized = np.asarray(array, dtype=np.float32)
            if not np.isfinite(normalized).all():
                raise ValueError("all values must be finite")
            selected = self._select_array_rows(
                normalized,
                source_len,
                indices,
                expected_dim,
                field_name,
            )
        except ValueError as exc:
            raise ValueError(
                f"Invalid {field_name} for record {record.get('id', '<unknown>')}: {exc}"
            ) from exc
        return torch.from_numpy(selected.copy()), torch.ones(len(indices), dtype=torch.float32)

    def _load_text_embedding(self, record: Dict[str, Any]) -> tuple[torch.Tensor, torch.Tensor]:
        value = record.get("text_embedding")
        if value is None:
            value = record.get("text_embedding_path")
        if isinstance(value, str) and "text" in self.teacher_path_overrides:
            value = self._remap_artifact_path(
                value,
                self.teacher_path_overrides["text"],
                "text_embedding",
            )
        try:
            array = self._load_ndarray(value)
        except FileNotFoundError as exc:
            if self._artifact_required("text_embedding"):
                raise FileNotFoundError(
                    f"Required artifact text_embedding is missing for record "
                    f"{record.get('id', '<unknown>')}: {value}"
                ) from exc
            raise
        if array is None:
            if self._artifact_required("text_embedding"):
                raise FileNotFoundError(
                    f"Required artifact text_embedding is missing for record "
                    f"{record.get('id', '<unknown>')}: {value}"
                )
            return torch.zeros(self.text_dim, dtype=torch.float32), torch.tensor(0.0, dtype=torch.float32)

        embedding = np.asarray(array, dtype=np.float32).reshape(-1)
        if not np.isfinite(embedding).all():
            raise ValueError("Invalid text_embedding: all values must be finite")
        if embedding.shape[0] != self.text_dim:
            raise ValueError(f"Unexpected text dim: {embedding.shape[0]} != {self.text_dim}")
        return torch.from_numpy(embedding), torch.tensor(1.0, dtype=torch.float32)

    def __getitem__(self, index: int) -> Dict[str, Any]:
        record = self.records[index]

        labels = record.get("segment_labels")
        if labels is None:
            raise ValueError("Each OV-AVEL record must contain `segment_labels`.")
        labels_array = np.asarray(labels, dtype=np.float32).reshape(-1)
        if labels_array.size == 0:
            raise ValueError("segment_labels cannot be empty")
        if not np.isfinite(labels_array).all():
            raise ValueError("segment_labels must contain only finite values")
        if not np.isin(labels_array, (0.0, 1.0)).all():
            raise ValueError("segment_labels must be binary values 0 or 1")

        seq_len = int(labels_array.shape[0])
        indices = self._select_indices(seq_len)

        frame_value = (
            record.get("segment_frame_paths")
            or record.get("frame_groups")
            or record.get("frame_paths")
            or record.get("frames")
        )
        frame_paths = self._normalize_segment_frame_paths(frame_value, seq_len)
        frames, frame_valid = self._load_image_sequence(frame_paths, indices, self.frame_transform)
        if self.preprocessing_mode == "canonical_official_png_wav":
            spectrograms, audio_valid = self._load_canonical_student_audio(
                record, seq_len, indices
            )
        else:
            spec_paths = self._normalize_paths(
                _ensure_list(
                    record.get("spectrogram_paths")
                    or record.get("spectrograms")
                    or record.get("audio_image_paths")
                ),
                seq_len,
            )
            spectrograms, audio_valid = self._load_image_sequence(
                spec_paths, indices, self.spec_transform
            )

        strong_teacher_logits, strong_teacher_mask = self._load_teacher_tensor(
            record=record,
            field_name="strong_teacher_logits",
            source_len=seq_len,
            indices=indices,
            expected_dim=self.strong_teacher_logit_dim,
        )
        strong_teacher_features, strong_teacher_feature_mask = self._load_teacher_tensor(
            record=record,
            field_name="strong_teacher_features",
            source_len=seq_len,
            indices=indices,
            expected_dim=self.strong_teacher_dim,
        )
        weak_teacher_features, weak_teacher_mask = self._load_teacher_tensor(
            record=record,
            field_name="weak_teacher_features",
            source_len=seq_len,
            indices=indices,
            expected_dim=self.weak_teacher_dim,
        )
        weak_teacher_logits, weak_teacher_logit_mask = self._load_teacher_tensor(
            record=record,
            field_name="weak_teacher_logits",
            source_len=seq_len,
            indices=indices,
            expected_dim=self.weak_teacher_logit_dim,
        )
        text_embedding, text_valid = self._load_text_embedding(record)
        meta = record.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        split_type = split_type_from_record(record)

        selected_labels = torch.from_numpy(labels_array[indices])
        sequence_mask = torch.ones(len(indices), dtype=torch.float32)

        return {
            "id": record.get("id", str(index)),
            "query": record.get("query", record.get("text_query", "unknown event")),
            "domain": record.get("domain", "unknown"),
            "split_type": split_type,
            "selected_segment_indices": list(indices),
            "temporal_sampling_policy": self.temporal_overflow_policy,
            "noncanonical_temporal_sampling": seq_len > self.max_segments,
            "frame": frames,
            "spectrogram": spectrograms,
            "segment_label": selected_labels,
            "sequence_mask": sequence_mask,
            "frame_valid": frame_valid,
            "audio_valid": audio_valid,
            "strong_teacher_logits": strong_teacher_logits,
            "strong_teacher_logit_mask": strong_teacher_mask,
            "strong_teacher_feature_mask": strong_teacher_feature_mask,
            "strong_teacher_features": strong_teacher_features,
            "weak_teacher_features": weak_teacher_features,
            "weak_teacher_feature_mask": weak_teacher_mask,
            "weak_teacher_mask": weak_teacher_mask,
            "weak_teacher_logits": weak_teacher_logits,
            "weak_teacher_logit_mask": weak_teacher_logit_mask,
            "text_embedding": text_embedding,
            "text_valid": text_valid,
            "meta": meta,
        }


def _pad_sequence_tensor(tensor: torch.Tensor, target_len: int) -> torch.Tensor:
    if tensor.size(0) == target_len:
        return tensor
    pad_shape = (target_len - tensor.size(0),) + tensor.shape[1:]
    padding = torch.zeros(pad_shape, dtype=tensor.dtype)
    return torch.cat([tensor, padding], dim=0)


def ov_avel_collate_fn(batch: List[Dict[str, Any]]) -> Dict[str, Any]:
    max_len = max(item["segment_label"].size(0) for item in batch)
    collated: Dict[str, Any] = {
        "id": [item["id"] for item in batch],
        "query": [item["query"] for item in batch],
        "domain": [item["domain"] for item in batch],
        "split_type": [item["split_type"] for item in batch],
        "selected_segment_indices": [item["selected_segment_indices"] for item in batch],
        "temporal_sampling_policy": [item["temporal_sampling_policy"] for item in batch],
        "noncanonical_temporal_sampling": [item["noncanonical_temporal_sampling"] for item in batch],
        "meta": [item["meta"] for item in batch],
    }

    tensor_keys = [
        "frame",
        "spectrogram",
        "segment_label",
        "sequence_mask",
        "frame_valid",
        "audio_valid",
        "strong_teacher_logits",
        "strong_teacher_logit_mask",
        "strong_teacher_feature_mask",
        "strong_teacher_features",
        "weak_teacher_features",
        "weak_teacher_feature_mask",
        "weak_teacher_mask",
        "weak_teacher_logits",
        "weak_teacher_logit_mask",
    ]
    for key in tensor_keys:
        collated[key] = torch.stack([_pad_sequence_tensor(item[key], max_len) for item in batch], dim=0)

    collated["text_embedding"] = torch.stack([item["text_embedding"] for item in batch], dim=0)
    collated["text_valid"] = torch.stack([item["text_valid"] for item in batch], dim=0)
    return collated


def seed_worker(worker_id: int) -> None:
    del worker_id
    worker_seed = torch.initial_seed() % (2**32)
    np.random.seed(worker_seed)
    random.seed(worker_seed)


def create_ov_avel_data_loaders(config: Dict[str, Any]) -> tuple[DataLoader, DataLoader, DataLoader | None]:
    data_cfg = config["data"]
    dataset_kwargs = {
        "image_size": int(data_cfg.get("image_size", 224)),
        "max_segments": int(data_cfg.get("max_segments", 16)),
        "allow_missing_modalities": bool(data_cfg.get("allow_missing_modalities", True)),
        "strict_alignment": bool(data_cfg.get("strict_alignment", True)),
        "strong_teacher_dim": int(data_cfg.get("strong_teacher_dim", 1024)),
        "weak_teacher_dim": int(data_cfg.get("weak_teacher_dim", 768)),
        "strong_teacher_logit_dim": int(data_cfg.get("strong_teacher_logit_dim", 1)),
        "weak_teacher_logit_dim": int(data_cfg.get("weak_teacher_logit_dim", 1)),
        "text_dim": int(data_cfg.get("text_dim", 512)),
        "path_root": str(data_cfg.get("path_root", ".")),
        "required_artifacts": data_cfg.get("required_artifacts", []),
        "teacher_path_overrides": data_cfg.get("teacher_path_overrides", {}),
        "temporal_overflow_policy": str(data_cfg.get("temporal_overflow_policy", "error")),
        "preprocessing_mode": str(data_cfg.get("preprocessing_mode", "legacy_manifest_spectrograms")),
        "audio_preprocessing": data_cfg.get("audio_preprocessing"),
    }
    batch_size = int(data_cfg.get("batch_size", 4))
    num_workers = int(data_cfg.get("num_workers", 4))
    pin_memory = bool(data_cfg.get("pin_memory", True))
    persistent_workers = bool(data_cfg.get("persistent_workers", False)) and num_workers > 0
    seed = int(config.get("seed", 42))
    train_generator = torch.Generator().manual_seed(seed)
    val_generator = torch.Generator().manual_seed(seed + 1)
    test_generator = torch.Generator().manual_seed(seed + 2)

    train_dataset = QueryConditionedOVAvelDataset(
        manifest_path=data_cfg["train_manifest"],
        augment=bool(data_cfg.get("train_augment", True)),
        **dataset_kwargs,
    )
    val_dataset = QueryConditionedOVAvelDataset(
        manifest_path=data_cfg["val_manifest"],
        augment=False,
        **dataset_kwargs,
    )

    test_manifest = data_cfg.get("test_manifest")
    test_dataset = None
    if test_manifest:
        test_dataset = QueryConditionedOVAvelDataset(
            manifest_path=test_manifest,
            augment=False,
            **dataset_kwargs,
        )

    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        pin_memory=pin_memory,
        persistent_workers=persistent_workers,
        collate_fn=ov_avel_collate_fn,
        worker_init_fn=seed_worker,
        generator=train_generator,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=pin_memory,
        persistent_workers=persistent_workers,
        collate_fn=ov_avel_collate_fn,
        worker_init_fn=seed_worker,
        generator=val_generator,
    )

    test_loader = None
    if test_dataset is not None:
        test_loader = DataLoader(
            test_dataset,
            batch_size=batch_size,
            shuffle=False,
            num_workers=num_workers,
            pin_memory=pin_memory,
            persistent_workers=persistent_workers,
            collate_fn=ov_avel_collate_fn,
            worker_init_fn=seed_worker,
            generator=test_generator,
        )

    return train_loader, val_loader, test_loader
