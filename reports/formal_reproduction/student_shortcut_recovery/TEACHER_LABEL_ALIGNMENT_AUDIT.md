# Teacher label/boundary alignment audit (A4)

This read-only audit loaded the official exported validation manifest and
selected its 1,967 mixed-label samples (`0 < k < 10`), preserving all ten
official task segments.  It derived onset/offset only from the supplied binary
labels; no annotation, interpolation, or temporal conversion was introduced.
Raw InternVideo2 features are `[1967,10,512]`; static C0/C1 projector outputs
are `[1967,10,256]`.  Query embeddings from the manifest were broadcast only
for the explicitly labelled `representation+query` probes.

| Representation | AP | AUROC | Pos–neg concordance |
|---|---:|---:|---:|
| raw | 0.534916 | 0.438346 | 0.437736 |
| centered raw | 0.514799 | 0.427077 | 0.411820 |
| raw + query | 0.536290 | 0.440819 | 0.437736 |
| C0 static projected | 0.576452 | 0.489487 | 0.516553 |
| centered C0 static projected | 0.515441 | 0.425311 | 0.415917 |
| centered C0 static projected + query | 0.593797 | 0.516756 | 0.415917 |
| C1 static projected | 0.565975 | 0.472818 | 0.488570 |
| centered C1 static projected | 0.515118 | 0.442728 | 0.414608 |
| centered C1 static projected + query | 0.530335 | 0.453188 | 0.414608 |

The C0 centered-static-plus-query AP gain over centered static is `+0.078356`
and the C1 gain is `+0.015217`; the corresponding raw gain is only `+0.001374`.
This is measurable query/teacher alignment evidence, so A4 does not by itself
block a clean clipping-scope control.  It is not sufficient to claim healthy
localization: onset/offset AUROC remains low (C0 `0.321338/0.291592`, C1
`0.322040/0.292706`) and the query multiplicity hash is unavailable because
the official manifest has no raw-video hash field.  That absence is reported,
not guessed.

Receipt: `phase_a/A4_teacher_alignment.json` on 5090; the implementation and
boundary tests pass.  The audit did not touch optimizer/checkpoint/cache state
and did not evaluate the test split.
