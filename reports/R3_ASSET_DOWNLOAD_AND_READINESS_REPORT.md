# R3 Asset Download and Conference Readiness Report

> Historical R3 snapshot. Its raw-video canonical blocker is superseded by the user-approved official T=10 JPG/WAV protocol and R4 evidence in `R4_T10_TEMPORAL_PROTOCOL_CORRECTION_REPORT.md`. The 13 zero-byte and 1,019 short raw streams remain valid optional-diagnostic facts.

Date: 2026-08-24

Branch: `repro/r3-assets-download-and-readiness`

Unique base: `f6e85eb61cdc09e530038d46671f70ee2618ea5c`

Final status: `BLOCKED_BEFORE_CONFERENCE_REPRO`

## Decision

All five public teacher checkpoints, the pinned GPT-2 snapshot, five fixed upstream repositories, the RTX 5090 teacher environment, the native Windows toolchain, and both official OV-AVEBench SharePoint archives are downloaded and byte-audited. Both archives were safely extracted and their complete extracted-tree hashes were frozen. All three real teacher classes strict-load their real checkpoint combinations successfully.

The preprocessed archive is complete and contains exactly 248,000 JPG files plus 24,800 WAV files. This byte-level observation corrects the official README's `.png` wording; every sample has the exact names `00000001.jpg` through `00000010.jpg`. A second audit of all extracted files decoded the entire release, proved the 24,800-row metadata bijection, and reported zero missing, extra, duplicate, zero-byte, error, or warning entries. The raw archive is also byte-complete and its gzip/tar container is fully readable. A full 16-worker ffprobe audit matches exactly 24,800 official IDs after excluding 25 macOS AppleDouble sidecars, but finds 13 zero-byte formal MP4s and 1,019 additional non-empty streams shorter than the currently locked ten-second policy. Of the latter, 958 are estimated not to cover the last deterministic 9.875-second InternVideo2 sampling point. The workflow therefore did not start formal student training, did not consume the one allowed real optimizer-step preflight, and keeps the canonical full-run guard enabled. Author-issued corrected bytes plus an official short-video protocol clarification are the remaining external blockers.

## Official data and source-metadata audit

| Asset | Bytes | SHA256 | Audit |
|---|---:|---|---|
| OV-AVEBench preprocessed | 24,618,769,924 | `ebecec9915052beffbba7ae1debd7b45cfef7b70fd7866196b964ab8542a413e` | container passed; 248,000 `.jpg`, 24,800 `.wav`, zero empty files |
| OV-AVEBench raw videos | 38,147,170,955 | `ac9c8fc6e8b905ed414082132d6c2f8c81f5a8aad5d2c996e7512a40ff12b1bc` | container/extraction passed; exact 24,800-ID match; 13 zero-byte MP4s; 1,019 streams below locked 10 s; formal use blocked |
| Official VGGSound CSV | 7,949,116 | `c1816c00a237afa4994e873e88f56bac206cbb285fddb05c564184b9c3d6e6ce` | 199,467 four-column rows; all 13 IDs found; `di01T0hGboU` has two distinct timestamps |

Safe extraction produced 272,800 preprocessed files / 27,959,350,079 bytes with tree SHA256 `7a2c848fcdfe5118b3ac1de23eaa7b9121c4e3a98f98d0112b3c6e6b72d75e60`, and 24,836 raw-archive files / 38,365,245,540 bytes with tree SHA256 `33e467c428432c5b67876350cd3f3bac0e267730f56ee71631e8864bf2077a89`. The complete extracted preprocessed layout report is 18,553,544 bytes with SHA256 `b663233b35c2f210c705ac7a6441c4947488b80ae2eba65fa4bd32aeee76b787`.

