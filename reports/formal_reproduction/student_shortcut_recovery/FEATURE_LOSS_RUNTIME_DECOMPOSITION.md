# Runtime feature-loss decomposition (A2)

The locked 5090 runtime evaluated one identical four-sample training batch for
initialization, C0 best/last, and C1 best/last.  The batch contains 40 valid
rows (`4 × T_task=10`), uses the configured `sum_feature_then_masked_mean_segments`
reduction, and is read-only.  The exact identity `L_total = L_mean +
L_centered` held within float32 round-off (maximum residual `4.3e-4`).

| State | normalized `L_mean` | normalized `L_centered` | normalized total | `k=0` / `k=10` samples |
|---|---:|---:|---:|---:|
| initialization | 167.622485 | 8.885765 | 176.508252 | 2 / 2 |
| C0 best@800 | 74.252588 | 8.047655 | 82.300232 | 2 / 2 |
| C0 last@800 | 74.898230 | 8.047928 | 82.946155 | 2 / 2 |
| C1 best@800 | 33.804736 | 8.047852 | 41.852588 | 2 / 2 |
| C1 last@800 | 33.116568 | 8.047646 | 41.164212 | 2 / 2 |

`L_mean` falls substantially after training while `L_centered` is almost
unchanged.  This is evidence about the representation geometry, not a claim
that the mean component alone causes the metric failure.

The component-wise student gradient receipts are finite and nonzero for the
visual encoder, visual projection, fusion, temporal encoder, and decision
projection.  For example, at C1 best the mean/centered norms are
`0.002817/0.0000369` (visual encoder), `0.05873/0.000141` (fusion),
`0.07368/0.0000693` (temporal encoder), and `0.40416/0.000125`
(decision projection).  The segment head is correctly zero for these feature
components because the feature loss enters before that head.

Receipts: `phase_a/A2_initialization.json`, `A2_C0_best.json`,
`A2_C0_last.json`, `A2_C1_best.json`, and `A2_C1_last.json` on the locked
5090.  The corresponding compact JSON files were fetched and checked locally;
the focused A2 test passes as part of the 10-test suite.
