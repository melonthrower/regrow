# Region Business Capability Induction and Task Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate Region-anchored business capabilities from a saved modular traversal ledger, then produce an object-dependent Clock instruction such as “create an 8:30 weekday alarm, then disable the alarm just created.”

**Architecture:** Keep the traversal ledger as button/Region/routing truth. A new offline inducer builds one compact local function packet per canonical Region, asks a text-only model to summarize business capabilities, and validates every returned Region/Operation/Transition reference. Task synthesis matches producer `outputs` to consumer `inputs`; the language model receives only framework-selected refs and parameters and may polish text but cannot change the selection.

**Tech Stack:** Python 3.10+, dataclasses/typing/json/hashlib, existing modular `exploration_ledger.json`, existing `predict_mm` model contract, pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-region-business-capability-design.md`

## Global Constraints

- Do not modify traversal runtime behavior or the saved Clock source artifact.
- Remove `skeleton/skNNN/start` from task generation; do not replace it with another template layer.
- Business capabilities may be incomplete and remain task-selectable through explicit `missing` facts.
- Do not require or synthesize a fixed ordered recipe.
- Every model-returned Region, Operation, State, Transition, input, and output reference must validate against the supplied local packet.
- Task design does not calculate route distance or execution order except explicit dependency order.
- Parameter values come only from observed/allowed values or caller-provided open-text fixtures; the polish model cannot invent values.
- This plan is offline: no VM/emulator and no changes to M13 live execution or augmented-graph writing.
- Preserve unrelated worktree changes and commit only task-owned paths.

## File Structure

- Create `gui_rewalk/src/core/scenario/region_business_capability.py`: schema, local Region packet construction, reference validation, stable IDs, load/save.
- Create `gui_rewalk/src/core/scenario/region_capability_induction.py`: text-only Prompt, model call, parse, and per-Region induction orchestration.
- Create `gui_rewalk/run_region_capability_induction.py`: offline CLI over `exploration_ledger.json`.
- Modify `gui_rewalk/src/core/scenario/capability_task_synthesis.py`: remove skeleton pagination, add object-dependent task synthesis and selected-ref polishing.
- Create `tests/test_region_business_capability.py`: deterministic packet/schema validation.
- Create `tests/test_region_capability_induction.py`: model boundary and CLI tests.
- Modify `tests/test_capability_task_synthesis.py`: object dependency and polish immutability tests.
- Modify `design/modules/capability_induction.md`, `design/CURRENT_FRAMEWORK.md`, and `design/changelog/2026-08.md`: current contract, new CLI/output, verification evidence.

---

### Task 1: Remove Skeleton Task Generation and Keep Only Selected-Ref Polishing

**Files:**
- Modify: `gui_rewalk/src/core/scenario/capability_task_synthesis.py`
- Modify: `tests/test_capability_task_synthesis.py`

**Interfaces:**
- Consumes: a capability graph, framework-selected task drafts, and an object exposing `predict_mm(prompt, images)`.
- Produces: `polish_selected_instructions(capability_graph, drafts, agent) -> List[Dict[str, Any]]`.

- [ ] **Step 1: Replace the skeleton tests with a failing selected-ref immutability test**

```python
def test_polisher_cannot_change_selected_capabilities_or_params() -> None:
    graph = _capability_graph()
    selected = [{
        "task_id": "task_alarm",
        "capability_refs": [{
            "capability_id": "create_alarm",
            "params": {"time": "08:30"},
        }],
    }]
    agent = _AgentReturning({
        "instructions": [{
            "task_id": "task_alarm",
            "instruction": "创建一个 8:30 的闹钟。",
            "capability_refs": [{"capability_id": "invented"}],
        }],
    })

    result = polish_selected_instructions(graph, selected, agent)

    assert result[0]["capability_refs"] == selected[0]["capability_refs"]
    assert "invented" not in agent.prompt
    assert "execution_recipe" not in agent.prompt
    assert "sk001" not in agent.prompt
