import io
import json
from types import SimpleNamespace

from PIL import Image

from gui_rewalk.src.core.visual_traversal.runtime.autonomous_page_session import (
    PageSessionLedger,
    _build_prompt,
    run_page_session_traversal,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_runtime import (
    AutonomousTraversalRuntime,
)


def _png(color):
    stream = io.BytesIO()
    Image.new("RGB", (120, 80), color).save(stream, format="PNG")
    return stream.getvalue()


class _Agent:
    model = "fake-page-session"

    def __init__(self, turns):
        self.turns = list(turns)
        self.backend_runs = []

    def invoke_specialist(self, **_kwargs):
        return self.turns.pop(0)


class _Env:
    vm_platform = "desktop"

    def __init__(self, before, after):
        self.observation = {"screenshot": before}
        self.after = after
        self.actions = []

    def _get_obs(self):
        return self.observation

    def step(self, action, pause=0):
        self.actions.append(action)
        self.observation = {"screenshot": self.after}
        return self.observation


def test_page_session_prompt_keeps_eight_settled_actions():
    history = [{
        "kind": "page_session_update", "screen": "Clock",
        "outcome": "recorded", "detail": "not an action",
    }]
    history.extend({
        "kind": "action", "screen": "Clock", "action": "CLICK",
        "target": f"Control {index}", "outcome": "observed_change",
        "detail": f"Control {index} opened its visible surface.",
        "landed_screen": f"Page {index}",
        "validated_action": {
            "operation": "click", "purpose": "navigation",
            "arguments": {
                "target": f"Control {index}",
                "point_1000": [100 + index, 200 + index],
            },
        },
    } for index in range(10))
    history.append({
        "kind": "action", "screen": "Clock", "action": "CLICK",
        "target": "Pending control", "outcome": "awaiting_observation",
    })
    host = SimpleNamespace(
        app_name="Clock", platform="desktop", action_count=11,
        max_actions=20,
        protocol_map=SimpleNamespace(
            current_page="Clock", current_variant="default",
            connections=[],
        ),
    )

    prompt = _build_prompt(
        host, PageSessionLedger(), history,
        pending=None, correction="", scope_unknown=False,
    )
    payload = json.loads(prompt[prompt.index("{"):])

    assert [item["arguments"]["target"]
            for item in payload["recent_actions"]] == [
        f"Control {index}" for index in range(2, 10)
    ]
    assert payload["recent_actions"][0]["purpose"] == "navigation"
    assert payload["recent_actions"][0]["operation"] == "click"
    assert payload["recent_actions"][-1]["landed_page"] == "Page 9"
    assert payload["recent_actions"][-1]["result"] == (
        "Control 9 opened its visible surface.")
    assert "recent_events" not in payload


def _screen(identity):
    return {
        "name": "Clock",
        "identity": identity,
        "summary": "Clock main page",
        "surface_kind": "page",
        "variant": {
            "name": "default",
            "identity": identity,
            "visible_predicates": ["Clock title is visible"],
        },
    }


def test_page_session_records_and_executes_in_one_turn(tmp_path):
    before = _png("white")
    after = _png("gray")
    first = {
        "app_scope": "target_app",
        "screen": _screen("new"),
        "reason": "The Search field is visible and accepts a harmless query.",
        "workspace_update": {
            "strategy": "Enter a query and inspect the visible result.",
            "todos": [{
                "id": "", "text": "Inspect Search", "status": "in_progress",
                "reason": "It may reveal a result surface.",
            }],
            "regions": [{
                "id": "", "name": "Main controls",
                "summary": "Primary controls for this page.",
            }],
            "operations": [{
                "id": "", "region_name": "Main controls",
                "operation": "input_text", "target": "Search field",
                "status": "pending", "reason": "Shows query results.",
                "result": "",
            }],
            "page_status": "active",
        },
        "action": {
            "purpose": "operation_attempt", "safety": "safe",
            "tool_name": "input_text",
            "tool_arguments": {
                "target": "Search field", "point_1000": [500, 500],
                "text": "London",
            },
        },
        "finish_exploration": False,
    }
    second = {
        "app_scope": "target_app",
        "screen": _screen("known"),
        "reason": "The click changed the visible surface as intended.",
        "previous_action": {
            "outcome": "changed", "matches_intent": True,
            "failure_kind": None,
            "reason": "A new reversible panel appeared after Add was clicked.",
        },
        "workspace_update": {
            "strategy": "The current page is complete.",
            "todos": [{
                "id": "t1", "text": "Inspect Search", "status": "completed",
                "reason": "The resulting surface was observed.",
            }],
            "regions": [],
            "operations": [],
            "page_status": "complete",
        },
        "action": None,
        "finish_exploration": True,
    }
    env = _Env(before, after)
    runtime = AutonomousTraversalRuntime(
        env=env,
        decision_agent=_Agent([first, second]),
        app_name="clock",
        output_root=str(tmp_path),
        max_states=0,
        max_actions=5,
    )

    graph = run_page_session_traversal(
        runtime, {"screenshot": before})

    assert graph.stop_reason == "agent_declared_complete"
    assert len(env.actions) == 1
    saved = json.loads(
        (tmp_path / "autonomous_page_sessions.json").read_text("utf-8"))
    page = saved["pages"][0]
    assert page["todos"][0]["status"] == "completed"
    assert page["operations"][0]["status"] == "verified"
    assert graph.autonomous_completion_summary["verification"] == (
        "agent_declared_not_framework_certified")


def test_page_session_ledger_restores_saved_status(tmp_path):
    ledger = PageSessionLedger()
    staged, issue = ledger.apply(
        "Inbox",
        "Mail list",
        {
            "strategy": "Inspect the toolbar.",
            "todos": [],
            "regions": [{
                "id": "", "name": "Toolbar", "summary": "Mail actions",
            }],
            "operations": [],
            "page_status": "complete",
        },
        reason="The toolbar is visible.",
    )
    assert issue == ""
    path = tmp_path / "autonomous_page_sessions.json"
    path.write_text(json.dumps(staged.snapshot()), encoding="utf-8")

    restored = PageSessionLedger.load(str(path))

    assert restored.page("Inbox")["strategy"] == "Inspect the toolbar."
    assert restored.page("Inbox")["regions"][0]["id"] == "r1"
