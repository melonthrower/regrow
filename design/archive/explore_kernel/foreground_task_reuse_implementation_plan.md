# Foreground Region Task Reuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make modular exploration inventory only the active foreground surface, reuse Region/Operation task history before task creation, and schedule one binding per logical task before deferred revisits.

**Architecture:** Keep the existing ExplorationLedger, local Operation/Task records, CanonicalOperation identity, and evidence artifacts. Split page-report acceptance from task materialization; perform source-first Region/Operation identity between them; derive logical task views from canonical identities and run a pending-first/deferred-second scheduler.

**Tech Stack:** Python 3.10, dataclasses, pytest, existing OSWorld VMware environment, `gpt-5.6-luna` through the existing modular `codex_cli` backend.

**Spec:** `design/modules/explore_kernel/foreground_task_reuse_design.md`

## Global Constraints

- Root Agent is the only implementation agent; do not spawn subagents.
- Do not modify or stage the user's existing changes in `gui_rewalk/src/core/scenario/live_state_locator.py` or `tests/test_live_state_locator.py`.
- Do not add application names, page names, control names, coordinates, screenshots, or target-specific exceptions to production code or prompts.
- Keep `qwen_api`, `codex_cli`, and `openai_api` on the same modular Prompt, Schema, parsing, runtime, and scheduler contracts.
- Do not add a parallel task-history store. Derive logical history from Region, CanonicalOperation, local Operation, Task, Attempt, and existing ledger events.
- A normal Region inheritance call has exactly current plus source screenshots. One fallback call may use current plus one historical candidate screenshot. One transition may reference at most three distinct screenshots.
- First pass attempts at most one executable binding per logical task. Deferred bindings are revisited only after no unattempted logical tasks remain.
- A local failure remains auditable. Any verified binding completes the canonical logical task; all exhausted bindings produce one logical gap.
- Run focused Tier 3 tests, syntax checks, saved-frame probes, and controlled Calculator plus one low-risk representative live path. Do not run Files or Terminal live.
- Every behavior change updates `design/modules/explore_kernel/*.md`, `design/modules/explore_kernel_design.md` when routing changes, and `design/changelog/2026-08.md` with exact verification evidence.

---

### Task 1: Restore the active-surface inventory contract

**Files:**
- Modify: `gui_rewalk/src/core/explore/prompts.py:9-29`
- Modify: `design/modules/explore_kernel/page_inventory.md`
- Test: `tests/test_explore_kernel.py`

**Interfaces:**
- Consumes: existing `MAIN_SYSTEM_PROMPT`, `PageReport`, and `handling=explore|record|defer` schema.
- Produces: one generic active-surface contract used unchanged by every model backend.

- [ ] **Step 1: Add a failing Prompt contract test**

Add beside `test_region_identity_rules_use_static_system_prompt()`:

```python
def test_main_prompt_inventory_is_active_surface_only() -> None:
    assert "只清点当前最前景且能直接接收用户交互的目标应用 surface" \
        in MAIN_SYSTEM_PROMPT
    assert "被该 surface 接管的背景只作为截图上下文" \
        in MAIN_SYSTEM_PROMPT
    assert "仍可直接交互的持久导航栏、工具栏或侧栏继续登记" \
        in MAIN_SYSTEM_PROMPT
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider `
  tests/test_explore_kernel.py::test_main_prompt_inventory_is_active_surface_only `
  --basetemp artifacts/.pytest_foreground_prompt_red_20260826
```

Expected: FAIL because the current Prompt says “全部可见稳定结构” without the active-surface/background distinction.

- [ ] **Step 3: Make the minimal Prompt change**

In `MAIN_SYSTEM_PROMPT`, preserve existing Region definitions and add this cross-application rule to the page-report section:

```text
page_report 只清点当前最前景且能直接接收用户交互的目标应用 surface。
菜单、弹层、对话框或抽屉接管交互时，被该 surface 接管的背景只作为截图上下文，
不登记为当前 State 的 Region/Element/Operation。新页面中仍可直接交互的持久导航栏、
工具栏或侧栏继续登记，并在 Identity 后复用既有任务历史。
```

Do not change the response schema or add `surface_kind`.

- [ ] **Step 4: Run the test and focused Prompt tests GREEN**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider `
  tests/test_explore_kernel.py -k "prompt or page_inventory" `
  --basetemp artifacts/.pytest_foreground_prompt_green_20260826
```

Expected: all selected tests PASS.

- [ ] **Step 5: Update the current page-inventory document**

Update `page_inventory.md` to distinguish intercepted background from persistent foreground navigation. State explicitly that `recover/route` closes the foreground surface without requiring background bindings in the transient State.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- gui_rewalk/src/core/explore/prompts.py tests/test_explore_kernel.py `
  design/modules/explore_kernel/page_inventory.md design/changelog/2026-08.md
git diff --cached --check
git commit -m "Constrain modular inventory to the active surface"
```

---

### Task 2: Delay local Task creation until after identity

**Files:**
- Modify: `gui_rewalk/src/core/explore/inventory.py:80-130,219-378`
- Modify: `gui_rewalk/src/core/explore/runtime.py:1983-2005`
- Test: `tests/test_explore_kernel.py:2525-2635`

**Interfaces:**
- Produces: `materialize_state_operation_tasks(ledger: ExplorationLedger, *, state_id: str) -> ExplorationLedger`.
- Changes: `apply_page_report()` writes facts and operation proposals but no Task rows.
- Consumed later by: Region identity runtime and scheme-A canonical history reuse.

- [ ] **Step 1: Replace the immediate-task test with an explicit staging RED test**

Add a focused test based on `test_page_inventory_creates_tasks_and_preserves_offscreen_facts()`:

```python
def test_page_inventory_stages_operations_without_tasks() -> None:
    ledger = _seed_ledger()
    report = parse_turn(
        _turn(screen=_known_screen(), page_report=_report()),
        has_pending_action=False,
    ).page_report
    assert report is not None
    result = apply_page_report(
        ledger,
        state_id="s1",
        report=report,
    )

    assert result.ok is True
    assert result.ledger.operations
    assert result.ledger.tasks == {}
