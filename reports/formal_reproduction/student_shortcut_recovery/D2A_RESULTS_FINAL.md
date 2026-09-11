# D2A paired pretrained early-dynamics result

Date: 2026-09-11  
Control: `D2A_PAIRED_PRETRAINED_EARLY_DYNAMICS_400`  
Code commit: `59e4a1cd5f23114da43abca2e9d20e5fb85f77d9`  
GPU: NVIDIA GeForce RTX 5090  
Split: validation only, official `T_task=10`

## Verdict

The run completed 400 attempted batches for both paired arms. Each arm
applied 394 updates; the AMP applied/skip masks were identical. The producer
completed with exit code `0`, and the independent auditor also completed with
exit code `0`.

The final status is:

- Artifact: `D2A_ARTIFACT_AUDIT_PASS`
- Scientific: `D2A_PRETRAINED_EARLY_DYNAMICS_FAIL`
- Next experiment authorization: none
- Test evaluation, D3, formal Full, second seed, automatic extension: all `false`

The exact locked pretrained visual initialization therefore did not pass the
pre-registered early-dynamics boundary. This is a bounded scientific failure,
not an artifact or runtime failure.

## Independent step-400 gate

| Requirement | Observed | Threshold | Result |
|---|---:|---:|---|
| Pretrained minus random mixed concordance | `+0.0967271` | `>= +0.020` | pass |
| Pretrained minus random validation AP | `-0.0195109` | `>= -0.020` | pass |
| Pretrained decision temporal std | `0.0002408` | `>= 0.003` | fail |
| Pretrained temporal-shuffle AP drop | `0.0005216` | `>= 0.010` | fail |
| Pretrained temporal-shuffle AUROC drop | `0.0009803` | `>= 0.010` | fail |
| Pretrained visual-zero concordance drop | `-0.0001376` | `>= 0.010` | fail |
| Pretrained predicted-positive rate | `1.0000000` | `< 0.98` | fail |
| Supporting criteria | `0 / 3` | `>= 2 / 3` | fail |

The concordance difference alone is not sufficient: the paired pretrained arm
still collapsed to an almost constant-positive decision and showed no
registered temporal or visual-causal signal.

## Trajectory

The following values are validation-only and descriptive; the scientific gate
was evaluated only at step 400.

| Attempted step | Random AP | Pretrained AP | Random concordance | Pretrained concordance | Pretrained positive rate |
|---:|---:|---:|---:|---:|---:|
| 0 | 0.568749 | 0.569165 | 0.491673 | 0.470423 | 0.809469 |
| 25 | 0.640220 | 0.641765 | 0.594319 | 0.517355 | 1.000000 |
| 50 | 0.666149 | 0.711140 | 0.627639 | 0.495499 | 1.000000 |
| 100 | 0.722095 | 0.743196 | 0.525076 | 0.503399 | 1.000000 |
| 200 | 0.734418 | 0.726576 | 0.535330 | 0.579592 | 1.000000 |
| 400 | 0.745006 | 0.725495 | 0.492637 | 0.589364 | 1.000000 |

## Audit and provenance

The independent audit was run twice: once by the persistent 5090 postprocess
worker and once locally over the downloaded raw validation NPZ files. The
results are byte-identical:

- `d2a_artifact_audit.json` SHA256:
  `726c5755c0a6d5efd7998a52a4df1c47408ee77e02e1f4d7fa2e9638fdd097f5`
- `D2A_PAIRED_EARLY_DYNAMICS_REPORT.md` SHA256:
  `48f5c6032f1c98d7de00d46ec4345736524fda7ed1ed5b95d274836b4c49efa0`
- Formal producer `result.json` SHA256:
  `8d2810cc9a75dcee06ab48a5433dd2ca608f7254ec3df75500f6478c7281a515`
- Formal elapsed time: `14019.5817446 s`
- Formal stderr SHA256: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

Compact receipts, resolved initialization, fixed batch plan, optimizer
receipts, trajectory and audit outputs are tracked beside this report under
[`evidence/d2a_paired_early_dynamics_59e4a1c/`](evidence/d2a_paired_early_dynamics_59e4a1c/).
Raw prediction NPZ files and `paired_resume.pt` are intentionally excluded
from Git; their remote root is
`E:/OV-OrthKD-R3/d2a_paired_early_dynamics_20260911_59e4a1c`.

## Boundary

This result does not authorize any follow-up run. In particular, do not
continue the pretrained arm to 800 steps, access the test split, start D3 or
formal Full, launch another seed, alter the scheduler, or reinterpret the
concordance-only pass as recovery. Any future action requires a new explicit
pre-registration and human authorization.
