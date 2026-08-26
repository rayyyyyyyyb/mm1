# Root-Cause Diagnostic Gate Results

Date: 2026-08-26

Status: `TEACHER_SIGNAL_GATE_PASSED__SHARED_STUDENT_CONTROL_PENDING`

## Decision

The web diagnosis is directionally sound, with one important update: the locked visual teacher signals are already healthy enough to reproduce the direct-logit diagnostic and to support strong transparent probes. The current evidence moves the primary search from teacher assets to the student/training/transfer path.

No structural candidate has been promoted. Paper-additive fusion, shared query projection, frozen target projectors, pretrained backbones and alternate `step400` semantics remain isolated A/B hypotheses.

## Gate 1: Zhou official output re-score

Status: `BLOCKED_MISSING_UPSTREAM_OUTPUT`

The locked official OV-AVEL checkout at commit `b5fe1d685d0c6d0d6fd80312b5ccde79f9b73ea6` contains source and annotations but no fine-tuning checkpoint or saved prediction output. `.checkpoints/readme.txt` is 62 bytes. The 5090 weights inventory contains only InternVideo2, BEATs and CLAP assets.

This gate cannot be replaced by re-scoring our own prediction. It remains open until the exact upstream output/checkpoint is published or supplied.

## Gate 2: teacher signals

### Visual direct logits

| Split | Samples | Segments | AP | AUROC | Paper AP | Paper AUROC |
|---|---:|---:|---:|---:|---:|---:|
| validation | 5,798 | 57,980 | 0.771935 | 0.707681 | 0.767 | 0.707 |
| test | 5,820 | 58,200 | 0.780220 | 0.716227 | 0.776 | 0.716 |

All arrays were present and exactly `[10]`. Test AUROC agrees with the paper at three decimals; test AP differs by `+0.004220`.

### Transparent reconstruction probes

The paper only specifies a “light linear probe.” The diagnostic therefore pre-registers and receipts train-only StandardScaler + deterministic SGD logistic regression, L2 `alpha=1e-4`, seed 42, no class weighting or early stopping. These numbers are not archival-exact Table 2 recovery.

| Signal | Validation AP | Validation AUROC | Test AP | Test AUROC | Paper test AP/AUROC |
|---|---:|---:|---:|---:|---:|
| visual features | 0.816315 | 0.738423 | 0.815682 | 0.735034 | 0.765 / 0.670 |
| audio features | 0.789878 | 0.730818 | 0.790812 | 0.732781 | 0.718 / 0.645 |

Interpretation: absolute differences can come from undisclosed probe details, but neither cache lacks boundary-separable information. Teacher identity/export is unlikely to be the main cause of Full AP `0.741946`.

## Prediction-only audit

Frozen validation threshold: `0.6659861520`.

| Test diagnostic | Value |
|---|---:|
| global segment micro AP | 0.741946 |
| per-sample macro AP, all-negative=0 | 0.679451 |
| per-query/category macro AP | 0.638631 |
| official segment F1 at 0.5 | 0.540393 |
| official segment F1 at frozen validation threshold | 0.544939 |
| predicted-positive rate at frozen threshold | 0.987251 |
| mean within-sample logit std across T=10 | 0.001085 |
| median within-sample logit std | 0.000072 |

The model has some sample-level ranking signal but almost no within-video temporal contrast. Calibration cannot recover the missing boundary behavior. AP aggregation semantics contribute a reporting difference, but macro alternatives are lower, not closer to `0.816`.

## Control configs

- `configs/diagnostics/ov_orthkd_mm26_student_only_seed42.yaml`
- `configs/diagnostics/ov_orthkd_mm26_visual_only_seed42.yaml`

Both are mechanically derived from the actual seed42 resolved config. Student-only changes only variant/output plus four enabled non-logit losses to zero. Visual-only changes only variant/output, audio feature loss and orthogonality to zero; it keeps text alignment at `0.8` as required by the paper control.

Both additionally enable the same observation-only diagnostic for the first batch of epochs 1--3. It records logit/probability distributions, within-sample temporal variation, modality gates, student/teacher-target geometry and effective rank, pre-clip named-module gradient norms, localization-head state, and teacher-projector parameter drift. The records do not enter the forward result, loss, optimizer update, validation, checkpoint selection or evaluator.

Each control has a derived archival lock whose fact bodies and evidence are byte-identical to the R5 lock except for its canonical experiment-config SHA256.

## Verification state

- Pure local evaluator/diagnostic tests: 10 passed; later probe suite: 7 passed.
- 5090 focused evaluator/config/diagnostic tests: 24 passed.
- Observation-only diagnostic unit tests: 9 passed; compileall and diff-check exited 0 locally. The clean 5090 full-suite rerun remains the controlling verification.
- First 5090 full suite in the temporary injected worktree: 395 passed, 1 failed. The only failure was the canonical ready-receipt test because that temporary worktree intentionally lacked asset junctions and was Git-dirty after scp injection. This is an environment/isolation failure, not a passing full-suite claim.
- Required next verification: fresh full suite from the clean diagnostic commit with `data`, `weights`, and `external` junctions. Student-only must not start before that exits 0.