```

Parse the report through the production contract exactly as `_seed_ledger()` does:

```python
report = parse_turn(
    _turn(screen=_known_screen(), page_report=_report()),
    has_pending_action=False,
).page_report
assert report is not None
```

- [ ] **Step 2: Run RED**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider `
  tests/test_explore_kernel.py::test_page_inventory_stages_operations_without_tasks `
  --basetemp artifacts/.pytest_inventory_staging_red_20260826
```

Expected: FAIL because `_accept_operation()` currently invokes `_ensure_operation_task()`.

- [ ] **Step 3: Remove task materialization from `_accept_operation()`**

Keep Operation status assignment, CanonicalOperation creation, element ownership, and source occurrence references unchanged. Remove only the `_ensure_operation_task(...)` call from inventory acceptance.

- [ ] **Step 4: Add the explicit materializer with a failing test**

Add:

```python
def test_materialize_state_operation_tasks_is_idempotent() -> None:
    ledger = _seed_ledger()
    assert ledger.tasks == {}

    once = materialize_state_operation_tasks(ledger, state_id="s1")
    twice = materialize_state_operation_tasks(once, state_id="s1")

    assert logical_task_count(once) == 1
    assert logical_task_count(twice) == 1
    assert len(twice.tasks) == len(once.tasks)
```

Run it before implementation and verify import/function failure.

- [ ] **Step 5: Implement `materialize_state_operation_tasks()`**

Implementation shape:

```python
def materialize_state_operation_tasks(
    ledger: ExplorationLedger,
    *,
    state_id: str,
) -> ExplorationLedger:
    staged = ledger.clone()
    operation_ids = {
        operation.operation_id
        for occurrence in staged.state_occurrences(state_id)
        for operation in staged.occurrence_operations(occurrence.occurrence_id)
    }
    for operation_id in sorted(operation_ids):
        operation = staged.operations.get(operation_id)
        if operation is not None:
            _ensure_operation_task(staged, operation, state_id=state_id)
    return staged
```

Export it from `inventory.py`. Do not import scheduler code into inventory.

- [ ] **Step 6: Call the materializer after Region identity**

In runtime, preserve this order:

```python
self.ledger = inventory.ledger
if confirmed_state.survey_complete:
    self._review_region_identity(
        state_id=self.ledger.current_state_id,
        current_region_ids=[
            item.region_id
            for item in self.ledger.state_occurrences(
                self.ledger.current_state_id)
        ],
        screenshot=screenshot,
    )
    self.ledger = materialize_state_operation_tasks(
        self.ledger,
        state_id=self.ledger.current_state_id,
    )
```

Materialize even when no Region candidate exists. Do not materialize on an incomplete survey.

- [ ] **Step 7: Run focused inventory/runtime tests GREEN**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider `
  tests/test_explore_kernel.py -k "page_inventory or materialize or runtime_completes_one_survey" `
  --basetemp artifacts/.pytest_inventory_staging_green_20260826
```

- [ ] **Step 8: Update inventory/runtime documentation**

Update `page_inventory.md` and `runtime_and_artifacts.md` so their current flow says facts are staged, Region/Operation identity runs, then local task bindings are materialized. Append the RED/GREEN commands and totals to `design/changelog/2026-08.md`.

- [ ] **Step 9: Commit Task 2**

```powershell
git add -- gui_rewalk/src/core/explore/inventory.py gui_rewalk/src/core/explore/runtime.py `
  tests/test_explore_kernel.py design/modules/explore_kernel/page_inventory.md `
  design/modules/explore_kernel/runtime_and_artifacts.md design/changelog/2026-08.md
