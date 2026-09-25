from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from gui_rewalk.src.core.visual_traversal.agents.explorer import ExplorerAgent
from gui_rewalk.src.core.visual_traversal.runtime.contracts import (
    CandidateContext,
    RunCursor,
    StageDirective,
)
from gui_rewalk.src.core.visual_traversal.runtime.element_task import (
    compact_page_graph,
    record_element_task_action,
    start_element_task,
    task_progress_facts,
)
from gui_rewalk.src.core.visual_traversal.runtime.agent_tools import (
    current_region_directory,
)
from gui_rewalk.src.core.visual_traversal.runtime.execution import (
    execute_candidate,
)
from gui_rewalk.src.core.visual_traversal.runtime.scheduling import plan_candidate
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement


class _Debug:
    def __init__(self):
        self.agents = []
        self.events = []

    def record_agent(self, role, **payload):
        self.agents.append((role, payload))

    def record_event(self, event, **payload):
        self.events.append((event, payload))


def _element(element_id=1, name="Add attachment", *, status="pending"):
    element = VisualElement(
        element_id, name, [0, 0, 1, 1], [10, 20],
        region="Chat actions", region_id="r1",
    )
    element.exploration_status = status
    return element


def _shot(width=100, height=200):
    stream = BytesIO()
    Image.new("RGB", (width, height), "white").save(stream, format="PNG")
    return stream.getvalue()


def _direct_decision(target, *, role="other", point=None,
                     action_type="CLICK", page_ref="p0"):
    return {
        "decision": "act",
        "current_page": {
            "kind": "known", "page_ref": page_ref,
            "proposed_name": "", "reason": "Visible page matches.",
        },
        "discovered_controls": [],
        "next_action": {
            "type": action_type,
            "target": target,
            "point_1000": point if point is not None else [500, 500],
            "direction": None,
            "safety": "safe",
            "action_role": role,
            "reason": f"Use {target}.",
            "expected_result": "The task advances.",
        },
        "reason": f"Use {target}.",
    }


def _host(elements, explorer, *, states=None, router=None):
    debug = _Debug()
    state_data = states or {"chat": {
        "page_name": "Chat info", "page_id": "page-chat",
        "elements": list(elements),
        "semantic_blocks": [{"region_id": "r1", "role": "Chat actions"}],
    }}
    return SimpleNamespace(
        _is_touch=False,
        app_name="Mingle",
        explorer=explorer,
        router=router or SimpleNamespace(plan_route=lambda _src, _dst: []),
        graph=SimpleNamespace(action_edges=[]),
        _state_data=state_data,
        _action_count=0,
        _active_state_mutation=None,
        _element_exploration_task=None,
        _explorer_deferred_regions=set(),
        _explorer_region_failure_counts={},
        perception=SimpleNamespace(use_semantic_inventory=True),
        review_debug=debug,
        _maybe_save=lambda: None,
    )


def test_element_task_prompt_repairs_unknown_page_and_uses_task_history(
        monkeypatch):
    replies = iter([
        json.dumps({
            "current_page": {"kind": "known", "page_ref": "missing",
                             "proposed_name": "", "reason": "Looks known."},
            "discovered_controls": [],
            "action": {"type": "CLICK", "target": "Close",
                       "point_1000": [500, 500], "direction": None,
                       "safety": "safe", "action_role": "recovery",
                       "reason": "Close the overlay.",
                       "expected_result": "Return to the page."},
        }),
        json.dumps({
            "current_page": {"kind": "known", "page_ref": "p1",
                             "proposed_name": "", "reason": "Overlay."},
            "discovered_controls": [{
                "target": "Close", "area": "top bar", "relation": "close",
                "reason": "Visible close control."}],
            "action": {"type": "CLICK", "target": "Close",
                       "point_1000": [500, 500], "direction": None,
                       "safety": "safe", "action_role": "recovery",
                       "reason": "Close the overlay first.",
                       "expected_result": "Return to Chat info."},
        }),
    ])
    calls = []
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value,
    )

    def predict(_agent, role, prompt, images, _ledger, **kwargs):
        calls.append((role, prompt, images, kwargs))
        return next(replies), None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict,
    )
    explorer = ExplorerAgent(object())
    result = explorer.explore_target(_shot(), {
        "application_name": "Mingle",
        "current_interface": "Attachment menu",
        "goal": {
            "target": "Add attachment",
            "source_page": "Chat info",
            "region_name": "Chat actions",
        },
        "page_graph": {
            "text": "CURRENT: p1\nPAGES:\np0 | Chat info\np1 | Menu",
            "page_refs": ["p0", "p1"],
        },
        "task_history": [{
            "step": 1, "selected_target": "More",
            "outcome": "transitioned", "landing_page": "Attachment menu",
        }],
        "remaining_actions": 5,
    })

    assert result["decision"] == "act"
    assert result["current_page"]["page_ref"] == "p1"
    assert result["next_action"]["target"] == "Close"
    assert result["next_action"]["point_1000"] == [500.0, 500.0]
    assert "Add attachment" in calls[0][1]
    assert "Attachment menu" in calls[0][1]
    assert "More" in calls[0][1]
    assert "previous_results" not in calls[0][1]
    assert "page_ref='missing'" in calls[1][1]


