# MM26 temporal-protocol text corrections

## Scope and evidence boundary

The conference PDF is retained as immutable historical evidence. No editable
paper source is present in this repository, so this file provides exact
replacement language for the next editable manuscript revision.

The official OV-AVEBench task timeline is ten one-second temporal segments for
each ten-second video. Labels, temporal teacher features, student logits, and
F1/AP/AUROC inputs remain on this T=10 timeline. The implementation does not
interpolate, repeat, resample, or relabel a T=10 target into T=16.

The value 16 has two distinct non-task meanings in the audited code:

- `student.max_position_segments=16` is positional-embedding capacity; the
  student slices this table to the actual sequence length, which is T=10 for
  the official task.
- `temporal_sampling_fps=16` belongs only to the explicitly disabled raw-video
  diagnostic decoder and is not used by the canonical JPG/WAV data path.

The pinned InternVideo2 wrapper consumes `num_frames=8` per teacher call. In
the current canonical reconstruction, each of the ten official one-second
keyframes is deterministically repeated to satisfy that eight-frame wrapper
input. This describes the released reconstruction path; it does not establish
that the original experiment decoded eight or sixteen distinct frames per
second.

## Exact replacement language

### Dataset and temporal protocol

Replace any statement that each video is divided into 16 temporal segments
with:

> Following the official OV-AVEBench protocol, each ten-second video is
> represented by ten one-second task segments. Ground-truth labels, student
> predictions, temporal teacher features, and evaluation inputs are aligned on
> these same ten segments.

### Teacher input description

Replace wording that equates task segments with teacher frames or clips with:

> Task-time alignment (T=10) is independent of the frame dimension consumed by
> a video teacher. In the released reconstruction, the InternVideo2 wrapper
> accepts eight frames for each official task segment; the canonical
> preprocessed path repeats that segment's official keyframe to fill the
> wrapper input. No task label is converted from T=10 to T=16.

Do not write that every one-second segment necessarily decodes 16 distinct
frames. The audited source does not support that claim.

### Configuration explanation

Use:

> The student supports positional indices for up to 16 segments, while the
> official OV-AVEBench input used in all task results has length 10. The extra
> positional capacity does not change the label or prediction timeline.

### Figure and table captions

For task-time diagrams, use:

> All temporal tensors in the OV-AVEBench task are aligned to the official ten
> one-second segments (T=10).

For efficiency results, use:

> Runtime is measured at the official task length T=10. Any separately reported
> T=16 measurement is a synthetic positional-capacity diagnostic and is not a
> paper-protocol result.

### Phrases to remove or qualify

- Replace “16 temporal segments” with “the official ten one-second temporal
  segments.”
- Replace “per-16-seg clip” with “per ten-segment OV-AVEBench clip” when the
  text refers to task evaluation.
- Remove an unqualified “16 fps” from task-protocol descriptions. If retained
  for a decoder diagnostic, label it as a raw-video diagnostic sampling grid
  that is disabled in the canonical reconstruction.
- Keep `num_segments`, `num_frames`, `clip_len`, `fps`, and `sampling_rate` as
  separate terms; never use one as a synonym for another.

## Result-table policy

The clarified wording does not authorize changing the original training
logic, metric formulas, or table values. Results may remain unchanged once the
real preflight receipt confirms student labels and logits are both `[B,10]`.
That real student forward has not yet been executed because the audited full
teacher cache is still pending; it must not be claimed from configuration alone.
