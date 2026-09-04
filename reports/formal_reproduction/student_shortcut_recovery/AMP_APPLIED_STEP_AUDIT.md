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

The C0 final summary is unavailable as a separate
`optimizer_step_summary.json`, although the complete JSONL receipt set and
`final_metrics.json` are present. C0 therefore has an independently verifiable
`805`/`800` attempt/applied count with a retained runtime-integrity caveat. The
corresponding C1 values will be appended after C1 exits cleanly. No test
evaluation is enabled.

## C1 final receipt audit

- Attempts: `805`
- Applied updates: `800`
- AMP overflows/skips: `5` (the same scaler warm-up pattern as C0; unexplained
  skips: `0`)
- Applied rows clipped: `800/800` (`100%`)
- Strong-projector gradient contribution share: mean `0.811494`, median
  `0.819354` (minimum `0.108261`, maximum `0.878841`)
- Student contribution share: mean `0.188429`, median `0.180558`; weak
  projector share is `0`; text-projector share mean is `0.0000772`.

The static C1 projector has zero learning rate but retains gradient flow, so
its large share is a direct receipt of the competing pathway rather than
parameter motion. The complete C1 JSONL receipt and summary agree, and no test
evaluation is enabled.
