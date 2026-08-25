# Final Runtime Protocol and Readiness Design

Date: 2026-08-25

## Approved runtime contract

The formal OV-OrthKD reproduction uses five independent quantities that must never be substituted for one another:

| Quantity | Exact value | Runtime meaning |
|---|---:|---|
| `T_task` | 10 | ten official one-second task segments; labels, student logits, teacher features and metric inputs all use this axis |
| `T_max` | 16 | student positional/model capacity only; it is not an observed task length |
| `K_student` | 1 | one official fixed JPG keyframe per task segment |
| `K_teacher` | 8 | repeat that same keyframe eight times for the InternVideo2 teacher input |
| `V_test` | 1 | one deterministic test forward; no multi-crop, multi-clip or multi-view averaging |

The official dataset therefore contributes exactly ten visual observations per video. Training augmentation is spatial only: horizontal flip and ColorJitter on the fixed keyframe. There is no temporal random sampling, no `10 -> 16` label conversion, no executed 16-fps canonical decode, no 160-frame student input and no test-time view ensemble.

## Enforcement

One machine-readable validator is the source of truth for the five quantities. Formal training, canonical readiness and real-data preflight must all reject a configuration that changes or omits any value. The preflight receipt records both the declared contract and observed tensor shapes so the ten-position label/logit/teacher alignment is auditable.

Historical documents remain evidence of what was believed at the time, but active reports explicitly mark any earlier 16-fps or 16-task-segment wording as superseded. Synthetic `T=16` checks are capacity tests only.

## Teacher export bootstrap fix

The current exporter binds every record to the SHA256 of the entire teacher lock, while the same lock contains mutable export status and final cache hashes. This creates a cycle: export is forbidden until the lock is ready, but the lock cannot become ready until export completes; changing it afterwards invalidates every record receipt.

The replacement binding is `teacher_identity_sha256`, computed only from immutable teacher identity and inference semantics: exact upstream repository and commit, implementation class, checkpoint filename and SHA256, preprocessing, output dimensions, determinism and export protocol. Mutable progress, smoke timestamps, full-export status and cache hashes are excluded. Export is allowed only after exact identities and real smoke have passed; changing a checkpoint or preprocessing field still invalidates all resume receipts, while updating final audit metadata does not.

## Completion flow

1. Enforce the approved runtime contract and immutable teacher identity digest with failing tests first.
2. Correct active configuration, locks, reports and comments without changing the official ten-segment training or evaluation logic.
3. Independently verify focused tests locally and the full suite on the 5090 environment.
4. Run resumable, split-safe full teacher export on the 5090, then audit every artifact and bind the resulting manifests/cache root.
5. Run at most one real-data one-step forward/backward preflight, record observed shapes, rebuild canonical readiness and create the ready configuration only if every gate passes.
6. Do not start formal student training in this stage.

## Acceptance criteria

- All formal entry points reject any protocol other than `10/16/1/8/1` with repeated teacher frames and single-view test evaluation.
- Teacher resume receipts survive mutable lock-status updates but fail after any teacher identity mutation.
- Full train/validation/test teacher manifests and all artifact bytes pass exhaustive audit.
- Exactly one real optimizer-step preflight passes with label/logit task axes of ten.
- Canonical readiness is evidence-backed; otherwise the final status remains blocked with explicit causes.