def test_element_agent_accepts_a_declared_lightweight_tool(monkeypatch):
    reply = json.dumps({
        "current_page": {
            "kind": "known", "page_ref": "p0",
            "proposed_name": "", "reason": "Settings is visible.",
        },
        "discovered_controls": [],
        "action": {
            "type": "CALL_TOOL", "target": "Preferences Region",
            "point_1000": None, "direction": None,
            "safety": "safe", "action_role": "other",
            "reason": "The Region has not been observed.",
            "expected_result": "Visible entries in the Region.",
            "tool_name": "inspect_region",
            "arguments": {"region_ref": "r0"},
        },
    })
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value,
    )
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: (reply, None),
    )
    explorer = ExplorerAgent(object())

    result = explorer.explore_target(_shot(), {
        "goal": {"target": "Notifications"},
        "page_graph": {"text": "CURRENT: p0", "page_refs": ["p0"]},
        "tool_catalog": [{"name": "inspect_region"}],
    })

    assert result["decision"] == "tool"
    assert result["next_action"]["tool_name"] == "inspect_region"
    assert result["next_action"]["arguments"] == {"region_ref": "r0"}


def test_plan_candidate_starts_goal_task_and_accepts_direct_recovery_click():
    goal = _element(1, "Add attachment")
    intermediate = _element(2, "Close overlay")
    captured = {}

    class Explorer:
        last_reason = ""
        last_prompts = []
        last_backend_runs = []
        last_raw_responses = []

        @staticmethod
        def choose(_shot, _context, **_kwargs):
            return {
                "next_action": {
                    "action": {"action_type": "CLICK", "parameters": {}},
                    "choice_id": "e0", "reason": "Explore attachments.",
                },
            }

        @staticmethod
        def explore_target(_shot, context):
            captured.update(context)
            return _direct_decision(
                "Close overlay", role="recovery", page_ref="p0")

    host = _host([goal, intermediate], Explorer())
    outcome = plan_candidate(
        host, RunCursor("chat", {"screenshot": _shot()}),
        [goal, intermediate])

    assert outcome.directive is StageDirective.EXECUTION
    assert outcome.candidate.element.name == "Close overlay"
    assert outcome.candidate.element is not intermediate
    assert outcome.candidate.direct_action is True
    assert outcome.candidate.action["parameters"]["x"] == 50
    assert outcome.candidate.action["parameters"]["y"] == 100
    assert outcome.candidate.exploration_task_id
    assert host._element_exploration_task["goal_element"] is goal
    assert captured["goal"]["target"] == "Add attachment"
    assert "PAGES:" in captured["page_graph"]["text"]
    assert "available_actions" not in captured


def test_active_task_passes_bounded_memory_progress_regions_and_tools():
    goal = _element(1, "Add attachment")
    other = _element(2, "Open menu")
    captured = {}

    class Explorer:
        last_reason = ""
        last_prompts = []
        last_backend_runs = []
        last_raw_responses = []

        @staticmethod
        def choose(*_args, **_kwargs):
            raise AssertionError("global goal selection must not repeat")

        @staticmethod
        def explore_target(_shot, context):
            captured.update(context)
            return _direct_decision("Open menu", page_ref="p0")

    host = _host([goal, other], Explorer())
    task = start_element_task(host, "chat", goal)
    task["history"].append({
        "step": 1, "selected_target": "Dismiss",
        "outcome": "transitioned", "landing_page": "Chat info",
    })
    task["actions_used"] = 1

    outcome = plan_candidate(
        host, RunCursor("chat", {"screenshot": _shot()}), [goal, other])

    assert outcome.candidate.element.name == "Open menu"
    assert captured["task_memory"]["events"] == task["history"]
    assert captured["task_memory"]["total_actions"] == 1
    assert "remaining_actions" not in captured
    assert captured["progress_facts"]["repeated_last_action"] == 1
    assert captured["current_regions"]["regions"][0][
        "region_ref"] == "r0"
    assert {tool["name"] for tool in captured["tool_catalog"]} == {
        "recall_page", "find_route", "inspect_region",
    }
    assert "available_actions" not in captured


