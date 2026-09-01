# Student shortcut recovery implementation audit

Date: 2026-09-02

Scientific A0 runtime commit: `f739399463c082cd670dff56e43c710d4fa6f283`

Scientific S3 runtime commit: `a0aa4d7ad4b98455e26a2fe6ff2537a321293233`

Scientific S4 runtime commit: `74d211d34ace74ce3b74ea082a7dfd0379b251fb`

Scientific S7 runtime commit: `a7f0dc06d6a98493c0d03f1caa2059e31c50b648`

Scientific S8 runtime commit: `60100c6fff95b313ae92bc91b10a3be7135dc437`

Scientific S9 implementation commit: `b8ea747dd792c939251152ead734d1826c26980d`

S9 runtime-control commit: `31497d58eb5d17e60cbebc6afa1bef5bcecb37a7`

S8 post-hoc reader-fix commit: `6f39172120ab877c246d3fd6fbd1a4699a6f2871`

Scope: observation-only A0 diagnostics plus the S3 pretrained-student, S4 no-augmentation, S7 temporal-identity, S8 fixed-equal-gate and S9 paper-additive single-variable controls. This package does not authorize or run formal Full training.

## Independent source review

The complete range from the accepted diagnosis baseline `0b2bf7eea8e09a1036432775ecbc0f50c5f7b9d3` to the scientific runtime commit was reviewed without editing during the first pass. It adds only:

- three read-only diagnostic/audit scripts;
- four focused test modules;
- one noncanonical S3 diagnostic configuration;
- the approved design, execution plan and ledger entries.

There is no change under `src/`, no edit to the trainer, model, loss, evaluator, teacher cache, formal configuration or canonical guard. `git diff --check 0b2bf7e..f739399` returned exit 0.

The only source difference from the A0 commit to the S3 runtime commit is a one-line audit serialization fix plus its regression test: scalar integer state buffers are flattened before byte reinterpretation. This is required for EfficientNet BatchNorm `num_batches_tracked` buffers and does not change any model or training computation.

The S4 candidate adds one diagnostic YAML and focused regression coverage; it does not change `src/`, trainer, model, loss, evaluator, teacher cache, canonical configurations, or the canonical full-run guard. After run-name/output normalization, the exact scientific difference from S0 is `{data.train_augment}`.

The S7 candidate adds a fail-closed optional model mode and observation-only diagnostic checkpoint support. The default for a missing or explicit canonical value is still `transformer`; only the noncanonical S7 YAML selects `identity_passthrough`. The temporal encoder is always constructed in the original order, so state-dict keys, parameter identity and constructor-time RNG use are unchanged. The active forward computes `temporal_input = fused_tokens_before_position + position_embedding`; S7 assigns that tensor directly to `shared_features`, while the original mode passes it through the temporal encoder. After output-path normalization, the exact S7/S0 scientific difference set is `{student.temporal_path_mode}`.

## A0 semantics reviewed

- The empirical priors use training labels only. Unknown queries use an explicitly counted global fallback; query-position priors use the matching global position fallback.
- Mean centering is performed independently inside each sample boundary from `sample_offsets`.
- Each of the 100 seed-42 shuffles independently permutes logits only inside the same ten-segment sample; labels and sample boundaries stay fixed.
- Content ablation replaces only `frame` and/or `spectrogram` with same-shape zeros. `frame_valid`, `audio_valid` and `sequence_mask` are preserved.
- Every checkpoint rerun requires strict state loading and canonical equality between the external resolved config and checkpoint-embedded config.
- Labels, logits and metric indices are rejected unless every sample has the ordered official segment indices `0..9` and exactly `T_task=10` values.
- Required path tensors must be finite and have leading `[B,T]`; scale summaries use only valid rows.
- The forward output named `query_features` is `query_proj(shared_features)`, a post-fusion shared-path projection. It is not an unmodified raw text token and is not described as one in the result report.

## S3 single-variable review

After normalizing only `reproduction.variant` and `logging.log_dir`, the S3/S0 configuration difference set is exactly `{student.pretrained}`. The literal YAML diff contains only those two identity/output fields and `pretrained: false -> true`. Seed, data, augmentation, batch size, three-epoch/400-batch diagnostic exposure, `CosineAnnealingLR(T_max=30)`, model, loss, gate, fusion and temporal settings are unchanged.

