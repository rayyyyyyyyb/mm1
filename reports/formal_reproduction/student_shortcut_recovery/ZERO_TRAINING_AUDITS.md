# S7 zero/near-zero-training audits

Date: 2026-09-01

Status: **A–F artifact integrity PASS; only S8 identity + fixed-equal-gate is authorized. Formal Full training remains blocked.**

## Scope and immutable boundary

These audits diagnose the completed S7 run without reinterpreting its preregistered failure. They use the official `T_task=10` test timeline, 5,820 samples and 58,200 ordered segment-logit/label pairs. There is no 10→16 conversion, no test-time multi-view average and no optimizer step on the loaded S7 or canonical Full modules.

- Scientific implementation: `c181ffb3297ff480a0d01186c626acce7c66afff`, exact clean on the 5090.
- Runtime-control commit: `9786eb4da95a99d123078674508dbe340170cef8`.
- A–E reconstructed step zero plus read-only S7 states 400/800/1200; it constructed no optimizer and wrote no checkpoint.
- F took exactly one AdamW step only on disposable in-memory projector/decision clones and persisted nothing.
- Independent audit recomputed the 17-mode NPZ metrics and verified ten source receipts, `T=10`, finiteness, donor maps, checkpoint immutability and the disposable-clone boundary.

## A. Official visual content is real

The full byte-and-decoded-RGB audit covered all 58,200 official JPGs. Its canonical digest is `1dc149cc761241567b9e789f03b0b7ccb537d82773cc53588fdd95af19e7d298`.

| Check | Result |
|---|---:|
| Videos / frames | 5,820 / 58,200 |
| Adjacent decoded-RGB MAD, mean | 25.290085 |
| Adjacent decoded-RGB MAD, range | 0.0–222.609861 |
| Within-video duplicate extras | 307 |
| Videos containing a within-video duplicate | 189 (3.25%) |
| Global duplicate extras | 348 |

The isolated zero-MAD pairs are explained by the explicitly counted duplicates. The corpus is not content-identical or globally corrupt, so bad official frames are not the cause of the visual shortcut.

## B. Visual temporal variation collapses during Student training

The stored `global_step_before_update=0` receipt reconstructs the exact random Student state; it is not represented as a saved checkpoint. Its segment-head weight L2/bias are `0.570144/-0.025373`, and its full Student state SHA256 is `1cad1d7d1432710b900fd504714853bad81bd12ee074ea9c08dfa1dd0f749678`.

| State | Raw-pixel temporal std | Visual-backbone temporal std | Projected-token temporal std | Backbone collapse vs step 0 | Projected collapse vs step 0 |
|---|---:|---:|---:|---:|---:|
| reconstructed step 0 | 0.484911 | 0.218586 | 0.066350 | 1.00× | 1.00× |
| step 400 | 0.484911 | 0.004290 | 0.001516 | 50.95× | 43.77× |
| step 800 | 0.484911 | 0.003402 | 0.001046 | 64.26× | 63.44× |
| step 1200 | 0.484911 | 0.003412 | 0.001051 | 64.06× | 63.15× |

Raw input variation is unchanged, while most of the collapse is already present at the visual-backbone output by step 400. The projector does not create the collapse by itself: projected RMS grows from `0.353149` at step zero to `1.187720` at step 1200 even as its within-video temporal variation disappears.

## C–D. A fixed gate cannot recover an already collapsed visual path

The concat-fusion first-linear visual/audio/query block norms remain nearly symmetric: `6.535/6.534/6.530` at reconstructed step zero and `6.624/6.665/7.072` at step 1200. Static fusion-column magnitude therefore does not explain the modality loss.

The exact first-test-batch logit Jacobians do. All 40 valid logits were differentiated without accumulating parameter gradients:

| State | Visual Jacobian L2 | Audio Jacobian L2 | Query Jacobian L2 | Audio/visual | Query/visual |
|---|---:|---:|---:|---:|---:|
| reconstructed step 0 | 2.236847 | 2.657968 | 4.683254 | 1.19× | 2.09× |
| step 400 | 0.006247 | 0.514050 | 1.338267 | 82.28× | 214.21× |
| step 800 | 0.001385 | 0.393753 | 1.142958 | 284.30× | 825.24× |
| step 1200 | 0.004885 | 0.861018 | 2.641338 | 176.25× | 540.68× |

At the S7 best checkpoint, forcing five literal visual/audio ratios still leaves visual-zero mixed-label AP nearly unchanged:

