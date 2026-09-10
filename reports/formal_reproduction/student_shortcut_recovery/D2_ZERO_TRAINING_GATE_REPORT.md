# D2 zero-training visual-pretraining gate

Date: 2026-09-10

Branch: `repro/student-shortcut-recovery`

Target: `DESKTOP-LPN6MT3`, NVIDIA GeForce RTX 5090

Artifact status: `ARTIFACT_AUDIT_PASS`

Scientific status: `D2_ZERO_TRAINING_DECODABILITY_GATE_FAIL`

The immutable producer evidence retains the earlier broad label
`VISUAL_PRETRAINING_CONTROL_FAIL`. The independent auditor normalizes it to
the precise status above. This zero-training frozen probe did not test the
effect of pretrained initialization during gradient training; that separate
question is `PRETRAINED_VISUAL_INITIALIZATION_TRAINING_EFFECT_UNTESTED`.

## Scope and protocol

This was the separately authorized D2 zero-training scientific gate. It used
the existing 256-record-per-split stratified subset budget, seed 42, the
official `T_task=10` timeline, train-fit/validation-eval probing, and the
previously registered thresholds. It did not name or read a test manifest,
construct a student optimizer, call backward, apply a model update, write a
model checkpoint, or run D2/D3/Full training.

The worker ran from 2026-09-10T02:19:08Z through 02:24:48Z and exited 0. Its
stderr is empty. The temporary subset manifests were removed at completion;
the isolated control directory contains no `.pt`, `.pth`, `.ckpt`, or `.npz`
artifact, and the RTX 5090 returned to 488 MiB idle usage.

## Locked inputs

| Input | SHA256 |
|---|---|
| reviewed probe runtime | `c57d69ea3c4c80ad53bb459d55c283bdc539000229f9cf1c1e37f98b599fde1e` |
| D2 wrapper | `b9c32df24aef4c30e2ca5869b52c5dbc16a4c517ab46fe35332f2e548110643d` |
| C2 `best.pt` (562,516,965 bytes) | `1b997952d2f9bb89b3783352655b044671a72a84ed76dcd6c4b8be6bf29cecf0` |
| train manifest | `cb30035c533d56d44469d063ba11720ae3660266535ede670db6b6f53bdc7666` |
| validation manifest | `df2e8979c3fa05dcadaeb5ff7ef9726263fae7950b7478d30cb709aefbc97160` |
| locked `model.safetensors` (114,561,694 bytes) | `6652fd90fc9c23977659e58515778e16fbbcd43f0b01fc693089cebe6d64c2a9` |
| locked `config.json` (901 bytes) | `a9adf5b660f85c08af085b19a80a47b942f574e62211f7af6c3c7b6fe2a88eb6` |

The exact visual asset is
`timm/convnextv2_tiny.fcmae_ft_in22k_in1k` at revision
`b1dd46230e80bf4cc3fa0c3c905db2c3ec53a817`. The run loaded it offline with
`pretrained=False` construction followed by verified safetensors state load.
The loaded 27,866,496-parameter, 768-dimensional backbone fingerprint is
`d8bcbc7225bedef0202e5f47613a4232eab9a7bbeef2be571831266361bafe90`;
there are no missing keys and only `head.fc.weight/bias` are intentionally
unused.

## Corrected representation results

All values below come from the same aligned sample identities and the same
seeded query map. The three 768-dimensional visual representations also share
the same visual map. AP and per-query macro AP are diagnostic context; the
gate uses mixed pair-weighted concordance only.

| Representation | Mixed concordance | Global AP | Per-query macro AP |
|---|---:|---:|---:|
| query/position only (QP) | 0.4942430704 | 0.5618463178 | 0.5940077454 |
| random visual VQP | 0.4906183369 | 0.5465512822 | 0.5935586409 |
| exact pretrained visual VQP | 0.5127931770 | 0.5572415039 | 0.6105512616 |
| current C2 visual VQP | 0.5174840085 | 0.5367781723 | 0.6218456279 |
| random audio positive control VQP | 0.6788912580 | 0.6239904843 | 0.6988669628 |

