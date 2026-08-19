#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
import torch
from sklearn.metrics import f1_score, precision_recall_curve, precision_score, recall_score

try:
    import matplotlib.pyplot as plt
except ImportError:
    plt = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data import create_ov_avel_data_loaders
from src.models import OVOrthKDStudent
from scripts.train_ov_orthkd import (
    build_model_and_loss,
    collect_predictions,
    compute_grouped_metrics,
    save_predictions_npz,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare multiple OV-OrthKD checkpoints with PR curves and best-threshold F1."
    )
    parser.add_argument(
        "--model",
        action="append",
        required=True,
        help="Model spec in the form name=checkpoint_path. Repeat for multiple models.",
    )
    parser.add_argument("--output-dir", type=str, required=True)
    parser.add_argument("--max-batches", type=int, default=None)
    return parser.parse_args()


def parse_model_specs(specs: Iterable[str]) -> List[Tuple[str, Path]]:
    parsed: List[Tuple[str, Path]] = []
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"Invalid --model spec '{spec}'. Expected name=checkpoint_path.")
        name, raw_path = spec.split("=", 1)
        name = name.strip()
        checkpoint_path = Path(raw_path.strip())
        if not name:
            raise ValueError(f"Model name is empty in spec '{spec}'.")
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")
        parsed.append((name, checkpoint_path))
    return parsed


def build_student(config: Dict[str, Any], device: torch.device) -> OVOrthKDStudent:
    student, _ = build_model_and_loss(config, device)
    return student


def flatten_valid_segments(
    logits: torch.Tensor,
    labels: torch.Tensor,
    mask: torch.Tensor,
) -> Tuple[np.ndarray, np.ndarray]:
    valid = mask.bool().view(-1)
    logits_np = logits.view(-1)[valid].detach().cpu().numpy()
    labels_np = labels.view(-1)[valid].detach().cpu().numpy()
    return logits_np, labels_np


@torch.no_grad()
def collect_probs_and_labels(
    student: OVOrthKDStudent,
    loader: torch.utils.data.DataLoader,
    device: torch.device,
    max_batches: int | None = None,
) -> Tuple[np.ndarray, np.ndarray]:
    student.eval()
    all_probs: List[np.ndarray] = []
    all_labels: List[np.ndarray] = []

    for batch_idx, batch in enumerate(loader):
        if max_batches is not None and batch_idx >= max_batches:
            break
        outputs = student(
            frame=batch["frame"].to(device),
            spectrogram=batch["spectrogram"].to(device),
            text_embedding=batch["text_embedding"].to(device),
            sequence_mask=batch["sequence_mask"].to(device),
            frame_valid=batch["frame_valid"].to(device),
            audio_valid=batch["audio_valid"].to(device),
        )
        logits_np, labels_np = flatten_valid_segments(
            outputs["segment_logits"].detach().cpu(),
            batch["segment_label"].detach().cpu(),
            batch["sequence_mask"].detach().cpu(),
        )
        probs_np = 1.0 / (1.0 + np.exp(-logits_np))
        all_probs.append(probs_np)
        all_labels.append(labels_np)

    return np.concatenate(all_probs, axis=0), np.concatenate(all_labels, axis=0)


def best_threshold_from_pr(labels: np.ndarray, probs: np.ndarray) -> Dict[str, float]:
    precision, recall, thresholds = precision_recall_curve(labels, probs)
    if thresholds.size == 0:
        threshold = 0.5
        preds = (probs >= threshold).astype(np.int64)
        return {
            "best_threshold": threshold,
            "best_f1": float(f1_score(labels, preds, zero_division=0)),
            "precision": float(precision_score(labels, preds, zero_division=0)),
            "recall": float(recall_score(labels, preds, zero_division=0)),
        }

    f1_scores = 2.0 * precision[:-1] * recall[:-1] / np.clip(precision[:-1] + recall[:-1], 1e-12, None)
    best_idx = int(np.argmax(f1_scores))
    best_threshold = float(thresholds[best_idx])
    preds = (probs >= best_threshold).astype(np.int64)
    return {
        "best_threshold": best_threshold,
        "best_f1": float(f1_scores[best_idx]),
        "precision": float(precision_score(labels, preds, zero_division=0)),
        "recall": float(recall_score(labels, preds, zero_division=0)),
    }


def metrics_at_threshold(labels: np.ndarray, probs: np.ndarray, threshold: float) -> Dict[str, float]:
    preds = (probs >= threshold).astype(np.int64)
    return {
        "threshold": float(threshold),
        "f1": float(f1_score(labels, preds, zero_division=0)),
        "precision": float(precision_score(labels, preds, zero_division=0)),
        "recall": float(recall_score(labels, preds, zero_division=0)),
    }