git diff --cached --check
git commit -m "Materialize modular tasks after region identity"
```

---

### Task 3: Restore source-first Region inheritance with a bounded fallback

**Files:**
- Modify: `gui_rewalk/src/core/explore/regions.py:144-250`
- Modify: `gui_rewalk/src/core/explore/runtime.py:918-1015,1240-1355`
- Modify: `gui_rewalk/src/core/explore/agent.py` so each identity call receives one explicit candidate-State plan and never selects screenshots internally
- Test: `tests/test_explore_kernel.py:1104-1325,3535-3625`

**Interfaces:**
- Produces: `source_region_candidate_occurrences(ledger, *, source_state_id: str) -> list[tuple[str, str]]`.
- Produces: `fallback_region_candidate_occurrences(ledger, *, state_id: str, current_region_ids: Sequence[str], excluded_state_ids: set[str]) -> list[tuple[str, str]]` with at most one candidate State.
- Produces: `inheritance_source_state_id(ledger: ExplorationLedger, *, source_state_id: str) -> str`, following `surface_host_bound` events and returning `""` on broken/cyclic provenance.
- Runtime identity order: source pass, then one fallback pass only for unmatched current Regions.

- [ ] **Step 1: Add a RED test for source candidates that ignore text drift**

```python
def test_source_region_candidates_ignore_name_and_target_drift() -> None:
    ledger = ExplorationLedger()
    ledger.pages["p1"] = Page(
        "p1", "Calculator", "计算器", ["s6", "s_current"])
    ledger.states["s6"] = PageState(
        "s6", "p1", "Basic 1+1", "已输入表达式",
        "screenshots/s6.png", ["ro15", "ro16", "ro17"], True, 1,
    )
    for region_id, occurrence_id, name in (
        ("r1", "ro15", "应用工具栏"),
        ("r16", "ro16", "表达式与结果区"),
        ("r17", "ro17", "基本计算键盘"),
    ):
        ledger.regions[region_id] = Region(
            region_id, name, name, occurrence_ids=[occurrence_id])
        ledger.occurrences[occurrence_id] = RegionOccurrence(
            occurrence_id, region_id, "s6", name, name)
    ledger.states["s_current"] = PageState(
        "s_current", "p1", "Menu", "菜单展开",
        "screenshots/current.png", ["ro19"], True, 1,
    )
    ledger.regions["r19"] = Region(
        "r19", "计算器显示与表达式区", "显示 1+1",
        operation_ids=["o19"], occurrence_ids=["ro19"],
    )
    ledger.occurrences["ro19"] = RegionOccurrence(
        "ro19", "r19", "s_current", "计算器显示与表达式区", "显示 1+1")
    ledger.operations["o19"] = Operation(
        "o19", "r19", "input_text", "计算器表达式输入框", "pending",
        source_occurrence_ids=["ro19"],
    )

    candidates = source_region_candidate_occurrences(
        ledger,
        source_state_id="s6",
    )

    assert candidates == [
        ("r1", "ro15"),
        ("r16", "ro16"),
        ("r17", "ro17"),
    ]
```

The current card deliberately uses the drifted strings `计算器显示与表达式区` and `计算器表达式输入框`; it cannot remove source candidates because this function does not score text.

- [ ] **Step 2: Add a RED test for the image budget**

Add `import hashlib` and import `ArtifactWriter` from `gui_rewalk.src.core.explore.artifacts` in the test module.

Add this capture double beside the existing `_Agent` test double:

```python
class _RegionCallCaptureAgent(_Agent):
    def __init__(self, turns, region_results):
        super().__init__(turns)
        self.region_results = iter(region_results)
        self.region_calls = []

    def correspond_regions(self, **kwargs):
        self.region_calls.append(kwargs)
        return next(self.region_results)
```

Add this literal runtime fixture after the capture Agent:

```python
def _runtime_with_three_historical_candidate_states(tmp_path):
    ledger = ExplorationLedger()
    ledger.pages["p1"] = Page(
        "p1", "Page", "候选页",
        ["s_source", "s_current", "s_match", "s_noise"],
    )
    state_rows = (
        ("s_source", "r_source", "ro_source", "来源工具栏", "来源操作"),
        ("s_current", "r_current", "ro_current", "共享输入区", "输入内容"),
        ("s_match", "r_match", "ro_match", "共享输入区", "输入内容"),
        ("s_noise", "r_noise", "ro_noise", "其他内容区", "打开其他内容"),
    )
    for index, (state_id, region_id, occurrence_id, name, target) in enumerate(
        state_rows, start=1,
    ):
        screenshot_ref = f"screenshots/{state_id}.png"
        ledger.states[state_id] = PageState(
            state_id, "p1", state_id, state_id,
            screenshot_ref, [occurrence_id], True, 1,
        )
        ledger.regions[region_id] = Region(
            region_id, name, name,
            operation_ids=[f"o{index}"], occurrence_ids=[occurrence_id],
        )
        ledger.occurrences[occurrence_id] = RegionOccurrence(
            occurrence_id, region_id, state_id, name, name,
        )
        ledger.operations[f"o{index}"] = Operation(
            f"o{index}", region_id, "click", target, "pending",
            source_occurrence_ids=[occurrence_id],
        )
        path = tmp_path / screenshot_ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_png(("white", "gray", "navy", "black")[index - 1]))
    ledger.transitions.append(Transition(
        "e1", "s_source", "s_current", "a1", {"kind": "click"}, "current"))
    ledger.current_state_id = "s_current"
    first = {
        "decisions": [{
            "current_region_ref": "r_current",
            "decision": "separate",
            "component_relation": "different_component",
            "causal_relation": "none",
            "known_region_ref": "",
            "shared_operations": [],
            "reason": "来源候选是不同组件。",
        }],
        "reason": "来源 pass 未复用。",
    }
    second = {
        "decisions": [{
            "current_region_ref": "r_current",
            "decision": "reuse",
            "component_relation": "same_complete_component",
            "causal_relation": "none",
            "known_region_ref": "r_match",
            "shared_operations": [{
                "current_operation_ref": "o2",
                "known_operation_ref": "o3",
                "reuse_level": "identity",
            }],
            "reason": "远距离候选是同一输入区。",
        }],
        "reason": "fallback pass 复用。",
    }
    agent = _RegionCallCaptureAgent([], [first, second])
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.agent = agent
    runtime.artifacts = ArtifactWriter(str(tmp_path))
    return runtime, agent
```

Then write the image-budget test:

```python
def test_region_identity_uses_source_then_one_fallback_state(tmp_path) -> None:
    runtime, agent = _runtime_with_three_historical_candidate_states(tmp_path)
    runtime._review_region_identity(
        state_id="s_current",
        source_state_id="s_source",
        current_region_ids=["r_current"],
        screenshot=_png("white"),
    )

    assert [len(call["screenshots"]) for call in agent.region_calls] == [2, 2]
    unique_hashes = {
        hashlib.sha256(item).hexdigest()
        for call in agent.region_calls
        for item in call["screenshots"]
    }
    assert len(unique_hashes) <= 3
