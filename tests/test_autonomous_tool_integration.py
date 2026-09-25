"""Offline integration checks for the autonomous tool path."""

from __future__ import annotations

import io
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from gui_rewalk.src.core.visual_traversal.runtime import autonomous_loop as loop
from gui_rewalk.src.core.visual_traversal.runtime import autonomous_recovery
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_agent import (
    INTERRUPTION_ROUND_LIMIT,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_completion import (
    TASK_REJECTION_LIMIT,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_entry_tools import (
    EntryStatus,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_prompt import (
    _history_summary,
    build_prompt,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_protocol import (
    available_tool_catalog,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_action_tools import (
    PreviousToolReview,
    action_tool_catalog,
    validate_action_tool_call,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_region_tools import (
    screenshot_frame_id,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_runtime import (
    _page_state_id,
    _record_agent_inferred_edges,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_schema import (
    response_schema_for_tools,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_scheduling import (
    _repeat_no_change_scroll_issue,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_turn import (
    ExplorationTask,
    PendingLandingPage,
    PreviousAssessment,
    SurfaceRegistration,
)


def _png(color: str) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (100, 80), color).save(stream, format="PNG")
    return stream.getvalue()


def _turn(
    screen: str,
    *,
    action: str,
    identity: str = "known",
    target: str = "",
    tool_name: str = "",
    tool_arguments=None,
    review=None,
    page_update=None,
    entry_review=None,
    previous_outcome: str = "not_applicable",
    previous_target: str = "",
) -> loop.AutonomousTurn:
    return loop.AutonomousTurn(
        screen_name=screen,
        previous=PreviousAssessment(
            outcome=previous_outcome,
            reason=(
                "Observed the requested outcome"
                if previous_outcome != "not_applicable"
                else "No previous action"
            ),
        ),
        decision=loop.AutonomousDecision(
            action=action,
            target=target,
            point_1000=None,
            direction="",
            reason=f"Exercise {tool_name or action}",
            tool_name=tool_name,
            tool_arguments=dict(tool_arguments or {}),
        ),
        registration=SurfaceRegistration(
            identity=identity,
            matched_page_name=screen if identity == "known" else "",
            variant_name="default",
            variant_identity=identity,
            visible_predicates=[],
        ),
        previous_tool_review=(
            PreviousToolReview(**review) if review else None
        ),
        page_update=page_update,
        entry_review=(
            loop.EntryReview(independent_entries=list(entry_review))
            if entry_review is not None else None
        ),
    )


class _Agent:
    model = "offline-agent"

    def __init__(self, turns, *, identity_result=None):
        self._turns = iter(turns)
        self._staged_turns = []
        self._identity_result = identity_result
        self.calls = []
        self.backend_runs = []

    def decide(self, screenshot, history, **values):
        self.calls.append((screenshot, list(history), dict(values)))
        if self._staged_turns:
            return self._staged_turns.pop(0)
        try:
            turn = next(self._turns)
        except StopIteration:
            return None
        phase = str(
            ((values.get("exploration_map") or {}).get("task") or {})
            .get("phase") or ""
        )
        if (
            phase == "identify_page"
            and turn.registration.identity in {"known", "new"}
            and turn.registration.variant_identity in {"known", "new"}
            and turn.decision.tool_name not in {
                "page_identity", "report_record_error",
                "handle_interruption",
            }
        ):
            self._staged_turns.append(replace(
                turn,
                decision=loop.AutonomousDecision(
                    action="NONE",
                    target="",
                    point_1000=None,
                    direction="",
                    reason="Fixture Variant identity turn",
                ),
                page_update=None,
                entry_review=None,
            ))
        return turn

    def resolve_page_identity(self, _request):
        return dict(self._identity_result or {})

    def review_region_proposal(self, request):
        regions = []
        revisions = []
        for region in request.get("existing_regions") or []:
            if not isinstance(region, dict):
                continue
            name = str(region.get("name") or "").strip()
            if not name:
                continue
            regions.append({
                "name": name,
                "summary": str(region.get("summary") or name),
            })
            revisions.append({
                "old_region": name,
                "decision": "keep",
                "reason": "The fixture Region remains a stable component.",
            })
        return {
            "regions": regions,
            "revisions": revisions,
            "reason": "The fixture Region proposal is complete and coherent.",
        }

    def review_entry_candidates(self, request):
        return {
            "independent_entries": [{
                "region_name": item.get("region_name"),
                "target": item.get("target"),
            } for item in request.get("candidates") or []],
            "deferred_entries": [],
            "deferred_regions": [],
            "reason_consistent": True,
            "reason": "The fixture candidates represent primary functions.",
        }


class _Env:
    vm_platform = "local_html"

    def __init__(self, initial, results=()):
        self.current = initial
        self.results = list(results)
        self.actions = []

    def _get_obs(self):
        return self.current

    def step(self, action, pause=0):
        self.actions.append((action, pause))
        if self.results:
            self.current = self.results.pop(0)
        return self.current


class _AndroidEnv(_Env):
    vm_platform = "androidworld"


def _runtime(tmp_path, initial, turns, *, results=(),
             identity_result=None, max_actions=4, env=None):
    agent = _Agent(
        turns,
        identity_result=identity_result,
    )
    env = env or _Env(initial, results)
    runtime = loop.AutonomousTraversalRuntime(
        env=env,
        decision_agent=agent,
        app_name="fixture",
        output_root=str(tmp_path),
        max_states=20,
        max_actions=max_actions,
    )
    return runtime, env, agent


def _bind_incomplete_page(runtime, page_name: str, screenshot: bytes) -> None:
    canonical, issue = runtime.protocol_map.observe(
        name=page_name,
        summary=f"Visible {page_name}",
        identity="new",
        matched_page_name="",
        surface_kind="page",
        regions=(),
        screenshot=screenshot,
        commit_regions=False,
    )
    assert (canonical, issue) == (page_name, "")
    state = loop._region_state(runtime, page_name)
    frame_id = screenshot_frame_id(screenshot)
    state_id = _page_state_id(
        runtime, page_name, runtime.protocol_map.current_variant)
    state.observe_frame(frame_id, state_id)
    state.apply_agent_update([{
        "name": "Main",
        "coverage_complete": False,
    }], frame_id=frame_id)
    region_ref, _ = runtime.region_registry.bind(
        page_name=page_name,
        region_name="Main",
        state_id=state_id,
        summary="Fixture main content",
    )
    state.set_region_ref("Main", region_ref)
    runtime.protocol_map.upsert_regions(
        page_name, state.snapshot().get("regions") or [])


def _accept_entry_audit(runtime, page_name: str, region_name: str) -> None:
    """Give a focused fixture the accepted review required before Entry work."""
    runtime.entry_review_audits.setdefault(page_name.casefold(), {})[
        region_name.casefold()
    ] = {
        "page_name": page_name,
        "region_name": region_name,
        "status": "complete",
        "coverage_basis": "fixture",
    }


def _accept_review():
    return {
        "decision": "accept",
        "reason": "The proposal matches the current screenshot.",
    }


def test_interruption_specialist_binds_hover_then_reviewed_click(
    tmp_path,
) -> None:
    before = {"screenshot": _png("white")}
    hovered = {"screenshot": _png("silver")}
    cleared = {"screenshot": _png("green")}
    turns = [
        _turn(
            "World",
            action="CALL_TOOL",
            tool_name="handle_interruption",
            tool_arguments={
                "suspected_surface": "Software Updates notification card",
                "obstruction_reason": "It covers the Alarms tab.",
            },
        ),
        _turn(
            "World",
            action="CALL_TOOL",
            tool_name="report_app_scope",
            tool_arguments={"classification": "target_app_obstructed"},
        ),
        _turn(
            "World",
            action="NONE",
            previous_outcome="changed",
        ),
        _turn(
            "World",
            action="CALL_TOOL",
            tool_name="handle_interruption",
            tool_arguments={
                "suspected_surface": "Software Updates notification card",
                "obstruction_reason": "It still covers the Alarms tab.",
            },
        ),
        _turn(
            "World",
            action="NONE",
            previous_outcome="changed",
        ),
    ]
    runtime, env, _agent = _runtime(
        tmp_path,
        before,
        turns,
        results=[hovered, cleared],
        max_actions=2,
    )
    class _Owner:
        @staticmethod
        def is_foreground():
            return None if len(env.actions) == 1 else True

    runtime.platform = "desktop"
    runtime.desktop_window_owner = _Owner()
    _bind_incomplete_page(runtime, "World", before["screenshot"])
    plans = iter([{
        "surface_is_temporary": True,
        "blocks_current_target": True,
        "strategy": "hover",
        "target": "Software Updates notification card",
        "point_1000": [530, 60],
        "target_is_close_control": False,
        "reason": "Hover the visible notification to reveal its controls.",
    }, {
        "surface_is_temporary": True,
        "blocks_current_target": True,
        "strategy": "click",
        "target": "Software Updates notification close button",
        "point_1000": [715, 45],
        "target_is_close_control": True,
        "reason": "The notification-owned X is now visibly present.",
    }])
    runtime.interruption_reviewer = lambda _request: next(plans)
    click_reviews = []
    def review_click(request):
        click_reviews.append(request)
        return {
            "decision": "approve",
            "observed_target": "Software Updates notification close button",
            "point_matches_target": True,
            "target_matches_request": True,
            "risk": "safe",
            "reason": "The visible X belongs directly to the notification.",
        }
    runtime.click_reviewer = review_click

    graph = loop.run_autonomous_traversal(runtime, before)

    assert graph.stop_reason == "max_actions"
    assert [item[0]["action_type"] for item in env.actions] == [
        "HOVER", "CLICK",
    ]
    assert env.actions[0][0]["parameters"]["dwell_ms"] == 700
    assert env.actions[1][0]["parameters"]["button"] == "left"
    trace = _trace(tmp_path)
    handlers = [
        item for item in trace["history"]
        if item.get("tool_name") == "handle_interruption"
    ]
    assert [
        item["tool_result"]["data"]["strategy"] for item in handlers
    ] == ["hover", "click"]
    assert len(click_reviews) == 1
    assert click_reviews[0]["target"].endswith("close button")
    assert {
        "current_screenshot", "target", "point_1000", "operation",
    }.issubset(click_reviews[0])
    assert any(
        item.get("kind") == "app_scope_resolution"
        and item.get("outcome") == "target_app_obstructed"
        and item.get("semantic_graph_recorded") is False
        for item in trace["history"]
    )
    assert (
        tmp_path / "action_attempts" / "000001" / "before.png"
    ).is_file()
    assert (
        tmp_path / "action_attempts" / "000002" / "before.png"
    ).is_file()


def test_page_stage_executes_reviewed_interruption_without_registration(
    tmp_path,
) -> None:
    blocked = {"screenshot": _png("white")}
    cleared = {"screenshot": _png("green")}
    runtime, env, _agent = _runtime(
        tmp_path,
        blocked,
        [_turn(
            "Unknown", action="CALL_TOOL", identity="new",
            tool_name="handle_interruption", tool_arguments={
                "suspected_surface": "Update notification",
                "obstruction_reason": "It hides the application title.",
            },
        ), _turn("Clock", action="NONE", identity="new")],
        results=[cleared],
        max_actions=1,
    )
    runtime.interruption_reviewer = lambda _request: {
        "surface_is_temporary": True,
        "blocks_current_target": True,
        "strategy": "click",
        "target": "Update notification close button",
        "point_1000": [900, 80],
        "target_is_close_control": True,
        "reason": "The visible X belongs to the blocking notification.",
    }
    runtime.click_reviewer = lambda _request: {
        "decision": "approve",
        "observed_target": "Update notification close button",
        "point_matches_target": True,
        "target_matches_request": True,
        "risk": "safe",
        "reason": "The point is on the notification-owned X.",
    }

    graph = loop.run_autonomous_traversal(runtime, blocked)

    assert graph.stop_reason == "max_actions"
    assert env.actions[0][0]["action_type"] == "CLICK"
    assert list(runtime.protocol_map.pages) == ["Clock"]
    assert list(runtime.protocol_map.pages["Clock"]["variants"]) == ["default"]
    assert runtime.pending_landing_page is None
    assert graph.graph.number_of_nodes() == 1
    assert [
        call[2]["exploration_map"]["task"]["phase"]
        for call in _agent.calls
    ] == ["identify_page", "identify_page", "identify_variant"]
    trace = _trace(tmp_path)
    recovery = next(
        item for item in trace["history"]
        if item.get("pre_registration_recovery") is True
        and item.get("outcome") == "executed"
    )
    assert recovery["obstructed_frame_registered"] is False
    assert not any(
        item.get("rejection", {}).get("code") == "page_context_missing"
        for item in trace["history"]
    )


def test_variant_stage_executes_interruption_back_without_registration(
    tmp_path,
) -> None:
    blocked = {"screenshot": _png("silver")}
    cleared = {"screenshot": _png("blue")}
    runtime, env, _agent = _runtime(
        tmp_path,
        blocked,
        [_turn(
            "Timer", action="CALL_TOOL", identity="new",
            tool_name="handle_interruption", tool_arguments={
                "suspected_surface": "Permission prompt",
                "obstruction_reason": "It covers the Timer controls.",
            },
        ), _turn("Timer", action="NONE", identity="new")],
        results=[cleared],
        max_actions=1,
    )
    runtime.pending_landing_page = PendingLandingPage(
        page_name="Timer", identity="new",
        summary="Timer setup", surface_kind="page",
    )
    runtime.interruption_reviewer = lambda _request: {
        "surface_is_temporary": True,
        "blocks_current_target": True,
        "strategy": "back",
        "target": "",
        "point_1000": None,
        "target_is_close_control": False,
        "reason": "Back dismisses this temporary prompt.",
    }

    graph = loop.run_autonomous_traversal(runtime, blocked)

    assert graph.stop_reason == "max_actions"
    assert env.actions[0][0] == {
        "action_type": "PRESS", "parameters": {"key": "esc"},
    }
    assert list(runtime.protocol_map.pages) == ["Timer"]
    assert list(runtime.protocol_map.pages["Timer"]["variants"]) == ["default"]
    assert runtime.pending_landing_page is None
    assert graph.graph.number_of_nodes() == 1
    assert [
        call[2]["exploration_map"]["task"]["phase"]
        for call in _agent.calls
    ] == ["identify_variant", "identify_page", "identify_variant"]
    trace = _trace(tmp_path)
    assert not any(
        item.get("rejection", {}).get("code") == "page_context_missing"
        for item in trace["history"]
    )


def test_changed_pre_registration_recovery_discards_stale_identity_assessment(
    tmp_path,
) -> None:
    blocked = {"screenshot": _png("silver")}
    cleared = {"screenshot": _png("green")}
    runtime, env, _agent = _runtime(
        tmp_path, blocked, [], results=[cleared])
    pending = loop.PendingAction(
        source=loop.ObservedScene(
            state_id="trusted-source",
            screenshot=_png("white"),
            page_name="World",
            variant_name="default",
        ),
        event_index=3,
        primitive={"action_type": "CLICK"},
        target="Open World",
        reason="Open World",
        history_index=0,
        evidence={"first_model_assessment": {"outcome": "changed"}},
        assessment=PreviousAssessment(
            outcome="changed", reason="The obstructed frame appeared."),
    )
    runtime.pending_page_identity = loop.PendingPageIdentity(
        status="known",
        data={"page_name": "World"},
        arguments={},
        stage="page",
    )
    runtime.pending_landing_page = PendingLandingPage(
        page_name="World", identity="known",
        summary="World clock", surface_kind="page",
    )
    runtime.protocol_map.current_page = "World"
    runtime.protocol_map.current_variant = "default"
    runtime.identity_feedback = {
        "decision": "reject", "reason": "Bound to the blocked frame",
    }
    history = []

    observation = loop._execute_pre_registration_interruption(
        runtime,
        blocked["screenshot"],
        loop.AutonomousDecision(
            action="BACK",
            target="back",
            point_1000=None,
            direction="",
            reason="Dismiss the temporary blocker.",
            tool_name="navigate",
            tool_arguments={"operation": "back"},
        ),
        history,
        pending=pending,
        screen_name="Unknown",
        source_page="World",
    )

    assert observation == cleared
    assert pending.assessment is None
    assert "first_model_assessment" not in pending.evidence
    assert runtime.pending_page_identity is None
    assert runtime.pending_landing_page is None
    assert runtime.identity_feedback is None
    assert runtime.protocol_map.current_page == ""
    assert runtime.protocol_map.current_variant == ""
    assert history[-1]["semantic_graph_recorded"] is False
    assert history[-1]["frame_changed"] is True
    assert len(env.actions) == 1


def test_identity_recovery_cannot_exceed_action_budget(tmp_path) -> None:
    before = {"screenshot": _png("white")}
    blocked = {"screenshot": _png("silver")}
    runtime, env, _agent = _runtime(
        tmp_path,
        before,
        [
            _turn(
                "World", action="CALL_TOOL", identity="known",
                target="Open details", tool_name="click",
                tool_arguments={
                    "target": "Open details", "entry_id": "",
                    "point_1000": [500, 500],
                },
            ),
            _turn(
                "World", action="CALL_TOOL", identity="known",
                tool_name="handle_interruption",
                tool_arguments={
                    "suspected_surface": "Permission prompt",
                    "obstruction_reason": "It covers the landing page.",
                },
                previous_outcome="changed",
            ),
        ],
        results=[blocked],
        max_actions=1,
    )
    _bind_incomplete_page(runtime, "World", before["screenshot"])
    runtime.interruption_reviewer = lambda _request: {
        "surface_is_temporary": True,
        "blocks_current_target": True,
        "strategy": "back",
        "target": "",
        "point_1000": None,
        "target_is_close_control": False,
        "reason": "Back would dismiss the prompt.",
    }

    loop.run_autonomous_traversal(runtime, before)

    assert len(env.actions) == 1
    trace = _trace(tmp_path)
    rejection = next(
        item for item in trace["history"]
        if item.get("rejection", {}).get("code") == "max_actions_reached"
    )
    assert rejection["pre_registration_recovery"] is True


def test_identity_stage_wait_reassesses_original_action_on_fresh_frame(
    tmp_path,
) -> None:
    before = {"screenshot": _png("white")}
    blocked = {"screenshot": _png("silver")}
    cleared = {"screenshot": _png("green")}

    class _WaitClearingEnv(_Env):
        def _get_obs(self):
            if self.actions:
                self.current = cleared
            return self.current

    wait_turn = replace(
        _turn(
            "World", action="CALL_TOOL", identity="known",
            tool_name="handle_interruption", tool_arguments={
                "suspected_surface": "Loading veil",
                "obstruction_reason": "It temporarily covers the landing.",
            },
            previous_outcome="changed",
        ),
        previous=PreviousAssessment(
            outcome="changed", reason="The blocked frame appeared."),
    )
    recovered_turn = replace(
        _turn(
            "World", action="NONE", identity="known",
            previous_outcome="changed",
        ),
        previous=PreviousAssessment(
            outcome="changed", reason="The recovered World page appeared."),
    )
    env = _WaitClearingEnv(before, [blocked])
    runtime, env, _agent = _runtime(
        tmp_path,
        before,
        [
            _turn(
                "World", action="CALL_TOOL", identity="known",
                target="Open World", tool_name="click",
                tool_arguments={
                    "target": "Open World", "entry_id": "",
                    "point_1000": [500, 500],
                },
            ),
            wait_turn,
            recovered_turn,
        ],
        max_actions=1,
        env=env,
    )
    _bind_incomplete_page(runtime, "World", before["screenshot"])
    runtime.interruption_reviewer = lambda _request: {
        "surface_is_temporary": True,
        "blocks_current_target": True,
        "strategy": "wait",
        "target": "",
        "point_1000": None,
        "target_is_close_control": False,
        "reason": "The loading veil is already disappearing.",
    }

    graph = loop.run_autonomous_traversal(runtime, before)

    assert graph.stop_reason == "max_actions"
    assert len(env.actions) == 1
    attempt = graph.action_edges[0]["attempts"][0]
    assert attempt["evidence"]["model_assessment"]["reason"] == (
        "The recovered World page appeared.")


def test_interruption_specialist_cannot_authorize_an_unowned_click(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, env, _agent = _runtime(tmp_path, screen, [])
    _bind_incomplete_page(runtime, "World", screen["screenshot"])
    runtime.interruption_reviewer = lambda _request: {
        "surface_is_temporary": True,
        "blocks_current_target": True,
        "strategy": "click",
        "target": "Clocks window close button",
        "point_1000": [985, 65],
        "target_is_close_control": False,
        "reason": "The point belongs to the application window, not the banner.",
    }
    history = []

    decision = loop._interruption_plan(
        runtime,
        screen["screenshot"],
        "World",
        {
            "suspected_surface": "Software Updates notification card",
            "obstruction_reason": "It covers the Alarms tab.",
        },
        history,
    )

    assert decision is None
    assert env.actions == []
    assert history[-1]["tool_result"]["data"]["strategy"] == "unresolved"
    assert "not strictly confirm" in history[-1]["tool_result"]["data"]["reason"]


def test_interruption_specialist_cannot_click_the_whole_surface_as_close(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, env, _agent = _runtime(tmp_path, screen, [])
    _bind_incomplete_page(runtime, "World", screen["screenshot"])
    runtime.interruption_reviewer = lambda _request: {
        "surface_is_temporary": True,
        "blocks_current_target": True,
        "strategy": "click",
        "target": "Software Updates notification card",
        "point_1000": [530, 60],
        "target_is_close_control": True,
        "reason": "Clicking the card may dismiss it.",
    }
    history = []

    decision = loop._interruption_plan(
        runtime,
        screen["screenshot"],
        "World",
        {
            "suspected_surface": "Software Updates notification card",
            "obstruction_reason": "It covers the Alarms tab.",
        },
        history,
    )

    assert decision is None
    assert env.actions == []
    assert history[-1]["tool_result"]["data"]["strategy"] == "unresolved"
    assert "whole suspected interference surface" in (
        history[-1]["tool_result"]["data"]["reason"])


def test_interruption_handler_disappears_after_three_rounds_for_same_task(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    _bind_incomplete_page(runtime, "World", screen["screenshot"])
    loop._sync_exploration_task(runtime)
    runtime.interruption_task_key = loop._exploration_task_key(
        runtime.exploration_task)
    runtime.interruption_rounds = INTERRUPTION_ROUND_LIMIT

    names = {
        item["name"] for item in loop._dynamic_tool_catalog(
            runtime, screen["screenshot"])
    }

    assert "handle_interruption" not in names
    assert "hover" in names


def test_invalid_agent_turn_returns_the_concrete_protocol_error(tmp_path) -> None:
    screen = {"screenshot": _png("white")}
    runtime, env, agent = _runtime(tmp_path, screen, [])
    agent.last_error = "CALL_TOOL requires a tool exposed in the current turn"

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "all_remaining_work_suspended"
    assert env.actions == []
    errors = [
        item for item in _trace(tmp_path)["history"]
        if item.get("kind") == "model_error"
    ]
    assert len(errors) == TASK_REJECTION_LIMIT
    assert all(
        item["detail"]
        == "CALL_TOOL requires a tool exposed in the current turn"
        for item in errors
    )
    assert errors[-1]["rejection"]["code"] == "invalid_agent_turn"
    assert "exposed in the current turn" in errors[-1]["rejection"]["message"]


def _trace(tmp_path):
    return json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8")
    )


def test_all_public_tools_have_one_uniform_strict_descriptor() -> None:
    catalog = (
        available_tool_catalog(pending_identity=False)
        + action_tool_catalog()
    )
    expected = {
        "page_identity", "report_record_error", "reuse_entry_result",
        "defer_current_task",
        "handle_interruption", "click", "hover", "scroll", "navigate",
        "input_text",
    }
    assert {item["name"] for item in catalog} == expected
    common = {
        "name", "description", "input_schema", "effect", "returns",
        "requires_review", "executes_gui",
    }
    assert all(common <= set(item) for item in catalog)

    errors = []

    def check(value, path="$", *, require_all=True):
        if isinstance(value, dict):
            if value.get("type") == "object":
                properties = value.get("properties") or {}
                if value.get("additionalProperties") is not False:
                    errors.append(f"{path}: open object")
                required = set(value.get("required") or [])
                if not required <= set(properties):
                    errors.append(f"{path}: unknown required fields")
                if require_all and required != set(properties):
                    errors.append(f"{path}: incomplete required fields")
            for key, child in value.items():
                check(child, f"{path}.{key}", require_all=require_all)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                check(child, f"{path}[{index}]", require_all=require_all)

    for item in catalog:
        check(item["input_schema"], f"$.tools.{item['name']}")
    check(response_schema_for_tools(catalog), require_all=False)
    assert errors == []


def test_dynamic_catalog_combines_page_and_action_without_empty_fallback(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])

    names = {
        item["name"]
        for item in loop._dynamic_tool_catalog(runtime, screen["screenshot"])
    }

    assert {"page_identity", "click", "navigate"} <= names
    assert not ({"map_regions", "inspect_region", "reconcile_regions"} & names)
    assert "scroll" in names
    assert "input_text" not in names
    assert "defer_current_task" not in names
    assert build_prompt(
        [], app_name="fixture", platform="local_html", tool_catalog=[]
    ).rstrip().endswith("[]")


def test_dynamic_catalog_exposes_gesture_only_for_android(tmp_path) -> None:
    screen = {"screenshot": _png("white")}
    android_runtime, _env, _agent = _runtime(
        tmp_path, screen, [], env=_AndroidEnv(screen))

    android_names = {
        item["name"] for item in loop._dynamic_tool_catalog(
            android_runtime, screen["screenshot"])
    }

    assert "gesture" in android_names


def test_explore_entry_uses_the_compact_base_tool_view(tmp_path) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    frame_id = screenshot_frame_id(screen["screenshot"])
    runtime.protocol_map.observe(
        name="Home", summary="Known home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"],
    )
    state = loop._region_state(runtime, "Home")
    state.observe_frame(frame_id)
    state.apply_agent_update([{
        "name": "Main", "summary": "Visible content",
        "bbox_1000": [0, 0, 1000, 1000],
        "coverage_complete": True,
    }], frame_id=frame_id)
    _accept_entry_audit(runtime, "Home", "Main")
    runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id=frame_id,
        observations=[{"target": "Open details"}],
    )
    loop._sync_exploration_task(runtime)

    names = {
        item["name"]
        for item in loop._dynamic_tool_catalog(
            runtime, screen["screenshot"])
    }

    assert runtime.exploration_task.task_type == "explore_entry"
    assert names == {
        "page_identity", "report_record_error",
        "reuse_entry_result", "defer_current_task",
        "handle_interruption", "click", "hover", "scroll", "navigate",
    }
    view = loop._exploration_map_view(runtime, None)
    assert view["task"]["target"] == "Open details"
    assert view["task"]["phase"] == "locate_entry"
    assert "survey_page_fact" not in view
    assert "pages" not in view
    assert "connections" not in view
    prompt = build_prompt(
        [], app_name="fixture", platform="local_html",
        exploration_map=view,
    )
    assert "当前任务是探索一个已经登记的入口" in prompt
    assert "当前任务是调查页面" not in prompt


def test_survey_page_view_keeps_compact_local_facts(tmp_path) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    frame_id = screenshot_frame_id(screen["screenshot"])
    runtime.protocol_map.observe(
        name="Home", summary="Known home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"],
    )
    state = loop._region_state(runtime, "Home")
    state.observe_frame(frame_id)
    state.apply_agent_update([{
        "name": "Main", "summary": "Partially seen content",
        "survey_memory": (
            "Continuous observations reached Privacy; continue down."),
        "bbox_1000": [0, 0, 1000, 1000],
        "coverage_complete": False,
    }], frame_id=frame_id)
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id=frame_id,
        observations=[{"target": "Open details"}],
    ).added[0]
    handled_id = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id=frame_id,
        observations=[{"target": "Open history"}],
    ).added[0]
    action = runtime.entry_ledger.begin_explicit_action(
        handled_id, frame_id=frame_id, page_name="Home")
    runtime.entry_ledger.finish_action(
        action.action_id, action_executed=True, outcome_verified=True,
        result="History page opened", destination_page="History",
    )
    loop._sync_exploration_task(runtime)

    view = loop._exploration_map_view(runtime, None)
    known_entries = view["survey_page_fact"]["known_entries"]
    entry = known_entries[0]

    assert runtime.exploration_task.task_type == "survey_page"
    assert view["task"]["phase"] == "survey_region"
    assert entry["target"] == "Open details"
    assert "temporary_bbox_1000" not in entry
    assert "observation_count" not in entry
    assert {item["target"] for item in known_entries} == {
        "Open details", "Open history",
    }
    assert all("id" not in item for item in known_entries)
    assert known_entries[-1] == {
        "target": "Open history",
        "region": "Main",
        "destination": "History",
    }
    assert "last_result" not in known_entries[-1]
    assert "status" not in known_entries[-1]
    assert view["survey_page_fact"]["regions"][0][
        "complete"] is False
    assert view["survey_page_fact"]["regions"][0]["survey_memory"] == (
        "Continuous observations reached Privacy; continue down.")
    assert "pages" not in view
    assert "connections" not in view
    assert "arrival_context" not in view


def test_route_stage_receives_task_route_but_not_full_graph_or_region_ledger(
    tmp_path,
) -> None:
    home = _png("white")
    settings = _png("gray")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": home}, [])
    for page_name, screenshot in (("Settings", settings), ("Home", home)):
        runtime.protocol_map.observe(
            name=page_name, summary=f"Visible {page_name}", identity="new",
            matched_page_name="", surface_kind="page", regions=(),
            screenshot=screenshot, commit_regions=False,
        )
    settings_scene = loop._register_scene(
        runtime, settings,
        _turn("Settings", action="NONE", identity="known"), "Settings")
    home_scene = loop._register_scene(
        runtime, home,
        _turn("Home", action="NONE", identity="known"), "Home")
    _complete = loop._region_state(runtime, "Home")
    _complete.observe_frame(screenshot_frame_id(home))
    _complete.apply_agent_update([{
        "name": "Main", "coverage_complete": True,
    }], frame_id=screenshot_frame_id(home))
    home_region_ref, _ = runtime.region_registry.bind(
        page_name="Home",
        region_name="Main",
        state_id=home_scene.state_id,
        summary="Visible Home main content",
    )
    _complete.set_region_ref("Main", home_region_ref)
    _pending = loop._region_state(runtime, "Settings")
    _pending.observe_frame(screenshot_frame_id(settings))
    _pending.apply_agent_update([{
        "name": "Settings list", "coverage_complete": False,
    }], frame_id=screenshot_frame_id(settings))
    settings_region_ref, _ = runtime.region_registry.bind(
        page_name="Settings",
        region_name="Settings list",
        state_id=settings_scene.state_id,
        summary="Visible Settings list",
    )
    _pending.set_region_ref("Settings list", settings_region_ref)
    runtime.protocol_map.connect("Home", "Settings", "CLICK", "Settings")
    runtime.graph.add_transition(
        home_scene.state_id,
        settings_scene.state_id,
        {"action_type": "CLICK", "selector": {"element_label": "Settings"}},
        element_label="Settings",
        landing_verified=True,
        target_page_name="Settings",
    )
    runtime.protocol_map.current_page = "Home"

    loop._sync_exploration_task(runtime)
    view = loop._exploration_map_view(runtime, None)

    assert view["task"]["phase"] == "route_to_page"
    assert view["task"]["page"] == "Settings"
    assert view["task"]["route"] == [{
        "from": "Home (default)",
        "via": "Settings",
        "to": "Settings (default)",
    }]
    assert "pages" not in view
    assert "connections" not in view
    assert "arrival_context" in view
    assert "survey_page_fact" not in view


def test_completed_regions_go_directly_to_completion_ready(
    tmp_path,
) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    runtime.protocol_map.observe(
        name="Home", summary="Known home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    state = loop._region_state(runtime, "Home")
    frame_id = screenshot_frame_id(screenshot)
    state.observe_frame(frame_id)
    state.apply_agent_update([
        {"name": "Header", "coverage_complete": True},
        {"name": "Cards", "coverage_complete": True},
    ], frame_id=frame_id)
    _accept_entry_audit(runtime, "Home", "Header")
    _accept_entry_audit(runtime, "Home", "Cards")
    loop._sync_exploration_task(runtime)
    view = loop._exploration_map_view(runtime, None)

    assert runtime.exploration_task is None
    assert loop._completion_gaps(runtime) == []


def test_scroll_frame_change_is_explicit_in_next_agent_view(tmp_path) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    pending = loop.PendingAction(
        source=loop.ObservedScene(
            state_id="state-home",
            screenshot=screenshot,
            page_name="Home",
            is_new=False,
        ),
        event_index=0,
        primitive={"action_type": "SCROLL"},
        target="Main",
        reason="Inspect more content",
        history_index=0,
        evidence={},
        validated_action=SimpleNamespace(
            operation="scroll",
            arguments={
                "container_hint": "outer page below the visible cards",
                "direction": "down",
                "point_1000": [500.0, 800.0],
            },
        ),
    )
    assert not hasattr(pending, "before_path")

    unchanged = loop._exploration_map_view(
        runtime, pending, current_screenshot=screenshot)
    changed = loop._exploration_map_view(
        runtime, pending, current_screenshot=_png("black"))

    assert "current_page" not in unchanged
    assert unchanged["arrival_context"]["source_page"] == "Home"
    assert "current_page" not in changed
    assert changed["arrival_context"]["source_page"] == "Home"
    assert "last_scroll_result" not in unchanged
    assert "last_scroll_result" not in changed


def test_exact_unchanged_scroll_repeat_is_rejected_before_execution(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    frame_id = screenshot_frame_id(screen["screenshot"])
    arguments = {
        "container_hint": "visible item list",
        "point_1000": [500, 800],
        "direction": "down",
        "amount": 300,
    }
    turns = [
        _turn(
            "Home", action="CALL_TOOL", target="visible item list",
            tool_name="scroll", tool_arguments=arguments,
        ),
        _turn(
            "Home", action="CALL_TOOL", target="visible item list",
            tool_name="scroll", tool_arguments=arguments,
            previous_outcome="no_visible_change",
            previous_target="visible item list",
        ),
        _turn(
            "Home", action="CALL_TOOL", target="visible item list",
            tool_name="scroll", tool_arguments=arguments,
        ),
    ]
    runtime, env, _agent = _runtime(tmp_path, screen, turns)
    _bind_incomplete_page(runtime, "Home", screen["screenshot"])

    loop.run_autonomous_traversal(runtime, screen)

    assert len(env.actions) == 1
    actions = [
        item for item in _trace(tmp_path)["history"]
        if item.get("kind") == "action"
    ]
    repeated = next(
        item for item in actions
        if item.get("rejection", {}).get("code")
        == "repeat_no_change_action"
    )
    assert repeated["outcome"] == "not_executed"
    assert "Change container_hint, point_1000, direction, or amount" in (
        repeated["rejection"]["message"])
    changed_point = validate_action_tool_call(
        "scroll",
        {**arguments, "point_1000": [600, 800]},
        latest_frame_id=frame_id,
        platform="local_html",
    )
    assert _repeat_no_change_scroll_issue(
        actions, changed_point, frame_id) == ""


def test_completed_page_starts_in_completion_ready(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, agent = _runtime(
        tmp_path,
        screen,
        [
            _turn(
                "Home", action="CALL_TOOL",
                tool_name="finish_exploration",
                tool_arguments={
                    "reason": "All framework work is complete.",
                    "unreachable_evidence": [],
                },
            ),
        ],
    )
    runtime.protocol_map.observe(
        name="Home", summary="Visible Home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"],
    )
    state = loop._region_state(runtime, "Home")
    frame_id = screenshot_frame_id(screen["screenshot"])
    state_id = _page_state_id(
        runtime, "Home", runtime.protocol_map.current_variant)
    state.observe_frame(frame_id, state_id)
    state.apply_agent_update([{
        "name": "Main cards", "coverage_complete": True,
    }], frame_id=frame_id)
    region_ref, _ = runtime.region_registry.bind(
        page_name="Home",
        region_name="Main cards",
        state_id=state_id,
        summary="Fixture card content",
    )
    state.set_region_ref("Main cards", region_ref)
    runtime.protocol_map.upsert_regions(
        "Home", state.snapshot().get("regions") or [])
    runtime.entry_review_audits.setdefault("home", {})["main cards"] = {
        "page_name": "Home",
        "region_name": "Main cards",
        "frame_id": frame_id,
        "status": "complete",
        "coverage_basis": "fixture",
    }
    runtime.region_probe_progress[region_ref] = {"status": "complete"}

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "framework_complete"
    assert "scroll_frontier_reviewed" not in state.snapshot()
    phases = [call[2]["exploration_map"]["task"]["phase"]
              for call in agent.calls]
    assert phases == []


def test_survey_scroll_can_discover_entry_outside_initial_region_boundary(
    tmp_path,
) -> None:
    first = {"screenshot": _png("white")}
    lower = {"screenshot": _png("gray")}
    frame_id = screenshot_frame_id(first["screenshot"])
    runtime, env, _agent = _runtime(
        tmp_path,
        first,
        [
            _turn(
                "Home", action="CALL_TOOL", tool_name="scroll",
                tool_arguments={
                    "container_hint": "outer page below the visible cards",
                    "point_1000": [900, 850],
                    "direction": "down",
                    "amount": 600,
                },
            ),
            _turn(
                "Home", action="NONE", previous_outcome="changed",
                previous_target="outer page below the visible cards",
            ),
            _turn(
                "Home", action="NONE",
                page_update=loop.PageUpdate(
                    page_name="Home",
                    regions=[{
                        "name": "Cards",
                        "survey_memory": (
                            "Outer-page probe revealed the lower action row."),
                        "coverage_complete": True,
                    }],
                    new_entries=[{
                        "region_name": "Cards",
                        "target": "View journey",
                    }],
                ),
            ),
            _turn(
                "Home", action="NONE",
                entry_review=[{
                    "region_name": "Cards",
                    "target": "View journey",
                }],
            ),
        ],
        results=[lower],
        max_actions=0,
    )
    runtime.protocol_map.observe(
        name="Home", summary="Visible Home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=first["screenshot"],
    )
    state = loop._region_state(runtime, "Home")
    state_id = _page_state_id(
        runtime, "Home", runtime.protocol_map.current_variant)
    state.observe_frame(frame_id, state_id)
    state.apply_agent_update([{
        "name": "Cards", "coverage_complete": False,
    }], frame_id=frame_id)
    region_ref, _ = runtime.region_registry.bind(
        page_name="Home",
        region_name="Cards",
        state_id=state_id,
        summary="Fixture card content",
    )
    state.set_region_ref("Cards", region_ref)
    runtime.protocol_map.upsert_regions(
        "Home", state.snapshot().get("regions") or [])

    loop.run_autonomous_traversal(runtime, first)

    assert [item[0]["action_type"] for item in env.actions] == ["SCROLL"]
    assert runtime.entry_ledger.get("ae1").target == "View journey"
    snapshot = state.snapshot()
    assert snapshot["coverage_complete"] is True
    assert snapshot["regions"][0]["survey_memory"] == (
        "Outer-page probe revealed the lower action row.")
    action = next(
        item for item in _trace(tmp_path)["history"]
        if item.get("kind") == "action" and item.get("action") == "SCROLL"
    )
    assert action["action_tool_result"]["container_hint"] == (
        "outer page below the visible cards")


def test_survey_page_rejects_a_functional_entry_click(tmp_path) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.exploration_task = ExplorationTask(
        task_type="survey_page", task_id="survey:Home", page_name="Home",
    )
    decision = loop.AutonomousDecision(
        action="CLICK", target="Open details", point_1000=[500, 500],
        direction="", reason="Probe the registered entry",
        tool_name="click",
        tool_arguments={"entry_id": "ae1"},
    )

    issue = loop._survey_entry_click_issue(runtime, decision)

    assert "survey_page only registers entry ae1" in issue


def test_dynamic_catalog_keeps_page_and_action_tools_during_landing_assessment(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])

    names = {
        item["name"]
        for item in loop._dynamic_tool_catalog(runtime, screen["screenshot"])
    }

    assert "page_identity" in names
    assert "click" in names
    assert "map_regions" not in names


def test_resumed_unbound_page_keeps_page_and_action_tools_visible(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.protocol_map.pages["Home"] = {
        "name": "Home",
        "internal_page_id": "auto_page_1",
        "summary": "Known home page",
        "surface_kind": "page",
        "identity_status": "known",
        "regions": {},
        "unreachable_evidence": [],
    }
    runtime.protocol_map.current_page = ""

    names = {
        item["name"]
        for item in loop._dynamic_tool_catalog(runtime, screen["screenshot"])
    }

    assert not ({"map_regions", "inspect_region", "reconcile_regions"} & names)
    assert {"page_identity", "click", "navigate"} <= names


def test_pending_page_review_keeps_direct_page_update_action_catalog(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.pending_page_identity = loop.PendingPageIdentity(
        status="known",
        data={"page_name": "Settings", "matched_page_name": "Settings"},
        arguments={},
    )

    names = {
        item["name"]
        for item in loop._dynamic_tool_catalog(runtime, screen["screenshot"])
    }

    assert "page_identity" in names
    assert "map_regions" not in names
    assert {"click", "navigate"} <= names


def test_framework_dispatches_one_agent_reported_entry_until_verified(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.entry_ledger.record_agent_update(
        page_name="Settings",
        region_name="Alarms",
        frame_id="frame-1",
        observations=[{
            "target": "Snooze length",
        }],
    )
    runtime.protocol_map.observe(
        name="Settings", summary="Settings page", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=b"settings",
    )
    runtime.protocol_map.observe(
        name="Home", summary="Home page", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=b"home",
    )
    runtime.protocol_map.connect("Home", "Settings", "CLICK", "Settings")
    loop._sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_type == "survey_page"
    assert runtime.exploration_task.page_name == "Home"

    for page_name, frame_id in (
        ("Home", "frame-home"), ("Settings", "frame-settings"),
    ):
        state = loop._region_state(runtime, page_name)
        state.observe_frame(frame_id)
        state.apply_agent_update(
            [{
                "name": "Alarms" if page_name == "Settings" else "Main",
                "summary": "Visible page content",
                "bbox_1000": [0, 0, 1000, 1000],
                "coverage_complete": True,
            }],
            frame_id=frame_id,
        )
        _accept_entry_audit(
            runtime, page_name,
            "Alarms" if page_name == "Settings" else "Main")
    runtime.protocol_map.current_page = "Settings"
    runtime.exploration_task = None
    loop._sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_type == "explore_entry"
    assert runtime.exploration_task.entry_id == "ae1"
    assert runtime.exploration_task.target == "Snooze length"
    assert runtime.exploration_task.route_hint == []

    attempt = runtime.entry_ledger.begin_explicit_action(
        "ae1", frame_id="frame-1", page_name="Settings")
    runtime.entry_ledger.finish_action(
        attempt.action_id,
        action_executed=True,
        outcome_verified=True,
        result="Opened the snooze duration dialog",
    )
    loop._sync_exploration_task(runtime)

    assert runtime.exploration_task is None


def test_initial_task_surveys_the_visible_page_before_any_entry_probe(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])

    loop._sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_type == "survey_page"
    assert runtime.exploration_task.phase == "identify_page"
    assert runtime.exploration_task.target == "current visible page"


def test_main_agent_page_update_registers_regions_and_entries_in_one_turn(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    screenshot = screen["screenshot"]
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.protocol_map.observe(
        name="Home", summary="Home page", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    history = []
    issue = loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            regions=[{
                "name": "Main", "summary": "Primary content",
                "bbox_1000": [0, 0, 1000, 1000],
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Main", "target": "Open details",
                "bbox_1000": [400, 400, 600, 600],
            }],
        ),
        loop.ObservedScene(
            state_id="state-home", screenshot=screenshot, page_name="Home",
            is_new=False,
        ),
        screenshot,
        history,
    )

    assert issue == ""
    assert history[-1] == {
        "kind": "page_update_result",
        "screen": "Home",
        "status": "accepted",
        "accepted_regions": ["Main"],
        "created_entries": [{
            "entry_id": "ae1",
            "target": "Open details",
            "operation": "Open details",
            "subject": "Main",
            "region_name": "Main",
        }],
        "rejected_items": [],
    }
    region = loop._region_state(runtime, "Home").snapshot()["regions"][0]
    assert region["coverage_complete"] is True
    assert region["summary"] == "Primary content"
    entry = runtime.entry_ledger.entries[0]
    assert entry.discovery_source == "main_agent_page_update"
    assert entry.task_eligible is True
    assert loop._completion_gaps(runtime) == [
        "home: Region Main has no accepted entry-coverage audit",
        "Home: 操作 Open details （对象：Main；代表目标：Open details） 已经登记但尚未探索",
    ]

    _accept_entry_audit(runtime, "Home", "Main")

    loop._sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_type == "explore_entry"
    assert runtime.exploration_task.entry_id == entry.entry_id


def test_page_update_groups_repeated_stateful_regions_without_duplicate_entry(
    tmp_path,
) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    runtime.protocol_map.observe(
        name="Alarm", summary="Alarm list", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )

    issue = loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Alarm",
            regions=[
                {
                    "name": "Alarm item 8:30",
                    "summary": "One independently expandable alarm item",
                    "coverage_complete": True,
                },
                {
                    "name": "Alarm item 9:00",
                    "summary": "Another independently expandable alarm item",
                    "same_group_as": "Alarm item 8:30",
                    "coverage_complete": True,
                },
            ],
            new_entries=[{
                "region_name": "Alarm item 8:30",
                "target": "Expand alarm item",
            }],
        ),
        loop.ObservedScene(
            state_id="state-alarm", screenshot=screenshot,
            page_name="Alarm", is_new=False),
        screenshot,
        [],
        region_reviewed=True,
    )

    assert issue == ""
    first_ref = runtime.region_registry.region_ref(
        "Alarm", "Alarm item 8:30")
    second_ref = runtime.region_registry.region_ref(
        "Alarm", "Alarm item 9:00")
    assert first_ref == second_ref
    assert runtime.region_registry.occurrence_ref(
        "Alarm", "Alarm item 8:30") != runtime.region_registry.occurrence_ref(
            "Alarm", "Alarm item 9:00")
    assert len(runtime.entry_ledger.entries) == 1
    entry = runtime.entry_ledger.entries[0]
    assert entry.owner_region_ref == first_ref
    assert entry.required_states


def test_ae13_page_update_regression_returns_framework_created_id(
    tmp_path,
) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    runtime.protocol_map.observe(
        name="Home", summary="Home page", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    frame_id = screenshot_frame_id(screenshot)
    runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Seed", frame_id=frame_id,
        observations=[{"target": f"Seed {index}"} for index in range(12)],
    )
    history = []

    issue = loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            regions=[{"name": "Main", "bbox_1000": [0, 0, 1000, 1000],
                      "coverage_complete": False}],
            new_entries=[{
                "region_name": "Main",
                "target": "Thirteenth discovered entry",
            }],
        ),
        loop.ObservedScene(
            state_id="state-home", screenshot=screenshot, page_name="Home",
            is_new=False,
        ),
        screenshot,
        history,
    )

    assert issue == ""
    assert history[-1]["created_entries"] == [{
        "entry_id": "ae13",
        "target": "Thirteenth discovered entry",
        "region_name": "Main",
    }]
    assert _history_summary(history)["recent_results"][-1]["kind"] == (
        "page_update_result")
    loop._sync_exploration_task(runtime)
    view = loop._exploration_map_view(runtime, None)
    assert any(
        item["target"] == "Thirteenth discovered entry"
        and "id" not in item
        for item in view["survey_page_fact"]["known_entries"]
    )


def test_agent_can_finish_scrollable_page_survey_without_regionscan(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    screenshot = screen["screenshot"]
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.protocol_map.observe(
        name="Settings", summary="Desktop settings", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    issue = loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Settings",
            regions=[{
                "bbox_1000": [0, 0, 1000, 1000],
                "name": "Settings categories",
                "coverage_complete": True,
            }],
        ),
        loop.ObservedScene(
            state_id="state-settings", screenshot=screenshot,
            page_name="Settings", is_new=False,
        ),
        screenshot,
        [],
    )

    assert issue == ""
    _accept_entry_audit(runtime, "Settings", "Settings categories")
    loop._sync_exploration_task(runtime)

    assert runtime.exploration_task is None
    assert loop._completion_gaps(runtime) == []


def test_specific_incomplete_region_precedes_generic_survey_request(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    screenshot = screen["screenshot"]
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.protocol_map.observe(
        name="Settings - About", summary="Desktop settings", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    state = loop._region_state(runtime, "Settings - About")
    state.observe_frame(loop.screenshot_frame_id(screenshot))
    state.apply_agent_update([
        {
            "name": "Settings Navigation Sidebar",
            "coverage_complete": True,
        },
        {
            "name": "About System Information Content",
            "coverage_complete": False,
        },
    ], frame_id=loop.screenshot_frame_id(screenshot))

    loop._sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_type == "survey_page"
    assert runtime.exploration_task.region_name == (
        "About System Information Content")
    assert runtime.exploration_task.phase == "survey_region"
    assert runtime.exploration_task.reason == (
        "region_has_not_been_fully_inspected")


def test_unregistered_navigation_backfill_is_a_completion_gap(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    payload = {"entries": [{
        "entry_id": "ae1",
        "page_name": "Settings",
        "region_name": "full_screen",
        "target": "Settings list area",
        "control_type": "control",
        "status": "unresolved",
        "discovery_source": "direct_action_backfill",
        "task_eligible": False,
        "last_result": "No independent function was established",
    }], "pending_actions": [], "next_action": 1}
    runtime.entry_ledger = type(runtime.entry_ledger).from_snapshot(payload)

    assert runtime.entry_ledger.get("ae1").task_eligible is False
    assert any(
        "unreviewed direct-action evidence" in gap
        for gap in loop._completion_gaps(runtime)
    )


def test_agent_declared_equivalence_creates_only_an_unverified_infer_edge(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.graph.graph.add_node("state-clock", page_name="Clock")
    runtime.graph.graph.add_node("state-alarm", page_name="Alarm")
    runtime.graph.graph.add_node("state-settings", page_name="Settings")
    representative = runtime.entry_ledger.record_agent_update(
        page_name="Clock",
        region_name="Navigation",
        frame_id="frame-clock",
        source_state_id="state-clock",
        observations=[{"target": "Settings"}],
    )
    attempt = runtime.entry_ledger.begin_explicit_action(
        representative.added[0],
        frame_id="frame-clock",
        page_name="Clock",
    )
    runtime.entry_ledger.finish_action(
        attempt.action_id,
        action_executed=True,
        outcome_verified=True,
        result="Settings opened",
        destination_page="Settings",
        destination_state_id="state-settings",
    )
    occurrence = runtime.entry_ledger.record_agent_update(
        page_name="Alarm",
        region_name="Navigation",
        frame_id="frame-alarm",
        source_state_id="state-alarm",
        observations=[{
            "target": "Settings",
            "equivalent_to_entry_id": representative.added[0],
        }],
    )

    _record_agent_inferred_edges(runtime)

    linked = runtime.entry_ledger.get(occurrence.added[0])
    assert linked.status is EntryStatus.INFERRED
    assert runtime.protocol_map.connections == [{
        "from": "Alarm",
        "via": "Settings",
        "action": "CLICK",
        "to": "Settings",
        "provenance": "agent_inferred_equivalence",
        "entry_id": linked.entry_id,
        "equivalent_to_entry_id": representative.added[0],
        "reason": (
            "Agent linked this visible entry to the verified shared-Region "
            "candidate during page survey."),
    }]
    infer_attempt = runtime.graph.action_edges[-1]["attempts"][-1]
    assert infer_attempt["outcome"] == "inferred_from_agent_equivalence"
    assert infer_attempt["committed"] is False
    assert infer_attempt["landing_verified"] is False
    assert infer_attempt["evidence"]["no_gui_action"] is True



def test_agent_inferred_edge_does_not_guess_material_variant_state(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.graph.graph.add_node("state-clock", page_name="Clock")
    runtime.graph.graph.add_node("state-alarm-empty", page_name="Alarm")
    runtime.graph.graph.add_node("state-alarm-active", page_name="Alarm")
    runtime.graph.graph.add_node("state-settings", page_name="Settings")
    representative = runtime.entry_ledger.record_agent_update(
        page_name="Clock",
        region_name="Navigation",
        frame_id="frame-clock",
        source_state_id="state-clock",
        observations=[{"target": "Settings"}],
    )
    attempt = runtime.entry_ledger.begin_explicit_action(
        representative.added[0],
        frame_id="frame-clock",
        page_name="Clock",
    )
    runtime.entry_ledger.finish_action(
        attempt.action_id,
        action_executed=True,
        outcome_verified=True,
        result="Settings opened",
        destination_page="Settings",
        destination_state_id="state-settings",
    )
    occurrence = runtime.entry_ledger.record_agent_update(
        page_name="Alarm",
        region_name="Navigation",
        frame_id="frame-alarm",
        observations=[{
            "target": "Settings",
            "equivalent_to_entry_id": representative.added[0],
        }],
    )

    _record_agent_inferred_edges(runtime)

    linked = runtime.entry_ledger.get(occurrence.added[0])
    assert linked.status is EntryStatus.INFERRED
    assert linked.inferred_edge_recorded is False
    assert runtime.protocol_map.connections == []

def test_unbound_click_records_action_evidence_without_formal_entry(
    tmp_path,
) -> None:
    before = {"screenshot": _png("white")}
    after = {"screenshot": _png("blue")}
    turns = [
        _turn(
            "Home", action="CALL_TOOL", identity="known", target="Open details",
            tool_name="click",
            tool_arguments={
                "target": "Open details",
                "point_1000": [500, 500],
                "entry_id": "",
            },
        ),
        _turn(
            "Home", action="WAIT", target="Open details",
            previous_outcome="changed",
        ),
    ]
    runtime, env, agent = _runtime(
        tmp_path, before, turns, results=[after], max_actions=1)
    _bind_incomplete_page(runtime, "Home", before["screenshot"])

    graph = loop.run_autonomous_traversal(runtime, before)

    assert [item[0]["action_type"] for item in env.actions] == ["CLICK"]
    assert len(graph.action_edges) == 1
    assert runtime.entry_ledger.entries == ()
    attempt = graph.action_edges[0]["attempts"][-1]
    assert attempt["evidence"]["explicit_entry_task"] is False
    assert "entry_id" not in attempt["evidence"]
    history = _trace(tmp_path)["history"]
    assert not any(
        item.get("kind") == "tool" and item.get("tool_name") == "click"
        for item in history
    )
    action = next(
        item for item in history
        if item.get("kind") == "action" and item.get("action") == "CLICK"
    )
    assert action["action_tool_result"]["operation"] == "click"


@pytest.mark.parametrize("operation", ["long_press", "double_tap"])
def test_unbound_android_pointer_gesture_records_no_formal_entry(
    tmp_path, monkeypatch, operation,
) -> None:
    before = {"screenshot": _png("white")}
    after = {"screenshot": _png("blue")}
    turns = [
        _turn(
            "Home", action="CALL_TOOL", identity="known",
            target="Open context actions", tool_name="gesture",
            tool_arguments={
                "operation": operation,
                "target": "Open context actions",
                "entry_id": "",
                "point_1000": [500, 500],
            },
        ),
        _turn(
            "Home", action="WAIT", target="Open context actions",
            previous_outcome="changed",
        ),
    ]
    env = _AndroidEnv(before, [after])
    agent = _Agent(turns)
    review_requests = []

    def review(request):
        review_requests.append(dict(request))
        return {
            "decision": "approve",
            "observed_target": "Open context actions",
            "point_matches_target": True,
            "target_matches_request": True,
            "risk": "safe",
            "reason": "The requested gesture is safe on the visible target.",
        }

    agent.review_click = review
    runtime = loop.AutonomousTraversalRuntime(
        env=env,
        decision_agent=agent,
        app_name="fixture",
        output_root=str(tmp_path),
        max_states=20,
        max_actions=1,
    )
    _bind_incomplete_page(runtime, "Home", before["screenshot"])
    monkeypatch.setattr(
        autonomous_recovery, "is_app_foreground", lambda *_args: True)

    graph = loop.run_autonomous_traversal(runtime, before)

    assert env.actions[0][0] == {
        "action_type": operation, "x": 50, "y": 40,
    }
    assert review_requests[0]["operation"] == operation
    assert len(graph.action_edges) == 1
    assert runtime.entry_ledger.entries == ()
    attempt = graph.action_edges[0]["attempts"][-1]
    assert attempt["evidence"]["explicit_entry_task"] is False
    assert "entry_id" not in attempt["evidence"]
    action = next(
        item for item in _trace(tmp_path)["history"]
        if item.get("kind") == "action"
        and item.get("action") == operation.upper()
    )
    assert action["action_tool_result"]["operation"] == operation


def test_android_swipe_uses_native_action_without_pointer_entry(
    tmp_path, monkeypatch,
) -> None:
    before = {"screenshot": _png("white")}
    after = {"screenshot": _png("blue")}
    turns = [
        _turn(
            "Home", action="CALL_TOOL", identity="known",
            target="swipe left", tool_name="gesture",
            tool_arguments={"operation": "swipe", "direction": "left"},
        ),
        _turn(
            "Home", action="WAIT", target="swipe left",
            previous_outcome="changed",
        ),
    ]
    env = _AndroidEnv(before, [after])
    runtime, env, _agent = _runtime(
        tmp_path, before, turns, results=[after], max_actions=1, env=env)
    _bind_incomplete_page(runtime, "Home", before["screenshot"])
    monkeypatch.setattr(
        autonomous_recovery, "is_app_foreground", lambda *_args: True)

    graph = loop.run_autonomous_traversal(runtime, before)

    assert env.actions == []
    assert len(graph.action_edges) == 0
    assert runtime.entry_ledger.entries == ()
    assert any(
        item.get("rejection", {}).get("code") == "invalid_agent_turn"
        for item in _trace(tmp_path)["history"]
    )


def test_action_budget_waits_for_landing_identity_before_stopping(tmp_path) -> None:
    before = {"screenshot": _png("white")}
    after = {"screenshot": _png("blue")}
    turns = [
        _turn(
            "Home", action="CALL_TOOL", identity="known", target="Open details",
            tool_name="click", tool_arguments={
                "target": "Open details",
                "point_1000": [500, 500],
                "entry_id": "",
            },
        ),
        _turn(
            "Details", action="CALL_TOOL", identity="uncertain",
            target="identify landing", tool_name="page_identity",
            tool_arguments={
                "suspected_pages": ["Home"],
                "proposed_new_name": "Details",
                "reason": "The click opened a different foreground page.",
            },
            previous_outcome="changed",
            previous_target="Open details",
        ),
        _turn(
            "Details", action="WAIT", identity="new",
            target="page identity analysis", review=_accept_review(),
            previous_outcome="no_visible_change",
        ),
        _turn("Details", action="NONE", identity="new"),
    ]
    identity_result = {
        "status": "new",
        "page_name": "Details",
        "matched_page_name": "",
        "surface_kind": "page",
        "summary": "A distinct details page.",
        "supporting_evidence": ["The foreground title is Details."],
        "conflicting_evidence": [],
        "checked_candidates": ["Home"],
        "reason": "The visible foreground differs from Home.",
    }
    runtime, env, agent = _runtime(
        tmp_path,
        before,
        turns,
        results=[after],
        identity_result=identity_result,
        max_actions=1,
    )
    _bind_incomplete_page(runtime, "Home", before["screenshot"])

    graph = loop.run_autonomous_traversal(runtime, before)

    assert graph.stop_reason == "max_actions"
    assert len(env.actions) == 1
    landing_catalog = {
        item["name"] for item in agent.calls[1][2]["tool_catalog"]
    }
    assert not ({
        "map_regions", "inspect_region", "reconcile_regions",
    } & landing_catalog)
    assert "Details" in runtime.protocol_map.pages
    assert graph.action_edges[0]["attempts"][0]["outcome"] == "observed_change"
    assert graph.action_edges[0]["element_label"] == "Open details"
    assert any(
        item.get("kind") == "tool_review" and item.get("outcome") == "accepted"
        for item in _trace(tmp_path)["history"]
    )


def test_main_agent_can_register_a_clear_non_root_new_page_directly(
    tmp_path,
) -> None:
    before = {"screenshot": _png("white")}
    after = {"screenshot": _png("blue")}
    turns = [
        _turn(
            "Home", action="CALL_TOOL", identity="known", target="Open details",
            tool_name="click", tool_arguments={
                "target": "Open details",
                "point_1000": [500, 500],
                "entry_id": "",
            },
        ),
        _turn(
            "Details", action="CALL_TOOL", identity="new",
            tool_name="finish_exploration", tool_arguments={
                "reason": "No known work remains.",
                "unreachable_evidence": [],
            },
            previous_outcome="changed",
            previous_target="Open details",
        ),
    ]
    runtime, env, agent = _runtime(
        tmp_path, before, turns, results=[after], max_actions=1)
    _bind_incomplete_page(runtime, "Home", before["screenshot"])

    graph = loop.run_autonomous_traversal(runtime, before)

    assert graph.stop_reason == "max_actions"
    assert len(env.actions) == 1
    assert set(runtime.protocol_map.pages) == {"Home", "Details"}
    assert runtime.protocol_map.connections == [{
        "from": "Home",
        "via": "Open details",
        "action": "CLICK",
        "to": "Details",
        "provenance": "observed",
    }]
    arrival = agent.calls[1][2]["exploration_map"]["arrival_context"]
    assert arrival == {
        "source_page": "Home",
        "via_action": "CLICK",
        "via_control": "Open details",
        "source_neighbors": [],
        "source_regions": [{"name": "Main"}],
    }


def test_unresolved_identity_defers_old_stage_action_until_page_is_resolved(
    tmp_path,
) -> None:
    before = {"screenshot": _png("white")}
    after = {"screenshot": _png("blue")}
    turns = [
        _turn(
            "Home", action="CALL_TOOL", identity="known", target="Details",
            tool_name="click", tool_arguments={
                "target": "Details",
                "point_1000": [500, 500],
                "entry_id": "",
            },
        ),
        _turn(
            "Unknown details", action="CALL_TOOL", identity="uncertain",
            target="Another button", tool_name="click", tool_arguments={
                "target": "Another button",
                "point_1000": [600, 600],
                "entry_id": "",
            },
            previous_outcome="changed",
            previous_target="Details",
        ),
        _turn(
            "Details", action="CALL_TOOL", identity="uncertain",
            target="identify landing", tool_name="page_identity",
            tool_arguments={
                "suspected_pages": ["Home"],
                "proposed_new_name": "Details",
                "reason": "The rejection requires resolving this landing first.",
            },
        ),
        _turn(
            "Details", action="WAIT", identity="new",
            target="page identity review", review=_accept_review(),
        ),
        _turn("Details", action="NONE", identity="new"),
    ]
    identity_result = {
        "status": "new",
        "page_name": "Details",
        "matched_page_name": "",
        "surface_kind": "page",
        "summary": "A distinct details page.",
        "supporting_evidence": ["Details title"],
        "conflicting_evidence": [],
        "checked_candidates": ["Home"],
        "reason": "The foreground differs from Home.",
    }
    runtime, env, agent = _runtime(
        tmp_path,
        before,
        turns,
        results=[after],
        identity_result=identity_result,
        max_actions=1,
    )
    _bind_incomplete_page(runtime, "Home", before["screenshot"])

    graph = loop.run_autonomous_traversal(runtime, before)

    assert graph.stop_reason == "max_actions"
    assert len(env.actions) == 1
    rejected = next(
        item for item in _trace(tmp_path)["history"]
        if item.get("kind") == "action"
        and item.get("rejection", {}).get("code") == "page_context_missing"
    )
    assert rejected["target"] == "Another button"
    assert rejected["outcome"] == "not_executed"
    transition = next(
        item for item in _trace(tmp_path)["history"]
        if item.get("kind") == "stage_transition"
        and item.get("from_stage") == "identify_variant"
    )
    assert transition["to_stage"] == "record_regions"
    assert "Details" in runtime.protocol_map.pages


def test_independent_click_review_rejects_without_dispatch(tmp_path) -> None:
    screen = {"screenshot": _png("white")}
    frame_id = screenshot_frame_id(screen["screenshot"])
    turns = [_turn(
        "Home", action="CALL_TOOL", identity="known", target="Delete account",
        tool_name="click", tool_arguments={
            "target": "Delete account",
            "point_1000": [500, 500],
            "entry_id": "",
        },
    )]
    runtime, env, _agent = _runtime(tmp_path, screen, turns)
    _bind_incomplete_page(runtime, "Home", screen["screenshot"])
    runtime.click_reviewer = lambda _request: {
        "decision": "reject",
        "observed_target": "Delete account",
        "point_matches_target": True,
        "target_matches_request": True,
        "risk": "unsafe",
        "reason": "This would start an irreversible destructive flow.",
    }

    loop.run_autonomous_traversal(runtime, screen)

    assert env.actions == []
    review = next(item for item in _trace(tmp_path)["history"]
                  if item.get("kind") == "click_review")
    assert review["outcome"] == "not_executed"
    assert review["review"]["risk"] == "unsafe"
    assert review["rejection"]["code"] == "click_review_rejected"
    assert "Rejected click request" in review["rejection"]["feedback"]
    assert "target 'Delete account'" in review["rejection"]["feedback"]
    assert "point_1000=[500.0, 500.0]" in review["rejection"]["feedback"]
    assert "Do not reuse the rejected point" in review["rejection"]["feedback"]


def test_click_review_rejects_interactive_point_on_a_different_target(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    frame_id = screenshot_frame_id(screen["screenshot"])
    turns = [_turn(
        "Alarm", action="CALL_TOOL", identity="known",
        target="Snooze/Add Button", tool_name="click", tool_arguments={
            "target": "Snooze/Add Button",
            "point_1000": [875, 460],
            "entry_id": "",
        },
    )]
    runtime, env, _agent = _runtime(tmp_path, screen, turns)
    _bind_incomplete_page(runtime, "Alarm", screen["screenshot"])
    runtime.click_reviewer = lambda _request: {
        "decision": "reject",
        "observed_target": "Plus icon on Pause alarm row",
        "point_matches_target": True,
        "target_matches_request": False,
        "risk": "safe",
        "reason": "The point is interactive, but it is not a Snooze control.",
    }

    loop.run_autonomous_traversal(runtime, screen)

    assert env.actions == []
    review = next(item for item in _trace(tmp_path)["history"]
                  if item.get("kind") == "click_review")
    assert review["review"]["target_matches_request"] is False
    assert review["rejection"]["code"] == "click_review_rejected"


def test_partial_entry_rejection_still_scrolls_registered_region(
    tmp_path,
) -> None:
    before = {"screenshot": _png("white")}
    after = {"screenshot": _png("gray")}
    frame_id = screenshot_frame_id(before["screenshot"])
    turns = [
        _turn(
            "Home", action="NONE", identity="known", target="Item list",
            page_update=loop.PageUpdate(
                page_name="Home",
                regions=[{
                    "bbox_1000": [0, 0, 1000, 1000],
                    "name": "Item list",
                    "summary": "Scrollable list of items",
                    "coverage_complete": True,
                }],
                new_entries=[
                    {"region_name": "Item list", "target": "Open item"},
                    {
                        "region_name": "Item list", "target": "Bad model ID",
                        "entry_id": "ae13",
                    },
                ],
            ),
        ),
        _turn(
            "Home", action="NONE", identity="known", target="Item list",
            entry_review=[
                {"region_name": "Item list", "target": "Open item"},
                {"region_name": "Item list", "target": "Bad model ID"},
            ],
        ),
        _turn(
            "Home", action="CALL_TOOL", identity="known", target="Item list",
            tool_name="scroll",
            tool_arguments={
                "container_hint": "item list viewport",
                "point_1000": [950, 950],
                "direction": "down",
                "amount": 600,
            },
        ),
        _turn(
            "Home", action="WAIT", target="Item list",
            previous_outcome="changed",
        ),
    ]
    runtime, env, agent = _runtime(
        tmp_path,
        before,
        turns,
        results=[after],
        max_actions=1,
    )
    runtime.protocol_map.observe(
        name="Home", summary="Visible Home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=before["screenshot"], commit_regions=False,
    )
    loop._register_scene(
        runtime,
        before["screenshot"],
        _turn("Home", action="NONE", identity="known"),
        "Home",
    )

    graph = loop.run_autonomous_traversal(runtime, before)

    catalogs = [
        {item["name"] for item in call[2]["tool_catalog"]}
        for call in agent.calls
    ]
    assert "scroll" in catalogs[0]
    assert [item[0]["action_type"] for item in env.actions] == ["SCROLL"]
    assert len(graph.action_edges) == 1
    page_results = [
        item for item in _trace(tmp_path)["history"]
        if item.get("kind") == "page_update_result"
    ]
    # The initial scene is still establishing its survey context, so the
    # same-turn partial update is deferred rather than committing a mixed
    # accepted/rejected Entry batch without its owner review.
    assert page_results == []


def test_completed_survey_switches_to_compact_entry_tool_view(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(
        tmp_path, screen, [],
    )
    runtime.protocol_map.observe(
        name="Home", summary="Known home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"],
    )
    frame_id = screenshot_frame_id(screen["screenshot"])
    state = loop._region_state(runtime, "Home")
    state.observe_frame(frame_id)
    state.apply_agent_update([{
        "name": "Item list", "summary": "Visible items",
        "bbox_1000": [0, 100, 1000, 900],
        "coverage_complete": True,
    }], frame_id=frame_id)
    _accept_entry_audit(runtime, "Home", "Item list")
    runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Item list", frame_id=frame_id,
        observations=[{"target": "Open details"}],
    )
    loop._sync_exploration_task(runtime)

    assert runtime.exploration_task.task_type == "explore_entry"
    final_catalog = loop._dynamic_tool_catalog(runtime, screen["screenshot"])
    final_names = {item["name"] for item in final_catalog}
    assert {"click", "scroll", "navigate", "page_identity"} <= final_names
    assert "inspect_region" not in final_names
    assert "reconcile_regions" not in final_names
    assert "defer_current_task" in final_names
    assert "finish_exploration" not in final_names


def test_uncertain_page_identity_never_registers_page_or_graph_node(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("orange")}
    identity_result = {
        "status": "uncertain",
        "page_name": "Maybe Home",
        "matched_page_name": "",
        "surface_kind": "page",
        "summary": "The foreground is ambiguous.",
        "supporting_evidence": [],
        "conflicting_evidence": ["A transient overlay obscures the title."],
        "checked_candidates": [],
        "reason": "The visible evidence is insufficient.",
    }
    first = _turn(
        "Maybe Home", action="CALL_TOOL", identity="uncertain",
        tool_name="page_identity",
        tool_arguments={
            "suspected_pages": [],
            "proposed_new_name": "Maybe Home",
            "reason": "Resolve the obscured foreground.",
        },
    )
    turns = [first] + [
        _turn("Maybe Home", action="WAIT", identity="uncertain")
        for _ in range(17)
    ]
    runtime, env, _agent = _runtime(
        tmp_path,
        screen,
        turns,
        identity_result=identity_result,
        max_actions=1,
    )

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert runtime.protocol_map.pages == {}
    assert runtime.protocol_map.current_page == ""
    assert graph.graph.number_of_nodes() == 0
    assert env.actions == []
    assert any(
        item.get("tool_name") == "page_identity"
        and item.get("tool_result", {}).get("status") == "uncertain"
        for item in _trace(tmp_path)["history"]
    )
