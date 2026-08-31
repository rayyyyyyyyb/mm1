# A0 shortcut-localization results

Date: 2026-08-31

Status: `PASS — SHORTCUT/COLLAPSE CONFIRMED`

Runtime: exact clean `f739399463c082cd670dff56e43c710d4fa6f283` on the RTX 5090. This is observation-only diagnostics over existing checkpoints; no parameters were updated.

## Artifact gate

The aggregate audit passed with exit 0 and zero stderr. Its SHA256 is `396311d0b0031695c4e80e1cda00eb8100cdfec03fd860b0bd7cba064a59db6b`. It binds all four source checkpoints/configs/prediction arrays, strict checkpoint loading, exact clean Git, official `T_task=10` sample ordering and saved-versus-rerun AP agreement within `1e-12`.

The aggregate receipt is in [`evidence/locks/a0_artifact_audit.json`](evidence/locks/a0_artifact_audit.json); the eight small per-checkpoint reports are under [`evidence/a0`](evidence/a0).

## Prediction-only controls

| Checkpoint | Original AP | Query-only AP | Query+position AP | Per-sample centered AP | 100× within-sample shuffle AP |
|---|---:|---:|---:|---:|---:|
| Student | 0.748745 | 0.693985 | 0.719324 | 0.637636 | 0.746699 |
| Visual-only | 0.725309 | 0.693985 | 0.719324 | 0.583850 | 0.725726 |
| Full | 0.741946 | 0.693985 | 0.719324 | 0.659784 | 0.741685 |
| S0 | 0.748745 | 0.693985 | 0.719324 | 0.637636 | 0.746699 |

Within-sample temporal shuffling changes AP by only about `-0.00205`, `+0.00042`, `-0.00026` and `-0.00205`, respectively. Much of the ranking therefore survives after destroying the association between each segment's logit and its temporal position. Query/position priors alone are also unusually strong.

## Checkpoint content ablations

| Checkpoint | Original AP | Visual zero | Audio zero | Both zero | Both-zero/original |
|---|---:|---:|---:|---:|---:|
| Student | 0.748745 | 0.747909 | 0.744467 | 0.743670 | 99.322% |
| Visual-only | 0.725309 | 0.725700 | 0.725335 | 0.725416 | 100.015% |
| Full | 0.741946 | 0.741535 | 0.737867 | 0.735515 | 99.133% |
| S0 | 0.748745 | 0.747909 | 0.744467 | 0.743670 | 99.322% |

Only frame/spectrogram content is zeroed; `frame_valid`, `audio_valid` and `sequence_mask` remain unchanged. Because almost all AP survives even when both modalities contain no content, the result cannot be explained by ordinary content-dependent recognition.

## Where temporal variation disappears

Mean within-sample temporal standard deviation over valid test segments:

| Checkpoint | Visual tokens | Audio tokens | Fused before position | Shared | Decision | Query features | Logits |
|---|---:|---:|---:|---:|---:|---:|---:|
| Student | 0.011248 | 0.213766 | 0.087404 | 0.006602 | 0.002481 | 0.005293 | 0.003236 |
| Visual-only | 0.011550 | 0.456112 | 0.006174 | 0.000083 | 0.000006 | 0.000016 | 0.000003 |
| Full | 0.059558 | 0.266880 | 0.072528 | 0.001830 | 0.000289 | 0.000484 | 0.001085 |
| S0 | 0.011248 | 0.213766 | 0.087404 | 0.006602 | 0.002481 | 0.005293 | 0.003236 |

The encoders and pre-position fusion retain nontrivial temporal variation. The large contraction appears in the shared/decision path, especially for Visual-only. `query_features` means `query_proj(shared_features)`, not a raw text/query token.

## Decision

A0 rejects the hypothesis that the AP gap is merely seed noise or a global evaluator shift. It supports a concrete failure mode: the student learns a query/position-dominated solution while the shared temporal representation suppresses content variation. This evidence authorizes only the already planned S3 single-variable pretrained-backbone control. It does not authorize formal Full training or S4/S5/S6 changes.
