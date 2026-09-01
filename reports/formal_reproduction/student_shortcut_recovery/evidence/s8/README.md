# S8 evidence inventory

Only compact, reviewable artifacts are published here.

- `training`: resolved configuration, exact runtime/data/cache/environment receipts, three-epoch history, first-batch diagnostics, implementation behavior and final metrics.
- `control`: detached-candidate preparation/verification, launch/training state, independent training audit, preserved reader-failure state, final completed state, clean audit-fix verification and post-hoc-only recovery receipt.
- `posthoc`: full A–E JSON and the independent post-hoc artifact audit.

The scientific run is commit `60100c6fff95b313ae92bc91b10a3be7135dc437`; the post-hoc reader fix is commit `6f39172120ab877c246d3fd6fbd1a4699a6f2871`. The fixed reader is the only scientific `src/scripts/configs` difference between those commits.

The dataset, caches, student checkpoints, prediction NPZ, bundles and logs remain on the 5090. In particular, `s8_zero_training_predictions.npz` is 9,883,684 bytes with SHA256 `5a28ce8cc58674f89aa4388b9e205410877a954491051b93c9db9e839c2bec68`; its dimensions and metrics are independently bound by `posthoc/s8_posthoc_audit.json`.
