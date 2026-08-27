# Causal Fusion Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make declared fusion/distillation modes control real runtime behavior and execute S0/S1/S2 single-variable Student-only diagnostics.

**Architecture:** Preserve the published reconstruction as explicit compatibility modes, add paper-additive/fixed-gate and distillation stability modes behind strict validated configuration, and receipt actual constructed behavior before fingerprinting. Diagnostic configs derive mechanically from one S0 base so the two causal variants differ by exactly one scientific field.

**Tech Stack:** Python 3.11, PyTorch 2.10, timm, PyYAML, pytest, PowerShell, RTX 5090.

**Spec:** `docs/superpowers/specs/2026-08-27-causal-fusion-diagnostics-design.md`

## Global Constraints

- Preserve official `T_task=10`; do not add temporal interpolation or T=16 labels/logits.
- Do not claim any diagnostic mode is the archival meeting implementation.
- Do not combine gate, fusion, pretraining, augmentation, exposure or projector changes in one run.
- Do not upload datasets, caches, checkpoints, NPZ files, ZIP files or progress logs.
- Write production changes only after the corresponding focused test fails for the intended missing behavior.
- Record every action and result in both activity ledgers.

---

### Task 1: Student fusion and gate modes

**Files:**
- Modify: `tests/test_paper_faithfulness.py`
- Modify: `src/models/ov_orthkd.py`

**Interfaces:**
- Consumes: `fusion_mode: str`, `gate_mode: str`, modality tokens and validity masks.
- Produces: `OVOrthKDStudent.fusion_mode`, `.gate_mode`, exact gate weights and fused tokens.

- [ ] **Step 1: Write failing behavior tests**

Add tests that replace encoders/projections/temporal encoder with deterministic identity modules, set literal visual/audio/text tensors, and assert:

```python
assert torch.equal(additive_outputs["fused_tokens_before_position"], 0.25 * visual + 0.75 * audio + text)
assert torch.equal(fixed_outputs["gate_weights"], torch.tensor([[[0.5, 0.5], [1.0, 0.0]]]))
```

Also assert invalid fusion/gate names raise `ValueError`.

- [ ] **Step 2: Verify RED**

Run on the locked 5090 environment:

```text
python -m pytest tests/test_paper_faithfulness.py -k "fusion or gate" -q
```

Expected: failure because constructor arguments and additive/fixed behavior do not exist.

- [ ] **Step 3: Implement minimal model modes**

Add validated constructor fields. Learned mode retains the current MLP/masking. Fixed mode derives weights only from validity. Concat mode calls `token_fusion(torch.cat(...))`; additive mode returns `weighted_visual + weighted_audio + text_token`. Expose `fused_tokens_before_position` only as a real forward result used by diagnostics/tests.

- [ ] **Step 4: Verify GREEN and mutation coverage**

Run the same focused test. Confirm changing additive `+` to concatenation or fixed 0.5 to 1.0 would fail a literal-value assertion.

### Task 2: Loss reduction and target stability modes

**Files:**
- Modify: `tests/test_paper_faithfulness.py`
- Modify: `src/losses/ov_orthkd_loss.py`

**Interfaces:**
- Consumes: `visual_l2_reduction`, `teacher_target_projector_trainable`, `query_anchor_mode`, optional `student_text_anchor`.
- Produces: exact feature-loss scaling, explicit projector trainability and selected text target path.

- [ ] **Step 1: Write failing L2 and projector tests**

Use a literal two-feature error whose squared errors are 1 and 4:

```python
assert mean_stats["strong_feat"] == pytest.approx(2.5)
assert sum_stats["strong_feat"] == pytest.approx(5.0)
assert all(not p.requires_grad for p in frozen_loss.strong_teacher_proj.parameters())
```

Assert invalid reduction and query-anchor modes fail.

- [ ] **Step 2: Verify RED**

Run:

```text
python -m pytest tests/test_paper_faithfulness.py -k "l2_reduction or projector or query_anchor" -q
```

Expected: failure because the constructor settings are absent and reduction is hard-coded.

- [ ] **Step 3: Implement reduction and projector trainability**

Select `.mean(dim=-1)` or `.sum(dim=-1)` from the validated reduction. Set `requires_grad_(False)` on every target-projector parameter when requested.

- [ ] **Step 4: Implement shared fusion query anchor**

In shared mode, make the student query path output `fusion_dim`, expose the unexpanded fusion text token as `text_alignment_target`, omit the independent loss projector, and require the provided target shape to match `student_query_features.shape[-1]`. Compatibility mode retains the current 256-dimensional independent projector.

- [ ] **Step 5: Verify GREEN**

Run all `test_paper_faithfulness.py` tests and confirm both compatibility and new modes pass.

### Task 3: Builder, optimizer and actual-behavior receipt

**Files:**
- Modify: `tests/test_training_reproducibility.py`
- Modify: `scripts/train_ov_orthkd.py`
- Modify: `src/utils/training_diagnostics.py`

