# Causal Fusion Diagnostics Design

Date: 2026-08-27

Status: approved for direct execution by the user's instruction accompanying the web diagnosis

## Purpose

Repair configuration paths that currently declare behavior without controlling it, expose the paper-additive fusion as a diagnostic implementation, and run three short Student-only controls that isolate learned-gate saturation from fusion structure. These are causal diagnostics of the reconstruction, not archival recovery and not replacements for the canonical Full result.

## Evidence boundary

The web diagnosis is technically supported for these repository facts:

- `student.fusion_mode` is present in YAML and locks but is not passed to `OVOrthKDStudent`;
- the current forward always performs weighted modality concatenation followed by `token_fusion`;
- `loss.visual_l2_reduction` is present in YAML and locks but the camera-ready loss always uses feature-dimension mean;
- teacher target projectors are trainable because all loss-module parameters enter the same AdamW as the student;
- fusion text projection and text-loss target projection are independent;
- training augmentation is sampled independently for each segment image.

Teacher cache quality, official `T_task=10`, evaluator aggregation and random seed are not promoted back to primary suspects. Historical choices for pretraining, batch size, step400, scheduler, projector freezing, L2 reduction and augmentation remain unresolved.

## Runtime modes

`OVOrthKDStudent` will expose two orthogonal settings:

- `fusion_mode=concat_mlp_query_conditioned`: preserve the current weighted concat plus learned `token_fusion` behavior;
- `fusion_mode=paper_additive_query_conditioned`: compute `alpha_v * visual + alpha_a * audio + text` with no concat projection;
- `gate_mode=learned_softmax`: preserve the current query-conditioned two-logit softmax gate, including validity masking;
- `gate_mode=fixed_equal`: use 0.5/0.5 when both modalities are valid, 1/0 or 0/1 when only one is valid, and 0.5/0.5 when both are missing.

Unknown values fail during construction. The additive mode does not remove validity inputs from the learned gate, because that would change a second variable.

## Distillation controls

`OVOrthKDLoss` will expose:

- `visual_l2_reduction=mean_feature_then_masked_mean_segments`, preserving the current behavior;
- `visual_l2_reduction=sum_feature_then_masked_mean_segments`, summing squared error over feature dimension before masked segment mean;
- `teacher_target_projector_trainable=true|false`, applied to strong, weak and independent text target projectors;
- `query_anchor_mode=independent_loss_projection`, preserving the current text target projector;
- `query_anchor_mode=shared_fusion_projection`, using the exact fusion `text_token` as the text-alignment target and producing the student query path in `fusion_dim` so dimensions match.

Shared-query mode is implemented and tested but is not enabled in S0/S1/S2. Projector freezing and shared query remain separate Visual-only variables.

## Runtime evidence

After model/loss construction, the trainer will derive a `runtime_implementation` mapping from actual module attributes and parameter trainability. It will be added to the resolved config before fingerprinting and stored both as `implementation_behavior.json` and in every checkpoint. Optimizer construction will include only parameters with `requires_grad=true`.

## Short Student-only controls

All controls use seed 42, official `T_task=10`, current backbones, `pretrained=false`, current augmentation, batch 4, 400 batches per epoch, three epochs, current optimizer/scheduler and all KD losses disabled.

- S0: learned gate plus current concat MLP;
- S1: fixed equal gate plus current concat MLP; only `gate_mode` differs from S0;
- S2: learned gate plus paper-additive fusion; only `fusion_mode` differs from S0.

They use `claim_level=noncanonical_diagnostic` with `diagnostic_only=true`. The trainer accepts that pair but rejects a noncanonical claim without the diagnostic marker.

## Acceptance criteria

- RED tests demonstrate each current no-op or missing mode before production edits.
- Focused tests pass after each minimal change.
- Configuration-diff tests prove S1 and S2 each change one scientific variable relative to S0.
- Full pytest passes on the exact committed candidate in the locked 5090 environment.
- Each control writes three history and three first-batch diagnostic records, an implementation behavior receipt, final metrics, fingerprints and artifact hashes.
- Comparison reports include gate saturation, both encoder gradients, within-video logit variance, predicted-positive rate, positive/negative logit separation, best epoch and AP/AUROC/F1.
- No formal Full, second seed, hyperparameter sweep, teacher export or additional real-data preflight is started.

## Independent review

After implementation, perform a fresh line-by-line review against this design, mutation-check every new behavioral test, parse every new YAML/JSON/JSONL artifact, scan the Git diff for unintended variables and large assets, then run focused and complete test suites independently of the implementation steps.