The config value reaches both constructors:

1. `build_model_and_loss` passes `student.pretrained` into `OVOrthKDStudent`;
2. `OVOrthKDStudent` passes the same boolean to both `SequenceImageEncoder` instances;
3. each encoder passes it directly to `timm.create_model(..., pretrained=pretrained)`.

The runtime receipt constructs each exact backbone first with `pretrained=True`, then with `pretrained=False` under the same seed. It hashes the actual backbone state, requires equal architecture dimensions/parameter counts but different state hashes, records resolved timm pretrained metadata, and propagates download/construction failures without fallback.

The two files are first locked from the exact official URLs in the installed timm 1.0.28 metadata. The cache receipt binds URL, byte count and full SHA256; the audio file additionally verifies the official filename SHA prefix. The receipt and training both run with Hugging Face/Transformers offline and `TIMM_USE_OLD_CACHE=1`, so construction must use those receipted files. A fresh run rejects an existing control directory or nonempty output. Resume is explicit and requires `last.pt`. Completion requires exactly three history records, three first-batch diagnostic records, global step 1200, finite full validation/test predictions and the official `T=10` ordering.

## S4 single-variable review

`data.train_augment` is read once by `create_ov_avel_data_loaders` and is passed only to the training dataset. With the switch enabled, the frame transform is `Resize -> RandomHorizontalFlip(0.5) -> ColorJitter -> ToTensor -> ImageNet normalization`; with it disabled, the transform is `Resize -> ToTensor -> ImageNet normalization`. Validation and test use the deterministic transform in both configurations. The switch does not affect audio, labels, teacher cache, segment ordering, metrics, or the number of official keyframes.

Focused tests require the S4/S0 normalized difference set to be exactly `{data.train_augment}` and dynamically inspect all three loader transforms. They also lock seed 42, `student.pretrained=false`, three epochs, 400 batches per epoch, scheduler `T_max=30`, all KD weights zero, `T_task=10`, and `T_max=16`. The YAML's canonical-LF SHA256 is `5b81218b55907a5dfb0419e62eff2128f0d08ce9301c97c081237f8c8f599b33`; runtime guards normalize only checkout CRLF to canonical LF before comparison and still require exact commit plus a clean worktree.

## Artifact audit design

- A0 is accepted only when all Student, Visual, Full and S0 JSONs are PASS, source checkpoint/NPZ hashes match the locked values, exact Git is clean, and saved versus checkpoint-rerun AP agrees within `1e-12`.
- S3 training is accepted only when the config is the exact single-variable control, both pretrained receipts pass, all required outputs exist, histories/diagnostics are complete, prediction arrays have the exact schema/order and all key files are hashed.
- S3 posthoc is accepted only when it is bound back to the audited S3 checkpoint and NPZ hashes and training AP, saved prediction AP and checkpoint-rerun AP agree within `1e-12`.
- S4 training is accepted only when the candidate-verification receipt passes, the resolved configuration has the exact single scientific difference, the three history/diagnostic records end at steps 400/800/1200, and full validation/test arrays pass the same official ten-segment schema checks.
- S4 posthoc is accepted only when it binds back to the audited S4 checkpoint and NPZ hashes, strict state loading has no missing or unexpected keys, all four content modes are present, and training, saved-NPZ and checkpoint-rerun AP agree within `1e-12`.
- S7 training is accepted only when the exact candidate/config/worker identities pass, all three atomic diagnostic checkpoints contain the same strict state/config/global-step payload as `last.pt`, all required T=10 outputs are complete, and the bypassed temporal tensors stay byte-identical while the active segment head changes.
- S7 posthoc is accepted only when all three checkpoint hashes are bound to the PASS training audit, every checkpoint has original/visual-zero/audio-zero/both-zero inference, 100 independent within-sample shuffles, finite path scales and exactly 5,820 samples/58,200 ordered segments. A separate auditor recomputes every delta, compression factor and causal Boolean instead of trusting the producer's summary.
- Checkpoints, NPZ files, datasets, caches, archives, bundles and progress logs remain on the 5090. Git receives only source, configuration and small review evidence.

