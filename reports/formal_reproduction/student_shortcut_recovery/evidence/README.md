# Evidence inventory

This directory contains only small review artifacts (JSON, JSONL and YAML) suitable for Git review.

- `a0/{student,visual,full,s0}/prediction_shortcut.json`: query-only, query-position, within-sample centering and shuffle controls.
- `a0/{student,visual,full,s0}/checkpoint_modality.json`: zero-content inference plus path-scale summaries.
- `locks/a0_artifact_audit.json`: aggregate A0 integrity gate.
- `locks/audio_range_download_receipt.json`: resumable eight-range audio weight download receipt.
- `locks/official_timm_cache_receipt.json`: official URL, byte count and SHA lock for both student backbones.
- `locks/candidate_a0aa4d7_verification.json`: exact clean 5090 compile/test receipt.
- `locks/s3_pretrained_backbone_receipt.json`: real `pretrained=True` versus same-seed random construction hashes.
- `baseline_s0`: the small three-epoch S0 history, diagnostics, final metrics, resolved config and implementation behavior used for the strict S3 comparison.
- `s3`: the audited three-epoch pretrained-only metrics, history, first-batch diagnostics, resolved config, behavior receipt and worker/training audit state.
- `s3/posthoc`: independently audited prediction-shortcut, content-ablation and forward-path-scale results, plus the retained failed-launch/resume state.

The corresponding datasets, teacher cache, timm weight files, student checkpoints, prediction NPZ files, bundles and progress logs remain on the 5090 and are not in Git. The receipts record their relevant identities without pretending that the large assets are web-recomputable. The S3 posthoc JSONs were copied here only after their independent artifact audit passed.
