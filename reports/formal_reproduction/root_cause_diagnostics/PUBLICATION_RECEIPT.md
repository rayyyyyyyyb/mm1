# Diagnostic evidence publication receipt

Date: 2026-08-27

Branch: `repro/root-cause-diagnostics`

## Verified evidence commit

- Commit: `59e5f7c919b6b8d427a8f68f751cd35b25d160d4`
- Parent: `c5c50361f549c84cb0a934955ac504137977003d`
- Commit message: `diagnostics: publish completed control evidence`
- Diff stat: 39 files changed, 2,291 insertions, 2 deletions
- Incremental bundle: 56,474 bytes
- Bundle SHA256: `b7d623d9f244d5462f9eae459a7613826ad6fb8b34a076a59ba617db0523d2d8`

## Exact 5090 verification

The bundle was verified and imported into the existing clean diagnostic worktree. Before testing, HEAD was exactly the evidence commit and Git dirty count was zero. The locked environment used:

- Python: `E:\OV-OrthKD-R0\env\.venv\Scripts\python.exe`
- MinGit: `E:\OV-OrthKD-R3\tools\mingit-2.55.0.5\root\cmd\git.exe`
- Hugging Face and Transformers offline mode

Command: `python -m pytest -q`

Result: `399 passed in 338.65s (0:05:38)`, `PYTEST_EXIT=0`.

UTC interval: `2026-08-27T03:56:40.8752044Z` to `2026-08-27T04:02:22.3211683Z`.

After testing, HEAD remained the exact evidence commit and Git dirty count remained zero. The test did not start training, teacher export or a real-data preflight.

## Artifact boundary

The published control evidence contains no dataset, teacher cache, checkpoint, NPZ prediction, PR-curve NPZ, ZIP, bundle or large progress log. The `control_runs/` payload contains 28 immutable run files totalling 151,524 bytes; the largest is 33,917 bytes. Source-copy SHA256 mismatches are zero.

## Publication-tip note

This receipt and the activity-ledger entry are documentation-only additions made after the exact full-suite run. Review the branch tip for this receipt; the scientific source, configs, tests and control-run evidence are byte-identical to the verified evidence commit.
