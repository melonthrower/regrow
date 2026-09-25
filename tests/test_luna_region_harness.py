import pytest

from tools.luna_region_harness import (
    CompiledRoute,
    DynamicInput,
    LunaResponses,
    RegionHarnessState,
    build_messages,
    build_completion,
    parse_turn,
    register_new_candidates,
    run_pilot,
    to_controller_action,
)


def test_known_selection_requires_existing_matching_owner_binding():
    state = RegionHarnessState.with_operation(
        region_ref="r1",
        canonical_operation_ref="co1",
        operation_ref="o1",
        action="click",
        target="Open Stopwatch",
    )

    turn = parse_turn({
        "previous_action": None,
        "region_updates": [],
        "next_action": {
            "region_ref": "r1",
            "canonical_operation_ref": "co1",
            "operation_ref": "o1",
            "purpose": "execute",
            "reason": "Visible and safe.",
        },
        "finish": False,
        "reason": "Continue.",
    }, state, pending_ref="")

    assert turn.next_action.operation_ref == "o1"


def test_exact_pending_settlement_may_schedule_the_next_known_action():
    state = RegionHarnessState.with_operation(
        region_ref="r1", canonical_operation_ref="co1", operation_ref="o1",
        action="click", target="Open Stopwatch",
    )

    turn = parse_turn({
        "previous_action": {
            "attempt_ref": "a1", "outcome": "success", "reason": "Settled.",
        },
        "region_updates": [],
        "next_action": {
            "region_ref": "r1", "canonical_operation_ref": "co1",
            "operation_ref": "o1", "purpose": "execute", "reason": "Next step.",
        },
        "finish": False,
        "reason": "The harness settles a1 before it executes o1.",
    }, state, pending_ref="a1")

    assert turn.previous_action.attempt_ref == "a1"
    assert turn.next_action.operation_ref == "o1"


def test_unknown_ref_and_owner_mismatch_are_rejected():
    state = RegionHarnessState.with_operation(
        region_ref="r1",
        canonical_operation_ref="co1",
        operation_ref="o1",
        action="click",
        target="Open Stopwatch",
    )

    with pytest.raises(ValueError, match="unknown operation_ref"):
        parse_turn({
            "previous_action": None,
            "region_updates": [],
            "next_action": {
                "region_ref": "r1",
                "canonical_operation_ref": "co1",
                "operation_ref": "o9",
                "purpose": "execute",
                "reason": "Visible and safe.",
            },
            "finish": False,
            "reason": "Continue.",
        }, state, pending_ref="")

    with pytest.raises(ValueError, match="does not own"):
        parse_turn({
            "previous_action": None,
            "region_updates": [],
            "next_action": {
                "region_ref": "r2",
                "canonical_operation_ref": "co1",
                "operation_ref": "o1",
                "purpose": "execute",
                "reason": "Visible and safe.",
            },
            "finish": False,
            "reason": "Continue.",
        }, state, pending_ref="")


def test_stable_ref_cards_stay_in_developer_message_and_frame_stays_dynamic():
    state = RegionHarnessState.with_operation(
        region_ref="r1",
        canonical_operation_ref="co1",
        operation_ref="o1",
        action="click",
        target="Open Stopwatch",
    )

    messages = build_messages(state, DynamicInput(
        screenshot=b"\x89PNG\r\n\x1a\nfixture",
        step="plan route",
        pending_result={"attempt_ref": "a1", "outcome": "success"},
        short_diff="Timer surface appeared.",
    ))

    assert messages[0]["role"] == "developer"
    assert "o1" in messages[0]["content"][0]["text"]
    assert "Timer surface appeared" not in messages[0]["content"][0]["text"]
    assert messages[1]["role"] == "user"
    assert messages[1]["content"][1]["type"] == "input_image"


def test_pending_settlement_sends_before_and_after_frames_only_in_user_message():
    state = RegionHarnessState.with_operation(
        region_ref="r1", canonical_operation_ref="co1", operation_ref="o1",
        action="click", target="Open Stopwatch",
    )

    messages = build_messages(state, DynamicInput(
        screenshot=b"after-frame",
        before_screenshot=b"before-frame",
        step="settle a1",
        pending_result={"attempt_ref": "a1"},
    ))

    assert [item["type"] for item in messages[1]["content"]] == [
        "input_text", "input_image", "input_image",
    ]
    assert len(messages[0]["content"]) == 1


