# D2 pretrained-visual asset receipt

Date: 2026-09-09
Branch: `repro/student-shortcut-recovery`

## Locked asset

The D2 candidate is the exact `timm/convnextv2_tiny.fcmae_ft_in22k_in1k`
repository at revision
`b1dd46230e80bf4cc3fa0c3c905db2c3ec53a817`. The tracked lock is
`configs/locks/diagnostics/convnextv2_tiny_pretrained_asset.yaml`.

| file | bytes | SHA256 | local result |
|---|---:|---|---|
| `config.json` | 901 | `a9adf5b660f85c08af085b19a80a47b942f574e62211f7af6c3c7b6fe2a88eb6` | MATCH |
| `model.safetensors` | 114,561,694 | `6652fd90fc9c23977659e58515778e16fbbcd43f0b01fc693089cebe6d64c2a9` | MATCH |

The model file was fetched as eight HTTP byte ranges from the fallback
`hf-mirror.com` transport after direct Hugging Face requests timed out. The
parts were concatenated in byte order and verified against the official
Hugging Face API metadata at the locked revision. The fallback is transport
only; it does not change the model ID or revision.

## Deployment state

The verified bytes are intentionally under ignored `tmp/` and are not staged
or uploaded to GitHub. Installation into the isolated 5090 Hugging Face cache,
offline `timm` load, state-dict fingerprint, and the zero-training VQP gate are
still pending. An earlier query reported an RTX 4070 Laptop GPU and therefore
correctly caused a no-mutation stop. A fresh direct SSH query now reports
`DESKTOP-LPN6MT3` with `NVIDIA GeForce RTX 5090, 32607 MiB`; the target is
reachable again. No upload, cache mutation, or D2 training had been started at
the time of this identity recheck.

## Scientific interpretation

This receipt is an asset lock, not evidence that D2 improves the boundary. The
scientific D2 status remains
`D2_BLOCKED_BY_PRETRAINED_ASSET_NOT_TESTED` until the remote cache is installed,
loaded offline, and the preregistered zero-training gate is executed.
