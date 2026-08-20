# R3 user-approved paper-specified reconstruction

Date: 2026-08-20

The user supplied the final R3 taskbook and explicitly instructed the agent to complete it without further confirmation. The taskbook changes the claim from unavailable `archival_exact` history to `paper_specified_reconstruction` and freezes the following nine previously blocked facts. This file records that approval; it is not presented as recovered historical evidence.

Taskbook attachment SHA256: `49113849a33a728c3cefdad69b0067ef9ba54946e097c9384cf1a9614a101d9d`

1. Temporal protocol: ten actual segments, maximum tensor capacity sixteen, query-conditioned binary labels, no temporal resampling, overflow is an error.
2. InternVideo identity: official InternVideo repository, upstream `InternVideo2_CLIP_small` implementation configured as Base/B14 with the exact three taskbook checkpoints.
3. Scheduler and early stopping: 30 full epochs, at most 400 batches per epoch, epoch-level `CosineAnnealingLR(T_max=30)`, no guessed patience, validation segment AP selects the saved best checkpoint.
4. Student initialization and augmentation: taskbook backbones, `pretrained=false`, and the exact specified train/validation visual transforms.
5. Visual L2 reduction: mean over feature dimension followed by masked mean over valid temporal segments.
6. Query-aware fusion: `concat_mlp_query_conditioned`.
7. Teacher frame sampling: official raw ten-second video; ten one-second intervals; deterministic 16-fps timestamp grid; upstream middle/uniform rule selecting eight frames per interval; short or missing video blocks.
8. Student audio preprocessing: fixed OV-AVEL `imagebind/data.py` semantics at repository commit `b5fe1d685d0c6d0d6fd80312b5ccde79f9b73ea6`, including per-clip mean centering, Kaldi fbank, the taskbook dimensions/statistics, and no second ImageNet normalization.
9. Evaluator mapping: paper F1@0.5 maps to `ovavel_segment_f1_at_0_5`; validation-calibrated F1 maps to `ovavel_segment_f1_at_validation_selected_threshold`; event F1 remains supplemental.

Approved by: `user`

Claim boundary: `paper_specified_reconstruction`