def test_goal_role_only_uses_goal_identity_when_target_name_matches():
    goal = _element(1, "Add attachment")

    class Explorer:
        last_reason = ""
        last_prompts = []
        last_backend_runs = []
        last_raw_responses = []

        @staticmethod
        def choose(_shot, _context, **_kwargs):
            return {"next_action": {
                "action": {"action_type": "CLICK", "parameters": {}},
                "choice_id": "e0", "reason": "Explore it.",
            }}

        @staticmethod
        def explore_target(_shot, _context):
            return _direct_decision(
                "Close overlay", role="goal", page_ref="p0")

    host = _host([goal], Explorer())
    outcome = plan_candidate(
        host, RunCursor("chat", {"screenshot": _shot()}), [goal])

    assert outcome.directive is StageDirective.EXECUTION
    assert outcome.candidate.element is not goal
    assert outcome.candidate.element.name == "Close overlay"


def test_verified_route_is_compacted_and_agent_clicks_the_visible_route_control():
    goal = _element(1, "Add attachment")
    pending = _element(2, "Menu item")
    route_back = _element(3, "Close", status="complete")
    states = {
        "chat": {"page_name": "Chat info", "page_id": "page-chat",
                 "elements": [goal]},
        "menu": {
            "page_name": "Attachment menu", "page_id": "page-menu",
            "elements": [pending, route_back],
        },
    }
    router = SimpleNamespace(plan_route=lambda _src, _dst: [{
        "element_id": str(route_back.id),
        "name": "Close", "region": "Chat actions", "dst": "chat",
    }])
    captured = {}

    class Explorer:
        last_reason = ""
        last_prompts = []
        last_backend_runs = []
        last_raw_responses = []

        @staticmethod
        def choose(*_args, **_kwargs):
            raise AssertionError

        @staticmethod
        def explore_target(_shot, context):
            captured.update(context)
            return _direct_decision(
                "Close", role="route", page_ref="p1")

    host = _host([pending], Explorer(), states=states, router=router)
    start_element_task(host, "chat", goal)
    outcome = plan_candidate(
        host, RunCursor("menu", {"screenshot": _shot()}), [pending])

    assert outcome.candidate.element.name == "Close"
    assert outcome.candidate.element.uid == outcome.candidate.element.id
    assert outcome.candidate.direct_action is True
    assert captured["route_guidance"]["status"] == "verified_route"
    assert "Close" in captured["page_graph"]["text"]
    assert "ROUTE:" in captured["page_graph"]["text"]


def test_element_task_codex_backend_uses_action_choice_schema(
        monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        ExplorerAgent, "_codex_command", staticmethod(lambda: ["codex-test"]))

    def run(command, **_kwargs):
        schema_path = command[command.index("--output-schema") + 1]
        output_path = command[command.index("-o") + 1]
        captured["schema"] = json.loads(
            Path(schema_path).read_text(encoding="utf-8"))
        Path(output_path).write_text(
            json.dumps({
                "current_page": {
                    "kind": "known", "page_ref": "p0",
                    "proposed_name": "", "reason": "Matches Settings.",
                },
                "discovered_controls": [],
                "action": {
                    "type": "CLICK", "target": "Notifications",
                    "point_1000": [500, 400], "direction": None,
                    "safety": "safe", "action_role": "goal",
                    "reason": "Open the requested setting.",
                    "expected_result": "Notifications page opens.",
                },
            }), encoding="utf-8")
        return SimpleNamespace(
            returncode=0,
            stdout='{"type":"thread.started","thread_id":"task-thread"}\n',
            stderr="",
        )

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer.subprocess.run",
        run,
    )
    explorer = ExplorerAgent(
        None, codex_model="codex-fixture-model", codex_temp_root=str(tmp_path))
    result = explorer.explore_target(b"screen", {
        "goal": {"target": "Add attachment"},
        "page_graph": {"text": "CURRENT: p0\nPAGES:\np0 | Settings",
                       "page_refs": ["p0"]},
    })

    assert result["decision"] == "act"
    assert result["current_page"]["page_ref"] == "p0"
    assert result["next_action"]["target"] == "Notifications"
    assert result["next_action"]["point_1000"] == [500.0, 400.0]
    assert "current_page" in captured["schema"]["required"]
    assert "action" in captured["schema"]["required"]
    assert explorer.last_backend_runs[0]["thread_id"] == "task-thread"


