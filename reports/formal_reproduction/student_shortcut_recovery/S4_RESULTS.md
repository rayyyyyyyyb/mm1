# S4 no-augmentation control result

Date: 2026-08-31

Status: **S4 REJECTED; FORMAL FULL REMAINS PAUSED**

S4 is a noncanonical diagnosis, not a historical-implementation claim. Relative to the three-epoch S0 control, it changes only `data.train_augment: true -> false` after normalizing the run name and output directory. It keeps `student.pretrained=false`, seed 42, all model/loss/schedule settings, official `T_task=10`, and positional capacity `T_max=16` unchanged.

## Runtime identity and independent audits

- Scientific runtime commit: `74d211d34ace74ce3b74ea082a7dfd0379b251fb`; exact and clean before and after every runtime phase.
- Canonical-LF S4 config SHA256: `5b81218b55907a5dfb0419e62eff2128f0d08ce9301c97c081237f8c8f599b33`.
- Candidate verification: focused `5 passed`, compileall exit 0, full `461 passed in 335.90s`; receipt SHA256 `f5cba2ea8d7504717ca3bdf458eb633c178ba34f956f5162d5759f284665fcf3`.
- Exposure: seed 42, 3 epochs, 400 batches per epoch, global step 1200.
- Training artifact audit: PASS, SHA256 `6f28df765bd436cf38db8fe0a38a239ce3d967518a934d214ebeee5416faa962`.
- Posthoc artifact audit: PASS, SHA256 `1a9751cbafe3f8504105063150f33cc09214abafb7768e88a1ba4f5c765dfe80`.
- Validation/test predictions contain 57,980/58,200 ordered task segments. Training AP, saved-NPZ AP, and strict checkpoint-rerun AP agree within `1e-12`.

## Training trajectory

| End of epoch | Global step | Train loss | Validation AP | Validation AUROC | Positive rate at 0.5 | Saved best |
|---:|---:|---:|---:|---:|---:|:---:|
| 1 | 400 | 0.689495 | 0.626508 | 0.514623 | 1.000 | yes |
| 2 | 800 | 0.670335 | 0.706469 | 0.599306 | 1.000 | yes |
| 3 | 1200 | 0.671997 | 0.543707 | 0.388291 | 1.000 | no |

The second epoch is selected, but the third epoch deteriorates sharply. The validation-selected threshold is `0.637659`; it still predicts 99.98% of test segments positive.

## Best-checkpoint test result

| Run | AP | AUROC | OV-AVEBench segment F1@0.5 |
|---|---:|---:|---:|
| Paper Student-only | 0.714000 | 0.612000 | 0.523000 |
| S0 reconstructed Student-only | 0.748745 | 0.636135 | 0.540393 |
| S3 pretrained-only | 0.745689 | 0.652332 | 0.540393 |
| S4 augmentation disabled | 0.703470 | 0.596009 | 0.540393 |
| S4 minus S0 | -0.045274 | -0.040126 | 0.000000 |

S4 is materially worse than S0 in ranking metrics and remains the same all-positive solution at threshold 0.5. Disabling the existing spatial `RandomHorizontalFlip` and `ColorJitter` therefore does not recover temporal localization.

## Training-collapse evidence

| Diagnostic batch | Within-sample logit std | Positive/negative logit mean | Visual/audio gate mean | Gate saturation | Visual/audio encoder gradient L2 |
|---|---:|---:|---:|---:|---:|
| step 0 | 0.123199 | -0.019784 / 0.456902 | 0.477982 / 0.522018 | 0.000 | 5.6204 / 7.6994 |
| step 400 | 0.003316 | 0.694409 / 1.083545 | 0.002146 / 0.997854 | 1.000 | 2.24e-7 / 0.002410 |
| step 800 | 0.001080 | 0.569648 / 0.569889 | 0.000616 / 0.999384 | 1.000 | 1.41e-7 / 0.000172 |

At step 400, S0 still has visual/audio gate means `0.753337/0.246663`, within-sample logit std `0.010901`, and visual/audio encoder gradients `0.010065/0.185608`. S4 instead reaches a saturated audio gate and a nearly dead visual gradient sooner. This is direct evidence that disabling the present augmentation accelerates, rather than repairs, the collapse in this controlled run.

## Shortcut and content-dependence tests

| Test | S4 value | Interpretation |
|---|---:|---|
| Original global micro AP | 0.703470 | audited checkpoint result |
| Query-only prior AP | 0.693985 | high query-only floor |
| Query+position prior AP | 0.719324 | exceeds the trained student |
| Mean-centered AP | 0.581009 | loses 0.122461 after removing sample offsets |
| 100-shuffle mean AP | 0.704645 | shuffling improves AP by 0.001174 |
| Per-query macro AP | 0.590516 | below S0 and S3 |
| Within-sample logit std | 2.48e-5 | only 0.77% of S0 |
| Visual-zero AP | 0.703225 | effectively unchanged (-0.000246) |
| Audio-zero AP | 0.750441 | improves by 0.046970 |
| Both-zero AP | 0.749499 | improves by 0.046028 |

All four content-ablation modes predict every test segment positive at threshold 0.5. Zeroing both modalities retains 106.54% of original AP. The result does not merely show weak visual use: in this checkpoint, the learned audio content path actively worsens the global ranking relative to the content-free shortcut.

## Where the remaining temporal variation resides

Mean within-sample temporal standard deviation on the full test split:

| Forward path | S4 |
|---|---:|
| visual projected tokens | 0.0582410 |
| audio projected tokens | 0.5797599 |
| fused tokens before position | 0.2422580 |
| shared features | 0.0008737 |
| decision features | 0.0001060 |
| post-fusion `query_features` | 0.0005577 |
| segment logits | 0.0000248 |

The input encoders still produce temporal variation, particularly audio, but the shared/decision/head path compresses it by orders of magnitude. With audio zeroed, logit temporal std falls to `8.57e-8`; with both modalities zeroed, it is `8.33e-8`. The remaining AP is therefore carried by query/sample/position structure, not meaningful within-video content localization.

## Decision

Reject S4 as a recovery. Keep the canonical `data.train_augment=true`; this experiment shows only that disabling the current spatial augmentation is not a fix, not that augmentation is universally beneficial. It also does not test clip-consistent augmentation.

Do not start formal Full, Visual-only, S5, or S6 from this result. The next decision should be made from the combined S0/S3/S4 evidence: first repair or isolate the rapid gate/shared-path collapse under one bounded variable, then require content removal and temporal shuffle to cause a real loss before resuming formal reproduction.

Evidence: [S4 training artifacts](evidence/s4/training), [S4 posthoc artifacts](evidence/s4/posthoc), [S3 result](S3_RESULTS.md), [A0 baseline](A0_RESULTS.md), and [implementation audit](IMPLEMENTATION_AUDIT.md).
