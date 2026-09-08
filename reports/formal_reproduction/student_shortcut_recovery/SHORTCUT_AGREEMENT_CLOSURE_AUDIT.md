# Stratified shortcut-agreement closure audit (Phase C)

The locked C2 best checkpoint was evaluated without constructing an optimizer
or mutating parameters. The validation manifest was partitioned into disjoint
`k=0`, `1<=k<=9`, `k=10`, and mixed-only pools. Each pool contributed 32
independent batches of four samples (128 batches total).

| Pool | Mean/centered visual-gradient ratio | Mean/centered loss ratio | Clipping engaged |
|---|---:|---:|---:|
| k=0 | 5.7041 | 4.5391 | 100% |
| 1<=k<=9 | 6.1378 | 4.6593 | 100% |
| k=10 | 9.4597 | 7.9223 | 100% |
| mixed-only | 5.2755 | 4.0981 | 100% |

The mean-plus-centered squared-error identity held for every batch. All
parameter snapshots and RNG snapshots were unchanged. The preregistered gate
(ratio ≥2 and clipping in ≥50% of batches in every pool) passed, so the
diagnostic classification is `SHORTCUT_AGREEMENT_CONFIRMED`.

This is an attribution result, not a training authorization. Full training,
second seed, schedule extension, test evaluation, and canonical-cache writes
remain forbidden; D1–D3 controls require their own explicit gates.
