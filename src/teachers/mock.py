from __future__ import annotations

import hashlib
from typing import Sequence

import numpy as np

from .common import AudioSegmentSpec


def _seed_from_parts(*parts: str) -> int:
    digest = hashlib.sha256("||".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="little", signed=False)


def _vector_from_key(key: str, dim: int) -> np.ndarray:
    rng = np.random.default_rng(_seed_from_parts(key, str(dim)))
    return rng.standard_normal(dim).astype(np.float32)


class MockTextTeacher:
    def __init__(self, feature_dim: int) -> None:
        self.feature_dim = int(feature_dim)

    def encode_queries(self, queries: Sequence[str]) -> np.ndarray:
        return np.stack([_vector_from_key(f"text::{query}", self.feature_dim) for query in queries], axis=0)


class MockStrongVisualTeacher:
    def __init__(self, feature_dim: int, logit_scale: float = 4.0) -> None:
        self.feature_dim = int(feature_dim)
        self.logit_scale = float(logit_scale)

    def export_segments(self, frame_groups: Sequence[Sequence[str]], query: str) -> tuple[np.ndarray, np.ndarray]:
        query_vector = _vector_from_key(f"query::{query}", self.feature_dim)
        query_vector = query_vector / np.linalg.norm(query_vector).clip(min=1e-6)

        features = []
        logits = []
        for idx, frame_group in enumerate(frame_groups):
            feature = _vector_from_key(f"vision::{query}::{idx}::{'|'.join(frame_group)}", self.feature_dim)
            features.append(feature)
            feature_norm = feature / np.linalg.norm(feature).clip(min=1e-6)
            logits.append(float(np.dot(feature_norm, query_vector) * self.logit_scale))
        return np.stack(features, axis=0), np.asarray(logits, dtype=np.float32)


class MockWeakAudioTeacher:
    def __init__(self, feature_dim: int) -> None:
        self.feature_dim = int(feature_dim)

    def export_segments(self, audio_segments: Sequence[AudioSegmentSpec]) -> np.ndarray:
        features = []
        for idx, segment in enumerate(audio_segments):
            key = (
                f"audio::{idx}::{segment.path}::{segment.start_time}::{segment.end_time}::{segment.sample_rate}"
            )
            features.append(_vector_from_key(key, self.feature_dim))
        return np.stack(features, axis=0)
