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
`convnextv2_tiny.fcmae_ft_in22k_in1k`. The exact official asset is now locked
at revision `b1dd46230e80bf4cc3fa0c3c905db2c3ec53a817` and verified locally:
`model.safetensors` is 114,561,694 bytes with SHA256
`6652fd90fc9c23977659e58515778e16fbbcd43f0b01fc693089cebe6d64c2a9` (see
`D2_PRETRAINED_ASSET_RECEIPT.md`). Direct official requests timed out, so the
bytes were fetched through an exact-revision mirror transport and checked
against official API metadata. Installation into the isolated 5090 cache and
offline loading remain pending because SSH port 22 was unreachable during this
check. The endpoint currently reports an RTX 4070 Laptop GPU rather than the
target 5090, so the verified asset has not been uploaded there. No random
state was substituted for a pretrained state, and no optimizer, update, or
checkpoint write occurred.

The preregistered D2 superiority gate cannot be evaluated without the actual
pretrained state (`pretrained VQP >= random + 0.05` and `>= QP + 0.02`), so
the precise scientific state is `D2_BLOCKED_BY_PRETRAINED_ASSET_NOT_TESTED`.
This is not evidence that visual pretraining is ineffective and does not
authorize a bounded control or Full training. The exact compact JSON receipt is
`TEACHER_SIGNAL_CLOSURE_SUMMARY.json` plus `D2_PRETRAINED_ASSET_RECEIPT.md`;
large model/data artifacts remain off-repository.
