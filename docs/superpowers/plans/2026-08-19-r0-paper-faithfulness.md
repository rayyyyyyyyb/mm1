# OV-OrthKD R0 Paper-Faithfulness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a tested, auditable R0 implementation that distinguishes the camera-ready OV-OrthKD computation graph from the legacy collaboration graph and blocks unsupported canonical full runs.

**Architecture:** The student exposes explicit decision, audio-auxiliary, and query projections only in camera-ready mode while a separate loss class preserves legacy behavior. Strict data/config validation, deterministic execution, prediction-aware evaluation, and audit scripts form an evidence boundary around both modes. Code is authored in the local `扩刊/OV-OrthKD-R0` worktree, executed in a native Windows Python environment on the RTX 5090, and evidence is copied back locally.

**Tech Stack:** Python 3.11, PyTorch with CUDA 12.8+, torchvision, timm, NumPy, scikit-learn, PyYAML, pytest, Windows OpenSSH/PowerShell, Git.

**Spec:** `docs/superpowers/specs/2026-08-19-r0-paper-faithfulness-design.md`

## Global Constraints

- Base commit is exactly `dca9f052fbe4a1e9d7982f24bdcec3edf1363fd4` on branch `repro/r0-paper-faithfulness`.
- Implement R0 conference-paper reproduction hardening only; do not implement VP-AdaOrthKD routing, reliability, OOF probes, or selective orthogonality.
- Do not download the complete dataset, export complete teacher artifacts, or launch complete training.
- Only unit tests, mock smoke tests, CUDA runtime verification, and CPU/GPU one-batch preflight are permitted.
- `alpha_strong_logit: 0.0` and `alpha_weak_logit: 0.0` are fixed in the camera-ready reproduction config.
- Preserve all six `BLOCKED_ARCHIVAL_FACTS`; never invent T=16 resampling, teacher identities, scheduler semantics, initialization, augmentation, L2 reduction, or fusion history.
- Code, reports, and retrieved evidence live under local `扩刊`; Python/Git/venv/package caches live only on the 5090.
- Create one final clean commit with message `repro: harden paper-faithful OV-OrthKD baseline`; do not make intermediate commits.

---

### Task 1: Establish the 5090 runtime and verify the untouched baseline

**Files:**
- Modify later: `scripts/setup_server.sh`
- Create later: `scripts/verify_cuda_runtime.py`
- Runtime only: `E:\OV-OrthKD-R0\env\.venv`
- Runtime only: `E:\OV-OrthKD-R0\repo`

**Interfaces:**
- Consumes: local clean worktree at base commit and SSH target `LXT@100.119.122.101`.
- Produces: callable remote Python path `E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe`, baseline pytest result, GPU identity, and dependency-install transcript.

- [ ] **Step 1: Verify official runtime sources**

Use primary Python/PyTorch documentation to confirm Python 3.11 support and the CUDA 12.8 wheel index. Record URLs and decisions in `all.md`; install no package from an unofficial mirror.

- [ ] **Step 2: Install remote user-scoped tools**

Run non-interactive PowerShell through SSH:

```powershell
winget install --id Python.Python.3.11 --exact --silent --scope user --accept-package-agreements --accept-source-agreements
winget install --id Git.Git --exact --silent --scope user --accept-package-agreements --accept-source-agreements
```

Resolve the installed executable paths explicitly rather than relying on the existing SSH `PATH`.

- [ ] **Step 3: Create a clean remote venv and install CUDA dependencies**

```powershell
& $Python311 -m venv E:\OV-OrthKD-R0\env\.venv
& E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
& E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
& E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe -m pip install -r E:\OV-OrthKD-R0\repo\requirements.txt
```

- [ ] **Step 4: Upload the untouched worktree and run baseline tests**

Archive tracked source without `.git`, venv, data, checkpoints, or outputs; upload and expand to `E:\OV-OrthKD-R0\repo`. Run:

```powershell
& $RemotePython -m pip check
& $RemotePython -m pytest -q
```

Expected baseline: existing tests pass. If installation or tests fail, diagnose the exact failure before modifying source.

- [ ] **Step 5: Record the baseline**

Append Python, PyTorch, CUDA, GPU, test count, warnings, and exit codes to `all.md`. Do not commit.

