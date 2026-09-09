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
or uploaded to GitHub. They were copied to an isolated ignored directory on
the 5090 and reverified byte-for-byte. Two explicit offline loads succeeded
with an identical loaded-backbone state SHA256 of
`d8bcbc7225bedef0202e5f47613a4232eab9a7bbeef2be571831266361bafe90`.
An earlier query reported an RTX 4070 Laptop GPU and therefore
correctly caused a no-mutation stop. A fresh direct SSH query now reports
`DESKTOP-LPN6MT3` with `NVIDIA GeForce RTX 5090, 32607 MiB`; the target is
reachable again. The D2 probe now requires the tracked lock to be passed into
an explicit offline safetensors load; it will not call `timm` with
`pretrained=True` or silently use a cache hit. No D2 training was started.

## Scientific interpretation

This receipt is an asset lock, not evidence that D2 improves the boundary.
E0.1 is now `D2_PROBE_READY_FOR_ZERO_TRAINING_GATE`: the remote locked load and
bitwise non-visual initialization-parity audit both passed. The scientific D2
status remains untested until the separately authorized zero-training VQP gate
is executed. Asset integrity and readiness are not scientific evidence.
