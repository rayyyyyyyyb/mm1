# OV-OrthKD T=10 temporal protocol correction design

Date: 2026-08-24

## Goal

Make the official OV-AVEBench task timeline unambiguous and executable: every real sample has ten one-second task segments, and labels, student logits, temporal teacher features, masks, and evaluator inputs remain aligned to those ten segments without any 10-to-16 conversion.

## Evidence boundary

- The official OV-AVEBench metadata has 24,800/24,800 label vectors of length 10, and the official loader requires exactly ten ordered visual images.
- Initial private artifact commit `dca9f052fbe4a1e9d7982f24bdcec3edf1363fd4` already configures InternVideo2 with `num_frames=8`; its wrapper repeats or uniformly selects each supplied frame group to exactly eight frames.
- The same initial commit configures `max_segments=16` on the dataset/student and constructs a synthetic T=16 efficiency input. In the student, this value sizes positional capacity; forward uses the actual input `seq_len`.
- No initial-source evidence was found for `num_frames=16`, `clip_len=16`, or label/logit conversion to T=16.
- R3's 16-fps raw decoder is a later reconstruction and must be isolated as optional raw-video diagnostics, not presented as the canonical task protocol.

## Terminology contract

| Name | Exact meaning | Canonical value |
|---|---|---:|
| `data.num_segments` | Number of official one-second task/evaluation segments | 10 |
| `student.max_position_segments` | Maximum positional-embedding capacity; never a target label length | 16 |
| `teacher_export.internvideo2.num_frames` | Frames passed to InternVideo2 for one task segment | 8 |
| `teacher_export.internvideo2.input_mode` | Visual source selection | `official_segment_keyframes` |
| `teacher_export.internvideo2.frame_expansion_policy` | Deterministic expansion of one official keyframe to eight teacher frames | `repeat_last_to_num_frames` |
| `teacher_export.internvideo2.raw_multiframe.sampling_fps` | Optional diagnostic raw-video sampling grid | 16 only in raw mode |
| audio `sample_rate` | Official WAV sampling rate | 16,000 Hz |

`num_frames`, `max_position_segments`, `sampling_fps`, and audio `sample_rate` must never be used to infer or rewrite `data.num_segments`.

## Canonical data and teacher flow

The source-manifest builder consumes one WAV, exactly ten official JPGs named `00000001.jpg` through `00000010.jpg`, and exactly ten binary labels. Raw MP4 is optional diagnostic metadata. Each JPG forms one task segment. The InternVideo2 wrapper repeats that segment's one JPG deterministically to eight frames, encodes ten independent eight-frame inputs, and returns `[10,512]` features plus `[10]` logits. BEATs returns `[10,768]`; CLAP returns `[1024]`.

The dataset rejects a canonical record whose label count is not exactly ten. Collation preserves `[B,10,...]`; the student slices its length-16 positional embedding to the observed T=10 and returns `[B,10]` logits. Evaluator collection must validate logits, labels, and masks as identical `[B,10]` tensors before flattening only the valid entries for AP/AUROC/F1.

## Shape receipt

A forward-only temporal audit records, without an optimizer step or formal metric claim:

- visual input `[B,10,3,224,224]`;
- audio input `[B,10,3,224,224]`;
- visual teacher features `[B,10,512]`;
- audio teacher features `[B,10,768]`;
- labels, sequence mask, and student logits `[B,10]`;
- evaluator pre-flatten tensors `[B,10]` and valid flattened inputs `[N]`.

The receipt fails closed on any T other than 10 or on any cross-field shape mismatch.

## Documentation policy

Repository prose and configuration comments describe the official ten one-second temporal segments. Historical reports remain historically identifiable but receive a supersession note where their wording could be mistaken for the active protocol. Efficiency reports label T=10 as canonical real-protocol measurement; any T=16 measurement is explicitly synthetic capacity analysis and cannot be placed in a paper row as a real 16-segment clip.

The supplied PDF is immutable evidence, not editable source. A correction note will provide exact replacement language for the manuscript source when it becomes available.

## Non-goals

- No label, logit, mask, teacher-feature, or evaluator resampling.
- No full teacher-cache export in this focused correction unless separately authorized by the R4 execution sequence.
- No optimizer-step preflight or formal student training.
- No claim that every one-second segment originally decoded 16 frames.
