# Control-run evidence inventory

This directory publishes small, reviewable evidence for the completed exact-current-pipeline controls. It intentionally excludes datasets, caches, checkpoints, prediction/PR-curve NPZ files, ZIP archives and progress logs.

## Student-only

- 30 epochs / 12,000 optimizer steps;
- best epoch 1 / step 400;
- config SHA256: `4664f9e4ba6da82f2ea2d901271d7a7b856dbc6d33c9b7726425da3f8f169659`;
- final-metrics SHA256: `c223ed776f80a65b03b94c3caa13c48edc4dab7a352fad2df94a0aadef467488`;
- history SHA256: `892694b36db1d20cb1d227acb177cf0619dbfffd789962c7c144c21af6cd4d6c`;
- diagnostics SHA256: `254c0a0fb96b41ebdb9babd1433f285bfe3f33450fc9dad678a3629fdd30d804`.

## Visual-only

- 30 epochs / 12,000 optimizer steps;
- best epoch 5 / step 2,000;
- config SHA256: `053cfc863beaecb4113470a65449b78e8ee81d089b41dcf1c94e500af8f3ed0c`;
- final-metrics SHA256: `39e881c1a89457c6e3f0b8dcef6fec8830c4d175685a4c667a7d7ae0d9a2cb69`;
- history SHA256: `bd7429cfeb583a06cb713df24012e2e3f0b204829eebed9e7ca8f77ce3709f55`;
- diagnostics SHA256: `0a9548b85b6f21739524278c88062b1026db6ec5d351fbbdb22b81cdf07b1f82`.

## File roles

- `config_resolved.yaml`: actual resolved configuration recorded by the run;
- `final_metrics.json`: best-checkpoint validation/test evaluation;
- `history.jsonl`: all epoch rows;
- `training_diagnostics.jsonl`: observation-only first-batch records for epochs 1--3;
- `experiment_variant.json` and `claim_level.txt`: control identity and claim boundary;
- remaining JSON/TXT files: Git, runtime, CUDA, dependency, manifest, lock, evaluator and teacher-cache identity receipts.

The files are stored with Git text conversion disabled so their committed bytes retain the recorded SHA256 values.
