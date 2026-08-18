from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import torch


class ClapTextTeacher:
    def __init__(
        self,
        repo_root: str | Path,
        checkpoint_path: str | Path,
        version: str = "2023",
        device: str = "cpu",
        normalize: bool = False,
    ) -> None:
        repo_dir = Path(repo_root).resolve()
        checkpoint = Path(checkpoint_path).resolve()
        if not repo_dir.exists():
            raise FileNotFoundError(f"CLAP repo not found: {repo_dir}")
        if not checkpoint.exists():
            raise FileNotFoundError(f"CLAP checkpoint not found: {checkpoint}")

        if str(repo_dir) not in sys.path:
            sys.path.insert(0, str(repo_dir))

        try:
            from msclap import CLAP
        except ImportError as exc:
            raise ImportError(
                "Failed to import CLAP. Install `transformers`, `torchaudio`, and the repo requirements first."
            ) from exc

        self.device = torch.device(device)
        self.normalize = bool(normalize)
        self.model = CLAP(
            model_fp=str(checkpoint),
            version=version,
            use_cuda=self.device.type == "cuda",
        )
        self.feature_dim = int(getattr(self.model.args, "d_proj", 1024))

    def encode_queries(self, queries: Sequence[str]) -> np.ndarray:
        embeddings = self.model.get_text_embeddings(list(queries))
        if isinstance(embeddings, torch.Tensor):
            array = embeddings.detach().cpu().float().numpy()
        else:
            array = np.asarray(embeddings, dtype=np.float32)
        if self.normalize:
            norms = np.linalg.norm(array, axis=-1, keepdims=True).clip(min=1e-6)
            array = array / norms
        return array.astype(np.float32)
