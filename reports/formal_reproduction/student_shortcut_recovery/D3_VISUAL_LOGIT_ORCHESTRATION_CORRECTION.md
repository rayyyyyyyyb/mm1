# D3 visual-logit orchestration correction

Date: 2026-09-09

## Defect and repair

The original D3 registration was invalid: it declared `student.path_mode` as
the single scientific change even though visual-teacher logit distillation is
enabled by `loss.alpha_strong_logit`. Its authorization also read
`phase_d.visual_logit_gate_pass`, a field Phase D never produces.

The repaired runner now:

- registers only `loss.alpha_strong_logit` as the D3 scientific change;
- recomputes authorization from Phase A direct-logit mixed concordance,
  temporal-shift, and within-video shuffle evidence;
- rejects a declared gate that disagrees with those measured values;
- requires a finite positive logit-KD weight;
- preserves `student.path_mode=explicit_projected` and
  `confidence_weighting=false`;
- mechanically compares the materialized configuration with the fixed C2
  baseline and rejects every additional scientific difference;
- requires exactly 800 applied updates and absence of test predictions.

Tests cover positive and negative authorization, the exact single-variable
diff, nonzero strong-logit loss and student-logit gradient, and the complete
800-step/no-test command receipt path.

## Current execution status

`D3_ORCHESTRATION_REPAIRED_WEIGHT_UNRESOLVED_NOT_EXECUTED`

The paper marks visual-logit KD as analysis-only and gives the default recipe a
zero weight, but it does not publish a positive analysis-control weight. No
positive value is committed or guessed. A real D3 wrapper must be created only
after either archival provenance is found or a separately preregistered
train-only gradient-matching receipt locks the value. No D3 training, test
evaluation, second seed, schedule extension, or Full run occurred in E0.