def test_compact_page_graph_collapses_states_and_omits_button_inventory():
    goal = _element(1, "Notifications")
    states = {
        "settings-a": {
            "page_id": "settings", "page_name": "Settings",
            "elements": [goal, _element(2, "Mute")],
            "semantic_blocks": [{"role": "Preferences"}],
        },
        "settings-b": {
            "page_id": "settings", "page_name": "Settings",
            "elements": [_element(3, "Theme")],
            "semantic_blocks": [{"role": "Account"}],
        },
        "notifications": {
            "page_id": "notifications", "page_name": "Notifications",
            "elements": [_element(4, "Message notifications")],
            "semantic_blocks": [{"role": "Notification controls"}],
        },
    }
    host = _host([], object(), states=states)
    host.graph.action_edges = [{
        "source": "settings-a", "target": "notifications",
        "routing_verified": True, "element_name": "Notifications",
        "attempts": [{"outcome": "transitioned_consistent"}],
    }]
    task = start_element_task(host, "settings-a", goal)
    graph = compact_page_graph(host, "settings-b", task, {
        "status": "at_goal_source", "steps": [],
    })

    assert graph["text"].count("| Settings |") == 1
    assert "Preferences, Account" in graph["text"]
    assert "p0 -> p1" in graph["text"]
    assert "Mute" not in graph["text"]
    assert "Theme" not in graph["text"]
    assert "attempts" not in graph["text"]


def test_direct_click_executes_agent_point_without_grounder_or_reviewer():
    element = _element(1, "Notifications")
    action = {
        "action_type": "CLICK",
        "parameters": {"x": 37, "y": 81, "button": "left"},
    }
    plan = CandidateContext(
        element=element, decision_reason="agent selected visible target",
        is_seed=False, is_stateful=False, is_restore=False,
        mutation_id="", stateful_evidence={}, active_mutation=None,
        pre_click_id="settings", action=action, targeted=True,
        direct_action=True, exploration_task_id="settings:1:1",
    )
    calls = []
    events = []

    class Graph:
        @staticmethod
        def record_action_event(**payload):
            events.append(payload)
            return 0

        @staticmethod
        def update_action_event(_index, **_changes):
            return None

    host = SimpleNamespace(
        _map_guided_inherited=None,
        _verify_navigation_effect=True,
        _settle_enabled=False,
        _action_count=0,
        _live_center_for=lambda *_a, **_kw: (
            pytest.fail("direct action called the old Grounder")),
        reviewer=SimpleNamespace(review_target=lambda *_a, **_kw: (
            pytest.fail("direct action called the old Reviewer"))),
        env=SimpleNamespace(step=lambda sent, **_kw: (
            calls.append(sent) or {"screenshot": b"after"})),
        graph=Graph(), review_debug=_Debug(),
        _edge_label=lambda *_a: "Notifications",
        _portable_graph_action=lambda sent, _elem: dict(sent),
        _stateful_edge_label=lambda *_a: "",
        _ensure_on_app=lambda obs: (obs, False, True),
        _save_action_attempt_screenshot=lambda *_a: None,
        _record_click_failure=lambda *_a: pytest.fail(
            "direct click should execute"),
        _maybe_save=lambda: None,
    )
    outcome = execute_candidate(
        host, RunCursor("settings", {"screenshot": b"before"}), plan)

    assert outcome.directive is StageDirective.RECOVERY
    assert calls == [action]
    assert element.center == [37, 81]
    assert events[0]["evidence"] == {
        "element_agent_direct_action": True,
        "element_agent_target": "Notifications",
        "element_agent_action_type": "CLICK",
        "element_agent_point_px": [37, 81],
    }


