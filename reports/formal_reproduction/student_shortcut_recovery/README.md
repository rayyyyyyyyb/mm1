# Student shortcut recovery

Start with [WEB_REVIEW_HANDOFF.md](WEB_REVIEW_HANDOFF.md).

Detailed A0, S3, S4, and S7 evidence is in [A0_RESULTS.md](A0_RESULTS.md), [S3_RESULTS.md](S3_RESULTS.md), [S4_RESULTS.md](S4_RESULTS.md), and [S7_RESULTS.md](S7_RESULTS.md). The separate source/runtime review is in [IMPLEMENTATION_AUDIT.md](IMPLEMENTATION_AUDIT.md).

This is a noncanonical diagnostic package. It preserves the official `T_task=10` metric timeline, treats `T_max=16` only as positional capacity, and stops before S5/S6 or formal Full training. S7 bypassed only the temporal Transformer. It improved AP/AUROC but failed the pre-approved early-checkpoint causal gates and left visual content with no measurable contribution, so it does not authorize formal Full training.

Git contains only source, configuration and small review evidence. Datasets, caches, checkpoints, prediction arrays, archives, bundles and progress logs remain on the 5090.
