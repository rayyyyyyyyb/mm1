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
The preregistered teacher gates all passed, so Phase A is
`TEACHER_BOUNDARY_SIGNAL_HEALTHY`.

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

## Phase C — stratified shortcut agreement

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
`SHORTCUT_AGREEMENT_CONFIRMED`. This is a diagnostic classification; it does
not authorize a Full run.

## Phase D and authorization

The code now resolves `visual_pretrained` and `audio_pretrained` independently;
legacy `pretrained` is accepted only when both new fields are absent. The
random visual, current C2 visual, and random audio controls completed on 256
mixed records per split. The timm-pretrained visual branch was blocked because
the requested Hugging Face weights were not cached and repeated downloads
timed out; this is recorded as `BLOCKED_BY_PRETRAINED_BACKBONE_ASSET`, never as
a random-weight substitute. No optimizer is constructed by any Phase A–D
audit, and no bounded control is authorized because the Phase D frozen-
representation gate cannot be evaluated. Formal Full, second seed, 3,200-step
extension, test evaluation, and canonical-cache overwrite remain forbidden.

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
not recover the missing boundary signal. The scientific classification is
`NO_BOUNDED_CONTROL_RECOVERS_BOUNDARY`. D2 (visual-pretrained) remained blocked
by unavailable Hugging Face weights, and D3 remained fail-closed because its
registered gate was not met; neither was trained.

The complete compact receipt is
`TEACHER_SIGNAL_CONTROL_D1_RESULT.json`; the large checkpoint and raw runtime
logs remain on the 5090 diagnostic directory only.

## Closure decision

The teacher boundary signal is healthy (`TEACHER_BOUNDARY_SIGNAL_HEALTHY`),
but the stratified audit confirms a visual mean/centered shortcut and the only
eligible bounded intervention fails to restore temporal decision variation or
mixed-label ordering. Phase B cannot establish true raw-video multiframe
provenance, while Phase D cannot establish a pretrained-visual advantage.
Therefore the final handoff state is
`NO_BOUNDED_CONTROL_RECOVERS_BOUNDARY`; formal Full, a second seed, schedule
extension, test evaluation, canonical-cache overwrite, and any 10→16 temporal
conversion remain forbidden.
