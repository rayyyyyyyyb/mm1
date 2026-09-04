# Static-target coupling control: final audit

Date: 2026-09-05
Claim level: `noncanonical_diagnostic`
Run: C2 `static_zero_lr_keep_grad` + `optimizer_groups_with_positive_lr`, seed 42, exactly 800 applied updates

## Decision

**Final state: `STATIC_TARGET_NOT_SUFFICIENT`.**

The C2 control removed the zero-learning-rate strong projector from the global
clipping norm and passed the ten-step equivalence check against the
`frozen_no_grad` target path. It therefore isolates the observed global-clip
coupling without changing the student trajectory in the equivalence window.
However, the full 800-applied-step validation control did not recover the
pre-registered student temporal-geometry or mixed-label concordance gates.
The result does not support `CLIP_COUPLING_CAUSAL` and does not identify an
intrinsic same-parameter loss conflict.

## C2 runtime and metrics

| Quantity | C2 best (global step 795) | C2 last (global step 800) |
|---|---:|---:|
| validation AP | 0.7336090805290894 | 0.7291997990871013 |
| validation AUROC | 0.6348366790117872 | 0.6266441093793944 |
| predicted-positive rate | 1.0 | 1.0 |
| segment F1@0.5 | 0.5377574807678815 | 0.5377574807678815 |
| event F1@0.5 | 0.5770955501897206 | 0.5770955501897206 |

The best C2 mixed-label pair-weighted concordance is `0.5093313881472102`
(video-macro `0.5087684896022466`) over 1,967 mixed-label samples and
36,329 mixed pairs. Relative to C0 best (`0.6098020864873792`), the gain is
`-0.100470698340169`; relative to C1 best (`0.5588235294117647`), it is
`-0.0494921413645545`. The C2 AP difference from C0 best is
`-0.0081703367945467`, which is within the `-0.02` AP tolerance, but the
concordance gate fails. Within-sample temporal shuffling changes AP by only
`+0.00014010556799237683` and AUROC by `-0.00027319618381216326`.

The final remote receipt is `attempted_steps=805`, `applied_steps=800`, and
`overflow_or_skipped_steps=5`. Every applied row is clipped; all rows record
scope `optimizer_groups_with_positive_lr` and `clipping_parameter_count=607`.
The positive-scope pre-clip norm mean is `49.78200641411791` and the clip
coefficient mean is `0.020991220771963248`. The excluded static projector is
still present in receipts and contributes `0.8136400323403845` of reconstructed
all-gradient square mass, so global clipping coupling is directly observed,
but removing it did not recover the task signal.

## Geometry and gradient gates

The read-only C2 geometry report covers the official validation T=10 mixed
subset (`1967` samples / `19670` segments). The strong projected target remains
temporally varying (`within_sample_temporal_std_mean=0.16820588860646918`) and
its projector hash is unchanged. At the C2 best checkpoint:

- student decision temporal std: `0.001476752159028226` (gate `>=0.003`, **fail**);
- projected-to-decision distance correlation: `0.3539093182416516` (gate `>=0.20`, pass);
- decision centered-to-total L2 ratio: `0.0039245120277748525` (gate `>=0.005`, **fail**).

At C2 last these values are `0.0013139303403639055`,
`0.3510774481973461`, and `0.0034990050049795007`, respectively. The C2 A2
decomposition on the fixed 4-sample/40-row batch is normalized mean
`34.15927734375`, centered `8.037702178955078`, total `42.19697875976563`,
with identity residual `3.05e-05`; static-projector gradients remain nonzero.
C2 A3 classifies `GRADIENT_CONFLICT_NOT_YET_IDENTIFIED` (BCE–visual median
`0.013278636150062084`, text–visual median `-0.08586530014872551`).

## Integrity and scope

- The ten-step static clipping equivalence passed exactly: target, loss,
  pre/post-clip student gradients, and student parameter hashes matched for
  all ten steps; only projector receipts differed.
- C2 used the official T=10 validation protocol, no label interpolation or
  T=16 conversion, and no test data. No second seed, 3,200-step extension, or
  canonical Full run was started.
- Read-only C2 geometry audit status is `PASS`; it reported no student/loss
  state mutation and unchanged static projector hashes.

Compact receipts are retained under `phase_a/` on 5090 and summarized in
`projector_collapse_summary.json`. Large checkpoints, datasets, caches and
prediction archives remain on 5090 and are not committed.