### Task 2: Add dual student paths and separate legacy/camera-ready losses

**Files:**
- Modify: `src/models/ov_orthkd.py`
- Modify: `src/models/__init__.py`
- Modify: `src/losses/ov_orthkd_loss.py`
- Create: `src/losses/ov_orthkd_legacy_loss.py`
- Modify: `src/losses/__init__.py`
- Create: `tests/test_paper_faithfulness.py`
- Modify: `tests/test_ov_orthkd_pipeline.py`

**Interfaces:**
- Consumes: baseline `OVOrthKDStudent` and `OVOrthKDLoss` behavior.
- Produces: `ProjectionHead`, `OVOrthKDStudent(..., projection_dim: int = 256, path_mode: str = "explicit_projected")`, `OVOrthKDLoss`, `OVOrthKDLegacyLoss`, and explicit output keys `shared_features`, `decision_features`, `audio_aux_features`, `query_features`.

- [ ] **Step 1: Write failing model-path tests**

Add tests equivalent to:

```python
def test_localization_head_reads_decision_projection():
    model = build_tiny_test_student(path_mode="explicit_projected")
    captured = {}
    handle = model.segment_head.register_forward_pre_hook(
        lambda _module, inputs: captured.setdefault("head_input", inputs[0].detach().clone())
    )
    outputs = model(**make_tiny_batch())
    handle.remove()
    assert torch.allclose(captured["head_input"], outputs["decision_features"])
    assert captured["head_input"].shape[-1] == model.projection_dim

def test_legacy_mode_keeps_shared_head_and_no_projection_parameters():
    model = build_tiny_test_student(path_mode="legacy_shared")
    outputs = model(**make_tiny_batch())
    assert outputs["decision_features"] is None
    assert model.segment_head.in_features == model.fusion_dim
    assert not any(name.startswith("decision_proj") for name, _ in model.named_parameters())
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run remotely:

```powershell
& $RemotePython -m pytest tests\test_paper_faithfulness.py -q
```

Expected failure: missing `path_mode`, projection outputs, or `ProjectionHead` in the model module.

- [ ] **Step 3: Implement the model paths**

Move `ProjectionHead` to `src/models/ov_orthkd.py`. Validate `path_mode` against `{"explicit_projected", "legacy_shared"}`. Create projection modules and a projection-sized segment head only in explicit mode. Return the exact dictionary:

```python
return {
    "segment_logits": segment_logits,
    "shared_features": shared_features,
    "decision_features": decision_features,
    "audio_aux_features": audio_aux_features,
    "query_features": query_features,
    "segment_features": shared_features,
    "visual_tokens": visual_tokens,
    "audio_tokens": audio_tokens,
    "text_tokens": text_token,
    "gate_logits": gate_logits,
    "gate_weights": gate_weights,
}
```

- [ ] **Step 4: Freeze legacy loss before replacing the camera-ready class**

Copy the baseline formulas and parameter names into `OVOrthKDLegacyLoss`. The class keeps `student_dim` and `student_*_proj`; it is the only class allowed to implement temperature-logit text BCE.

- [ ] **Step 5: Write failing camera-ready loss tests**

Cover mapped probability BCE, disabled logit terms, every enabled-but-missing tensor/mask, squared-cosine orthogonality, and absence of student projectors. The formula test is:

```python
student = torch.tensor([[[0.0, 1.0], [0.0, -1.0]]])
text = torch.tensor([[1.0, 0.0]])
labels = torch.tensor([[1.0, 0.0]])
terms = paper_text_alignment_terms(student, text, labels)
assert torch.allclose(terms, torch.full_like(terms, torch.log(torch.tensor(2.0))), atol=1e-6)
```

- [ ] **Step 6: Implement the camera-ready loss**

Use keyword-only explicit path tensors and separate weak feature/logit masks:

```python
def forward(
    self,
    *,
    student_segment_logits: torch.Tensor,
    student_decision_features: torch.Tensor,
    student_audio_aux_features: torch.Tensor,
    student_query_features: torch.Tensor,
    segment_labels: torch.Tensor,
    sequence_mask: torch.Tensor,
    strong_teacher_logits: torch.Tensor | None = None,
    strong_teacher_features: torch.Tensor | None = None,
    weak_teacher_logits: torch.Tensor | None = None,
    weak_teacher_features: torch.Tensor | None = None,
    text_embeddings: torch.Tensor | None = None,
    strong_teacher_logit_mask: torch.Tensor | None = None,
    strong_teacher_feature_mask: torch.Tensor | None = None,
    weak_teacher_logit_mask: torch.Tensor | None = None,
    weak_teacher_feature_mask: torch.Tensor | None = None,
    text_valid: torch.Tensor | None = None,
) -> tuple[torch.Tensor, dict[str, float]]:
```

Compute a term only when its alpha is positive. `_require_tensor` raises `ValueError` naming the missing field. `_masked_mean` validates equal shapes.

- [ ] **Step 7: Sync and run focused tests**

Run the model/loss tests on the 5090; expect all pass and finite backward gradients. Record exit code and test count in `all.md`. Do not commit.

### Task 3: Enforce strict artifact loading and deterministic DataLoaders

**Files:**
- Modify: `src/data/ov_avel_dataset.py`
- Modify: `src/data/__init__.py`
- Create: `tests/test_strict_reproduction_data.py`
- Modify: `tests/test_ov_orthkd_pipeline.py`

**Interfaces:**
- Consumes: manifest records and `data.path_root`, `data.required_artifacts`, `seed`.
- Produces: `_resolve_path`, `_artifact_required`, `seed_worker`, explicit `weak_teacher_feature_mask`, and deterministic train/val/test loaders.

- [ ] **Step 1: Write failing strict-data tests**

Add tests for a missing required weak feature, permissive zero fallback, relative paths from a different CWD, invalid dimensions, and deterministic loader ordering. Core assertions:

```python
with pytest.raises(FileNotFoundError, match="weak_teacher_features.*sample_0"):
    _ = strict_dataset[0]

