# Static-target 800-applied-step control

## Preregistration

C0 and C1 use the same seed-42 Visual-only `sum_feature_then_masked_mean_segments`
configuration, official `T=10` segments, batch size 4, and no test evaluation.
The sole scientific difference is the strong teacher projector update mode:

| control | strong projector | weak/text projectors | budget |
|---|---|---|---:|
| C0 | `trainable` | `trainable` | 800 applied updates |
| C1 | `static_zero_lr_keep_grad` | `trainable` | 800 applied updates |

## C0 (observed)

- Receipts: 805 attempts, 800 applied, 5 AMP overflows.
- First completed validation (global step 395): AP `0.7417794173`, AUROC
  `0.6437222374`; predicted-positive rate at threshold 0.5: `1.0`.
- Second completed validation (global step 795): AP `0.7195224277`, AUROC
  `0.6188235417`; predicted-positive rate remains `1.0`.
- Third completed validation (global step 800): AP `0.7213457392`, AUROC
  `0.6199481023`; predicted-positive rate remains `1.0`. It did not improve
  the epoch-0 best checkpoint. The post-loop `final_metrics.json` was written
  with the epoch-0 best validation metrics and no test artifact. The expected
  `optimizer_step_summary.json` is absent from the C0 directory; applied-step
  counts are therefore taken from the complete JSONL receipts and this missing
  summary is retained as a runtime-integrity caveat.

## C1 (observed)

- Receipts: 805 attempts, 800 applied, 5 AMP overflows; the separate summary and
  complete JSONL receipt set agree. All 800 applied rows were globally clipped.
- Best validation checkpoint is epoch 1 / global step 795: AP `0.7366111005`,
  AUROC `0.6349032370`; predicted-positive rate remains `1.0`. The final step-
  800 validation row is AP `0.7323133188`, AUROC `0.6242927241`. No test
  evaluation or test artifact was produced.
- On the fixed mixed-label validation subset, C1 pair-weighted concordance is
  `0.5588235294` versus C0 `0.6098020865` (gain `-0.0509785576`).

## Read-only geometry audit

The validation geometry receipts use 1,967 mixed-label videos and 19,670
official task segments. At C1 best, the projected strong-teacher target has
within-sample temporal standard deviation `0.1682058886` and its hash is
unchanged from initialization. The student decision representation has temporal
standard deviation `0.0013909233`, centered-to-total row-L2 ratio
`0.0036688604`, and projected-to-decision distance correlation `0.3277767299`.
The corresponding C1 last-state values are `0.1682058886`, `0.0011678901`,
`0.0030746154`, and `0.3419778306`. The raw and projected teacher tensors
remain temporally informative while the student decision remains near-collapsed.
The full JSON receipts are `raw_teacher_geometry_c0_validation.json` and
`raw_teacher_geometry_c1_validation.json`.

## Preregistered nine-gate result

| gate | value | threshold | result |
|---|---:|---:|---|
| strong projector hash unchanged | `true` | exact unchanged | PASS |
| projected-target temporal std | `0.1682058886` | >= 0.15 | PASS |
| decision temporal std | `0.0013909233` | >= 0.003 | FAIL |
| projected-to-decision distance correlation | `0.3277767299` | >= 0.20 | PASS |
| decision centered/total row-L2 ratio | `0.0036688604` | >= 0.005 | FAIL |
| mixed validation concordance gain over C0 | `-0.0509785576` | >= 0.02 | FAIL |
| C1 AP minus C0 AP | `-0.0051683168` | >= -0.02 | PASS |
| unexplained AMP skips | `0` | == 0 | PASS |
| clip receipts complete | `true` | complete | PASS |

The static-target mechanism therefore does **not** pass the preregistered
gates. The preserved projected target together with dominant strong-projector
gradient share (mean `0.811494`, median `0.819354`) and universal clipping is
consistent with a remaining gradient-conflict bottleneck. This is a diagnostic
failure, not evidence that the projector alone is causal. Formal Full,
additional schedule extension, and test evaluation remain blocked.