The VGGSound CSV is locked to `hche11/VGGSound@1e75f4d30de3a99115ee9333464854c5e3d161a7`, path `data/vggsound.csv`, Git blob `53da0dc492b8a3fadf770f0f175cef1e652c0447`. It is source-identity evidence only. The deterministic recovery manifest reports 12 `source_identified_only`, one `source_timestamp_ambiguous`, zero author replacements, and `BLOCKED_BEFORE_CONFERENCE_REPRO`.

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
- Official VGGSound source metadata: `hche11/VGGSound@1e75f4d30de3a99115ee9333464854c5e3d161a7`, `data/vggsound.csv`, immutable API download with Range support.

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
| download | blocked_raw_video_validation | Five weights, two archive downloads, and VGGSound metadata are byte-complete; raw payload has 13 zero-byte MP4s and 1,019 clips below the locked duration policy. |
| data | blocked_raw_video_validation | Official metadata counts 13,182/5,798/5,820, both archive hashes, both extracted-tree hashes and the passed preprocessed layout are locked; raw formal use awaits 13 author replacements and official resolution of the short-video protocol. |
| archival | resolved | Nine taskbook choices are explicit user-approved paper-specified reconstruction assumptions, not claimed as recovered archival history. |
| preprocessing | resolved | Actual release layout is locked to `00000001.jpg`–`00000010.jpg` plus WAV; mixed/missing/extra frames fail. |
| teacher | blocked | Three identities and five checkpoints resolved and strict-loaded; real smoke/full export wait on official data. |
| evaluator | resolved | Paper F1@0.5 and validation-calibrated F1 mappings are bound to config; event F1 remains supplemental. |

## Teacher strict-load and data-dependent stages

| Teacher | Exact class | Output dimension | Strict load |
|---|---|---:|---|
| InternVideo2 | `multi_modality.models.internvideo2_clip_small.InternVideo2_CLIP_small` | 512 | passed, 6.963 s CPU |
| BEATs | `BEATs.BEATs` | 768 | passed, 2.544 s CPU |
| CLAP | `msclap.models.clap.CLAP` | 1024 | passed, 6.291 s CPU |

- Real repeat-2 smoke: prior teacher readiness evidence remains available, but conference reconstruction is blocked before any raw-video-dependent rerun because 13 formal samples are empty and the locked short-video policy rejects 1,019 more.
- Full teacher export: not started; 0/24,800 records, no cache root SHA256 exists.
- Real optimizer-step preflight: not invoked; invocation count is 0 and no invocation marker/report exists.
- Full conference training: not started.
- `configs/ov_orthkd_mm26_repro_ready.yaml`: intentionally absent.

## Verification evidence

| Command/check | Exit | Result |
|---|---:|---|
| `python -m compileall -q src scripts tests` | 0 | passed |
| `python -m pytest -q` | 0 | 319 passed in 309.73 s; stderr empty |
| `python -m pip check` | 0 | no broken requirements |
| `python scripts/verify_cuda_runtime.py` | 0 | RTX 5090, CUDA 12.8, capability 12.0, FP16 result finite |
| `python scripts/assets/download_mm26_assets.py --verify --root .` | 0 | all five weights passed |
| teacher environment canonical audit | 0 | ready; Transformers 4.45.1 and GPT-2 root verified |
| repository audit-only | 0 | five fixed repositories passed |
| tool receipt validator | 0 | ready; zero errors |
| three real teacher strict-load commands | 0 | all passed |

The fail-closed readiness builder exited 1 and serialized `BLOCKED_BEFORE_CONFERENCE_REPRO` (receipt SHA256 `baf60e11c642a26a9763caed797d1c9975600b6ba265139e555be920149ed09c`). Its archive/extraction and full preprocessed-layout gates pass. The blocked gates are the intentionally incomplete data/source chain, data-dependent teacher smoke/export, and the intentionally absent R3 real-preflight receipt. The builder's stale R2-only final-state names and default preflight path were corrected with a red/green regression test so the repository now emits only the two R3 taskbook statuses.

## Required human action

Do not download the same two archives again and do not provide an account password. Use the ready-to-send request in `reports/data/OVAVEBENCH_RAW_VIDEO_AUTHOR_REQUEST.md` to ask the OV-AVEL authors for (a) either a corrected official raw archive or the exact 13 original MP4 files with author-hosted locators/checksums, and (b) the official non-repeating temporal policy or corrected source bytes for released clips shorter than ten seconds. When replacement bytes arrive, keep them in a separate quarantine overlay and run `scripts/verify_ovave_raw_replacements.py`; the original archive must remain unchanged. YouTube recuts, mirrors, repeated frames, silent padding/resampling, and the official JPG/WAV derivatives are not canonical replacements.

Final status: `BLOCKED_BEFORE_CONFERENCE_REPRO`