## Verification evidence

The exact clean A0 runtime commit was installed in `E:\OV-OrthKD-R3\student-shortcut-f739399` with the nine locked resource junctions. Fresh verification returned:

- compileall: exit 0;
- full pytest: exit 0, `457 passed in 331.58s`;
- pytest log SHA256: `dd5d2df9e9c77b95e7f6eaf4c76fcdb4b84bfce1cda2a2c47ed41a787fa2447f`;
- HEAD before/after: exact `f739399463c082cd670dff56e43c710d4fa6f283`;
- dirty status before/after: empty.

The scalar-buffer fix was then installed independently in `E:\OV-OrthKD-R3\student-shortcut-a0aa4d7`. Focused verification returned `6 passed in 3.17s`; full verification returned compileall exit 0 and `458 passed in 336.08s`, with pytest log SHA256 `7e28a001986a4fe5bf20861c212eb1ff8e1b4c858603f9313a276e4b70a5bdc9`. HEAD before/after was exact `a0aa4d7ad4b98455e26a2fe6ff2537a321293233` and both dirty counts were zero.

Official cache evidence is locked by receipt SHA256 `edecae3ae9ba5fbc7102883d1c1d667df71810facb2731d2ec34503a81bca255`. The visual file is 114,604,362 bytes with SHA256 `853d431aa9363f1b058e3c343d4bf2fca5fe2a4196621c381ddbcd4828290a96`; the audio file is 40,795,861 bytes with SHA256 `847de54eb133fad3ab1230ff637ed242aefe9fd2da197d041e6753d9ec5a80bd`.

The exact S3 worker completed with exit 0 at global step 1200. Its independent training artifact audit also exited 0 and produced PASS receipt SHA256 `5058f78a8a9dfef354158d956205987550e0a745b3fe3f8f3cb79d8de7edbf71`. In addition to the output/config/prediction checks above, this audit re-hashed both official timm files at audit time. The audited best-checkpoint test AP/AUROC/F1@0.5 is `0.7456886647/0.6523319338/0.5403934128`; the saved test prediction contains 5,820 samples and 58,200 ordered task segments.

An independent pre-launch review found that posthoc model reconstruction did not yet force the training-time timm cache. The worker was changed before modality inference to set `TIMM_USE_OLD_CACHE=1`, bind the exact `TORCH_HOME`, compare the cache receipt embedded in the training audit against fixed role/path/size/SHA expectations, and re-hash both files immediately before model construction. Static RED/GREEN binding checks, local and remote PowerShell parsing, exact uploaded SHA checks, Python compile and the posthoc preflight all passed.

The first posthoc launch then failed closed before model inference because the wrapper passed obsolete prediction CLI names. Its state and stderr were retained. Source inspection confirmed that the current parser requires `--validation` and `--test`; those two names alone were corrected, parser/SHA/preflight checks were repeated, and explicit resume preserved the failed launch history. Prediction-only diagnostics then passed and modality inference began. This runner-only correction does not change model, predictions, labels or metrics.

The resumed posthoc worker completed with exit 0 and empty stderr. Its independent audit also exited 0 and produced PASS receipt SHA256 `6dc432dfccf142ed80902328755402cd140170894be3a44c7130b8b93b69ee44`. The receipt binds the result to the audited best checkpoint and prediction NPZ identities and re-establishes training AP, saved-NPZ AP and strict checkpoint-rerun AP agreement within `1e-12`.

The posthoc result does not support Student-only recovery. Test AP is `0.7456886647`, while 100 within-sample temporal shuffles average `0.7420317690`; removing visual content changes AP by only `+0.0000001263`, removing audio content lowers it by `0.0093849558`, and removing both modalities still leaves `0.7361561796` (98.72% of the original AP). All four content modes predict every segment positive at threshold 0.5. The best checkpoint has 22.23 times the S0 within-sample logit standard deviation, but visual projected-token temporal standard deviation is only `3.09e-5`; zeroing audio collapses logit temporal standard deviation to `1.60e-6`. These facts establish an audio-dominated transient variation together with a large query/sample/position shortcut, not healthy audiovisual temporal localization.