```

Expected RED: current runtime has no `source_state_id` argument and may shortlist two candidate States before image review.

- [ ] **Step 3: Implement mandatory source candidates**

```python
def source_region_candidate_occurrences(
    ledger: ExplorationLedger,
    *,
    source_state_id: str,
) -> list[tuple[str, str]]:
    return [
        (occurrence.region_id, occurrence.occurrence_id)
        for occurrence in ledger.state_occurrences(source_state_id)
    ]
```

Do not score or filter these candidates by text.

- [ ] **Step 4: Restrict fallback to one candidate State**

Reuse the current text/operation scoring for distant history, but set `max_candidate_states=1`, exclude the source/inheritance State, and process only Regions not reused in the source pass.

- [ ] **Step 5: Derive the inheritance source from existing evidence**

Use the pending ActionAttempt source State for ordinary transitions. For a source State already identified as an independently revealed surface, emit/read a ledger event:

```python
ledger.event(
    "surface_host_bound",
    state_id=current_state_id,
    host_state_id=attempt.source_state_id,
    trigger_attempt_id=attempt.attempt_id,
)
```

`inheritance_source_state_id()` follows this event chain to the nearest stable host. Do not add a PageState field unless a failing resume test proves event-derived recovery insufficient.

- [ ] **Step 6: Run Region recall and identity tests GREEN**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider `
  tests/test_explore_kernel.py -k "region_candidates or region_shortlist or region_identity or inheritance_source" `
  --basetemp artifacts/.pytest_region_source_first_green_20260826
```

- [ ] **Step 7: Update Region identity documentation and commit**

Document the two calls, image budgets, fail-closed unmatched behavior, and canonical-name authority.

```powershell
git add -- gui_rewalk/src/core/explore/regions.py gui_rewalk/src/core/explore/runtime.py `
  gui_rewalk/src/core/explore/agent.py tests/test_explore_kernel.py `
  design/modules/explore_kernel/region_identity.md design/changelog/2026-08.md
git diff --cached --check
git commit -m "Restore source-first modular region identity"
```

---

### Task 4: Materialize scheme-A canonical task history

**Files:**
- Modify: `gui_rewalk/src/core/explore/inventory.py`
- Modify: `gui_rewalk/src/core/explore/tasks.py:1-95`
- Modify: `gui_rewalk/src/core/explore/regions.py` only for task migration during confirmed identity
- Test: `tests/test_explore_kernel.py:767-890,2857-3290`

**Interfaces:**
- Consumes: staged local Operations after Region/Operation identity.
- Produces: one logical task view per `canonical_operation_id`, with any number of local Operation/Task bindings.
- Preserves: existing local Task records as binding-level execution/audit state.

- [ ] **Step 1: Add a RED test for one logical task across State bindings**

Add this literal two-binding fixture in the test file:

```python
def _shared_region_two_state_ledger(
    *, first_status: str = "pending",
    second_status: str = "pending",
) -> ExplorationLedger:
    ledger = ExplorationLedger()
    ledger.pages["p1"] = Page("p1", "Page", "共享页面", ["s1", "s2"])
    for state_id, occurrence_id, variant_id in (
        ("s1", "ro1", "rv1"),
        ("s2", "ro2", "rv2"),
    ):
        ledger.states[state_id] = PageState(
            state_id, "p1", state_id, state_id,
            f"screenshots/{state_id}.png", [occurrence_id], True, 1,
        )
        ledger.occurrences[occurrence_id] = RegionOccurrence(
            occurrence_id, "r1", state_id, "共享输入区", "同一输入区",
            variant_id=variant_id,
        )
        ledger.region_variants[variant_id] = RegionVariant(variant_id, "r1")
    ledger.regions["r1"] = Region(
        "r1", "共享输入区", "同一输入区",
        operation_ids=["o1", "o2"], occurrence_ids=["ro1", "ro2"],
        variant_ids=["rv1", "rv2"], canonical_operation_ids=["co1"],
    )
    ledger.canonical_operations["co1"] = CanonicalOperation(
        "co1", "r1", "input_text", "输入内容", ["o1", "o2"])
    for operation_id, state_id, occurrence_id, variant_id, status in (
        ("o1", "s1", "ro1", "rv1", first_status),
        ("o2", "s2", "ro2", "rv2", second_status),
    ):
        ledger.operations[operation_id] = Operation(
            operation_id, "r1", "input_text", "输入内容", status,
            source_occurrence_ids=[occurrence_id], variant_id=variant_id,
            canonical_operation_id="co1",
        )
        ledger.region_variants[variant_id].operation_ids.append(operation_id)
    return ledger
```

```python
def test_materialization_reuses_canonical_task_history_across_states() -> None:
    ledger = _shared_region_two_state_ledger()
    ledger = materialize_state_operation_tasks(ledger, state_id="s1")
    ledger = materialize_state_operation_tasks(ledger, state_id="s2")

    assert logical_task_count(ledger) == 1
    assert sorted(
        tuple(sorted(task_source_states(ledger, task)))
        for task in ledger.tasks.values()
        if task.kind == "explore_operation"
    ) == [("s1",), ("s2",)]
```

- [ ] **Step 2: Add a RED test for verified history suppression**

