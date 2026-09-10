# Independent pretrained-representation audit (Phase D)

## Corrected gate result

The corrected zero-training gate ran on the RTX 5090 on 2026-09-10. It used
256 stratified mixed records per split, seed 42, official `T=10`, train-fit /
validation-eval probes, exact sample-ID alignment, one shared query projection,
one visual projection per feature dimension, and real query strings for macro
grouping.

| Representation | VQP mixed concordance | Status |
|---|---:|---|
| random visual | 0.4906183369 | valid corrected measurement |
| current C2 visual checkpoint | 0.5174840085 | valid corrected measurement |
| random audio positive control | 0.6788912580 | valid corrected measurement |
| exact timm-pretrained visual | 0.5127931770 | valid corrected measurement |
| query/position only (QP) | 0.4942430704 | shared baseline |

The exact pretrained candidate gains `0.0221748401` over random visual, below
the required `0.05`, and gains `0.0185501066` over QP, below the required
`0.02`. Both registered conditions were conjunctive. The resulting scientific
status is therefore `D2_ZERO_TRAINING_DECODABILITY_GATE_FAIL`. This is a
zero-training decodability result, not a verdict on pretrained initialization
after gradient training.

The earlier `0.523028 / 0.488699 / 0.455437` measurements are historical only.
They cannot be compared directly with the corrected numbers because repeated
train-loader passes were position-paired before ID alignment and QP/VQP used
different query maps. They are not used by the present decision.

## Identity, map, and asset closure

Every encoder pass carries the real manifest ID, real query, label, query
embedding, sequence mask, and selected segment indices. Subsequent shuffled
passes are reordered to the random-visual canonical ID order and all
non-feature fields are verified. The independent audit confirmed identical
post-alignment hashes for all four passes on both splits.

All QP results are byte-for-byte identical across representation rows. Every
probe records query-map SHA256
`6033fee877eb4380864eb544d622330d5d20a11e78e0d5a6c1753c4964f4a6f3`;
the common 768-dimensional visual-map SHA256 is
`51d292437d75fefa03e85125d0690319685ad8fe4bba72cb38a3292c6457c028`.
Validation macro grouping uses 53 real query strings whose counts total 256.

The visual backbone is
`timm/convnextv2_tiny.fcmae_ft_in22k_in1k`, exact revision
`b1dd46230e80bf4cc3fa0c3c905db2c3ec53a817`. The 114,561,694-byte
safetensors file SHA256 is
`6652fd90fc9c23977659e58515778e16fbbcd43f0b01fc693089cebe6d64c2a9`.
Offline load produced backbone-state SHA256
`d8bcbc7225bedef0202e5f47613a4232eab9a7bbeef2be571831266361bafe90`,
27,866,496 parameters and feature dimension 768, with no missing keys.

## Audit and authorization

The producer exited 0 with empty stderr. The result JSON SHA256 is
`5f29e4ca172334e9e041cac7e57ca11c6adb9d5d5686c7629cd8435d680f898c`.
The independent auditor returned `ARTIFACT_AUDIT_PASS`, independently
recomputed the failed thresholds, and confirmed no test manifest, student
optimizer, backward/update, or model checkpoint.

D2 800-step training is not authorized. Formal Full, D3, test evaluation, a
second seed, and schedule extension remain stopped. See
`D2_ZERO_TRAINING_GATE_REPORT.md` and `d2_zero_training_gate_audit.json`.
