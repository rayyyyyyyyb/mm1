#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class DownloadSpec:
    key: str
    description: str
    mode: str
    target_relpath: str
    url: str | None = None
    repo_id: str | None = None
    repo_type: str = "dataset"
    extract_archive: bool = False
    note: str | None = None


DOWNLOAD_SPECS: Dict[str, DownloadSpec] = {
    "ave": DownloadSpec(
        key="ave",
        description="AVE benchmark archive from the official AVE-ECCV18 release.",
        mode="gdown_file",
        target_relpath="downloads/ave/AVE_Dataset.zip",
        url="https://drive.google.com/open?id=1FjKwe79e0u96vdjIVwfRQ1V6SoDHe7kK",
        extract_archive=True,
        note="Extracted files are placed under data/raw/ave/.",
    ),
    "unav100_meta": DownloadSpec(
        key="unav100_meta",
        description="UnAV-100 metadata from the official Hugging Face dataset.",
        mode="hf_snapshot",
        target_relpath="raw/unav100_meta",
        repo_id="ttgeng233/UnAV-100",
        repo_type="dataset",
        note="The HF release is mainly metadata and annotations. If the upstream project also provides raw media elsewhere, place the raw files under data/raw/unav100_media/.",
    ),
    "ov_avebench_raw": DownloadSpec(
        key="ov_avebench_raw",
        description="Official OV-AVEBench raw-video SharePoint folder.",
        mode="manual_link",
        target_relpath="manual_sources/ov_avebench_raw.txt",
        url="https://1drv.ms/f/c/10f45f3af4615f22/Et4f0M9PZdVLm9VAXx2FbbkBn9_T5yr4if_xQINp0zTiSQ?e=y9cGgf",
        note="SharePoint public folder links are not reliably scriptable from CLI. This script writes the official URL and the expected local target directory for your teammate.",
    ),
    "ov_avebench_preprocessed": DownloadSpec(
        key="ov_avebench_preprocessed",
        description="Official OV-AVEBench preprocessed-data SharePoint folder.",
        mode="manual_link",
        target_relpath="manual_sources/ov_avebench_preprocessed.txt",
        url="https://1drv.ms/f/c/10f45f3af4615f22/EsnKs9uu0cxHmPO4_BhVQwQBy3p4xCaB6bR4y8CAemuhJw?e=vBDrfb",
        note="Download the upstream release into data/raw/ov_avebench_preprocessed/ and then build source manifests from those files.",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download or scaffold official benchmark resources for OV-OrthKD.")
    parser.add_argument("--root", type=str, default="data", help="Data root. Default: data")
    parser.add_argument(
        "--datasets",
        type=str,
        nargs="*",
        default=None,
        help="Dataset keys to process. Choices: ave unav100_meta ov_avebench_raw ov_avebench_preprocessed. Default: --all",
    )
    parser.add_argument("--all", action="store_true", help="Process all supported dataset keys.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip targets that already exist.")
    parser.add_argument("--extract-archives", action="store_true", help="Extract downloaded archives when supported.")
    return parser.parse_args()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def download_with_gdown(spec: DownloadSpec, output_path: Path, skip_existing: bool) -> Dict[str, Any]:
    if skip_existing and output_path.exists():
        return {
            "status": "skipped_existing",
            "path": str(output_path.resolve()),
        }

    try:
        import gdown
    except ImportError as exc:
        raise ImportError("`gdown` is required. Run setup_server.sh with --with-download-tools.") from exc

    ensure_parent(output_path)
    downloaded_path = gdown.download(url=spec.url, output=str(output_path), fuzzy=True, resume=True)
    if not downloaded_path:
        raise RuntimeError(f"gdown failed for {spec.key}")

    return {
        "status": "downloaded",
        "path": str(Path(downloaded_path).resolve()),
        "size_bytes": int(Path(downloaded_path).stat().st_size),
    }


def extract_zip(archive_path: Path, output_dir: Path, skip_existing: bool) -> Dict[str, Any]:
    marker_path = output_dir / ".extracted.ok"
    if skip_existing and marker_path.exists():
        return {
            "status": "skipped_existing",
            "path": str(output_dir.resolve()),
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "r") as handle:
        handle.extractall(output_dir)
    marker_path.write_text("ok\n", encoding="utf-8")
    return {
        "status": "extracted",
        "path": str(output_dir.resolve()),
    }


def download_hf_snapshot(spec: DownloadSpec, output_dir: Path, skip_existing: bool) -> Dict[str, Any]:
    marker_path = output_dir / ".snapshot_download.ok"
    if skip_existing and marker_path.exists():
        return {
            "status": "skipped_existing",
            "path": str(output_dir.resolve()),
        }

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise ImportError("`huggingface_hub` is required. Run setup_server.sh with --with-download-tools.") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=str(spec.repo_id),
        repo_type=spec.repo_type,
        local_dir=str(output_dir),
        local_dir_use_symlinks=False,
        resume_download=True,
    )
    marker_path.write_text("ok\n", encoding="utf-8")
    return {
        "status": "downloaded",
        "path": str(output_dir.resolve()),
    }


def write_manual_note(spec: DownloadSpec, output_path: Path, root_dir: Path) -> Dict[str, Any]:
    ensure_parent(output_path)
    target_dir = root_dir / f"raw/{spec.key}"
    payload = {
        "dataset": spec.key,
        "description": spec.description,
        "official_url": spec.url,
        "expected_local_target_dir": str(target_dir.resolve()),
        "note": spec.note,
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "status": "manual_required",
        "path": str(output_path.resolve()),
        "expected_local_target_dir": str(target_dir.resolve()),
    }


def run_spec(spec: DownloadSpec, root_dir: Path, skip_existing: bool, extract_archives: bool) -> Dict[str, Any]:
    if spec.mode == "gdown_file":
        archive_path = root_dir / spec.target_relpath
        result = download_with_gdown(spec, archive_path, skip_existing=skip_existing)
        if spec.extract_archive and extract_archives:
            extract_result = extract_zip(
                archive_path=archive_path,
                output_dir=root_dir / "raw" / spec.key,
                skip_existing=skip_existing,
            )
            result["extract"] = extract_result
        if spec.note:
            result["note"] = spec.note
        return result

    if spec.mode == "hf_snapshot":
        output_dir = root_dir / spec.target_relpath
        result = download_hf_snapshot(spec, output_dir, skip_existing=skip_existing)
        if spec.note:
            result["note"] = spec.note
        return result

    if spec.mode == "manual_link":
        note_path = root_dir / "downloads" / spec.target_relpath
        return write_manual_note(spec, note_path, root_dir=root_dir)

    raise ValueError(f"Unsupported download mode: {spec.mode}")


def resolve_dataset_keys(args: argparse.Namespace) -> List[str]:
    if args.all or not args.datasets:
        return list(DOWNLOAD_SPECS.keys())
    unknown = [item for item in args.datasets if item not in DOWNLOAD_SPECS]
    if unknown:
        raise ValueError(f"Unknown dataset keys: {', '.join(sorted(unknown))}")
    return list(args.datasets)


def main() -> None:
    args = parse_args()
    root_dir = Path(args.root)
    keys = resolve_dataset_keys(args)

    summary: Dict[str, Any] = {
        "root": str(root_dir.resolve()),
        "datasets": {},
    }
    for key in keys:
        spec = DOWNLOAD_SPECS[key]
        summary["datasets"][key] = run_spec(
            spec=spec,
            root_dir=root_dir,
            skip_existing=bool(args.skip_existing),
            extract_archives=bool(args.extract_archives),
        )

    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