The exact clean S4 candidate was independently verified in `E:\OV-OrthKD-R3\student-shortcut-s4-74d211d`: focused tests returned `5 passed`, compileall exit 0, and the full suite returned `461 passed in 335.90s`. The verification receipt SHA256 is `f5cba2ea8d7504717ca3bdf458eb633c178ba34f956f5162d5759f284665fcf3`. The three-epoch worker then completed at step 1200 with exit 0. Its training audit passed with SHA256 `6f28df765bd436cf38db8fe0a38a239ce3d967518a934d214ebeee5416faa962`; its separate posthoc audit passed with SHA256 `1a9751cbafe3f8504105063150f33cc09214abafb7768e88a1ba4f5c765dfe80`.

S4 test AP/AUROC/F1@0.5 is `0.7034703980/0.5960085404/0.5403934128`, a change of `-0.0452742844/-0.0401261259/0` from S0. Query+position prior AP (`0.7193241998`) exceeds the student; mean-centered AP is `0.5810092411`; 100 temporal shuffles increase rather than reduce mean AP to `0.7046448804`. Visual-zero AP is effectively unchanged (`0.7032248832`), while audio-zero and both-zero AP rise to `0.7504406649/0.7494988965`. The original test logit temporal standard deviation is only `2.48e-5`; the visual/audio token temporal standard deviations of `0.058241/0.579760` are compressed to shared/decision values `0.000874/0.000106`. These independently audited facts reject augmentation removal as a recovery and show a stronger content-independent collapse.

## S7 implementation and execution review

Focused model/config/checkpoint tests were written against the absent behavior before implementation, then passed after the bounded changes. A structural re-review found that the first checkpoint-helper insertion had accidentally split `main()` and made the remaining training body unreachable; Ruff exposed the unreachable layout, the helper was moved above `main()`, and the combined focused suite returned `16 passed in 8.18s`. No experiment was launched from the defective intermediate tree.

The exact clean candidate was installed in `E:\OV-OrthKD-R3\student-shortcut-s7-a7f0dc0` with the nine validated resource junctions. Verification returned compileall exit 0 and `477 passed in 354.75s`, pytest exit 0, stdout SHA256 `d12c0906fe4463d2c9ad3e0548927471e35bb140dcf87862481fc1a613041a7f`, and verification-receipt SHA256 `ce10e08506e7382bedfc16442c4d46f30834b2f20b0b90d54148100193ae7cf9`. HEAD remained exact and dirty status remained empty.

The persistent training worker completed with exit 0 at step 1200. Its artifact audit passed with SHA256 `6583c7f403041be961bba5a40dd7f7e4c8f8d38fd1fee2c7548396b5b6e30dc2`. It binds the sole config change, every small output, the three 500,254,643-byte diagnostic checkpoint hashes, the best/last strict state hash, and the fact that all 48 bypassed temporal-encoder tensors remained unchanged while the active segment head changed.

The posthoc launcher was independently reviewed before use. Its initial launch-time health check accepted only the `training_audit` phase; because that audit can finish inside the ten-second window, a healthy worker could already be in `checkpoint_trajectory` and be rejected. The accepted phase set was widened to `training_audit`, `checkpoint_trajectory`, or `completed`, then its parser, exact hash and preflight were rerun before launch. The successful worker completed both phases with exit 0.

The trajectory producer evaluated steps 400, 800 and 1200 over the full test set in four content modes and performed 100 seed-42 within-sample shuffles at each step. The independent auditor had five focused tamper tests, including altered deltas, altered decisions, T=16 rejection and overwrite refusal; local and remote runs both returned `5 passed`. The final independent audit exited 0 and produced PASS SHA256 `1207c255ccbd918cb5c2899f7da929170c8020f63becd7548e29c473f9671956`, binding the trajectory SHA256 `74fd36bafd08d0d30e0e165c886e02b84fa94ac092b359399714d71e360be992`.

