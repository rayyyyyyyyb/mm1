# R3 Assets Download and Conference Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reliably acquire and audit all public OV-OrthKD conference-reproduction assets on the RTX 5090 host, close the remaining code/configuration gaps, export real teacher caches, and reach an evidence-backed `READY_FOR_CONFERENCE_REPRO` or an honest `BLOCKED_BEFORE_CONFERENCE_REPRO`.

**Architecture:** A pure, testable asset catalog and validation core feeds an aria2-based detached Windows supervisor and status monitor. Existing fail-closed data, teacher, fingerprint, evaluator, and preflight components are extended through TDD; real smoke/export/preflight execution remains downstream of immutable hashes and canonical gates.

**Tech Stack:** Python 3.11, pytest, aria2, PowerShell hidden processes, Playwright Chromium for optional legal SharePoint authorization, Git, 7-Zip, FFmpeg, PyTorch 2.10/CUDA 12.8.

**Spec:** `docs/superpowers/specs/2026-08-20-r3-assets-download-and-readiness-design.md`

## Global Constraints

- Start commit is exactly `f6e85eb61cdc09e530038d46671f70ee2618ea5c`; branch is `repro/r3-assets-download-and-readiness`.
- Formal full training, any full epoch, validation/test threshold selection, and formal conference metrics are forbidden in R3.
- Journal-extension mechanisms are out of scope.
- Official archive, data, weights, external repositories, teacher caches, checkpoints, cookies, and tokens remain Git-ignored.
- A real optimizer step may run once and only after every upstream canonical gate passes.
- Free space below 50 GiB gracefully pauses downloads while preserving session and partial files.
- User instruction requires one final clean commit; therefore intermediate tasks end with tests and chronological `all.md` entries, not intermediate commits.

---

### Task 1: Exact Asset Catalog and Binary Validation

**Files:**
- Create: `scripts/assets/__init__.py`
- Create: `scripts/assets/mm26_asset_catalog.py`
- Create: `scripts/assets/asset_validation.py`
- Create: `tests/test_r3_asset_catalog.py`
- Create: `tests/test_r3_asset_validation.py`

**Interfaces:**
- Produces: `AssetSpec(name, kind, target, sources, expected_sha256, checkpoint_format)`.
- Produces: `validate_download(path: Path, spec: AssetSpec) -> ValidationReceipt`.
- Produces: `probe_response(head: bytes, content_type: str | None, content_length: int | None) -> list[str]`.

- [x] **Step 1: Write the failing catalog tests**

```python
def test_weight_catalog_has_exact_targets_and_hashes():
    specs = {item.name: item for item in weight_assets()}
    assert specs["internvideo2_b14"].expected_sha256 == "1037a4785a830f9d663cab72da5751129e012042e428a74e019f84f016cd0be7"
    assert specs["clap_2023"].target.as_posix() == "weights/clap/CLAP_weights_2023.pth"
    assert len(specs) == 5
```

- [x] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_r3_asset_catalog.py`

Expected: collection fails because `scripts.assets.mm26_asset_catalog` does not exist.

- [x] **Step 3: Implement immutable catalog records**

Use a frozen dataclass, literal task-book hashes, ordered official/fallback source tuples, and the five exact checkpoint roles. Include the two SharePoint records and five Git repository records without embedding cookies or tokens.

- [x] **Step 4: Run catalog GREEN**

Run: `python -m pytest -q tests/test_r3_asset_catalog.py`

Expected: all catalog tests pass.

- [x] **Step 5: Write binary validation RED tests**

```python
@pytest.mark.parametrize("payload", [b"<html>login</html>", b"<?xml version='1.0'?>", b"version https://git-lfs.github.com/spec/v1"])
def test_validation_rejects_non_asset_payloads(tmp_path, payload):
    path = tmp_path / "asset.pth"
    path.write_bytes(payload)
    receipt = validate_download(path, fake_spec(hashlib.sha256(payload).hexdigest()))
    assert receipt.status == "failed"
