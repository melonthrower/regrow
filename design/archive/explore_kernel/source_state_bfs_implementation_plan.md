# Source-State BFS Exploration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement source-State-first BFS scheduling and exact action receipts without adding a persistent graph or model-authored Operation IDs.

**Architecture:** `TaskScheduler` derives an ancestor frontier from existing verified Transitions and prioritizes the oldest task on that frontier after current-State survey. `status.py` and `runtime.py` project exact focus/actual Operation refs to Luna. Runtime rejects a second successful non-focus Operation within one focus.

**Tech Stack:** Python dataclasses, deterministic ledger queries, pytest, existing modular Luna runtime.

**Spec:** `design/modules/explore_kernel/source_state_bfs_design.md`

## Global Constraints

- Preserve the single `ExplorationLedger`; no new persistent schema.
- Luna submits `owner_ref`; framework remains the only Operation binder.
- Preserve user-owned `live_state_locator.py` and its test.
- Run only focused tests and syntax checks before live Clock validation.

---

### Task 1: Source-State BFS Scheduler

**Files:**
- Modify: `gui_rewalk/src/core/explore/tasks.py`
- Test: `tests/test_explore_kernel.py`

**Interfaces:**
- Consumes: `Task.state_id`, `Task.created_seq`, `ExplorationLedger.transitions`.
- Produces: `ancestor_state_distances(ledger, current_state_id) -> Dict[str, int]` and a BFS-first scheduling key.

- [x] **Step 1: Change the existing directed-reachability test into a RED ancestor-frontier test**

```python
chosen = TaskScheduler().choose(ledger)
assert chosen.task_id == "t-unreachable"  # s1 is an ancestor of current s3
```

- [x] **Step 2: Add a RED unrelated-state fallback test**

```python
assert "detached" not in ancestor_state_distances(ledger, "s3")
assert TaskScheduler().choose(ledger).task_id == "t-reachable"
```

- [x] **Step 3: Run the two tests and verify the ancestor case fails for the old distance-first Scheduler**

Run: `python -m pytest -q --tb=short -p no:cacheprovider tests/test_explore_kernel.py -k "ancestor_frontier or unrelated_unreachable"`

- [x] **Step 4: Implement reverse Transition traversal and prefer `created_seq` within the ancestor frontier**

```python
def ancestor_state_distances(ledger, current_state_id):
    reverse = {}
    for transition in ledger.transitions:
        reverse.setdefault(transition.target_state_id, []).append(
            transition.source_state_id)
    distances = {current_state_id: 0} if current_state_id else {}
    queue = deque([current_state_id] if current_state_id else [])
    while queue:
        current = queue.popleft()
        for source in reverse.get(current, []):
            if source in distances:
                continue
            distances[source] = distances[current] + 1
            queue.append(source)
    return distances
```

- [x] **Step 5: Run Scheduler-adjacent tests**

Run: `python -m pytest -q --tb=short -p no:cacheprovider tests/test_explore_kernel.py -k "scheduler or directed_state_distance or current_binding"`

### Task 2: Exact Local Preconditions and Recovery Topology

**Files:**
- Modify: `gui_rewalk/src/core/explore/runtime.py`
- Test: `tests/test_explore_kernel.py`

**Interfaces:**
- Produces exact task-card fields from existing Operation/Occurrence/Task refs.
- Preserves Add/Save execution; missing bindings become Region/State recovery goals, not ordering blocks.

- [x] **Step 1: Add RED assertions for `required_region_ref`, `required_variant_ref`, `required_occurrence_refs` and `source_state_refs`**
- [x] **Step 2: Project these refs in `_task_view()` without adding persisted fields**
- [x] **Step 3: Verify the existing away-from-source instruction requires Region/State recovery and still permits current visible recovery Operations**
- [x] **Step 4: Run task-card, route, recovery and context tests**

### Task 3: Exact Task Card and Action Receipts

**Files:**
- Modify: `gui_rewalk/src/core/explore/status.py`
- Modify: `gui_rewalk/src/core/explore/runtime.py`
- Test: `tests/test_explore_kernel.py`

**Interfaces:**
- Consumes: Task, Operation, Region, Element, Attempt and current Page/State.
- Produces: `_task_view()` exact refs and `recent_actions()` Attempt receipts.

- [x] **Step 1: Add a RED context test**

```python
card = runtime._context(task, "target")["当前任务精确卡"]
assert card["operation_ref"] == "o68"
assert card["region_ref"] == "r24"
assert card["element_ref"] == "el75"
```

- [x] **Step 2: Add a RED action-receipt test for focus o68 / actual o91**

```python
receipt = context["当前焦点动作回执"][-1]
assert receipt["focus_operation_ref"] == "o68"
assert receipt["actual_operation_ref"] == "o91"
assert receipt["completed_focus"] is False
```

- [x] **Step 3: Project the existing `_task_view(task)` into `_context()` and derive receipts from Attempts**

- [x] **Step 4: Run context/status tests**

Run: `python -m pytest -q --tb=short -p no:cacheprovider tests/test_explore_kernel.py -k "task_view or exact_task_card or action_receipt or context"`

### Task 4: Reject Repeated Successful Non-Focus Operations

**Files:**
- Modify: `gui_rewalk/src/core/explore/runtime.py`
- Test: `tests/test_explore_kernel.py`

**Interfaces:**
- Consumes: bound current action, active focus Task, prior Attempts under that Task.
- Produces: deterministic validation error naming focus and actual Operation refs plus exact source State.

- [x] **Step 1: Add a RED test with one successful o91 Attempt under focus o68**

```python
issue = runtime._validate_action(focus_task, second_o91_action)
assert "o91 已在当前焦点中成功执行" in issue
assert "返回来源 State s13" in issue
```

- [x] **Step 2: Verify old near-point-only logic allows the changed-point repeat**

Run: `python -m pytest -q --tb=short -p no:cacheprovider tests/test_explore_kernel.py::test_successful_nonfocus_operation_cannot_repeat_within_focus`

- [x] **Step 3: Implement the successful non-focus Operation guard before the near-point guard**

- [x] **Step 4: Verify focus Operation retries and no-effect re-grounding remain allowed**

Run: `python -m pytest -q --tb=short -p no:cacheprovider tests/test_explore_kernel.py -k "nonfocus or repeated_detour or no_effect"`

### Task 5: Documentation, Checkpoint and Live Clock

**Files:**
- Modify: `design/modules/explore_kernel/operation_tasks.md`
- Modify: `design/modules/explore_kernel/agent_context.md`
- Modify: `design/CURRENT_FRAMEWORK.md`
- Modify: `design/changelog/2026-09.md`

- [x] **Step 1: Update current-state docs and record exact focused verification**
- [x] **Step 2: Run focused regression, `py_compile`, and `git diff --check`**
- [ ] **Step 3: Stage exact task-owned paths and create a local commit**
- [ ] **Step 4: Deploy committed HEAD to a new isolated js1 run root**
- [ ] **Step 5: Run desktop Clock with Luna API and audit Alarm coverage, duplicate actual Operations per focus, Region reveal edges, gaps, bundle, quality, cost, and cleanup**
- [ ] **Step 6: For a simple general failure, reproduce with a focused test, patch, recommit, and rerun from a fresh environment; otherwise preserve the partial evidence and report the blocker**
