# Optimizer-state-aware virtual replay (A5)

One real C1-best train batch was differentiated against the loaded AdamW state,
then replayed entirely on clones.  The comparison changes only the clipping
scope; no optimizer step, checkpoint write, or input-state mutation occurred.

| Scope | Included groups | Pre-clip global norm | Clip coefficient |
|---|---:|---:|---:|
| `current_global_all_grad_clip` | 613 | 104.552886 | 0.00956454 |
| `updating_parameters_only_clip` | 607 | 42.956841 | 0.02327918 |

The six excluded parameters are the zero-LR static projector group.  Including
that group reduces the effective clip coefficient by about 2.43x.  Student
delta cosines between the two virtual replays remain high (`0.8999` visual
encoder, `0.9114` decision projection, `0.9219` temporal encoder), while delta
norms increase under the positive-LR-only scope (for example visual encoder
`0.07393 -> 0.11239`, temporal encoder `0.12054 -> 0.15033`).  This directly
quantifies optimization coupling and does not establish a same-parameter loss
direction conflict.

Receipt: `phase_a/A5_C1_best.json` on 5090.  The AdamW one-step equivalence and
input-invariance tests pass. The replay was diagnostic only; the subsequent C2
positive-LR clipping control is reported in
[STATIC_TARGET_COUPLING_FINAL.md](STATIC_TARGET_COUPLING_FINAL.md).
