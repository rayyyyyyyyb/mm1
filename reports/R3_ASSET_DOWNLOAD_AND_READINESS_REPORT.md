# R3 Asset Download and Conference Readiness Report

Date: 2026-08-20

Branch: `repro/r3-assets-download-and-readiness`

Unique base: `f6e85eb61cdc09e530038d46671f70ee2618ea5c`

Final status: `BLOCKED_BEFORE_CONFERENCE_REPRO`

## Decision

All five public teacher checkpoints, the pinned GPT-2 snapshot, five fixed upstream repositories, the RTX 5090 teacher environment, and the native Windows toolchain are downloaded and byte-audited. All three real teacher classes strict-load their real checkpoint combinations successfully.

The two official OV-AVEBench SharePoint archives still require one legal Microsoft organization login. Their original bytes are not present in `E:\OV-OrthKD-R3\repo\data\downloads\manual_sources\`. Consequently the workflow intentionally did not extract data, build source manifests, run real repeat-2 smoke, export the 24,800-record teacher cache, or claim the single allowed optimizer-step preflight. No ready configuration was created and the canonical full-run guard remains enabled.

## Public weight receipts

| Asset | Final configured source | Bytes | SHA256 | Resumptions | Result |
|---|---|---:|---|---:|---|
| InternVideo2 B14 vision | `https://hf-mirror.com/OpenGVLab/InternVideo2_distillation_models/resolve/main/stage1/B14/B14_dist_1B_stage2/pytorch_model.bin?download=true` | 204,538,935 | `1037a4785a830f9d663cab72da5751129e012042e428a74e019f84f016cd0be7` | 1 | passed |
| InternVideo2 CLIP-B14 overlay | `https://hf-mirror.com/OpenGVLab/InternVideo2_distillation_models/resolve/main/clip/B14/pytorch_model.bin?download=true` | 5,552,811 | `c76ebe61e955500056e83f137e028eb6ad5101e1ace137c62fbde6c3569fb05e` | 1 | passed |
| MobileCLIP-B-LT | `https://docs-assets.developer.apple.com/ml-research/datasets/mobileclip/mobileclip_blt.pt` | 599,214,572 | `670844f7a886dd6eff7a9285adfc53f3d3c889c03bfc8354010cb5c6bf27441a` | 1 | passed |
| BEATs Iter3+ AS2M | `https://hf-mirror.com/lpepino/beats_ckpts/resolve/main/BEATs_iter3_plus_AS2M.pt?download=true` | 361,499,833 | `d43cbfad4d7b56381c061d7a24774f908d4d94c72961f6eb1d9090ff18cd8d34` | 1 | passed |
| Microsoft CLAP 2023 | `https://huggingface.co/microsoft/msclap/resolve/main/CLAP_weights_2023.pth?download=true` | 689,950,036 | `2cef4016d47d00eb28d153d522f397222057f95000e9bad6b9583c631284a1e6` | 2 | passed |

All five passed non-empty/non-HTML/non-XML/non-LFS validation, published SHA256 comparison, safe `torch.load(weights_only=True)` structure checks, and final wrapper strict-load. Stable alternates are preserved in `configs/locks/mm26_download_lock.yaml`; temporary signed CDN URLs, cookies, and tokens are not recorded.

## Additional immutable resources

- GPT-2 repository/revision: `openai-community/gpt2@607a30d783dfa663caf39e06633721c8d4cfcd7e`.
- GPT-2 `model.safetensors`: 548,105,171 bytes, SHA256 `248dfc3911869ec493c76e65bf2fcf7f615828b0254c12b473182f0f81d3a707`.
- GPT-2 seven-file root SHA256: `b153066835c920d5713823134e00bde77a6ec5af4746c11984658debbaddbf0a`.
- FFmpeg 9.0.1 distribution: 111,253,802 bytes, SHA256 `fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9`; identical bytes obtained from the GyanD GitHub release mirror after the Gyan rolling endpoint proved slow.
- Tool receipt: ready for aria2 1.37.0, curl 8.21.0, FFmpeg 9.0.1, Git LFS 3.7.1, jq 1.8.2, Python 3.11.9, and 7-Zip 26.02. Windows-native background processes, SCP/SFTP, and curl replace tmux, rsync, and wget where those POSIX tools do not exist.

## Fixed repositories

