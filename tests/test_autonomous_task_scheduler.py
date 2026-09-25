"""Focused contracts for autonomous task-pool scheduling."""

from __future__ import annotations

import io
import json

from PIL import Image

from gui_rewalk.src.core.visual_traversal.runtime import autonomous_loop as loop
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_runtime import (
    AutonomousTraversalRuntime,
    _checkpoint,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_region_tools import (
    AutonomousRegionRegistry,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_context import (
    _exploration_map_view,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_completion import (
    _completion_gaps,
    _completion_summary,
    _request_same_page_resurvey,
    _rejection_progress_token,
    _region_exploration_status,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_scheduling import (
    _defer_current_task,
    _entry_source_route,
    _page_survey_need,
    _region_probe_state_ids,
    _sync_exploration_task,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_turn import (
    AutonomousDecision,
    AutonomousTurn,
    ExplorationTask,
    PageUpdate,
    PreviousAssessment,
    SurfaceRegistration,
)


def _png(color: str) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (20, 20), color).save(stream, format="PNG")
    return stream.getvalue()


class _Env:
    vm_platform = "desktop"


class _Agent:
    model = "scheduler-fixture"
    backend_runs = []


def _turn(
    page_name: str,
    *,
    identity: str,
    variant_name: str = "default",
    variant_identity: str = "",
) -> AutonomousTurn:
    return AutonomousTurn(
        screen_name=page_name,
        previous=PreviousAssessment(
            outcome="not_applicable", reason="fixture observation"),
        decision=AutonomousDecision(
            action="NONE", target="", point_1000=None, direction="",
            reason="fixture observation"),
        registration=SurfaceRegistration(
            identity=identity,
            matched_page_name=page_name if identity == "known" else "",
            variant_name=variant_name,
            variant_identity=(
                variant_identity or ("new" if identity == "new" else "known")
            ),
        ),
    )


def _runtime(tmp_path) -> AutonomousTraversalRuntime:
    return AutonomousTraversalRuntime(
        env=_Env(),
        decision_agent=_Agent(),
        app_name="fixture",
        output_root=str(tmp_path),
        max_states=20,
        max_actions=20,
        enable_region_probes=False,
    )


def _register_complete_page(
    runtime: AutonomousTraversalRuntime,
    page_name: str,
    screenshot: bytes,
    *,
    identity: str,
    coverage_complete: bool = True,
    entry_review_complete: bool = True,
):
    canonical, issue = runtime.protocol_map.observe(
        name=page_name,
        summary=f"Visible {page_name}",
        identity=identity,
        matched_page_name=page_name if identity == "known" else "",
        surface_kind="page",
        regions=(),
        screenshot=screenshot,
        variant_name="default",
        variant_identity="new" if identity == "new" else "known",
        visible_predicates=[],
        commit_regions=False,
    )
    assert (canonical, issue) == (page_name, "")
    scene = loop._register_scene(runtime, screenshot, _turn(
        page_name, identity=identity), page_name)
    state = loop._region_state(runtime, page_name)
    frame_id = loop.screenshot_frame_id(screenshot)
    state.observe_frame(frame_id, scene.state_id)
    state.apply_agent_update([{
        "name": "Main",
        "summary": "Fixture controls",
        "coverage_complete": coverage_complete,
    }], frame_id=frame_id)
    region_ref, _ = runtime.region_registry.bind(
        page_name=page_name,
        region_name="Main",
        state_id=scene.state_id,
        summary="Fixture controls",
    )
    runtime.region_registry.mark_state_visible(
        page_name=page_name,
        region_name="Main",
        state_id=scene.state_id,
    )
    state.set_region_ref("Main", region_ref)
    runtime.entry_review_audits.setdefault("main" if page_name == "Main" else page_name.casefold(), {})[
        "main"
    ] = {
        "page_name": page_name,
        "region_name": "Main",
        "status": "complete" if entry_review_complete else "pending",
    }
    runtime.protocol_map.upsert_regions(
        page_name, state.snapshot().get("regions") or [])
    return scene


def _add_region(
    runtime: AutonomousTraversalRuntime,
    page_name: str,
    state_id: str,
    name: str,
    *,
    coverage_complete: bool,
) -> None:
    state = loop._region_state(runtime, page_name)
    frame_id = f"{page_name.casefold()}-{name.casefold()}-frame"
    state.observe_frame(frame_id, state_id)
    state.apply_agent_update([{
        "name": name,
        "summary": f"{name} controls",
        "coverage_complete": coverage_complete,
    }], frame_id=frame_id)
    region_ref, _ = runtime.region_registry.bind(
        page_name=page_name,
        region_name=name,
        state_id=state_id,
        summary=f"{name} controls",
    )
    runtime.region_registry.mark_state_visible(
        page_name=page_name,
        region_name=name,
        state_id=state_id,
    )
    state.set_region_ref(name, region_ref)
    runtime.entry_review_audits.setdefault(page_name.casefold(), {})[
        name.casefold()
    ] = {"page_name": page_name, "region_name": name, "status": "complete"}
    runtime.protocol_map.upsert_regions(
        page_name, state.snapshot().get("regions") or [])


def test_scheduler_requires_verified_route_and_keeps_selected_entry_task(
    tmp_path,
) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    detail = _register_complete_page(
        runtime, "Detail", _png("blue"), identity="new")
    _register_complete_page(runtime, "Home", _png("white"), identity="known")

    remote_entry = runtime.entry_ledger.record_agent_update(
        page_name="Detail",
        region_name="Main",
        frame_id="detail-frame",
        observations=[{"target": "Remote control"}],
        source_state_id=detail.state_id,
    ).added[0]

    _sync_exploration_task(runtime)

    assert runtime.exploration_task is None
    assert runtime.graph.stop_reason == "unverified_route_remaining"

    runtime.graph.add_transition(
        home.state_id,
        detail.state_id,
        {"action_type": "CLICK", "selector": {"element_label": "Detail"}},
        element_id="fixture-detail-route",
        element_label="Detail",
        landing_verified=True,
        target_page_name="Detail",
        effect_verdict="observed_change",
    )
    _sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == remote_entry
    assert runtime.exploration_task.phase == "route_to_source"
    assert len(runtime.exploration_task.route_hint) == 1

    local_entry = runtime.entry_ledger.record_agent_update(
        page_name="Home",
        region_name="Main",
        frame_id="home-frame",
        observations=[{"target": "Closer control"}],
        source_state_id=home.state_id,
    ).added[0]
    _sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == remote_entry

    pending = runtime.entry_ledger.begin_explicit_action(
        remote_entry, frame_id="detail-frame", page_name="Detail")
    runtime.entry_ledger.finish_action(
        pending.action_id,
        action_executed=True,
        outcome_verified=True,
        result="Remote control opened its verified destination.",
        destination_page="Detail",
        destination_state_id=detail.state_id,
    )
    _sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == local_entry
    assert runtime.exploration_task.phase == "locate_entry"


def test_scheduler_uses_stable_creation_order_for_equal_verified_distances(
    tmp_path,
) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    detail = _register_complete_page(
        runtime, "Detail", _png("blue"), identity="new")
    other = _register_complete_page(runtime, "Other", _png("green"), identity="new")
    _register_complete_page(runtime, "Home", _png("white"), identity="known")
    first = runtime.entry_ledger.record_agent_update(
        page_name="Detail",
        region_name="Main",
        frame_id="detail-frame",
        observations=[{"target": "First discovered"}],
        source_state_id=detail.state_id,
    ).added[0]
    runtime.entry_ledger.record_agent_update(
        page_name="Other",
        region_name="Main",
        frame_id="other-frame",
        observations=[{"target": "Second discovered"}],
        source_state_id=other.state_id,
    )
    for destination, label in ((detail, "Detail"), (other, "Other")):
        runtime.graph.add_transition(
            home.state_id,
            destination.state_id,
            {"action_type": "CLICK", "selector": {"element_label": label}},
            element_id=f"fixture-{label.casefold()}-route",
            element_label=label,
            landing_verified=True,
            target_page_name=label,
            effect_verdict="observed_change",
        )

    _sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == first


def test_same_page_new_state_surveys_before_retained_entry(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    first = _register_complete_page(
        runtime, "Clock", _png("white"), identity="new")
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Clock",
        region_name="Main",
        frame_id="clock-default-frame",
        observations=[{"target": "Alarm tab"}],
        source_state_id=first.state_id,
    ).added[0]
    _sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == entry_id

    second_screen = _png("silver")
    canonical, issue = runtime.protocol_map.observe(
        name="Clock",
        summary="Visible Clock",
        identity="known",
        matched_page_name="Clock",
        surface_kind="page",
        regions=(),
        screenshot=second_screen,
        variant_name="clean",
        variant_identity="new",
        visible_predicates=["The clean Clock surface is visible"],
        commit_regions=False,
    )
    assert (canonical, issue) == ("Clock", "")
    second = loop._register_scene(
        runtime,
        second_screen,
        AutonomousTurn(
            screen_name="Clock",
            previous=PreviousAssessment(
                outcome="not_applicable", reason="fixture observation"),
            decision=AutonomousDecision(
                action="NONE", target="", point_1000=None, direction="",
                reason="fixture observation"),
            registration=SurfaceRegistration(
                identity="known", matched_page_name="Clock",
                variant_name="clean", variant_identity="new",
                visible_predicates=["The clean Clock surface is visible"],
            ),
        ),
        "Clock",
    )
    assert second.state_id != first.state_id
    assert not runtime.region_registry.has_state_occurrence(
        "Clock", second.state_id)

    _sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_type == "survey_page"
    assert runtime.exploration_task.page_name == "Clock"
    assert runtime.exploration_task.phase == "record_regions"
    assert runtime.exploration_task.reason == (
        "material_variant_has_no_region_occurrence")


def test_unaffected_entry_stays_local_after_owner_region_state_change(
    tmp_path,
) -> None:
    runtime = _runtime(tmp_path)
    first = _register_complete_page(
        runtime, "Clock", _png("white"), identity="new")
    _add_region(
        runtime, "Clock", first.state_id, "Navigation",
        coverage_complete=True)
    navigation_ref = runtime.region_registry.region_ref(
        "Clock", "Navigation")
    navigation_occurrence = runtime.region_registry.occurrence_ref(
        "Clock", "Navigation")
    navigation_state = runtime.region_registry.occurrence_state_ref(
        "Clock", "Navigation", first.state_id)
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Clock",
        region_name="Navigation",
        frame_id="clock-default-frame",
        observations=[{"target": "Add alarm"}],
        source_state_id=first.state_id,
        owner_region_ref=navigation_ref,
        representative_occurrence_ref=navigation_occurrence,
        required_state_ref=navigation_state,
    ).added[0]

    second_screen = _png("silver")
    runtime.protocol_map.observe(
        name="Clock", summary="Visible Clock", identity="known",
        matched_page_name="Clock", surface_kind="page", regions=(),
        screenshot=second_screen, variant_name="expanded",
        variant_identity="new", visible_predicates=["Alarm item expanded"],
        commit_regions=False,
    )
    second = loop._register_scene(
        runtime,
        second_screen,
        AutonomousTurn(
            screen_name="Clock",
            previous=PreviousAssessment(
                outcome="changed", reason="Alarm item expanded",
                visible_effect="owner_structure"),
            decision=AutonomousDecision(
                action="NONE", target="", point_1000=None, direction="",
                reason="fixture settlement"),
            registration=SurfaceRegistration(
                identity="known", matched_page_name="Clock",
                variant_name="expanded", variant_identity="new",
                visible_predicates=["Alarm item expanded"],
            ),
        ),
        "Clock",
    )
    runtime.region_registry.record_local_transition(
        page_name="Clock",
        region_name="Main",
        source_state_id=first.state_id,
        destination_state_id=second.state_id,
        trigger_entry_id="ae-expand",
        effect_text="Alarm item expanded",
        effect_kind="structure",
        evidence_action_id="attempt-expand",
    )

    entry = runtime.entry_ledger.get(entry_id)
    assert _entry_source_route(runtime, entry) == (True, [])
    _sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == entry_id
    assert runtime.exploration_task.phase == "locate_entry"


def test_owner_local_resurvey_invalidates_only_its_region(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    scene = _register_complete_page(
        runtime, "Clock", _png("white"), identity="new")
    _add_region(
        runtime, "Clock", scene.state_id, "Navigation",
        coverage_complete=True)

    _request_same_page_resurvey(
        runtime,
        [],
        page_name="Clock",
        entry_id="ae-expand",
        target="Expand alarm item",
        reason="Edit controls appeared inside the alarm item.",
        region_name="Main",
        region_ref=runtime.region_registry.region_ref("Clock", "Main"),
        occurrence_ref=runtime.region_registry.occurrence_ref("Clock", "Main"),
    )

    state = loop._region_state(runtime, "Clock")
    assert state.region("Main")["coverage_complete"] is False
    assert state.region("Navigation")["coverage_complete"] is True
    assert _page_survey_need(runtime, "Clock", scene.state_id) == (
        "same_page_functional_surface_changed", "Main", "survey_region")


def test_empty_static_page_survey_is_a_persisted_completion_fact(
    tmp_path,
) -> None:
    screenshot = _png("black")
    runtime = _runtime(tmp_path)
    canonical, issue = runtime.protocol_map.observe(
        name="Screen saver",
        summary="Static clock display",
        identity="new",
        matched_page_name="",
        surface_kind="page",
        regions=(),
        screenshot=screenshot,
        variant_name="default",
        variant_identity="new",
        visible_predicates=[],
        commit_regions=False,
    )
    assert (canonical, issue) == ("Screen saver", "")
    scene = loop._register_scene(
        runtime, screenshot,
        _turn("Screen saver", identity="new"),
        "Screen saver",
    )
    runtime.exploration_task = ExplorationTask(
        task_type="survey_page",
        task_id="survey:Screen saver",
        page_name="Screen saver",
        target="Screen saver",
        goal="discover_page_entries",
        phase="record_regions",
        reason="material_variant_has_no_region_occurrence",
    )
    result = {}
    progress_before = _rejection_progress_token(runtime)

    assert loop._apply_main_agent_page_update(
        runtime,
        PageUpdate(page_name="Screen saver", regions=[]),
        scene,
        screenshot,
        [],
        result_out=result,
    ) == ""

    assert result["empty_region_survey_completed"] == scene.state_id
    assert _rejection_progress_token(runtime) != progress_before
    assert runtime.empty_region_surveys == {
        "screen saver": {scene.state_id},
    }
    assert _page_survey_need(
        runtime, "Screen saver", scene.state_id) == ("", "", "")
    _sync_exploration_task(runtime)
    assert runtime.exploration_task is None
    assert not any(
        "page survey has no Regions" in gap
        for gap in _completion_gaps(runtime)
    )
    assert _completion_summary(runtime)["pages"] == [{
        "page": "Screen saver",
        "status": "complete",
        "regions": [],
    }]

    _checkpoint(runtime, [])
    saved = json.loads(
        (tmp_path / "autonomous_regions.json").read_text("utf-8"))
    assert saved["schema"] == "gui_rewalk.autonomous_regions_by_page.v8"
    assert saved["empty_region_surveys"] == {
        "screen saver": [scene.state_id],
    }
    resumed = _runtime(tmp_path)
    resumed.restore(runtime.graph_path)
    assert resumed.empty_region_surveys == runtime.empty_region_surveys


def test_deferred_entry_waits_for_unlock_then_becomes_runnable_again(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    input_entry, unlock_entry = runtime.entry_ledger.record_agent_update(
        page_name="Home",
        region_name="Main",
        frame_id="home-frame",
        observations=[{"target": "Disabled input"}, {"target": "Unlock"}],
        source_state_id=home.state_id,
    ).added

    _sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == input_entry
    assessment = PreviousAssessment(
        outcome="no_visible_change",
        reason="The input is visibly disabled until Unlock is used.",
        matches_intent=False,
    )
    assert _defer_current_task(
        runtime,
        {
            "prerequisite_target": "Unlock",
            "reason": "Disabled input is visibly locked; Unlock is the adjacent enable control.",
        },
        assessment=assessment,
    ) == ""

    _sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == unlock_entry

    pending = runtime.entry_ledger.begin_explicit_action(
        unlock_entry, frame_id="home-frame", page_name="Home")
    runtime.entry_ledger.finish_action(
        pending.action_id,
        action_executed=True,
        outcome_verified=True,
        result="Unlock visibly enabled the input.",
        destination_page="Home",
        destination_state_id=home.state_id,
    )
    _sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == input_entry
    dependency = runtime.task_dependencies[f"explore:{input_entry}"]
    assert dependency["status"] == "recheck_after_prerequisite"
    assert "Unlock" in dependency["prerequisite_result"]
    view = _exploration_map_view(runtime, None)
    assert view["task"]["前置重新检查"]["目标"] == "Unlock"
    assert "最新截图" in view["task"]["前置重新检查"]["注意"]


def test_entry_can_defer_to_visible_prerequisite_before_attempt(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    alarm = _register_complete_page(
        runtime, "Alarm", _png("white"), identity="new")
    clock_tab, cancel_button = runtime.entry_ledger.record_agent_update(
        page_name="Alarm",
        region_name="Main",
        frame_id="alarm-dialog-frame",
        observations=[{"target": "Clock tab"}, {"target": "Cancel button"}],
        source_state_id=alarm.state_id,
    ).added

    _sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == clock_tab
    assessment = PreviousAssessment(
        outcome="not_applicable",
        reason="The modal visibly blocks the Clock tab before any attempt.",
    )

    assert _defer_current_task(
        runtime,
        {
            "prerequisite_target": "Cancel button",
            "reason": "The visible time dialog blocks the Clock tab.",
        },
        assessment=assessment,
    ) == ""
    _sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == cancel_button


def test_hidden_incomplete_region_routes_to_its_recorded_state(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    menu_state = _register_complete_page(
        runtime, "Alarm", _png("white"), identity="new")
    _add_region(
        runtime,
        "Alarm",
        menu_state.state_id,
        "Overflow menu",
        coverage_complete=False,
    )
    default_screen = _png("blue")
    canonical, issue = runtime.protocol_map.observe(
        name="Alarm",
        summary="Visible Alarm",
        identity="known",
        matched_page_name="Alarm",
        surface_kind="page",
        regions=(),
        screenshot=default_screen,
        variant_name="default without menu",
        variant_identity="new",
        visible_predicates=["The overflow menu is closed"],
        commit_regions=False,
    )
    assert (canonical, issue) == ("Alarm", "")
    default_state = loop._register_scene(
        runtime,
        default_screen,
        AutonomousTurn(
            screen_name="Alarm",
            previous=PreviousAssessment(
                outcome="not_applicable", reason="fixture observation"),
            decision=AutonomousDecision(
                action="NONE", target="", point_1000=None, direction="",
                reason="fixture observation"),
            registration=SurfaceRegistration(
                identity="known",
                matched_page_name="Alarm",
                variant_name="default without menu",
                variant_identity="new",
                visible_predicates=["The overflow menu is closed"],
            ),
        ),
        "Alarm",
    )
    state = loop._region_state(runtime, "Alarm")
    frame_id = loop.screenshot_frame_id(default_screen)
    state.observe_frame(frame_id, default_state.state_id)
    main_ref, _ = runtime.region_registry.bind(
        page_name="Alarm",
        region_name="Main",
        state_id=default_state.state_id,
        summary="Fixture controls",
    )
    state.set_region_ref("Main", main_ref)
    runtime.protocol_map.upsert_regions(
        "Alarm", state.snapshot().get("regions") or [])
    runtime.graph.add_transition(
        default_state.state_id,
        menu_state.state_id,
        {"action_type": "CLICK", "selector": {"element_label": "More"}},
        element_id="fixture-open-menu",
        element_label="More",
        landing_verified=True,
        target_page_name="Alarm",
        effect_verdict="observed_change",
    )
    overflow_ref = runtime.region_registry.region_ref(
        "Alarm", "Overflow menu")
    runtime.region_registry.bind(
        page_name="Alarm",
        region_name="Overflow menu",
        state_id=default_state.state_id,
        equivalent_to_region_ref=overflow_ref,
        reason="Stable identity continued while the menu was hidden.",
    )
    assert default_state.state_id != menu_state.state_id
    assert _region_probe_state_ids(
        runtime, "Alarm", "Overflow menu") == [menu_state.state_id]
    runtime.region_registry.publish_coverage(
        region_ref=overflow_ref,
        page_name="Alarm",
        region_name="Overflow menu",
        state_id=menu_state.state_id,
        frame_id="menu-visible-frame",
        entry_signature=["control:settings"],
    )
    legacy_snapshot = runtime.region_registry.snapshot()
    for group in legacy_snapshot["groups"]:
        for occurrence in group.get("occurrences") or []:
            occurrence.pop("visible_state_ids", None)
    runtime.region_registry = AutonomousRegionRegistry.from_snapshot(
        legacy_snapshot)
    assert _region_probe_state_ids(
        runtime, "Alarm", "Overflow menu") == [menu_state.state_id]

    _sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_id == "survey:Alarm"
    assert runtime.exploration_task.region_name == "Overflow menu"
    assert runtime.exploration_task.phase == "route_to_page"
    assert runtime.exploration_task.route_hint[-1]["via"] == "More"
    assert runtime.exploration_task.route_hint[-1]["provenance"] == (
        "landing_verified")


def test_same_page_missing_state_route_is_dispatched_to_agent(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    target_state = _register_complete_page(
        runtime, "Alarm", _png("white"), identity="new")
    _add_region(
        runtime,
        "Alarm",
        target_state.state_id,
        "Time Setting Area",
        coverage_complete=False,
    )
    target_ref = runtime.region_registry.region_ref(
        "Alarm", "Time Setting Area")
    overlay_screen = _png("blue")
    canonical, issue = runtime.protocol_map.observe(
        name="Alarm", summary="Alarm with an open menu", identity="known",
        matched_page_name="Alarm", surface_kind="page", regions=(),
        screenshot=overlay_screen, variant_name="menu open",
        variant_identity="new", visible_predicates=[], commit_regions=False)
    assert (canonical, issue) == ("Alarm", "")
    overlay_state = loop._register_scene(
        runtime, overlay_screen, _turn(
            "Alarm", identity="known", variant_name="menu open",
            variant_identity="new"), "Alarm")
    state = loop._region_state(runtime, "Alarm")
    state.observe_frame(
        loop.screenshot_frame_id(overlay_screen), overlay_state.state_id)
    runtime.region_registry.bind(
        page_name="Alarm",
        region_name="Time Setting Area",
        state_id=overlay_state.state_id,
        equivalent_to_region_ref=target_ref,
        reason="The same controls continue beneath the open menu.",
    )

    _sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_id == "survey:Alarm"
    assert runtime.exploration_task.region_name == "Time Setting Area"
    assert runtime.exploration_task.phase == "route_to_page"
    assert runtime.exploration_task.route_hint == []
    task_view = _exploration_map_view(
        runtime, None, overlay_screen)["task"]
    assert "没有已验证的状态转换路线" in task_view["route_status"]
    assert "安全的可见步骤" in task_view["route_status"]
    assert task_view["target_condition"] == (
        "使“Time Setting Area”区域重新完整可见并可调查；"
        "任一真实满足该条件的页面状态均可。"
    )


def test_unreachable_incomplete_region_does_not_mask_visible_sibling(
    tmp_path,
) -> None:
    runtime = _runtime(tmp_path)
    dial_state = _register_complete_page(
        runtime, "Select time", _png("white"), identity="new")
    _add_region(
        runtime,
        "Select time",
        dial_state.state_id,
        "Clock dial",
        coverage_complete=False,
    )
    keyboard_screen = _png("blue")
    canonical, issue = runtime.protocol_map.observe(
        name="Select time",
        summary="Visible Select time",
        identity="known",
        matched_page_name="Select time",
        surface_kind="page",
        regions=(),
        screenshot=keyboard_screen,
        variant_name="keyboard",
        variant_identity="new",
        visible_predicates=["The number keyboard is visible"],
        commit_regions=False,
    )
    assert (canonical, issue) == ("Select time", "")
    keyboard_state = loop._register_scene(
        runtime,
        keyboard_screen,
        AutonomousTurn(
            screen_name="Select time",
            previous=PreviousAssessment(
                outcome="not_applicable", reason="fixture observation"),
            decision=AutonomousDecision(
                action="NONE", target="", point_1000=None, direction="",
                reason="fixture observation"),
            registration=SurfaceRegistration(
                identity="known",
                matched_page_name="Select time",
                variant_name="keyboard",
                variant_identity="new",
                visible_predicates=["The number keyboard is visible"],
            ),
        ),
        "Select time",
    )
    _add_region(
        runtime,
        "Select time",
        keyboard_state.state_id,
        "Number keyboard",
        coverage_complete=False,
    )
    assert not runtime.graph.routing_graph.has_edge(
        keyboard_state.state_id, dial_state.state_id)

    _sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_type == "survey_page"
    assert runtime.exploration_task.region_name == "Number keyboard"
    assert runtime.exploration_task.phase == "survey_region"


def test_defer_rejects_empty_and_cyclic_prerequisites_and_propagates_blocker(
    tmp_path,
) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    input_entry, unlock_entry = runtime.entry_ledger.record_agent_update(
        page_name="Home",
        region_name="Main",
        frame_id="home-frame",
        observations=[{"target": "Disabled input"}, {"target": "Unlock"}],
        source_state_id=home.state_id,
    ).added
    assessment = PreviousAssessment(
        outcome="no_visible_change",
        reason="The input is disabled.",
        matches_intent=False,
    )
    _sync_exploration_task(runtime)
    assert _defer_current_task(
        runtime, {"prerequisite_target": "", "reason": "No control named."},
        assessment=assessment,
    ).startswith("defer_current_task requires")
    assert _defer_current_task(
        runtime,
        {"prerequisite_target": "Unlock", "reason": "Unlock is visibly required."},
        assessment=assessment,
    ) == ""
    _sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == unlock_entry
    assert _defer_current_task(
        runtime,
        {"prerequisite_target": "Disabled input", "reason": "Input is required."},
        assessment=assessment,
    ) == "prerequisite dependency would create a cycle"

    runtime.entry_ledger.mark_unsafe_to_execute(
        unlock_entry, reason="Unlock is blocked by the safety reviewer.")
    gaps = _completion_gaps(runtime)

    assert any("prerequisite root “Unlock”" in gap for gap in gaps)
    assert any(
        f"explore:{input_entry}: affected by prerequisite root “Unlock”"
        in gap for gap in gaps)


def test_prerequisite_no_visible_result_rechecks_once_but_inferred_does_not(
    tmp_path,
) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    target, prerequisite = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id="home-frame",
        observations=[{"target": "Disabled input"}, {"target": "Unlock"}],
        source_state_id=home.state_id,
    ).added
    assessment = PreviousAssessment(
        outcome="no_visible_change", reason="Input is disabled.",
        matches_intent=False)
    _sync_exploration_task(runtime)
    assert _defer_current_task(
        runtime, {"prerequisite_target": "Unlock", "reason": "Unlock is required."},
        assessment=assessment) == ""
    runtime.entry_ledger.mark_no_effect_probe(
        prerequisite, result="Unlock was clicked without visible change.",
        classification="temporarily_unavailable")
    _sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == target
    assert runtime.task_dependencies[f"explore:{target}"]["status"] == \
        "recheck_after_prerequisite"

    # An inferred representative is semantic reuse, not current-State evidence.
    dependency = runtime.task_dependencies[f"explore:{target}"]
    dependency["status"] = "deferred"
    record = runtime.entry_ledger.get(prerequisite)
    record.status = type(record.status).INFERRED
    record.task_eligible = False
    _sync_exploration_task(runtime)
    assert runtime.task_dependencies[f"explore:{target}"]["status"] == "blocked"
    assert runtime.task_dependencies[f"explore:{target}"]["failure_kind"] == \
        "inferred_not_current_state_effect"


def test_unexpected_prerequisite_result_releases_one_target_recheck(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    target, prerequisite = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id="home-frame",
        observations=[{"target": "Disabled input"}, {"target": "Unlock"}],
        source_state_id=home.state_id).added
    assessment = PreviousAssessment(
        outcome="no_visible_change", reason="Input is disabled.",
        matches_intent=False)
    _sync_exploration_task(runtime)
    assert _defer_current_task(
        runtime, {"prerequisite_target": "Unlock", "reason": "Unlock is required."},
        assessment=assessment) == ""
    _sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == prerequisite
    pending = runtime.entry_ledger.begin_explicit_action(
        prerequisite, frame_id="home-frame", page_name="Home")
    runtime.entry_ledger.finish_action(
        pending.action_id, action_executed=True, outcome_verified=False,
        result="Unlock opened an unexpected help panel.", destination_page="Home",
        destination_state_id=home.state_id)
    # The target recheck outranks the still-retryable prerequisite even when
    # the prerequisite was created first.
    runtime.task_creation_order[f"explore:{prerequisite}"] = 1
    runtime.task_creation_order[f"explore:{target}"] = 2
    _sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == target
    dependency = runtime.task_dependencies[f"explore:{target}"]
    assert dependency["status"] == "recheck_after_prerequisite"
    assert dependency["prerequisite_release_consumed"] is True


def test_rechecked_target_can_switch_to_new_prerequisite_not_repeat_old_one(
    tmp_path,
) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    target, first, second = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id="home-frame",
        observations=[
            {"target": "Disabled input"}, {"target": "Unlock"},
            {"target": "Enable editing"},
        ], source_state_id=home.state_id).added
    assessment = PreviousAssessment(
        outcome="no_visible_change", reason="Input remains disabled.",
        matches_intent=False)
    _sync_exploration_task(runtime)
    assert _defer_current_task(
        runtime, {"prerequisite_target": "Unlock", "reason": "Unlock is required."},
        assessment=assessment) == ""
    pending = runtime.entry_ledger.begin_explicit_action(
        first, frame_id="home-frame", page_name="Home")
    runtime.entry_ledger.finish_action(
        pending.action_id, action_executed=True, outcome_verified=True,
        result="Unlock completed.", destination_page="Home",
        destination_state_id=home.state_id)
    _sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == target
    assert _defer_current_task(
        runtime, {"prerequisite_target": "Unlock", "reason": "Still disabled."},
        assessment=assessment).startswith("the same prerequisite was already handled")
    assert _defer_current_task(
        runtime,
        {"prerequisite_target": "Enable editing", "reason": "Visible edit lock remains."},
        assessment=assessment) == ""
    assert runtime.task_dependencies[f"explore:{target}"]["prerequisite_entry_id"] == second


def test_prerequisite_recheck_survives_checkpoint_and_resume(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    target, prerequisite = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id="home-frame",
        observations=[{"target": "Disabled input"}, {"target": "Unlock"}],
        source_state_id=home.state_id).added
    assessment = PreviousAssessment(
        outcome="no_visible_change", reason="Input is disabled.",
        matches_intent=False)
    _sync_exploration_task(runtime)
    assert _defer_current_task(
        runtime, {"prerequisite_target": "Unlock", "reason": "Unlock is required."},
        assessment=assessment) == ""
    pending = runtime.entry_ledger.begin_explicit_action(
        prerequisite, frame_id="home-frame", page_name="Home")
    runtime.entry_ledger.finish_action(
        pending.action_id, action_executed=True, outcome_verified=True,
        result="Unlock completed.", destination_page="Home",
        destination_state_id=home.state_id)
    _sync_exploration_task(runtime)
    _checkpoint(runtime, [])

    resumed = _runtime(tmp_path)
    resumed.restore(str(tmp_path / "graph.json"))
    dependency = resumed.task_dependencies[f"explore:{target}"]
    assert dependency["status"] == "recheck_after_prerequisite"
    assert dependency["rechecked_prerequisite_entry_id"] == prerequisite
    _sync_exploration_task(resumed)
    # A checkpoint has no fresh cursor screenshot.  Resume preserves the
    # recheck fact but must not guess a route until the loop binds one.
    assert resumed.exploration_task is None
    assert resumed.graph.stop_reason == "unverified_route_remaining"


def test_entry_waits_for_owner_survey_then_releases_after_review(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(
        runtime, "Home", _png("white"), identity="new",
        coverage_complete=False, entry_review_complete=False)
    entry = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id="home-frame",
        observations=[{"target": "Open detail"}], source_state_id=home.state_id,
    ).added[0]

    _sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_type == "survey_page"
    assert runtime.exploration_task.region_name == "Main"

    state = loop._region_state(runtime, "Home")
    state.observe_frame("home-reviewed-frame", home.state_id)
    state.apply_agent_update([{
        "name": "Main", "summary": "Fixture controls",
        "coverage_complete": True,
    }], frame_id="home-reviewed-frame")
    runtime.entry_review_audits["home"]["main"]["status"] = "complete"
    _sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == entry


def test_completion_summary_derives_region_children_without_agent_status(
    tmp_path,
) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    complete_entry, gap_entry = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id="home-frame",
        observations=[{"target": "Open"}, {"target": "Unavailable"}],
        source_state_id=home.state_id,
    ).added
    pending = runtime.entry_ledger.begin_explicit_action(
        complete_entry, frame_id="home-frame", page_name="Home")
    runtime.entry_ledger.finish_action(
        pending.action_id, action_executed=True, outcome_verified=True,
        result="Opened.", destination_page="Home",
        destination_state_id=home.state_id)
    runtime.entry_ledger.mark_no_effect_probe(
        gap_entry, result="Unavailable stayed disabled.",
        classification="temporarily_unavailable")

    summary = _completion_summary(runtime)

    assert summary["entry_totals"] == {
        "complete": 1,
        "recorded": 0,
        "invalidated": 0,
        "open": 0,
        "gap": 1,
    }
    region = summary["pages"][0]["regions"][0]
    assert region["status"] == "partial"
    assert summary["pages"][0]["status"] == "partial"


def test_equal_distance_current_page_survey_precedes_ready_entry(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    _register_complete_page(runtime, "Home", _png("white"), identity="known")
    entry = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id="home-frame",
        observations=[{"target": "Ready entry"}], source_state_id=home.state_id,
    ).added[0]
    _add_region(runtime, "Home", home.state_id, "Later", coverage_complete=False)

    _sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_type == "survey_page"
    assert runtime.exploration_task.region_name == "Later"
    assert runtime.exploration_task.entry_id != entry


def test_remote_survey_does_not_block_local_ready_entry(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    detail = _register_complete_page(
        runtime, "Detail", _png("blue"), identity="new", coverage_complete=False)
    _register_complete_page(runtime, "Home", _png("white"), identity="known")
    entry = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id="home-frame",
        observations=[{"target": "Ready entry"}], source_state_id=home.state_id,
    ).added[0]

    _sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == entry
    assert detail.state_id


def test_held_entry_is_not_preempted_by_new_current_page_survey(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    _register_complete_page(runtime, "Home", _png("white"), identity="known")
    entry = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id="home-frame",
        observations=[{"target": "Held entry"}], source_state_id=home.state_id,
    ).added[0]
    _sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == entry

    _add_region(runtime, "Home", home.state_id, "New area", coverage_complete=False)
    _sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == entry


def test_region_closure_is_derived_from_owned_entry_terminal_states(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    first, second = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id="home-frame",
        observations=[{"target": "First"}, {"target": "Second"}],
        source_state_id=home.state_id,
    ).added

    assert _region_exploration_status(runtime, "Home", "Main") == "open"
    for entry_id in (first, second):
        pending = runtime.entry_ledger.begin_explicit_action(
            entry_id, frame_id="home-frame", page_name="Home")
        runtime.entry_ledger.finish_action(
            pending.action_id, action_executed=True, outcome_verified=True,
            result="Verified.", destination_page="Home",
            destination_state_id=home.state_id)
    assert _region_exploration_status(runtime, "Home", "Main") == "complete"

    runtime = _runtime(tmp_path / "partial")
    home = _register_complete_page(runtime, "Home", _png("white"), identity="new")
    entry = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id="home-frame",
        observations=[{"target": "Unavailable"}], source_state_id=home.state_id,
    ).added[0]
    runtime.entry_ledger.mark_no_effect_probe(
        entry, result="Disabled.", classification="temporarily_unavailable")

    assert _region_exploration_status(runtime, "Home", "Main") == "partial"
