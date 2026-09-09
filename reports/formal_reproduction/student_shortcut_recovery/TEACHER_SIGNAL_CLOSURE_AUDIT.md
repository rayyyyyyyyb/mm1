# Teacher-signal and shortcut-agreement closure audit

Date: 2026-09-06
Branch: `repro/student-shortcut-recovery`
All probes use the official `T_task=10` timeline. No label interpolation,
replication, or temporal conversion was performed.

## Phase A — corrected teacher probe

The corrected audit fits every readout on the train manifest and evaluates it
on the disjoint validation manifest. Query IDs come from `manifest.query` and
query vectors come from `text_embedding_path`; they are never substituted for
one another. The readout is a disposable `StandardScaler + SGDClassifier`
with fixed label-independent common-space maps and `[v,q,v*q,position]`
interaction features. Ties receive half credit, all adjacent transitions are
retained, and the direct-logit sweep tests shifts `{-2,-1,0,+1,+2}`.

| Probe | Validation AP | Validation AUROC | Mixed video-macro concordance |
|---|---:|---:|---:|
| raw teacher | 0.816315 | 0.738423 | 0.594799 |
| centered raw teacher | 0.662413 | 0.539267 | 0.613361 |
| static projected (C2 projector, hash unchanged) | 0.799585 | 0.719744 | 0.588891 |
| centered static projected | 0.624057 | 0.537075 | 0.604537 |
| cached direct visual logits | 0.771935 | 0.707681 | 0.629716 |
| query-only + position (QP) | 0.677364 | 0.613488 | 0.571924 |
| raw + query interaction | 0.710520 | 0.667195 | 0.605202 |
| projected + query interaction | 0.765984 | 0.697712 | 0.611253 |

The cached direct-logit shift sweep selected offset `0` (status `PASS`). Its
100 within-video shuffles reduced AUROC by `0.025589`; direct mixed
concordance was `0.629716`. Transition AUROC for raw teacher was `0.579906`
(onset `0.548036`, offset `0.546989`), with `3,950` validation transitions.
The direct-logit gate passes, so the narrow Phase A status is
`DIRECT_VISUAL_LOGIT_SIGNAL_HEALTHY_CURRENT_T10`. The corrected raw-feature
probe also establishes `TEACHER_FEATURE_SIGNAL_DECODABLE`, but its
StandardScaler/SGD/common-space/interaction protocol is not published in the
paper and its AP/AUROC (`0.816315/0.738423`) exceed the Table 2 feature-probe
numbers (`0.764/0.669`). It is therefore explicitly
`TABLE2_FEATURE_PROBE_PROTOCOL_UNRESOLVED`, not archival-equivalent evidence.

Data receipt: train `13,182` samples / `131,820` segments and validation
`5,798` / `57,980`; validation mixed samples `1,967`. Raw teacher feature
shape is `[10,512]`, query embedding shape `[1024]`, and labels/logits remain
`[10]`. The official manifest has no raw-video hash field. The C2 projector
checkpoint used by the audit has SHA256
`1b997952d2f9bb89b3783352655b044671a72a84ed76dcd6c4b8be6bf29cecf0`.

## Phase B — true multiframe sampling

The deterministic 512-record mixed validation sample had:

| Quantity | Count |
|---|---:|
| records selected | 512 |
| records with a raw-video field | 0 |
| existing non-empty raw-video paths | 0 |
| supported video paths | 0 |
| records marked raw-video unavailable | 512 |

The canonical manifests expose only official JPG keyframes. Because no
`raw_video_path`, `official_video_path`, or `video_path` is available, a true
uniform 8-frame comparison cannot be run without fabricating inputs. The
phase therefore ends as `BLOCKED_BY_TEACHER_FRAME_SAMPLING`; canonical teacher
cache and checkpoints were not touched.

The otherwise-unreachable positive path is complete and independently tested:
when official raw videos are provided, it uses uniform-center timestamps inside
each of the ten official one-second task segments, exports `[10,8,H,W,3]`
views through the locked InternVideo2 transform/model, and compares them with
repeat-keyframe receipts using direct-logit, 100-shuffle, transition,
query-conditioned train-fit/validation-eval, and temporal-geometry metrics.
Missing raw videos, teacher identity, or a separate train receipt still blocks
the comparison rather than weakening the protocol.

## Phase C — stratified visual mean-component dominance

Using the locked C2 best checkpoint and validation-only data, four disjoint
strata were audited: `k=0`, `1<=k<=9`, `k=10`, and a separate mixed-only pool.
Each has 32 independent batches (batch size 4), for 128 batches total.