```python
def test_new_binding_is_not_pending_when_canonical_sibling_verified() -> None:
    ledger = _shared_region_two_state_ledger(first_status="verified")

    result = materialize_state_operation_tasks(ledger, state_id="s2")

    current = result.operations["o2"]
    assert current.status == "recorded"
    assert result.operation_task("o2") is None
    assert logical_task_count(result) == 0
```

- [ ] **Step 3: Make materialization canonical-history aware**

Before `_ensure_operation_task()`:

```python
identity = staged.canonical_operations.get(operation.canonical_operation_id)
siblings = [
    staged.operations[item]
    for item in (identity.operation_ids if identity else [])
    if item in staged.operations and item != operation.operation_id
]
if any(item.status == "verified" for item in siblings):
    operation.status = "recorded"
    continue
```

If a canonical sibling already has a pending/deferred/failed local Task, create only the current local binding Task; `logical_task_count()` and gaps continue grouping by canonical identity. Do not clone verified results into the current local Operation.

- [ ] **Step 4: Preserve the first true task escalation**

Add a test where all historical bindings are `recorded`, the current same canonical Operation is newly reported `pending`, and no logical task has ever existed. Materialization must create the first logical task rather than suppressing it.

- [ ] **Step 5: Run canonical task tests GREEN**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider `
  tests/test_explore_kernel.py -k "canonical or logical_task or task_history or region_merge" `
  --basetemp artifacts/.pytest_canonical_task_history_green_20260826
```

- [ ] **Step 6: Update canonical task-history documentation**

Update `operation_tasks.md` to distinguish one canonical logical task from its local Task bindings and document the verified-sibling suppression rule. Append exact test evidence to `design/changelog/2026-08.md`.

- [ ] **Step 7: Commit Task 4**

```powershell
git add -- gui_rewalk/src/core/explore/inventory.py gui_rewalk/src/core/explore/tasks.py `
  gui_rewalk/src/core/explore/regions.py tests/test_explore_kernel.py `
  design/modules/explore_kernel/operation_tasks.md design/changelog/2026-08.md
git diff --cached --check
git commit -m "Reuse canonical operation task history"
```

---

### Task 5: Implement pending-first, deferred-second binding scheduling

**Files:**
- Modify: `gui_rewalk/src/core/explore/tasks.py:20-250`
- Modify: `gui_rewalk/src/core/explore/runtime.py:600-670,1490-1620`
- Modify: `gui_rewalk/src/core/explore/status.py`
- Test: `tests/test_explore_kernel.py:628-890,1875-2325`

**Interfaces:**
- Produces: `LogicalOperationTaskView` derived from current ledger state.
- Produces: `logical_operation_task_views(ledger: ExplorationLedger) -> Sequence[LogicalOperationTaskView]`.
- Produces: `_choose_nearest_binding(ledger: ExplorationLedger, views: Sequence[LogicalOperationTaskView], *, phase: str) -> Optional[Task]`, where phase is `"first_pass"` or `"revisit"`.
- Scheduler returns one local Task binding, but phase selection is based on logical views.

- [ ] **Step 1: Add a RED test proving B1 failure yields to L2**

Add these scheduler fixtures:

```python
def _add_execute_attempt(
    ledger: ExplorationLedger,
    *,
    attempt_id: str,
    task_id: str,
    operation_ref: str,
    source_state_id: str,
    outcome: str,
) -> None:
    ledger.attempts[attempt_id] = ActionAttempt(
        attempt_id, task_id, source_state_id, "execute",
        {"kind": "click", "operation_ref": operation_ref},
        f"action_attempts/{attempt_id}/before.png",
        after_ref=f"action_attempts/{attempt_id}/after.png",
        outcome=outcome,
    )


def _logical_scheduler_ledger() -> ExplorationLedger:
    ledger = ExplorationLedger()
    ledger.pages["p1"] = Page(
        "p1", "Page", "调度页",
        ["s_current", "s_b1", "s_b2", "s_mid", "s_b3", "s_l2"],
    )
    for state_id in ledger.pages["p1"].state_ids:
        ledger.states[state_id] = PageState(
            state_id, "p1", state_id, state_id,
            f"screenshots/{state_id}.png", [], True, 1,
        )
    ledger.current_state_id = "s_current"
    ledger.transitions.extend([
        Transition("e1", "s_current", "s_b2", "a_route1", {"kind": "click"}, "near"),
        Transition("e2", "s_current", "s_mid", "a_route2", {"kind": "click"}, "mid"),
        Transition("e3", "s_mid", "s_b3", "a_route3", {"kind": "click"}, "far"),
        Transition("e4", "s_current", "s_l2", "a_route4", {"kind": "click"}, "next logical"),
    ])
    for region_id, canonical_id, target in (
        ("r1", "co1", "L1"),
        ("r2", "co2", "L2"),
    ):
        ledger.regions[region_id] = Region(
            region_id, target, target, canonical_operation_ids=[canonical_id])
        ledger.canonical_operations[canonical_id] = CanonicalOperation(
            canonical_id, region_id, "click", target, [])
    for operation_id, task_id, state_id, canonical_id, region_id in (
        ("o_b1", "t_b1", "s_b1", "co1", "r1"),
        ("o_b2", "t_b2_near", "s_b2", "co1", "r1"),
        ("o_b3", "t_b3_far", "s_b3", "co1", "r1"),
        ("o_l2", "t_l2", "s_l2", "co2", "r2"),
    ):
        occurrence_id = "ro_" + operation_id
        variant_id = "rv_" + operation_id
        ledger.occurrences[occurrence_id] = RegionOccurrence(
            occurrence_id, region_id, state_id, region_id, region_id,
            variant_id=variant_id,
        )
        ledger.states[state_id].region_occurrence_ids.append(occurrence_id)
        ledger.region_variants[variant_id] = RegionVariant(variant_id, region_id)
        ledger.operations[operation_id] = Operation(
            operation_id, region_id, "click",
            "L1" if canonical_id == "co1" else "L2", "pending",
            source_occurrence_ids=[occurrence_id], variant_id=variant_id,
            canonical_operation_id=canonical_id,
        )
        ledger.canonical_operations[canonical_id].operation_ids.append(operation_id)
        ledger.tasks[task_id] = Task(
            task_id, "explore_operation", "pending", state_id, operation_id,
            created_seq=len(ledger.tasks) + 1,
        )
    return ledger