Shapes are `[256,10,768]` for all visual passes, `[256,10,1408]` for the
audio control, and `[256,1024]` for query embeddings. Real query grouping
contains 53 query strings whose counts sum to 256.

## Independent gate recomputation

The frozen gate is:

1. `pretrained VQP >= random VQP + 0.05`; and
2. `pretrained VQP >= QP + 0.02`.

The observed comparisons are:

| Comparison | Observed gain | Required gain | Margin to threshold | Result |
|---|---:|---:|---:|---|
| pretrained minus random VQP | +0.0221748401 | +0.0500000000 | -0.0278251599 | FAIL |
| pretrained VQP minus QP | +0.0185501066 | +0.0200000000 | -0.0014498934 | FAIL |

Both conjunctive requirements fail. The second is close, but the threshold was
frozen before observation and must not be relaxed. The exact pretrained visual
candidate is also 0.0046908316 below the current C2 visual representation on
the primary concordance statistic. The much stronger audio-control value
shows that the corrected probe can expose label-aligned representation signal;
this is not a universal probe-floor result.

The earlier values `0.523028 / 0.488699 / 0.455437` are retained only as
historical invalid measurements. They are not directly comparable because
the corrected run aligns every loader pass by real ID and reuses one projection
map family instead of changing the query map between QP and VQP.

## Exact-candidate full test

Commit `c0dca35ec226ba87ecd4ae4bcbfd7a37a04e0e30` was exported as a
tracked-files-only archive (3,117,462 bytes, SHA256
`18689cfb018db713e9e39f0e79d3c5d10a98db754e70a1852b4f6c851d7e873b`) and
deployed to a fresh isolated directory on `DESKTOP-LPN6MT3`. Read-only
junctions expose the existing data, teacher assets, weights, and upstream
repositories without placing any of those bytes in Git. The two tracked
manual-source receipts had identical SHA256 values before and after the
junction was installed, and the candidate worktree remained clean.

The first complete test attempt found an environment defect: the
non-interactive SSH `PATH` did not contain the already installed MinGit. It
therefore ended with `644 passed, 36 failed`; all 36 failures were
`FileNotFoundError` at tests that spawn `git`, rather than assertion failures
in the candidate. Its receipt and raw output are retained with the suffix
`.attempt1_missing_git`. No source file was changed.

The same candidate was rerun after prepending the verified
`E:/OV-OrthKD-R0/env/Git/cmd` directory to `PATH`:

- command: `python -m pytest -q`;
- result: `680 passed in 343.81s (0:05:43)`;
- process exit: `0`;
- runner interval: 2026-09-10T04:49:19Z through 04:55:09Z;
- stdout: 1,688 bytes, SHA256
  `7872a8036c1eb7560248c3c4c9faaabc621552e568b568312d5fa74854358247`;
- stderr: 0 bytes, SHA256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
- post-test Git status: clean.

The deployment receipt SHA256 is
`d2b4421dd1f6a9b7ee347a470ab4bfbc1970a0b47adadf4e12f86148fd7cc497`.
The successful test receipt SHA256 is
`028ba64ed21912744de2bae72ac555d78f196a4f4bccd2109a2e05314163272f`.
All verification receipts, both attempts, and both auditable PowerShell
helpers are retained with the repository evidence.

## Artifact audit and decision

The independent auditor recomputed both inequalities and verified cross-pass
ID/label/query/mask/selected-index hashes, shared projection maps, real query
grouping, the exact offline asset, worker state, exit code, and empty stderr.
It returned `ARTIFACT_AUDIT_PASS` with no errors. The producer JSON SHA256 is
`5f29e4ca172334e9e041cac7e57ca11c6adb9d5d5686c7629cd8435d680f898c`;
the independent audit is `d2_zero_training_gate_audit.json`.

Because the scientific status is `D2_ZERO_TRAINING_DECODABILITY_GATE_FAIL`, the old D2
800-step training is **not authorized**. D3, Full, test evaluation, a second
seed, and schedule extension also remain unauthorized. This rejects this exact
pretrained-visual candidate as the next bounded control under the registered
gate; it does not by itself invalidate every form of visual pretraining or the
paper's complete method.
