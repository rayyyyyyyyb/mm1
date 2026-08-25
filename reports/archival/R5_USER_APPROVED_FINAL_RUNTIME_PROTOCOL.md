# R5 User-Approved Final Runtime Protocol

Date: 2026-08-25
Evidence kind: explicit user approval
Scope: canonical ACM MM 2026 OV-OrthKD reconstruction

## Final ruling

The conference paper contains a writing/terminology conflation. The experiment itself follows the official OV-AVEBench ten-segment protocol. All current reproduction records and active manuscript corrections use the following five independent quantities:

| Symbol | Value | Exact meaning |
|---|---:|---|
| `T_task` | 10 | ten official one-second task segments; ten labels and ten valid prediction positions |
| `T_max` | 16 | maximum student positional/model capacity only |
| `K_student` | 1 | one fixed official JPG keyframe per task segment |
| `K_teacher` | 8 | repeat the same official keyframe eight times for the visual teacher input |
| `V_test` | 1 | one fixed deterministic test forward |

## Locked behavior

- Each official video has exactly ten visual JPG observations, one for each one-second task segment.
- The historical student loader chooses the middle candidate within each segment group. Because the official published group contains exactly one JPG, this is a fixed read, not temporal random sampling.
- Student training applies spatial augmentation only: random horizontal flip and ColorJitter to that fixed keyframe. It does not select another time point.
- The InternVideo2 teacher receives eight copies of the same per-segment official keyframe. These are repeated frames, not eight distinct decoded frames.
- Validation and test use the fixed keyframe in one forward pass. There is no multi-crop, multi-clip, multi-view or view averaging.
- Labels, student logits, temporal teacher features and F1/AP/AUROC metric inputs remain aligned on `[B, 10]`/T=10.

## Explicitly rejected interpretations

The canonical runtime contains none of the following:

- sixteen independent images per one-second task segment;
- 160 visual student inputs per video;
- an executed 16-fps raw-video decode path;
- sixteen ground-truth labels or sixteen valid prediction positions;
- `10 -> 16` label interpolation, copying, resampling or relabelling;
- test-time multi-view ensembling.

The value 16 in `student.max_position_segments` is retained only as unused capacity above the observed T=10 sequence. Historical paper phrases such as “16 fps”, “16 temporal segments”, and “per 16-seg clip” are corrected as writing ambiguity and do not authorize a protocol change.

## Reproduction authority

This approval supersedes the temporal/frame-sampling wording in `R3_USER_APPROVED_RECONSTRUCTION.md` and `R4_USER_APPROVED_TEMPORAL_PROTOCOL.md` wherever they differ. It does not change the original table values, training objective or evaluator formulas. Formal execution remains evidence-gated until full teacher export, exhaustive artifact audit and the single real-data optimizer-step preflight pass.
