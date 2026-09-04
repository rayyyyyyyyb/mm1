# Student shortcut recovery

Start with [WEB_REVIEW_HANDOFF.md](WEB_REVIEW_HANDOFF.md). The latest read-only audit is [FROZEN_FEATURE_PROBE_RESULTS.md](FROZEN_FEATURE_PROBE_RESULTS.md).

The latest bounded diagnostic is [S9_RESULTS.md](S9_RESULTS.md). Earlier S8, S7, S4, S3 and A0 results remain available in [S8_RESULTS.md](S8_RESULTS.md), [S7_RESULTS.md](S7_RESULTS.md), [S4_RESULTS.md](S4_RESULTS.md), [S3_RESULTS.md](S3_RESULTS.md) and [A0_RESULTS.md](A0_RESULTS.md). The source/runtime review is in [IMPLEMENTATION_AUDIT.md](IMPLEMENTATION_AUDIT.md).

S9 is a noncanonical, single-variable paper-additive control: relative to S8 it changes only `student.fusion_mode` from `concat_mlp_query_conditioned` to `paper_additive_query_conditioned`. Training, A–E, and independent posthoc artifact audits all passed, but the pre-registered scientific outcome is **FAIL**: visual-zero mixed AP/AUROC do not decrease and visual concordance changes by only `0.000056`.

The subsequent read-only frozen-feature audit compared equal-capacity QP, VQP and AQP probes. Artifact/runtime status is **PASS**. The pre-registered S8 step-1200 primary outcome is `VISUAL_INFORMATION_NOT_DECODABLE`; S9 steps 400/800 are `INCONCLUSIVE`, and S9 step 1200 is `VISUAL_INFORMATION_NOT_DECODABLE`. The AQP positive control passes at every point. This closes the narrow hypothesis that a different readout alone can recover label-aligned visual information from these frozen student representations. It does not identify one unique causal layer and does not test the complete paper architecture.

The official `T_task=10` metric timeline is preserved; `T_max=16` is positional capacity only. Neither the S9 result nor the frozen probe authorizes another experiment or formal Full training.

## Latest bounded projector control

The preregistered C0/C1 800-applied-step control is documented in
[STATIC_TARGET_800STEP_RESULTS.md](STATIC_TARGET_800STEP_RESULTS.md), with
machine-readable evidence in
[projector_collapse_summary.json](projector_collapse_summary.json). C1 keeps the
strong projected teacher target static with gradient flow. The target remains
temporally varying, but student decision variation and mixed-label concordance
fail the gates; the final state is **BLOCKED_BY_GRADIENT_CONFLICT**. Full,
second-seed, schedule extension, and test evaluation remain blocked.

Git contains source, configuration, runtime controls and compact review evidence only. Datasets, caches, checkpoints, prediction arrays, archives, bundles and progress logs remain on the 5090.
