# AMP, clipping, and applied-step audit

This report is populated from `optimizer_receipts.jsonl` and
`optimizer_step_summary.json` for the noncanonical paired control. An attempted
step is counted before `GradScaler.step`; an applied step is counted by the
optimizer post-hook. Thus an overflow is never silently treated as an update.

## C0 status observed so far

- Attempts: `805`
- Applied updates: `800`
- AMP overflows/skips: `5` (all at scaler warm-up; scale decreased until the
  first finite update)
- Applied rows clipped: `800/800` (`100%`)
- Strong-projector gradient contribution share: mean `0.510517`, median `0.512074`

The final C0 summary, validation metrics, and the corresponding C1 values will
be appended after both controls exit cleanly. No test evaluation is enabled.
