# Student-only current-pipeline control completion status

## Outcome

The seed-42 Student-only control completed normally on the RTX 5090 with exit code `0`. It ran the exact diagnostic commit `c5c50361f549c84cb0a934955ac504137977003d`, canonical experiment config SHA256 `4664f9e4ba6da82f2ea2d901271d7a7b856dbc6d33c9b7726425da3f8f169659`, 30 epochs, and 12,000 optimizer steps.

The best validation AP occurred at epoch 1 / global step 400. Later epochs never improved it. Evaluation used the best checkpoint, not the last checkpoint.

## Final best-checkpoint metrics

| Reference | AP | AUROC | official segment F1@0.5 |
|---|---:|---:|---:|
| Paper Student-only | 0.714000 | 0.612000 | 0.523000 |
| Current-pipeline Student-only | 0.748745 | 0.636135 | 0.540393 |
| Current-pipeline Full seed42 | 0.741946 | 0.633875 | 0.540393 |
| Paper Full | 0.816000 | 0.750000 | 0.596000 |

The current-pipeline Student-only result exceeds the paper Student-only row by `+0.034745 AP`, `+0.024135 AUROC`, and `+0.017393 F1`. It also exceeds the current Full run by `+0.006799 AP` and `+0.002260 AUROC`, while F1@0.5 is identical to floating-point precision. It remains far below paper Full by `-0.067255 AP`, `-0.113865 AUROC`, and `-0.055607 F1`.

Validation selected threshold `0.6857516565`. At that threshold, test official segment F1 is `0.5450419944`, event F1 is `0.5809450172`, and predicted-positive rate remains `0.9873711340`.

## Early-training diagnostic trajectory

| Epoch/batch | mean within-sample logit std | visual gate mean | gate entropy | saturation rate | visual encoder grad |
|---|---:|---:|---:|---:|---:|
| epoch 1, batch 1 | 0.121423 | 0.477567 | 0.691656 | 0.000 | 5.279463 |
| epoch 2, batch 1 | 0.010901 | 0.753337 | 0.211739 | 0.525 | 0.010065 |
| epoch 3, batch 1 | 0.002377 | 6.84e-11 | 1.51e-9 | 1.000 | 0.000000 |

By epoch 3 the modality gate has collapsed completely to the audio branch for the observed batch, the visual encoder gradient is zero, and within-video temporal contrast has nearly vanished. This is direct evidence of training instability in the shared student/gating path, but it is not yet sufficient to declare a unique root cause. Visual-only is the required next controlled run.

## Artifact verification

- `history.jsonl`: 30 records, final epoch index 29, final global step 12,000.
- `final_metrics.json`: parsed successfully; SHA256 `c223ed776f80a65b03b94c3caa13c48edc4dab7a352fad2df94a0aadef467488`.
- `best.pt`: 556,937,401 bytes; SHA256 `830c600babdba1e26ab0385c30b61eb9a1d4218e69a75cf36df5620de953d579`.
- `last.pt`: 556,937,401 bytes; SHA256 `438c11bfaed25df8f10edd82e99c939c6c1be4e97ffb015b2677181d720d2a0c`.
- The two checkpoints remain only on the 5090 and are not prepared for Git upload.
- Twenty small artifacts were archived and copied to `student_only_completed_snapshot`; all nine JSON files parse, all four NPZ files load with `allow_pickle=False`, all numeric arrays are finite, validation is 5,798 × 10 segments, and test is 5,820 × 10 segments.
- Small-artifact archive SHA256: `5715a193f75617345840a2c93d4fb95b599bbc5f6fa645b56f0f60360fdd77ce`.

## Current machine state

At UTC `2026-08-26T14:40:24Z`, no Student-only or Visual-only process matched the diagnostic commands. The RTX 5090 was idle at 0% utilization with 879 MiB / 32,607 MiB allocated. Visual-only had not yet started at the time of this status snapshot.

## Subsequent action

After closing the Student-only evidence chain, the exact-current-pipeline Visual-only control was launched persistently at UTC `2026-08-26T14:49:24Z`. Its config SHA256 is `053cfc863beaecb4113470a65449b78e8ee81d089b41dcf1c94e500af8f3ed0c`; worker PID 15056 reported `running`, with venv/native Python PIDs 27784/8316. A second independent SSH session confirmed the same state after the launch session ended. At that point it was still performing startup readiness/evidence hashing, so 0% GPU usage and an empty output directory were expected.
