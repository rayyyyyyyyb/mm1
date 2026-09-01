# S8 identity + fixed-equal-gate diagnostic results

Date: 2026-09-01

Status: **completed and independently audited; S8 matches evidence pattern 2, so no next experiment or formal Full reproduction is authorized.**

S8 is a noncanonical, single-variable Student-only control. Relative to the locked S7 configuration, its sole normalized scientific change is:

```text
student.gate_mode: learned_softmax -> fixed_equal
```

The student temporal path remains `identity_passthrough`; the visual/audio gates are literal `0.5/0.5` from initialization. Seed 42, random initialization, official `T_task=10`, `T_max=16` positional capacity, training augmentation, concat fusion, Student-only BCE, three epochs of 400 batches and checkpoints at steps 400/800/1200 are unchanged. No canonical loss, evaluator, data lock, teacher cache or full-run guard changed.

## Result in one sentence

Fixed-equal fusion prevents the visual representation and visual gradient collapse seen in S7, but zeroing visual content changes mixed-video AP by only `0.000632`; the recovered visual path is therefore not converted into useful label-aligned predictions, which matches the pre-approved pattern “visual tokens vary but visual-zero remains inert: concat MLP suppresses vision.”

## Best-checkpoint metrics

Validation AP selects step 1200.

| Run | Test AP | AUROC | Binary micro F1@0.5 | OV-AVEL segment F1@0.5 | OV-AVEL event F1@0.5 |
|---|---:|---:|---:|---:|---:|
| S0 | 0.748745 | 0.636135 | 0.761966 | 0.540393 | 0.577434 |
| S7 | 0.758605 | 0.669173 | 0.678173 | 0.530286 | 0.485278 |
| S8 | 0.769761 | 0.674486 | 0.687314 | 0.537494 | 0.502510 |
| S8 - S7 | +0.011156 | +0.005313 | +0.009140 | +0.007208 | +0.017232 |

Validation behavior across the three fixed 400-batch epochs was:

| Step | AP | AUROC | Binary micro F1@0.5 | Segment F1@0.5 | Event F1@0.5 |
|---:|---:|---:|---:|---:|---:|
| 400 | 0.747315 | 0.654823 | 0.745387 | 0.570721 | 0.557355 |
| 800 | 0.742466 | 0.638779 | 0.745057 | 0.547570 | 0.560506 |
| 1200 | 0.758385 | 0.664911 | 0.684879 | 0.532624 | 0.501779 |

This is a normal-range ranking improvement rather than a numerical failure, but AP/AUROC alone do not establish audiovisual localization.

## Visual representation and optimization recover

All measurements below use the same 5,820 official test samples and 58,200 ordered one-second task segments.

| State | Visual-backbone temporal std | Projected visual temporal std | Visual Jacobian L2 | Audio Jacobian L2 | Query Jacobian L2 |
|---|---:|---:|---:|---:|---:|
| reconstructed step 0 | 0.218586 | 0.066350 | 2.333746 | 2.522438 | 4.648380 |
| step 400 | 0.162155 | 0.093735 | 0.322289 | 0.408152 | 1.793753 |
| step 800 | 0.163354 | 0.082353 | 0.153023 | 0.255230 | 1.596726 |
| step 1200 | 0.138895 | 0.056053 | 0.274656 | 0.481062 | 2.847662 |

S7's step-1200 backbone/projected temporal standard deviations were only `0.003412/0.001051`; S8 retains roughly `40.7x/53.3x` more variation. S7's step-1200 visual Jacobian was `0.004885`; S8 raises it to `0.274656`, about `56.2x`. The first-batch visual-encoder gradient L2 at steps 0/400/800 is `2.584008/0.024794/0.041727`, instead of S7's near-zero step-800 value. The fixed gate and bypassed temporal encoder have exact zero gradients and remain byte-identical to reconstructed initialization at all audited checkpoints, while the active segment head changes.

The concat-fusion visual/audio/query input-block Frobenius norms at step 1200 are `6.621382/6.680113/7.040511`, so static column magnitude does not explain the missing visual contribution.

## Behavioral dependence remains audio dominated

The mixed-label stratum contains 1,941 videos and has positive-segment rate `0.571355`.

| Intervention | Mixed AP | AUROC | AP drop from original |
|---|---:|---:|---:|
| Original | 0.649065 | 0.603468 | 0 |
| Visual zero | 0.648434 | 0.604930 | 0.000632 |
| Audio zero | 0.618108 | 0.556101 | 0.030958 |
| Both zero | 0.617914 | 0.557368 | 0.031151 |
| 100 within-sample temporal shuffles | n/a | n/a | 0.034302 mean |