```

```python
def test_first_pass_binding_failure_yields_to_next_logical_task() -> None:
    ledger = _logical_scheduler_ledger()
    _add_execute_attempt(
        ledger,
        attempt_id="a_b1",
        task_id="t_b1",
        operation_ref="o_b1",
        source_state_id="s_b1",
        outcome="failed",
    )
    ledger.tasks["t_b1"].status = "deferred"
    ledger.operations["o_b1"].status = "deferred"

    chosen = TaskScheduler().choose(ledger)

    assert chosen.task_id == "t_l2"
```

The fixture must also contain an untried `B2` binding for L1. The failure is correct only if current Scheduler chooses B2 too early.

- [ ] **Step 2: Add a RED test proving deferred revisit chooses nearest B2**

```python
def test_second_pass_revisits_nearest_untried_binding() -> None:
    ledger = _logical_scheduler_ledger()
    _add_execute_attempt(
        ledger,
        attempt_id="a_b1",
        task_id="t_b1",
        operation_ref="o_b1",
        source_state_id="s_b1",
        outcome="failed",
    )
    _add_execute_attempt(
        ledger,
        attempt_id="a_l2",
        task_id="t_l2",
        operation_ref="o_l2",
        source_state_id="s_l2",
        outcome="failed",
    )
    ledger.tasks["t_b1"].status = "deferred"
    ledger.operations["o_b1"].status = "deferred"
    ledger.tasks["t_l2"].status = "failed"
    ledger.operations["o_l2"].status = "failed"
    ledger.current_state_id = "s_current"

    chosen = TaskScheduler().choose(ledger)

    assert chosen.task_id == "t_b2_near"
```

Include a farther B3 and directed transitions so the expected choice proves shortest directed distance.

- [ ] **Step 3: Add `LogicalOperationTaskView`**

```python
@dataclass(frozen=True)
class LogicalOperationTaskView:
    canonical_operation_id: str
    binding_task_ids: tuple[str, ...]
    verified: bool
    first_pass_attempted: bool
    untried_binding_task_ids: tuple[str, ...]
    deferred_binding_task_ids: tuple[str, ...]
    failed_binding_task_ids: tuple[str, ...]
```

`first_pass_attempted` is true after any binding has a real `purpose=execute` Attempt, or an explicit terminal unavailable fact. Route/recover alone does not count as the logical first attempt.

- [ ] **Step 4: Refactor `TaskScheduler.choose()` around logical phases**

Pseudo-code:

```python
views = logical_operation_task_views(ledger)
phase_one = [item for item in views if not item.verified and not item.first_pass_attempted]
if phase_one:
    chosen = _choose_nearest_binding(ledger, phase_one, phase="first_pass")
    if chosen is not None:
        return chosen
phase_two = [item for item in views if not item.verified and item.untried_binding_task_ids]
if phase_two:
    chosen = _choose_nearest_binding(ledger, phase_two, phase="revisit")
    if chosen is not None:
        return chosen
# Continue through the existing page-survey and terminal fallback branches.
```

Preserve page survey priority. Keep directed graph distance and deterministic created-sequence tiebreakers.

- [ ] **Step 5: Release a binding after an inconclusive execute attempt**

When one `purpose=execute` Attempt settles with `failed`, `uncertain`, or `no_effect` that is not `completed`:

```python
binding_task.status = "deferred"
operation.status = "deferred"
ledger.current_task_id = ""
```

Do not release on a route/recover action that is still making bounded progress toward an untried binding. Existing identical-action and no-effect recovery guards remain final safety bounds.

- [ ] **Step 6: Ensure verified B2 closes L1 but preserves B1 evidence**

Extend `test_verified_binding_closes_logical_gap_but_keeps_failed_evidence()` to assert:

```python
assert ledger.operations["o_b1"].status == "failed"
assert ledger.operations["o_b2"].status == "verified"
assert TaskScheduler.gaps(ledger) == []
```

- [ ] **Step 7: Run scheduler/runtime tests GREEN**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider `
  tests/test_explore_kernel.py -k "scheduler or binding or logical_task or no_effect or recovery" `
  --basetemp artifacts/.pytest_binding_scheduler_green_20260826
```

- [ ] **Step 8: Update two-phase scheduling documentation**

Update `operation_tasks.md` and `action_transition.md` with first-pass/revisit priority, the definition of a first real binding attempt, binding release semantics, and the single logical-gap boundary. Append exact test evidence to `design/changelog/2026-08.md`.

- [ ] **Step 9: Commit Task 5**

```powershell
git add -- gui_rewalk/src/core/explore/tasks.py gui_rewalk/src/core/explore/runtime.py `
  gui_rewalk/src/core/explore/status.py tests/test_explore_kernel.py `
  design/modules/explore_kernel/operation_tasks.md `
  design/modules/explore_kernel/action_transition.md design/changelog/2026-08.md
