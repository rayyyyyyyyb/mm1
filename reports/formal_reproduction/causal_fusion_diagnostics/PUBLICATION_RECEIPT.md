# Publication receipt

Date: 2026-08-27

Branch: `repro/causal-fusion-diagnostics`

Scientific run commit: `d5d13c2a9c913d35addbc3b496d76988008bd613`

Complete evidence commit verified on the 5090: `76dabc67e939012653afa10d1526556e10d6a2d8`

## Exact 5090 verification

- Evidence bundle: 80,965 bytes; SHA256 `5b21323fd34fa9f0d6c3983310a48bfa44442ce422e3af99c72f9d523fd292fc`.
- Fresh detached worktree: `E:\OV-OrthKD-R3\causal-fusion-76dabc6`.
- Locked environment: R0 virtual environment plus the locked MinGit executable.
- HEAD before the test: exact `76dabc67e939012653afa10d1526556e10d6a2d8`; dirty count 0.
- `compileall` log: 0 bytes; SHA256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- Full pytest log: `428 passed in 338.65s (0:05:38)`; 1,040 bytes; SHA256 `316c7202dddf68e2b81f3b5143f96831decf6fc253d0e5661ec03d2307023b0b`.
- Independent post-test query: HEAD unchanged; dirty count 0; bundle SHA256 unchanged.

The original long-lived SSH caller timed out after pytest completed, so its parent PowerShell process did not write the planned `verification_receipt.json`. The complete test log and the independent immutable checks above are retained as the evidence. This limitation is disclosed rather than representing a nonexistent JSON receipt as present.

The final publication commit may add only this receipt, the handoff wording, and the chronological ledgers. The scientific source, configurations, tests, and run artifacts verified at `76dabc67…` must remain byte-identical.

## Local limitation

Local `compileall` exited 0. Local pytest aborted during collection with exit 3 while Anaconda imported torch/NumPy and reached `numpy.__init__.py:blas_fpe_check`; no assertion ran. The local result is not reported as a pass. The locked 5090 run above is the passing full-suite gate.

## Upload boundary

Git contains source, configurations, tests, reports, and small structured receipts only. It does not contain the dataset, teacher cache, checkpoints, prediction arrays, PR-curve arrays, ZIP files, bundles, or progress logs.
