# Gradient conflict and clipping audit

The control runner records gradient geometry immediately before the single
global clip. Per-group squared-norm shares are retained for the student,
strong/weak/text teacher projectors; these receipts are instrumentation only and
do not alter the forward or loss equations.

For C0 (trainable projectors), the current 800-applied-step receipt set shows:

- strong-projector share mean `0.510517`, median `0.512074`;
- every applied update was clipped (`800/800`), with five initial AMP-overflow
  attempts excluded from the applied count;
- the first validation already had a thresholded predicted-positive rate of
  `1.0`, while AP was `0.7417794173`.

This is evidence of a large, competing projector/ student gradient pathway, not
proof that the projector alone is causal. C1 uses the same loss and data with
only the strong projector changed to `static_zero_lr_keep_grad`; its receipts
will determine whether the signal survives without parameter motion.

For C1, the strong projector is static in parameter space (zero learning rate)
but remains in the autograd graph. Across 800 applied updates its gradient
contribution share is mean `0.811494`, median `0.819354`, while the student
share is mean `0.188429`; all applied updates are clipped and five warm-up
overflows are excluded. The C1 validation geometry confirms that the projected
target retains temporal variation (`0.1682058886`), but student decision
variation is only `0.0013909233` at best and the mixed validation concordance
drops by `0.0509785576` relative to C0. This isolates a remaining gradient
conflict/optimization bottleneck rather than proving a projector-only cause.
