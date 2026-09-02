# Visual-only mean-to-sum bounded control

Status: **pre-registered diagnostic control; formal Full remains blocked**.

## Decision boundary

The local and 5090 provenance audit found no recoverable original OV-OrthKD
branch, command history, TensorBoard/W&B run, environment snapshot, or original
checkpoint. Existing checkpoints contain optimizer state, but their embedded
metadata identifies them as this repository's `paper_specified_reconstruction`
or diagnostic runs. They are not archival evidence. Therefore this control is
the next highest-value action under the supplied review ruling.

## Single scientific variable

The source configuration is
`configs/diagnostics/ov_orthkd_mm26_visual_only_seed42.yaml`. The control copies
that configuration and changes exactly one scientific field:

```text
loss.visual_l2_reduction:
  mean_feature_then_masked_mean_segments
  -> sum_feature_then_masked_mean_segments
```

For projection dimension 256, this changes the feature-dimension reduction from
the arithmetic mean to the squared-norm sum. The masked segment reduction,
teacher detach, coefficients, data, teacher exports, student, optimizer,
schedule, seed, augmentation, and evaluator are otherwise frozen.

The control is intentionally labelled `noncanonical_diagnostic`, sets
`diagnostic_only: true` and `full_run_blocked: true`, and writes below an
`outputs/diagnostic/` namespace. These are run-identity and safety metadata, not
scientific interventions. The canonical Full guard and canonical lock files are
unchanged.

## Frozen protocol

- seed `42`; official `T_task=10`; student positional capacity `T_max=16`;
- existing Visual-only reconstruction architecture and teacher cache;
- `pretrained=false`, training augmentation enabled;
- AdamW, learning rate `2e-4`, weight decay `1e-4`, gradient clip `1.0`;
- cosine schedule with `T_max=30` at epoch interval;
- 30 epochs, at most 400 batches per epoch, no optimizer-step truncation or
  early stopping, and one fixed test view;
- validation model selection remains `validation_segment_AP`; all metrics stay
  on the official ten task segments.

## Audit and interpretation

Before launch, the config contract test must pass and the blocked-run validator
must deny execution without `--allow-blocked-reproduction`. The actual run must
record the resolved config, implementation behavior, runtime environment,
history, checkpoints, predictions and exit status. A valid run is not a paper
reproduction claim.

The first independent check is the exact reduction identity on a real batch:
for finite, identical tensors and masks, the sum/mean feature-loss ratio must
be the projection dimension (`256`) up to floating-point tolerance. Only after
that check are validation/test AP, AUROC and F1 compared with the existing
mean-reduction Visual-only baseline. No post-hoc threshold, second seed,
schedule extension, architecture change, or Full launch is authorized by this
plan. If any artifact or identity check fails, classify the control
`BLOCKED_BEFORE_R2` and do not interpret metrics.