```

- [ ] **Step 2: Run the test and confirm the old skeleton API fails the contract**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider tests/test_capability_task_synthesis.py -k "polisher_cannot"
```

Expected: FAIL because `polish_selected_instructions` is absent.

- [ ] **Step 3: Implement the minimal selected-ref polisher and delete skeleton code**

Remove `_instruction_skeletons`, `skNNN`, and the `start` argument. Keep compact card rendering only for refs already present in each draft.

```python
def polish_selected_instructions(
    capability_graph: Mapping[str, Any],
    drafts: Sequence[Mapping[str, Any]],
    agent: Any,
) -> List[Dict[str, Any]]:
    capabilities = _composition_capabilities(capability_graph)
    fixed = _validate_selected_drafts(drafts, capabilities)
    prompt_items = [
        _selected_draft_prompt_item(item, capabilities) for item in fixed
    ]
    response = _invoke_json(agent, _POLISH_PROMPT.format(
        drafts=json.dumps(prompt_items, ensure_ascii=False)))
    polished = {
        _text(item.get("task_id")): _text(item.get("instruction"))
        for item in response.get("instructions") or []
        if isinstance(item, Mapping)
    }
    return [
        {**copy.deepcopy(item), "instruction": polished[item["task_id"]]}
        for item in fixed if polished.get(item["task_id"])
    ]
```

The model response schema contains only `task_id` and `instruction`. Ignore any extra keys.

- [ ] **Step 4: Run the focused synthesis tests**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider tests/test_capability_task_synthesis.py
```

Expected: all tests pass and no test refers to skeleton IDs or `start` pagination.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- gui_rewalk/src/core/scenario/capability_task_synthesis.py tests/test_capability_task_synthesis.py
git diff --cached --check
git commit -m "Remove capability task skeletons"
```

---

### Task 2: Add the Region Business Capability Graph Contract

**Files:**
- Create: `gui_rewalk/src/core/scenario/region_business_capability.py`
- Create: `tests/test_region_business_capability.py`

**Interfaces:**
- Consumes: a loaded modular exploration ledger with `pages/states/regions/occurrences/operations/transitions`.
- Produces:
  - `REGION_BUSINESS_CAPABILITY_SCHEMA = "gui_rewalk.region_business_capability_graph.v1"`
  - `build_region_function_packets(ledger) -> List[Dict[str, Any]]`
  - `validate_region_business_capability_graph(payload, ledger) -> Dict[str, Any]`
  - `load_region_business_capability_graph(path) -> Dict[str, Any]`
  - `save_region_business_capability_graph(path, payload) -> None`

- [ ] **Step 1: Write failing packet tests using a minimal Clock-shaped ledger**

```python
def test_alarm_owner_packet_contains_same_page_function_closure() -> None:
    ledger = clock_alarm_ledger_fixture()

    packet = next(
        item for item in build_region_function_packets(ledger)
        if item["owner_region_ref"] == "r4"
    )

    assert packet["entry_operation_refs"] == ["o12"]
    assert {item["state_id"] for item in packet["states"]} == {
        "s2", "s17", "s18", "s19"}
    assert {item["operation_id"] for item in packet["operations"]} >= {
        "o12", "o104", "o105", "o106", "o107", "o108",
        "o109", "o110", "o111", "o112", "o113",
    }
    assert {item["transition_id"] for item in packet["transitions"]} >= {
        "e33", "e35"}
```

Add a second test proving shared Region `r1` yields one packet even with multiple occurrences.

