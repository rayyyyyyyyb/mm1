# S3 pretrained-only recovery result

Date: 2026-08-31

Status: **S3 REJECTED AS A SUFFICIENT RECOVERY; FORMAL FULL REMAINS PAUSED**

S3 is a noncanonical diagnostic, not a claim about the unavailable historical implementation. It changes only `student.pretrained: false -> true` relative to S0 after normalizing the run name and output directory. The official task timeline remains `T_task=10`; `T_max=16` is positional capacity only.

## Runtime identity and audit

- Scientific runtime commit: `a0aa4d7ad4b98455e26a2fe6ff2537a321293233` (exact and clean before/after).
- Seed/exposure: seed 42, 3 epochs, 400 batches per epoch, global step 1200.
- Real pretrained construction: visual and audio pretrained state hashes both differ from their same-seed random references.
- Official timm cache receipt: `edecae3ae9ba5fbc7102883d1c1d667df71810facb2731d2ec34503a81bca255`.
- Training artifact audit: PASS, SHA256 `5058f78a8a9dfef354158d956205987550e0a745b3fe3f8f3cb79d8de7edbf71`.
- Posthoc artifact audit: PASS, SHA256 `6dc432dfccf142ed80902328755402cd140170894be3a44c7130b8b93b69ee44`.
- Validation/test predictions contain 57,980/58,200 ordered task segments. Training AP, saved-NPZ AP and strict checkpoint-rerun AP agree within `1e-12`.

## Training trajectory

| End of epoch | Global step | Validation AP | Validation AUROC | Predicted positive rate at 0.5 | Saved best |
|---:|---:|---:|---:|---:|:---:|
| 1 | 400 | 0.741581 | 0.643946 | 1.000 | yes |
| 2 | 800 | 0.657378 | 0.496680 | 1.000 | no |
| 3 | 1200 | 0.655598 | 0.535014 | 1.000 | no |

Pretraining produces a real but transient early effect. At the first batch after step 400, within-sample logit standard deviation is `0.186587` and positive/negative logit means are `0.912720/0.565430`. By the first batch after step 800, the same quantities collapse to `0.002026` and `0.415410/0.416618`; the visual gate mean is `0.00705`, gate saturation is `1.0`, and visual/audio encoder gradient norms are `6.88e-6/0.011588`.

## Best-checkpoint test result

| Run | AP | AUROC | OV-AVEBench segment F1@0.5 |
|---|---:|---:|---:|
| Paper Student-only | 0.714 | 0.612 | 0.523 |
| S0 reconstructed Student-only | 0.748745 | 0.636135 | 0.540393 |
| S3 pretrained-only | 0.745689 | 0.652332 | 0.540393 |
| S3 minus S0 | -0.003056 | +0.016197 | 0.000000 |

The S3 AUROC increase does not constitute recovery: at the paper threshold 0.5 every test segment is still predicted positive. At the validation-selected threshold, the predicted-positive rate is still `0.987337`.

## Shortcut and content-dependence tests

| Test metric | S0 | S3 | Interpretation |
|---|---:|---:|---|
| Original global micro AP | 0.748745 | 0.745689 | no AP recovery |
| Query-only prior AP | 0.693985 | 0.693985 | high query-only floor |
| Query+position prior AP | 0.719324 | 0.719324 | close to the student |
| Mean-centered AP | 0.637636 | 0.617675 | S3 is worse by 0.019960 |
| 100-shuffle mean AP | 0.746699 | 0.742032 | S3 loses only 0.003657 |
| Per-query macro AP | 0.624370 | 0.612308 | S3 is worse by 0.012062 |
| Within-sample logit std | 0.003236 | 0.071926 | 22.23x larger, but not label-aligned enough |
| Visual-zero AP | 0.747909 | 0.745689 | S3 visual removal has no cost |
| Audio-zero AP | 0.744467 | 0.736304 | only a 0.009385 drop |
| Both-zero AP | 0.743670 | 0.736156 | retains 98.72% of S3 AP |

S3 therefore passes only the narrow “more temporal variation” check. It fails the substantive requirements that temporal order matter, content removal matter, calibration stop being nearly all-positive, and centered/per-query localization improve together.

## Where the temporal variation resides

Mean within-sample temporal standard deviation on the full test split:

| Forward path | S0 | S3 |
|---|---:|---:|
| visual projected tokens | 0.011248 | 0.0000309 |
| audio projected tokens | 0.213766 | 0.309949 |
| fused tokens before position | 0.087404 | 0.173310 |
| shared features | 0.006602 | 0.153350 |
| decision features | 0.002481 | 0.070296 |
| post-fusion `query_features` | 0.005293 | 0.086305 |
| segment logits | 0.003236 | 0.071926 |

The recovered variation is overwhelmingly audio-driven. The effective visual token path is nearly temporally constant, visual-zero inference is numerically unchanged, and removing audio reduces within-sample logit std to `1.60e-6`. Yet removing both contents still leaves AP `0.736156`, so query/sample/position offsets continue to dominate the global ranking.

## Recovery gate

| Required Student-only condition | S3 outcome |
|---|---|
| At least one-order temporal-std increase | PASS (22.23x at the best checkpoint) |
| Stable positive-segment score above negative-segment score | FAIL (early separation reverses by step 800) |
| Clear AP/F1 loss under temporal shuffle | FAIL (AP drop 0.003657; F1 remains all-positive) |
| Clear loss when both modalities are zeroed | FAIL (only 1.28% AP loss) |
| Predicted-positive rate no longer near one | FAIL (1.000 at 0.5) |
| Centered and per-query metrics improve with global AP | FAIL (both decline versus S0) |
| Best selection no longer rewards an early offset solution | FAIL (best remains epoch 1) |

## Decision and remaining work

Do not enable student pretraining in the canonical configuration: archival evidence still locks `pretrained=false`, and this diagnostic does not justify overriding it. Do not start Visual-only, Full, S4, S5 or S6 in this stage.

The next single-variable experiment in the reviewed plan is S4, derived from S0 with training augmentation disabled and pretraining kept false. If separately authorized, S5 should then test clip-consistent augmentation, followed by schedule/exposure controls S6a/S6b/S6c. The visual projected-token collapse and the early-epoch selection failure must remain explicit diagnostic targets.

Evidence: [training artifacts](evidence/s3), [posthoc artifacts](evidence/s3/posthoc), [A0 baseline](A0_RESULTS.md), and [implementation audit](IMPLEMENTATION_AUDIT.md).
