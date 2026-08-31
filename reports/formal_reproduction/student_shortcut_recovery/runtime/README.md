# Runtime controls

These are the exact small control/audit files used on the 5090. They are included for code review, not as a portable one-command reproduction package: absolute paths intentionally bind the locked remote layout.

The historical `f739399` suffix remains in several filenames because those controls were first prepared at the A0 commit. Their active embedded S3 identity is the exact clean commit `a0aa4d7ad4b98455e26a2fe6ff2537a321293233`; the only `f739399 -> a0aa4d7` source change is the scalar state-buffer audit fix and its test.

Groups:

- `download_audio_ranges_*`, `run_audio_ranges_*`, `launch_audio_ranges_*`, `query_audio_ranges_*`: validated resumable eight-range download.
- `finalize_timm_cache_*`, `run_finalize_timm_cache_*`: transactional two-file cache verification and receipt.
- `run_s3_worker_*`, `launch_s3_*`, `resume_s3_*`, `query_s3_*`, `preflight_s3_*`: persistent S3 training control and monitoring.
- `query_s3_liveness_*` and `query_s3_metrics_*`: compact process/I/O and scientific-metric monitors.
- `audit_s3_training.py`, `run_s3_training_artifact_audit_*`: full S3 output/config/prediction integrity audit, including a second full hash of both official timm cache files.
- `verify_official_cache_audit_function.py`: isolated execution of the cache-audit function against the locked files.
- `run_s3_posthoc_worker_*`, launch/resume/query/preflight and `audit_s3_posthoc.py`: A0-equivalent diagnostics bound to the audited S3 checkpoint. Model reconstruction is offline, uses the same locked timm cache as training, and re-hashes both official backbone files immediately before evaluation.
- `prepare_s4_candidate_*`, its launch/query pair, and `preflight_s4_uploaded_*`: import the exact S4 bundle into a detached worktree, reuse the locked data/cache junctions, then gate execution on focused tests, `compileall`, the complete repository suite, exact HEAD and a clean worktree.
- `run_s4_worker_*`, launch/resume/query and `audit_s4_training.py`: the single-variable S4 training control. It keeps S0 random initialization and changes only `data.train_augment: true -> false`; the audit binds the candidate/S3 receipts, exact config, three 400-step epochs, ordered T=10 prediction arrays and every required artifact hash.
- `run_s4_posthoc_worker_*`, launch/resume/query/preflight and `audit_s4_posthoc.py`: checkpoint-strict prediction-shortcut and four-way modality-ablation reruns gated on the PASS S4 training audit. The final audit requires training, saved-prediction and checkpoint-rerun AP to agree within `1e-12`.

PowerShell files were parsed locally and again after upload. Python files passed local Ruff and `py_compile`; the exact uploaded Python hashes also passed remote `py_compile`. The locked remote environment does not contain Ruff, so no remote Ruff success is claimed.
