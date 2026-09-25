"""Offline contracts for the screenshot-only visual collection executor.

No VM, model, network, screenshot decoder, or filesystem fixture is used.  The
fake adapters expose opaque observations and deterministic visual identities.
"""

from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import networkx as nx


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.src.core.scenario.visual_collection_executor import (
    CapabilityExecutionRef,
    VLMCollectionWorkflowAgent,
    VLMCompletionVerifier,
    VisualCollectionExecutor,
)


class _Adapter:
    def __init__(
        self,
        app_id: str,
        node: str,
        transitions: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.app_id = app_id
        self.current_node = node
        self.transitions: Dict[str, deque[str]] = {}
        for action, destinations in (transitions or {}).items():
            if isinstance(destinations, str):
                destinations = [destinations]
            self.transitions[action] = deque(destinations)
        self.activations = 0
        self.grounded: list[str] = []
        self.workflow_grounded: list[str] = []
        self.capability_params: list[Dict[str, Any]] = []
        self.capability_refs: list[Dict[str, Any]] = []
        self.executed: list[str] = []
        self.calls: list[str] = []

    def activate(self) -> None:
        self.activations += 1
        self.calls.append("activate")

    def capture(self) -> Dict[str, str]:
        self.calls.append("capture")
        return {
            "app_id": self.app_id,
            "node": self.current_node,
            "frame": f"{self.app_id}:{self.current_node}:{len(self.calls)}",
        }

    def identify(self, observation: Mapping[str, str]) -> str:
        self.calls.append("identify")
        return observation["node"]

    def ground(self, action_spec: Mapping[str, Any], _observation: Any) -> Any:
        self.calls.append("ground")
        if action_spec["kind"] == "graph_edge":
            action = action_spec["edge"].get("action")
        else:
            action = action_spec["capability_ref"].get("action") or action_spec["ref_id"]
            self.capability_params.append(dict(action_spec["capability_ref"].get("params") or {}))
            self.capability_refs.append(dict(action_spec["capability_ref"]))
        if not action:
            return None
        self.grounded.append(str(action))
        return {"action": str(action)}

    def execute(self, grounded_action: Mapping[str, str]) -> None:
        self.calls.append("execute")
        action = grounded_action["action"]
        self.executed.append(action)
        destinations = self.transitions.get(action)
        if destinations:
            self.current_node = destinations[0]
            if len(destinations) > 1:
                destinations.popleft()

    def ground_workflow_click(
        self, target: str, decision: Mapping[str, Any], _observation: Any,
    ) -> Any:
        click = decision.get("next_click") or {}
        if click.get("target") != target:
            return None
        self.workflow_grounded.append(target)
        return {"action": f"click {target}"}

    def settle(self, _execution_result: Any = None) -> None:
        self.calls.append("settle")


class _Verifier:
    def __init__(self, failed_refs: Iterable[str] = (), final: bool = True) -> None:
        self.failed_refs = set(failed_refs)
        self.final = final
        self.ref_order: list[str] = []
        self.final_calls = 0

    def verify_ref(self, ref, _before, _after, _context):
        self.ref_order.append(ref["ref_id"])
        return {
            "complete": ref["ref_id"] not in self.failed_refs,
            "reason": "fake semantic verdict",
        }

    def verify_final(self, _instruction, _observation, _context):
        self.final_calls += 1
        return {"complete": self.final, "reason": "fake final verdict"}


class _WorkflowAgent:
    def __init__(self) -> None:
        self.calls = []

    def confirm(self, **request):
        self.calls.append(request)
        result = {
            "matches_expected": True,
            "previous_action": "success",
            "reason": "The screenshot agrees with the predicted graph State.",
        }
        if request.get("next_target"):
            result["next_click"] = {
                "target": request["next_target"],
                "bbox_1000": [100, 100, 300, 200],
                "click_point_1000": [200, 150],
            }
        else:
            result["next_click"] = None
        return result


class _WorkflowTransport:
    def __init__(self) -> None:
        self.calls = []

    def predict_mm_with_policy(
        self, user_prompt, images, *, max_attempts,
        timeout_seconds, system_prompt,
    ):
        self.calls.append({
            "user_prompt": user_prompt,
            "images": images,
            "max_attempts": max_attempts,
            "timeout_seconds": timeout_seconds,
            "system_prompt": system_prompt,
        })
        return json.dumps({
            "matches_expected": True,
            "previous_action": "success",
            "reason": "Stopwatch shows Start and Lap with no menu.",
            "next_click": {
                "target": "Start",
                "bbox_1000": [400, 500, 500, 600],
                "click_point_1000": [450, 550],
            },
        }), 10, 5, 1

    @staticmethod
    def parse_json(raw):
        return json.loads(raw)


def test_workflow_agent_receives_compact_natural_language_not_state_schema():
    transport = _WorkflowTransport()
    agent = VLMCollectionWorkflowAgent(transport, timeout=45)

    result = agent.confirm(
        screenshot=b"frame",
        expected_state=(
            "s3，Stopwatch 页面；Main Content Area 有 "
            "Start button、Lap button"),
        previous_action="从 s2 点击 Stopwatch，预计到达 s3。",
        remaining_route=(
            "1. 点击 Start，预计到达 s11，Stopwatch 页面；"
            "Main Content Area 有 Pause button、Lap button。"),
        recent_steps=["从 s1 点击 Alarms，已到达 s2。"],
        next_target="Start",
    )

    assert result["matches_expected"] is True
    call = transport.calls[0]
    assert call["images"] == [b"frame"]
    assert call["max_attempts"] == 1
    assert call["timeout_seconds"] == 45
    assert "框架预计当前位置：\ns3，Stopwatch 页面" in call["user_prompt"]
    assert "最近操作：\n- 从 s1 点击 Alarms，已到达 s2。" in \
        call["user_prompt"]
    assert "后续路线：\n1. 点击 Start" in call["user_prompt"]
    assert "expected_state" not in call["user_prompt"]
    assert "visible_regions" not in call["user_prompt"]
    assert result["next_click"]["target"] == "Start"


class _OutcomeVerifier(_Verifier):
    def __init__(self, observed_outcome: Any) -> None:
        super().__init__()
        self.observed_outcome = observed_outcome

    def verify_ref(self, ref, _before, _after, _context):
        self.ref_order.append(ref["ref_id"])
        return {
            "complete": True,
            "observed_outcome": self.observed_outcome,
            "changed": True,
            "reason": "fake directional verdict",
        }


def _graph(*edges: tuple[str, str, str, int]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for source, target, action, action_steps in edges:
        graph.add_edge(
            source,
            target,
            action=action,
            element_label=action,
            action_steps=action_steps,
        )
    return graph


def _ref(
    ref_id: str,
    app_id: str,
    node_id: str,
    *,
    action: Optional[str] = None,
    target_node: Optional[str] = None,
    requires=None,
    depends_on=None,
    action_steps: int = 1,
    desired_outcome: Any = None,
    params: Optional[Mapping[str, Any]] = None,
    output_slot: str = "",
) -> Dict[str, Any]:
    value = {
        "ref_id": ref_id,
        "name": ref_id,
        "app_id": app_id,
        "node_id": node_id,
        "target_node": target_node or node_id,
        "action": action or f"do_{ref_id}",
        "requires": requires or [],
        "depends_on": depends_on or [],
        "params": dict(params) if params is not None else {"value": ref_id},
        "action_steps": action_steps,
    }
    if desired_outcome is not None:
        value["desired_outcome"] = desired_outcome
    if output_slot:
        value["output_slot"] = output_slot
    return value


class _RuntimeVerifier(_Verifier):
    def __init__(self, query_results: Mapping[str, Any]) -> None:
        super().__init__()
        self.query_results = dict(query_results)

    def verify_ref(self, ref, _before, _after, _context):
        self.ref_order.append(ref["ref_id"])
        verdict = {
            "complete": True,
            "reason": "fake runtime query verdict",
        }
        if ref["ref_id"] in self.query_results:
            verdict["query_result"] = self.query_results[ref["ref_id"]]
        return verdict


def test_verified_scalar_query_result_binds_dependent_runtime_param() -> None:
    adapter = _Adapter("app", "page", {"read": "page", "use": "page"})
    verifier = _RuntimeVerifier({"read": "selected item"})
    result = VisualCollectionExecutor(
        {"app": _graph()}, {"app": adapter}, verifier,
    ).execute(
        {
            "instruction": "read then use the selected item",
            "capability_refs": [
                _ref("read", "app", "page", action="read", output_slot="item"),
                _ref(
                    "use", "app", "page", action="use", depends_on=["read"],
                    params={"value": {"from_slot": "item"}},
                ),
            ],
        },
        initial_app_id="app",
    )

    assert result["success"] is True
    assert result["blackboard"]["item"] == "selected item"
    assert result["ref_results"][0]["verification"]["query_result"] == "selected item"
    assert result["trajectory"][0]["verification"]["query_result"] == "selected item"
    assert adapter.capability_params == [{"value": "read"}, {"value": "selected item"}]


def test_output_slot_rejects_missing_or_non_scalar_query_result() -> None:
    for query_results in ({}, {"read": ["not", "scalar"]}):
        adapter = _Adapter("app", "page", {"read": "page"})
        result = VisualCollectionExecutor(
            {"app": _graph()}, {"app": adapter},
            _RuntimeVerifier(query_results),
        ).execute(
            {
                "instruction": "read a runtime value",
                "capability_refs": [
                    _ref("read", "app", "page", action="read", output_slot="item"),
                ],
            },
            initial_app_id="app",
        )

        assert result["success"] is False
        assert result["ref_results"][0]["status"] == "ref_verification_failed"
        assert result["ref_results"][0]["committed"] is False
        assert result["trajectory"][0]["committed"] is False
        assert "item" not in result["blackboard"]


def test_runtime_binding_missing_slot_and_type_mismatch_fail_before_target_action() -> None:
    adapter = _Adapter("app", "page", {"read": "page", "use": "page"})
    source = _ref("read", "app", "page", action="read", output_slot="item")
    source["runtime_param_types"] = {"value": "string"}
    target = _ref(
        "use", "app", "page", action="use", depends_on=["read"],
        params={"value": {"from_slot": "item"}},
    )
    target["runtime_param_types"] = {"value": "string"}
    executor = VisualCollectionExecutor(
        {"app": _graph()}, {"app": adapter}, _RuntimeVerifier({"read": 7}),
    )
    result = executor.execute(
        {"instruction": "use runtime item", "capability_refs": [source, target]},
        initial_app_id="app",
    )

    assert adapter.executed == ["read"]
    assert result["ref_results"][1]["status"] == "runtime_binding_failed"
    assert result["ref_results"][1]["committed"] is False
    assert adapter.capability_params == [{"value": "read"}]

    executor._reset_run_state()
    missing = executor._bind_runtime_ref(
        CapabilityExecutionRef.from_mapping(target, 0)
    )
    assert missing[0] is None
    assert missing[1] == "runtime slot 'item' is missing"
    assert adapter.executed == ["read"]


def test_runtime_slot_contract_rejects_missing_dependency_and_malformed_tokens() -> None:
    cases = [
        _ref(
            "use", "app", "page", depends_on=[],
            params={"value": {"from_slot": "item"}},
        ),
        _ref(
            "use", "app", "page", depends_on=["read"],
            params={"value": {"from_slot": "item", "extra": True}},
        ),
        _ref(
            "use", "app", "page", depends_on=["read"],
            params={"value": {"from_slot": ""}},
        ),
    ]
    for target in cases:
        adapter = _Adapter("app", "page", {"read": "page", "use": "page"})
        source = _ref("read", "app", "page", action="read", output_slot="item")
        result = VisualCollectionExecutor(
            {"app": _graph()}, {"app": adapter}, _RuntimeVerifier({"read": "ok"}),
        ).execute(
            {"instruction": "invalid runtime contract", "capability_refs": [source, target]},
            initial_app_id="app",
        )

        assert result["final_status"] == "invalid_instruction"
        assert adapter.executed == []


def test_output_slot_vlm_prompt_requires_query_result() -> None:
    class _Agent:
        def __init__(self) -> None:
            self.prompt = ""

        def predict_mm(self, prompt, _images):
            self.prompt = prompt
            return '{"complete": true, "reason": "visible", "query_result": "x"}'

    agent = _Agent()
    verdict = VLMCompletionVerifier(agent).verify_ref(
        {"ref_id": "read", "output_slot": "item"}, "before", "after", {},
    )

    assert verdict["query_result"] == "x"
    assert '"query_result"' in agent.prompt


def test_output_slot_forces_ref_verifier_instead_of_workflow_effect_shortcut() -> None:
    graph = _graph()
    graph.add_node("page")
    adapter = _Adapter("app", "page", {"read": "page"})
    verifier = _RuntimeVerifier({"read": "visible query value"})
    ref = _ref("read", "app", "page", action="read", output_slot="item")
    ref["target_node"] = ""
    ref["verification_level"] = "effect_verified"
    ref["risk_level"] = "normal"
    ref["effects"] = [{
        "kind": "state_change",
        "changes": [{"scope": {"state_id": "page"}}],
    }]

    result = VisualCollectionExecutor(
        {"app": graph}, {"app": adapter}, verifier,
        workflow_agent=_WorkflowAgent(),
    ).execute(
        {"instruction": "read query value", "capability_refs": [ref]},
        initial_app_id="app",
    )

    assert result["success"] is True
    assert verifier.ref_order == ["read"]
    assert result["blackboard"]["item"] == "visible query value"


def test_ordinary_structured_params_remain_capability_authority_values() -> None:
    structured = {
        "selection": {"labels": ["one", "two"], "match": "exact"},
        "flags": ["keep", {"visible": True}],
    }
    adapter = _Adapter("app", "page", {"use": "page"})
    result = VisualCollectionExecutor(
        {"app": _graph()}, {"app": adapter}, _Verifier(),
    ).execute(
        {
            "instruction": "use the prevalidated structured parameters",
            "capability_refs": [
                _ref("use", "app", "page", action="use", params=structured),
            ],
        },
        initial_app_id="app",
    )

    assert result["success"] is True
    assert adapter.capability_params == [structured]


def test_manual_output_slot_must_be_stable_ascii_name() -> None:
    adapter = _Adapter("app", "page", {"read": "page"})
    result = VisualCollectionExecutor(
        {"app": _graph()}, {"app": adapter}, _RuntimeVerifier({"read": "x"}),
    ).execute(
        {
            "instruction": "read a value",
            "capability_refs": [
                _ref("read", "app", "page", action="read", output_slot="Bad-Slot"),
            ],
        },
        initial_app_id="app",
    )

    assert result["final_status"] == "invalid_instruction"
    assert adapter.executed == []


def test_bound_runtime_param_replaces_raw_value_and_runtime_metadata() -> None:
    adapter = _Adapter("app", "page", {"read": "page", "use": "page"})
    target = _ref(
        "use", "app", "page", action="use", depends_on=["read"],
        params={"text": {"from_slot": "item"}},
    )
    target.update({"slot": "text", "value": "<runtime>", "runtime": True})
    result = VisualCollectionExecutor(
        {"app": _graph()}, {"app": adapter},
        _RuntimeVerifier({"read": "selected text"}),
    ).execute(
        {
            "instruction": "read then use a value",
            "capability_refs": [
                _ref("read", "app", "page", action="read", output_slot="item"),
                target,
            ],
        },
        initial_app_id="app",
    )

    assert result["success"] is True
    bound = adapter.capability_refs[1]
    assert bound["params"] == {"text": "selected text"}
    assert bound["value"] == "selected text"
    assert bound["runtime"] is False


def test_precondition_cannot_overwrite_reserved_query_output_slot() -> None:
    adapter = _Adapter(
        "app", "page", {"read": "page", "middle": "page", "use": "page"},
    )

    def resolver(_requirement, ref, _context):
        if ref["ref_id"] == "middle":
            return {"satisfied": True, "bindings": {"item": "B"}}
        return {"satisfied": True}

    result = VisualCollectionExecutor(
        {"app": _graph()}, {"app": adapter}, _RuntimeVerifier({"read": "A"}),
        precondition_resolver=resolver,
    ).execute(
        {
            "instruction": "read then use the query value",
            "capability_refs": [
                _ref("read", "app", "page", action="read", output_slot="item"),
                _ref(
                    "middle", "app", "page", action="middle", requires=["setup"],
                    depends_on=["read"],
                ),
                _ref(
                    "use", "app", "page", action="use", depends_on=["read", "middle"],
                    params={"value": {"from_slot": "item"}},
                ),
            ],
        },
        initial_app_id="app",
    )

    assert adapter.executed == ["read"]
    assert result["blackboard"]["item"] == "A"
    assert result["ref_results"][1]["status"] == "skipped_precondition"
    assert result["ref_results"][1]["reason"] == "precondition attempted reserved query slot 'item'"
    assert result["ref_results"][2]["status"] == "not_attempted"


def test_reserved_slot_collision_retains_reported_precondition_action_evidence() -> None:
    adapter = _Adapter(
        "app", "page", {"read": "page", "middle": "page", "use": "page"},
    )

    def resolver(_requirement, ref, _context):
        if ref["ref_id"] == "middle":
            return {
                "satisfied": True,
                "bindings": {"item": "B"},
                "action_steps": 1,
                "action_events": [{
                    "action_id": "setup_click",
                    "action_spec": {"action_type": "CLICK"},
                    "action_steps": 1,
                    "committed": True,
                }],
            }
        return {"satisfied": True}

    result = VisualCollectionExecutor(
        {"app": _graph()}, {"app": adapter}, _RuntimeVerifier({"read": "A"}),
        precondition_resolver=resolver,
    ).execute(
        {
            "instruction": "read, set up, then use the query value",
            "capability_refs": [
                _ref("read", "app", "page", action="read", output_slot="item"),
                _ref(
                    "middle", "app", "page", action="middle", requires=["setup"],
                    depends_on=["read"],
                ),
                _ref(
                    "use", "app", "page", action="use", depends_on=["read", "middle"],
                    params={"value": {"from_slot": "item"}},
                ),
            ],
        },
        initial_app_id="app",
    )

    assert adapter.executed == ["read"]
    assert result["blackboard"]["item"] == "A"
    assert result["ref_results"][1]["status"] == "skipped_precondition"
    assert result["total_action_steps"] == 2
    assert result["trajectory"][-1]["kind"] == "precondition"
    assert result["trajectory"][-1]["action_id"] == "setup_click"
    assert result["trajectory"][-1]["action_steps"] == 1


def test_precondition_keeps_nonreserved_bindings() -> None:
    adapter = _Adapter("app", "page", {"use": "page"})
    result = VisualCollectionExecutor(
        {"app": _graph()}, {"app": adapter}, _Verifier(),
        precondition_resolver=lambda *_args: {
            "satisfied": True, "bindings": {"session": "ordinary"},
        },
    ).execute(
        {
            "instruction": "use ordinary precondition binding",
            "capability_refs": [
                _ref("use", "app", "page", action="use", requires=["setup"]),
            ],
        },
        initial_app_id="app",
    )

    assert result["success"] is True
    assert result["blackboard"]["session"] == "ordinary"
    assert adapter.executed == ["use"]


def test_directional_outcome_is_recorded_and_audited() -> None:
    adapter = _Adapter("app", "page", {"toggle": "page"})
    executor = VisualCollectionExecutor(
        {"app": _graph()}, {"app": adapter}, _OutcomeVerifier(True)
    )

    result = executor.execute(
        {
            "instruction": "enable the setting",
            "capability_refs": [
                _ref(
                    "toggle",
                    "app",
                    "page",
                    action="toggle",
                    desired_outcome=True,
                )
            ],
        },
        initial_app_id="app",
    )

    assert result["success"] is True
    assert result["agent_audit"]["agent_failure"] is False
    step = result["trajectory"][0]
    assert step["effect"] == {
        "desired_outcome": True,
        "observed_outcome": True,
        "had_effect": True,
    }
    assert step["verification"]["outcome_match"] is True


def test_directional_outcome_keeps_explicit_verifier_with_workflow_agent() -> None:
    adapter = _Adapter("app", "page", {"toggle": "page"})
    graph = _graph()
    graph.add_node(
        "page", page_name="Setting",
        semantic_blocks=[{
            "role": "Main Content Area", "element_names": ["Toggle"]}])
    verifier = _OutcomeVerifier(True)
    executor = VisualCollectionExecutor(
        {"app": graph}, {"app": adapter}, verifier,
        workflow_agent=_WorkflowAgent())
    ref = _ref(
        "toggle", "app", "page", action="toggle", desired_outcome=True)
    ref["target_node"] = ""
    ref["verification_level"] = "effect_verified"
    ref["risk_level"] = "normal"
    ref["effects"] = [{
        "kind": "state_change",
        "changes": [{
            "fact": "visible_state",
            "scope": {"state_id": "page"},
            "value": "page",
        }],
    }]

    result = executor.execute(
        {"instruction": "toggle", "capability_refs": [ref]},
        initial_app_id="app",
    )

    assert result["success"] is True
    assert verifier.ref_order == ["toggle"]
    assert verifier.final_calls == 1
    assert result["trajectory"][0]["effect"]["observed_outcome"] is True

def test_blank_target_uses_effect_verification_for_variant_landing() -> None:
    adapter = _Adapter("app", "before", {"save": "after"})
    graph = _graph()
    graph.add_nodes_from(["before", "after"])
    executor = VisualCollectionExecutor(
        {"app": graph}, {"app": adapter}, _Verifier()
    )
    ref = _ref("save", "app", "before", action="save")
    ref["target_node"] = ""

    result = executor.execute(
        {"instruction": "save the change", "capability_refs": [ref]},
        initial_app_id="app",
    )

    assert result["success"] is True
    assert result["ref_results"][0]["arrived_node"] == "after"


def test_capability_routes_to_the_nearest_recorded_entry_surface() -> None:
    graph = _graph(
        ("root", "near", "go_near", 1),
        ("root", "middle", "go_middle", 1),
        ("middle", "far", "go_far", 1),
    )
    adapter = _Adapter("app", "root", {
        "go_near": "near",
        "go_middle": "middle",
        "go_far": "far",
        "do_start": "near",
    })
    executor = VisualCollectionExecutor(
        {"app": graph}, {"app": adapter}, _Verifier())
    ref = _ref("start", "app", "far", action="do_start")
    ref["target_node"] = ""
    ref["entry_surfaces"] = [
        {"state_id": "far"},
        {"state_id": "near"},
    ]

    result = executor.execute(
        {"instruction": "start", "capability_refs": [ref]},
        initial_app_id="app",
    )

    assert result["success"] is True
    assert adapter.executed == ["go_near", "do_start"]
    assert result["ref_results"][0]["entry_node"] == "near"
    assert result["trajectory"][-1]["action_spec"][
        "capability_ref"]["node_id"] == "near"


def test_workflow_agent_confirms_predicted_states_with_natural_route_context():
    graph = _graph(
        ("s1", "s2", "click Alarms", 1),
        ("s2", "s3", "click Stopwatch", 1),
    )
    graph.add_node("s11")
    graph.nodes["s1"].update(
        page_name="World",
        semantic_blocks=[{
            "role": "Main Content Area",
            "element_names": ["Add World Clock button"],
        }],
    )
    graph.nodes["s2"].update(
        page_name="Alarms",
        semantic_blocks=[{
            "role": "Main Content Area",
            "element_names": ["Add Alarm button"],
        }],
    )
    graph.nodes["s3"].update(
        page_name="Stopwatch",
        semantic_blocks=[{
            "role": "Main Content Area",
            "element_names": ["Start button", "Lap button"],
        }],
    )
    graph.nodes["s11"].update(
        page_name="Stopwatch",
        semantic_blocks=[{
            "role": "Main Content Area",
            "element_names": ["Pause button", "Lap button"],
        }],
    )
    adapter = _Adapter("clock", "s1", {
        "click Alarms": "s2",
        "click Stopwatch": "s3",
        "click Start": "s11",
    })
    verifier = _Verifier()
    workflow = _WorkflowAgent()
    executor = VisualCollectionExecutor(
        {"clock": graph},
        {"clock": adapter},
        verifier,
        workflow_agent=workflow,
    )
    ref = _ref("start", "clock", "s3", action="click Start")
    ref["target_node"] = ""
    ref["verification_level"] = "effect_verified"
    ref["risk_level"] = "normal"
    ref["effects"] = [{
        "kind": "state_change",
        "changes": [{
            "fact": "visible_state",
            "scope": {"page_id": "p3", "state_id": "s11"},
            "value": "s11",
        }],
    }]

    result = executor.execute(
        {"instruction": "start the stopwatch", "capability_refs": [ref]},
        initial_app_id="clock",
    )

    assert result["success"] is True
    assert adapter.executed == [
        "click Alarms", "click Stopwatch", "click Start"]
    assert adapter.grounded == ["click Alarms"]
    assert adapter.workflow_grounded == ["Stopwatch", "Start"]
    assert adapter.calls.count("identify") == 1
    assert len(workflow.calls) == 3
    assert "s2，Alarms 页面；Main Content Area 有 Add Alarm button" in \
        workflow.calls[0]["expected_state"]
    assert "点击 Stopwatch，预计到达 s3，Stopwatch 页面；" in \
        workflow.calls[0]["remaining_route"]
    assert "Start button、Lap button" in workflow.calls[0]["remaining_route"]
    assert workflow.calls[1]["recent_steps"] == [
        "从 s1 点击 Alarms，已到达 s2。"]
    assert workflow.calls[2]["remaining_route"] == "没有后续动作。"
    assert verifier.ref_order == []
    assert verifier.final_calls == 0


def test_workflow_mismatch_falls_back_to_full_live_identity():
    class _MismatchWorkflow:
        def confirm(self, **_request):
            return {
                "matches_expected": False,
                "previous_action": "unexpected",
                "reason": "An unexpected dialog is in the foreground.",
                "next_click": None,
            }

    graph = _graph(("s1", "s2", "go expected", 1))
    graph.add_node("sx")
    adapter = _Adapter("app", "s1", {"go expected": "sx"})
    executor = VisualCollectionExecutor(
        {"app": graph}, {"app": adapter}, _Verifier(),
        workflow_agent=_MismatchWorkflow())
    executor._current_app = "app"
    executor._nodes["app"] = "s1"
    executor._workflow_confirmed_nodes["app"] = "s1"

    step = executor._perform_action(
        "app",
        {
            "kind": "graph_edge",
            "edge": {"action": "go expected"},
        },
        action_steps=1,
        expected_source="s1",
        provenance={"kind": "graph_edge"},
        workflow_expected_landing="s2",
        workflow_action_label="go expected",
        workflow_remaining_route="没有后续动作。",
    )

    assert step["arrived_node"] == "sx"
    assert adapter.calls.count("identify") == 1
    assert executor._workflow_confirmed_nodes["app"] == "sx"
    assert executor._trajectory[0]["workflow_review"][
        "matches_expected"] is False


def test_one_region_only_hop_can_reenter_a_known_stage():
    class _RegionThenStageWorkflow:
        def __init__(self):
            self.calls = []

        def confirm(self, **request):
            self.calls.append(request)
            if len(self.calls) == 1:
                return {
                    "match_scope": "region",
                    "matches_expected": False,
                    "previous_action": "success",
                    "reason": (
                        "The whole Alarms Stage differs, but the active top "
                        "navigation region and Stopwatch target match."),
                    "next_click": {
                        "target": "Stopwatch",
                        "bbox_1000": [400, 0, 600, 100],
                        "click_point_1000": [500, 50],
                    },
                }
            return {
                "match_scope": "stage",
                "matches_expected": True,
                "previous_action": "success",
                "reason": "The Stopwatch Stage matches s3.",
                "next_click": None,
            }

    graph = _graph(
        ("s1", "s2", "click Alarms", 1),
        ("s2", "s3", "click Stopwatch", 1),
    )
    graph.edges["s2", "s3"]["region"] = "r1"
    graph.nodes["s2"].update(
        page_name="Alarms",
        semantic_blocks=[{
            "region_id": "r1",
            "role": "Top Navigation Bar",
            "element_names": [
                "World", "Alarms", "Stopwatch", "Timer", "Menu"],
        }, {
            "region_id": "r4",
            "role": "Main Content Area",
            "element_names": ["Add Alarm button"],
        }],
    )
    graph.nodes["s3"].update(
        page_name="Stopwatch",
        semantic_blocks=[{
            "region_id": "r6",
            "role": "Main Content Area",
            "element_names": ["Start button", "Lap button"],
        }],
    )
    adapter = _Adapter("clock", "s1", {
        "click Alarms": "s2",
        "click Stopwatch": "s3",
    })
    workflow = _RegionThenStageWorkflow()
    executor = VisualCollectionExecutor(
        {"clock": graph}, {"clock": adapter}, _Verifier(),
        workflow_agent=workflow)
    executor._current_app = "clock"
    executor._nodes["clock"] = "s1"
    executor._workflow_confirmed_nodes["clock"] = "s1"

    ok, reason, provenance = executor._route_to("clock", "s3")

    assert ok is True, reason
    assert adapter.executed == ["click Alarms", "click Stopwatch"]
    assert adapter.workflow_grounded == ["Stopwatch"]
    assert adapter.calls.count("identify") == 0
    assert executor._trajectory[0]["arrived_node_id"] is None
    assert executor._trajectory[0]["workflow_review"][
        "match_scope"] == "region"
    assert provenance[0]["region_only"] is True
    assert executor._trajectory[1]["arrived_node_id"] == "s3"
    assert "Top Navigation Bar，包含 World、Alarms、Stopwatch、Timer" in \
        workflow.calls[0]["required_region"]



def test_inverse_direction_fails_ref_and_agent_audit() -> None:
    adapter = _Adapter("app", "page", {"toggle": "page"})
    executor = VisualCollectionExecutor(
        {"app": _graph()}, {"app": adapter}, _OutcomeVerifier(False)
    )

    result = executor.execute(
        {
            "instruction": "enable the setting",
            "capability_refs": [
                _ref(
                    "toggle",
                    "app",
                    "page",
                    action="toggle",
                    desired_outcome=True,
                )
            ],
        },
        initial_app_id="app",
    )

    assert result["success"] is False
    assert result["final_status"] == "capability_failed"
    assert result["agent_audit"]["agent_failure"] is True
    codes = {issue["code"] for issue in result["agent_audit"]["issues"]}
    assert "wrong_outcome" in codes
    assert "verification_failed" in codes
    verification = result["trajectory"][0]["verification"]
    assert verification["complete"] is False
    assert verification["outcome_match"] is False


def test_directional_verifier_must_report_observed_outcome() -> None:
    adapter = _Adapter("app", "page", {"toggle": "page"})
    executor = VisualCollectionExecutor(
        {"app": _graph()}, {"app": adapter}, _Verifier()
    )

    result = executor.execute(
        {
            "instruction": "enable the setting",
            "capability_refs": [
                _ref(
                    "toggle",
                    "app",
                    "page",
                    action="toggle",
                    desired_outcome=True,
                )
            ],
        },
        initial_app_id="app",
    )

    assert result["success"] is False
    verification = result["trajectory"][0]["verification"]
    assert verification["complete"] is False
    assert verification["reason"] == \
        "directional capability verification omitted observed_outcome"


def test_unordered_refs_choose_minimum_actual_gui_action_count() -> None:
    graph = _graph(
        ("start", "near", "go_near", 1),
        ("start", "far", "expensive_far", 5),
        ("near", "far", "near_to_far", 1),
        ("far", "near", "far_to_near", 10),
    )
    adapter = _Adapter(
        "app",
        "start",
        {
            "go_near": "near",
            "expensive_far": "far",
            "near_to_far": "far",
            "far_to_near": "near",
            "do_near": "near",
            "do_far": "far",
        },
    )
    verifier = _Verifier()
    executor = VisualCollectionExecutor(
        {"app": graph}, {"app": adapter}, verifier
    )

    result = executor.execute(
        {
            "instruction_id": "MIN",
            "instruction": "complete both functions",
            # Deliberately put the expensive destination first.
            "capability_refs": [
                _ref("far", "app", "far"),
                _ref("near", "app", "near"),
            ],
        },
        initial_app_id="app",
    )

    assert result["success"] is True
    assert verifier.ref_order == ["near", "far"]
    assert adapter.executed == ["go_near", "do_near", "near_to_far", "do_far"]
    assert result["total_action_steps"] == 4
    assert all(step["committed"] for step in result["trajectory"])


def test_weighted_route_uses_action_steps_not_fewest_edge_count() -> None:
    graph = _graph(
        ("root", "target", "one_expensive_hop", 7),
        ("root", "middle", "cheap_one", 1),
        ("middle", "target", "cheap_two", 1),
    )
    adapter = _Adapter(
        "app",
        "root",
        {
            "one_expensive_hop": "target",
            "cheap_one": "middle",
            "cheap_two": "target",
            "finish": "target",
        },
    )
    executor = VisualCollectionExecutor(
        {"app": graph}, {"app": adapter}, _Verifier()
    )

    result = executor.execute(
        {
            "instruction": "finish",
            "capability_refs": [
                _ref("finish", "app", "target", action="finish")
            ],
        },
        initial_app_id="app",
    )

    assert result["success"] is True
    assert adapter.executed == ["cheap_one", "cheap_two", "finish"]
    assert result["total_action_steps"] == 3


def test_scheduler_includes_declared_prerequisite_setup_cost() -> None:
    graph = _graph()
    adapter = _Adapter(
        "app", "page",
        {"do_expensive": "page", "do_cheap": "page"},
    )
    verifier = _Verifier()
    expensive = _ref(
        "expensive", "app", "page", action="do_expensive",
        requires=[{
            "kind": "resource",
            "fact": "fixture_exists",
            "resource_slot": "fixture_ref",
            "setup_recipe": [{
                "recipe_id": "create_fixture",
                "estimated_gui_actions": 5,
                "actions": [{"action": "create"}],
            }],
        }],
    )
    cheap = _ref("cheap", "app", "page", action="do_cheap")
    result = VisualCollectionExecutor(
        {"app": graph}, {"app": adapter}, verifier,
        precondition_resolver=lambda *_args: {"satisfied": True},
    ).execute(
        {
            "instruction": "do both functions",
            "capability_refs": [expensive, cheap],
        },
        initial_app_id="app",
    )

    assert result["success"] is True
    assert verifier.ref_order == ["cheap", "expensive"]


def test_explicit_dependency_order_is_respected() -> None:
    graph = _graph(
        ("root", "first_page", "to_first", 3),
        ("root", "second_page", "to_second", 1),
        ("first_page", "second_page", "first_to_second", 1),
    )
    adapter = _Adapter(
        "app",
        "root",
        {
            "to_first": "first_page",
            "to_second": "second_page",
            "first_to_second": "second_page",
            "do_first": "first_page",
            "do_second": "second_page",
        },
    )
    verifier = _Verifier()
    executor = VisualCollectionExecutor(
        {"app": graph}, {"app": adapter}, verifier
    )

    result = executor.execute(
        {
            "instruction": "first, then second",
            "capability_refs": [
                _ref("first", "app", "first_page"),
                # A ref id in requires is a dependency, not a runtime predicate.
                _ref("second", "app", "second_page", requires=["first"]),
            ],
        },
        initial_app_id="app",
    )

    assert result["success"] is True
    assert verifier.ref_order == ["first", "second"]
    assert adapter.executed == ["to_first", "do_first", "first_to_second", "do_second"]


def test_runtime_precondition_satisfied_already_complete_and_unsatisfied_skip() -> None:
    graph = _graph()

    satisfied_adapter = _Adapter("app", "page", {"do_edit": "page"})
    satisfied = VisualCollectionExecutor(
        {"app": graph},
        {"app": satisfied_adapter},
        _Verifier(),
        precondition_resolver=lambda requirement, _ref, _context: {
            "satisfied": requirement == "unlocked",
            "evidence": "runtime gate checked",
            "gui_action_count": 2,
            "action_events": [
                {
                    "action_id": "unlock_click",
                    "action_spec": {"action_type": "CLICK"},
                    "action_steps": 1,
                    "committed": True,
                },
                {
                    "action_id": "confirm_click",
                    "action_spec": {"action_type": "CLICK"},
                    "action_steps": 1,
                    "committed": True,
                },
            ],
            "world_facts": {"authorized": True},
            "resource_bindings": {"session": "runtime-session"},
        },
    ).execute(
        {
            "instruction": "edit protected setting",
            "capability_refs": [
                _ref("edit", "app", "page", action="do_edit", requires=["unlocked"])
            ],
        },
        initial_app_id="app",
    )
    assert satisfied["success"] is True
    assert satisfied_adapter.executed == ["do_edit"]
    assert satisfied["total_action_steps"] == 3
    precondition_steps = [
        step for step in satisfied["trajectory"]
        if step["kind"] == "precondition"
    ]
    assert [step["action_id"] for step in precondition_steps] == [
        "unlock_click", "confirm_click"
    ]
    assert [step["step"] for step in satisfied["trajectory"]] == [0, 1, 2]
    assert satisfied["blackboard"] == {
        "authorized": True,
        "session": "runtime-session",
    }

    already_adapter = _Adapter("app", "page")
    already = VisualCollectionExecutor(
        {"app": graph},
        {"app": already_adapter},
        _Verifier(),
        precondition_resolver=lambda *_args: {
            "satisfied": True,
            "already_complete": True,
            "evidence": "goal visible before action",
        },
    ).execute(
        {
            "instruction": "ensure protected setting is enabled",
            "capability_refs": [
                _ref("ensure", "app", "page", requires=["unlocked"])
            ],
        },
        initial_app_id="app",
    )
    assert already["success"] is True
    assert already_adapter.executed == []
    assert already["total_action_steps"] == 0
    assert already["ref_results"][0]["status"] == "completed_precondition_skip"

    blocked_adapter = _Adapter("app", "page", {"do_edit": "page"})
    blocked = VisualCollectionExecutor(
        {"app": graph},
        {"app": blocked_adapter},
        _Verifier(),
        precondition_resolver=lambda *_args: {
            "satisfied": False,
            "reason": "credential unavailable",
        },
    ).execute(
        {
            "instruction": "edit protected setting",
            "capability_refs": [
                _ref("edit", "app", "page", action="do_edit", requires=["unlocked"])
            ],
        },
        initial_app_id="app",
    )
    assert blocked["success"] is False
    assert blocked_adapter.executed == []
    assert blocked["total_action_steps"] == 0
    assert blocked["ref_results"][0]["status"] == "skipped_precondition"


def test_precondition_is_checked_on_entry_surface_when_route_is_available() -> None:
    graph = _graph(("root", "protected", "open_protected", 1))
    adapter = _Adapter(
        "app", "root",
        {"open_protected": "protected", "do_edit": "protected"},
    )
    seen_nodes = []

    def resolve(_requirement, _ref_value, context):
        seen_nodes.append(context["current_node_id"])
        return {"satisfied": True}

    result = VisualCollectionExecutor(
        {"app": graph}, {"app": adapter}, _Verifier(),
        precondition_resolver=resolve,
    ).execute(
        {
            "instruction": "edit unlocked setting",
            "capability_refs": [
                _ref("edit", "app", "protected", requires=["unlocked"])
            ],
        },
        initial_app_id="app",
    )

    assert result["success"] is True
    assert seen_nodes == ["protected"]
    assert adapter.executed == ["open_protected", "do_edit"]


def test_unreachable_resource_surface_resolves_gate_then_replans() -> None:
    graph = _graph()
    graph.add_nodes_from(["empty", "populated"])
    adapter = _Adapter("clock", "empty", {"open_alarm": "populated"})

    def create_alarm(_requirement, _ref_value, context):
        assert context["current_node_id"] == "empty"
        adapter.current_node = "populated"
        return {
            "satisfied": True,
            "gui_action_count": 1,
            "action_events": [{
                "action_id": "create_alarm",
                "action_spec": {"action_type": "CLICK"},
                "action_steps": 1,
                "committed": True,
            }],
            "resource_bindings": {"alarm_ref": "08:00 test alarm"},
        }

    result = VisualCollectionExecutor(
        {"clock": graph}, {"clock": adapter}, _Verifier(),
        precondition_resolver=create_alarm,
    ).execute(
        {
            "instruction": "open the existing alarm function",
            "capability_refs": [
                _ref(
                    "open_alarm", "clock", "populated",
                    action="open_alarm", requires=[{
                        "kind": "resource",
                        "fact": "alarm_exists",
                        "resource_slot": "alarm_ref",
                    }],
                )
            ],
        },
        initial_app_id="clock",
    )

    assert result["success"] is True
    assert result["blackboard"]["alarm_ref"] == "08:00 test alarm"
    assert result["total_action_steps"] == 2
    assert [step["kind"] for step in result["trajectory"]] == [
        "precondition", "capability"
    ]


def test_run_owned_precondition_resources_are_cleaned_after_verification() -> None:
    class Resolver:
        def __init__(self):
            self.action_events = []

        def __call__(self, *_args):
            self.action_events.append({
                "action_id": "create_fixture",
                "action_spec": {"action_type": "CLICK"},
                "action_steps": 1,
                "committed": True,
            })
            return {
                "satisfied": True,
                "gui_action_count": 1,
                "action_events": list(self.action_events),
            }

        def cleanup(self):
            self.action_events.append({
                "action_id": "delete_fixture",
                "phase": "cleanup",
                "action_spec": {"action_type": "CLICK"},
                "action_steps": 1,
                "committed": True,
            })
            return {
                "status": "complete",
                "gui_action_count": 1,
                "results": [],
            }

    graph = _graph()
    adapter = _Adapter("clock", "page", {"edit": "page"})
    result = VisualCollectionExecutor(
        {"clock": graph}, {"clock": adapter}, _Verifier(),
        precondition_resolver=Resolver(),
    ).execute(
        {
            "instruction": "edit test alarm",
            "capability_refs": [
                _ref("edit", "clock", "page", action="edit",
                     requires=["alarm_exists"])
            ],
        },
        initial_app_id="clock",
    )

    assert result["success"] is True
    assert result["total_action_steps"] == 2
    assert result["cleanup_action_steps"] == 1
    assert result["cleanup"]["status"] == "complete"
    assert result["trajectory"][-1]["kind"] == "precondition_cleanup"
    assert result["trajectory"][-1]["action_id"] == "delete_fixture"


def test_partial_dynamic_execution_is_retained_as_uncommitted_action_evidence() -> None:
    class PartialAdapter(_Adapter):
        def ground(self, _action_spec, _observation):
            return {
                "dynamic_recipe": [{"action": "first"}, {"action": "second"}],
                "gui_action_count": 2,
                "_executed_gui_actions": 0,
            }

        def execute(self, grounded_action):
            self.executed.append("first")
            grounded_action["_executed_gui_actions"] = 1
            self._last_obs = self.capture()
            raise RuntimeError("second dynamic step could not be grounded")

    adapter = PartialAdapter("app", "page")
    result = VisualCollectionExecutor(
        {"app": _graph()}, {"app": adapter}, _Verifier(),
    ).execute(
        {
            "instruction": "perform two-step function",
            "capability_refs": [
                _ref("multi", "app", "page", action_steps=2)
            ],
        },
        initial_app_id="app",
    )

    assert result["success"] is False
    assert result["total_action_steps"] == 1
    assert len(result["trajectory"]) == 1
    assert result["trajectory"][0]["committed"] is False
    assert result["trajectory"][0]["status"] == "execution_failed"
    assert result["trajectory"][0]["action_steps"] == 1


def test_application_login_capability_requires_user_without_gui_actions() -> None:
    adapter = _Adapter("vscode", "account", {"sign_in": "account"})
    ref = _ref("sign_in", "vscode", "account", action="sign_in")
    ref["name"] = "Sign in to Settings Sync"
    ref["execution_recipe"] = [{
        "action_type": "CLICK",
        "selector": {"element_label": "Sign in"},
    }]
    result = VisualCollectionExecutor(
        {"vscode": _graph()}, {"vscode": adapter}, _Verifier(),
    ).execute(
        {"instruction": "sign in", "capability_refs": [ref]},
        initial_app_id="vscode",
    )

    assert result["success"] is False
    assert result["ref_results"][0]["status"] == "needs_user"
    assert adapter.executed == []
    assert result["total_action_steps"] == 0


def test_cross_app_switch_is_one_step_and_graphs_remain_separate() -> None:
    graphs = {"app_a": _graph(), "app_b": _graph()}
    adapter_a = _Adapter("app_a", "a_home", {"do_a": "a_home"})
    adapter_b = _Adapter("app_b", "b_home", {"do_b": "b_home"})
    verifier = _Verifier()
    executor = VisualCollectionExecutor(
        graphs, {"app_a": adapter_a, "app_b": adapter_b}, verifier
    )

    result = executor.execute(
        {
            "instruction": "do A, then B",
            "fixed_order": True,
            "capability_refs": [
                _ref("a", "app_a", "a_home", action="do_a"),
                _ref("b", "app_b", "b_home", action="do_b"),
            ],
        },
        initial_app_id="app_a",
    )

    assert result["success"] is True
    assert result["app_switches"] == 1
    assert result["total_action_steps"] == 3  # A action + switch + B action
    switch = next(step for step in result["trajectory"] if step["kind"] == "app_switch")
    assert switch["graph_provenance"] == {
        "kind": "cross_app_boundary",
        "source_app_id": "app_a",
        "target_app_id": "app_b",
        "graphs_merged": False,
    }
    assert graphs["app_a"] is not graphs["app_b"]


def test_navigation_derailment_replans_from_actual_identified_node() -> None:
    graph = _graph(
        ("root", "target", "planned_direct", 1),
        ("detour", "target", "recover_from_detour", 1),
    )
    adapter = _Adapter(
        "app",
        "root",
        {
            "planned_direct": "detour",
            "recover_from_detour": "target",
            "finish": "target",
        },
    )
    executor = VisualCollectionExecutor(
        {"app": graph}, {"app": adapter}, _Verifier(), max_replans=2
    )

    result = executor.execute(
        {
            "instruction": "finish after recovering",
            "capability_refs": [
                _ref("finish", "app", "target", action="finish")
            ],
        },
        initial_app_id="app",
    )

    assert result["success"] is True
    assert adapter.executed == [
        "planned_direct", "recover_from_detour", "finish", "finish"]
    assert result["route_collection_attempt"] == 2
    assert result["discarded_route_attempts"] == [{
        "attempt": 1,
        "final_status": "complete",
        "action_steps": 3,
        "route_corrections": [{
            "app_id": "app", "source": "root",
            "predicted_target": "target", "actual_target": "detour",
            "route_context": "", "edge_key": None, "persisted": True,
        }],
    }]
    route = result["ref_results"][0]["route_provenance"]
    assert route == []
    assert result["total_action_steps"] == 1
    assert [step["kind"] for step in result["trajectory"]] == ["capability"]


def test_vlm_ref_failure_never_commits_capability_or_success() -> None:
    graph = _graph()
    adapter = _Adapter("app", "page", {"do_sensitive": "page"})
    verifier = _Verifier(failed_refs={"sensitive"}, final=True)
    executor = VisualCollectionExecutor(
        {"app": graph}, {"app": adapter}, verifier
    )

    result = executor.execute(
        {
            "instruction": "perform sensitive operation",
            "capability_refs": [
                _ref("sensitive", "app", "page", action="do_sensitive")
            ],
        },
        initial_app_id="app",
    )

    assert adapter.executed == ["do_sensitive"]
    assert result["success"] is False
    assert result["final_status"] == "capability_failed"
    assert result["completed_refs"] == []
    assert result["ref_results"][0]["committed"] is False
    assert result["trajectory"][-1]["committed"] is False
    assert verifier.final_calls == 1
    assert result["total_action_steps"] == 1


def test_simple_vlm_verifier_is_explicit_and_fail_closed() -> None:
    class _Agent:
        def __init__(self, response: str) -> None:
            self.response = response

        def predict_mm(self, _prompt, _images):
            return self.response, 0, 0

    approved = VLMCompletionVerifier(_Agent('{"complete": true, "reason": "visible"}'))
    denied = VLMCompletionVerifier(_Agent("not valid JSON"))

    assert approved.verify_final({"instruction": "x"}, "frame", {})["complete"] is True
    assert denied.verify_final({"instruction": "x"}, "frame", {})["complete"] is False
