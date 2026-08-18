from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms


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
        teacher_path_overrides: Dict[str, str] | None = None,
    ) -> None:
        self.records = _load_manifest(manifest_path)
        self.frame_transform = _build_frame_transform(image_size, augment=augment)
        self.spec_transform = _build_spectrogram_transform(image_size)
        self.image_size = image_size
        self.max_segments = max_segments
        self.allow_missing_modalities = allow_missing_modalities
        self.strict_alignment = strict_alignment
        self.strong_teacher_dim = strong_teacher_dim
        self.weak_teacher_dim = weak_teacher_dim
        self.strong_teacher_logit_dim = strong_teacher_logit_dim
        self.weak_teacher_logit_dim = weak_teacher_logit_dim
        self.text_dim = text_dim
        self.teacher_path_overrides = teacher_path_overrides or {}

    def __len__(self) -> int:
        return len(self.records)

    def _empty_image(self) -> Image.Image:
        return Image.new("RGB", (self.image_size, self.image_size))

    def _read_image(self, path_str: str | None) -> tuple[Image.Image, float]:
        if path_str:
            path = Path(path_str)
            if path.exists():
                return Image.open(path).convert("RGB"), 1.0
        if not self.allow_missing_modalities:
            raise FileNotFoundError(f"Missing modality file: {path_str}")
        return self._empty_image(), 0.0

    def _select_indices(self, seq_len: int) -> List[int]:
        if seq_len <= self.max_segments:
            return list(range(seq_len))
        return np.linspace(0, seq_len - 1, num=self.max_segments, dtype=int).tolist()

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

    def _load_ndarray(self, value: Any) -> np.ndarray | None:
        if value is None:
            return None
        if isinstance(value, str):
            path = Path(value)
            if not path.exists():
                if self.allow_missing_modalities:
                    return None
                raise FileNotFoundError(f"Missing feature file: {value}")
            if path.suffix == ".npy":
                return np.load(path)
            if path.suffix == ".npz":
                with np.load(path) as data:
                    if "arr_0" in data:
                        return data["arr_0"]
                    first_key = next(iter(data.keys()))
                    return data[first_key]
            raise ValueError(f"Unsupported feature extension: {value}")
        return np.asarray(value, dtype=np.float32)

    def _select_array_rows(self, array: np.ndarray, target_len: int, expected_dim: int) -> np.ndarray:
        if array.ndim == 1:
            if expected_dim == 1:
                if array.shape[0] == target_len:
                    return array[:, None]
                if array.shape[0] == 1:
                    return np.repeat(array.reshape(1, 1), target_len, axis=0)
                if self.strict_alignment:
                    raise ValueError(
                        f"Expected scalar sequence of length {target_len} or 1, got length {array.shape[0]}."
                    )
                indices = np.linspace(0, array.shape[0] - 1, num=target_len, dtype=int)
                return array[indices][:, None]
            if self.strict_alignment:
                raise ValueError(
                    f"Expected feature dim {expected_dim}, but got 1D array of length {array.shape[0]}."
                )
            return np.repeat(array[None, :], target_len, axis=0)
        if array.shape[0] == target_len:
            return array
        if array.shape[0] == 1:
            return np.repeat(array, target_len, axis=0)
        if self.strict_alignment:
            raise ValueError(
                f"Expected teacher sequence length {target_len} or 1, but received {array.shape[0]}."
            )
        indices = np.linspace(0, array.shape[0] - 1, num=target_len, dtype=int)
        return array[indices]

    def _load_teacher_tensor(
        self,
        record: Dict[str, Any],
        field_name: str,
        target_len: int,
        expected_dim: int,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        value = record.get(field_name) or record.get(f"{field_name}_path")

        # Robust override check: match exact field_name or the base teacher name (strong_teacher/weak_teacher)
        base_name = field_name.replace("_features", "").replace("_logits", "")
        best_override_key = field_name if field_name in self.teacher_path_overrides else (
            base_name if base_name in self.teacher_path_overrides else None
        )

        if isinstance(value, str) and best_override_key:
            override_root = Path(self.teacher_path_overrides[best_override_key])
            original_path = Path(value)
            value = str(override_root / original_path.name)

        array = self._load_ndarray(value)
        if array is None:
            return (
                torch.zeros(target_len, expected_dim, dtype=torch.float32),
                torch.zeros(target_len, dtype=torch.float32),
            )

        selected = self._select_array_rows(np.asarray(array, dtype=np.float32), target_len, expected_dim)
        if selected.shape[-1] != expected_dim:
            raise ValueError(
                f"Unexpected feature dim for {field_name}: {selected.shape[-1]} != {expected_dim}"
            )
        return torch.from_numpy(selected), torch.ones(target_len, dtype=torch.float32)

    def _load_text_embedding(self, record: Dict[str, Any]) -> tuple[torch.Tensor, torch.Tensor]:
        value = record.get("text_embedding") or record.get("text_embedding_path")
        if isinstance(value, str) and "text" in self.teacher_path_overrides:
            override_root = Path(self.teacher_path_overrides["text"])
            original_path = Path(value)
            value = str(override_root / original_path.name)
        array = self._load_ndarray(value)
        if array is None:
            return torch.zeros(self.text_dim, dtype=torch.float32), torch.tensor(0.0, dtype=torch.float32)

        embedding = np.asarray(array, dtype=np.float32).reshape(-1)
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
            raise ValueError("`segment_labels` cannot be empty.")

        seq_len = int(labels_array.shape[0])
        indices = self._select_indices(seq_len)

        frame_value = (
            record.get("segment_frame_paths")
            or record.get("frame_groups")
            or record.get("frame_paths")
            or record.get("frames")
        )
        frame_paths = self._normalize_segment_frame_paths(frame_value, seq_len)
        spec_paths = self._normalize_paths(
            _ensure_list(record.get("spectrogram_paths") or record.get("spectrograms") or record.get("audio_image_paths")),
            seq_len,
        )

        frames, frame_valid = self._load_image_sequence(frame_paths, indices, self.frame_transform)
        spectrograms, audio_valid = self._load_image_sequence(spec_paths, indices, self.spec_transform)

        strong_teacher_logits, strong_teacher_mask = self._load_teacher_tensor(
            record=record,
            field_name="strong_teacher_logits",
            target_len=len(indices),
            expected_dim=self.strong_teacher_logit_dim,
        )
        strong_teacher_features, strong_teacher_feature_mask = self._load_teacher_tensor(
            record=record,
            field_name="strong_teacher_features",
            target_len=len(indices),
            expected_dim=self.strong_teacher_dim,
        )
        weak_teacher_features, weak_teacher_mask = self._load_teacher_tensor(
            record=record,
            field_name="weak_teacher_features",
            target_len=len(indices),
            expected_dim=self.weak_teacher_dim,
        )
        weak_teacher_logits, weak_teacher_logit_mask = self._load_teacher_tensor(
            record=record,
            field_name="weak_teacher_logits",
            target_len=len(indices),
            expected_dim=self.weak_teacher_logit_dim,
        )
        text_embedding, text_valid = self._load_text_embedding(record)

        selected_labels = torch.from_numpy(labels_array[indices])
        sequence_mask = torch.ones(len(indices), dtype=torch.float32)

        return {
            "id": record.get("id", str(index)),
            "query": record.get("query", record.get("text_query", "unknown event")),
            "domain": record.get("domain", "unknown"),
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
            "weak_teacher_mask": weak_teacher_mask,
            "weak_teacher_logits": weak_teacher_logits,
            "weak_teacher_logit_mask": weak_teacher_logit_mask,
            "text_embedding": text_embedding,
            "text_valid": text_valid,
            "meta": record.get("meta", {}),
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
        "weak_teacher_mask",
        "weak_teacher_logits",
        "weak_teacher_logit_mask",
    ]
    for key in tensor_keys:
        collated[key] = torch.stack([_pad_sequence_tensor(item[key], max_len) for item in batch], dim=0)

    collated["text_embedding"] = torch.stack([item["text_embedding"] for item in batch], dim=0)
    collated["text_valid"] = torch.stack([item["text_valid"] for item in batch], dim=0)
    return collated


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
        "teacher_path_overrides": data_cfg.get("teacher_path_overrides", {}),
    }
    batch_size = int(data_cfg.get("batch_size", 4))
    num_workers = int(data_cfg.get("num_workers", 4))
    pin_memory = bool(data_cfg.get("pin_memory", True))
    persistent_workers = num_workers > 0

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
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=pin_memory,
        persistent_workers=persistent_workers,
        collate_fn=ov_avel_collate_fn,
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
        )

    return train_loader, val_loader, test_loader
