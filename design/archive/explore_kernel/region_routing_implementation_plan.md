# Region Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compile evidence-backed Region visibility relations and use them to route from current visible RegionVariants to a target Region without making Page the routing node.

**Architecture:** `Transition` remains the only persisted action edge and adds hidden Region refs beside existing revealed refs. A small `region_routes.py` module derives Page membership, relations, and context-sensitive BFS plans. Runtime records effects after settled inventories and projects plans into the exact task card; bundle writes a derived Region route artifact.

**Tech Stack:** Python dataclasses, deterministic ledger queries, pytest, existing modular Luna runtime.

**Spec:** `design/modules/explore_kernel/region_routing_design.md`

## Global Constraints

- Preserve one `ExplorationLedger`; no second persistent Region graph or new Region/Operation IDs.
- Match route effects by source Region, source Variant, and CanonicalOperation.
- Page is a Region group, while State occurrence remains the executable visibility truth.
- Preserve user-owned `live_state_locator.py` and its test.
- Run focused Tier 3 tests; do not run the full release gate.

---

### Task 1: Persist Region Visibility Effects

**Files:**
- Modify: `gui_rewalk/src/core/explore/models.py`
- Modify: `gui_rewalk/src/core/explore/regions.py`
- Create: `gui_rewalk/src/core/explore/region_routes.py`
- Modify: `gui_rewalk/src/core/explore/runtime.py`
- Test: `tests/test_explore_kernel.py`

**Interfaces:**
- Produces `Transition.hidden_region_ids`.
- Produces `refresh_transition_region_effects(ledger, transition)`.

- [x] Add RED tests proving a settled, fully inventoried source/target pair records target-minus-source as revealed and source-minus-target as hidden.
- [x] Add a RED save/load and Region merge test for both Region ref lists.
- [x] Implement effect refresh only for accepted States with completed inventories.
- [x] Invoke it immediately for known target States and after new target Region identity is finalized.
- [x] Run Transition, Region identity, merge, and ledger persistence tests.

### Task 2: Compile Context-Sensitive Region Routes

**Files:**
- Modify: `gui_rewalk/src/core/explore/region_routes.py`
- Test: `tests/test_explore_kernel.py`

**Interfaces:**
- Produces `page_region_refs(ledger, page_id)`.
- Produces `region_relations(ledger)`.
- Produces `plan_region_route(ledger, current_state_id, target_region_id)`.

- [x] Add RED fixtures where one shared navigation Region has World, Alarms, and Timer Variants with different Add CanonicalOperations and effects.
- [x] Prove the exact current Variant selects only its own Add relation.
- [x] Prove a new Variant may reuse a stable canonical effect through its current local binding.
- [x] Prove conflicting effect signatures return no route for an unseen Variant.
- [x] Implement deterministic shortest Region route planning and Page membership union.
- [x] Run Region route planner tests.

### Task 3: Feed Region Routes to Luna

**Files:**
- Modify: `gui_rewalk/src/core/explore/runtime.py`
- Modify: `design/modules/explore_kernel/agent_context.md`
- Test: `tests/test_explore_kernel.py`

**Interfaces:**
- Extends exact task cards with `required_region_ref` and `region_route`.
- Keeps existing State connections as landing evidence, not the semantic route target.

- [x] Add a RED context test for an away-from-source task whose target Region has a two-hop Region route.
- [x] Project compact route steps with current local `operation_ref/owner_ref`, expected revealed/hidden Regions, and evidence.
- [x] Update the instruction so Luna executes only the current fresh-frame owner and replans if the expected Region is absent.
- [x] Verify current local binding, modal foreground, State route, and action receipt tests remain green.

### Task 4: Compile Page Groups and Region Route Artifact

**Files:**
- Modify: `gui_rewalk/src/core/explore/bundle.py`
- Test: `tests/test_explore_kernel.py`

**Interfaces:**
- Produces `modular_region_routes.json`.
- Extends `compile_modular_bundle()` result with `region_routes_path`.

- [x] Add a RED bundle test for Page Region union, Variant-conditioned relations, reveal/hide refs, and evidence refs.
- [x] Write the deterministic artifact without changing annotated graph or capability schemas.
- [x] Run bundle, capability induction, and graph load focused tests.

### Task 5: Current-State Documentation and Verification

**Files:**
- Modify: `design/RESEARCH_GOAL.md`
- Modify: `design/CURRENT_FRAMEWORK.md`
- Modify: `design/modules/explore_kernel/action_transition.md`
- Modify: `design/modules/explore_kernel/operation_tasks.md`
- Modify: `design/modules/explore_kernel/runtime_and_artifacts.md`
- Modify: `design/modules/explore_kernel_design.md`
- Modify: `design/changelog/2026-09.md`

- [x] Update the current method chain from State-target routing to Region-target/State-occurrence execution.
- [x] Record that Page is a Region grouping projection and context-sensitive Add effects remain Variant-conditioned.
- [x] Run `tests/test_explore_kernel.py`, directly affected bundle/Region tests, `py_compile`, and `git diff --check`.
- [x] Stage exact task-owned paths, inspect the staged diff, and commit locally.
- [x] Validate the saved Clock ledger produces distinct World/Alarm/Timer Add relations and a Region route artifact; report this as offline saved-run evidence, not fresh live acceptance.
