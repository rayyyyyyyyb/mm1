# Student Shortcut Recovery Design

Date: 2026-08-31

Status: approved by the user's instruction to execute the reviewed web-diagnosis plan

## Purpose

Determine whether the current AP is primarily explained by query/sample priors instead of within-video temporal localization, then test the smallest high-priority recovery variable: real ImageNet-pretrained student backbones. This phase is diagnostic. It does not recover an archival fact, alter the official temporal protocol, or authorize a formal Full run.

## Fixed scientific boundary

- Preserve the official `T_task=10` ordered one-second segments for labels, logits and metrics.
- Preserve `T_max=16` only as positional capacity.
- Do not interpolate, duplicate, resample or relabel 10 segments into 16.
- Do not modify teacher caches, the evaluator, seed 42, fusion modes or target-projector policy in S3.
- Do not start a formal Full run.

## A0 prediction-only shortcut diagnostics

The prediction-only tool consumes the exact training JSONL plus saved validation/test prediction NPZ files. It does not load images, audio, a checkpoint or a GPU.

Every input is fail-closed: the manifest must contain a non-empty query and exactly 10 binary `segment_labels`; each prediction sample must contain exactly the ordered indices `0..9`; all scores must be finite; ids and queries must align at sample granularity.

The tool computes these controls:

1. **Query-only prior.** For a query seen in training, every segment receives the empirical training probability `positive_segments / valid_segments` for that query. An evaluation query absent from training receives the global training positive rate. The report records known and fallback sample counts.
2. **Query-plus-position prior.** A known `(query, position)` receives its empirical training probability. If the query is absent, the corresponding global per-position training probability is used. The report records fallback counts. No smoothing is applied; this is the literal empirical prior requested by the diagnosis.
3. **Mean-centered student score.** Subtract each sample's mean logit from its ten logits, apply sigmoid, and recompute global segment-micro AP. This removes the sample-level offset while retaining within-sample ordering.
4. **Within-sample temporal shuffle.** Keep labels fixed and independently permute the ten student logits inside every sample. Run 100 deterministic repetitions with seed 42 and report mean, standard deviation, quantiles and the delta from unshuffled AP.

The report labels all AP values as diagnostic global segment-micro AP, hashes every source, and never presents a prior or transformed score as an official model result.

## A0 checkpoint modality diagnostics

The checkpoint tool reconstructs the model and official loaders from the source resolved config, loads the checkpoint state dict, and evaluates four inference modes:

- `original`;
- `visual_zero`;
- `audio_zero`;
- `both_zero`.

Zeroing means replacing the selected input content tensor with zeros while preserving `frame_valid`, `audio_valid` and `sequence_mask`. This isolates content dependence without conflating it with missing-modality gate behavior. It is explicitly not a robustness benchmark.

For each mode the tool validates `[B,10]` labels/logits and records global AP/AUROC, official thresholded metrics, predicted-positive rate and within-sample logit variance. For the original mode it also summarizes the actual forward outputs `query_features`, `visual_tokens`, `audio_tokens`, `fused_tokens_before_position`, `shared_features`, `decision_features` and `segment_logits` using valid-row count, absolute mean, RMS, per-row L2 norm and mean within-sample temporal standard deviation. Missing or non-finite required tensors fail the run.

Checkpoint loading is diagnostic and receipts the checkpoint bytes/SHA256, source config bytes/SHA256, model state loading result, Git HEAD/dirty state and exact zeroing semantics. It does not use `allow_incompatible_resume` to turn a mismatched formal run into a canonical claim.

## Real A0 matrix and gate

Run A0 against the completed Student-only, Visual-only, canonical Full diagnostic source, and S0 checkpoints/predictions where their exact assets exist. Absence of an asset is reported as `UNAVAILABLE` with the expected path; it is never silently substituted.

Do not interpret pooled AP alone as localization. The recovery gate requires materially non-zero within-video variation and sensitivity to content/temporal order. Query priors that approach model AP, little AP loss after shuffle, or little change under both-zero inference confirm shortcut dependence.

## S3 single-variable run

S3 derives from the valid S0 Student-only control and changes only:

- `reproduction.variant` and `logging.log_dir` as identity/output fields;
- `student.pretrained: false -> true` as the sole scientific variable.

All other data, augmentation, optimizer, scheduler, batch, exposure, model, loss and temporal fields remain byte-value equivalent after normalization. S3 remains `claim_level=noncanonical_diagnostic`, runs seed 42 for three epochs at 400 batches per epoch, and uses the existing `T_max=30` scheduler prefix.

Before training, produce a pretrained-backbone receipt that proves `pretrained=True` reached both `timm.create_model` calls, records each resolved timm pretrained configuration and hashes the constructed encoder state. A same-seed `pretrained=False` comparison must produce a different encoder-state hash. A download/construction failure blocks S3 instead of falling back to random initialization.

S3 is useful only if its temporal and modality diagnostics improve, not merely if pooled AP changes. S4/S5/S6 remain pending until S3 is audited.

## Artifact policy

The 5090 retains datasets, caches, checkpoints, prediction NPZ files and progress logs. Git receives source, tests, diagnostic configs, design/plan documents, small JSON receipts and reports only. All actions and results are appended in order to both required `all.md` ledgers.

## Independent review

After each implementation group, rerun its focused tests. Before any result claim, perform a fresh line-by-line review of manifest fallback logic, sample boundaries, shuffle direction, zeroing semantics, validity masking, metric inputs, state loading, single-variable config differences and temporal guards. Then run `compileall`, `git diff --check`, focused tests and the complete pytest suite on an exact clean 5090 commit.
