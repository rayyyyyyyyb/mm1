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
- Final third-epoch validation and clean summary are still pending at report
  initialization; no test artifact has been created.

## C1

Pending C0 clean exit. Results and the nine preregistered gates will be appended
only from remote receipts/checkpoints; missing measurements remain failed/unknown
and will not be guessed.
