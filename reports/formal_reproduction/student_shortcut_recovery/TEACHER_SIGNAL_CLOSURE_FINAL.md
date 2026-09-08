# Teacher-signal closure — final handoff

Date: 2026-09-08
Branch: \`repro/student-shortcut-recovery\`

## Decision

The final scientific state for this closure phase is:

\`NO_BOUNDED_CONTROL_RECOVERS_BOUNDARY\`

This is a diagnostic handoff, not a formal conference reproduction result.
The official protocol remains exactly ten one-second task segments. No
10→16 conversion, label interpolation, canonical-cache overwrite, test
evaluation, second seed, schedule extension, or Full run was performed.

## Evidence chain

- Phase A corrected teacher probe: \`TEACHER_BOUNDARY_SIGNAL_HEALTHY\`.
  Cached direct logits have mixed concordance \`0.629716\`, and the direct
  shuffle/shift checks pass.
- Phase B: \`BLOCKED_BY_TEACHER_FRAME_SAMPLING\`. The locked validation
  manifests contain no usable raw-video path, so a true uniform 8-frame
  comparison cannot be fabricated. Its positive path is fully implemented and
  tested against a fake raw decoder/locked-teacher boundary, including both
  direct and train-fit/validation-eval comparison metrics.
- Phase C: \`SHORTCUT_AGREEMENT_CONFIRMED\`. Across four strata and 128
  read-only batches, mixed visual mean/centered gradient ratio is \`5.275533\`.
- Phase D: \`BLOCKED_BY_PRETRAINED_BACKBONE_ASSET\`. The requested timm/Hugging
  Face visual weights were unavailable and timed out; no random substitute was
  used.
- D1 centered visual control: exactly \`800\` applied updates (\`803\` attempts,
  \`3\` AMP skips), seed \`42\`, validation-only. AP \`0.708303\`, AUROC \`0.603108\`,
  mixed tie-aware concordance \`0.499469\`, and mean temporal logit std
  \`0.0000478\`. Both preregistered recovery gates failed.

## Reproducibility and scope

The compact D1 receipt is in \`TEACHER_SIGNAL_CONTROL_D1_RESULT.json\`; the
large checkpoint, cache and runtime logs remain on the 5090 under the recorded
diagnostic path and are not committed. \`TEACHER_SIGNAL_CLOSURE_SUMMARY.json\`
contains machine-readable values and the prior C2 evidence remains in
\`projector_collapse_summary.json\`.

The next action requires a new explicit design decision. This branch does not
authorize formal Full training.

## Verification

The final focused local suite passed (\`43 passed, 2 skipped\`, exit \`0\`); the two
skips are optional pretrained integrations unavailable on the local host. Local
compileall and changed-file Ruff passed (exit \`0\`, with the repository's existing
\`E402\` path-bootstrap pattern ignored). A fresh 839-file snapshot of the current
tree was extracted on the locked 5090: compileall passed and all 601 tests not
requiring the absent remote \`git.exe\` passed (exit \`0\`). The four Git-dependent
fixture files remain an explicitly isolated environment limitation, not a test
failure attributed to this change.