sample = permissive_dataset[0]
assert sample["weak_teacher_feature_mask"].sum().item() == 0.0
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Expected failure: missing constructor options or unresolved relative paths.

- [ ] **Step 3: Implement root-based path resolution and required artifacts**

Add:

```python
def _resolve_path(self, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = self.path_root / path
    return path.resolve()

def _artifact_required(self, field_name: str) -> bool:
    return field_name in self.required_artifacts
```

Use `_resolve_path` for frames, spectrograms, teacher arrays, text embeddings, and override paths. Required missing artifacts raise `FileNotFoundError` with field and record id.

- [ ] **Step 4: Implement deterministic workers and generators**

```python
def seed_worker(worker_id: int) -> None:
    del worker_id
    worker_seed = torch.initial_seed() % (2**32)
    np.random.seed(worker_seed)
    random.seed(worker_seed)
```

Create separately seeded generators for train, val, and test so iterating one loader cannot advance another loader's order.

- [ ] **Step 5: Preserve the compatibility alias**

Return `weak_teacher_feature_mask` as canonical and `weak_teacher_mask` as a temporary identical alias. New train/preflight code uses only the canonical name.

- [ ] **Step 6: Sync and run strict-data plus legacy pipeline tests**

Expect strict failures where configured, permissive legacy behavior where configured, and deterministic equality across recreated loaders. Record results; do not commit.

### Task 4: Add mode validation, run blocking, schedulers, and complete training evidence

**Files:**
- Modify: `scripts/train_ov_orthkd.py`
- Modify: `scripts/preflight_ov_orthkd.py`
- Create or modify: `tests/test_training_reproducibility.py`
- Modify: `tests/test_teacher_export_and_preflight.py`

**Interfaces:**
- Consumes: dual model/loss classes and deterministic loaders.
- Produces: `validate_repro_config`, `build_scheduler`, deterministic `set_seed`, `sha256_file`, evidence writers, prediction collection, `best.pt`/`last.pt`, and full-run safety behavior.

- [ ] **Step 1: Write failing configuration and safety tests**

Test the exact allowed mappings, rejection of mismatches, rejection of blocked full training, creation of `NON_CANONICAL_UNRESOLVED_RUN.txt` when explicitly overridden, early-stop config fallback, and distinct max-step semantics.