The original mixed pairwise concordance is `0.685425` pair-weighted and `0.691610` video-macro. Temporal shuffling also drops AUROC by `0.046604` on average. Audio therefore carries real temporal/content information, while the visual-zero AP change remains about 49 times smaller than the audio-zero change.

The key distinction from S7 is precise: the visual encoder is no longer collapsed or starved of gradient, and local logits have a nonzero visual Jacobian, yet the full-dataset ranking is nearly invariant to removing visual content. The evidence localizes the remaining failure to useful visual information being suppressed, cancelled or ignored during concat-fusion/decision formation; it does not justify claiming one exact downstream layer without another bounded intervention.

## Audit integrity and reader-fix recovery

- Scientific runtime commit: `60100c6fff95b313ae92bc91b10a3be7135dc437`.
- Canonical-LF S8 config SHA256: `9175ae127d602741f8e6357366b093dafec433d3a578d096be8d49ae2ad1c505`.
- Exact detached scientific candidate: clean before and after; compileall exit 0 and full suite `536 passed in 346.15s`.
- Training artifact audit: PASS, SHA256 `7aa1108a8f536f720735edec5183d9846d52e8b28ce7236db2f5121354bc6a11`.
- A–E report: PASS, SHA256 `54baa6c27b286226bce5698ef0a3e56456aadf739c577915d5a57c82af55ca7d`.
- Remote-only 17-mode prediction NPZ: 9,883,684 bytes, SHA256 `5a28ce8cc58674f89aa4388b9e205410877a954491051b93c9db9e839c2bec68`.
- Best/last checkpoint SHA256: `f1ce2c6b7ec17db04651982391ad732542e387ab38d2cc1c76e7084941470614` / `76bb0a12f995adff6146fbd2f58682789b6292bf4b56bda3a63ee0718a8375db`.
- Diagnostic step 400/800/1200 checkpoint SHA256: `d60d72b...d8c80b`, `bcc3b543...1c6f8`, `96b2f783...b33c` (full values are in the training audit).

The first post-hoc invocation failed only because `audit_s8_results.py` read the real A–E field as `fusion_input_blocks.visual` instead of `fusion_input_blocks.blocks.visual`. The producer artifacts, checkpoints and predictions were already complete and immutable. Test-driven repair commit `6f39172120ab877c246d3fd6fbd1a4699a6f2871` updates only that reader in the scientific `src/scripts/configs` scope and adds a real-schema regression fixture. The clean repair candidate passed compileall and `536 passed in 347.58s`; a locked recovery ran only the missing post-hoc audit, with `starts_training=false` and `starts_ae=false`.

The recovered independent post-hoc audit is PASS, SHA256 `7784887d05199ae4d70a81c29d497d4a9cd6c689a0746d56aa459b83df4e0d5b`, with eight verified source receipts, 17 modes, 5,820 samples, 58,200 T=10 segments and independently recomputed metric digest `08334096358cb5c6a9cf59e1e4deb22662abc727201ea26ab9eea72db174bfaf`. Its stderr is empty. It explicitly sets `automatic_scientific_success_claimed=false`, `next_experiment_authorized=false` and `formal_full_training_authorized=false`.

Primary compact evidence:

1. [Independent post-hoc artifact audit](evidence/s8/posthoc/s8_posthoc_audit.json)
2. [Full A–E diagnostic report](evidence/s8/posthoc/s8_zero_training_ae.json)
3. [Independent training artifact audit](evidence/s8/control/s8_training_audit.json)
4. [Post-hoc recovery receipt](evidence/s8/control/posthoc_recovery_receipt_6f39172.json)
5. [Final metrics](evidence/s8/training/final_metrics.json)
6. [Three-epoch history](evidence/s8/training/history.jsonl)
7. [First-batch diagnostics](evidence/s8/training/training_diagnostics.jsonl)
8. [Resolved configuration](evidence/s8/training/resolved_config.yaml)

## Boundary and next decision

S8 completes the only experiment authorized by A–F. It clears the representation-collapse branch but does not clear the behavioral visual-dependence branch. No numeric S8 success threshold was preregistered, so none is invented after seeing the data. The supported classification is evidence pattern 2, not a successful audiovisual recovery.

At the time of the S8 report, no S9, Visual-only, second seed, extended schedule or formal Full training had been started. The subsequently authorized S9 paper-additive control is documented separately in [S9_RESULTS.md](S9_RESULTS.md); S8 itself did not authorize it. No canonical loss was changed and the canonical full-run guard remains intact.