| Stratum | Mean/centered visual gradient ratio | Mean/centered loss ratio | Clip engaged |
|---|---:|---:|---:|
| `k=0` | 5.7041 | 4.5391 | 1.000 |
| `1<=k<=9` | 6.1378 | 4.6593 | 1.000 |
| `k=10` | 9.4597 | 7.9223 | 1.000 |
| mixed-only | 5.2755 | 4.0981 | 1.000 |

All batches preserved parameters and RNG state. The preregistered gate
(mean/centered gradient ratio at least 2 and clipping engaged in at least
half the batches in every stratum) passed, yielding
`VISUAL_MEAN_COMPONENT_DOMINANCE_CONFIRMED`. The audit computes inter-loss
cosines, but they do not enter this gate, so it does not claim BCE/text/visual
directional agreement. This is a diagnostic classification and does not
authorize a Full run.

## Phase D and authorization

The code now resolves `visual_pretrained` and `audio_pretrained` independently;
legacy `pretrained` is accepted only when both new fields are absent. The
random visual, current C2 visual, and random audio controls completed on 256
mixed records per split. Those historical metrics are retained, but the prior
pretrained branch is rejected because its repeated loader passes were not
aligned by real sample ID. E0.1 now aligns every pass by ID, verifies all
non-feature identity fields, shares one projection map family, and groups
per-query macro by real query strings.

The exact asset passed byte verification, two identical offline timm loads,
and bitwise non-visual initialization parity on the RTX 5090. The resulting
readiness status is `D2_PROBE_READY_FOR_ZERO_TRAINING_GATE`; the corrected
zero-training gate itself was deliberately not executed. Therefore D2 still
has no scientific result and no bounded training is authorized. Formal Full,
second seed, 3,200-step extension, test evaluation, and canonical-cache
overwrite remain forbidden.

## Phase D1 — centered visual-feature control

D1 was the only control authorized: `per_sample_temporal` centering of the
strong visual feature loss, with the C2 projector update modes and positive-LR
clipping held fixed. It ran on seed `42`, validation-only, for exactly `800`
applied optimizer updates (`803` attempts, `3` AMP skips). An independent
post-run audit verified the step receipt, `[B,10]` prediction alignment, and
absence of test predictions.

| Metric | D1 result | preregistered gate |
|---|---:|---:|
| validation AP | 0.708303 | informational |
| validation AUROC | 0.603108 | informational |
| mixed validation tie-aware concordance | 0.499469 | ≥ 0.60 |
| mean decision temporal logit std | 0.0000478 | ≥ 0.003 |

The mixed-boundary and temporal-variation gates both failed, so centering did
not recover the missing boundary signal. The control-specific classification
is `D1_CENTERED_VISUAL_CONTROL_FAIL`. Relative to C2, validation AP fell from
`0.733609` to `0.708303`, AUROC from `0.634837` to `0.603108`, mixed
concordance from `0.509331` to `0.499469`, and decision temporal std from
`0.001477` to `0.0000478`. This rejects this unrenormalized centered-only
diagnostic under the current reconstructed protocol; it does not reject every
centered-supervision design or the paper's absolute-geometry feature loss.

D2 800-step training remains unexecuted; only its corrected zero-training probe
is now ready. Independent review also found that
D3 had incorrectly registered `student.path_mode` and read a nonexistent
Phase D gate. E0 repairs D3 to use `loss.alpha_strong_logit` and the Phase A
direct-logit gate, while preserving `student.path_mode=explicit_projected` and
`confidence_weighting=false`. No D3 training is executed because the positive
analysis-only weight has no archival provenance and must not be guessed.

The complete compact receipt is
`TEACHER_SIGNAL_CONTROL_D1_RESULT.json`; the large checkpoint and raw runtime
logs remain on the 5090 diagnostic directory only.

## Closure decision

Current-T10 direct visual logits are healthy, feature signal is decodable under
a non-archival-exact probe, and the stratified audit confirms visual
mean-component dominance under strong clipping. Only D1 was actually executed,
and it failed; Phase B, D2, and corrected D3 remain unanswered or unexecuted.
Therefore the corrected final handoff state is
`NO_EXECUTED_BOUNDED_CONTROL_RECOVERS_BOUNDARY`, not a claim that every planned
control failed. Formal Full, a second seed, schedule extension, test evaluation,
canonical-cache overwrite, and any 10→16 temporal conversion remain forbidden.