```python
with pytest.raises(ValueError, match="camera_ready_explicit_paths.*explicit_projected"):
    build_model_and_loss(mismatched_config, torch.device("cpu"))

with pytest.raises(RuntimeError, match="full run is blocked"):
    validate_repro_config(repro_config, allow_blocked=False, preflight=False)
```

- [ ] **Step 2: Implement one-to-one model/loss construction**

`build_model_and_loss` returns `tuple[OVOrthKDStudent, nn.Module]`. It selects `OVOrthKDLoss` only for camera-ready explicit mode and `OVOrthKDLegacyLoss` only for legacy shared mode.

- [ ] **Step 3: Remove synthetic audio logits and add fail-fast behavior**

Delete the random-noise proxy. When `alpha_weak_logit > 0` and a batch contains no real weak logits, raise:

```python
RuntimeError(
    "alpha_weak_logit > 0, but the batch contains no real weak-teacher logits. "
    "Synthetic logits are forbidden in paper reproduction."
)
```

- [ ] **Step 4: Implement deterministic setup and scheduler construction**

`set_seed(seed: int, deterministic: bool = True)` configures Python, NumPy, PyTorch, CUDA, cuDNN, and deterministic algorithms. `build_scheduler` returns `(scheduler, interval)` for cosine or step and raises on `UNRESOLVED`.

- [ ] **Step 5: Implement optimizer-step and per-epoch limits**

Maintain `global_step`; stop all training at `max_optimizer_steps`, while `max_batches_per_epoch` only truncates each epoch. Emit a deprecation warning when `--max-train-steps` supplies the per-epoch limit.

- [ ] **Step 6: Implement evidence writers**

Write `runtime.json`, `resolved_config.yaml`, `git_state.json`, `requirements_freeze.txt`, `manifest_hashes.json`, `history.jsonl`, `best.pt`, `last.pt`, `best_validation_predictions.npz`, `test_predictions.npz`, `final_metrics.json`, and `train.log`. Every checkpoint includes `implementation_mode`, `global_step`, optimizer/scheduler/scaler states, and config.

- [ ] **Step 7: Update preflight to reuse production builders**

Preflight must call `validate_repro_config(..., preflight=True)`, use explicit output paths/masks, use `build_scheduler`, exercise forward/backward/evaluation/save/resume, and label mock outputs as mock.

- [ ] **Step 8: Sync and run focused training/preflight tests**

Expect mode mismatches and blocked full runs to fail before data loading. Expect mock preflight forward/backward/resume/evaluation to pass. Record results; do not commit.

### Task 5: Export traceable predictions and total/seen/unseen metrics

**Files:**
- Modify: `scripts/train_ov_orthkd.py`
- Modify: `scripts/evaluate_pr_f1.py`
- Create: `tests/test_reproduction_evaluation.py`

**Interfaces:**
- Consumes: batch ids, queries, domains/meta split types, labels, masks, and model logits.
- Produces: prediction dictionaries/NPZ files, grouped metrics, validation-only threshold calibration, and PR summaries.

- [ ] **Step 1: Write failing prediction and threshold tests**

Construct two validation samples and two test samples with distinct optimal thresholds. Assert that the reported test threshold equals the validation threshold and that ids, queries, split types, offsets, and segment indices survive export.

- [ ] **Step 2: Implement structured prediction collection**

Return fields:

```python
{
    "ids": np.ndarray,
    "queries": np.ndarray,
    "split_types": np.ndarray,
    "sample_offsets": np.ndarray,
    "segment_indices": np.ndarray,
    "labels": np.ndarray,
    "logits": np.ndarray,
    "probabilities": np.ndarray,
}
```

Use Unicode arrays, not pickled Python objects.

- [ ] **Step 3: Implement grouped metrics**

For total, seen, and unseen report accuracy, F1@threshold, AP, AUROC, positive rate, sample count, and segment count. Handle one-class AUROC explicitly without crashing and record that it is unavailable rather than inventing a value.

- [ ] **Step 4: Enforce validation-only calibration**

Select best F1 threshold on all validation predictions once, persist the PR curve, and pass the frozen threshold to test metrics. Never invoke threshold search on test.

- [ ] **Step 5: Sync and run evaluation tests**

