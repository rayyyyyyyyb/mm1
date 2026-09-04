# Projector control implementation receipt

Date: 2026-09-04  
Branch: `repro/student-shortcut-recovery`  
Claim level: `noncanonical_diagnostic`

## Scope

This change implements the pre-registered C0/C1 bounded control requested by the
projector-collapse review. It does not alter the official `T=10` data protocol,
does not write the canonical teacher cache, and does not authorize Full training.

## Explicit update modes

Each teacher target projector now has an independent, named mode:

- `trainable`: gradients and the normal AdamW learning rate/weight decay apply.
- `frozen_no_grad`: `requires_grad=False`; the projector is omitted from the optimizer.
- `static_zero_lr_keep_grad`: `requires_grad=True`, participates in backward,
  clipping, and receipts, but its optimizer group has `lr=0` and `weight_decay=0`.
  Tensor values therefore remain bitwise unchanged while optimizer moments may
  still be updated.

When all new fields are absent, the legacy boolean is mapped to the equivalent
all-projector mode for backward compatibility. Partial explicit fields or any
old/new conflict fail closed.

## Receipt coverage

`optimizer_groups.json` records group names, parameter names/count/hash, learning
rate, weight decay, and update mode. `optimizer_receipts.jsonl` records every
attempted step, post-hook applied-step count, AMP scale transition, pre-clip norm,
clip coefficient, clipped flag, per-group norms, and contribution shares.

The applied counter is incremented by the optimizer post-hook, so GradScaler
overflow skips are not counted as applied updates. `optimizer_step_summary.json`
is written at clean loop exit.

## Verification

Focused tests covering mode resolution, fail-closed validation, static tensor
semantics, named groups, clipping, and applied-step hooks passed locally. Full
runtime tests require the locked 5090 environment because the local Anaconda
environment does not provide `timm`.
