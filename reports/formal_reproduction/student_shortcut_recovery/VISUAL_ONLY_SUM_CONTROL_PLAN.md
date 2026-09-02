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

## Runtime-only retry after Windows error 1455

The first real run reached epoch 4 (global step 1600), then failed during
validation with PyTorch's shared-file-mapping error 1455. The failure is an
execution-resource issue from four DataLoader workers and does not identify a
scientific effect. The failed output is retained as evidence.

The retry configuration
`configs/diagnostics/recovery/ov_orthkd_visual_only_sum_feature_seed42_single_worker.yaml`
sets `data.num_workers: 1` solely to avoid that Windows paging/shared-memory
failure. Its `reproduction.runtime_overrides` field records the change and
reason. The only scientific change relative to the mean-reduction baseline is
still `loss.visual_l2_reduction`; no incompatible resume is allowed, so the
retry starts from a clean output namespace and retains the same 30-epoch,
400-batch, seed-42 protocol. A worker-count change is treated as runtime
plumbing, not as a model, data, loss, schedule, or evaluation intervention.

That single-worker retry also reproduced error 1455 before its first batch,
showing that the shared-file mapping limit is not solved by reducing the worker
count alone. The next and final runtime retry is
`configs/diagnostics/recovery/ov_orthkd_visual_only_sum_feature_seed42_no_workers.yaml`
with `data.num_workers: 0`, so loading occurs in the training process and no
inter-process tensor mapping is required. It remains a clean run (no
incompatible resume), keeps the same scientific configuration and schedule,
and records the two failed resource attempts as evidence. If this retry cannot
complete, the control is `BLOCKED_BEFORE_R2` and no further runtime or
scientific variants are authorized.