**Interfaces:**
- Consumes: the five explicit configuration settings from Tasks 1--2.
- Produces: `runtime_implementation_behavior(student, loss_module) -> dict[str, Any]`, `implementation_behavior.json`, fingerprinted resolved config and checkpoint field.

- [ ] **Step 1: Write failing plumbing tests**

Build tiny configs with non-default modes and assert actual module attributes, absent trainable frozen-projector parameters, and behavior receipt values. Assert changing YAML changes the constructed module, not only the config dictionary.

- [ ] **Step 2: Verify RED**

Run:

```text
python -m pytest tests/test_training_reproducibility.py -k "fusion or implementation_behavior or projector" -q
```

Expected: failure because builder plumbing and receipt do not exist.

- [ ] **Step 3: Plumb and receipt actual behavior**

Pass all settings in `build_model_and_loss`. Build a literal schema-1 receipt from module attributes and trainable parameter counts, attach it to `config["runtime_implementation"]` after construction, then write metadata and build the fingerprint. Add the same receipt as a top-level checkpoint field.

- [ ] **Step 4: Filter optimizer parameters**

Use:

```python
parameters = [
    parameter
    for parameter in list(student.parameters()) + list(loss_module.parameters())
    if parameter.requires_grad
]
```

Update diagnostics to ignore absent/`None` modules and to report the shared text anchor without inventing a projector.

- [ ] **Step 5: Verify GREEN**

Run the focused builder, checkpoint, resume and training-diagnostics tests.

### Task 4: Diagnostic claim and S0/S1/S2 configs

**Files:**
- Create: `configs/diagnostics/causal/ov_orthkd_s0_learned_concat_seed42.yaml`
- Create: `configs/diagnostics/causal/ov_orthkd_s1_fixed_concat_seed42.yaml`
- Create: `configs/diagnostics/causal/ov_orthkd_s2_learned_additive_seed42.yaml`
- Create: `tests/test_causal_diagnostic_configs.py`
- Modify: `scripts/train_ov_orthkd.py`

**Interfaces:**
- Consumes: verified runtime modes and the current Student-only configuration.
- Produces: three noncanonical, three-epoch, 1,200-step configurations with strict single-variable relationships.

- [ ] **Step 1: Write failing config tests**

Load all three YAMLs and normalize only `reproduction.variant` and `logging.log_dir`. Assert S1 differs from S0 only at `student.gate_mode`, S2 only at `student.fusion_mode`, and all contain:

```python
assert config["reproduction"]["claim_level"] == "noncanonical_diagnostic"
assert config["reproduction"]["diagnostic_only"] is True
assert config["training"]["epochs"] == 3
assert config["training"]["max_batches_per_epoch"] == 400
assert config["loss"]["alpha_strong_feat"] == 0.0
```

- [ ] **Step 2: Verify RED**

Run the new test and confirm missing configs/claim handling fail.

- [ ] **Step 3: Add fail-closed diagnostic claim handling and configs**

Accept `noncanonical_diagnostic` only with `diagnostic_only=true`; reject this marker for formal claim levels. Derive the three YAML files from the published Student-only config, explicitly declaring every new runtime mode.

- [ ] **Step 4: Verify GREEN**

Run the config tests plus canonical readiness/config regression tests to prove formal gates remain unchanged.

### Task 5: Independent verification and 5090 execution

**Files:**
- Create: `reports/formal_reproduction/causal_fusion_diagnostics/IMPLEMENTATION_AUDIT.md`
- Create outside Git: `扩刊/复现/causal_fusion_diagnostics/`

**Interfaces:**
- Consumes: exact committed candidate and S0/S1/S2 configs.
- Produces: verified code commit and three auditable diagnostic outputs.

- [ ] **Step 1: Independently review the diff**

Check every new setting from YAML to constructor to forward/loss to receipt/checkpoint. Scan for unused keys, default-only tests, dimension mismatches, accidental changes to T=10, formal guards, optimizer composition and canonical config bytes.

- [ ] **Step 2: Run focused and complete verification**

Run compileall, JSON/YAML parsing, `git diff --check`, focused tests and the complete `python -m pytest -q` on the exact clean 5090 commit.

- [ ] **Step 3: Launch persistent sequential controls**

Use the existing detached-worker pattern. Run S0, then S1, then S2; each must begin from a clean exact commit, use its own output directory and write worker state atomically. Do not share a running GPU with another control.

- [ ] **Step 4: Audit and compare results**

Require worker exit 0, history rows 3, final step 1,200, diagnostics rows 3, finite metrics, exact T=10 prediction shapes and implementation receipt matching the intended mode. Compare the collapse criteria in the design, not AP alone.

- [ ] **Step 5: Publish small evidence only**

Commit code, configs, tests, reports, resolved configs, histories, diagnostic JSONL and hash receipts. Keep checkpoints, predictions, caches, datasets and progress logs only on the 5090.
