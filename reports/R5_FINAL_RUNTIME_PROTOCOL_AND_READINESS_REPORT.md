# R5 Final Runtime Protocol and Conference-Reproduction Readiness

Date: 2026-08-25

Branch: `repro/r5-final-runtime-protocol-and-readiness`

Base commit: `82901e4e24caec768525ded84c865e0d39acaccb`

Current status: `READY_FOR_CONFERENCE_REPRO`; formal training has not started

## 1. Final approved runtime facts

The only formal runtime interpretation is:

| Symbol | Exact value | Meaning |
|---|---:|---|
| `T_task` | 10 | ten official one-second task segments, labels, prediction positions and metric inputs |
| `T_max` | 16 | student positional-embedding capacity only |
| `K_student` | 1 | one fixed official JPG keyframe per task segment |
| `K_teacher` | 8 | eight repeats of that same keyframe for each InternVideo2 call |
| `V_test` | 1 | one deterministic validation/test forward, without view aggregation |

The formal path therefore contains no T=10 to T=16 label conversion, no 16-label prediction axis, no 160-frame video input, no executed 16-fps raw-video decode, and no test-time multi-crop, multi-clip, multi-view or ensemble average. The paper phrases “16 fps”, “16 temporal segments”, and “per-16-seg clip” are treated as systematic writing/terminology ambiguity. They do not authorize a protocol change.

## 2. Enforced implementation contract

- `src/utils/temporal_protocol.py` is the shared fail-closed validator for training, preflight and canonical readiness.
- Every public real experiment configuration explicitly states T=10, capacity 16, one official JPG per segment, eight repeated teacher frames, disabled/unexecuted raw-video diagnostic, and one non-aggregated test view.
- Formal source manifests contain ten single-JPG segment groups and ten labels per record. The student reads the segment keyframe once. Training applies only spatial horizontal flip and ColorJitter; validation/test transforms are deterministic.
- InternVideo2 receives one batch containing ten independent task-segment items. Each item repeats its one official JPG to eight identical frame tensors; the single batched `encode_vision(..., test=True)` call returns `[10,512]` features, and the paired text-similarity computation returns `[10]` logits.
- BEATs consumes a fixed ten-second, 16 kHz task window and returns `[10,768]`. CLAP returns one `[1024]` text embedding per query.
- The preflight shape receipt requires student visual/audio input, visual/audio teacher features, labels, student logits and metric input to preserve the official T=10 axis.

## 3. Official data and audio-window audit

- Official records: 24,800; split 13,182 train / 5,798 validation / 5,820 test.
- Official visual files: 248,000 JPG; exactly ten per record.
- Official audio files: 24,800 WAV; all 16 kHz.
- Source manifests passed an exhaustive audit with zero errors, warnings, duplicate IDs, split overlap or temporal resampling.
- Source manifest SHA256:
  - train: `296e087bee10c2ef40ac647fa6d19ae355296366f4f281bca3b58dfd1663d9a0`
  - val: `deebdc384b6d12d9794b923b4c4387205bc33c819aac06cc92bb1c0febb5fa16`
  - test: `d2d7ec2a7b45651fb620d826edcef3d18c8eac861732f12af538bbb4a794a814`
- The exhaustive WAV audit passed with zero errors: 23,844 files were exactly ten seconds, 954 were deterministically zero-padded at the tail, and 2 were truncated to ten seconds. There is no interpolation, sample-rate conversion, last-sample repetition or label transformation.
- Audio-window audit SHA256: `b8d779aa5e748d10ffdeef8663901306f0c25ceb74cb17adedfc2d6599e306e7`.

The optional raw MP4 archive remains diagnostic-only. Its 13 zero-byte files and 1,019 non-empty streams shorter than ten seconds are preserved in the audit record but are neither read nor substituted by the canonical official JPG/WAV path.

## 4. Locked teacher identity and real smoke

- Teacher identity SHA256: `c15bc96f00d6e391083bd8d00a31443a356870592a3afa809df528bf973ed90c`.
- InternVideo2: exact upstream repository/commit/class, Base/B14 declaration and three exact checkpoint roles (`vision`, `text`, `extra_clip`) are byte/SHA locked.
- BEATs: exact upstream repository/commit/class, Iter3+ AS2M pretrained checkpoint and ten-second waveform-fit semantics are byte/SHA locked.
- CLAP: exact upstream repository/commit/class, 2023 checkpoint, tokenizer revision and normalization setting are byte/SHA locked.
- Real repeat-2 smoke on RTX 5090 passed for all teachers. Outputs were finite and bitwise identical with maximum and mean absolute difference 0.
- Teacher identity report SHA256: `2894263aaed63f26ec2c02db825cc94815e328a0bd17bda4fbeaec8b35dfd74f`.

