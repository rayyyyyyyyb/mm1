# D2A paired early-dynamics independent audit

- Artifact status: `D2A_ARTIFACT_AUDIT_PASS`
- Scientific status: `D2A_PRETRAINED_EARLY_DYNAMICS_FAIL`
- Attempted batches: `400`
- Applied updates: `{'random': 394, 'pretrained': 394}`
- Test accessed: `false`
- Automatic extension: `false`

## Independent step-400 gate

- Pass: `False`
- Observed: `{"pretrained_decision_temporal_std": 0.00024077488519275324, "pretrained_minus_random_mixed_concordance": 0.09672713259379562, "pretrained_minus_random_validation_ap": -0.019510898647627672, "pretrained_predicted_positive_rate": 1.0, "pretrained_shuffle_ap_drop": 0.0005216390583230313, "pretrained_shuffle_auroc_drop": 0.0009803289854386499, "pretrained_visual_zero_mixed_concordance_drop": -0.0001376310936166414}`
- Requirements: `{"concordance_delta": true, "predicted_positive_rate": false, "support_count": false, "validation_ap_floor": true}`

## Audit failures

- None

This result is validation-only and diagnostic. It does not authorize test evaluation, D3, Full, a second seed, or automatic schedule extension.
