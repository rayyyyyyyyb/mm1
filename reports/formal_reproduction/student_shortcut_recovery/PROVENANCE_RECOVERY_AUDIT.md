# Provenance Recovery Audit (2026-09-03)

## Scope and decision

This is a read-only recovery attempt before any canonical Full run. The search covered the 5090 repository, its Git refs/reflogs, isolated diagnostic trees, checkpoint metadata, user command-history locations, and experiment logging locations. It did not modify the original dirty repository or shared data/cache junctions.

**Decision: author-original training provenance remains unavailable in the searched scope.** The canonical Full guard therefore remains enabled. The only permitted follow-up is the pre-registered non-canonical visual-only bounded control documented in `VISUAL_ONLY_SUM_CONTROL_PLAN.md`.

## Evidence found

- `git branch -a` on `E:\OV-OrthKD-R3\repo` contains the R2/R3 readiness branches and diagnostic transfer refs, but no author-training branch. `git reflog --all` contains the clone and later diagnostic worktree heads only.
- `git fsck --full --no-reflogs --unreachable` found `53dc809d399dadb66e2e0c1563b6e94e903dcc7e` and `f07fd5c5264a203ead0628c4e3b70d64a55e637b`. Both are duplicate `repro: enforce official T10 temporal protocol` commits with parent `eae79f1`; neither predates the reconstruction history or contains an original training run.
- Checkpoints in the isolated S3--S9, causal, frozen-feature, and canonical-control trees are generated reconstruction artifacts. Representative S9 and S8 `best.pt` files contain `student_state_dict`, `optimizer_state_dict`, `scheduler_state_dict`, `config`, and runtime fingerprints; both report `global_step=1200`, a three-epoch diagnostic configuration, and trainable target projectors. Their 823-key, ~46.36M-parameter student state is evidence of this pipeline, not an author checkpoint.
- The checkpoint optimizer/scheduler states are internally loadable (AdamW and `CosineAnnealingLR`, `T_max=30`), but no checkpoint carries a recoverable author command line, author YAML, or canonical conference schedule.
- The 5090 PowerShell history file has no entries matching OV-OrthKD/training. No W&B or TensorBoard run directories were found under the OV-OrthKD workspace. Existing `requirements`/pip-freeze and verification logs describe the reconstruction environment only.
- `C:\Users\LXT\smc_task3_b4a47f5_complete-history.bundle` was inspected because it was the only user-home history bundle; it is an unrelated SMC repository (`conference-rerun-20260821`) and contains no OV-OrthKD code or run provenance.

## Consequence

The search raises confidence that available artifacts are auditable reconstruction evidence, but it does not recover the missing author choices (loss reduction semantics, target-projector training, and independent text-target projection). No parameter or checkpoint is guessed from the paper. Formal Full, a second random seed, and schedule extension remain paused.