def test_compiled_route_requires_fresh_unique_safe_grounding():
    route = CompiledRoute(["o1", "o2"])

    assert route.next_operation() == "o1"
    assert route.consume_grounding("o1", "frame-1", {
        "target_visible": True,
        "identity_matches": True,
        "unique": True,
        "safe": True,
    }) == "o2"
    assert route.consume_grounding("o2", "frame-1", {
        "target_visible": True,
        "identity_matches": True,
        "unique": True,
        "safe": True,
    }) == "replan_required"


def test_new_region_candidates_receive_only_harness_allocated_refs():
    state = RegionHarnessState()
    turn = parse_turn({
        "previous_action": None,
        "region_updates": [{
            "status": "new",
            "region_ref": "",
            "candidate": {
                "name": "Bottom navigation",
                "operations": [{"action": "click", "target": "Open Stopwatch"}],
            },
        }],
        "next_action": None,
        "finish": False,
        "reason": "Register the visible surface first.",
    }, state, pending_ref="")

    created = register_new_candidates(turn, state)

    assert [(item.region_ref, item.canonical_operation_ref, item.operation_ref)
            for item in created] == [("r1", "co1", "o1")]


def test_completion_labels_teacher_mode_as_non_final_evidence():
    completion = build_completion(
        teacher_mode=True,
        status="partial",
        stop_reason="action_budget",
        actions=24,
        gaps=["o3 blocked"],
    )

    assert completion["evidence_class"] == "teacher_student_live_pilot"
    assert completion["luna_only_acceptance"] is False


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "model": "gpt-5.6-luna",
            "output_text": '{"ready":true}',
            "usage": {"input_tokens": 12, "input_tokens_details": {"cached_tokens": 8}},
        }


def test_responses_client_keeps_stable_and_dynamic_messages_separate(monkeypatch):
    captured = {}

    def post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse()

    monkeypatch.setattr("tools.luna_region_harness.requests.post", post)
    client = LunaResponses(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="gpt-5.6-luna",
        reasoning_effort="medium",
        timeout=30,
    )
    result, telemetry = client.call(
        role="region_planner",
        messages=[
            {"role": "developer", "content": [{"type": "input_text", "text": "stable"}]},
            {"role": "user", "content": [{"type": "input_text", "text": "dynamic"}]},
        ],
        schema={"type": "object", "properties": {"ready": {"type": "boolean"}}, "required": ["ready"], "additionalProperties": False},
    )

    assert result == {"ready": True}
    assert captured["url"] == "https://example.test/v1/responses"
    assert captured["json"]["input"][0]["role"] == "developer"
    assert captured["json"]["input"][1]["role"] == "user"
    assert captured["json"]["store"] is False
    assert telemetry["cached_tokens"] == 8


def test_controller_action_uses_raw_grounding_coordinates_for_bound_operation():
    binding = RegionHarnessState.with_operation(
        region_ref="r1",
        canonical_operation_ref="co1",
        operation_ref="o1",
        action="click",
        target="Open Stopwatch",
    ).operations["o1"]

    action = to_controller_action(binding, {"x": 1310, "y": 214})

    assert action == {
        "action_type": "CLICK",
        "parameters": {"x": 1310, "y": 214},
    }