git diff --cached --check
git commit -m "Schedule one binding per logical task pass"
```

---

### Task 6: Verify logical completion, image budgets, saved frames, and live behavior

**Files:**
- Audit and modify only if the RED completion test fails: `gui_rewalk/src/core/explore/status.py`
- Audit and modify only if the RED completion test fails: `gui_rewalk/src/core/explore/bundle.py`
- Create: `tools/probe_modular_foreground_reuse.py`
- Create: `tests/test_probe_modular_foreground_reuse.py`
- Modify: `tests/test_explore_kernel.py`
- Modify: `design/modules/explore_kernel_design.md`
- Modify: `design/modules/explore_kernel/page_inventory.md`
- Modify: `design/modules/explore_kernel/region_identity.md`
- Modify: `design/modules/explore_kernel/operation_tasks.md`
- Modify: `design/modules/explore_kernel/runtime_and_artifacts.md`
- Modify: `design/changelog/2026-08.md`

**Interfaces:**
- Completion and bundle count canonical logical tasks once while preserving every local binding and Attempt.
- Saved-frame/live outputs remain new artifacts; old raw evidence is read-only.

- [ ] **Step 1: Add a completion RED test for multiple failed bindings**

```python
def test_multiple_failed_bindings_form_one_logical_gap() -> None:
    ledger = _shared_region_two_state_ledger(
        first_status="failed",
        second_status="failed",
    )

    gaps = TaskScheduler.gaps(ledger)

    assert len(gaps) == 1
    assert "bindings=" in gaps[0]
```

If this already passes, retain it as characterization evidence and do not modify production code for this step.

- [ ] **Step 2: Run full focused Tier 3 suite**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider `
  tests/test_explore_kernel.py tests/test_local_html_env.py `
  --basetemp artifacts/.pytest_foreground_task_reuse_tier3_20260826
```

Expected: all tests PASS. Record exact totals.

- [ ] **Step 3: Run syntax and diff checks**

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m py_compile `
  gui_rewalk/src/core/explore/prompts.py `
  gui_rewalk/src/core/explore/inventory.py `
  gui_rewalk/src/core/explore/regions.py `
  gui_rewalk/src/core/explore/runtime.py `
  gui_rewalk/src/core/explore/tasks.py `
  gui_rewalk/src/core/explore/status.py `
  gui_rewalk/src/core/explore/bundle.py `
  tests/test_explore_kernel.py
git diff --check
```

- [ ] **Step 4: Run saved-frame Calculator foreground validation**

Create `tools/probe_modular_foreground_reuse.py` with this CLI:

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--source-image", required=True, type=Path)
    parser.add_argument("--current-image", required=True, type=Path)
    parser.add_argument("--source-ledger", required=True, type=Path)
    parser.add_argument("--source-state", required=True)
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--backend", choices=("codex_cli",), default="codex_cli")
    parser.add_argument("--model", default="gpt-5.6-luna")
    return parser
```

The script must:

1. load the two screenshot bytes and the read-only source ledger;
2. call `CodexExplorerAgent.decide()` once on the current screenshot with a first-survey context;
3. assign probe-local current Region/Operation refs without mutating the source ledger;
4. build one source-pass Region payload from every occurrence in `--source-state`;
5. call `CodexExplorerAgent.correspond_regions()` with exactly `[current_bytes, source_bytes]`;
6. copy the validated `--expected` object and write `input.json`, `main_raw.json`, `region_raw.json`, `expected.json`, `screenshot_hashes.json`, and `result.json` below `--output-root`;
7. return nonzero if the main report includes a `forbidden_background_targets` value, omits a `required_current_targets` value, if the Region call uses other than two images, or if `required_reuse_pairs` / `required_separate_regions` are absent from the verdict.

Unit-test the argument contract and a fake-agent successful probe in `tests/test_probe_modular_foreground_reuse.py`; the test must use in-memory fake image bytes and must not invoke a model.

Use the preserved source/current images:

```text
artifacts/luna_command_design_batch_20260826/20260826/calculator/action_attempts/a7/before.png
artifacts/luna_command_design_batch_20260826/20260826/calculator/screenshots/frame_00018.png
```

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe tools/probe_modular_foreground_reuse.py `
  --app-name calculator `
  --source-image artifacts/luna_command_design_batch_20260826/20260826/calculator/action_attempts/a7/before.png `
  --current-image artifacts/luna_command_design_batch_20260826/20260826/calculator/screenshots/frame_00018.png `
  --source-ledger artifacts/luna_command_design_batch_20260826/20260826/calculator/exploration_ledger.json `
  --source-state s6 `
  --expected artifacts/probes/foreground_task_reuse_calculator_expected_20260826.json `
  --output-root artifacts/probes/foreground_task_reuse_calculator_20260826 `
  --backend codex_cli --model gpt-5.6-luna
