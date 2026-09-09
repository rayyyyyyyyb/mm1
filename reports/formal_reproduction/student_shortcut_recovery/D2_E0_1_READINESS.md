# D2 E0.1 readiness audit

Date: 2026-09-09  
Branch: `repro/student-shortcut-recovery`  
Final E0.1 status: `D2_PROBE_READY_FOR_ZERO_TRAINING_GATE`

This status authorizes only the already preregistered zero-training D2 probe.
It does **not** report a scientific D2 result and does not authorize the
800-step D2 control, Full training, test evaluation, a second seed, or a longer
schedule.

## P0 sample-identity correction

Every encoder pass now carries the real manifest `id`, real `query`, label,
query embedding, sequence mask, and selected segment indices. Because the
training loader may reshuffle on each traversal, subsequent passes are
reordered by real sample ID before comparison. Duplicate IDs, a missing/extra
ID, or any aligned label/query/query-embedding/mask/selected-index difference
fails closed. Regression tests cover shuffled order and each mismatch class.

QP and VQP use one shared seeded query map and one visual map per input
dimension. Map SHA256 values are written into the future probe receipt. The
per-query macro receives `batch["query"]`, not an artificial row index, and
the future receipt reports query counts plus query/sample ID hashes.

## Exact asset and actual load path

| Item | Receipt |
|---|---|
| Model | `timm/convnextv2_tiny.fcmae_ft_in22k_in1k` |
| Revision | `b1dd46230e80bf4cc3fa0c3c905db2c3ec53a817` |
| `config.json` | 901 bytes, `a9adf5b660f85c08af085b19a80a47b942f574e62211f7af6c3c7b6fe2a88eb6` |
| `model.safetensors` | 114,561,694 bytes, `6652fd90fc9c23977659e58515778e16fbbcd43f0b01fc693089cebe6d64c2a9` |
| Source state-key SHA256 | `dcae30d4a74adba8a659830e14f2f3ffa02dee51afcdf873480bbc5e2f56ff51` |
| Source tensor-state SHA256 | `bd92db7f811465a831aad5ec369139ab438d6794c5cdd5cb16d4c4db320a972b` |
| Loaded backbone-state SHA256 | `d8bcbc7225bedef0202e5f47613a4232eab9a7bbeef2be571831266361bafe90` |
| Loaded parameters / feature dim | 27,866,496 / 768 |
| Missing keys | none |
| Intentionally unused checkpoint keys | `head.fc.weight`, `head.fc.bias` |
| Repeat load | identical across two offline loads |

The runtime calls `timm.create_model(..., pretrained=False)` and then loads
only the verified safetensors bytes. `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1` were set during the 5090 audit. No timm pretrained
lookup or random fallback can satisfy the receipt.

The executed input SHA256 values are recorded in the JSON: readiness script
`9f7bc4969a77fa98464c030d163b991b89fd7203a2ef0d8aca44bc4823ab9f89`,
asset lock `b50207f0e3b34536ab73c152c1762f8c6ec5a904710f7364ceb10b009d9cdf07`,
C2 config `bddbdc33de6cc9bfb317e965e5fe094cf2a8225a492a793b20b311618ad8e264`,
and D2 config `b9c32df24aef4c30e2ca5869b52c5dbc16a4c517ab46fe35332f2e548110643d`.

## Initialization parity

C2 and D2 were both constructed on CPU with seed 42 through the same random
initialization path. Only after construction was D2's visual-backbone state
replaced by the locked state. All 643 non-visual student/loss state entries
were bitwise identical:

- C2 non-visual SHA256:
  `d157e5086dd7bb33141e3e787a7f9bebd2bcfd3bd99776164b34a1d1e5122272`
- D2 non-visual SHA256:
  `d157e5086dd7bb33141e3e787a7f9bebd2bcfd3bd99776164b34a1d1e5122272`
- random C2 visual SHA256:
  `f09afc6aa2c664bcbf1728a3c9d98a92999713caf92b659d43040dc179288e61`
- locked D2 visual SHA256:
  `46c0d38d3a361b3f3f72440ebae05b4a658f1325572b125e0a4b41fb00e4aee4`

Thus the intended visual initialization changed while the non-visual state did
not.

## Runtime and no-mutation receipt

The successful audit ran on `NVIDIA GeForce RTX 5090` with Python 3.11.9,
PyTorch 2.10.0+cu128, timm 1.0.28, safetensors 0.8.0, and CUDA 12.8. The
machine-readable receipt is `d2_e0_1_readiness.json`, whose local and remote
SHA256 matched at collection time:
`784f1cb06ace0df5e2810a13dae91d0cb83760267bfde7e393c62744ae4bf8ab`.

The audit constructed no data loader, optimizer, or scheduler; executed no
forward, backward, optimizer step, scientific gate, or test evaluation; and
wrote no checkpoint. Two preliminary no-training runs were retained in the
ledger: the first exposed the legacy/explicit-pretrained config conflict, and
the second exposed scalar-buffer hashing. Both defects were corrected and
covered before this successful receipt.

The final `d7b29ca` snapshot also passed the complete remote suite: `675 passed
in 346.25s (0:05:46)`, pytest exit `0`, using the verified Python 3.11.9/MinGit
environment. A preliminary code-only run was `673 passed, 2 failed` because the
disposable tree intentionally lacked `.git` and non-repository assets; the
rerun supplied only excluded read-only junctions and passed all 675 tests.

## Next authorized boundary

The next action, only when requested, is the preregistered validation-only,
zero-training QP/VQP probe using this exact asset and the corrected ID-aligned
protocol. D2 800-step training remains gated on that probe's superiority rule.