Expect the validation/test threshold equality assertion and structured NPZ round-trip to pass. Record results; do not commit.

### Task 6: Implement export truncation, strict audit, teacher identity, CUDA verification, and synchronized efficiency

**Files:**
- Modify: `src/teachers/pipeline.py`
- Modify: `scripts/export_teacher_artifacts.py`
- Create: `scripts/audit_mm26_reproduction.py`
- Create: `scripts/inspect_teacher_identity.py`
- Create: `scripts/verify_cuda_runtime.py`
- Modify: `scripts/measure_efficiency.py`
- Modify: `scripts/setup_server.sh`
- Modify: `tests/test_teacher_export_and_preflight.py`
- Create: `tests/test_reproduction_audit.py`

**Interfaces:**
- Consumes: source/exported manifests, artifact paths, teacher wrappers/checkpoints, and CUDA runtime.
- Produces: safe truncated manifests, JSON audit reports, teacher identity JSON, CUDA JSON, and synchronized latency results.

- [ ] **Step 1: Write failing export-limit and audit tests**

Export three mock records with `limit=1` and assert the output contains exactly one record by default. Audit fixtures cover duplicate ids, split overlap, non-binary labels, missing files, invalid exported dimensions, NaN artifacts, and a valid T=10 set.

- [ ] **Step 2: Fix teacher export truncation**

Add `copy_unprocessed_records: bool = False` to `export_manifest_records` and `export_manifest_file`. Add CLI `--copy-unprocessed-records`; default output contains only processed records and summary reports both processed and copied counts.

- [ ] **Step 3: Implement `audit_mm26_reproduction.py`**

Support all required CLI flags. Emit a JSON report with counts, category/split counts, duplicate/overlap lists, label and segment histograms, path/artifact errors, finite checks, manifest SHA256 values, `configured_max_segments: 16`, and `resampling_performed_by_dataset: false`. Exit nonzero for P0 errors and for warnings when `--fail-on-warning` is used.

- [ ] **Step 4: Implement `inspect_teacher_identity.py`**

Load only explicitly configured paths. Record wrapper/upstream classes, upstream Git SHA, checkpoint absolute paths and SHA256 hashes, top-level keys, dimensions, num_frames, CLAP version, BEATs `finetuned_model`, and smoke output shape/finite/norm stats. A missing or contradictory identity is an error, not an automatic download.

- [ ] **Step 5: Implement `verify_cuda_runtime.py`**

Print JSON containing Python, platform, torch, CUDA, GPU name, capability, cuDNN, synchronized FP16 2048×2048 matmul latency, finite flag, mean absolute value, allocated GB, and reserved GB. Raise when CUDA is absent or output is non-finite.

- [ ] **Step 6: Synchronize efficiency measurement**

Use `torch.cuda.Event` on CUDA and `time.perf_counter` on CPU. Synchronize before/after warmup and timing. Accept a segment count argument and label results with that exact T.

- [ ] **Step 7: Add cu128 to Linux setup helper**

Extend usage and case handling with:

```bash
cu128)
  TORCH_INDEX="https://download.pytorch.org/whl/cu128"
  ;;
```

- [ ] **Step 8: Sync and run focused tool tests**

Expect export truncation and valid audit tests to pass; invalid audit fixtures must return nonzero. Run CUDA verification on the 5090 and save its JSON. Record every result; do not commit.

### Task 7: Add canonical configs, update README, and run the complete R0 verification matrix

**Files:**
- Create: `configs/ov_orthkd_mm26_repro.yaml`
- Create: `configs/ov_orthkd_mm26_smoke.yaml`
- Modify: `README.md`
- Modify: `scripts/preflight_ov_orthkd.py`
- Create: `reports/R0_REPRO_HARDENING_REPORT.md`
- Runtime evidence: `reports/runtime/cuda_runtime_check.json`
- Runtime evidence: `reports/runtime/requirements-lock-5090.txt`
- Runtime evidence: `reports/runtime/nvidia-smi.txt`
- Runtime evidence: `reports/runtime/verification_commands.jsonl`

**Interfaces:**
- Consumes: all earlier production/test interfaces.
- Produces: canonical blocked config, unblocked mock config, documentation, full verification evidence, and the final report.

