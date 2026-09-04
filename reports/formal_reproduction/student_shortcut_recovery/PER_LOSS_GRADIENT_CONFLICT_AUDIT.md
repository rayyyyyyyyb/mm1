# Per-loss gradient conflict audit (A3)

`autograd.grad` was applied to BCE, weighted visual feature loss, and weighted
text alignment on the same four-sample, 40-row train batch.  Parameters,
buffers, RNG state, optimizer state, and checkpoints were not mutated.  Cosines
are computed on the same student parameter group/module; zero-gradient modules
are excluded from finite-count statistics.

| State | BCE–visual median cosine | text–visual median cosine | Classification |
|---|---:|---:|---|
| C0 best@800 | +0.066951 | +0.006988 | `GRADIENT_CONFLICT_NOT_YET_IDENTIFIED` |
| C0 last@800 | +0.349349 | −0.093023 | `GRADIENT_CONFLICT_NOT_YET_IDENTIFIED` |
| C1 best@800 | +0.266063 | −0.085859 | `GRADIENT_CONFLICT_NOT_YET_IDENTIFIED` |
| C1 last@800 | +0.292903 | −0.108260 | `GRADIENT_CONFLICT_NOT_YET_IDENTIFIED` |

The preregistered intrinsic-conflict criterion is a visual-pair median below
`−0.2` with non-negligible norms.  None of the four measured states meets it;
the earlier `BLOCKED_BY_GRADIENT_CONFLICT` label is therefore not supported by
same-parameter directional evidence.  This does not erase the separately
observed global clipping coupling from the C1 receipts.

Receipts: `phase_a/A3_C0_best.json`, `A3_C0_last.json`,
`A3_C1_best.json`, and `A3_C1_last.json` on 5090.  Focused A3 tests pass; no
training or test evaluation was performed.
