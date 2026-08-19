#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import platform
import sys

import torch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the CUDA runtime used by OV-OrthKD")
    parser.add_argument("--matrix-size", type=int, default=2048)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--iterations", type=int, default=5)
    return parser.parse_args()


def verify_cuda_runtime(matrix_size: int = 2048, warmup: int = 2, iterations: int = 5) -> dict[str, object]:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; RTX 5090 verification cannot run")
    if matrix_size <= 0 or warmup < 0 or iterations <= 0:
        raise ValueError("matrix_size/iterations must be positive and warmup must be non-negative")

    device = torch.device("cuda:0")
    torch.cuda.empty_cache()
    left = torch.randn((matrix_size, matrix_size), device=device, dtype=torch.float16)
    right = torch.randn((matrix_size, matrix_size), device=device, dtype=torch.float16)

    torch.cuda.synchronize(device)
    for _ in range(warmup):
        output = left @ right
    torch.cuda.synchronize(device)

    starter = torch.cuda.Event(enable_timing=True)
    ender = torch.cuda.Event(enable_timing=True)
    starter.record()
    for _ in range(iterations):
        output = left @ right
    ender.record()
    torch.cuda.synchronize(device)

    finite = bool(torch.isfinite(output).all().item())
    report: dict[str, object] = {
        "python": sys.version,
        "platform": platform.platform(),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "cuda_available": True,
        "gpu_name": torch.cuda.get_device_name(device),
        "gpu_capability": list(torch.cuda.get_device_capability(device)),
        "gpu_count": torch.cuda.device_count(),
        "cudnn": torch.backends.cudnn.version(),
        "matrix_size": matrix_size,
        "dtype": "float16",
        "warmup": warmup,
        "iterations": iterations,
        "average_matmul_ms": float(starter.elapsed_time(ender) / iterations),
        "finite": finite,
        "mean_absolute_value": float(output.abs().mean().item()),
        "allocated_gb": float(torch.cuda.memory_allocated(device) / (1024**3)),
        "reserved_gb": float(torch.cuda.memory_reserved(device) / (1024**3)),
    }
    if not finite:
        raise RuntimeError(f"CUDA FP16 matmul produced non-finite output: {json.dumps(report)}")
    return report


def main() -> None:
    args = parse_args()
    report = verify_cuda_runtime(
        matrix_size=args.matrix_size,
        warmup=args.warmup,
        iterations=args.iterations,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
