# OV-AVEBench Raw Video Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the 13 zero-byte official OV-AVEBench raw-video members into an auditable, non-bypassable recovery decision without modifying the downloaded official archive or treating a reconstructed YouTube clip as an official replacement.

**Architecture:** Add a small evidence pipeline that joins the official OV-AVEL metadata, the official VGGSound source metadata, and the immutable archive audit into one recovery manifest. The pipeline may probe original public sources, but it keeps candidates quarantined and reports `BLOCKED_BEFORE_CONFERENCE_REPRO` until author-issued replacement bytes or a corrected official archive pass exact provenance, media, and dataset-layout validation.

**Tech Stack:** Python 3.10+, standard library (`argparse`, `csv`, `hashlib`, `json`, `pathlib`, `subprocess`), pytest, ffprobe, existing OV-OrthKD data-layout/readiness validators.

**Spec:** `C:\Users\lwz20\.codex\attachments\4ebbbc0f-5299-493e-8a93-2af71f051e6a\pasted-text.txt`

**Execution status (2026-08-24):** Tasks 1–5 are implemented and focused tests pass. Task 6 is in progress while the 5090 completes immutable extraction/tree hashing and the final verification matrix. Full raw-video audit added a second fail-closed finding beyond the 13 zero-byte members: 1,019 non-empty streams are shorter than the locked ten-second policy, so replacement verification alone cannot promote global conference readiness.

## Global Constraints

- Preserve `OV-AVEBench_raw_videos.tar.gz` byte-for-byte; never edit or repack it.
- Do not substitute the ten preprocessed JPG frames, repeated frames, generated frames, a mirror, or a freshly cut YouTube clip for an official raw video.
- Use only pinned official OV-AVEL and VGGSound metadata as source-identity evidence.
- Keep downloaded candidate media outside Git and mark it `quarantine` until provenance is author-issued and all checks pass.
- Do not run formal training, a full epoch, validation/test evaluation, or the one allowed real optimizer-step preflight while any raw-video member remains unresolved.
- Every generated receipt must include input file sizes and SHA256 values, source repository URLs and commits, exact failing IDs, and a machine-readable final status.

---

## Task 1: Lock the official VGGSound source metadata

**Files:**

- Create: `configs/locks/mm26_vggsound_source_lock.yaml`
- Create: `reports/data/vggsound_source_metadata_receipt.json`
- Modify: `reports/downloads/asset_receipts.json`

- [ ] Download `https://raw.githubusercontent.com/hche11/VGGSound/master/data/vggsound.csv` on the 5090 into `E:\OV-OrthKD-R3\repo\data\downloads\incoming\vggsound_metadata\vggsound.csv` using resumable transfer.
- [ ] Resolve and record the exact `hche11/VGGSound` commit containing `data/vggsound.csv`; record byte size, SHA256, media type, and retrieval time.
- [ ] Verify the CSV has exactly four columns per record: YouTube ID, start seconds, label, and split; reject malformed IDs, non-integer start seconds, duplicate `(ID,start)` pairs, and an empty dataset.
- [ ] Verify all 13 zero-byte OV-AVEBench IDs have at least one official VGGSound row. Record every distinct start-second candidate, label, and VGGSound split; mark any ID with more than one distinct candidate as `source_timestamp_ambiguous` instead of guessing.
- [ ] Do not download source videos in this task.

## Task 2: Add a deterministic recovery-manifest builder using TDD

**Files:**

- Create: `tests/test_r3_ovave_raw_recovery.py`
- Create: `scripts/build_ovave_raw_recovery_manifest.py`
- Create: `reports/data/ovave_raw_video_recovery_manifest.json`

- [ ] Write a failing test `test_build_manifest_joins_exact_official_rows` using three tiny fixture inputs: OV-AVEL CSV, VGGSound CSV, and zero-member audit JSON.
- [ ] Write a failing test `test_build_manifest_rejects_missing_or_exact_duplicate_vggsound_rows` covering one missing row and one duplicate `(YouTube ID, start seconds)` row; a repeated ID with distinct starts must be preserved and marked ambiguous.
- [ ] Write a failing test `test_build_manifest_never_marks_reconstructed_candidates_official` proving that `candidate_kind: reconstructed_source_clip` cannot resolve a zero-byte official member.
- [ ] Write a failing test `test_build_manifest_requires_author_issued_bytes_to_resolve` proving that resolution requires a replacement receipt with an official author locator, non-zero bytes, SHA256, and media-audit success.
- [ ] Run `pytest -q tests/test_r3_ovave_raw_recovery.py` and confirm the tests fail because the script does not exist.
- [ ] Implement `build_ovave_raw_recovery_manifest.py` with a reusable `build_manifest(...)` function and CLI arguments for the three evidence files plus an optional replacement-receipt JSON.
- [ ] Emit one record per zero member with OV-AVEL split/category/type, all VGGSound label/start/split candidates, archive member path, source URL, and a `resolution_status` chosen from `author_replacement_verified`, `source_identified_only`, `source_timestamp_ambiguous`, or `unresolved`.
- [ ] Set the aggregate status to `passed` only when every record is `author_replacement_verified`; otherwise set `blocked` and `final_status: BLOCKED_BEFORE_CONFERENCE_REPRO`.
- [ ] Run `pytest -q tests/test_r3_ovave_raw_recovery.py` and confirm all focused tests pass.
- [ ] Run the builder against the real pinned metadata and archive audit on the 5090; copy the non-sensitive receipt back into `reports/data/`.