def test_pilot_records_fresh_attempt_and_closes_only_after_exact_settlement(tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    before.write_bytes(b"before")
    after.write_bytes(b"after")

    class Controller:
        def __init__(self):
            self.calls = []

        def status(self):
            return {"status": "ready", "current_frame": str(before)}

        def action(self, action):
            self.calls.append(action)
            return {
                "attempt_id": "attempt_0001",
                "before": str(before),
                "after": str(after),
                "controller_error": "",
            }

    turns = iter([
        {
            "previous_action": None,
            "region_updates": [{
                "status": "new", "region_ref": "",
                "candidate": {
                    "name": "Bottom navigation",
                    "operations": [{"action": "click", "target": "Open Stopwatch"}],
                },
            }],
            "next_action": None,
            "finish": False,
            "reason": "Register first.",
        },
        {
            "previous_action": None,
            "region_updates": [],
            "next_action": {
                "region_ref": "r1", "canonical_operation_ref": "co1",
                "operation_ref": "o1", "purpose": "execute", "reason": "Visible.",
            },
            "finish": False,
            "reason": "Execute the known operation.",
        },
        {
            "previous_action": {
                "attempt_ref": "a1", "outcome": "success", "reason": "Stopwatch selected.",
            },
            "region_updates": [],
            "next_action": None,
            "finish": True,
            "reason": "The bounded fixture is closed.",
        },
    ])

    completion = run_pilot(
        root=tmp_path / "run",
        controller=Controller(),
        planner=lambda _state, _dynamic: next(turns),
        grounder=lambda _binding, _frame: {
            "target_visible": True, "identity_matches": True,
            "unique": True, "safe": True, "x": 120, "y": 240,
        },
        teacher_mode=True,
        max_actions=3,
        max_turns=5,
    )

    assert completion["status"] == "complete"
    assert completion["actions"] == 1
    assert (tmp_path / "run" / "attempts.jsonl").exists()


def test_pilot_returns_schema_owner_correction_then_accepts_same_frame_retry(tmp_path):
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"screen")

    class Controller:
        def status(self):
            return {"status": "ready", "current_frame": str(screenshot)}

        def action(self, _action):
            raise AssertionError("the malformed turn must not execute an action")

    turns = iter([
        {
            "previous_action": None,
            "region_updates": [{
                "status": "new", "region_ref": "unknown",
                "candidate": {"name": "Navigation", "operations": []},
            }],
            "next_action": None,
            "finish": False,
            "reason": "Malformed new candidate.",
        },
        {
            "previous_action": None,
            "region_updates": [{
                "status": "new", "region_ref": "",
                "candidate": {"name": "Navigation", "operations": []},
            }],
            "next_action": None,
            "finish": True,
            "reason": "No executable fixture operation remains.",
        },
    ])

    completion = run_pilot(
        root=tmp_path / "retry-run",
        controller=Controller(),
        planner=lambda _state, _dynamic: next(turns),
        grounder=lambda _binding, _frame: {},
        teacher_mode=True,
        max_actions=1,
        max_turns=4,
    )

    assert completion["status"] == "complete"
    assert (tmp_path / "retry-run" / "harness_rejections.jsonl").exists()


def test_pilot_rejects_finish_until_every_known_operation_is_settled(tmp_path):
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"screen")

    class Controller:
        def __init__(self):
            self.count = 0

        def status(self):
            return {"status": "ready", "current_frame": str(screenshot)}

        def action(self, action):
            self.count += 1
            return {
                "attempt_id": f"attempt_{self.count:04d}",
                "before": str(screenshot), "after": str(screenshot), "controller_error": "",
            }

    turns = iter([
        {
            "previous_action": None,
            "region_updates": [{"status": "new", "region_ref": "", "candidate": {
                "name": "Navigation", "operations": [
                    {"action": "click", "target": "One"},
                    {"action": "click", "target": "Two"},
                ],
            }}],
            "next_action": None, "finish": False, "reason": "Register candidates.",
        },
        {
            "previous_action": None, "region_updates": [],
            "next_action": {"region_ref": "r1", "canonical_operation_ref": "co1", "operation_ref": "o1", "purpose": "execute", "reason": "First."},
            "finish": False, "reason": "Execute one.",
        },
        {
            "previous_action": {"attempt_ref": "a1", "outcome": "success", "reason": "One settled."},
            "region_updates": [], "next_action": None,
            "finish": True, "reason": "Incorrectly early finish.",
        },
        {
            "previous_action": None, "region_updates": [],
            "next_action": {"region_ref": "r1", "canonical_operation_ref": "co2", "operation_ref": "o2", "purpose": "execute", "reason": "Second."},
            "finish": False, "reason": "Execute two.",
        },
        {
            "previous_action": {"attempt_ref": "a2", "outcome": "success", "reason": "Two settled."},
            "region_updates": [], "next_action": None,
            "finish": True, "reason": "Closed.",
        },
    ])

    completion = run_pilot(
        root=tmp_path / "finish-retry",
        controller=Controller(),
        planner=lambda _state, _dynamic: next(turns),
        grounder=lambda _binding, _frame: {
            "target_visible": True, "identity_matches": True,
            "unique": True, "safe": True, "x": 10, "y": 20,
        },
        teacher_mode=True, max_actions=3, max_turns=8,
    )

    assert completion["status"] == "complete"
    assert completion["actions"] == 2


