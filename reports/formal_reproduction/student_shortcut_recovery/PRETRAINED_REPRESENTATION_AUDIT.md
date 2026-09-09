# Independent pretrained-representation audit (Phase D)

The prior valid measurements were zero-training, validation-only probes on
256 stratified mixed records per split (seed 42, official `T=10`). They are
retained below only as historical context; the pretrained row has not yet been
run under the corrected E0.1 protocol.

| Representation | VQP mixed concordance | Status |
|---|---:|---|
| random visual | 0.523028 | prior measurement |
| current C2 visual checkpoint | 0.488699 | prior measurement |
| random audio control | 0.455437 | prior measurement |
| timm-pretrained visual | not run | readiness passed; scientific gate not executed |

The corrected code resolves `visual_pretrained` and `audio_pretrained`
independently; legacy `pretrained` is only a paired fallback when both explicit
fields are absent. Each encoder pass is aligned by real sample ID and verifies
its labels, query strings, query embeddings, sequence mask, and selected
indices. QP/VQP share the same query map, passes with the same visual dimension
share the same visual map, and per-query macro grouping uses real query strings.

The requested visual backbone is
`convnextv2_tiny.fcmae_ft_in22k_in1k`. The exact official asset is locked at
revision `b1dd46230e80bf4cc3fa0c3c905db2c3ec53a817` and verified locally and on
the RTX 5090: `model.safetensors` is 114,561,694 bytes with SHA256
`6652fd90fc9c23977659e58515778e16fbbcd43f0b01fc693089cebe6d64c2a9`.
The bytes came through an exact-revision mirror transport after official
downloads timed out, then matched official API metadata.

Two explicit offline loads on the RTX 5090 produced identical state
fingerprints. The loader constructs timm with `pretrained=False`, verifies the
lock and bytes, and loads safetensors directly. All 643 non-visual student/loss
state entries were bitwise identical between same-seed C2 and D2 construction;
only the visual state changed. See `D2_E0_1_READINESS.md` and
`d2_e0_1_readiness.json`. No data loader, optimizer, scheduler, forward,
backward, update, checkpoint, test evaluation, or scientific gate was run.

The asset/load/parity readiness state is
`D2_PROBE_READY_FOR_ZERO_TRAINING_GATE`. The preregistered superiority gate
(`pretrained VQP >= random + 0.05` and `>= QP + 0.02`) has deliberately not
been executed in E0.1, so there is still no scientific D2 result. This does not
authorize the 800-step D2 control or Full training. Large model/data artifacts
remain off-repository.
