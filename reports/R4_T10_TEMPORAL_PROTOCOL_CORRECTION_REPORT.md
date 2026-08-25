# R4 T=10 Temporal Protocol Correction Report

> Superseded for current execution by `reports/archival/R5_USER_APPROVED_FINAL_RUNTIME_PROTOCOL.md`. R4 remains historical evidence. The final runtime statement is `T_task=10, T_max=16, K_student=1, K_teacher=8, V_test=1`; canonical execution performs no raw-video/16-fps decode and no test-time view ensemble.

Date: 2026-08-24
Branch: `repro/r4-keyframe-readiness-and-experiment-prep`
Base: `eae79f1c07b037cc7e6a7080402988b60d314dd1`
Final status: `BLOCKED_BEFORE_CONFERENCE_REPRO`

## Decision

The canonical OV-AVEBench task timeline is the official ten one-second temporal segments per ten-second clip. Labels, student logits, temporal teacher features and evaluator inputs remain on T=10. This implementation contains no 10-to-16 label interpolation, repetition, resampling or relabelling.

The values that were previously conflated are now explicit:

| Setting | Locked meaning | Value |
|---|---|---:|
| `data.num_segments` | official task timeline | 10 |
| `student.max_position_segments` | positional embedding capacity | 16 |
| `teacher_export.internvideo2.num_frames` | frames consumed per teacher segment | 8 |
| raw diagnostic `temporal_sampling_fps` | disabled diagnostic decoder grid only | 16 |

Read-only inspection of the initial source outside the expansion worktree showed that the historical InternVideo2 wrapper already used `num_frames=8`, while the student created a positional table with capacity 16 and sliced it to the actual sequence length. No source evidence was found for `num_frames=16`, `clip_len=16`, or a T=16 label protocol. Accordingly, the paper phrases “16 fps”, “16 temporal segments” and “per-16-seg clip” are treated as terminology/writing ambiguity, not as authority to change the official task labels.

## Implementation changes

- Separated task length from student positional capacity in every formal and ablation config.
- Added strict runtime checks for visual/audio input, visual/audio teacher features, labels, masks, logits and metric inputs.
- Bound the formal training and standalone PR/F1 evaluation paths to exactly ten ordered metric segments per sample before F1, AP, or AUROC is computed.
- Added a machine-readable temporal shape receipt to the only permitted real-data preflight.
- Made official JPG/WAV manifests independent of optional raw MP4s and added exact `[0,1]` through `[9,10]` audio windows.
- Added explicit teacher input dispatch. Canonical InternVideo2 uses ten official segment keyframes and deterministically repeats each keyframe to the historically evidenced eight-frame teacher input. Raw multiframe decoding remains an explicitly disabled diagnostic.
- Corrected Microsoft CLAP tokenizer compatibility using the exact pinned-upstream pad token `!`.
- Made canonical efficiency measurement T=10; T=16 is accepted only as a labelled synthetic capacity analysis.
- Kept canonical full-run blocking intact and did not start formal student training.

## Real data audit

The canonical manifest builder completed on the RTX 5090 and published 24,800 records:

| Split | Records | Bytes | SHA256 |
|---|---:|---:|---|
| train | 13,182 | 30,361,994 | `296e087bee10c2ef40ac647fa6d19ae355296366f4f281bca3b58dfd1663d9a0` |
| val | 5,798 | 13,264,784 | `deebdc384b6d12d9794b923b4c4387205bc33c819aac06cc92bb1c0febb5fa16` |
| test | 5,820 | 13,385,007 | `d2d7ec2a7b45651fb620d826edcef3d18c8eac861732f12af538bbb4a794a814` |

The final full source audit passed with zero errors and zero warnings. All 24,800 records have exactly ten labels and ten official keyframes; the seen/unseen split matrix matches the locked official counts; no duplicate IDs or split overlap were found; dataset temporal resampling is false for all records.

## Real teacher smoke

The RTX 5090 repeat-2 smoke used official train record `EpxQKLhAP0s` (`people burping`) and passed:

| Output | Shape | Finite | Repeatability |
|---|---|---|---|
| InternVideo2 features | `[10, 512]` | yes | bitwise identical |
| InternVideo2 logits | `[10]` | yes | bitwise identical |
| BEATs features | `[10, 768]` | yes | bitwise identical |
| CLAP text features | `[1024]` | yes | bitwise identical |

The maximum and mean absolute differences across repeated outputs are both `0.0` at locked tolerance `0.0`. Peak allocated GPU memory was 6,183,477,760 bytes. Repository identities and all five checkpoint SHA256 values were revalidated by the same receipt.

## Efficiency wording correction

The fresh RTX 5090 receipts report:

- canonical official T=10: 29.631 ms/clip and 33.748 clips/s;
- synthetic T=16 capacity analysis: 29.530 ms/clip and 33.863 clips/s.

Only the T=10 result is a task-protocol measurement. The T=16 result is retained solely to describe model capacity behavior and is neither a paper-protocol result nor evidence of temporal resampling.

## Remaining gates

Formal conference reproduction cannot start yet. The remaining ordered work is:

1. resumable full export of all 24,800 teacher-cache records;
2. full exported-artifact audit and cache root SHA256;
3. the single permitted real-data one-optimizer-step preflight, including the exact T=10 shape receipt;
4. generation and independent review of the ready config and readiness receipt.

The real preflight invocation count remains zero, formal student training was not started, the ready config remains absent, and `reproduction.full_run_blocked` remains `true`.

## Verification

- Final focused formal-evaluation tests: 14 passed.
- Final conference-readiness builder tests: 9 passed.
- Final full regression suite from a standard clean Git checkout on the RTX 5090 environment: 338 passed in 533.15 seconds, exit code 0.
- `python -m compileall -q scripts src tests`: exit code 0.
- `python -m pip check`: exit code 0, no broken requirements.
- CUDA verification: PyTorch 2.10.0+cu128, CUDA 12.8, RTX 5090 capability 12.0, FP16 2048-square matrix multiplication finite, exit code 0.

The readiness builder was rerun against actual locked files. It correctly
reports `BLOCKED_BEFORE_CONFERENCE_REPRO`: source audit, preprocessing,
archive/layout, archival assumptions, teacher smoke, evaluator parity, resume
tests and the full-run guard pass; full teacher export/cache audit and the one
real optimizer-step preflight remain blocked. A stale preprocessing-receipt
SHA inherited from the branch base was found by byte recomputation, covered by
a new regression assertion, and corrected to the actual committed receipt SHA
`307774d55d3886c5a9d0ad1ac838f12eafa5932e17e8a4138328d1a8f84992ec`.
The download receipt and layout audit are also explicitly checked out with LF
line endings so those byte locks remain valid on Windows clean checkouts.

## Historical raw-video evidence

The official raw archive still contains 13 zero-byte formal MP4 files and 1,019 non-empty streams shorter than ten seconds. These facts are preserved as optional raw-diagnostic evidence. They do not block the canonical official JPG/WAV path under the current user-approved protocol, and no raw file was replaced, padded, looped, or reconstructed.
