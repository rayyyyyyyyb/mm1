# R3 Remaining-Defect Regression Matrix

This report covers the 18 code defects listed in section 15 of the R3 taskbook. A
`PASS` here means that the behavior is implemented and regression-tested. It does
not claim that SharePoint data, all teacher weights, the full cache, or the single
real optimizer-step receipt already exist.

| # | Required behavior | Status | Implementation evidence | Regression evidence |
|---:|---|---|---|---|
| 1 | `close/open` maps to `seen/unseen` through one helper | PASS | `src/data/split_types.py`; dataset, source builder, audit and training import it | `tests/test_r2_split_type_contract.py` |
| 2 | Canonical readiness cannot be bypassed by changing one boolean | PASS | `scripts/train_ov_orthkd.py::validate_repro_config`; `src/utils/canonical_readiness.py` | `tests/test_r2_canonical_readiness_gate.py::{test_archival_exact_claim_cannot_bypass_gate_with_false_boolean,test_resolved_evidence_cannot_bypass_full_run_block,test_paper_reconstruction_claim_cannot_skip_readiness}` |
| 3 | Eval-only does not construct an unresolved scheduler | PASS | Eval-only branches before optimizer/scheduler construction in `scripts/train_ov_orthkd.py` | `tests/test_r1_checkpoint_resume.py::test_eval_only_main_never_constructs_scheduler` |
| 4 | Singleton teacher rows are never broadcast over segments | PASS | Strict shape handling in `src/data/ov_avel_dataset.py` | `tests/test_r1_dataset_integrity.py::test_singleton_teacher_rows_are_not_broadcast` |
| 5 | Artifact overrides retain relative hierarchy, not basename only | PASS | Safe source-root-relative override resolution in `src/data/ov_avel_dataset.py` | `tests/test_r1_dataset_integrity.py::{test_artifact_override_preserves_relative_hierarchy_and_avoids_basename_collision,test_artifact_override_rejects_source_root_traversal}` |
| 6 | Teacher cache is isolated by split | PASS | `src/teachers/common.py::strong_teacher_artifact_paths` and split-root publication in `src/teachers/pipeline.py` | `tests/test_r2_teacher_export_scaling.py::test_artifact_paths_are_split_safe_and_reject_unsupported_split` |
| 7 | Per-record export does not rewrite one large JSON receipt | PASS | Atomic per-record receipts plus one final aggregate in `src/teachers/pipeline.py` | `tests/test_r2_teacher_export_scaling.py::{test_export_writes_each_receipt_once_and_shares_query_embedding,test_resume_scans_per_record_receipts_without_aggregate_jsonl}` |
| 8 | Checkpoints save/restore early state, all RNGs and DataLoader generator | PASS | `src/utils/reproduction_fingerprint.py::{capture_rng_state,restore_rng_state}` and checkpoint state in `scripts/train_ov_orthkd.py` | `tests/test_r1_checkpoint_resume.py::{test_rng_and_loader_generator_states_round_trip,test_epoch_boundary_resume_matches_uninterrupted_ids_losses_and_parameters}`; `tests/test_r2_exact_epoch_resume.py::test_three_epoch_worker_augmentation_resume_is_exact` |
| 9 | Formal reproducible config uses `persistent_workers=false` | PASS | `src/data/ov_avel_dataset.py` honors the explicit boolean; R3 config is false | `tests/test_r2_exact_epoch_resume.py::test_data_loader_honors_explicit_false_persistent_workers`; `tests/test_r3_conference_reconstruction.py` |
| 10 | Backbone dimension probing does not mutate BatchNorm | PASS | Train/eval state and buffers are preserved in `src/models/ov_orthkd.py::_infer_feature_dim` | `tests/test_r2_model_construction_state.py::test_feature_dim_probe_preserves_batchnorm_buffers_and_training_mode` |
| 11 | NumPy loads always use `allow_pickle=False` | PASS | Dataset, atomic artifacts, audit and BEATs wrapper use explicit safe loading | `tests/test_r1_dataset_integrity.py::test_numpy_object_artifacts_are_rejected_without_pickle`; `tests/test_r2_teacher_wrapper_safety.py::test_beats_numpy_waveforms_disable_pickle_and_require_exact_npz_key` |
| 12 | Real arrays/waveforms/artifacts reject NaN and Inf | PASS | Dataset, audio preprocessing, atomic publication and source/export audit use finite checks | `tests/test_r1_dataset_integrity.py::{test_nonfinite_teacher_artifact_fails_immediately,test_labels_must_be_nonempty_finite_and_binary}`; `tests/test_r3_audio_preprocessing.py::{test_nonfinite_waveform_is_rejected,test_student_adapter_repeats_channels_resizes_and_stays_finite}` |
| 13 | Image reads close file handles | PASS | `src/data/ov_avel_dataset.py` and layout discovery use `with Image.open(...)` and copy/convert before return | `tests/test_r1_dataset_integrity.py::test_image_is_detached_from_file_handle` |
| 14 | CUDA latency synchronizes before and after timing | PASS | `scripts/measure_efficiency.py::measure_latency` synchronizes before event start and after event end | `tests/test_r3_remaining_defects.py::test_cuda_latency_measurement_synchronizes_before_and_after_timed_region` |
| 15 | data/teacher/evaluator/archival/preprocessing locks enter the fingerprint | PASS | `scripts/train_ov_orthkd.py::build_runtime_reproduction_fingerprint`; R3 also binds download lock | `tests/test_r2_canonical_readiness_gate.py::test_fingerprint_binds_locks_audit_git_mode_and_variant`; `tests/test_r3_remaining_defects.py::test_download_lock_is_part_of_runtime_fingerprint` |
| 16 | Formal checkpoint/config fingerprint mismatch rejects resume | PASS | Train and standalone evaluator compare the invocation-invariant fingerprint before state/metrics | `tests/test_r1_checkpoint_resume.py::test_incompatible_resume_fingerprint_is_rejected_before_state_load`; `tests/test_reproduction_evaluation.py::test_formal_checkpoint_requires_matching_invariant_fingerprint` |
| 17 | No fabricated audio logits | PASS | `scripts/train_ov_orthkd.py::require_real_weak_logits` rejects nonzero KD weight without a real mask | `tests/test_training_reproducibility.py::test_weak_logit_kd_requires_real_nonempty_mask` |
| 18 | Missing real teacher artifacts fail fast | PASS | Strict dataset mode and non-mock export lock validation reject missing artifacts/resources | `tests/test_strict_reproduction_data.py::{test_missing_required_weak_feature_names_field_and_record,test_invalid_required_teacher_dimension_names_artifact}`; `tests/test_r2_teacher_export_lock_binding.py::test_every_non_mock_export_requires_a_teacher_lock` |

## Frozen verification

RTX 5090 command scope: the 15 test files named above, including canonical gate,
resume, data integrity, teacher export, evaluation, CUDA synchronization and strict
data behavior.

- First run: exit `1`, `129 passed, 1 failed in 67.78s`. The only failure showed
  that a missing real-preflight receipt failed closed but lacked the canonical gate
  error prefix.
- Focused fix verification: exit `0`, `1 passed in 6.11s`.
- Full matrix rerun: exit `0`, `130 passed in 65.86s`.

No formal student training, real-data optimizer step, or synthetic readiness receipt
was produced by these tests.
