#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.models.ov_orthkd import OVOrthKDStudent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure synchronized OV-OrthKD student latency")
    parser.add_argument("--segments", type=int, default=16)
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--text-dim", type=int, default=1024)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--device", default=None)
    return parser.parse_args()


def count_parameters(model: torch.nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)


def measure_latency(
    model: torch.nn.Module,
    device: torch.device,
    *,
    segments: int,
    image_size: int,
    text_dim: int,
    warmup: int,
    iterations: int,
) -> float:
    if segments <= 0 or image_size <= 0 or warmup < 0 or iterations <= 0:
        raise ValueError("segments/image_size/iterations must be positive and warmup non-negative")
    model.eval().to(device)
    frames = torch.randn(1, segments, 3, image_size, image_size, device=device)
    spectrograms = torch.randn_like(frames)
    text = torch.randn(1, text_dim, device=device)
    mask = torch.ones(1, segments, device=device)

    if device.type == "cuda":
        torch.cuda.synchronize(device)
    for _ in range(warmup):
        with torch.inference_mode():
            model(frames, spectrograms, text, mask)
    if device.type == "cuda":
        torch.cuda.synchronize(device)
        starter = torch.cuda.Event(enable_timing=True)
        ender = torch.cuda.Event(enable_timing=True)
        starter.record()
        for _ in range(iterations):
            with torch.inference_mode():
                model(frames, spectrograms, text, mask)
        ender.record()
        torch.cuda.synchronize(device)
        return float(starter.elapsed_time(ender) / iterations)

    started = time.perf_counter()
    for _ in range(iterations):
        with torch.inference_mode():
            model(frames, spectrograms, text, mask)
    return float((time.perf_counter() - started) * 1000.0 / iterations)


def main() -> None:
    args = parse_args()
    device = torch.device(args.device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = OVOrthKDStudent(
        visual_backbone="convnextv2_tiny.fcmae_ft_in22k_in1k",
        audio_backbone="tf_efficientnetv2_b2.in1k",
        text_dim=args.text_dim,
        fusion_dim=384,
        projection_dim=256,
        path_mode="explicit_projected",
        temporal_layers=4,
        temporal_heads=8,
        max_segments=max(16, args.segments),
    )
    latency_ms = measure_latency(
        model,
        device,
        segments=args.segments,
        image_size=args.image_size,
        text_dim=args.text_dim,
        warmup=args.warmup,
        iterations=args.iterations,
    )
    trainable_parameters = count_parameters(model)
    result = {
        "device": str(device),
        "segments": args.segments,
        "segment_label": f"T={args.segments}",
        "average_latency_ms": latency_ms,
        "throughput_clips_per_second": 1000.0 / latency_ms,
        "trainable_parameters": trainable_parameters,
        "visual_parameters": count_parameters(model.visual_encoder),
        "audio_parameters": count_parameters(model.audio_encoder),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
