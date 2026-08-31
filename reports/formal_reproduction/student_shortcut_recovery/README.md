# Student shortcut recovery

Start with [WEB_REVIEW_HANDOFF.md](WEB_REVIEW_HANDOFF.md).

Detailed A0, S3, and S4 evidence is in [A0_RESULTS.md](A0_RESULTS.md), [S3_RESULTS.md](S3_RESULTS.md), and [S4_RESULTS.md](S4_RESULTS.md). The separate source/runtime review is in [IMPLEMENTATION_AUDIT.md](IMPLEMENTATION_AUDIT.md).

This is a noncanonical diagnostic package. It preserves the official `T_task=10` metric timeline, treats `T_max=16` only as positional capacity, and stops before S5/S6 or formal Full training. S4 changed only the training augmentation switch and was rejected because it worsened ranking metrics and accelerated the content-independent collapse.

Git contains only source, configuration and small review evidence. Datasets, caches, checkpoints, prediction arrays, archives, bundles and progress logs remain on the 5090.
