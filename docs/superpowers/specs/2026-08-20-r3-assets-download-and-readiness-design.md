# R3 Assets Download and Conference Readiness Design

## Authority and goal

This design implements the user-provided 1,357-line final task book whose UTF-8 SHA256 is `49113849a33a728c3cefdad69b0067ef9ba54946e097c9384cf1a9614a101d9d`. The only successful terminal state is `READY_FOR_CONFERENCE_REPRO`; otherwise the phase must end as `BLOCKED_BEFORE_CONFERENCE_REPRO` with only observed blockers.

R3 starts from commit `f6e85eb61cdc09e530038d46671f70ee2618ea5c` on branch `repro/r3-assets-download-and-readiness`. It may download and validate public assets, resolve official data through legal authentication, fix the conference reproduction path, export real teacher caches, and run one real optimizer step. It may not start a full epoch, produce formal paper metrics, or implement any journal-extension mechanism.

## Platform adaptation

The RTX 5090 host is Windows 10 with 5.72 TiB free on `E:` and no installed WSL distribution. `tmux` therefore cannot supervise native Windows downloads. R3 uses hidden detached PowerShell processes (`Start-Process -WindowStyle Hidden`) as the platform-equivalent session supervisor while retaining the required aria2 guarantees: `.aria2` control files, a saved session file, unlimited transient retry, deterministic destination names, resumability after SSH disconnect, and independent log files. No download is tied to a foreground Codex tool call.

All runtime data lives below `E:\OV-OrthKD-R3\repo` in Git-ignored `data/`, `weights/`, and `external/` trees. Portable tools may live under `E:\OV-OrthKD-R3\tools`. The pre-existing dirty `E:\OV-OrthKD-R2\repo` is preserved and never cleaned or reused as the R3 source of truth.

## Components

### Asset catalog and verifier

`scripts/assets/mm26_asset_catalog.py` defines the five exact weight records, two SharePoint records, five official Git repositories, allowed sources, expected SHA256 values, and target paths. `scripts/assets/asset_validation.py` performs streaming SHA256, size, HTML/XML/LFS-pointer rejection, and checkpoint-specific validation. No unverified file is promoted from `data/downloads/incoming` to its final path; a conflicting file is moved to quarantine with its bytes preserved.

### Resumable download supervisor

`scripts/assets/download_mm26_assets.py` exposes `--all`, `--weights-only`, `--data-only`, `--resume`, `--status`, and `--verify`. It creates aria2 input/session files, chooses a valid source through a small Range probe, starts one hidden aria2 process per independent asset group, and records non-secret state in `data/downloads/state`. It reuses a completed file only after full validation.

`scripts/assets/monitor_downloads.py` reads asset definitions, aria2 control files, logs, receipts, process identifiers, and disk space. `--once` atomically refreshes JSON and Markdown status. `--watch` repeats at 60-second intervals and requests graceful aria2 pause when free disk drops below 50 GiB. It never deletes partial files.

### SharePoint authorization boundary

`scripts/assets/resolve_sharepoint_download.py` first tests anonymous redirects and binary response metadata. If JavaScript is needed, Playwright captures only the final download request and passes short-lived headers/cookies to aria2 through a user-only temporary file. If Microsoft login is required, it returns `AUTH_REQUIRED`, writes a secret-free instruction report, and waits for the user to complete one visible legal login. It never reads stored passwords, guesses credentials, or includes tokens in Git/log/report artifacts.

### Data and reconstruction locks

The existing safe extractor, layout discovery, source-manifest builder, evaluator, and canonical readiness gate remain the only path from official bytes to readiness. R3 changes the claim level to `paper_specified_reconstruction` and locks the task-book values for the 10-segment protocol, student backbones/augmentation, raw-video InternVideo2 sampling, ImageBind-derived audio fbank, teacher identities, 30-epoch mechanics, camera-ready loss weights, and evaluator mappings. The ready config is created only after every lock and real artifact validates.

### Teachers and export

Teacher wrappers bind exact repository commits, imported classes, checkpoint roles, preprocessing, and checkpoint SHA256. The repeat-2 smoke uses one real training record and checks shape, dtype, finite values, repeatability, latency, and CUDA memory. The export pipeline writes split-isolated per-record artifacts and receipts atomically; receipt presence, shape, content hash, and lock fingerprint define resumability. `scripts/teachers/monitor_export.py` reports progress without reading or modifying tensors.

### One-step preflight and final gate

The real preflight remains structurally gated by canonical readiness. Only after official data, all five checkpoints, real smoke, 24,800 exported records, cache root hash, and evaluator parity pass may it run exactly one batch and one optimizer step. It saves and restores model, optimizer, scheduler, scaler, early state, RNG, and DataLoader generator without validation/test evaluation or threshold selection.

## Failure, security, and evidence rules

- HTTP 429/503 reduces per-server concurrency from 8 to 2; transient network failures retry indefinitely without a forced wall-clock timeout.
- Unexpected HTML, XML, Git LFS pointer, zero bytes, wrong SHA256, wrong checkpoint keys, or a non-finite tensor fails closed and preserves evidence.
- Secrets use an ACL-restricted temporary path, never appear in command output or reports, and are removed after handoff to aria2.
- Every action and result is appended chronologically to the outer and repository `all.md` until the single final commit; post-push facts remain in the outer log to preserve that one-commit requirement.
- Data, weights, external repositories, teacher cache, checkpoints, cookies, and tokens never enter Git.

## Verification

Behavior changes use strict RED/GREEN tests on controlled local fixtures. Operational downloads use receipts and independent hashes. Final evidence includes compileall, full pytest, CUDA runtime, asset verification, readiness validation, Git scope audit, download receipts, five locks, teacher smoke/export audit, and the real preflight receipt. A missing authenticated SharePoint asset or any other unresolved upstream gate produces `BLOCKED_BEFORE_CONFERENCE_REPRO`; no approximation is accepted.
