# Web Diagnosis Review Assessment

Date: 2026-08-26

Starting evidence commit: `44b88fc8a011436e33b6ff91e65d220511c7ecd4`

Diagnostic branch: `repro/root-cause-diagnostics`

## Verdict

The recommended causal order is sound: do not attribute the gap to seed noise, do not sweep loss weights first, and use evaluation → teacher → shared student → Full-specific controls to localize the failure.

The following observations are already supported by committed evidence:

- the Full run is complete and byte/audit healthy but does not reproduce the paper ranking;
- the test prediction at `0.5` is all-positive and the best validation AP occurs at epoch 1;
- the current formal lineage has no same-pipeline Student-only or Visual-only run;
- teacher-side projectors are optimized with the student and the feature/orthogonal losses rapidly approach zero;
- current fusion is concat-MLP while paper Eq. 3 states additive fusion;
- current `pretrained=false`, 400 batches per epoch, epoch-cosine scheduler, no early stopping and train augmentation are reconstruction assumptions rather than recovered historical facts.

## Corrections and boundaries

1. The paper's official repository, <https://github.com/ScottBlizzard/OV-OrthKD>, is public but currently has one README-only commit and explicitly says code/checkpoints are still being organized. It cannot resolve fusion, scheduler or projector semantics today.
2. The official OV-AVEL checkout at locked commit `b5fe1d685d0c6d0d6fd80312b5ccde79f9b73ea6` contains baseline code and annotations but no released fine-tuning checkpoint or prediction output. Its `.checkpoints/readme.txt` is only 62 bytes. Gate 1 therefore remains asset-blocked; our predictions must not be substituted.
3. “Paper additive fusion,” “shared query projection,” “frozen projector,” and alternate `step400` meanings are candidate reconstruction hypotheses. The first two are paper/code structure mismatches, but no public archival implementation proves which code produced the paper tables. They must be opt-in A/B factors and must not replace the current pipeline before shared controls are measured.
4. The paper defines Table 2 probes only as a “light linear probe”; optimizer, feature normalization, regularization, epochs and selection are absent. A new probe can be transparent and useful, but not archival-exact.
5. The user-confirmed official temporal protocol remains fixed at `T=10`; no temporal conversion is part of this diagnosis.

## First new evidence: Table 2 visual direct logits

The locked teacher cache was read without modification over every official segment:

| Split | Samples | Shape per sample | AP | AUROC | Paper AP | Paper AUROC |
|---|---:|---|---:|---:|---:|---:|
| validation | 5,798 | `[10]` | 0.771934530 | 0.707681250 | 0.767 | 0.707 |
| test | 5,820 | `[10]` | 0.780220386 | 0.716227041 | 0.776 | 0.716 |

All 11,618 arrays were present, finite and exactly length 10. Test AUROC agrees with the paper to three decimals and AP differs by only `+0.00422`; validation is similarly close. This materially lowers the probability that the locked InternVideo2 identity, T=10 keyframe alignment, or visual cache is the main cause of the Full result gap. It does not yet validate the visual/audio feature probes or student transfer.

## Immediate execution decision

Proceed with prediction-only aggregation/calibration audit, transparent teacher feature probes, and exact-current-pipeline Student-only/Visual-only controls. Delay structural and training-recipe A/B changes until those controls identify the failing layer.
