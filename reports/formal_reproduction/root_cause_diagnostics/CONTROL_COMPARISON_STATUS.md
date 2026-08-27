# Current-pipeline control comparison

## Completion state

Both same-pipeline controls completed normally on the RTX 5090 from exact diagnostic commit `c5c50361f549c84cb0a934955ac504137977003d`:

- Student-only config SHA256: `4664f9e4ba6da82f2ea2d901271d7a7b856dbc6d33c9b7726425da3f8f169659`.
- Visual-only config SHA256: `053cfc863beaecb4113470a65449b78e8ee81d089b41dcf1c94e500af8f3ed0c`.
- Each ran 30 epochs and 12,000 optimizer steps and exited with code `0`.
- No diagnostic process remains; the RTX 5090 returned to idle.

## Best-checkpoint test comparison

| Run | AP | AUROC | segment F1@0.5 | calibrated segment F1 | predicted-positive rate |
|---|---:|---:|---:|---:|---:|
| Paper Student-only | 0.714000 | 0.612000 | 0.523000 | — | — |
| Current Student-only | **0.748745** | **0.636135** | 0.540393 | 0.545042 | 0.987371 |
| Paper Visual-only | 0.778000 | 0.701000 | 0.568000 | — | — |
| Current Visual-only | 0.725309 | 0.617160 | 0.540393 | **0.548733** | 0.990893 |
| Current Full | 0.741946 | 0.633875 | 0.540393 | 0.544939 | 0.987251 |
| Paper Full | 0.816000 | 0.750000 | 0.596000 | — | — |

Current Visual-only misses its paper row by `-0.052691 AP`, `-0.083840 AUROC`, and `-0.027607 F1@0.5`. It is also below current Student-only by `-0.023435 AP` and `-0.018975 AUROC`, and below current Full by `-0.016637 AP` and `-0.016715 AUROC`. Its small calibrated-F1 advantage does not compensate for the ranking loss or near-all-positive prediction.

Visual-only generalization is especially weak on unseen categories: seen/unseen test AP is `0.760851/0.711105`, while AUROC is `0.706209/0.577494`.

## Optimization trajectory

Visual-only best validation AP `0.727597` occurred at epoch 5 / step 2,000. Validation predicted-positive rate was exactly `1.0` for the sampled epoch records, and final-epoch validation AP/AUROC fell to `0.701202/0.607955`.

| Visual-only diagnostic batch | within-sample logit std | visual gate mean | gate entropy | gate saturation | visual encoder grad | audio encoder grad |
|---|---:|---:|---:|---:|---:|---:|
| epoch 1, batch 1 | 0.121423 | 0.477567 | 0.691656 | 0.000 | 5.471938 | 8.221914 |
| epoch 2, batch 1 | 0.093889 | 0.091324 | 0.208588 | 0.750 | 0.000234 | 0.384432 |
| epoch 3, batch 1 | 0.004494 | 0.999887 | 0.000919 | 1.000 | 8.29e-6 | 2.81e-11 |

The gate first saturates toward audio and then flips to virtually pure visual. In both directions the excluded encoder loses nearly all gradient. The best-checkpoint full-test prediction audit shows mean within-video T=10 logit standard deviation `3.19e-6`, compared with `0.003236` for current Student-only and about `0.001085` for current Full.

## Degenerate feature-distillation evidence

The strong-feature loss drops from `0.061268` at epoch 1 to `0.008183` at epoch 2, `0.002404` at epoch 3, and `0.0000324` at epoch 30, but ranking performance does not improve accordingly. During the first three diagnostic batches:

- student decision-feature variance falls `0.208858 → 0.003376 → 0.000375`;
- projected strong-teacher target variance falls `0.160833 → 0.005860 → 0.001864`;
- the trainable strong-teacher projector relative drift reaches `0.1066` and then `0.1315`;
- the trainable text projector relative drift reaches `0.1063` and then `0.1465`.

Code tracing confirms that the softmax modality gate multiplies visual/audio tokens before fusion, so saturation suppresses the corresponding encoder gradient. The optimizer jointly trains all student parameters and all loss-module teacher projectors. Therefore the current feature objective admits a low-variance solution in which both projected target and student decision representation move while the feature loss becomes tiny.

## Diagnostic conclusion

The completed controls rule out a globally broken dataset, T=10 protocol, evaluator, teacher cache, or student forward path: current Student-only already exceeds the paper Student-only row. They instead expose a shared training failure mode:

1. the learned modality gate rapidly saturates and cuts gradient to one modality;
2. temporal logits become nearly constant within every 10-second video;
3. trainable teacher projectors allow the feature target itself to collapse toward a low-variance solution;
4. Full/Visual distillation consequently provides no paper-level improvement over Student-only.

This is a localized failure mechanism, not yet proof of the exact archival conference implementation. No structural fix or new training sweep has been started. The next minimal causal test should change one variable only: bypass the learned gate with a fixed equal/additive fusion in Student-only while keeping every other config, seed, schedule, data, and evaluator field unchanged. A separate later test can freeze teacher projectors, but the two interventions must not be combined.

## Artifact locks

- Visual final metrics SHA256: `39e881c1a89457c6e3f0b8dcef6fec8830c4d175685a4c667a7d7ae0d9a2cb69`.
- Visual `best.pt`: 562,479,777 bytes, SHA256 `f27cde2b2ae179552b20d804af250c698aa2161eab08cfbc4e4cadadbd4158d1`.
- Visual `last.pt`: 562,479,777 bytes, SHA256 `9d17f00da9c5f4f1174ae37e08d42b58179c46226647c200172a59157fd33259`.
- Visual small-artifact archive: 2,169,822 bytes, SHA256 `0e07df03a9f46565a14a27bb19a8866ac255bef21de23805421b2ea0a941dcc1`.
- Prediction audit SHA256: `0afc8670faedb75411d71984c32544148f485cb09639f37d616d73e200e0f6eb`.
- Checkpoints remain only on the 5090. The 24-file small snapshot is local at `visual_only_completed_snapshot` and contains no `.pt` files.