```

- [x] **Step 6: Run validation RED**

Run: `python -m pytest -q tests/test_r3_asset_validation.py`

Expected: import or assertion failure because the validator is absent.

- [x] **Step 7: Implement streaming validation and quarantine decisions**

Reject zero length, HTML/XML/login/LFS signatures, implausible content metadata, and SHA mismatch. Return structured evidence rather than deleting or overwriting bytes. Checkpoint-specific `torch.load` validation remains opt-in so ordinary status commands do not allocate large tensors.

- [x] **Step 8: Run Task 1 GREEN and log**

Run: `python -m pytest -q tests/test_r3_asset_catalog.py tests/test_r3_asset_validation.py`

Expected: all tests pass. Append RED/GREEN commands and exit codes to both `all.md` copies.

---

### Task 2: Aria2 Input Builder and Detached Download Manager

**Files:**
- Create: `scripts/assets/download_mm26_assets.py`
- Create: `tests/test_r3_download_manager.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `AssetSpec`, `validate_download`.
- Produces: `build_aria2_arguments(spec, paths, connections) -> list[str]`.
- Produces: `build_aria2_input(specs, secret_headers=None) -> str`.
- Produces CLI modes: `--all`, `--weights-only`, `--data-only`, `--resume`, `--status`, `--verify`.

- [x] **Step 1: Write manager RED tests**

```python
def test_aria2_arguments_are_resumable_and_never_overwrite(tmp_path):
    args = build_aria2_arguments(fake_spec(), DownloadPaths(tmp_path), connections=8)
    assert "--continue=true" in args
    assert "--max-tries=0" in args
    assert "--allow-overwrite=false" in args
    assert any(value.startswith("--save-session=") for value in args)
```

Add tests for deterministic targets, completed-valid skip, wrong-hash quarantine plan, 429/503 connection downgrade, and CLI mutual behavior.

