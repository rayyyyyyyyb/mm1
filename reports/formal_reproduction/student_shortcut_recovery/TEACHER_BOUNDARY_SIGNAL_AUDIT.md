# Teacher-boundary signal audit

## Scope

This is a read-only audit receipt for the noncanonical C0/C1 control. The
official task timeline remains exactly `T_task=10`; no label, logit, or metric
conversion to 16 positions is permitted.

## Evidence status

The current training receipts and validation prediction artifacts contain
official `[B,10]` labels/logits and segment counts, but they do not serialize an
explicit transition-boundary annotation. The new read-only validation geometry
receipts do provide per-segment raw/projected teacher and student decision
arrays for 1,967 mixed-label videos. They show, at C1 best, projected-target
temporal standard deviation `0.1682058886`, student-decision temporal standard
deviation `0.0013909233`, and projected-to-decision distance correlation
`0.3277767299`; these are geometry measurements, not boundary labels. A
transition-boundary-specific score remains **UNKNOWN** and is not inferred from
logits or from the model-capacity setting `max_position_segments=16`.

The fixed-batch diagnostic records and the new full mixed-validation geometry
receipts provide shape-checked teacher/projected and student geometry, gradient
receipts, and valid-mask accounting. They are not a substitute for a
boundary-specific measurement. If a future authorized read-only extraction supplies the six arrays required by
`scripts/audit_static_target_root_cause.py`, this report can be extended with
the resulting boundary metrics without changing the training protocol.

## Guard

Because the boundary measurements are missing, this audit cannot pass a
scientific gate and does not authorize a 3200-step extension or formal Full.
