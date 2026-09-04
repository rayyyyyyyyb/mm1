# Feature-loss decomposition audit

The diagnostic helper `src/utils/feature_loss.py` decomposes the masked squared
feature error into the exact temporal mean and centered components:

`sum_t ||s_t - t_t||² = T ||mean(s)-mean(t)||² + sum_t ||(s_t-mean(s))-(t_t-mean(t))||²`.

The implementation accepts `[B,T,D]` student/target tensors, a `[B,T]` validity
mask, and optional integer group labels. It reports global totals plus grouped
`k=0`, `k=1..9`, and `k=10` counts when labels are provided. Invalid shapes,
non-finite values, and empty masks fail closed.

`scripts/audit_feature_loss_decomposition.py` provides an NPZ-only read-only
entry point; it never touches canonical artifacts. Unit tests verify the exact
identity, masking/group accounting, and shape validation.
