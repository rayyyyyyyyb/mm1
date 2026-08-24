# T=10 temporal protocol correction implementation plan

**Goal:** Enforce and evidence the official ten-segment task timeline while separating student capacity, teacher frame count, raw diagnostic fps, and audio sample rate.

**Architecture:** Add one shared temporal-shape contract, route canonical InternVideo2 export through official keyframes, make raw video optional diagnostics, and bind the clarified terminology into formal configuration and readiness evidence. Preserve metric formulas and training behavior; add fail-closed checks before flattening.

**Tech Stack:** Python 3.11, PyTorch, NumPy, pytest, YAML, Windows/RTX 5090.

**Spec:** `docs/superpowers/specs/2026-08-24-t10-temporal-protocol-correction-design.md`

## Global constraints

- Canonical task length is exactly 10.
- No 10-to-16 transformation is permitted anywhere.
- Student positional capacity 16 and InternVideo2 frame count 8 are independent dimensions.
- Canonical keyframe mode has no fps assumption; 16-fps remains optional raw diagnostics only.
- Shape audit is forward-only and cannot consume the single real optimizer-step allowance.
- Formal training remains blocked.

### Task 1: Lock the temporal and shape contracts with failing tests

**Files:**
- Create: `tests/test_r4_t10_temporal_protocol.py`
- Modify: `tests/test_r3_conference_reconstruction.py`
- Modify: `tests/test_r3_internvideo_raw_video.py`

- [x] Add a canonical dataset test that rejects 9/16 labels and preserves ten labels without resampling.
- [x] Add a model/metric contract test requiring `[B,10]` logits, labels, and masks and reporting the flattened valid metric length.
- [x] Add a keyframe teacher test requiring ten groups, one official frame per group, and deterministic repeat-to-eight behavior.
- [x] Add source-manifest tests proving raw MP4 is optional and ten JPGs/labels remain mandatory.
- [x] Run focused tests and confirm RED failures are caused by missing new behavior.

### Task 2: Implement explicit task, capacity, and frame semantics

**Files:**
- Create: `src/utils/temporal_protocol.py`
- Modify: `src/data/ov_avel_dataset.py`
- Modify: `src/models/ov_orthkd.py`
- Modify: `scripts/train_ov_orthkd.py`
- Modify: `scripts/evaluate_pr_f1.py`

- [x] Define the official task length and shape validator.
- [x] Require canonical dataset records to have exactly ten segments.
- [x] Introduce `student.max_position_segments` while preserving legacy constructor compatibility outside formal configs.
- [x] Reject student sequences longer than positional capacity, without padding or resampling shorter sequences.
- [x] Validate evaluator inputs before flattening and expose the shape receipt fields.
- [x] Run focused tests to GREEN.

### Task 3: Restore canonical keyframe teacher export

**Files:**
- Modify: `src/teachers/internvideo2_visual.py`
- Modify: `src/teachers/pipeline.py`
- Modify: `scripts/export_teacher_artifacts.py`
- Modify: `scripts/inspect_teacher_identity.py`
- Modify: `scripts/build_ov_avebench_source_manifests.py`

- [x] Add explicit `official_segment_keyframes` and `raw_multiframe` modes.
- [x] In canonical mode, require ten one-frame groups and repeat each frame to `num_frames=8`.
- [x] Dispatch by configured mode; never silently fall back between keyframe and raw inputs.
- [x] Make `--raw-video-root` optional and record raw defects only as diagnostic metadata.
- [x] Update repeat-2 teacher smoke to use the configured mode.
- [x] Run focused tests to GREEN.

### Task 4: Add forward-only shape audit and correct efficiency labels

**Files:**
- Integrate: `scripts/preflight_ov_orthkd.py` (no separate optimizer-free claim path)
- Modify: `scripts/preflight_ov_orthkd.py`
- Modify: `scripts/measure_efficiency.py`
- Test: `tests/test_r4_t10_temporal_protocol.py`

- [x] Write the preflight receipt schema containing all requested batch, teacher, label, logit, and metric-input shapes.
- [x] Assert real preflight receipts use the same shape contract.
- [x] Default efficiency measurement to canonical T=10 and label T=16 only as synthetic capacity analysis when explicitly requested.
- [x] Run focused tests to GREEN.

### Task 5: Correct formal configuration, locks, and prose

**Files:**
- Modify: `configs/ov_orthkd_mm26_repro.yaml`
- Modify: `configs/ov_orthkd_mm26_smoke.yaml`
- Modify: `configs/locks/mm26_data_lock.yaml`
- Modify: `configs/locks/mm26_preprocessing_lock.yaml`
- Modify: `configs/locks/mm26_archival_facts.yaml`
- Modify: `src/utils/canonical_readiness.py`
- Create: `reports/archival/R4_USER_APPROVED_TEMPORAL_PROTOCOL.md`
- Create: `reports/R4_T10_TEMPORAL_PROTOCOL_CORRECTION_REPORT.md`
- Create: `docs/MM26_TEMPORAL_PROTOCOL_TEXT_CORRECTIONS.md`
- Modify relevant README/status/historical reports with supersession notes.

- [x] Bind `data.num_segments=10`, `student.max_position_segments=16`, and teacher `num_frames=8` independently.
- [x] Remove raw-video defects from canonical readiness while preserving their diagnostic facts.
- [x] Replace active “16 temporal segments/per-16-seg clip” wording with official ten-segment language.
- [x] Provide exact manuscript replacement text without modifying the evidence PDF.
- [x] Run config/readiness focused tests.

### Task 6: Real evidence and independent verification

**Files:**
- Generate: `reports/mm26_source_manifest_audit.json`
- Generate: `reports/teachers/teacher_identity.json`
- Generate: `reports/teachers/smoke_repeatability.json`
- Reserve: `reports/runtime/r4_real_preflight.json`
- Update: `all.md` in both the repository and parent expansion folder.

- [x] Sync code-only changes to the 5090 host.
- [x] Generate and audit all 24,800 source records from official JPG/WAV data.
- [x] Run repeat-2 real teacher smoke in keyframe mode.
- [x] Preserve the real preflight allowance at zero invocations while the teacher cache is incomplete.
- [ ] Run the single authorized real one-step preflight after full cache audit and confirm `[B,10]` labels/logits.
- [x] Run compileall, focused tests, full pytest, pip check, CUDA check, diff checks, and an independent requirements/code review.
- [ ] Commit and push the R4 branch, then report remaining teacher-cache/preflight/training blockers.
