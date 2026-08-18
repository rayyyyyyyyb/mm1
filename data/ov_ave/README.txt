OV-OrthKD workspace scaffold
=================================

This folder was created by `python scripts/scaffold_workspace.py`.

What each folder is for:
- data/raw/: benchmark archives, extracted raw files, or manually downloaded upstream releases
- data/ov_ave/: source and exported manifests that the training code reads
- data/teacher_cache/ov_ave/: offline teacher artifacts written by export_teacher_artifacts.py
- weights/: teacher checkpoints
- outputs/: logs, configs, checkpoints, and preflight outputs

Template manifests:
- `*_source.template.jsonl` are examples, not ready-to-train files
- copy a template to `train_source.jsonl`, `val_source.jsonl`, or `test_source.jsonl`
- replace every path with your real local file paths
- keep `frame_paths`, `spectrogram_paths`, `audio_paths`, and `segment_labels` aligned by segment index

Two valid audio styles:
1. Per-segment audio files:
   - `audio_paths`: ["seg_000.wav", "seg_001.wav"]
2. One clip waveform plus timestamps:
   - `audio_path`: "clip.wav"
   - `segment_timestamps`: [[0.0, 1.0], [1.0, 2.0]]
