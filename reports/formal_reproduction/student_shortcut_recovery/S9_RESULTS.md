# S9 paper-additive diagnostic results

Date: 2026-09-02
Scientific status: **FAIL** (pre-registered S9 visual-causal gates)
Artifact status: **PASS** (training, A–E and posthoc integrity)

## Scope and locked change

S9 is the single bounded control authorized after S8. It starts from the S8 identity-temporal/fixed-equal-gate setup and changes exactly one scientific field:

```text
student.fusion_mode:
  concat_mlp_query_conditioned -> paper_additive_query_conditioned
```

The additive branch is the paper-form operator

```text
fused_tokens_before_position = 0.5 * weighted_visual + 0.5 * weighted_audio + text_token
```

The `token_fusion` module remains instantiated solely to preserve parameter count and state-dict keys; in this branch it is not called. No canonical loss, evaluator, data manifest, teacher cache, Full guard, temporal path, gate, seed, augmentation, pretrained setting or training exposure changed.

## Protocol locks

- Official task timeline: `T_task=10` one-second segments; no 10→16 conversion.
- `T_max=16` is positional capacity only.
- Seed 42, deterministic mode, one test view.
- Student visual/audio gate is fixed `0.5/0.5`; temporal path is `identity_passthrough`.
- Explicit projected route; fusion/projected dimensions 384/256.
- Student-only BCE; all KD/text/orth weights are zero.
- AdamW, learning rate `2e-4`, weight decay `1e-4`, gradient clip `1.0`, AMP.
- Three epochs of 400 batches, batch size 4; validation AP selects the best checkpoint.
- Checkpoints at steps 400, 800 and 1200; all 5,798 validation and 5,820 test samples use the official evaluator.
- A–E uses 17 intervention modes, 5,820 samples/58,200 task segments, and 100 fixed-seed within-sample temporal shuffles.

## Training result

Validation AP selected step 1200. The ranking metrics improved over S8 only modestly at the final test point:

| Run | Test AP | AUROC | Binary micro F1@0.5 | Segment F1@0.5 | Event F1@0.5 |
|---|---:|---:|---:|---:|---:|
| S8 | 0.769761 | 0.674486 | 0.687314 | 0.537494 | 0.502510 |
| S9 | 0.774657 | 0.679398 | 0.620111 | 0.525174 | 0.444836 |
| S9 − S8 | +0.004896 | +0.004912 | −0.067204 | −0.012320 | −0.057674 |

S9 validation AP/AUROC at steps 400/800/1200 were `0.728994/0.635471`, `0.758936/0.666368` and `0.762621/0.670530`. The selected checkpoint is therefore the AP-best step 1200 despite the fixed-threshold F1 fall; changing selection after observing F1 would violate the locked protocol.

## Full A–E intervention result on mixed-label videos

The mixed stratum has 1,941 videos and 19,410 one-second segments. Original and visual-zero predictions are almost identical:

| Intervention | AP | AUROC | Pair-weighted concordance |
|---|---:|---:|---:|
| Original | 0.6574390533 | 0.6111105921 | 0.6361746362 |
| Visual zero | 0.6574472739 | 0.6111150681 | 0.6361184469 |
| Audio zero | 0.6222040206 | 0.5608467651 | 0.5523121874 |
| Both zero | 0.6220512366 | 0.5608432157 | 0.5519188627 |
| Forced visual gate (1/0) | 0.6213766287 | 0.5601162202 | 0.5508231724 |

Derived visual causal effects (original minus visual-zero) are:

```text
ΔAP      = -0.0000082206
ΔAUROC   = -0.0000044761
ΔC       = +0.0000561892
```

For reference, audio zero changes AP by `0.0352350327` and both zero by `0.0353878167`. Thus the visual concordance effect is about 356× below the required `0.020` gate and the visual-zero intervention slightly improves AP/AUROC when visual content is removed.