def test_task_defer_closes_task_without_forcing_goal_click():
    goal = _element(1, "Hidden action")
    failures = []

    class Explorer:
        last_reason = ""
        last_prompts = []
        last_backend_runs = []
        last_raw_responses = []

        @staticmethod
        def choose(_shot, _context, **_kwargs):
            return {"next_action": {
                "action": {"action_type": "CLICK", "parameters": {}},
                "choice_id": "e0", "reason": "Explore it.",
            }}

        @staticmethod
        def explore_target(_shot, _context):
            return {
                "decision": "defer", "selected_entry_id": None,
                "reason": "No allowed action can remove the blocking dialog.",
            }

    host = _host([goal], Explorer())
    host._record_click_failure = lambda state, target, reason: (
        failures.append((state, target.name, reason)) or 1)
    outcome = plan_candidate(
        host, RunCursor("chat", {"screenshot": b"screen"}), [goal])

    assert outcome.directive is StageDirective.CONTINUE
    assert outcome.candidate is None
    assert host._element_exploration_task is None
    assert failures == [("chat", "Hidden action", "element_task_deferred")]


def test_verified_goal_enters_optional_return_phase_instead_of_auto_closing():
    goal = _element(1, "Add attachment")
    intermediate = _element(2, "Close overlay")
    debug = _Debug()
    event = {
        "action": {"action_type": "CLICK"},
        "outcome": "transitioned_consistent",
        "detail": "overlay closed",
        "landing_verified": True,
    }
    host = SimpleNamespace(
        _action_count=0,
        _state_data={"chat": {"page_name": "Chat info"}},
        graph=SimpleNamespace(action_attempt=lambda _index: event),
        review_debug=debug,
        _record_click_failure=lambda *_args: 1,
        _element_exploration_task=None,
    )
    task = start_element_task(host, "chat", goal)
    plan = CandidateContext(
        element=intermediate, decision_reason="close overlay",
        is_seed=False, is_stateful=False, is_restore=False,
        mutation_id="", stateful_evidence={}, active_mutation=None,
        pre_click_id="chat", action={"action_type": "CLICK"},
        exploration_task_id=task["task_id"],
    )
    attempt = SimpleNamespace(event_index=1)
    cursor = RunCursor("chat", {"screenshot": b"screen"})

    record_element_task_action(
        host, plan, cursor, cursor, attempt, stage="landing_processed")

    assert task["history"] == [{
        "step": 1,
        "selected_target": "Close overlay",
        "goal_action": False,
        "action": {"action_type": "CLICK"},
        "source_page": "Chat info",
        "outcome": "transitioned_consistent",
        "detail": "overlay closed",
        "landing_page": "Chat info",
        "landing_verified": True,
    }]
    goal.exploration_status = "complete"
    plan.element = goal
    record_element_task_action(
        host, plan, cursor, cursor, attempt, stage="landing_processed")
    assert host._element_exploration_task is task
    assert task["phase"] == "goal_verified_return_optional"
    assert task["actions_used"] == 2


def test_optional_return_closes_task_after_verified_source_landing():
    goal = _element(1, "Open Weekend Plan")
    back = _element(2, "Back")
    debug = _Debug()
    event = {
        "action": {"action_type": "CLICK"},
        "outcome": "transitioned_consistent",
        "detail": "Returned to Chats.",
        "landing_verified": True,
    }
    states = {
        "chat": {"page_name": "Chats", "page_id": "page-chat"},
        "weekend": {
            "page_name": "Weekend Plan", "page_id": "page-weekend"},
    }
    host = SimpleNamespace(
        _action_count=0, _state_data=states,
        graph=SimpleNamespace(action_attempt=lambda _index: event),
        review_debug=debug, _element_exploration_task=None,
    )
    task = start_element_task(host, "chat", goal)
    task["phase"] = "goal_verified_return_optional"
    task["history"] = [{
        "goal_action": True,
        "outcome": "transitioned_consistent",
        "landing_verified": True,
    }]
    plan = CandidateContext(
        element=back, decision_reason="return",
        is_seed=False, is_stateful=False, is_restore=False,
        mutation_id="", stateful_evidence={}, active_mutation=None,
        pre_click_id="weekend", action={"action_type": "CLICK"},
        exploration_task_id=task["task_id"],
    )

    record_element_task_action(
        host, plan,
        RunCursor("weekend", {"screenshot": b"before"}),
        RunCursor("chat", {"screenshot": b"after"}),
        SimpleNamespace(event_index=1), stage="landing_processed",
    )

    assert host._element_exploration_task is None
    assert debug.events[-1][0] == "element_task_finished"
    assert debug.events[-1][1]["verdict"] == "complete"