def evaluate_prediction_sets(
    validation_predictions: Dict[str, np.ndarray],
    test_predictions: Dict[str, np.ndarray],
) -> Dict[str, Any]:
    val_labels = validation_predictions["labels"]
    val_probs = validation_predictions["probabilities"]
    best = best_threshold_from_pr(val_labels, val_probs)
    precision, recall, thresholds = precision_recall_curve(val_labels, val_probs)
    frozen_threshold = float(best["best_threshold"])
    return {
        "validation_calibration": {
            "best_threshold": frozen_threshold,
            "best_f1": float(best["best_f1"]),
            "precision_at_best_f1": float(best["precision"]),
            "recall_at_best_f1": float(best["recall"]),
            "precision": precision,
            "recall": recall,
            "thresholds": thresholds,
        },
        "validation": {
            "threshold": frozen_threshold,
            "metrics": compute_grouped_metrics(validation_predictions, frozen_threshold),
        },
        "test": {
            "threshold": frozen_threshold,
            "metrics": compute_grouped_metrics(test_predictions, frozen_threshold),
        },
    }


def plot_pr_curves(
    curves: Dict[str, Tuple[np.ndarray, np.ndarray]],
    output_path: Path,
    title: str,
) -> None:
    if plt is None:
        return
    plt.figure(figsize=(7, 6))
    for name, (precision, recall) in curves.items():
        plt.plot(recall, precision, linewidth=2, label=name)
    plt.xlabel("Recall")
    plt.ylabel("Precision")
    plt.title(title)
    plt.xlim(0.0, 1.0)
    plt.ylim(0.0, 1.05)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def main() -> None:
    args = parse_args()
    model_specs = parse_model_specs(args.model)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    summary: List[Dict[str, Any]] = []
    val_curves: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    test_curves: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}

    for name, checkpoint_path in model_specs:
        checkpoint = torch.load(checkpoint_path, map_location="cpu")
        if "config" not in checkpoint:
            raise KeyError(f"Checkpoint missing embedded config: {checkpoint_path}")
        config = checkpoint["config"]
        student = build_student(config, device)
        student.load_state_dict(checkpoint["student_state_dict"])

        _, val_loader, test_loader = create_ov_avel_data_loaders(config)
        if test_loader is None:
            raise ValueError(f"Checkpoint config has no test manifest: {checkpoint_path}")
        validation_predictions = collect_predictions(
            student,
            val_loader,
            device,
            max_batches=args.max_batches,
        )
        test_predictions = collect_predictions(
            student,
            test_loader,
            device,
            max_batches=args.max_batches,
        )
        evaluation_report = evaluate_prediction_sets(
            validation_predictions,
            test_predictions,
        )
        calibration = evaluation_report["validation_calibration"]
        validation_total = evaluation_report["validation"]["metrics"]["total"]
        test_total = evaluation_report["test"]["metrics"]["total"]
        save_predictions_npz(output_dir / f"{name}_validation_predictions.npz", validation_predictions)
        save_predictions_npz(output_dir / f"{name}_test_predictions.npz", test_predictions)

        test_precision, test_recall, _ = precision_recall_curve(
            test_predictions["labels"],
            test_predictions["probabilities"],
        )
        val_curves[name] = (calibration["precision"], calibration["recall"])
        test_curves[name] = (test_precision, test_recall)

        summary.append(
            {
                "name": name,
                "checkpoint": str(checkpoint_path),
                "val_best_threshold": calibration["best_threshold"],
                "val_best_f1": calibration["best_f1"],
                "val_precision_at_best_f1": calibration["precision_at_best_f1"],
                "val_recall_at_best_f1": calibration["recall_at_best_f1"],
                "test_f1_at_val_best_threshold": test_total["f1"],
                "test_precision_at_val_best_threshold": test_total["precision"],
                "test_recall_at_val_best_threshold": test_total["recall"],
                "validation_grouped_metrics": evaluation_report["validation"]["metrics"],
                "test_grouped_metrics": evaluation_report["test"]["metrics"],
            }
        )

    plot_pr_curves(val_curves, output_dir / "val_pr_curves.png", "Validation PR Curves")
    plot_pr_curves(test_curves, output_dir / "test_pr_curves.png", "Test PR Curves")

    with (output_dir / "pr_f1_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    header = (
        "name,checkpoint,val_best_threshold,val_best_f1,val_precision_at_best_f1,"
        "val_recall_at_best_f1,test_f1_at_val_best_threshold,"
        "test_precision_at_val_best_threshold,test_recall_at_val_best_threshold"
    )
    lines = [header]
    for row in summary:
        lines.append(
            ",".join(
                [
                    row["name"],
                    row["checkpoint"],
                    f"{row['val_best_threshold']:.8f}",
                    f"{row['val_best_f1']:.8f}",
                    f"{row['val_precision_at_best_f1']:.8f}",
                    f"{row['val_recall_at_best_f1']:.8f}",
                    f"{row['test_f1_at_val_best_threshold']:.8f}",
                    f"{row['test_precision_at_val_best_threshold']:.8f}",
                    f"{row['test_recall_at_val_best_threshold']:.8f}",
                ]
            )
        )
    (output_dir / "pr_f1_summary.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    payload: Dict[str, Any] = {
        "summary": summary,
        "plots_saved": plt is not None,
    }
    if plt is None:
        payload["plot_warning"] = "matplotlib is not installed; PR curve images were skipped."
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