| Repository | Commit | Audit |
|---|---|---|
| OpenGVLab/InternVideo | `3965eef16e2dadd0ea6c8d0cc29c8a3039df52e3` | clean; exact licenses and key sources hashed |
| microsoft/CLAP | `e8a6467b87cd85716e20c6a008126150d9740be0` | clean; exact licenses and key sources hashed |
| apple/ml-mobileclip | `aecfb5453d022e9deff12f81a150ea8f35194baa` | clean; exact licenses and key sources hashed |
| jasongief/OV-AVEL | `b5fe1d685d0c6d0d6fd80312b5ccde79f9b73ea6` | clean; exact metadata/preprocessing/evaluator sources hashed |
| microsoft/unilm (BEATs) | `833df7e7832e5064a281131ee64a481afa8e5b95` | clean; exact licenses and BEATs sources hashed |

The InternVideo receipt includes `InternVideo2/multi_modality/models/internvideo2_clip_small.py` at 10,952 bytes / SHA256 `4b58387591be5ed2ce8170af119f01957553a286d58741b1b2ade5d81b53d667`.

## Lock summary

| Lock | State | Summary |
|---|---|---|
| download | blocked_auth_required | Five weights passed; two SharePoint data assets AUTH_REQUIRED. |
| data | blocked | Official metadata counts 13,182/5,798/5,820 are locked; both archive byte streams, extraction, layouts, and manifests remain gated. |
| archival | resolved | Nine taskbook choices are explicit user-approved paper-specified reconstruction assumptions, not claimed as recovered archival history. |
| preprocessing | resolved | Official PNG/WAV student path, ImageBind-compatible audio semantics, and official raw-video InternVideo path are fixed. |
| teacher | blocked | Three identities and five checkpoints resolved and strict-loaded; real smoke/full export wait on official data. |
| evaluator | resolved | Paper F1@0.5 and validation-calibrated F1 mappings are bound to config; event F1 remains supplemental. |

## Teacher strict-load and data-dependent stages

| Teacher | Exact class | Output dimension | Strict load |
|---|---|---:|---|
| InternVideo2 | `multi_modality.models.internvideo2_clip_small.InternVideo2_CLIP_small` | 512 | passed, 6.963 s CPU |
| BEATs | `BEATs.BEATs` | 768 | passed, 2.544 s CPU |
| CLAP | `msclap.models.clap.CLAP` | 1024 | passed, 6.291 s CPU |

- Real repeat-2 smoke: not run; no audited official train sample exists.
- Full teacher export: not started; 0/24,800 records, no cache root SHA256 exists.
- Real optimizer-step preflight: not invoked; invocation count is 0 and no invocation marker/report exists.
- Full conference training: not started.
- `configs/ov_orthkd_mm26_repro_ready.yaml`: intentionally absent.

## Verification evidence

| Command/check | Exit | Result |
|---|---:|---|
| `python -m compileall -q src scripts tests` | 0 | passed |
| `python -m pytest -q` | 0 | 296 passed in 104.21 s, no warnings |
| `python -m pip check` | 0 | no broken requirements |
| `python scripts/verify_cuda_runtime.py` | 0 | RTX 5090, CUDA 12.8, capability 12.0, FP16 result finite |
| `python scripts/assets/download_mm26_assets.py --verify --root .` | 0 | all five weights passed |
| teacher environment canonical audit | 0 | ready; Transformers 4.45.1 and GPT-2 root verified |
| repository audit-only | 0 | five fixed repositories passed |
| tool receipt validator | 0 | ready; zero errors |
| three real teacher strict-load commands | 0 | all passed |

The final conference readiness command ran in a clean Windows checkout of the exact candidate commit, exited 1, and serialized `BLOCKED_BEFORE_CONFERENCE_REPRO` (receipt SHA256 `d764e12218cdb328dca7ad84effaed0e1c4dc3f1b1bab6e767451328fcc2beb1`). Its immediate blocker is the intentionally absent real-preflight receipt. A second canonical audit with `require_real_preflight=False` exhaustively checked the rest of the chain: no Git-dirty, archival, preprocessing, evaluator-parity, teacher-checkpoint, environment, or repository error remained; every reported blocker was the missing SharePoint bytes or a data-dependent extraction/layout/manifest/smoke/export consequence. This expected fail-closed result is not a test failure.

## Required human action

Follow `reports/downloads/SHAREPOINT_AUTH_REQUIRED.md`: sign in through an authorized browser/RDP session, download both original files without renaming or modifying them, and place them in `E:\OV-OrthKD-R3\repo\data\downloads\manual_sources\`. Do not send a password, MFA code, cookie, token, or signed URL. After the files are present, rerun the byte validation, safe extraction, full layout/manifest audits, real repeat-2 teacher smoke, resumable full export, full artifact audit, and only then the one allowed optimizer-step preflight.

Final status: `BLOCKED_BEFORE_CONFERENCE_REPRO`