- [ ] **Step 2: Run packet tests and confirm RED**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider tests/test_region_business_capability.py
```

Expected: collection error because the module/functions do not exist.

- [ ] **Step 3: Implement deterministic local packet construction**

Index the ledger once. For each canonical owner Region:

1. collect its occurrences and source States;
2. collect its Operations;
3. follow committed/verified Transitions triggered by those Operations;
4. continue through States on the same Page to form the local functional closure;
5. deduplicate canonical Regions and Operations while retaining exact IDs and visible results;
6. include `allowed_refs` sets for validation, but do not expose screenshots or full history.

```python
def build_region_function_packets(
    ledger: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    index = _LedgerIndex.from_mapping(ledger)
    return [
        _build_owner_packet(index, region_id)
        for region_id in sorted(index.regions, key=_numeric_ref_key)
    ]
```

The closure stops at a different Page. Cross-Page navigation remains routing structure, not part of a Region business capability packet.

- [ ] **Step 4: Write failing schema-validation tests**

```python
def test_validator_rejects_invented_operation_and_accepts_missing() -> None:
    ledger = clock_alarm_ledger_fixture()
    payload = business_graph_fixture()
    payload["capabilities"][0]["operation_refs"].append("o999")
    with pytest.raises(ValueError, match="o999"):
        validate_region_business_capability_graph(payload, ledger)

    payload = business_graph_fixture()
    payload["capabilities"][0]["missing"] = ["exact city selection operation"]
    validated = validate_region_business_capability_graph(payload, ledger)
    assert validated["capabilities"][0]["missing"]
```

- [ ] **Step 5: Implement schema validation and deterministic persistence**

Require each capability to contain:

```python
{
    "capability_id": "bc_a1b2c3d4",
    "name": "创建闹钟",
    "owner_region_ref": "r4",
    "entry_bindings": [{"state_id": "s2", "operation_ref": "o12"}],
    "operation_refs": ["o12", "o104"],
    "parameters": [],
    "inputs": [],
    "outputs": [],
    "expected_result": "",
    "missing": [],
    "evidence_refs": [],
}
```

The graph root also contains `schema_version`, `app_id`, `source_ledger_digest`, and
`capabilities`. Validate exact refs, unique capability IDs, input/output names,
and parameter source refs. Save JSON atomically and sort capabilities by stable ID.

- [ ] **Step 6: Run Task 2 tests and commit**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider tests/test_region_business_capability.py
```

Expected: all Task 2 tests pass.

```powershell
git add -- gui_rewalk/src/core/scenario/region_business_capability.py tests/test_region_business_capability.py
git diff --cached --check
git commit -m "Add Region business capability contract"
```

---

### Task 3: Add Text-Only Per-Region Capability Induction and CLI

**Files:**
- Create: `gui_rewalk/src/core/scenario/region_capability_induction.py`
- Create: `gui_rewalk/run_region_capability_induction.py`
- Create: `tests/test_region_capability_induction.py`

**Interfaces:**
- Consumes: `build_region_function_packets(ledger)` and an Agent with `predict_mm(prompt, [])`.
- Produces:
  - `RegionCapabilityInducer(agent).induce(ledger, region_refs=None) -> Dict[str, Any]`
  - CLI `python gui_rewalk/run_region_capability_induction.py --ledger ... --output ... --model-backend ... --model-version ...`.

- [ ] **Step 1: Write a failing exact-reference induction test**

```python
def test_inducer_builds_create_alarm_and_incomplete_add_world() -> None:
    ledger = clock_business_ledger_fixture()
    agent = RegionResponseAgent({
        "r4": [{
            "name": "创建闹钟",
            "entry_operation_refs": ["o12"],
            "operation_refs": [
                "o12", "o104", "o105", "o106", "o107", "o108",
                "o109", "o110", "o111", "o112"],
            "parameters": [
                {"name": "time", "source_operation_refs": [
                    "o105", "o106", "o107", "o108"]},
            ],
            "inputs": [],
            "outputs": [{
                "name": "alarm_item",
                "object_type": "alarm",
                "result_region_refs": ["r46"],
            }],
            "expected_result": "闹钟列表出现新闹钟条目",
            "missing": [],
            "evidence_refs": ["e33"],
        }],
        "r2": [{
            "name": "添加世界时钟",
            "entry_operation_refs": ["o6"],
            "operation_refs": ["o6", "o132", "o133"],
            "parameters": [{
                "name": "city", "value_source": "open_text_fixture",
                "source_operation_refs": ["o133"],
            }],
            "inputs": [], "outputs": [],
            "expected_result": "世界时钟列表出现对应城市卡片",
            "missing": ["城市文本输入", "结果选择", "成功 Add", "城市卡片绑定"],
            "evidence_refs": [],
        }],
        "r46": [{
            "name": "设置闹钟启用状态",
            "entry_operation_refs": ["o113"],
            "operation_refs": ["o113"],
            "parameters": [{
                "name": "enabled", "allowed_values": [False, True],
                "source_operation_refs": ["o113"],
            }],
            "inputs": [{
                "name": "target_alarm", "object_type": "alarm",
            }],
            "outputs": [],
            "expected_result": "目标闹钟启用状态与 enabled 一致",
            "missing": [],
            "evidence_refs": [],
        }],
    })

    graph = RegionCapabilityInducer(agent).induce(
        ledger, region_refs=["r4", "r2", "r46"])

    assert {item["name"] for item in graph["capabilities"]} == {
        "创建闹钟", "添加世界时钟", "设置闹钟启用状态"}
    assert agent.image_counts == [0, 0, 0]
```

- [ ] **Step 2: Run the induction test and confirm RED**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider tests/test_region_capability_induction.py -k "builds_create_alarm"
```

Expected: FAIL because `RegionCapabilityInducer` is absent.

- [ ] **Step 3: Implement the minimal Prompt and induction loop**

The system text defines a business capability as a user-meaningful goal, excludes navigation/open/close as standalone capabilities, allows `missing`, and requires exact refs. The user message contains one packet as compact JSON.

```python
class RegionCapabilityInducer:
    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def induce(
        self,
        ledger: Mapping[str, Any],
        *,
        region_refs: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        packets = build_region_function_packets(ledger)
        chosen = set(region_refs or [p["owner_region_ref"] for p in packets])
        raw_capabilities = []
        for packet in packets:
            if packet["owner_region_ref"] not in chosen:
                continue
            raw_capabilities.extend(self._invoke(packet))
        payload = _assemble_graph(ledger, raw_capabilities)
        return validate_region_business_capability_graph(payload, ledger)
```

Compute `capability_id` in framework code from normalized name, owner Region, sorted entry refs, and sorted input/output object types. Do not accept a model-provided ID.

- [ ] **Step 4: Add rejection tests for invented refs and output bindings**

Test that an invented `o999`, an output Region outside the packet, duplicate input names, and an output claiming a nonexistent `r999` each reject the whole Region response without partially writing a capability.

- [ ] **Step 5: Implement the offline CLI**

Arguments:

```text
--ledger PATH                         required
--output PATH                         required and must differ from ledger
--region-ref REGION                   repeatable; omitted means all Regions
--model-backend codex_cli|qwen_api    required
--model-version MODEL                 required
--output-root PATH                    required for model diagnostics
```

For `codex_cli`, instantiate `CodexGUIGenAgent`; it accepts zero images. For `qwen_api`, reuse `GUIGenAgent`. Do not read or write API credentials in source or output.

- [ ] **Step 6: Add a CLI test with a patched agent factory**

Write a temporary ledger, patch `_build_agent` to return `RegionResponseAgent`, call `main([...])`, and assert output schema, source ledger digest, capabilities, and that the ledger bytes are unchanged.

- [ ] **Step 7: Run Task 3 tests and commit**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider tests/test_region_business_capability.py tests/test_region_capability_induction.py
```

Expected: all Task 2–3 tests pass.

```powershell
git add -- gui_rewalk/src/core/scenario/region_capability_induction.py gui_rewalk/run_region_capability_induction.py tests/test_region_capability_induction.py
git diff --cached --check
git commit -m "Add offline Region capability induction"
```

---

### Task 4: Generate Object-Dependent Multi-Stage Instructions

**Files:**
- Modify: `gui_rewalk/src/core/scenario/capability_task_synthesis.py`
- Modify: `tests/test_capability_task_synthesis.py`

**Interfaces:**
- Consumes: validated Region business capability graph and explicit parameter fixtures.
- Produces: `synthesize_object_dependent_tasks(graph, parameter_fixtures) -> List[Dict[str, Any]]`.

- [ ] **Step 1: Write the failing create-then-disable test**

```python
def test_synthesis_binds_new_alarm_output_to_disable_input() -> None:
    graph = region_business_graph_with_create_and_set_enabled()

    tasks = synthesize_object_dependent_tasks(graph, {
        "bc_create_alarm": {"time": "08:30", "repeat": "weekdays"},
        "bc_set_alarm_enabled": {"enabled": False},
    })

    task = tasks[0]
    create, disable = task["capability_refs"]
    assert create["capability_id"] == "bc_create_alarm"
    assert disable["capability_id"] == "bc_set_alarm_enabled"
    assert disable["depends_on"] == [create["ref_id"]]
    assert disable["input_bindings"] == {
        "target_alarm": {
            "from_ref": create["ref_id"],
            "output": "alarm_item",
        },
    }
    assert task["fixed_order"] is False
```

- [ ] **Step 2: Run the test and confirm RED**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider tests/test_capability_task_synthesis.py -k "binds_new_alarm"
```

Expected: FAIL because object-dependent synthesis is absent.

- [ ] **Step 3: Implement output-to-input matching**

Build producer/consumer pairs only when `object_type` matches uniquely. Reject ambiguous multiple producers, missing required parameter fixtures, direct expected-result conflicts, and cyclic dependencies.

```python
def _bind_consumer_input(
    producer_ref: Mapping[str, Any],
    producer_output: Mapping[str, Any],
    consumer_ref: MutableMapping[str, Any],
    consumer_input: Mapping[str, Any],
) -> None:
    consumer_ref.setdefault("depends_on", []).append(producer_ref["ref_id"])
    consumer_ref.setdefault("input_bindings", {})[consumer_input["name"]] = {
        "from_ref": producer_ref["ref_id"],
        "output": producer_output["name"],
    }
```

The task list order is presentation order only; dependency edges are authoritative. Leave `fixed_order=False`.

- [ ] **Step 4: Add polish-model immutability to the dependent task**

Feed the selected refs and bindings to `polish_selected_instructions`. The fake model returns the Chinese command plus invented refs; assert the natural text is accepted and all refs/bindings remain byte-for-byte framework-owned.

- [ ] **Step 5: Run synthesis regressions and commit**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider tests/test_capability_task_synthesis.py tests/test_region_business_capability.py tests/test_region_capability_induction.py
```

Expected: all offline capability/task tests pass.

```powershell
git add -- gui_rewalk/src/core/scenario/capability_task_synthesis.py tests/test_capability_task_synthesis.py
git diff --cached --check
git commit -m "Generate object-dependent capability tasks"
```

---

### Task 5: Run the Saved-Clock Offline Probe and Document the Current Contract

**Files:**
- Modify: `design/modules/capability_induction.md`
- Modify: `design/CURRENT_FRAMEWORK.md`
- Modify: `design/changelog/2026-08.md`
- Runtime artifact only: `artifacts/region_business_capability_clock_probe_20260826/`

**Interfaces:**
- Consumes: `artifacts/completed_traversal_graphs/desktop/clocks/exploration_ledger.json`.
- Produces: read-only probe `region_business_capability_graph.json` and one generated dependent-task JSON; no source artifact mutation.

- [ ] **Step 1: Run static and focused offline verification**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m pytest -q --tb=short -p no:cacheprovider tests/test_region_business_capability.py tests/test_region_capability_induction.py tests/test_capability_task_synthesis.py tests/test_capability_desired_outcome.py --basetemp C:\Users\Admin\AppData\Local\Temp\codex_region_capability_final_20260826
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe -m py_compile gui_rewalk/src/core/scenario/region_business_capability.py gui_rewalk/src/core/scenario/region_capability_induction.py gui_rewalk/src/core/scenario/capability_task_synthesis.py gui_rewalk/run_region_capability_induction.py
```

Expected: all listed tests pass and `py_compile` exits 0.

- [ ] **Step 2: Run a three-Region Luna text-only probe**

Run:

```powershell
C:\Users\Admin\miniconda3\envs\guiwalk\python.exe gui_rewalk/run_region_capability_induction.py --ledger artifacts/completed_traversal_graphs/desktop/clocks/exploration_ledger.json --output artifacts/region_business_capability_clock_probe_20260826/region_business_capability_graph.json --region-ref r4 --region-ref r2 --region-ref r46 --model-backend codex_cli --model-version gpt-5.6-luna --output-root artifacts/region_business_capability_clock_probe_20260826
```

Expected structural output:

- `创建闹钟` owner `r4`, entry `o12`, output `alarm_item -> r46`, no false skeleton IDs;
- `添加世界时钟` owner `r2`, entry `o6`, non-empty `missing` for input/select/Add/result;
- `设置闹钟启用状态` owner `r46`, entry `o113`, input object type `alarm`;
- every Region/Operation/Transition ref validates against the saved ledger;
- no screenshots, VM, emulator, or Qwen call.

If Luna returns a semantically weak name but valid refs, adjust only the Region inducer Prompt and add the exact saved response as a model fixture; do not add Clock string rules to framework validation.

- [ ] **Step 3: Generate and inspect the dependent Clock instruction**

Resolve the unique generated IDs by exact capability name, then pass fixtures keyed by
those framework IDs:

```python
by_name = {item["name"]: item for item in graph["capabilities"]}
fixtures = {
    by_name["创建闹钟"]["capability_id"]: {
        "time": "08:30", "repeat": "weekdays"},
    by_name["设置闹钟启用状态"]["capability_id"]: {
        "enabled": False},
}
tasks = synthesize_object_dependent_tasks(graph, fixtures)
```

Expected command meaning: create an 8:30 weekday alarm, then disable the alarm just created. Confirm refs express `create -> disable`, and the consumer input points to producer output `alarm_item`.

- [ ] **Step 4: Update current-state documentation**

Document:

- the new CLI and output schema;
- Region-local text-only induction;
- incomplete capability eligibility;
- object `inputs/outputs` and dependency synthesis;
- the fact that live M13 still cannot execute incomplete capabilities or cross-ref object bindings until the separate live-collection plan is implemented;
- exact offline test commands and Luna probe outcome, without calling them VM/live collection validation.

- [ ] **Step 5: Inspect diffs and commit Task 5**

```powershell
git diff --check
git add -- design/modules/capability_induction.md design/CURRENT_FRAMEWORK.md design/changelog/2026-08.md
git diff --cached --check
git commit -m "Document Region capability induction"
```

Do not commit the runtime probe artifact unless the user separately requests it as a retained research artifact.

## Plan Completion Gate

Before claiming this plan complete:

1. `skeleton`, `skNNN`, and task-generation `start` are absent from the active task-polish contract.
2. The saved Clock ledger produces one closed `创建闹钟` capability and one incomplete `添加世界时钟` capability with exact refs.
3. The generated create-then-disable task has a producer/consumer object binding and explicit dependency.
4. The polish model cannot change capability refs, params, dependency, or input binding.
5. Source Clock ledger bytes remain unchanged.
6. No VM/emulator is started; model probe evidence is reported as text-only offline evidence.
7. Existing unrelated `live_state_locator.py` worktree changes remain unstaged.

## Deferred Follow-Up Plan

After reviewing the offline Clock output, write a separate implementation plan for:

- allowing incomplete capabilities through M13 hydration;
- adaptive capability-goal execution over live screenshots;
- persisting producer output Region bindings across capability refs;
- registering newly discovered State/Region/Operation/Transition facts into an augmented graph without overwriting the source traversal run.
