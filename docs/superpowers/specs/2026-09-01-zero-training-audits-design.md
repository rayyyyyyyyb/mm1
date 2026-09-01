# S7 Zero-Training Audit Design

## Scope and decision boundary

This phase adds a fail-closed diagnostic subsystem around the existing S7 artifacts. It does not alter the official `T_task=10` protocol, start formal Full training, change canonical defaults, or reinterpret the preregistered S7 result. The six audits are:

- A: test-specific label-count strata, mixed-only temporal shuffle, and within-video positive/negative concordance;
- B: raw-pixel, visual-backbone, and projected-visual temporal variation at a reconstructed zero-step state and steps 400/800/1200, plus official JPG content checks;
- C: checkpoint inference under forced visual/audio gate ratios without optimization;
- D: concat-fusion block norms and input Jacobians;
- E: deterministic same-query, different-query, and within-video temporal audio swaps;
- F: a one-batch Full projector gradient probe, with any optimizer step confined to a disposable in-memory clone.

S8 is conditionally authorized only after all A–F artifacts pass integrity audit. It remains blocked if official frames are content-identical/corrupt, the reconstructed zero-step identity cannot be supported by the stored step-zero receipt, any audit violates `T=10`, or the diagnostic artifacts are incomplete/non-finite. Otherwise the next single-variable control is S8: S7 identity passthrough plus `gate_mode=fixed_equal`.

## Considered approaches

### 1. Extend the model with explicit diagnostic controls — selected

Add an optional forward-only gate override and expose the already-computed visual-backbone tensor in the output mapping. Defaults preserve the existing path exactly. This keeps forced-gate inference on the production forward path, respects validity masks, and avoids duplicating fusion logic in an external script. Tests must prove default outputs/state keys remain unchanged and literal ratios are applied only when requested.

### 2. Monkey-patch PyTorch modules with hooks

Forward hooks could replace gate logits and capture backbone features without source changes. This is rejected because extreme ratios require numerical approximations, hook lifetime is easy to leak across modes, and a hook can silently bypass validity-mask semantics.

### 3. Reimplement downstream fusion in the audit script

Caching projected tokens and replaying fusion would reduce GPU time. This is rejected for the first evidence run because duplicated model logic can drift from the checkpoint path and would weaken the evidentiary value. The direct path is slower but easier to audit.

## Components

### Pure diagnostic core

`src/utils/zero_training_diagnostics.py` owns deterministic, unit-testable calculations that do not load a model or write files:

- strict prediction-schema validation for ten ordered task segments;
- label-count strata and valid metric semantics;
- mixed-only probability/logit shuffle distributions;
- pair-weighted and video-macro concordance;
- deterministic same-query and different-query donor maps;
- tensor temporal-variation accumulators;
- concat-fusion block-norm and gradient-norm summaries.

Single-class strata never report a fabricated AUROC. They report `auroc=null` with an explicit reason, score distribution, positive rate, and thresholded prediction rate. Mixed-label is the only boundary-localization stratum.

### Student zero-training runtime

`scripts/diagnose_s7_zero_training.py` binds exact S7 config/checkpoints and performs A–E. It reconstructs step zero with the stored seed and builder, labels it `reconstructed_zero_step`, and checks its segment-head receipt against the existing `global_step_before_update=0` training diagnostic before using it. It never calls an optimizer.

The visual timeline records normalized input pixels, visual-backbone outputs, projected visual tokens, gates, logits, and exact shapes. The official-JPG audit covers the complete test split, records aggregate duplicate/pixel-difference statistics and a canonical digest over every per-frame SHA, while retaining the ten literal hashes for deterministic example videos in the compact report.

Forced gate ratios are `(0,1)`, `(0.25,0.75)`, `(0.5,0.5)`, `(0.75,0.25)`, and `(1,0)`. Each ratio runs original and visual-zero inputs at the S7 best checkpoint. Audio interventions use deterministic bijective donor maps where possible and preserve labels, query, position, frames, and masks; the report states coverage and rejects same-ID donors or a same-query violation.

### Full projector probe

`scripts/diagnose_full_projector_probe.py` loads the completed canonical Full checkpoint and one deterministic real training batch. It computes strong-feature mean/sum loss and gradient receipts without updating the loaded model. A separate cloned projector plus cloned student-decision tensor receives exactly one AdamW step at the resolved LR; the process then exits and no updated checkpoint is written. The report hashes projector state before/after, measures target variance movement, and labels this section `near_zero_training_disposable_clone`.

### Independent artifact audit

`scripts/audit_zero_training_evidence.py` independently reloads the compact A–F JSON artifacts and source receipts. It recomputes key A metrics from the S7 prediction NPZ, verifies checkpoint/config/source hashes, exact gate grid, `T=10`, donor-map invariants, finite values, zero-step provenance, and the disposable-clone boundary. It emits PASS only for artifact integrity; scientific findings remain descriptive.

## Data flow and filesystem policy

Source code and compact reports live in the local `扩刊/OV-OrthKD-R2` worktree and are pushed to GitHub. Checkpoints, prediction NPZs, official JPG/WAV files, caches, and large raw audit streams remain on the 5090. Runtime outputs use a new noncanonical diagnostic directory and atomic `.tmp` replacement. Existing S7 artifacts are read-only and outputs refuse overwrite.

The remote run is launched as a persistent monitored process. A source commit, config hash, checkpoint hashes, environment receipt, and upstream S7 audit hashes are bound before GPU work begins. An interruption may resume only at phase boundaries with already-PASS phase artifacts; no partial JSON is treated as evidence.

## Error handling

Every audit fails closed on malformed offsets, segment counts other than ten, missing or duplicated source files, non-finite metrics, checkpoint/config mismatch, dirty source worktree, invalid gate ratios, impossible donor pairing, missing zero-step provenance, output collision, or an optimizer mutation outside the disposable clone. Single-class metric undefinedness is represented explicitly rather than raised as a scientific failure.

## Verification

Implementation follows red-green TDD for every new pure function and model diagnostic control. Verification consists of focused unit tests, complete repository pytest in the locked 5090 environment, `compileall`, Ruff on changed Python, PowerShell parser checks for launch/query/resume scripts, source/hash audits before and after execution, JSON schema/invariant recomputation, link checks, forbidden-large-file scan, secret scan, clean git status, and local/upstream/remote SHA equality.

## Expected interpretation

A–F can distinguish data/input collapse, random or trained visual-backbone collapse, projection collapse, learned-gate starvation, concat-fusion suppression, audio category versus temporal dependence, and moving projector targets. These audits do not by themselves claim paper-level reproduction. If their integrity gate passes and no data/zero-step blocker is found, S8 supplies the missing identity×fixed-gate cell; S9 and any frozen-projector experiment remain separate later decisions.