## Task 3: Add strict official-replacement verification using TDD

**Files:**

- Modify: `tests/test_r3_ovave_raw_recovery.py`
- Create: `scripts/verify_ovave_raw_replacements.py`
- Create: `reports/data/ovave_raw_replacement_audit.json`

- [ ] Write a failing test `test_replacement_verifier_rejects_unapproved_source_kind` for mirrors and reconstructed clips.
- [ ] Write a failing test `test_replacement_verifier_rejects_zero_byte_and_wrong_id`.
- [ ] Write a failing test `test_replacement_verifier_requires_ffprobe_and_ten_second_duration` using a stubbed probe result.
- [ ] Implement a verifier that accepts only `author_sharepoint_file` or `author_corrected_archive` locators, recomputes each replacement SHA256, checks that the expected ID is the filename stem, and calls ffprobe for decodable video/audio streams and a duration compatible with the official 10-second protocol.
- [ ] Keep verified replacements in a separate overlay root; do not overwrite the original extraction or archive.
- [ ] Emit per-file checks and a deterministic aggregate hash over sorted `(split, sample_id, sha256)` tuples.
- [ ] Run focused tests and `python -m compileall -q scripts tests`.

## Task 4: Produce the author handoff package and current blocker report

**Files:**

- Create: `reports/data/OVAVEBENCH_RAW_VIDEO_AUTHOR_REQUEST.md`
- Modify: `reports/R3_ASSET_DOWNLOAD_AND_READINESS_REPORT.md`
- Modify: `reports/mm26_conference_readiness.json`

- [ ] List all 13 exact archive member paths grouped by split and category, the immutable raw archive SHA256, and the official VGGSound ID/start metadata.
- [ ] Ask the OV-AVEL authors for either a corrected official raw archive or the 13 original MP4 files, plus an official checksum or author-hosted locator.
- [ ] State that the full official raw archive is readable but contains 13 zero-byte formal samples, while the official preprocessed archive has non-empty audio and frames for all 13.
- [ ] Keep the conference status `BLOCKED_BEFORE_CONFERENCE_REPRO`; name the single blocking condition and the exact verification command that should run after author files arrive.
- [ ] Do not send a message or open an issue without the user's explicit authorization; provide a ready-to-send draft only.

## Task 5: Correct the discovered JPG/PNG layout mismatch

**Files:**

- Modify: `tests/test_r3_preprocessed_layout.py`
- Modify: `scripts/build_ov_avebench_source_manifests.py`
- Modify: `scripts/discover_ovave_preprocessed_layout.py`

- [ ] Write a failing regression test proving that the official archive's ten `.jpg` frames per sample are accepted while mixed extensions, missing indices, duplicates, or extra frames are rejected.
- [ ] Replace the hard-coded `.png` expectation with an explicitly locked official extension discovered from the archive receipt; require exactly `00000001.jpg` through `00000010.jpg` for every sample.
- [ ] Update discovery output to record extension counts and the canonical extension, and bind that value into the preprocessing/data lock fingerprint.
- [ ] Run the focused layout and source-manifest tests.

## Task 6: Verification, audit log, commit, and push

**Files:**

- Modify: `C:\Users\lwz20\Desktop\OV-OrthKD-Collaboration-Base1\扩刊\all.md`

- [ ] Run `python -m compileall -q src scripts tests`.
- [ ] Run `pytest -q`.
- [ ] Run `python scripts/assets/download_mm26_assets.py --verify` on the 5090.
- [ ] Run the recovery-manifest builder and replacement verifier on the 5090; record every exit code.
- [ ] Run `git diff --check`, `git status --short`, and `git diff --stat`.
- [ ] Append every command, result, source locator, SHA256, and status decision chronologically to `扩刊/all.md`.
- [ ] Commit only code, tests, locks, and small receipts; confirm no data, weights, caches, checkpoints, cookies, tokens, or quarantine candidates are tracked.
- [ ] Push `repro/r3-assets-download-and-readiness` and verify the remote SHA.
- [ ] Report `BLOCKED_BEFORE_CONFERENCE_REPRO` unless all 13 author-issued replacements pass the strict verifier and the complete 24,800-video layout audit.