- [x] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_r3_download_manager.py`

Expected: import failure for the missing manager.

- [x] **Step 3: Implement manager core**

Keep command construction pure. Operational launch resolves `aria2c.exe`, creates `incoming/state/logs/tmp/quarantine`, writes input/session files atomically, and starts a hidden PowerShell process whose PID and start time are recorded in a non-secret JSON state file. Never use a forced timeout.

- [x] **Step 4: Extend `.gitignore` and pressure-test it**

Ensure generated download state, incoming bytes, quarantine, weights, external repositories, cookies, and Playwright profiles are ignored while `reports/downloads/*.json` and source scripts remain trackable. Verify with `git check-ignore -v` on representative paths.

- [x] **Step 5: Run GREEN and CLI fixture checks**

Run: `python -m pytest -q tests/test_r3_download_manager.py`

Run: `python scripts/assets/download_mm26_assets.py --status --root tests/fixtures/empty_asset_root`

Expected: tests pass; status exits 0 without starting downloads.

---

### Task 3: Download and Disk-Safety Monitor

**Files:**
- Create: `scripts/assets/monitor_downloads.py`
- Create: `tests/test_r3_download_monitor.py`

**Interfaces:**
- Consumes: asset catalog, state files, logs, `.aria2` files, validation receipts.
- Produces: `collect_download_status(root: Path, now: datetime) -> dict`.
- Produces: atomic `reports/downloads/live_status.json` and `live_status.md`.

- [x] **Step 1: Write monitor RED tests**

```python
def test_low_disk_requests_pause_without_deleting_partial(tmp_path):
    partial = tmp_path / "asset.pth"
    partial.write_bytes(b"partial")
    status = collect_download_status(tmp_path, free_bytes=49 * 1024**3)
    assert status["disk_guard"]["action"] == "pause_requested"
    assert partial.read_bytes() == b"partial"
```

Add literal fixture tests for byte counts, completion ratio, `.aria2` presence, PID liveness, retry extraction, stale progress time, SHA state, and Markdown rendering.

- [x] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_r3_download_monitor.py`

Expected: missing monitor import.

- [x] **Step 3: Implement `--once` and `--watch`**

Use atomic temp-plus-replace output. `--watch` waits 60 seconds between samples, continues after recoverable log/JSON parse errors, and issues a graceful aria2 pause request when disk is below the fixed threshold.

- [x] **Step 4: Run GREEN**

Run: `python -m pytest -q tests/test_r3_download_monitor.py`

Expected: all monitor tests pass.

---

### Task 4: SharePoint Anonymous Resolution and Legal Interactive Authorization

**Files:**
- Create: `scripts/assets/resolve_sharepoint_download.py`
- Create: `tests/test_r3_sharepoint_resolver.py`
- Create when required at runtime: `reports/downloads/SHAREPOINT_AUTH_REQUIRED.md`

**Interfaces:**
- Produces: `classify_sharepoint_response(final_url, content_type, prefix, length) -> ResolutionStatus`.
- Produces: `resolve_anonymous(url) -> ResolvedDownload | AuthRequired`.
- Produces: visible Playwright `--interactive` mode with a user-only secret handoff file.

- [x] **Step 1: Write resolver RED tests**

```python
def test_login_redirect_is_auth_required_without_secret_leak():
    result = classify_sharepoint_response(
        "https://login.microsoftonline.com/...", "text/html", b"<html>", 5432
    )
    assert result.status == "AUTH_REQUIRED"
    assert "cookie" not in json.dumps(result.public_dict()).lower()
```

Also test valid binary redirect, `download=1` variants, HTML masquerading, token redaction, and secret-file cleanup.

- [x] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_r3_sharepoint_resolver.py`

Expected: missing resolver import.

- [x] **Step 3: Implement anonymous probe and Playwright boundary**

Anonymous mode performs only small HEAD/Range requests. Interactive mode opens visible Chromium, waits for the user, captures the first validated binary download request, restricts the secret file to the current Windows account, starts aria2, and removes the file after handoff. Reports contain only status, timestamps, and sanitized domains.

- [x] **Step 4: Run GREEN and live anonymous probes**

Run: `python -m pytest -q tests/test_r3_sharepoint_resolver.py`

Run the resolver once for each official SharePoint URL without interactive credentials. If `AUTH_REQUIRED`, keep other work running and give the user exact visible-login steps.

---

### Task 5: Bootstrap Tools, Clone Official Repositories, and Launch Public Downloads

**Files:**
- Create: `scripts/assets/bootstrap_windows_tools.ps1`
- Create: `scripts/assets/clone_mm26_repositories.py`
- Create: `tests/test_r3_repository_locking.py`
- Generate: `reports/downloads/asset_receipts.json`
- Generate: `configs/locks/mm26_download_lock.yaml`

**Interfaces:**
- Produces exact portable tool paths below `E:\OV-OrthKD-R3\tools`.
- Produces repository receipts with origin, full commit, branch, clean state, license path/hash, and key source hashes.

- [x] **Step 1: Test repository receipt validation RED**

Create tiny local Git fixtures and assert wrong origin, dirty checkout, abbreviated commit, missing license, and mismatched key-source hash fail closed.

- [x] **Step 2: Implement repository cloning and lock receipts**

Clone InternVideo, sparse `unilm/beats`, Microsoft CLAP, MobileCLIP, and OV-AVEL concurrently into the exact Git-ignored targets. Pin the observed full commits rather than the word `latest`.

- [ ] **Step 3: Install/verify portable operational tools**

Use official package sources, verify downloaded archives before extraction, and record versions for aria2, 7-Zip, FFmpeg, jq, and Git LFS. Do not install WSL or request an administrator password when portable/user-scoped tools suffice.

- [x] **Step 4: Launch five weight downloads concurrently**

Sync the tested asset scripts to `E:\OV-OrthKD-R3\repo`, start hidden aria2 jobs, start the monitor as a separate hidden process, and immediately return control. Record PID, log, session, destination, and source selection.

- [ ] **Step 5: Poll conditionally while continuing later tasks**

Use short status invocations rather than a blocking foreground wait. On completion, run full SHA256 and checkpoint-structure validation, promote verified files, and regenerate the download lock.

---

### Task 6: Paper-Specified Reconstruction and the 18-Defect Regression Matrix

**Files:**
- Modify: `configs/ov_orthkd_mm26_repro.yaml`
- Modify: `configs/locks/mm26_archival_facts.yaml`
- Modify: `configs/locks/mm26_preprocessing_lock.yaml`
- Modify: `configs/locks/mm26_evaluator_lock.yaml`
- Modify only when a new failing test proves a gap: `src/data/ov_avel_dataset.py`, `src/teachers/*.py`, `src/utils/*.py`, `scripts/train_ov_orthkd.py`, `scripts/evaluate_pr_f1.py`, `scripts/verify_cuda_runtime.py`, `scripts/export_teacher_artifacts.py`
- Create: `tests/test_r3_conference_reconstruction.py`
- Create: `tests/test_r3_remaining_defects.py`

**Interfaces:**
- Claim level: `paper_specified_reconstruction`.
- Canonical configuration binds exact task-book values and all five core locks plus the new download lock.

- [x] **Step 1: Audit all 18 requirements against behavior tests**

Map every item to an existing R1/R2 test or add one new failing behavior test. Do not add source-text grep tests. Name the mutation each test catches before writing its body.

- [x] **Step 2: Run focused RED matrix**

Run: `python -m pytest -q tests/test_r3_conference_reconstruction.py tests/test_r3_remaining_defects.py`

Expected: only genuinely missing behaviors fail; already-correct R2 behavior remains green and is not rewritten.

- [x] **Step 3: Apply minimal fixes one defect at a time**

For each failure, trace the bad value/state to its source, patch only that path, rerun its single test, then rerun the focused matrix. Required behaviors include scheduler-free eval-only, split-isolated caches, append-only per-record receipts, full resume state, non-mutating dimension probes, safe NumPy/image loading, finite checks, CUDA synchronization, and lock-bound fingerprints.

- [x] **Step 4: Freeze reconstruction evidence without pretending assets exist**

Update approved reconstruction facts with exact config paths/values and `approved_by: user`. Keep data/checkpoint/smoke/export statuses blocked until real bytes pass. Do not create `configs/ov_orthkd_mm26_repro_ready.yaml` yet.

- [x] **Step 5: Run focused GREEN and prior regression suite**

Run the two R3 files plus all R1/R2 canonical, data, teacher, evaluation, resume, and preflight tests.

---

### Task 7: Official Archive Safety, Layout Discovery, and Source Manifests

**Files:**
- Modify if tests expose gaps: `scripts/safe_extract_official_archive.py`
- Modify if tests expose gaps: `scripts/discover_ovave_layout.py`
- Modify if tests expose gaps: `scripts/build_ov_avebench_source_manifests.py`
- Modify if tests expose gaps: `scripts/audit_mm26_reproduction.py`
- Create: `tests/test_r3_official_data_pipeline.py`
- Generate only from real data: official archive/layout receipts, source manifests, data/preprocessing locks.

**Interfaces:**
- Safe extraction refuses absolute/traversal/symlink/duplicate/bomb-risk members before publishing a tree.
- Source manifests have exact 13,182/5,798/5,820 records and normalized seen/unseen split types.

- [x] **Step 1: Add any missing adversarial extraction/layout tests and run RED**

Cover archive member collisions, case folding on Windows, link escape, decompression ratio/total size, metadata/filesystem bijection, raw-video ID matching, PNG counts, WAV properties, and video probe fields.

- [x] **Step 2: Implement only proven gaps and run GREEN**

Use staging extraction plus atomic publish. Preserve original archives. Never infer a missing raw video from PNGs.

- [ ] **Step 3: Run real pipeline only after verified official archives exist**

Generate receipts, layouts, source manifests, and audits; require zero errors and zero warnings. If SharePoint remains unavailable, leave all runtime steps unexecuted and report the exact authentication blocker.

---

### Task 8: Exact Teachers, Repeat-2 Smoke, Resumable Full Export, and Export Monitor

**Files:**
- Modify: `configs/locks/mm26_teacher_lock.yaml`
- Modify as exact repositories require: `src/teachers/internvideo2_visual.py`, `beats_audio.py`, `clap_text.py`, `pipeline.py`
- Modify: `scripts/inspect_teacher_identity.py`
- Modify: `scripts/export_teacher_artifacts.py`
- Create: `scripts/teachers/__init__.py`
- Create: `scripts/teachers/monitor_export.py`
- Create: `tests/test_r3_real_teacher_contracts.py`
- Create: `tests/test_r3_export_monitor.py`

**Interfaces:**
- InternVideo2 `[10, 512]`, BEATs `[10, 768]`, CLAP `[1024]`.
- Cache target `data/teacher_cache/mm26/{train,val,test}/...` with per-record receipt and deterministic root hash.

- [ ] **Step 1: Write strict-load and preprocessing RED tests from exact official classes**

Use minimal synthetic checkpoint structures only to exercise wrapper mapping; live strict-load is separately recorded against verified real files. Test output shape, no singleton broadcast, finite rejection, raw-video sampling contract, BEATs raw waveform input, and exact CLAP 2023 binding.

- [ ] **Step 2: Implement repository/checkpoint bindings and run GREEN**

Lock observed repository commits, imported module/classes, preprocessing and all five checkpoint hashes. Refuse class/variant mismatch and unused/missing strict-load keys beyond explicitly documented official wrappers.

- [ ] **Step 3: Implement export monitor through RED/GREEN**

Monitor per-split receipts, speed, ETA, failures, current ID, GPU utilization/memory, and disk space without touching cached data.

- [ ] **Step 4: Run one real record repeat-2 smoke**

Record dtype/statistics/finite/repeatability/latency/memory and require the exact output shapes.

- [ ] **Step 5: Start full export detached and resume until audited**

Use a hidden process equivalent to `mm26-teacher-export`. Skip only records whose files, shapes, hashes, and teacher-lock fingerprint validate. Require 24,800 receipts and compute a deterministic cache root SHA256.

---

### Task 9: Canonical One-Step Preflight and Ready Configuration

**Files:**
- Modify: `scripts/preflight_ov_orthkd.py`
- Create: `scripts/validate_conference_readiness.py`
- Create: `tests/test_r3_final_readiness_gate.py`
- Generate after all gates pass: `reports/runtime/r3_real_preflight.json`
- Generate only after all gates pass: `configs/ov_orthkd_mm26_repro_ready.yaml`

**Interfaces:**
- `validate_conference_readiness(config) -> readiness receipt` recomputes every lock/artifact/checkpoint/cache/evaluator byte.
- Real preflight invocation count is exactly one and optimizer steps are exactly one.

- [ ] **Step 1: Write gate RED tests**

Assert missing archive, manifest, checkpoint, cache root, smoke, evaluator, dirty Git, unresolved marker, wrong config binding, or previous preflight invocation prevents model/data construction and prevents ready-config creation.

- [ ] **Step 2: Run RED and implement minimal canonical aggregation**

Reuse `src/utils/canonical_readiness.py`; do not create a weaker validator. The CLI exits nonzero and writes a blocked receipt when any input fails.

- [ ] **Step 3: Run GREEN with complete synthetic canonical fixture**

Require ready only with exact bytes and clean Git fixture. Confirm the real repository remains blocked until operational artifacts exist.

- [ ] **Step 4: Run the one real step only if operational gate is ready**

Forward, all camera-ready losses, finite backward/gradients, one optimizer step, checkpoint save/rebuild/load, and complete state/RNG restoration. Do not evaluate validation/test or produce formal metrics.

- [ ] **Step 5: Create ready config only after the successful receipt**

Copy the fully bound canonical config to `configs/ov_orthkd_mm26_repro_ready.yaml` with `full_run_blocked: false`. Do not invoke the training entry point for a full run.

---

### Task 10: Final Audit, Report, Single Commit, and Push

**Files:**
- Create: `reports/R3_ASSET_DOWNLOAD_AND_READINESS_REPORT.md`
- Regenerate: `reports/mm26_conference_readiness.json`
- Update: `README.md`
- Update: both `all.md` copies through the pre-commit audit.

**Interfaces:**
- Final status is exactly `READY_FOR_CONFERENCE_REPRO` or `BLOCKED_BEFORE_CONFERENCE_REPRO`.

- [ ] **Step 1: Run the complete verification matrix on 5090**

```text
python -m compileall -q src scripts tests
python -m pytest -q
python scripts/verify_cuda_runtime.py
python scripts/assets/download_mm26_assets.py --verify
python scripts/validate_conference_readiness.py --config <actual candidate config>
```

Record every exit code. Expected nonzero readiness is acceptable only when the final status is BLOCKED and the report names the exact real blocker.

- [ ] **Step 2: Audit evidence and Git scope**

Recompute every asset/lock/cache/report SHA. Parse all JSON/YAML. Scan for secrets, weights, checkpoints, archives, caches, raw data, external repositories, and files over 1 MiB. Run `git diff --check`, inspect every staged path, and require no unstaged changes.

- [ ] **Step 3: Create the single clean R3 commit**

Commit all source, tests, locks, receipts, reports, plan, and pre-push `all.md` snapshot once. Verify exactly one R3 commit from `f6e85eb…` and a clean worktree.

- [ ] **Step 4: Push and verify web-visible SHA**

Push `repro/r3-assets-download-and-readiness`, compare `git ls-remote` to local HEAD, check branch/commit/report HTTP status, and append post-push facts to the outer `all.md` only so the one-commit rule remains true.