The S7 causal claim was rejected exactly as pre-registered. At steps 400/800, shuffle AP drops are only `0.005508/0.010488` against the required `0.02`; both-zero AP drops are only `0.010096/0.003133` against `0.03`. Positive-minus-negative logits, logit temporal variation and compression checks pass, but all five conditions had to pass at both checkpoints. At best step 1200, AP/AUROC improve to `0.7586053689/0.6691730030`, while F1@0.5 falls to `0.5302860299`. Visual-zero AP is unchanged to eight decimal places; audio-zero and both-zero AP are `0.7335981850/0.7334019023`. This is modest ranking recovery dominated by audio, not restored audiovisual temporal localization and not evidence to start formal Full training.

All active PowerShell workers, launchers, resumptions, queries, preflights and artifact-audit wrappers were parsed locally and on the 5090 with zero parser errors. The Python artifact auditors passed compilation checks; their exact uploaded hashes were bound into the remote wrappers. The locked 5090 environment does not include Ruff, so Ruff was run locally against those exact hashes and recorded separately rather than claimed as a remote result.

The final evidence commit additionally hardens `.gitignore` for common checkpoint, array and archive formats. This is a publication-safety change only and is outside the scientific runtime commit.

## A–F zero/near-zero-training audit review

The exact clean implementation commit `c181ffb3297ff480a0d01186c626acce7c66afff` passed project-boundary compileall and the complete 5090 suite (`526 passed in 346.28s`). The runtime-control commit is `9786eb4da95a99d123078674508dbe340170cef8`; its launcher binds the implementation, prepare/verification/preflight receipts, nine resource junctions, locked Python/Git/GPU identity, S7 audit/trajectory/config/checkpoint hashes and canonical Full config/checkpoint hashes. It launches only `ae→f→audit`, with `starts_training=false` and `starts_s8=false`.

The persistent worker completed all three phases with exit 0 and empty stderr. A–E audited every official test JPG, reconstructed step zero from the stored before-update receipt, evaluated visual variation/fusion/Jacobians at steps 0/400/800/1200 and generated 17 best-checkpoint interventions. F performed mean/sum gradient scaling and one AdamW step only on disposable in-memory clones. The independent auditor recomputed the NPZ metrics, verified ten source receipts and emitted PASS without making a scientific-success claim.

The evidence localizes the visual collapse before or inside the trained visual backbone by step 400, not in corrupt input files or unequal concat-fusion column norms. Dynamic visual Jacobians become 82–284 times smaller than audio at the early checkpoints, and inference-time fixed gates cannot restore visual-zero sensitivity. Audio donor/shuffle results show genuine audio temporal ordering plus a large surviving sample/query/class prior. The canonical Full probe separately shows exact 256× attenuation caused by feature-mean reduction while proving that a correctly scaled disposable projector/decision clone updates normally. These findings clear the preregistered integrity blockers for only S8 identity + fixed-equal-gate from initialization; they do not authorize formal Full training or a canonical loss edit.

## S8 implementation, execution and recovery review

Config TDD first established that the S8 YAML differs from S7 only at `student.gate_mode`, changing `learned_softmax` to `fixed_equal`. The model implementation keeps the default learned gate fail-closed for every canonical configuration and returns literal `0.5/0.5` only when the explicit diagnostic mode is selected. The temporal Transformer remains constructed but bypassed exactly as in S7. The exact detached scientific candidate passed project-boundary compileall and the complete 5090 suite (`536 passed in 346.15s`) with HEAD `60100c6fff95b313ae92bc91b10a3be7135dc437` and empty status before and after.

The persistent worker completed training, the independent training artifact audit and the full A–E diagnostic. The training audit is PASS at SHA256 `7aa1108a8f536f720735edec5183d9846d52e8b28ce7236db2f5121354bc6a11`; it proves exact `T=10`, the sole S7→S8 change, three 400-batch epochs, immutable bypassed temporal/gate tensors and changing active head state. The A–E report is PASS at SHA256 `54baa6c27b286226bce5698ef0a3e56456aadf739c577915d5a57c82af55ca7d`, bound to a remote-only 17-mode NPZ at SHA256 `5a28ce8cc58674f89aa4388b9e205410877a954491051b93c9db9e839c2bec68`.