| Forced visual/audio ratio | Original mixed AP | Visual-zero mixed AP | AP drop |
|---|---:|---:|---:|
| 0/1 | 0.634675 | 0.634675 | 0 |
| 0.25/0.75 | 0.632275 | 0.632270 | 0.00000475 |
| 0.5/0.5 | 0.629167 | 0.629151 | 0.00001625 |
| 0.75/0.25 | 0.625058 | 0.625034 | 0.00002417 |
| 1/0 | 0.615946 | 0.615880 | 0.00006618 |

This does not prove that a fixed gate from initialization is ineffective. It proves only that changing the gate at inference cannot recreate visual information after the backbone/path has already collapsed. That distinction is why the only authorized next cell is the preregistered S8 from-scratch fixed-equal control.

## E. Audio carries temporal order, while large class/sample bias survives

The mixed-label stratum contains 1,941 videos; its positive segment rate is `0.571355`. K0/mixed/K10 counts are `1,406/1,941/2,473`.

| Mode | Mixed AP | AP drop vs original | AUROC | Pairwise concordance |
|---|---:|---:|---:|---:|
| original | 0.634651 | 0 | 0.597801 | 0.667107 |
| visual zero | 0.634651 | 0.00000040 | 0.597800 | 0.667107 |
| audio zero | 0.627364 | 0.007287 | 0.561886 | 0.535568 |
| both zero | 0.627199 | 0.007452 | 0.561954 | 0.535568 |
| same-query audio donor | 0.614237 | 0.020414 | 0.555583 | 0.519189 |
| different-query audio donor | 0.613282 | 0.021369 | 0.550632 | 0.505338 |
| within-sample audio temporal shuffle | 0.613549 | 0.021102 | 0.559235 | 0.516604 |

The similar same-query and different-query donor damage shows that query matching alone does not preserve localization. Donor replacement or temporal shuffling removes most mixed-video pairwise ordering, so the learned audio path contains real sample-specific temporal information. At the same time, both-zero mixed AP remains above the `0.571355` positive rate and K0/K10 mean scores retain a large separation (`0.178229/0.236142`), confirming a substantial query/sample/class prior in addition to the audio signal.

## F. The canonical Full projector path is weakly scaled, not disconnected

F used canonical Full checkpoint step 400 (`01cdb036...f392`), the exact first four-sample training batch and 40 valid T=10 rows. The existing feature-mean reduction and the intended feature-sum reduction differ by the exact feature dimension 256:

| Reduction | Loss | Projector grad L2 | Student-decision grad L2 | Target variance |
|---|---:|---:|---:|---:|
| mean over 256 features | 0.007289 | 0.108157 | 0.001687 | 0.009870 |
| sum over 256 features | 1.865892 | 27.688309 | 0.431960 | 0.009870 |

Observed sum/mean ratios are exactly `256` for the loss and both gradient norms. One real AdamW step (`lr=2e-4`, weight decay `0.01`) on disposable clones changed the clone projector SHA, changed the decision SHA and changed target variance `0.009870→0.008443`. The loaded source projector SHA stayed `85615cc7...a45`, all source gradients remained `None`, and no updated checkpoint was written. The projector is trainable; its current loss reduction attenuates this signal by 256×.

## Independent audit and decision

The independent audit is `PASS`, `claim_level=artifact_integrity_only`, with clean HEAD `c181ffb...`, 17 modes, 5,820 samples, 58,200 segments and independently recomputed metric digest `2801f7698190113737cf7516008803a597a3be1aa2b0b16eeb16a70ecb89a22`. It intentionally sets `scientific_success_claimed=false`.

The preregistered S8 blockers are all cleared:

- A–F integrity is PASS and all outputs are finite.
- The official JPG content is not identical/corrupt.
- Reconstructed step-zero identity is supported without fabricating a saved checkpoint.
- Every label, logit and metric remains on official `T=10`.
- All S7/canonical source and checkpoint hashes are resolved and unchanged.

Therefore **only S8 (`identity_passthrough` + `fixed_equal` gate from initialization) is authorized**. Formal Full training, S9, second seeds, extended schedules, canonical loss changes and removal of the full-run guard remain prohibited. S8 must preserve S7 seed 42, random initialization, augmentation, concat fusion, Student-only BCE, three 400-batch epochs and diagnostic checkpoints.

## Published and remote-only evidence

Small review artifacts are in [evidence/zero_training](evidence/zero_training/README.md). The remote-only intervention NPZ is 9,623,269 bytes with SHA256 `061fea68cc4478ce67a62d50fbbe58714f9e0db82cb7db24aaf0f1374cc9c45f`; it is intentionally excluded from Git together with checkpoints, data, caches, bundles and logs.