- [ ] **Step 1: Create the two configs exactly from the task specification**

The reproduction config uses explicit paths, strict artifacts, deterministic training, fixed loss weights, `scheduler.type: "UNRESOLVED"`, and `full_run_blocked: true`. The smoke config uses mock manifests, two epochs, two batches per epoch, cosine scheduling, and `full_run_blocked: false`.

- [ ] **Step 2: Update README safety guidance**

Document both modes, cu128/5090 setup, strict manifests, mock-only smoke commands, full-run blocking, and the six archival facts. Remove the unsafe suggestion that the old paper config is ready for direct reproduction.

- [ ] **Step 3: Generate mock manifests and artifacts in a temporary remote location**

Use test fixtures or the mock export pipeline. Do not download official data. Mark every generated record and summary as mock.

- [ ] **Step 4: Run the permitted verification matrix on the 5090**

Run each command independently and record its exit code:

```powershell
& $RemotePython -m pip check
& $RemotePython scripts\verify_cuda_runtime.py
& $RemotePython -m compileall -q src scripts tests
& $RemotePython -m pytest -q
& $RemotePython scripts\smoke_test.py
& $RemotePython scripts\preflight_ov_orthkd.py --config configs\ov_orthkd_mm26_smoke.yaml --output-dir outputs\r0_preflight --probe-samples 4 --max-eval-batches 2
```

Also run `git diff --check`, `git status --short`, and `git diff --stat` locally.

- [ ] **Step 5: Retrieve evidence into local `reports/runtime`**

Copy CUDA JSON, dependency freeze, `nvidia-smi`, pytest summary, smoke summary, and preflight summary back to the local worktree. Do not retrieve the venv or pip cache.

- [ ] **Step 6: Write the R0 report**

For every finding use one of `CONFIRMED_FIXED`, `CONFIRMED_REMAINING_BUG`, `BLOCKED_ARCHIVAL_FACT`, or `NOT_EXECUTED`. Include base/current SHA, file list, P0/P1 mapping, exact commands and exit codes, CUDA JSON summary, pytest/preflight summaries, all six blockers, and an explicit statement that no real-data full reproduction ran.

### Task 8: Final self-review, audit log inclusion, one clean commit, and GitHub upload

**Files:**
- Create in repository root: `all.md` copied from the enclosing authoritative log at finalization
- Create in repository root: `MM26_OVORTHKD_R0_REPRODUCTION_IMPLEMENTATION_TASK.md` copied from the enclosing task file at finalization
- Modify: `reports/R0_REPRO_HARDENING_REPORT.md` if verification changes facts

**Interfaces:**
- Consumes: complete local worktree and all retrieved evidence.
- Produces: one clean commit and uploaded GitHub branch containing the complete R0 folder contents.

- [ ] **Step 1: Run the two task-spec self-checklists**

Answer every method/code and reproducibility/safety item with evidence. Any unmet required item must be fixed or classified in the report before proceeding.

- [ ] **Step 2: Run final static and repository checks**

```powershell
git diff --check
git status --short
git diff --stat
git diff --name-status
```

Confirm no `.venv`, full data, teacher cache, output checkpoint, third-party checkpoint, or local `file://` dependency is staged.

- [ ] **Step 3: Copy the authoritative task and action log into the repository root**

The committed `all.md` must contain every substantive action/result in chronological order through final verification. Preserve the original UTF-8 task specification unchanged.

- [ ] **Step 4: Stage and inspect**

```powershell
git add src scripts configs tests reports README.md docs all.md MM26_OVORTHKD_R0_REPRODUCTION_IMPLEMENTATION_TASK.md
git diff --cached --check
git diff --cached --stat
```

- [ ] **Step 5: Create the single required commit**

```powershell
git commit -m "repro: harden paper-faithful OV-OrthKD baseline"
git rev-parse HEAD
```

- [ ] **Step 6: Push the complete branch to the corresponding GitHub repository**

Verify `origin` is `https://github.com/rayyyyyyyyb/mm1` or its authenticated equivalent. Push only after all checks pass:

```powershell
git push -u origin repro/r0-paper-faithfulness
```

Record remote URL, branch, commit SHA, push exit code, and any server response in `all.md` and the final report.
