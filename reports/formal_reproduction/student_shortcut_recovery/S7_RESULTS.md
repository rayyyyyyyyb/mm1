# S7 temporal-identity diagnostic results

Date: 2026-09-01

Status: **completed and independently audited; the approved causal gate failed, so formal Full reproduction remains paused.**

S7 is a noncanonical, single-variable Student-only control. Relative to the locked three-epoch S0 configuration, its only normalized scientific change is:

```text
student.temporal_path_mode: transformer -> identity_passthrough
```

The identity path sets `shared_features = fused_tokens_before_position + position_embedding`. The original temporal encoder is still instantiated in its original order so state-dict keys, parameter identity and construction-time RNG consumption remain stable, but it is not executed. All data, initialization, optimizer, exposure, augmentation, loss weights, evaluator and `T_task=10` settings remain locked to S0. Observation-only checkpoints were emitted at global steps 400, 800 and 1200.

## Result in one sentence

Removing the temporal Transformer improves global AP and AUROC modestly, but the model remains essentially blind to visual content and fails the pre-approved temporal/content-dependence gates at both early checkpoints; therefore the evidence does **not** identify the temporal Transformer as the major source of collapse.

## Best-checkpoint metrics

The validation-AP-selected checkpoint is step 1200.

| Run | Test AP | AUROC | OV-AVEL segment F1@0.5 | Predicted-positive rate@0.5 |
|---|---:|---:|---:|---:|
| S0 | 0.748745 | 0.636135 | 0.540393 | 1.000000 |
| S7 | 0.758605 | 0.669173 | 0.530286 | 0.584089 |
| S7 - S0 | +0.009861 | +0.033038 | -0.010107 | -0.415911 |

S7 also passes the three pre-declared “stronger recovery at best” checks: predicted-positive rate is below 0.98, mean-centered AP is `0.646228` versus S0 `0.637636`, and per-query macro AP is `0.655878` versus S0 `0.624370`. These improvements are real but are insufficient to establish healthy audiovisual temporal localization.

## Pre-approved causal decision

The decisive criteria had to hold at **both** steps 400 and 800: positive-label mean logit above negative-label mean logit, shuffle AP drop at least 0.02, both-zero AP drop at least 0.03, within-sample logit standard deviation at least 0.01, and shared-to-decision/logit compression below 100.

| Quantity | Step 400 | Step 800 | Required |
|---|---:|---:|---:|
| Positive - negative mean logit | +0.493618 | +0.657539 | > 0 |
| Within-sample logit std | 0.086974 | 0.206778 | >= 0.01 |
| Shuffle AP drop | 0.005508 | 0.010488 | >= 0.02 |
| Both-zero AP drop | 0.010096 | 0.003133 | >= 0.03 |
| Shared-to-decision compression | 1.945 | 2.479 | < 100 |
| Shared-to-logit compression | 1.324 | 0.702 | < 100 |
| Supports temporal encoder as major cause | **No** | **No** | Both must be Yes |

The independent auditor recomputed the decision as:

- `step_400_supports_shared_encoder_major_cause=false`;
- `step_800_supports_shared_encoder_major_cause=false`;
- `simultaneous_step_400_and_800_support=false`.

At step 400, shuffle AP drops by only `0.005508`, and both-zero inference retains `98.66%` of original AP. Both are explicit failure signals from the approved plan.

## Best-checkpoint content dependence

At step 1200:

| Mode | AP | Change from original | Predicted-positive rate@0.5 |
|---|---:|---:|---:|
| Original | 0.758605 | - | 0.584089 |
| Visual zero | 0.758605 | -0.00000008 | 0.584089 |
| Audio zero | 0.733598 | -0.025007 | 0.011512 |
| Both zero | 0.733402 | -0.025203 | 0.011512 |
| 100 within-sample shuffles, mean | 0.753572 | -0.005033 | n/a |

Visual removal is numerically irrelevant. Audio removal explains essentially the entire content-dependent AP change, while both-zero still falls short of the required 0.03 drop and temporal shuffling has only a small effect. Training diagnostics agree: the step-800 mean visual/audio gates are `0.001115/0.998885`, visual encoder gradient norm is `1.96e-5`, and audio encoder gradient norm is `0.412243`.

This narrows the diagnosis: bypassing the temporal Transformer removes one compression mechanism and improves ranking, but it does not restore audiovisual dependence. The remaining shortcut is already established before or around fusion/decision formation and is strongly audio dominated. S7 does not prove that the Transformer is harmless in the canonical model; it proves only that removing it alone is not a sufficient recovery and does not meet the plan's causal standard.

## Integrity and reproducibility evidence

- Scientific runtime commit: `a7f0dc06d6a98493c0d03f1caa2059e31c50b648`.
- Canonical-LF S7 config SHA256: `26e3f21504d7ce3f9a5498b8c89073fc910db80cbdf058c4b6a397b8735518b6`.
- Exact detached 5090 candidate: clean before and after execution.
- Candidate gate: compileall exit 0; full suite `477 passed in 354.75s`, pytest exit 0.
- Candidate verification receipt SHA256: `ce10e08506e7382bedfc16442c4d46f30834b2f20b0b90d54148100193ae7cf9`.
- Training worker: completed at step 1200 with exit 0.
- Training artifact audit: PASS, SHA256 `6583c7f403041be961bba5a40dd7f7e4c8f8d38fd1fee2c7548396b5b6e30dc2`.
- Trajectory result: 45,552 bytes, SHA256 `74fd36bafd08d0d30e0e165c886e02b84fa94ac092b359399714d71e360be992`.
- Independent posthoc audit: PASS, SHA256 `1207c255ccbd918cb5c2899f7da929170c8020f63becd7548e29c473f9671956`.
- Test evidence contains 5,820 samples and 58,200 ordered task segments, exactly ten per sample.
- All 48 temporal-encoder tensors are byte-identical across steps 400/800/1200, as required for a bypassed module; the active segment head changed.

Primary small evidence:

1. [Checkpoint trajectory and causal decision](evidence/s7/posthoc/s7_checkpoint_trajectory.json)
2. [Independent posthoc artifact audit](evidence/s7/posthoc/s7_posthoc_artifact_audit.json)
3. [Training artifact audit](evidence/s7/control/s7_training_artifact_audit.json)
4. [Final metrics](evidence/s7/training/final_metrics.json)
5. [Three-epoch history](evidence/s7/training/history.jsonl)
6. [First-batch training diagnostics](evidence/s7/training/training_diagnostics.jsonl)
7. [Resolved configuration](evidence/s7/training/resolved_config.yaml)
8. [Exact candidate verification](evidence/s7/control/candidate_verification_receipt.json)

## Boundary and next decision

No S5, S6, Visual-only, formal Full, second seed or extended training was started. No canonical configuration, evaluator, teacher cache, data protocol or full-run guard was changed. The next intervention should be chosen only after reviewing the S7 evidence, with emphasis on the audio-saturated gate and the content-independent/query-position component that survives both-zero inference. S7 itself does not authorize a particular next experiment.
