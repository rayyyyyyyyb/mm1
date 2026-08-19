# OV-OrthKD R0 Paper-Faithfulness Design

## Purpose

Harden the collaboration baseline so it can truthfully support an ACM MM 2026 OV-OrthKD conference-paper reproduction attempt. R0 validates code paths and evidence collection only: it does not claim a numerical reproduction, download the complete dataset, export complete teacher artifacts, or start a full training run.

The authoritative task specification is `../MM26_OVORTHKD_R0_REPRODUCTION_IMPLEMENTATION_TASK.md` in the enclosing local `扩刊` directory. This design freezes its implementation boundaries for the `repro/r0-paper-faithfulness` branch at base commit `dca9f052fbe4a1e9d7982f24bdcec3edf1363fd4`.

## Repository and execution layout

- Source worktree: `扩刊/OV-OrthKD-R0`.
- Local source of truth: code, tests, configs, reports, `all.md`, and retrieved runtime artifacts under `扩刊`.
- Remote execution host: `LXT@100.119.122.101`, NVIDIA GeForce RTX 5090.
- Remote runtime root: `E:\OV-OrthKD-R0`; Python, Git, the virtual environment, package caches, and transient copied source remain on the 5090.
- The remote host is Windows without WSL, Python, or Git at the start of R0. It therefore uses a native Windows Python 3.11 venv and a CUDA 12.8-or-newer PyTorch wheel. `scripts/setup_server.sh` is still updated for Linux users, but is not the Windows deployment entry point.
- Runtime artifacts needed for audit are copied back into the local worktree before the final commit. Virtual environments and download caches are never copied back or committed.

## Dual implementation modes

The student owns three explicit projection heads only in `explicit_projected` mode. The localization head consumes `decision_features`; the audio and query paths are exposed independently. `legacy_shared` retains the original parameter structure and feeds the shared temporal feature directly to the localization head.

Mode selection is one-to-one:

- `camera_ready_explicit_paths` → `explicit_projected` student + `OVOrthKDLoss`.
- `legacy_collaboration` → `legacy_shared` student + `OVOrthKDLegacyLoss`.

Configuration validation rejects every cross-pairing. Checkpoints, metrics, reports, and prediction exports record `implementation_mode`, preventing legacy and camera-ready results from being mislabeled.

## Loss semantics

`OVOrthKDLegacyLoss` preserves the baseline formulas and parameter structure for controlled historical reruns. The new `OVOrthKDLoss` consumes explicit decision, audio-auxiliary, and query features.

The camera-ready path implements:

- supervised segment BCE with logits;
- visual feature L2 alignment on the decision path;
- BEATs cosine alignment on the audio-auxiliary path;
- CLAP text alignment using `(cosine + 1) / 2` followed by probability BCE;
- squared cosine orthogonality between decision and audio-auxiliary features;
- zero visual-logit and audio-logit KD by default.

Disabled terms do not require tensors. Enabled terms fail immediately when their tensor or mask is absent. Synthetic audio logits are prohibited.

## Data integrity and determinism

Every relative manifest and artifact path is resolved against `data.path_root`, not the process working directory. Reproduction configs require visual inputs, audio inputs, strong visual features, weak audio features, and text embeddings. Missing required artifacts raise an error that includes the field and record id; permissive legacy configs retain zero-tensor behavior.

DataLoader workers seed NumPy and Python from PyTorch's worker seed. Train, validation, and test loaders receive seeded generators. Training seeds Python, NumPy, CPU CUDA RNGs and enables deterministic algorithms with warnings for unsupported operations.

## Full-run safety and scheduling

The paper reproduction config keeps `reproduction.full_run_blocked: true` and the paper scheduler as `UNRESOLVED`. Ordinary full training fails before data loading or model construction. A deliberate `--allow-blocked-reproduction` run writes `NON_CANONICAL_UNRESOLVED_RUN.txt`; R0 smoke/preflight uses a separate unblocked cosine configuration.

`max_batches_per_epoch` and `max_optimizer_steps` have distinct meanings. The old `--max-train-steps` flag remains a deprecated per-epoch-batch alias with an explicit warning. Scheduler construction supports cosine and step schedules without claiming either is the archived paper schedule.

## Evidence chain and evaluation

Runs save resolved configuration, runtime metadata, Git state, dependency freeze, manifest hashes, JSONL history, best and last checkpoints, validation/test prediction NPZ files, final metrics, and logs. Best checkpoint selection uses validation AP; final validation/test evaluation reloads `best.pt`.

Predictions retain sample id, query/category, seen/unseen type, segment index, label, logit, probability, and sample offsets. Metrics are reported for total, seen, and unseen groups. The best F1 threshold is selected only on the validation set and then applied unchanged to test.

Efficiency measurement synchronizes CUDA around warmup and timed inference. The report labels T=10 and T=16 separately and does not infer a resampling protocol.

## Audit and teacher identity

`audit_mm26_reproduction.py` validates split counts, ids, binary labels, segment alignment, path existence, metadata, finite numeric artifacts, exact exported dimensions, hashes, and split overlap. It returns a nonzero status for P0 errors. It reports the observed segment-length histogram and states that the dataset performs no T=10→T=16 resampling.

`inspect_teacher_identity.py` records wrapper/upstream classes, upstream Git SHA, checkpoint absolute paths and SHA256 values, checkpoint keys, dimensions, frame count, CLAP version, BEATs fine-tuning flag, and smoke-output statistics. It never guesses checkpoint locations or identities.

Teacher export writes only processed records when `limit` is set by default. Copying unprocessed records requires an explicit compatibility option.

## Archival blockers

The following remain `BLOCKED_ARCHIVAL_FACTS` and block a canonical full run:

1. Official T=10 labels versus the camera-ready table's 16 temporal segments.
2. Exact InternVideo2 model class and the three checkpoint identities.
3. Meaning, gamma, and interval of the step400 schedule and early-stop patience.
4. Student pretrained initialization and exact augmentation recipe.
5. Visual feature L2 sum-versus-mean reduction.
6. Paper additive fusion plus TransformerLayer versus the current concat-MLP fusion and validity-bit gate.

## Verification and deliverables

Verification is performed on the 5090 with a clean native Windows venv:

1. `python -m pip check`.
2. `python scripts/verify_cuda_runtime.py` with capability `(12, 0)` and finite FP16 matrix multiplication.
3. `python -m compileall -q src scripts tests`.
4. `python -m pytest -q`.
5. `python scripts/smoke_test.py`.
6. One mock forward/backward/resume/evaluation preflight using `configs/ov_orthkd_mm26_smoke.yaml`.
7. `git diff --check` and final repository-status review.

The final branch contains the requested source/config/test changes, `reports/R0_REPRO_HARDENING_REPORT.md`, retrieved CUDA/test/preflight evidence, and one clean commit named `repro: harden paper-faithful OV-OrthKD baseline`. The full local `扩刊` folder is then pushed to the corresponding GitHub repository without full data, checkpoints, venvs, or package caches.
