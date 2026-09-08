# Temporary real-multiframe teacher-sampling audit (Phase B)

Selection was deterministic (seed 42) over 512 mixed validation records. The
official records contain no `raw_video_path`, `official_video_path`, or
`video_path`; all 512 selected records are marked raw-video unavailable and
have zero existing supported video paths. They contain only the canonical JPG
keyframe groups.

The diagnostic therefore returns `BLOCKED_BY_TEACHER_FRAME_SAMPLING`. A true
uniform 8-frame-per-second comparison cannot be inferred from repeated JPG
keyframes, so no substitute features were produced. The canonical teacher
cache, model checkpoints, and official T=10 data were not modified.

The positive raw-video path is nevertheless implemented and independently
tested. When official raw videos are supplied, it decodes uniform-center 8-frame
views inside each of the official 10 one-second task segments, exports them
through the locked InternVideo2 model, and compares repeat-keyframe and real-frame
receipts using direct-logit, 100-shuffle, transition, query-conditioned
train-fit/validation-eval, and temporal-geometry diagnostics. It fails closed if
the locked teacher config or a separate canonical train receipt is unavailable.
