# Fixed-budget last-checkpoint comparison (A1)

This is a read-only comparison of the two 800-applied-step controls on the
same official validation loader.  Both exports have exactly 5,798 samples and
57,980 ordered task segments (`T_task=10`); no test loader was enabled.

| View | AP | AUROC | Predicted-positive rate | Mixed pair-weighted concordance |
|---|---:|---:|---:|---:|
| C0 trainable projector, last@800 | 0.7213457392 | 0.6199481023 | 1.000000 | 0.5213328195 |
| C1 static zero-LR projector, last@800 | 0.7323133188 | 0.6242927241 | 1.000000 | 0.5741143439 |
| C1 − C0 (last@800) | +0.0109675796 | +0.0043446218 | +0.000000 | +0.0527815244 |

The preregistered best-vs-best view remains separate: C0 best AP/AUROC is
`0.7417794173/0.6437222374`, C1 best is `0.7366111005/0.6349032370`, and
C1 − C0 is `−0.0051683168/−0.0088190003`.  Therefore last-vs-last does not
replace model selection and does not establish recovery.

The deterministic 100-repeat within-sample temporal shuffle audit reports
mixed-label AP mean drops of `−0.0000069167` (C0 last) and `+0.0007035948`
(C1 last), with AUROC mean drops `+0.0003049499` and `+0.0007980813`.
These small effects, together with a 100% predicted-positive rate, remain
consistent with the existing shortcut diagnosis.

## Receipts

- C0 eval-only exit code: `0`; validation metrics were emitted at
  `2026-09-04 21:51:09`.
- C1 eval-only exit code: `0`; validation metrics were emitted at
  `2026-09-04 22:10:58`.
- Both commands used the explicit diagnostic override
  `--allow-blocked-reproduction --eval-only --resume <last.pt>` and wrote only
  validation artifacts under their isolated `diagnostic/.../last_eval`
  directories.  No optimizer, checkpoint, cache, or test artifact was
  created by A1.
- Summary implementation: `scripts/audit_static_target_fixed_budget.py`;
  focused test result: `10 passed`, exit `0` across A1–A5 primitive tests.

Scientific authorization remains unchanged: formal Full, second seed, 3,200
step extension, and test evaluation are not authorized by this audit.
