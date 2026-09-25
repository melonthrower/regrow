# Operation Parameter Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every new Operation explicitly confirm `unknown|none|observed` parameters and block v5 completion while a logical Operation remains parameter-unknown.

**Architecture:** Persist parameter confirmation on Variant-local Operations, keep the existing `explore_operation` task as the only executable work item, and bind after-action parameter reports through the completed owner instead of a model-supplied Operation ID. Aggregate confirmation only at completion/bundle projection so canonical reuse stays evidence-preserving.

**Tech Stack:** Python dataclasses, strict JSON parsing/schema, pytest, existing modular exploration ledger and compiler.

**Spec:** `design/modules/explore_kernel/operation_parameter_confirmation_design.md`

## Global Constraints

- Do not add a Parameter object, ParameterTask type, application-specific rule, or per-value Operation.
- Direct screenshot confirmation of `none` or `observed` must not execute a GUI action.
- `unknown + explore` must reuse the existing Operation action and one pending ActionAttempt; `unknown + record` remains non-executable and produces a parameter gap.
- Old v3/v4 evidence remains read-only and is not retroactively certified for parameter coverage.
- Keep saved-frame, offline, supervised live, and unsupervised live evidence separate.

---

### Task 1: Persist and parse parameter confirmation

**Files:**
- Modify: `gui_rewalk/src/core/explore/models.py`
- Modify: `gui_rewalk/src/core/explore/ledger.py`
- Modify: `gui_rewalk/src/core/explore/contracts.py`
- Modify: `gui_rewalk/src/core/explore/prompts.py`
- Test: `tests/test_explore_kernel.py`

**Interfaces:**
- Produces: `Operation.parameter_status`, `parameter_summary`, `parameter_evidence_refs`.
- Produces: `ParameterInfoUpdate(status, summary)` on `PreviousActionReport.parameter_info`.

- [ ] Write parser/schema tests requiring parameter fields on every new Operation and validating `previous_action.parameter_info`.
- [ ] Run the focused parser tests and confirm failure because the fields do not exist.
- [ ] Add the dataclass fields, v5 ledger schema with v3/v4 legacy load preservation, parser validation, and static JSON schema.
- [ ] Update the fixed Prompt to distinguish direct confirmation, hidden-domain `unknown`, and non-Operation option values.
- [ ] Run the focused parser/schema tests and confirm pass.

### Task 2: Enforce inventory, settlement, and completion

**Files:**
- Modify: `gui_rewalk/src/core/explore/inventory.py`
- Modify: `gui_rewalk/src/core/explore/settlement.py`
- Modify: `gui_rewalk/src/core/explore/tasks.py`
- Modify: `gui_rewalk/src/core/explore/status.py`
- Test: `tests/test_explore_kernel.py`

**Interfaces:**
- Consumes: Operation parameter fields and `PreviousActionReport.parameter_info` from Task 1.
- Produces: explicit explore-only parameter probing, non-executable recorded gaps, framework-attached screenshot evidence, owner-bound after-action confirmation, and `parameter_unknown` logical gaps.

- [ ] Write failing tests for direct `none/observed`, safe `unknown + explore` task creation, non-executable `unknown + record` gaps, missing after-action confirmation rejection, successful owner-bound update, conflict rejection, and canonical logical gap closure.
- [ ] Run those tests and confirm each fails for the missing behavior.
- [ ] Make inventory preserve handling so only `unknown + explore` is pending while `unknown + record` remains non-executable; attach the current State screenshot to accepted direct confirmations.
- [ ] Make settlement validate and apply parameter info before marking the completed Operation verified.
- [ ] Project parameter requirements in the status bar/current page/pending action card and add v5-only canonical parameter gaps.
- [ ] Run the focused lifecycle tests and confirm pass.

### Task 3: Preserve parameter context in formal projection

**Files:**
- Modify: `gui_rewalk/src/core/explore/bundle.py`
- Test: `tests/test_explore_kernel.py`

**Interfaces:**
- Consumes: local Operation parameter confirmation evidence.
- Produces: canonical entry fields `parameter_status`, `parameter_summaries`, and `parameter_evidence_refs` without changing capability parameterization.

- [ ] Write failing bundle tests showing a canonical entry aggregates one observed binding, retains its evidence refs, and exposes conflicting none/observed bindings.
- [ ] Run it and confirm the projection fields are absent.
- [ ] Add deterministic aggregation and `parameter_conflict` to `_entry_snapshot`; keep `_effect_observation.parameter_bindings` unchanged.
- [ ] Run bundle and adjacent capability compilation tests.

### Task 4: Document and verify the shared contract

**Files:**
- Modify: `design/CURRENT_FRAMEWORK.md`
- Modify: `design/RESEARCH_GOAL.md`
- Modify: `design/modules/explore_kernel_design.md`
- Modify: `design/modules/explore_kernel/page_inventory.md`
- Modify: `design/modules/explore_kernel/operation_tasks.md`
- Modify: `design/modules/explore_kernel/agent_context.md`
- Modify: `design/modules/explore_kernel/runtime_and_artifacts.md`
- Modify: `design/changelog/2026-08.md`

**Interfaces:**
- Produces: current-state documentation and exact verification evidence.

- [ ] Update current docs only for implemented behavior and keep Luna-only acceptance unchecked until the live run succeeds without teacher correction.
- [ ] Run `python -m pytest -q --tb=short -p no:cacheprovider --basetemp .test-tmp/parameter tests/test_explore_kernel.py`.
- [ ] Run adjacent completion/bundle tests and `python -m py_compile` on every changed Python file.
- [ ] Inspect the exact staged path list and `git diff --cached --check`, then commit only task-owned files.

### Task 5: Run a fresh supervised Android Clock pilot

**Files:**
- No source changes during the run.
- Write remote evidence under a new task-owned run root and local evidence under ignored `artifacts/`.

**Interfaces:**
- Consumes: committed v5 framework and persistent Luna API configuration.
- Produces: separate live completion, ledger, screenshots, debug/cost audit, parameter coverage audit, and cleanup evidence.

- [ ] Deploy the exact commit archive to the isolated server project and verify its SHA-256.
- [ ] Allocate a new AVD/serial/ports without touching existing emulators, verify the exact Clock package/launcher, and capture a fresh preflight screenshot.
- [ ] Run the fixed Prompt with Luna API and a bounded larger action budget; Codex monitors but does not inject actions or edit the run.
- [ ] Verify completion/bundle/digest, audit every logical Operation parameter status, compare actions/calls/tokens/cache/gaps with the previous 118-action run, and classify remaining errors.
- [ ] Stop only the run-owned emulator/viewer processes and delete only the run-owned temporary AVD; preserve evidence.