The original post-hoc reader failed closed after A–E because it indexed the actual nested `fusion_input_blocks.blocks.visual/audio/query` schema as if the modality keys were direct children. A real-schema fixture reproduced the failure against the old reader (`1 failed, 2 passed`), and the minimal repair changed only that access. The repaired tests returned `3 passed`; an isolated cross-suite returned `107 passed`; and an independently prepared clean audit candidate at `6f39172120ab877c246d3fd6fbd1a4699a6f2871` passed compileall plus the full suite (`536 passed in 347.58s`). The original failed worker state was preserved. A SHA-locked recovery control then ran only the missing reader, not training or A–E, and refused any duplicate output.

The recovered post-hoc artifact is PASS at SHA256 `7784887d05199ae4d70a81c29d497d4a9cd6c689a0746d56aa459b83df4e0d5b`. It independently verifies eight source receipts, 17 modes, 5,820 samples, 58,200 ordered T=10 segments and metric digest `08334096358cb5c6a9cf59e1e4deb22662abc727201ea26ab9eea72db174bfaf`; stderr is empty. The scientific conclusion is evidence pattern 2: visual backbone/projected variation and visual gradients recover, but mixed visual-zero AP drop is only `0.0006317742` while audio-zero and both-zero drops are `0.0309577768/0.0311512139`. The remaining failure lies in converting visual representations into useful final ranking behavior, not in the input frame corpus, fixed gate, or visual backbone collapse. Because no numeric S8 success threshold was preregistered, the audit makes no automatic success claim and authorizes neither S9 nor formal Full.

## S9 paper-additive implementation and execution review

S9 was implemented as a bounded configuration/audit change, not a new model structure. TDD first locked the S8→S9 YAML diff to the single field `student.fusion_mode`, and the mechanical tests verify the exact additive equation, equal fixed gate, identity temporal path, T=10, unchanged parameter count (`46,278,129`), unchanged state-dict keys and bitwise-equal S8/S9 initialization. `token_fusion` remains constructed for state/RNG compatibility but has no gradient and no state change in the additive branch. The core `OVOrthKDStudent` source was not structurally altered.

The exact detached candidate at `b8ea747dd792c939251152ead734d1826c26980d` passed compileall and the complete 5090 suite (`555 passed in 372.02s`, exit 0). The persistent runtime commit is `31497d58eb5d17e60cbebc6afa1bef5bcecb37a7`; its only scientific phase sequence is `s9_training→training_audit→s9_ae→posthoc_audit`, with Full, canonical-loss and next-experiment flags false. The worker completed all four phases with exit code 0 and empty stderr. Training artifact audit is PASS (SHA256 `a0a1b35fae2a5c5cf352e406b57e8f2d7cdd7828fe837f19f0230f7b03f0a7c4`) and confirms the fixed inactive modules remain immutable while the active segment head changes at steps 400/800/1200.

The full A–E producer is PASS (SHA256 `54391fa046dd7ec2900bc613aabcb6f1200fa59e8d18b3a2b0d8da2ac6dae264`) over 17 modes, 5,820 samples and 58,200 T=10 segments with 100 fixed-seed shuffles. The formal posthoc artifact audit is PASS (SHA256 `a9a3040738f5a1b2e003838c36960e10b0dbae77a88e3d1a3170d75aa4f7a740`), and a second read-only posthoc invocation on the same remote NPZ produced byte-identical output and the same scientific classification. The remote prediction archive is intentionally not published.

The pre-registered scientific classifier returns FAIL, not because of artifact corruption but because additive fusion does not recover visual label-aligned behavior: mixed visual-zero changes are `ΔAP=-0.0000082206`, `ΔAUROC=-0.0000044761`, `ΔC=+0.0000561892`; two effects are non-positive and all three are below the weak-effect fail thresholds. Mixed AP (`0.657439`) and original temporal-shuffle AP drop (`0.035437`) remain measurable, while mixed concordance (`0.636175`) is below the protection gate. Forced visual concordance (`0.550823`) and forced-visual shuffle AP drop (`0.001726`) are also weak supporting signals. The bounded result rejects this additive readout as a sufficient recovery under S8 conditions; it does not identify one downstream layer as the unique root cause.

S9 therefore leaves `next_experiment_authorized=false` and `formal_full_training_authorized=false`. No Visual-only, second seed, extended schedule, canonical loss edit or formal Full run was started. Any future intervention requires a new human-approved design, explicit thresholds and a fresh clean candidate.