Temporal protection remains present for the original mixed predictions: 100 fixed-seed shuffles give mean AP drop `0.0354367223` (mean AUROC drop `0.0481806614`). Forced visual-only temporal shuffle AP drop is only `0.0017258646`, and forced-visual concordance is `0.5508231724`.

## Pre-registered classification

The implementation-integrity gate passed. The scientific gates are evaluated exactly as registered:

| Gate | Requirement | S9 | Result |
|---|---:|---:|---|
| Visual causal concordance | `ΔC ≥ 0.020` | `0.000056` | fail |
| One global ranking effect | `ΔAP ≥ 0.010` or `ΔAUROC ≥ 0.010` | both negative | fail |
| Other ranking effect | strictly positive | both negative | fail |
| Mixed AP protection | `AP ≥ 0.640` | `0.657439` | pass |
| Mixed concordance protection | `C ≥ 0.650` | `0.636175` | fail |
| Mixed shuffle protection | AP drop `≥ 0.020` | `0.035437` | pass |

The registered fail rule is already met: all three visual effects are below their weak-effect thresholds, and two effects are non-positive. The independent classifier therefore returns:

```text
classification = FAIL
reason = all_visual_effects_below_preregistered_fail_thresholds
```

This is a scientific failure of the bounded additive readout to recover useful visual label-aligned ranking, not an artifact or numerical-runtime failure. It does not prove that one specific downstream layer is solely responsible; it rejects this one additive intervention under the fixed-gate/identity-temporal diagnostic condition.

## Independent integrity evidence

- Scientific implementation commit: `b8ea747dd792c939251152ead734d1826c26980d`.
- Canonical-LF S9 config SHA256: `61942acb92fe0a9a1a87a828764073303761328783b515c606e97d8f10e26cbe`.
- Exact candidate compile/full-suite verification: `555 passed in 372.02s`, exit 0; verification receipt SHA256 `e2071da533d757ec627b9e55c2998f334c5a3385f209b4d2509d73944ac9acc7`.
- Training artifact audit: PASS, SHA256 `a0a1b35fae2a5c5cf352e406b57e8f2d7cdd7828fe837f19f0230f7b03f0a7c4`.
- A–E artifact audit: PASS, SHA256 `54391fa046dd7ec2900bc613aabcb6f1200fa59e8d18b3a2b0d8da2ac6dae264`.
- Formal posthoc artifact/scientific audit: PASS as an integrity report, SHA256 `a9a3040738f5a1b2e003838c36960e10b0dbae77a88e3d1a3170d75aa4f7a740`.
- Independent posthoc re-audit on the 5090 produced byte-identical SHA256 `a9a3040738f5a1b2e003838c36960e10b0dbae77a88e3d1a3170d75aa4f7a740` and the same scientific `FAIL` classification.
- Remote-only prediction archive: 10,031,929 bytes, SHA256 `e7a57a74de3359aa03ca7de44f3cace555897012bc1802db1c8af1b0a02e73eb`; it is not uploaded.
- Checkpoints, data, teacher cache, prediction arrays and logs remain only on the 5090.

Primary evidence:

1. [Independent posthoc audit](evidence/s9/posthoc/s9_posthoc_audit.json)
2. [Independent posthoc re-audit](evidence/s9/posthoc/s9_posthoc_reaudit.json)
3. [Full A–E report](evidence/s9/posthoc/s9_zero_training_ae.json)
4. [Training artifact audit](evidence/s9/control/s9_training_audit.json)
5. [Final metrics](evidence/s9/training/final_metrics.json)
6. [Resolved configuration](evidence/s9/training/resolved_config.yaml)

## Boundary

S9 is complete and scientifically **FAIL** under its pre-registered thresholds. `next_experiment_authorized=false` and `formal_full_training_authorized=false` are explicitly recorded in both posthoc reports. No S5/S6, Visual-only, second seed, extended schedule, canonical loss edit or formal Full training was started. Any future intervention requires a new human-approved design and independent pre-registration; this report does not authorize it.
