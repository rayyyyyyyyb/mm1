# Completed Controls and Paper-to-Code Fusion Audit

Date: 2026-08-27

Scope: exact-current-pipeline Student-only and Visual-only controls, plus a static comparison of the paper's Section 3.2 fusion equations with the current reconstruction.

## Claim boundary

The numbers and code paths below are directly evidenced. The root-cause interpretation is a diagnosis of this reconstruction. It is not archival proof of the unpublished meeting-paper implementation.

## Controls

Both controls used commit `c5c50361f549c84cb0a934955ac504137977003d`, seed 42, the same official `T_task=10` data/evaluator path and the same locked teacher cache as the Full run. Each completed 30 epochs and 12,000 optimizer steps with worker exit code 0.

| Run | Config SHA256 | Best epoch / step | Test AP | Test AUROC | F1@0.5 | Calibrated F1 |
|---|---|---:|---:|---:|---:|---:|
| Student-only | `4664f9e4ba6da82f2ea2d901271d7a7b856dbc6d33c9b7726425da3f8f169659` | 1 / 400 | 0.748745 | 0.636135 | 0.540393 | 0.545042 |
| Visual-only | `053cfc863beaecb4113470a65449b78e8ee81d089b41dcf1c94e500af8f3ed0c` | 5 / 2,000 | 0.725309 | 0.617160 | 0.540393 | 0.548733 |
| Full | canonical evidence | 1 / 400 | 0.741946 | 0.633875 | 0.540393 | 0.544939 |

The final-metrics SHA256 values are:

- Student-only: `c223ed776f80a65b03b94c3caa13c48edc4dab7a352fad2df94a0aadef467488`;
- Visual-only: `39e881c1a89457c6e3f0b8dcef6fec8830c4d175685a4c667a7d7ae0d9a2cb69`.

Checkpoint bytes remain only on the 5090:

- Student best: 556,937,401 bytes, SHA256 `830c600babdba1e26ab0385c30b61eb9a1d4218e69a75cf36df5620de953d579`;
- Student last: 556,937,401 bytes, SHA256 `438c11bfaed25df8f10edd82e99c939c6c1be4e97ffb015b2677181d720d2a0c`;
- Visual best: 562,479,777 bytes, SHA256 `f27cde2b2ae179552b20d804af250c698aa2161eab08cfbc4e4cadadbd4158d1`;
- Visual last: 562,479,777 bytes, SHA256 `9d17f00da9c5f4f1174ae37e08d42b58179c46226647c200172a59157fd33259`.

## Paper-to-code mapping

The meeting paper Section 3.2, Equations 1--3, describes:

1. visual, audio and query projections to the common dimension;
2. a two-output softmax MLP producing separate visual/audio weights for each task segment;
3. additive fusion of weighted visual, weighted audio and query embeddings before the Transformer layer.

The current source implements item 2. It does **not** omit separate modality parameters:

- `src/models/ov_orthkd.py:107-111`: a two-output gate;
- `src/models/ov_orthkd.py:179-186`: softmax followed by separate visual/audio multiplication.

The structural mismatch is downstream:

- paper: additive fusion, then Transformer;
- source at `src/models/ov_orthkd.py:187`: concatenate all three tokens and feed a learned `token_fusion` block;
- source at `src/models/ov_orthkd.py:190-193`: add position embeddings, then temporal Transformer;
- source gate input additionally contains validity flags at lines 168--178.

This mismatch is potentially causal because the learned gate saturated early in both controls and acts before the learned fusion block. It is not yet proven causal. A paper-additive-fusion run and a fixed-gate run change different variables and must not be combined.

## Trainable-target evidence

The teacher features themselves are detached, but the target projection layers are trainable:

- projector definitions: `src/losses/ov_orthkd_loss.py:87-89`;
- projected targets: `src/losses/ov_orthkd_loss.py:159`, `:173`, and `:188`;
- optimizer includes the entire loss module: `scripts/train_ov_orthkd.py:1352-1357`.

The Visual-only early diagnostic shows simultaneous collapse of student decision variance and projected strong-target variance while the projector parameters drift. This supports, but does not uniquely prove, a moving-target degeneracy.

## Exact evidence set

Each `control_runs/<variant>/` directory contains:

- actual resolved config;
- final metrics;
- all 30 history rows;
- the observation-only diagnostic rows for the first batch of epochs 1--3;
- runtime/CUDA, Git-state, dependency, manifest, lock, teacher-cache and official-evaluator receipts.

The two prediction audits are PASS and mechanically verify official `T=10` shapes and finite arrays. The binary prediction arrays themselves are excluded.

## Next-step boundary

No new training is started by this publication. The next run must be chosen after independent review and should be one single-variable causal test. It must not be reported as the historical meeting-paper implementation without archival evidence.
