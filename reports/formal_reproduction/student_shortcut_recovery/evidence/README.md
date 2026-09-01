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
- `s4/training`: the audited three-epoch no-augmentation control metrics, history, first-batch diagnostics, resolved config, runtime/lock receipts and environment identity.
- `s4/control`: candidate verification, launch/worker state and the independent S4 training artifact audit.
- `s4/posthoc`: independently audited prediction-shortcut, content-ablation and forward-path-scale results plus launch/worker state.
- `s7/training`: the audited three-epoch temporal-identity metrics, history, first-batch diagnostics, resolved config, runtime/lock receipts and environment identity.
- `s7/control`: exact candidate preparation/verification, launch/worker state and the independent S7 training artifact audit.
- `s7/posthoc`: the three-checkpoint trajectory with four content modes, 100 within-sample shuffles per checkpoint, path scales, compression factors and the recomputed causal decision, plus launch/worker state and the independent posthoc audit.
- `zero_training`: independently audited A–F evidence: full official-JPG content audit, reconstructed step-zero/400/800/1200 visual timeline and Jacobians, forced gate and audio interventions, disposable Full projector probe, exact runtime receipts and completed worker state.

The corresponding datasets, teacher cache, timm weight files, student checkpoints, prediction NPZ files, bundles and progress logs remain on the 5090 and are not in Git. The receipts record their relevant identities without pretending that the large assets are web-recomputable. The S3, S4, S7 and zero-training JSONs were copied here only after their independent artifact audits passed.