## 5. Exhaustive export, artifact audit and preflight

The teacher export used per-record schema-3 receipts bound to the source-manifest SHA256 and immutable teacher-identity SHA256. It published arrays and receipts atomically, rejected orphan/stale artifacts, and resumed only after recomputing bytes, hashes and shapes. The persistent main supervisor and both split-scoped sidecars completed on attempt 1 with exit code 0.

The completed mechanical evidence is:

1. exactly 24,800 valid exported records and zero errors;
2. 24,800 identity-bound receipts and 24,800 artifact records exhaustively checked for bytes, SHA256, finite values and exact shapes, with zero errors or warnings;
3. exported manifests: train `cb30035c533d56d44469d063ba11720ae3660266535ede670db6b6f53bdc7666`, validation `df2e8979c3fa05dcadaeb5ff7ef9726263fae7950b7478d30cb709aefbc97160`, test `ae8bd54c74d7e1c522c7d41cce9c2b8b2e96556ba80480ab6c1382d481ab2ea3`;
4. cache tree: 99,334 files, 1,310,102,478 bytes, SHA256 `6707900b5d4acb39752baeea11cd1e90d8d3394600b1fa3a6cc3984223860244`;
5. exactly one real-data, one-optimizer-step forward/backward/checkpoint-resume preflight passed without formal metric emission. The report SHA256 is `09a70816a2828eb1f3db95a976a47ee2e6b35f94ec50413be0da2c597c2f083a`;
6. the preflight shape receipt records visual/audio inputs `[4,10,3,224,224]`, visual teacher features `[4,10,512]`, audio teacher features `[4,10,768]`, labels/logits `[4,10]`, and 40 valid metric pairs, with no temporal resampling;
7. the final clean-tree canonical evidence chain passed with zero blockers and generated the guarded-to-unguarded ready config. Its readiness receipt SHA256 is `6aa11a2e3db214f8611cd538a637d704f08bbefe11fb26cc58733503f72a365c`.

The audit receipt's `teacher_lock_status` is the truthful pre-promotion snapshot `smoke_passed_export_pending`: the audit first computed the cache and manifest identities, those exact values were then written into the mutable full-export section of the teacher lock, and the final canonical gate subsequently revalidated the promoted `ready` lock against the same immutable teacher identity and actual bytes.

The real preflight invocation count is now exactly one and must not be incremented. No formal student training, main-table run, ablation or paper metric computation has started. The canonical preparation config retains `reproduction.full_run_blocked: true`; the generated `configs/ov_orthkd_mm26_repro_ready.yaml` differs only by setting it to false and must not be executed before explicit user instruction.

## 6. Verification policy and repository boundary

Every implementation change was checked independently before inclusion. The fresh full suite in a clean detached worktree on the locked RTX 5090 environment passed `388 passed in 328.59s` with pytest exit code 0. The same candidate then passed `pip check` (no broken requirements), full `src/scripts/tests` bytecode compilation, all 63 tracked YAML/JSON parses with `utf-8-sig`, and `git diff --check`, each with exit code 0. The worktree remained clean.

The CUDA runtime check also exited 0 on `NVIDIA GeForce RTX 5090`: Python 3.11.9, PyTorch `2.10.0+cu128`, CUDA 12.8, compute capability 12.0 and cuDNN 91002. Its FP16 2048-square matrix multiplication result was finite. This is an environment check, not a formal experiment or paper metric.

Git contains only source code, configuration, tests and compact evidence receipts. Official archives/data, manifests containing local absolute paths, checkpoints, teacher cache, outputs, logs, credentials, cookies, HAR files, tokens and signed URLs remain on the RTX 5090 and are not uploaded.

## 7. Decision

Final decision: `READY_FOR_CONFERENCE_REPRO`. The preparation stage is complete and stops here. This status authorizes a later formal reproduction run only after explicit user instruction; it does not claim that any paper result has already been reproduced.