def test_effective_task_actions_are_not_closed_at_the_old_six_step_limit():
    goal = _element(1, "Hidden target")
    intermediate = _element(2, "Continue route")
    event = {
        "action": {"action_type": "CLICK"},
        "outcome": "transitioned_consistent",
        "detail": "Reached another useful route state.",
        "landing_verified": True,
    }
    host = SimpleNamespace(
        _action_count=0,
        _state_data={"chat": {"page_name": "Chat info"}},
        graph=SimpleNamespace(
            action_attempt=lambda _index: event,
            action_edges=[], scroll_ledger={},
        ),
        review_debug=_Debug(), _element_exploration_task=None,
    )
    task = start_element_task(host, "chat", goal)
    plan = CandidateContext(
        element=intermediate, decision_reason="continue route",
        is_seed=False, is_stateful=False, is_restore=False,
        mutation_id="", stateful_evidence={}, active_mutation=None,
        pre_click_id="chat", action={"action_type": "CLICK"},
        exploration_task_id=task["task_id"],
    )
    cursor = RunCursor("chat", {"screenshot": b"screen"})

    for _ in range(7):
        record_element_task_action(
            host, plan, cursor, cursor,
            SimpleNamespace(event_index=1), stage="landing_processed")

    assert host._element_exploration_task is task
    assert task["actions_used"] == 7
    assert task_progress_facts(host, task)["loop_warning"] is False


def test_tool_call_returns_page_memory_without_executing_gui_action():
    goal = _element(1, "Add attachment")

    class Explorer:
        last_reason = ""
        last_prompts = []
        last_backend_runs = []
        last_raw_responses = []

        @staticmethod
        def choose(*_args, **_kwargs):
            raise AssertionError("active task must not select a new goal")

        @staticmethod
        def explore_target(_shot, _context):
            return {
                "decision": "tool",
                "current_page": {
                    "kind": "known", "page_ref": "p0",
                    "proposed_name": "", "reason": "Need page memory.",
                },
                "discovered_controls": [],
                "next_action": {
                    "type": "CALL_TOOL", "target": "page p0",
                    "point_1000": None, "direction": None,
                    "safety": "safe", "action_role": "other",
                    "reason": "Recall the known page.",
                    "expected_result": "Known Regions are returned.",
                    "tool_name": "recall_page",
                    "arguments": {"page_ref": "p0"},
                },
                "reason": "Recall the known page.",
            }

    host = _host([goal], Explorer())
    task = start_element_task(host, "chat", goal)
    outcome = plan_candidate(
        host, RunCursor("chat", {"screenshot": _shot()}), [goal])

    assert outcome.directive is StageDirective.CONTINUE
    assert outcome.candidate is None
    assert task["actions_used"] == 0
    assert task["tool_calls_used"] == 1
    assert task["history"][-1]["outcome"] == "tool_result"
    assert task["history"][-1]["tool_result"]["data"][
        "page_name"] == "Chat info"
    assert current_region_directory(host, "chat")["regions"][0][
        "region_ref"] == "r0"


def test_defer_after_verified_goal_action_completes_without_failure():
    goal = _element(1, "Open Weekend Plan")
    other = _element(2, "Back to chats")
    failures = []

    class Explorer:
        last_reason = ""
        last_prompts = []
        last_backend_runs = []
        last_raw_responses = []

        @staticmethod
        def explore_target(_shot, _context):
            return {
                "decision": "defer", "selected_entry_id": None,
                "reason": "The target page is already open.",
            }

    states = {
        "chat": {
            "page_name": "Chats", "elements": [goal],
            "semantic_blocks": [],
        },
        "weekend": {
            "page_name": "Weekend Plan", "elements": [other],
            "semantic_blocks": [{
                "region_id": "r1", "role": "Chat actions"}],
        },
    }
    host = _host([other], Explorer(), states=states)
    host._record_click_failure = lambda state, target, reason: (
        failures.append((state, target.name, reason)) or 1)
    task = start_element_task(host, "chat", goal)
    task["history"] = [{
        "step": 1,
        "selected_target": "Weekend Plan",
        "goal_action": True,
        "action": {"action_type": "CLICK"},
        "source_page": "Chats",
        "outcome": "transitioned_consistent",
        "detail": "Opened Weekend Plan.",
        "landing_page": "Weekend Plan",
        "landing_verified": True,
    }]

    outcome = plan_candidate(
        host, RunCursor("weekend", {"screenshot": b"screen"}), [other])

    assert outcome.directive is StageDirective.CONTINUE
    assert outcome.candidate is None
    assert host._element_exploration_task is None
    assert failures == []
    assert host.review_debug.events[-1][0] == "element_task_finished"
    assert host.review_debug.events[-1][1]["verdict"] == "complete"
