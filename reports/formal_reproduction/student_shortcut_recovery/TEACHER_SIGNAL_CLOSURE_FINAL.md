# Teacher-signal closure — final handoff

Date: 2026-09-09
Branch: \`repro/student-shortcut-recovery\`

## Decision

The final scientific state for this closure phase is:

\`NO_EXECUTED_BOUNDED_CONTROL_RECOVERS_BOUNDARY\`

This is a diagnostic handoff, not a formal conference reproduction result.
The official protocol remains exactly ten one-second task segments. No
10→16 conversion, label interpolation, canonical-cache overwrite, test
evaluation, second seed, schedule extension, or Full run was performed.

## Evidence chain

- Phase A direct visual logits:
  \`DIRECT_VISUAL_LOGIT_SIGNAL_HEALTHY_CURRENT_T10\`. Cached direct logits have
  mixed concordance \`0.629716\`, shuffle AUROC drop \`0.025589\`, and best
  temporal shift \`0\`.
- Teacher features: \`TEACHER_FEATURE_SIGNAL_DECODABLE\`, but
  \`TABLE2_FEATURE_PROBE_PROTOCOL_UNRESOLVED\`; the reconstructed probe is not
  claimed to be the paper's archival-exact Table 2 protocol.
- Phase B: \`BLOCKED_BY_TEACHER_FRAME_SAMPLING\`. The locked validation
  manifests contain no usable raw-video path, so a true uniform 8-frame
  comparison cannot be fabricated. Its positive path is fully implemented and
  tested against a fake raw decoder/locked-teacher boundary, including both
  direct and train-fit/validation-eval comparison metrics.
- Phase C: \`VISUAL_MEAN_COMPONENT_DOMINANCE_CONFIRMED\`. Across four strata
  and 128 read-only batches, mixed visual mean/centered gradient ratio is
  \`5.275533\`; this does not claim multi-loss directional agreement.
- D2: \`D2_BLOCKED_BY_PRETRAINED_ASSET_NOT_TESTED\`. The requested timm/Hugging
  Face visual weights were unavailable and timed out; no random substitute was
  used.
- D1 centered visual control: exactly \`800\` applied updates (\`803\` attempts,
  \`3\` AMP skips), seed \`42\`, validation-only. AP \`0.708303\`, AUROC \`0.603108\`,
  mixed tie-aware concordance \`0.499469\`, and mean temporal logit std
  \`0.0000478\`. Both preregistered recovery gates failed, so its precise state
  is \`D1_CENTERED_VISUAL_CONTROL_FAIL\`.
- D3 orchestration is repaired to register \`loss.alpha_strong_logit\` and read
  the Phase A direct-logit gate. D3 remains unexecuted because its positive
  analysis-only weight is not historically known and was not guessed.

## Reproducibility and scope

The compact D1 receipt is in \`TEACHER_SIGNAL_CONTROL_D1_RESULT.json\`; the
large checkpoint, cache and runtime logs remain on the 5090 under the recorded
diagnostic path and are not committed. \`TEACHER_SIGNAL_CLOSURE_SUMMARY.json\`
contains machine-readable values and the prior C2 evidence remains in
\`projector_collapse_summary.json\`.

Only D1 was executed. D2 is asset-blocked, Phase B lacks raw videos, and D3 is
now mechanically valid but weight-provenance-blocked. This branch does not
authorize formal Full training.

## Verification

The pre-E0 closure suite passed (\`43 passed, 2 skipped\`, exit \`0\`). After the
E0 edits, an independent targeted suite covering the changed controls, probe,
label alignment, and config resolver passed \`35 passed, 2 skipped\` (exit
\`0\`); changed-file Ruff, compileall, diff-check, and JSON/YAML parsing also
passed (exit \`0\`). The local full collection is environment-limited because
the host lacks \`timm\` (collection exit \`2\`), so no assertion failure is
attributed to E0. A prior fresh 839-file snapshot on the locked 5090 had 601
tests passing, but the E0 edits have not yet been deployed there. An earlier
query identified an RTX 4070 and was left untouched; the latest direct SSH
query now identifies the target RTX 5090 with 32,607 MiB.