def test_safety_deferred_operation_does_not_stop_other_known_operation(tmp_path):
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"screen")

    class Controller:
        def action(self, action):
            return {
                "attempt_id": "attempt_0001", "before": str(screenshot),
                "after": str(screenshot), "controller_error": "",
            }

        def status(self):
            return {"status": "ready", "current_frame": str(screenshot)}

    turns = iter([
        {
            "previous_action": None,
            "region_updates": [{"status": "new", "region_ref": "", "candidate": {
                "name": "World", "operations": [
                    {"action": "click", "target": "Add World Clock"},
                    {"action": "click", "target": "Open application menu"},
                ],
            }}],
            "next_action": None, "finish": False, "reason": "Register.",
        },
        {
            "previous_action": None, "region_updates": [],
            "next_action": {"region_ref": "r1", "canonical_operation_ref": "co1", "operation_ref": "o1", "purpose": "execute", "reason": "Unsafe first choice."},
            "finish": False, "reason": "Try o1.",
        },
        {
            "previous_action": None, "region_updates": [],
            "next_action": {"region_ref": "r1", "canonical_operation_ref": "co2", "operation_ref": "o2", "purpose": "execute", "reason": "Safe alternative."},
            "finish": False, "reason": "Try o2.",
        },
        {
            "previous_action": {"attempt_ref": "a1", "outcome": "success", "reason": "Menu opened."},
            "region_updates": [], "next_action": None,
            "finish": True, "reason": "Only deferred o1 remains.",
        },
    ])

    def grounder(binding, _frame):
        if binding.operation_ref == "o1":
            return {
                "target_visible": False, "identity_matches": False,
                "unique": False, "safe": False, "reason": "safety-stop: persistent action",
            }
        return {
            "target_visible": True, "identity_matches": True,
            "unique": True, "safe": True, "x": 10, "y": 20,
        }

    completion = run_pilot(
        root=tmp_path / "safety-defer", controller=Controller(),
        planner=lambda _state, _dynamic: next(turns), grounder=grounder,
        teacher_mode=True, max_actions=3, max_turns=8,
    )

    assert completion["actions"] == 1
    assert completion["status"] == "partial"
    assert completion["gaps"] == ["safety-stop: o1"]


def test_back_operation_executes_without_calling_grounder(tmp_path):
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"screen")

    class Controller:
        def __init__(self):
            self.actions = []

        def status(self):
            return {"status": "ready", "current_frame": str(screenshot)}

        def action(self, action):
            self.actions.append(action)
            return {
                "attempt_id": "attempt_0001", "before": str(screenshot),
                "after": str(screenshot), "controller_error": "",
            }

    controller = Controller()
    turns = iter([
        {
            "previous_action": None,
            "region_updates": [{"status": "new", "region_ref": "", "candidate": {
                "name": "Foreground menu", "operations": [{"action": "back", "target": "Close menu"}],
            }}],
            "next_action": None, "finish": False, "reason": "Register Back.",
        },
        {
            "previous_action": None, "region_updates": [],
            "next_action": {"region_ref": "r1", "canonical_operation_ref": "co1", "operation_ref": "o1", "purpose": "recover", "reason": "Close menu."},
            "finish": False, "reason": "Execute Back.",
        },
        {
            "previous_action": {"attempt_ref": "a1", "outcome": "success", "reason": "Menu closed."},
            "region_updates": [], "next_action": None,
            "finish": True, "reason": "Closed.",
        },
    ])

    completion = run_pilot(
        root=tmp_path / "back-without-grounder", controller=controller,
        planner=lambda _state, _dynamic: next(turns),
        grounder=lambda _binding, _frame: (_ for _ in ()).throw(AssertionError("Back must not call Grounder")),
        teacher_mode=True, max_actions=2, max_turns=5,
    )

    assert completion["status"] == "complete"
    assert controller.actions == [{"action_type": "PRESS", "parameters": {"key": "ESC"}}]