```

Prepare the probe-local `expected.json` with `forbidden_background_targets` containing the Calculator expression-input and keypad targets, plus `required_current_targets` for the menu entries. Acceptance:

Write `artifacts/probes/foreground_task_reuse_calculator_expected_20260826.json` as:

```json
{
  "forbidden_background_targets": [
    "计算器表达式输入框",
    "数字按键计算器输入",
    "等号计算器计算"
  ],
  "required_current_targets": [
    "New Window 计算器新窗口",
    "Preferences 计算器偏好设置"
  ],
  "required_reuse_pairs": [],
  "required_separate_regions": ["应用菜单弹层"]
}
```

- menu State reports only the active menu surface;
- source pass sends exactly current plus source screenshots;
- no background input/keyboard Operation or Task is materialized;
- no application-specific Prompt text is present.

- [ ] **Step 5: Run saved-frame Files inheritance validation without live Files**

Use the same tool:

```text
artifacts/luna_command_design_batch_20260826_files_wmclass/20260826/files/screenshots/frame_00001.png
artifacts/luna_command_design_batch_20260826_files_wmclass/20260826/files/screenshots/frame_00004.png
```

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe tools/probe_modular_foreground_reuse.py `
  --app-name files `
  --source-image artifacts/luna_command_design_batch_20260826_files_wmclass/20260826/files/screenshots/frame_00001.png `
  --current-image artifacts/luna_command_design_batch_20260826_files_wmclass/20260826/files/screenshots/frame_00004.png `
  --source-ledger artifacts/luna_command_design_batch_20260826_files_wmclass/20260826/files/exploration_ledger.json `
  --source-state s1 `
  --expected artifacts/probes/foreground_task_reuse_files_expected_20260826.json `
  --output-root artifacts/probes/foreground_task_reuse_files_20260826 `
  --backend codex_cli --model gpt-5.6-luna
```

Prepare `expected.json` with required reuse pairs for the navigation and toolbar Regions and one required separate current main-content Region.

Write `artifacts/probes/foreground_task_reuse_files_expected_20260826.json` as:

```json
{
  "forbidden_background_targets": [],
  "required_current_targets": ["搜索按钮", "更多选项按钮"],
  "required_reuse_pairs": [
    ["左侧位置导航栏", "左侧位置导航栏"],
    ["路径与工具栏", "路径与工具栏"]
  ],
  "required_separate_regions": ["Desktop 文件网格"]
}
```

Acceptance:

- navigation and toolbar reuse canonical Region/history;
- main content remains new/separate;
- exactly two screenshots are used in the source pass;
- no second logical task is created for shared toolbar/navigation operations.

- [ ] **Step 6: Run controlled Calculator live validation**

Start from `init_state`, use `--modular-explore --explore-backend codex_cli --explore-model gpt-5.6-luna`, a small explicit action budget, and a new result root. Supervise every event. Acceptance:

- menu open/close does not create a background input task;
- no menu close→binding rejection→menu reopen oscillation;
- first binding failure releases the logical task;
- VM closes and no task-created process remains.

Run:

```powershell
$env:PYTHONPATH='.;OSWorld'
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe gui_rewalk\run_visual_traversal.py `
  --vm_provider vmware `
  --path_to_vm 'C:\Users\Admin\Desktop\GUI agent\mywork\OSWorld\vmware_vm_data\Ubuntu0\Ubuntu0.vmx' `
  --app_name calculator `
  --modular-explore --explore-backend codex_cli --explore-model gpt-5.6-luna `
  --max_states 8 --max_actions 12 `
  --result_dir artifacts/foreground_task_reuse_calculator_live_20260826 `
  --require_complete --no_live_monitor
```

- [ ] **Step 7: Run one low-risk representative live path**

Use Calculator plus one non-Files/non-Terminal application whose persistent toolbar/navigation remains visible across a real page change. Apply the same evidence and cleanup boundaries. Do not claim all-app coverage.

Use Text Editor as the fixed representative:

```powershell
$env:PYTHONPATH='.;OSWorld'
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe gui_rewalk\run_visual_traversal.py `
  --vm_provider vmware `
  --path_to_vm 'C:\Users\Admin\Desktop\GUI agent\mywork\OSWorld\vmware_vm_data\Ubuntu0\Ubuntu0.vmx' `
  --app_name 'text editor' `
  --modular-explore --explore-backend codex_cli --explore-model gpt-5.6-luna `
  --max_states 8 --max_actions 10 `
  --result_dir artifacts/foreground_task_reuse_text_editor_live_20260826 `
  --require_complete --no_live_monitor
```

After each run verify cleanup:

```powershell
& 'C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe' -T ws list
```

Expected: `Total running VMs: 0`.

- [ ] **Step 8: Update docs and monthly changelog**

Record exact tests, static checks, saved-frame calls, live actions, logical task/binding counts, no-effect/rejections, image counts, completion status, and any remaining gaps. Update the module index only if the current routing description changed.

- [ ] **Step 9: Final exact-scope commit**

```powershell
git add -- gui_rewalk/src/core/explore/prompts.py `
  gui_rewalk/src/core/explore/inventory.py `
  gui_rewalk/src/core/explore/regions.py `
  gui_rewalk/src/core/explore/runtime.py `
  gui_rewalk/src/core/explore/tasks.py `
  gui_rewalk/src/core/explore/status.py `
  gui_rewalk/src/core/explore/bundle.py `
  tools/probe_modular_foreground_reuse.py `
  tests/test_probe_modular_foreground_reuse.py `
  tests/test_explore_kernel.py tests/test_local_html_env.py `
  design/CURRENT_FRAMEWORK.md design/modules/explore_kernel_design.md `
  design/modules/explore_kernel/page_inventory.md `
  design/modules/explore_kernel/region_identity.md `
  design/modules/explore_kernel/operation_tasks.md `
  design/modules/explore_kernel/action_transition.md `
  design/modules/explore_kernel/runtime_and_artifacts.md `
  design/changelog/2026-08.md
git diff --cached --name-status
git diff --cached --stat
git diff --cached --check
git commit -m "Reuse foreground region tasks across state bindings"
```

Stage only paths actually changed by the task. Do not stage generated artifacts, pytest temporary directories, caches, or the user's existing `live_state_locator` changes.
