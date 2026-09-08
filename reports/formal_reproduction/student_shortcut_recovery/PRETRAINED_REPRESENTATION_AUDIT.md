# Independent pretrained-representation audit (Phase D)

This is a zero-training, validation-only probe on 256 stratified mixed
records per split (seed 42, official `T=10`). The code now resolves
`visual_pretrained` and `audio_pretrained` independently; legacy `pretrained`
is only a paired fallback when both new fields are absent.

| Representation | VQP mixed concordance | Status |
|---|---:|---|
| random visual | 0.523028 | measured |
| current C2 visual checkpoint | 0.488699 | measured |
| random audio control | 0.455437 | measured |
| timm-pretrained visual | — | blocked |

The requested visual backbone is
`convnextv2_tiny.fcmae_ft_in22k_in1k`. Its timm/Hugging Face weights were not
present in the 5090 cache; five retries for both safetensors and PyTorch
weight endpoints timed out. The resulting receipt is
`BLOCKED_BY_PRETRAINED_BACKBONE_ASSET`. No random state was substituted for a
pretrained state, and no optimizer, update, or checkpoint write occurred.

The preregistered D2 superiority gate cannot be evaluated without the actual
pretrained state (`pretrained VQP >= random + 0.05` and `>= QP + 0.02`), so
`VISUAL_PRETRAINING_CONTROL_NOT_PASS` is recorded. This does not authorize a
bounded control or Full training. The exact compact JSON receipt is
`TEACHER_SIGNAL_CLOSURE_SUMMARY.json` plus the remote-only Phase D receipt;
large model/data artifacts remain off-repository.
