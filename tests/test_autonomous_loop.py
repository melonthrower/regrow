"""Offline contracts for Qwen-led screenshot exploration."""

from __future__ import annotations

import io
import json
from dataclasses import replace
from pathlib import Path

from PIL import Image
from gui_rewalk.src.core.scenario.capability_induction import (
    AUTONOMOUS_ENTRY_UID_PREFIX,
    induce_capability_graph,
)

from gui_rewalk.src.core.visual_traversal.runtime import autonomous_loop as loop
from gui_rewalk.src.core.visual_traversal.runtime import (
    autonomous_recovery,
)
from gui_rewalk.src.core.visual_traversal.runtime import (
    autonomous_page_commit,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_completion import (
    RUN_REJECTION_LIMIT,
    TASK_REJECTION_LIMIT,
    _finish_rejection_record,
    _region_exploration_status,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_entry_tools import (
    EntryStatus,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_action_execution import (
    _action_element_uid,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_context import (
    _exploration_map_view,
    _page_entry_history,
    _region_probe_capability_evidence,
    _region_probe_effect_memory,
    _region_probe_ref,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_action_tools import (
    PreviousToolReview,
    action_tool_catalog,
    validate_action_tool_call,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_prompt import (
    AUTONOMOUS_PROMPT,
    _entry_review_feedback_text,
    _history_summary,
    _model_page_correction_text,
    build_prompt,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_page_update import (
    _normalize_new_entry_item,
    _normalize_page_region_item,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_protocol import (
    ENTRY_REVIEW_SPECIALIST_PROMPT,
    PAGE_ONLY_IDENTITY_RESPONSE_SCHEMA,
    PAGE_IDENTITY_RESPONSE_SCHEMA,
    available_tool_catalog,
    protocol_prompt_for,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_region_tools import (
    AutonomousRegionState,
    RegionProtocolError,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_runtime import (
    _page_state_id,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_schema import (
    BUSINESS_EFFECT_KINDS,
    RESPONSE_SCHEMA,
    response_schema_for_tools,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_scheduling import (
    _covered_region_probe_operation_issue,
    _page_survey_need,
    _region_probe_candidates,
    _region_probe_task,
    _repeat_task_frame_action_issue,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_turn import (
    ExplorationTask,
    ObservedBusinessEffect,
    PendingLandingPage,
    PreviousAssessment,
    SurfaceRegistration,
    parse_turn,
)


def _png(color: str) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (100, 80), color).save(stream, format="PNG")
    return stream.getvalue()


def _simple_page_update(page_name: str) -> loop.PageUpdate:
    return loop.PageUpdate(
        page_name=page_name,
        regions=[{
            "name": "Main", "summary": "Visible fixture content",
            "bbox_1000": [0, 0, 1000, 1000],
            "coverage_complete": True,
        }],
        new_entries=[],
    )


def _keep_region_review(request, reason: str = "The partition is coherent."):
    regions = []
    revisions = []
    for item in request.get("existing_regions") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        regions.append({
            "name": name,
            "summary": str(item.get("summary") or name),
        })
        revisions.append({
            "old_region": name,
            "decision": "keep",
            "reason": "This Region remains a stable functional component.",
        })
    return {"regions": regions, "revisions": revisions, "reason": reason}


def _complete_fixture_survey(
    runtime,
    page_name: str,
    screenshot: bytes,
    *,
    region_names: tuple[str, ...] = ("Main",),
) -> None:
    state = loop._region_state(runtime, page_name)
    frame_id = loop.screenshot_frame_id(screenshot)
    state_id = loop._current_page_state_id(runtime)
    if (
        not state_id
        and loop._page_key(runtime.protocol_map.current_page)
        == loop._page_key(page_name)
        and runtime.protocol_map.current_variant
    ):
        state_id = _page_state_id(
            runtime, page_name, runtime.protocol_map.current_variant)
    state.observe_frame(frame_id, state_id)
    state.apply_agent_update([
        {
            "name": region_name,
            "summary": "Visible fixture content",
            "bbox_1000": [0, 0, 1000, 1000],
            "coverage_complete": True,
        }
        for region_name in region_names
    ], frame_id=frame_id)
    page_audits = runtime.entry_review_audits.setdefault(
        loop._page_key(page_name), {})
    for region_name in region_names:
        region_ref, _ = runtime.region_registry.bind(
            page_name=page_name,
            region_name=region_name,
            state_id=state_id,
            summary="Visible fixture content",
        )
        state.set_region_ref(region_name, region_ref)
        page_audits[loop._page_key(region_name)] = {
            "page_name": page_name,
            "region_name": region_name,
            "frame_id": frame_id,
            "status": "complete",
            "coverage_basis": "fixture",
        }
    runtime.protocol_map.upsert_regions(
        page_name, state.snapshot().get("regions") or [])


def _register_reviewed_main_region(
    runtime,
    page_name: str,
    scene: loop.ObservedScene,
    screenshot: bytes,
) -> None:
    assert loop._apply_main_agent_page_update(
        runtime,
        _simple_page_update(page_name),
        scene,
        screenshot,
        [],
        allow_same_frame_completion=True,
        region_reviewed=True,
    ) == ""
    _complete_fixture_survey(runtime, page_name, screenshot)


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
    frame_id = loop.screenshot_frame_id(screenshot)
    state.observe_frame(frame_id)
    state.apply_agent_update([{
        "name": "Main",
        "coverage_complete": False,
    }], frame_id=frame_id)


def _turn(
    screen: str,
    *,
    action: str,
    target: str = "",
    point=None,
    outcome: str = "not_applicable",
    corrected_target: str = "",
    matches_intent: bool = True,
    tool_name: str = "",
    tool_arguments=None,
    identity: str = "new",
    tool_review=None,
    page_update=None,
    entry_review=None,
    previous_reason: str = "",
    failure_kind: str = "",
    variant_name: str = "default",
    variant_identity: str = "",
    visible_predicates=None,
    purpose: str = "",
    visible_effect: str = "",
):
    if not purpose and action == "CALL_TOOL":
        if tool_name == "navigate":
            purpose = "navigation"
        elif tool_name == "scroll":
            purpose = "region_survey"
        elif tool_name == "hover":
            purpose = "locating"
        elif tool_name in {"click", "input_text", "gesture"}:
            purpose = (
                "entry_attempt"
                if str((tool_arguments or {}).get("entry_id") or "").strip()
                else "operation_attempt"
            )
    return loop.AutonomousTurn(
        screen_name=screen,
        previous=PreviousAssessment(
            outcome=outcome,
            reason=(
                previous_reason
                or ("Previous action assessed"
                    if outcome != "not_applicable" else "No previous action")
            ),
            matches_intent=matches_intent,
            failure_kind=failure_kind,
            visible_effect=visible_effect,
        ),
        decision=loop.AutonomousDecision(
            action=action,
            target=target,
            point_1000=point,
            direction="down" if action == "SCROLL" else "",
            reason=f"Explore {target or screen}",
            tool_name=tool_name,
            tool_arguments=dict(tool_arguments or {}),
            purpose=purpose,
        ),
        registration=SurfaceRegistration(
            identity=identity,
            matched_page_name=(screen if identity == "known" else ""),
            variant_name=variant_name,
            variant_identity=(variant_identity or identity),
            visible_predicates=list(visible_predicates or []),
        ),
        previous_tool_review=(
            PreviousToolReview(**tool_review)
            if tool_review else None
        ),
        page_update=page_update,
        entry_review=(
            loop.EntryReview(independent_entries=list(entry_review))
            if entry_review is not None else None
        ),
    )


class _Agent:
    model = "qwen-fixture"

    def __init__(self, turns):
        self.turns = iter(turns)
        self._staged_turns = []
        self._landing_identity_turn = None
        self.auto_stage_variants = True
        self.calls = []
        self.backend_runs = []

    def decide(self, screenshot, history, **values):
        self.calls.append((screenshot, list(history), dict(values)))
        if self._staged_turns:
            return self._staged_turns.pop(0)
        phase = str(
            ((values.get("exploration_map") or {}).get("task") or {})
            .get("phase") or ""
        )
        if phase == "identify_variant" and self._landing_identity_turn is not None:
            turn = self._landing_identity_turn
            self._staged_turns.append(replace(
                turn,
                decision=loop.AutonomousDecision(
                    action="NONE",
                    target="",
                    point_1000=None,
                    direction="",
                    reason="Fixture accepts the Variant identity result.",
                ),
                previous_tool_review=PreviousToolReview(
                    decision="accept",
                    reason="The specialist result matches the fixture frame.",
                ),
                page_update=None,
                entry_review=None,
            ))
            return replace(
                turn,
                decision=loop.AutonomousDecision(
                    action="CALL_TOOL",
                    target="",
                    point_1000=None,
                    direction="",
                    reason="Ask the Variant specialist to classify the landing.",
                    tool_name="page_identity",
                    tool_arguments={
                        "suspected_pages": [turn.screen_name],
                        "proposed_new_name": "",
                        "reason": "Classify the material Variant on the selected Page.",
                    },
                ),
                registration=SurfaceRegistration(
                    identity="uncertain",
                    matched_page_name="",
                    variant_name="",
                    variant_identity="uncertain",
                    visible_predicates=[],
                ),
                previous_tool_review=None,
                page_update=None,
                entry_review=None,
            )
        try:
            turn = next(self.turns)
        except StopIteration:
            return None
        if turn is None:
            return None
        pending_action = (
            (values.get("exploration_map") or {}).get("pending_action")
        )
        if (
            phase == "identify_page"
            and isinstance(pending_action, dict)
            and turn.registration.identity in {"known", "new"}
            and turn.registration.variant_identity in {"known", "new"}
            and turn.decision.tool_name not in {
                "page_identity", "report_record_error", "handle_interruption",
            }
        ):
            self._landing_identity_turn = turn
            self._staged_turns.append(replace(
                turn,
                decision=loop.AutonomousDecision(
                    action="NONE",
                    target="",
                    point_1000=None,
                    direction="",
                    reason="Fixture accepts the Page identity result.",
                ),
                registration=SurfaceRegistration(
                    identity=turn.registration.identity,
                    matched_page_name=turn.registration.matched_page_name,
                    variant_name="",
                    variant_identity="uncertain",
                    visible_predicates=[],
                ),
                previous_tool_review=PreviousToolReview(
                    decision="accept",
                    reason="The specialist result matches the fixture frame.",
                ),
                page_update=None,
                entry_review=None,
            ))
            return replace(
                turn,
                decision=loop.AutonomousDecision(
                    action="CALL_TOOL",
                    target="",
                    point_1000=None,
                    direction="",
                    reason="Ask the Page specialist to classify the landing.",
                    tool_name="page_identity",
                    tool_arguments={
                        "suspected_pages": (
                            [turn.screen_name]
                            if turn.registration.identity == "known" else []
                        ),
                        "proposed_new_name": (
                            turn.screen_name
                            if turn.registration.identity == "new" else ""
                        ),
                        "reason": "Classify the stable Page in the landing frame.",
                    },
                ),
                registration=SurfaceRegistration(
                    identity="uncertain",
                    matched_page_name="",
                    variant_name="",
                    variant_identity="uncertain",
                    visible_predicates=[],
                ),
                previous_tool_review=None,
                page_update=None,
                entry_review=None,
            )
        if (
            self.auto_stage_variants
            and phase == "identify_page"
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

    def resolve_page_identity(self, request):
        turn = self._landing_identity_turn
        if turn is None:
            return {
                "status": "uncertain",
                "reason": "The fixture has no pending landing identity.",
            }
        stage = str(request.get("identity_stage") or "").strip().casefold()
        if stage == "page":
            identity = turn.registration.identity
            return {
                "status": identity,
                "page_name": turn.screen_name,
                "matched_page_name": (
                    turn.screen_name if identity == "known" else ""
                ),
                "surface_kind": "page",
                "summary": f"Fixture Page {turn.screen_name}",
                "supporting_evidence": ["The fixture landing frame is stable."],
                "conflicting_evidence": [],
                "checked_candidates": list(request.get("suspected_pages") or []),
                "reason": "The stable fixture Page anchors match this result.",
            }
        if stage == "variant":
            identity = turn.registration.variant_identity
            result = {
                "variant_name": turn.registration.variant_name,
                "variant_identity": identity,
                "visible_predicates": list(
                    turn.registration.visible_predicates or []),
                "supporting_evidence": [
                    "The fixture material state matches this Variant."
                ],
                "conflicting_evidence": [],
                "checked_candidates": [],
                "reason": "The fixture operation state supports this Variant.",
            }
            self._landing_identity_turn = None
            return result
        return {
            "status": "uncertain",
            "reason": "The fixture only handles staged Page and Variant identity.",
        }

    def review_region_proposal(self, request):
        return {
            "decision": "accept",
            "issues": [],
            "reason": "The fixture Region proposal is complete and coherent.",
        }

    def map_region_partitions(self, request):
        after = [
            str(item.get("id") or "")
            for item in request.get("after_regions") or []
            if isinstance(item, dict) and str(item.get("id") or "")
        ]
        self.region_mapping_calls = getattr(self, "region_mapping_calls", [])
        self.region_mapping_calls.append(dict(request))
        return {"matches": [], "new": after, "uncertain": []}

    def review_entry_candidates(self, request):
        candidates = [{
            "region_name": item.get("region_name"),
            "target": item.get("target"),
        } for item in request.get("candidates") or []]
        self.entry_review_calls = getattr(self, "entry_review_calls", [])
        self.entry_review_calls.append(dict(request))
        return {
            "independent_entries": candidates,
            "deferred_entries": [],
            "deferred_regions": [],
            "reason_consistent": True,
            "reason": "The fixture candidates represent primary functions.",
        }


class _QwenTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.model_version = ""

    def predict_mm_with_policy(
        self, prompt, images, max_attempts, timeout_seconds=None,
        system_prompt="",
    ):
        self.calls.append({
            "prompt": prompt,
            "system_prompt": system_prompt,
            "images": list(images),
            "max_attempts": max_attempts,
            "timeout_seconds": timeout_seconds,
        })
        return next(self.responses), 123, 45, 1

    @staticmethod
    def parse_json(response):
        return json.loads(response)


def _qwen_call_prompt(call):
    return (
        str(call.get("system_prompt") or "")
        + "\n\n"
        + str(call.get("prompt") or "")
    )


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


def _runtime(
    tmp_path, initial, turns, results=(), *, max_actions=6,
    identity_resolver=None, target_edge_scope=None,
    enable_region_probes=False,
):
    agent = _Agent(turns)
    env = _Env(initial, results)
    runtime = loop.AutonomousTraversalRuntime(
        env=env,
        decision_agent=agent,
        app_name="fixture",
        output_root=str(tmp_path),
        max_states=20,
        max_actions=max_actions,
        identity_resolver=identity_resolver,
        target_edge_scope=target_edge_scope,
        enable_region_probes=enable_region_probes,
    )
    return runtime, env, agent


def test_clock_world_writer_keeps_four_material_variants_and_real_edges(
    tmp_path,
) -> None:
    from gui_rewalk.src.core.graph.state_graph import StateGraph

    frames = [
        _png("white"), _png("silver"), _png("blue"), _png("green"),
    ]
    variants = [
        ("world.empty", ["City list is empty", "Add city is available"]),
        (
            "world.add_dialog",
            ["City search input and dismiss control are visible"],
        ),
        (
            "world.search_results",
            ["A city query and at least one result row are visible"],
        ),
        (
            "world.populated",
            ["The city list contains the city created in this run"],
        ),
    ]
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": frames[0]}, [])
    scenes = []
    for index, ((variant_name, predicates), screenshot) in enumerate(
        zip(variants, frames)
    ):
        page_identity = "new" if index == 0 else "known"
        page_name, issue = runtime.protocol_map.observe(
            name="World",
            summary="World clock city management",
            identity=page_identity,
            matched_page_name="World" if index else "",
            surface_kind="dialog" if index in {1, 2} else "page",
            regions=(),
            screenshot=screenshot,
            variant_name=variant_name,
            variant_identity="new",
            visible_predicates=predicates,
            commit_regions=False,
        )
        assert issue == ""
        turn = _turn(
            "World",
            action="NONE",
            identity=page_identity,
            variant_name=variant_name,
            variant_identity="new",
            visible_predicates=predicates,
        )
        scenes.append(loop._register_scene(
            runtime, screenshot, turn, page_name))

    toolbar_ref, _created = runtime.region_registry.bind(
        page_name="World",
        region_name="World Toolbar",
        state_id=scenes[0].state_id,
        summary="Owns the stable Add city entry.",
    )
    dialog_ref, _created = runtime.region_registry.bind(
        page_name="World",
        region_name="Add City Dialog",
        state_id=scenes[1].state_id,
        summary="Owns the city query and result controls.",
    )
    runtime.region_registry.bind(
        page_name="World",
        region_name="Add City Dialog",
        state_id=scenes[2].state_id,
    )
    city_list_ref, _created = runtime.region_registry.bind(
        page_name="World",
        region_name="World City List",
        state_id=scenes[0].state_id,
        summary="Owns created city rows and their cleanup controls.",
    )
    runtime.region_registry.bind(
        page_name="World",
        region_name="World City List",
        state_id=scenes[3].state_id,
    )
    runtime.entry_ledger.record_agent_update(
        page_name="World",
        region_name="World Toolbar",
        frame_id=loop.screenshot_frame_id(frames[0]),
        observations=[{"target": "Add city"}],
        source_state_id=scenes[0].state_id,
    )
    runtime.entry_ledger.record_agent_update(
        page_name="World",
        region_name="Add City Dialog",
        frame_id=loop.screenshot_frame_id(frames[1]),
        observations=[{"target": "Dismiss dialog"}],
        source_state_id=scenes[1].state_id,
    )
    runtime.entry_ledger.record_agent_update(
        page_name="World",
        region_name="Add City Dialog",
        frame_id=loop.screenshot_frame_id(frames[2]),
        observations=[{"target": "Dismiss dialog"}],
        source_state_id=scenes[2].state_id,
    )
    runtime.entry_ledger.record_agent_update(
        page_name="World",
        region_name="World City List",
        frame_id=loop.screenshot_frame_id(frames[3]),
        observations=[{"target": "Delete city"}],
        source_state_id=scenes[3].state_id,
    )
    assert toolbar_ref and dialog_ref and city_list_ref
    assert toolbar_ref != "Add city"

    labels = ["Add city", "Enter city query", "Select city result"]
    region_labels = ["World Toolbar", "Add City Dialog", "Add City Dialog"]
    for index, label in enumerate(labels):
        event_index = runtime.graph.record_action_event(
            source=scenes[index].state_id,
            action={"action_type": "CLICK"},
            element_label=label,
            region=region_labels[index],
            evidence={
                "before_frame_id": loop.screenshot_frame_id(frames[index]),
                "after_frame_id": loop.screenshot_frame_id(frames[index + 1]),
            },
        )
        runtime.graph.update_action_event(
            event_index,
            target=scenes[index + 1].state_id,
            outcome="transitioned",
            landing_verified=True,
            target_page_name="World",
            committed=True,
        )

    assert list(runtime.protocol_map.pages) == ["World"]
    assert list(runtime.protocol_map.pages["World"]["variants"]) == [
        item[0] for item in variants
    ]
    assert runtime.graph.graph.number_of_nodes() == 4
    assert {
        node["perception_mode"]
        for _state_id, node in runtime.graph.graph.nodes(data=True)
    } == {"autonomous_vlm"}
    page_id = runtime.protocol_map.page_id("World")
    assert len(runtime.graph.pages[page_id]["variants"]) == 4
    assert len(runtime.graph.action_edges) == 3
    assert {
        edge["source_variant_id"] for edge in runtime.graph.action_edges
    } == {
        runtime.graph.graph.nodes[scene.state_id]["variant_id"]
        for scene in scenes[:-1]
    }
    assert {
        edge["target_variant_id"] for edge in runtime.graph.action_edges
    } == {
        runtime.graph.graph.nodes[scene.state_id]["variant_id"]
        for scene in scenes[1:]
    }

    loop._checkpoint(runtime, [])
    loaded = StateGraph.load(runtime.graph_path)
    assert len(loaded.pages[page_id]["variants"]) == 4

    from gui_rewalk.src.core.scenario.capability_induction import (
        compile_collection_bundle,
    )

    saved_entries = json.loads(
        (Path(tmp_path) / "autonomous_entries.json").read_text("utf-8"))
    saved_regions = json.loads(
        (Path(tmp_path) / "autonomous_regions.json").read_text("utf-8"))
    annotated_path = Path(tmp_path) / "annotated_graph.json"
    capability_path = Path(tmp_path) / "capability_graph.json"
    bundle = compile_collection_bundle(
        runtime.graph_path,
        str(capability_path),
        annotated_graph_path=str(annotated_path),
        entries_path=str(Path(tmp_path) / "autonomous_entries.json"),
        regions_path=str(Path(tmp_path) / "autonomous_regions.json"),
    )
    assert bundle["projected_elements"] == 3
    loaded = StateGraph.load(str(annotated_path))
    assert len(loaded.pages[page_id]["variants"]) == 4
    assert {
        scene.state_id: [
            item["name"]
            for item in loaded.graph.nodes[scene.state_id]["elements"]
        ]
        for scene in scenes
    } == {
        scenes[0].state_id: ["Add city"],
        scenes[1].state_id: ["Dismiss dialog"],
        scenes[2].state_id: ["Dismiss dialog"],
        scenes[3].state_id: ["Delete city"],
    }
    capability_graph = json.loads(capability_path.read_text("utf-8"))
    assert capability_graph["source_graph_digest"] == bundle[
        "source_graph_digest"]
    assert capability_graph["capabilities"] == []


    resumed, _env, _agent = _runtime(
        tmp_path, {"screenshot": frames[-1]}, [])
    resumed.restore(str(annotated_path))
    assert list(resumed.protocol_map.pages["World"]["variants"]) == [
        item[0] for item in variants
    ]
    assert len(resumed.graph.pages[page_id]["variants"]) == 4
    assert resumed.region_registry.has_state_occurrence(
        "World", scenes[2].state_id)
    assert resumed.entry_ledger.get("ae2").source_state_ids == [
        scenes[1].state_id, scenes[2].state_id]
    assert saved_regions["schema"] == (
        "gui_rewalk.autonomous_regions_by_page.v8")
    assert saved_regions["region_groups"]["schema"] == (
        "gui_rewalk.autonomous_region_groups.v6")
    requests = []

    def resolve_restored(request):
        requests.append(request)
        return {
            "status": "known",
            "page_name": "World",
            "matched_page_name": "World",
            "variant_name": "world.populated",
            "variant_identity": "known",
            "visible_predicates": variants[-1][1],
            "surface_kind": "page",
            "summary": "The populated World Page is visible.",
            "supporting_evidence": ["The created city row is visible."],
            "conflicting_evidence": [],
            "checked_candidates": ["World"],
            "reason": "The Page anchors and populated Variant both match.",
        }

    evidence = resumed.protocol_map.call_tool(
        "page_identity",
        {
            "suspected_pages": ["World"],
            "proposed_new_name": "",
            "reason": "Re-identify the restored World screenshot.",
        },
        frames[-1],
        page_identity_resolver=resolve_restored,
    )
    assert evidence.status == "known"
    restored_variants = requests[0]["registered_pages"][0]["variants"]
    assert [item["variant_name"] for item in restored_variants] == [
        item[0] for item in variants
    ]
    assert all(item["representative_screenshot"] for item in restored_variants)


def test_new_material_variant_requires_its_own_region_occurrence(
    tmp_path,
) -> None:
    first = _png("white")
    second = _png("silver")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": first}, [])

    page_name, issue = runtime.protocol_map.observe(
        name="World",
        summary="World clock",
        identity="new",
        matched_page_name="",
        surface_kind="page",
        regions=(),
        screenshot=first,
        variant_name="world.empty",
        variant_identity="new",
        visible_predicates=["The city list is empty"],
        commit_regions=False,
    )
    assert issue == ""
    first_scene = loop._register_scene(
        runtime,
        first,
        _turn(
            "World",
            action="NONE",
            identity="new",
            variant_name="world.empty",
            variant_identity="new",
            visible_predicates=["The city list is empty"],
        ),
        page_name,
    )
    _complete_fixture_survey(runtime, "World", first)

    page_name, issue = runtime.protocol_map.observe(
        name="World",
        summary="World clock",
        identity="known",
        matched_page_name="World",
        surface_kind="dialog",
        regions=(),
        screenshot=second,
        variant_name="world.add_dialog",
        variant_identity="new",
        visible_predicates=["The Add city dialog is visible"],
        commit_regions=False,
    )
    assert issue == ""
    second_scene = loop._register_scene(
        runtime,
        second,
        _turn(
            "World",
            action="NONE",
            identity="known",
            variant_name="world.add_dialog",
            variant_identity="new",
            visible_predicates=["The Add city dialog is visible"],
        ),
        page_name,
    )

    assert runtime.region_registry.has_state_occurrence(
        "World", first_scene.state_id)
    assert _page_survey_need(
        runtime, "World", second_scene.state_id) == (
            "material_variant_has_no_region_occurrence",
            "",
            "record_regions",
        )

    main_ref = runtime.region_registry.region_ref("World", "Main")
    runtime.region_registry.bind(
        page_name="World",
        region_name="Main",
        state_id=second_scene.state_id,
        equivalent_to_region_ref=main_ref,
    )
    assert _page_survey_need(
        runtime, "World", second_scene.state_id) == ("", "", "")


def test_unreviewed_new_variant_does_not_create_a_state(tmp_path) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path,
        {"screenshot": screenshot},
        [_turn(
            "World",
            action="NONE",
            identity="known",
            variant_name="world.add_dialog",
            variant_identity="new",
            visible_predicates=["City search input is visible"],
        )],
    )
    page_name, issue = runtime.protocol_map.observe(
        name="World",
        summary="World clock",
        identity="new",
        matched_page_name="",
        surface_kind="page",
        regions=(),
        screenshot=screenshot,
        variant_name="world.empty",
        variant_identity="new",
        visible_predicates=["City list is empty"],
        commit_regions=False,
    )
    assert issue == ""
    loop._register_scene(
        runtime,
        screenshot,
        _turn(
            "World", action="NONE", identity="new",
            variant_name="world.empty", variant_identity="new",
            visible_predicates=["City list is empty"],
        ),
        page_name,
    )

    graph = loop.run_autonomous_traversal(
        runtime, {"screenshot": screenshot})

    assert graph.graph.number_of_nodes() == 1
    trace = json.loads(
        (tmp_path / "autonomous_trace.json").read_text("utf-8"))
    assert any(
        item.get("rejection", {}).get("code")
        == "variant_identity_requires_review"
        for item in trace["history"]
    )


def test_reviewed_new_variant_is_committed_under_the_known_page(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    resolver_calls = []

    def resolver(request):
        resolver_calls.append(request)
        return {
            "status": "known",
            "page_name": "World",
            "matched_page_name": "World",
            "variant_name": "world.add_dialog",
            "variant_identity": "new",
            "visible_predicates": ["City search input is visible"],
            "surface_kind": "dialog",
            "summary": "World add-city dialog",
            "reason": "The dialog changes the available operations.",
        }

    turns = [
        _turn(
            "World", action="CALL_TOOL", identity="known",
            variant_name="world.empty", variant_identity="known",
            tool_name="page_identity", tool_arguments={
                "suspected_pages": ["World"],
                "proposed_new_name": "",
                "reason": "Check whether this is a material World Variant.",
            },
        ),
        _turn(
            "World", action="NONE", identity="known",
            variant_name="world.add_dialog", variant_identity="new",
            visible_predicates=["City search input is visible"],
            tool_review={
                "decision": "accept",
                "reason": "The specialist evidence supports a new Variant.",
            },
        ),
    ]
    runtime, env, _agent = _runtime(
        tmp_path, screen, turns, max_actions=1,
        identity_resolver=resolver,
    )
    page_name, issue = runtime.protocol_map.observe(
        name="World",
        summary="World clock",
        identity="new",
        matched_page_name="",
        surface_kind="page",
        regions=(),
        screenshot=screen["screenshot"],
        variant_name="world.empty",
        variant_identity="new",
        visible_predicates=["City list is empty"],
        commit_regions=False,
    )
    assert issue == ""
    loop._register_scene(
        runtime,
        screen["screenshot"],
        _turn(
            "World", action="NONE", identity="new",
            variant_name="world.empty", variant_identity="new",
            visible_predicates=["City list is empty"],
        ),
        page_name,
    )

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert len(resolver_calls) == 1
    assert len(env.actions) == 0
    assert runtime.pending_page_identity is None
    assert list(runtime.protocol_map.pages) == ["World"]
    assert list(runtime.protocol_map.pages["World"]["variants"]) == [
        "world.empty", "world.add_dialog",
    ]
    assert graph.graph.number_of_nodes() == 2
    page_id = runtime.protocol_map.page_id("World")
    assert len(graph.pages[page_id]["variants"]) == 2


def _identity_arguments(name: str) -> dict:
    return {
        "suspected_pages": [],
        "proposed_new_name": name,
        "reason": f"Check whether {name} is a distinct page.",
    }


def test_android_external_surface_never_reaches_agent_or_page_registration(
    tmp_path, monkeypatch,
) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, env, agent = _runtime(tmp_path, screen, [])
    env.vm_platform = "android"
    runtime.platform = "android"
    monkeypatch.setattr(
        autonomous_recovery, "is_app_foreground",
        lambda _env, _app: False,
    )
    monkeypatch.setattr(
        autonomous_recovery, "focus_app_window",
        lambda _env, _app: False,
    )
    monkeypatch.setattr(
        autonomous_recovery, "restart_app_preserving_data",
        lambda _env, _app: False,
    )

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "left_target_app"
    assert graph.graph.number_of_nodes() == 0
    assert agent.calls == []
    assert env.actions == []
    trace = json.loads(
        (tmp_path / "autonomous_trace.json").read_text("utf-8"))
    violation = next(
        item for item in trace["history"]
        if item.get("kind") == "app_scope_violation")
    assert violation["outcome"] == "left_target_app"


def test_android_unknown_focus_is_resolved_by_main_agent(
    tmp_path, monkeypatch,
) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, env, agent = _runtime(
        tmp_path,
        screen,
        [_turn(
            "",
            action="CALL_TOOL",
            tool_name="report_app_scope",
            tool_arguments={"classification": "target_app"},
            identity="uncertain",
            variant_name="",
            variant_identity="uncertain",
        )],
        max_actions=1,
    )
    env.vm_platform = "android"
    runtime.platform = "android"
    runtime.action_count = 1
    runtime.protocol_map.current_page = "Home"
    runtime.protocol_map.current_variant = "default"
    monkeypatch.setattr(
        autonomous_recovery, "is_app_foreground",
        lambda _env, _app: None,
    )

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "max_actions"
    assert len(agent.calls) == 1
    scope_call = agent.calls[0][2]
    assert (
        scope_call["exploration_map"]["task"]["phase"]
        == "resolve_app_scope"
    )
    assert [item["name"] for item in scope_call["tool_catalog"]] == [
        "report_app_scope",
    ]
    assert env.actions == []
    trace = json.loads(
        (tmp_path / "autonomous_trace.json").read_text("utf-8"))
    resolution = next(
        item for item in trace["history"]
        if item.get("kind") == "app_scope_resolution")
    assert resolution["outcome"] == "target_app"
    assert resolution["semantic_graph_recorded"] is False


def test_desktop_external_surface_never_reaches_agent_or_page_registration(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, env, agent = _runtime(tmp_path, screen, [])

    class _Owner:
        def __init__(self) -> None:
            self.calls = 0

        def is_foreground(self):
            self.calls += 1
            return False

        @staticmethod
        def activate():
            return False

    owner = _Owner()
    runtime.platform = "desktop"
    runtime.desktop_window_owner = owner
    runtime.relaunch_fn = lambda: {}

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "left_target_app"
    assert graph.graph.number_of_nodes() == 0
    assert agent.calls == []
    assert env.actions == []
    assert owner.calls == 2


def test_autonomous_run_keeps_desktop_focus_dependencies(
    tmp_path, monkeypatch,
) -> None:
    screen = {"screenshot": _png("navy")}
    env = _Env(screen)
    owner = object()
    relaunch = lambda: screen
    monkeypatch.setattr(
        loop,
        "run_autonomous_traversal",
        lambda runtime, _initial_obs: runtime,
    )

    runtime = loop.run(
        env=env,
        app_name="fixture",
        output_root=str(tmp_path),
        initial_obs=screen,
        transport_agent=_QwenTransport([]),
        desktop_window_owner=owner,
        relaunch_fn=relaunch,
    )

    assert runtime.desktop_window_owner is owner
    assert runtime.relaunch_fn is relaunch


def test_desktop_external_entry_reactivates_bound_window_first(tmp_path) -> None:
    before = {"screenshot": _png("navy")}
    recovered = {"screenshot": _png("blue")}
    runtime, env, _agent = _runtime(tmp_path, before, [])

    class _Owner:
        @staticmethod
        def is_foreground():
            return False

        @staticmethod
        def activate():
            env.current = recovered
            return True

    runtime.platform = "desktop"
    runtime.desktop_window_owner = _Owner()
    relaunch_calls = []

    def relaunch():
        relaunch_calls.append(True)
        return recovered

    runtime.relaunch_fn = relaunch
    event_index = runtime.graph.record_action_event(
        source="clock", action={"action_type": "CLICK"},
        element_label="Open link", region="Help",
    )
    history = [{"kind": "action", "outcome": "executed"}]
    pending = loop.PendingAction(
        source=loop.ObservedScene(
            state_id="clock", screenshot=before["screenshot"],
            page_name="Clock",
        ),
        event_index=event_index,
        primitive={"action_type": "CLICK"},
        target="Open link",
        reason="Open help",
        history_index=0,
        evidence={},
    )

    status, observation = autonomous_recovery._handle_outside_target_app(
        runtime, pending, history)

    assert status == "recovered"
    assert observation == recovered
    assert relaunch_calls == []
    assert history[0]["outcome"] == "left_target_app"
    assert history[-1]["outcome"] == "reactivated_target_app"
    assert history[-1]["semantic_graph_recorded"] is False
    assert runtime.protocol_map.pages == {}


def test_android_external_entry_is_semantic_terminal_then_app_reopens(
    tmp_path, monkeypatch,
) -> None:
    home = {"screenshot": _png("navy")}
    external = {"screenshot": _png("orange")}
    runtime, env, _agent = _runtime(
        tmp_path,
        home,
        [
            _turn(
                "Home", action="CALL_TOOL", identity="known",
                tool_name="navigate",
                tool_arguments={"operation": "wait"},
                page_update=loop.PageUpdate(
                    page_name="Home",
                    regions=[{
                        "name": "Main", "summary": "Main functions",
                        "bbox_1000": [0, 0, 1000, 1000],
                        "coverage_complete": True,
                    }],
                    new_entries=[{
                        "region_name": "Main",
                        "target": "Open external help",
                        "bbox_1000": [300, 300, 700, 500],
                    }],
                ),
            ),
            _turn(
                "Home", action="CALL_TOOL", identity="known",
                target="Open external help", tool_name="click",
                tool_arguments={
                    "target": "Open external help", "entry_id": "ae1",
                    "point_1000": [500, 400],
                },
            ),
                _turn(
                    "Home", action="CALL_TOOL", identity="known",
                    tool_name="finish_exploration", tool_arguments={
                        "reason": "All registered function entries are covered.",
                        "unreachable_evidence": [],
                    },
                ),
                _turn(
                    "Home", action="CALL_TOOL", identity="known",
                    tool_name="finish_exploration", tool_arguments={
                        "reason": "All registered function entries are covered.",
                        "unreachable_evidence": [],
                    },
                ),
        ],
        [external],
    )
    runtime.protocol_map.observe(
        name="Home", summary="Visible Home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=home["screenshot"], commit_regions=False,
    )
    env.vm_platform = "android"
    runtime.platform = "android"
    monkeypatch.setattr(
        autonomous_recovery, "is_app_foreground",
        lambda _env, _app: env.current["screenshot"] != external["screenshot"],
    )
    monkeypatch.setattr(
        autonomous_recovery, "focus_app_window",
        lambda _env, _app: False,
    )

    def restart(_env, _app_name):
        env.current = home
        return True

    monkeypatch.setattr(
        autonomous_recovery, "restart_app_preserving_data", restart)

    graph = loop.run_autonomous_traversal(runtime, home)

    assert graph.stop_reason in {
        "framework_complete", "all_remaining_work_suspended",
    }
    assert list(runtime.protocol_map.pages) == ["Home"]
    assert runtime.entry_ledger.get("ae1").status.value == "verified"
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text("utf-8"))
    external_action = next(
        item for item in trace["history"]
        if item.get("semantic_only_terminal") is True)
    assert external_action["outcome"] == "left_target_app"
    assert any(
        item.get("kind") == "app_scope_recovery"
        and item.get("outcome") == "restarted_target_app"
        for item in trace["history"]
    )


def test_app_scope_response_uses_one_identity_free_tool() -> None:
    catalog = [
        item for item in available_tool_catalog(pending_identity=False)
        if item.get("name") == "report_app_scope"
    ]
    schema = response_schema_for_tools(
        catalog, identity_stage="app_scope")

    assert "screen" not in schema["properties"]
    assert "screen" not in schema["required"]
    turn, error = parse_turn(
        {
            "reason": "当前截图仍显示目标应用主体，但上方有临时通知。",
            "task_strategy": "先报告应用归属，再继续原探索任务。",
            "action": {
                "tool_name": "report_app_scope",
                "tool_arguments": {
                    "classification": "target_app_obstructed",
                },
            },
        },
        has_previous=False,
        available_tools=["report_app_scope"],
        identity_stage="app_scope",
    )
    assert error == ""
    assert turn is not None
    assert turn.decision.tool_name == "report_app_scope"


def test_framework_does_not_run_unassigned_action_on_completed_map(
    tmp_path,
) -> None:
    before = {"screenshot": _png("navy")}
    after = {"screenshot": _png("blue")}
    runtime, env, _agent = _runtime(
        tmp_path, before, [], [after], max_actions=0)
    runtime.max_states = 1
    runtime.protocol_map.observe(
        name="Home", summary="Visible Home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=before["screenshot"], commit_regions=False,
    )
    _complete_fixture_survey(runtime, "Home", before["screenshot"])
    runtime.decision_agent.turns = iter([
        _turn(
            "Home", action="CALL_TOOL", identity="known", target="Refresh",
            tool_name="click", tool_arguments={
                "target": "Refresh", "point_1000": [500, 500],
                "entry_id": "",
            },
        ),
        _turn(
            "Home", action="CALL_TOOL", identity="known",
            outcome="changed", corrected_target="Refresh",
            tool_name="finish_exploration", tool_arguments={
                "reason": "The same known Variant has been observed.",
                "unreachable_evidence": [],
            },
        ),
        _turn(
            "Home", action="CALL_TOOL", identity="known",
            tool_name="finish_exploration", tool_arguments={
                "reason": "The same known Variant has been observed.",
                "unreachable_evidence": [],
            },
        ),
    ])

    graph = loop.run_autonomous_traversal(runtime, before)

    assert graph.stop_reason in {
        "framework_complete", "all_remaining_work_suspended",
    }
    assert len(env.actions) == 0
    assert graph.graph.number_of_nodes() == 0
    assert len(runtime.protocol_map.pages) == 1


def test_main_prompt_requires_before_after_grounded_landing_assessment() -> None:
    assert "可复核的应用能力地图" in AUTONOMOUS_PROMPT
    assert "历史只用于理解已走路线、失败原因和仍有效约束" in (
        AUTONOMOUS_PROMPT)
    assert "不能继续点击旧坐标" in AUTONOMOUS_PROMPT
    assert "区分“值得记录”和“需要探索”" in AUTONOMOUS_PROMPT
    assert "截图只能证明控件存在及其可见语义" in AUTONOMOUS_PROMPT
    assert "复核意见用于证据讨论，不替代视觉判断" in AUTONOMOUS_PROMPT
    assert "先独立描述最新截图中的争议对象" in (
        _entry_review_feedback_text({"status": "disagreement"}))
    assert "不能据此关闭覆盖" in _entry_review_feedback_text({
        "status": "disagreement",
        "deferred_regions": ["Top Navigation Bar"],
    })
    assert "固定完整截图" in ENTRY_REVIEW_SPECIALIST_PROMPT
    assert "deferred_entries 表示操作有探索价值" in (
        ENTRY_REVIEW_SPECIALIST_PROMPT)
    region_feedback = _model_page_correction_text({
        "review": {"reason": "The old content may be obscured."},
    })
    assert "Reviewer 的待核对理由" in region_feedback
    assert "请先独立说明当前截图" in region_feedback
    assert "阶段完成后停止操作" in AUTONOMOUS_PROMPT
    settlement = protocol_prompt_for(
        "explore_entry", "locate_entry", has_pending_action=True)
    assert "只比较动作前截图和最新截图" in settlement
    assert "不得根据落地结果将它改写成其他控件" in settlement
    assert "中间导航或定位动作失败" in settlement
    assert "尚未完成的路线、定位和调查步骤继续保留" in settlement
    matches_description = RESPONSE_SCHEMA["properties"][
        "previous_action"
    ]["properties"]["matches_intent"]["description"]
    assert "pending entry or action" in matches_description
    previous_schema = RESPONSE_SCHEMA["properties"]["previous_action"]
    assert "reason" in previous_schema["required"]
    assert "target_name" not in previous_schema["properties"]
    assert set(RESPONSE_SCHEMA["properties"]["screen"][
        "properties"]) == {"name", "identity", "variant"}


def test_prompt_keeps_current_task_scoped_without_blocking_intermediate_edges() -> None:
    survey = build_prompt(
        [], app_name="fixture", platform="local_html",
        exploration_map={"exploration_task": {
            "task_type": "survey_page", "phase": "survey_region",
        }},
    )
    entry = build_prompt(
        [], app_name="fixture", platform="local_html",
        exploration_map={"exploration_task": {
            "task_type": "explore_entry", "phase": "locate_entry",
        }},
    )
    assert "当前任务是调查页面" in survey
    assert "功能区域是共同承担一个稳定功能角色的组件组" in survey
    assert "当前阶段是继续调查 task.region" in survey
    assert "当前任务是探索一个已经登记的入口" in entry
    assert "路线、定位、恢复和真正尝试都属于这条任务" in entry
    assert "当前阶段是定位并尝试入口" in entry
    assert "purpose=entry_attempt" in entry


def test_stage_transition_defers_tool_until_fresh_stage_prompt(tmp_path) -> None:
    screen = {"screenshot": _png("navy")}
    frame_id = loop.screenshot_frame_id(screen["screenshot"])
    runtime, env, _agent = _runtime(
        tmp_path,
        screen,
        [
            _turn(
                "Home", action="CALL_TOOL", target="Open details",
                page_update=_simple_page_update("Home"),
                tool_name="click", tool_arguments={
                    "target": "Open details",
                    "point_1000": [500, 500],
                    "entry_id": "",
                },
            ),
            _turn(
                "Home", action="NONE", identity="known",
                page_update=_simple_page_update("Home"),
            ),
            _turn(
                "Home", action="NONE", identity="known",
            ),
            _turn(
                "Home", action="CALL_TOOL", identity="known",
                tool_name="finish_exploration", tool_arguments={
                    "reason": "No staged work remains.",
                    "unreachable_evidence": [],
                },
            ),
        ],
    )

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "framework_complete"
    assert env.actions == []
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text("utf-8"))
    transitions = [
        item for item in trace["history"]
        if item.get("kind") == "stage_transition"
    ]
    transition = transitions[0]
    assert transition["from_stage"] == "identify_page"
    assert transition["to_stage"] == "identify_variant"
    assert transitions[1]["from_stage"] == "identify_variant"
    assert transitions[1]["to_stage"] == "record_regions"
    assert transition["deferred_tool"] == "click"
    assert transition["deferred_status"] == "not_executed"
    assert any(
        item.get("kind") == "stage_context_feedback"
        and item.get("outcome") == "page_update_deferred"
        for item in trace["history"]
    )


def test_history_summary_omits_internal_stage_transition_from_agent_context() -> None:
    summary = _history_summary([{
        "kind": "stage_transition",
        "outcome": "stage_advanced",
        "from_stage": "locate_entry",
        "to_stage": "route_to_source",
        "deferred_tool": "click",
        "deferred_status": "not_executed",
        "deferred_entry_attempt_created": False,
        "detail": "The requested tool was not executed.",
    }])

    assert summary["recent_results"] == []


def test_prompt_moves_latest_rejection_to_current_task_status() -> None:
    history = [{
        "kind": "page_update_result",
        "screen": "Home",
        "status": "rejected",
        "rejected_items": [{
            "kind": "region",
            "error_code": "coverage_same_frame_without_new_evidence",
            "field": "coverage_complete",
            "region_name": "Results",
            "reason": "No new visual evidence was observed before completion was requested.",
        }],
    }]

    summary = _history_summary(history)
    assert summary["recent_results"] == []
    feedback = summary["active_rejection"]["feedback"]
    assert "Results" in feedback
    assert "No new visual evidence" in feedback
    assert "coverage_same_frame_without_new_evidence" not in feedback

    prompt = build_prompt(
        history,
        app_name="fixture",
        platform="local_html",
        exploration_map={"task": {
            "type": "survey_page", "phase": "survey_region",
        }},
    )
    assert "coverage_same_frame_without_new_evidence" not in prompt
    assert prompt.count("No new visual evidence") == 1
    assert "当前任务历史（按时间顺序）" in prompt
    assert "当前探索任务状态（只列仍影响下一步的结论）" in prompt
    assert "不要原样重交" in prompt


def test_prompt_folds_active_constraints_into_compact_task_status() -> None:
    history = [{
        "kind": "action",
        "screen": "Alarm",
        "action": "CLICK",
        "target": "Unlock",
        "outcome": "awaiting_observation",
        "exploration_task_id": "explore:ae2",
    }]
    prompt = build_prompt(
        history,
        app_name="clock",
        platform="android",
        exploration_map={
            "task": {
                "task_id": "explore:ae2",
                "type": "explore_entry",
                "page": "Alarm",
                "region": "Alarm form",
                "phase": "locate_entry",
                "region_survey": "已完成",
                "前置重新检查": {
                    "目标": "Unlock",
                    "真实结果": "Unlock visibly enabled the input.",
                },
                "last_result": "Previous target stayed unavailable.",
                "route_status": "No verified route reaches the target state.",
            },
            "pending_action": {"operation": "click", "target": "Unlock"},
        },
        include_tool_catalog=False,
    )

    status_heading = "当前探索任务状态（只列仍影响下一步的结论）"
    assert prompt.index(status_heading) > prompt.index("当前任务历史")
    status = prompt.split(status_heading, 1)[1]
    assert "待结算：历史第 1 条真实动作" in status
    assert "前置“Unlock”已处理" in status
    assert "Previous target stayed unavailable." in status
    assert "No verified route reaches the target state." in status
    assert sum(line.startswith("- ") for line in status.splitlines()) <= 4
    assert '"pending_action"' not in prompt
    assert '"前置重新检查"' not in prompt
    assert '"last_result"' not in prompt
    assert '"route_status"' not in prompt
    assert '"region_survey"' not in prompt


def test_prompt_keeps_only_latest_current_task_strategy_in_status() -> None:
    history = [
        {
            "kind": "observation",
            "screen": "Alarm",
            "task_strategy": "First try the visible tab.",
            "exploration_task_id": "explore:ae2",
        },
        {
            "kind": "observation",
            "screen": "Alarm",
            "task_strategy": "Close the menu, then locate the Alarm tab.",
            "exploration_task_id": "explore:ae2",
        },
        {
            "kind": "observation",
            "screen": "Timer",
            "task_strategy": "Ignore the Alarm task and start Timer.",
            "exploration_task_id": "explore:ae3",
        },
    ]
    prompt = build_prompt(
        history,
        app_name="clock",
        platform="desktop",
        exploration_map={"task": {
            "task_id": "explore:ae2",
            "type": "explore_entry",
            "page": "Alarm",
            "region": "Navigation",
            "phase": "locate_entry",
        }},
        include_tool_catalog=False,
    )

    assert prompt.count("Close the menu, then locate the Alarm tab.") == 1
    assert "First try the visible tab." not in prompt
    assert "Ignore the Alarm task and start Timer." not in prompt
    assert "当前策略：Close the menu, then locate the Alarm tab." in prompt


def test_prompt_keeps_full_task_history_and_latest_action_rejection() -> None:
    history = [{
        "kind": "page_update_result",
        "screen": "Alarm",
        "status": "rejected",
        "rejected_items": [{
            "kind": "region",
            "reason": "Earlier Region correction remains relevant.",
        }],
        "exploration_task_id": "survey:alarm",
    }]
    history.extend({
        "kind": "action",
        "screen": "Alarm",
        "action": "CLICK",
        "target": f"target-{index}",
        "outcome": "observed_change",
        "exploration_task_id": "survey:alarm",
    } for index in range(6))
    history.append({
        "kind": "action",
        "screen": "Alarm",
        "action": "CLICK",
        "target": "Overflow menu button",
        "outcome": "not_executed",
        "exploration_task_id": "survey:alarm",
        "validated_action": {
            "operation": "click",
            "arguments": {"point_1000": [930, 80]},
        },
        "rejection": loop._rejection_feedback(
            "latest_action_rejected",
            "The overflow click must use a different visible point.",
        ),
    })

    prompt = build_prompt(
        history,
        app_name="clock",
        platform="android",
        exploration_map={"task": {
            "task_id": "survey:alarm",
            "type": "survey_page",
            "page": "Alarm",
            "phase": "record_regions",
        }},
    )

    assert all(f"target-{index}" in prompt for index in range(6))
    assert "Earlier Region correction remains relevant" in prompt
    assert "The overflow click must use a different visible point" in prompt
    assert 'CLICK Overflow menu button parameters={"point_1000":[930,80]}' in prompt


def test_prompt_drops_rejection_bound_to_previous_entry_task() -> None:
    history = [
        {
            "kind": "action",
            "screen": "Recipe collection",
            "target": "Ginger vegetable soup card",
            "outcome": "not_executed",
            "exploration_task_id": "explore:ae3",
            "rejection": loop._rejection_feedback(
                "repeat_task_action_on_same_frame",
                "Ginger duplicate click must be corrected.",
            ),
        },
        {
            "kind": "action",
            "screen": "Recipe collection",
            "target": "Roasted sweet potato tacos card",
            "outcome": "not_executed",
            "exploration_task_id": "explore:ae4",
            "rejection": loop._rejection_feedback(
                "invalid_target",
                "Roasted card must be located again on the current screenshot.",
            ),
        },
    ]

    prompt = build_prompt(
        history,
        app_name="fixture",
        platform="local_html",
        exploration_map={"task": {
            "task_id": "explore:ae4",
            "type": "explore_entry",
            "entry_id": "ae4",
            "page": "Recipe collection",
            "region": "Recipe list",
            "target": "Roasted sweet potato tacos card",
            "phase": "locate_entry",
        }},
    )

    assert "Ginger duplicate click" not in prompt
    assert "Roasted card must be located again" in prompt
    assert "explore:ae3" not in prompt
    assert "explore:ae4" not in prompt
    assert "当前任务历史（按时间顺序）" in prompt


def test_prompt_keeps_review_and_later_pointer_action_in_full_history() -> None:
    history = [
        {
            "kind": "click_review",
            "screen": "Notes",
            "action": "CLICK",
            "target": "Open notes",
            "outcome": "not_executed",
            "exploration_task_id": "explore:ae6",
            "rejection": loop._rejection_feedback(
                "click_review_rejected",
                "The point landed on the card background.",
            ),
        },
        {
            "kind": "action",
            "screen": "Notes",
            "action": "CLICK",
            "target": "Open notes",
            "outcome": "awaiting_observation",
            "exploration_task_id": "explore:ae6",
        },
    ]
    exploration_map = {
        "task": {
            "task_id": "explore:ae6",
            "type": "explore_entry",
            "entry_id": "ae6",
            "page": "Notes",
            "region": "Notes card",
            "target": "Open notes",
            "phase": "locate_entry",
        },
        "pending_action": {"operation": "click", "target": "Open notes"},
    }

    pending_prompt = build_prompt(
        history,
        app_name="fixture",
        platform="local_html",
        exploration_map=exploration_map,
    )
    assert "The point landed on the card background" in pending_prompt
    assert "1. CLICK Open notes" in pending_prompt
    assert "2. CLICK Open notes" in pending_prompt

    history[-1]["outcome"] = "observed_change"
    exploration_map.pop("pending_action")
    settled_prompt = build_prompt(
        history,
        app_name="fixture",
        platform="local_html",
        exploration_map=exploration_map,
    )
    assert "The point landed on the card background" in settled_prompt


def test_prompt_keeps_all_short_results_for_the_current_task() -> None:
    history = [{
        "kind": "entry_probe",
        "screen": "Recipe collection",
        "target": f"Target {index}",
        "outcome": "observed",
        "detail": f"Current-task result {index}",
        "exploration_task_id": "explore:ae6",
    } for index in range(1, 6)]

    prompt = build_prompt(
        history,
        app_name="fixture",
        platform="local_html",
        exploration_map={"task": {
            "task_id": "explore:ae6",
            "type": "explore_entry",
            "entry_id": "ae6",
            "page": "Recipe collection",
            "region": "Recipe list",
            "target": "Roasted sweet potato tacos card",
            "phase": "locate_entry",
        }},
    )

    for index in range(1, 6):
        assert f"Current-task result {index}" in prompt


def test_history_records_are_bound_to_the_turn_task() -> None:
    records = [{
        "kind": "entry_probe",
        "screen": "Recipe collection",
        "target": "Ginger vegetable soup card",
        "outcome": "no_effect_observed",
    }]
    task = ExplorationTask(
        task_type="explore_entry",
        task_id="explore:ae3",
        entry_id="ae3",
        page_name="Recipe collection",
        region_name="Recipe list",
        phase="locate_entry",
    )

    loop._bind_history_records_to_task(records, task)

    assert records[0]["exploration_task_id"] == "explore:ae3"
    assert records[0]["exploration_task_page"] == "Recipe collection"
    assert records[0]["exploration_task_phase"] == "locate_entry"


def test_entry_task_gets_short_page_and_prioritized_region_memory(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Recipe collection", summary="Recipes", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    runtime.protocol_map.connect(
        page_name, "Previous page", "CLICK", "Back button")
    for index in range(1, 5):
        runtime.protocol_map.connect(
            page_name,
            f"Related page {index}",
            "CLICK",
            f"Open related {index}",
        )
    frame_id = loop.screenshot_frame_id(screenshot)
    state = loop._region_state(runtime, page_name)
    state.observe_frame(frame_id)
    state.apply_agent_update([{
        "name": "Recipe list",
        "survey_memory": "The visible recipe-card range was inspected.",
        "coverage_complete": True,
    }], frame_id=frame_id)
    runtime.entry_ledger.record_agent_update(
        page_name=page_name,
        region_name="Recipe list",
        frame_id=frame_id,
        observations=[
            {"target": "Garden bowl card"},
            {"target": "Citrus salad card"},
            {"target": "Lentil stew card"},
            {"target": "Ginger vegetable soup card"},
            {"target": "Tomato soup card"},
            {"target": "Roasted sweet potato tacos card"},
        ],
    )
    for entry_id in ("ae1", "ae2", "ae3", "ae5"):
        action = runtime.entry_ledger.begin_explicit_action(
            entry_id, frame_id=frame_id, page_name=page_name)
        runtime.entry_ledger.finish_action(
            action.action_id,
            action_executed=True,
            outcome_verified=True,
            result="Opened the expected recipe details.",
            destination_page="Recipe details",
        )
    runtime.entry_ledger.mark_no_effect_probe(
        "ae4",
        result="The card stayed visually unchanged and appears static.",
        classification="not_interactive",
    )
    runtime.exploration_task = ExplorationTask(
        task_type="explore_entry",
        task_id="explore:ae6",
        entry_id="ae6",
        page_name=page_name,
        region_name="Recipe list",
        target="Roasted sweet potato tacos card",
        phase="locate_entry",
    )

    view = loop._exploration_map_view(
        runtime, None, current_screenshot=screenshot)
    task = view["task"]

    assert "Back button" in task["page_memory"]
    assert "Ginger vegetable soup card" in task["region_memory"]
    assert "没有表现为可交互的功能入口" in task["region_memory"]
    assert "Tomato soup card" in task["region_memory"]
    assert "Lentil stew card" in task["region_memory"]
    assert "Citrus salad card" in task["region_memory"]
    assert "Garden bowl card" not in task["region_memory"]
    assert "Open related 3" in task["page_memory"]
    assert "Open related 4" not in task["page_memory"]
    assert len(task["page_memory"]) <= 520
    assert len(task["region_memory"]) <= 760

    prompt = build_prompt(
        [], app_name="fixture", platform="local_html",
        exploration_map=view,
    )
    assert "explore:ae6" not in prompt
    assert '"recent_results"' not in prompt


def test_entry_task_gets_natural_language_history_for_all_page_entries(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World Clock", summary="Clock", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    frame_id = loop.screenshot_frame_id(screenshot)
    runtime.entry_ledger.record_agent_update(
        page_name=page_name,
        region_name="Header Action Bar",
        frame_id=frame_id,
        observations=[{"target": "Application menu button"}],
    )
    runtime.entry_ledger.record_agent_update(
        page_name=page_name,
        region_name="Add World Clock Modal",
        frame_id=frame_id,
        observations=[{"target": "Cancel button"}],
    )
    legacy_payload = runtime.entry_ledger.snapshot()
    legacy_payload["entries"].append({
        "entry_id": "ae3",
        "page_name": page_name,
        "region_name": "full_screen",
        "target": "Temporary notification close button",
        "control_type": "control",
        "status": "verified",
        "discovery_source": "direct_action_backfill",
        "task_eligible": False,
        "last_result": "Notification closed.",
    })
    runtime.entry_ledger = type(runtime.entry_ledger).from_snapshot(
        legacy_payload)
    runtime.exploration_task = ExplorationTask(
        task_type="explore_entry",
        task_id="explore:ae1",
        entry_id="ae1",
        page_name=page_name,
        region_name="Header Action Bar",
        target="Application menu button",
        phase="locate_entry",
    )

    view = loop._exploration_map_view(
        runtime, None, current_screenshot=screenshot)
    page_history = view["task"]["page_history"]

    assert isinstance(page_history, str)
    assert "ae1 是 Header Action Bar 中的“Application menu button”" in page_history
    assert "ae2 是 Add World Clock Modal 中的“Cancel button”" in page_history
    assert "已登记、尚未验证" in page_history
    assert "Temporary notification close button" not in page_history

    prompt = build_prompt(
        [], app_name="Clocks", platform="desktop",
        exploration_map=view,
    )
    assert page_history in prompt
    assert '"page_history"' not in prompt
    assert "当前任务是探索一个已经登记的入口" in prompt
    assert "purpose=entry_attempt" in prompt


def test_invalid_turn_correction_does_not_force_a_landing_wait() -> None:
    correction = loop._invalid_turn_correction(
        model_error="CALL_TOOL requires a tool exposed in the current turn",
    )
    assert "factual reason" in correction
    assert "wait" not in correction


def test_framework_completion_tool_is_not_model_visible(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])

    def names():
        return {
            item["name"] for item in loop._dynamic_tool_catalog(
                runtime, screen["screenshot"])
        }

    assert "finish_exploration" not in names()


def test_survey_catalog_has_no_region_specialist_and_scroll_uses_current_point(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])

    catalog = loop._dynamic_tool_catalog(runtime, screen["screenshot"])
    names = {item["name"] for item in catalog}
    scroll = next(item for item in catalog if item["name"] == "scroll")

    assert "complete_region_probe" not in names
    assert "input_text" not in names
    # New runs have no free Region-operation task: survey only observes and
    # catalogues targets, while real controls are dispatched as exact Entries.
    assert "complete_region_probe" not in names
    assert "input_text" not in names
    assert not ({"map_regions", "inspect_region", "reconcile_regions"} & names)
    assert set(scroll["input_schema"]["properties"]) == {
        "container_hint", "point_1000", "direction", "amount",
    }
    assert "region_scan_id" not in scroll["input_schema"]["required"]
    page_update = RESPONSE_SCHEMA["properties"]["page_update"]["anyOf"][0]
    assert set(page_update["properties"]) == {"regions"}
    region = page_update["properties"]["regions"]["items"]
    assert region["required"] == [
        "name", "summary", "coverage_complete", "entries",
    ]
    assert set(region["properties"]) == {
        "name", "summary", "survey_memory", "coverage_complete",
        "same_group_as", "split_from_group", "entries",
    }
    assert "纯参数操作不建任务的理由" in region[
        "properties"]["survey_memory"]["description"]
    assert "survey_memory" not in region["required"]
    entry = region["properties"]["entries"]["items"]
    assert "框架自动绑定到父区域" in region[
        "properties"]["entries"]["description"]
    assert "一个代表目标" in entry[
        "properties"]["target"]["description"]
    assert entry["required"] == ["target", "operation", "subject"]
    assert set(entry["properties"]) == {
        "target", "operation", "subject", "control_type",
    }
    assert entry["additionalProperties"] is False


def test_region_probe_keeps_point_binding_across_passive_pixel_change(
    tmp_path,
) -> None:
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": _png("navy")}, [])
    state = loop._region_state(runtime, "Search")
    state.observe_frame("frame-before-passive-change", "state-search-dialog")
    state.apply_agent_update([{
        "name": "Search Results",
        "summary": "Search field and result surface",
        "bbox_1000": [300, 200, 700, 800],
        "coverage_complete": True,
    }], frame_id="frame-before-passive-change")
    state.observe_frame("frame-after-passive-change", "state-search-dialog")
    runtime.exploration_task = ExplorationTask(
        task_type="probe_region",
        task_id="probe:search-results:1",
        page_name="Search",
        region_name="Search Results",
        phase="probe_region",
    )
    decision = loop.AutonomousDecision(
        action="INPUT_TEXT",
        target="Search input field",
        point_1000=[500, 300],
        direction="",
        reason="Probe the visible search field",
    )

    assert loop._region_probe_action_issue(runtime, "Search", decision) == ""


def test_page_update_can_register_then_scroll_and_completed_survey_switches_task(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Home", summary="Fixture", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"],
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-home", screenshot=screen["screenshot"],
        page_name=page_name, is_new=True,
    )
    frame_id = loop.screenshot_frame_id(screen["screenshot"])
    update = loop.PageUpdate(
        page_name="Home",
        regions=[{
            "name": "Results", "summary": "Scrollable results",
            "survey_memory": (
                "Started from Open result; continue along the visible list."),
            "coverage_complete": False,
            "bbox_1000": [100, 100, 900, 900],
        }],
        new_entries=[{
            "region_name": "Results", "target": "Open result",
            "bbox_1000": [200, 200, 500, 300],
        }],
    )
    assert loop._apply_main_agent_page_update(
        runtime, update, scene, screen["screenshot"], []) == ""

    converted, error = loop._convert_action_tool(
        runtime,
        screen["screenshot"],
        loop.AutonomousDecision(
            action="CALL_TOOL", target="Results", point_1000=None,
            direction="", reason="Continue the Region.",
            tool_name="scroll", tool_arguments={
                "container_hint": "outer results viewport",
                "point_1000": [950, 950],
                "direction": "down",
                "amount": 600,
            },
        ),
        None,
    )
    assert error == ""
    assert converted is not None
    assert converted.point_1000 == [950.0, 950.0]

    state = loop._region_state(runtime, "Home")
    state.apply_agent_update([{
        "name": "Results", "summary": "Scrollable results",
        "survey_memory": (
            "Reached the final visible result with no unresolved gap."),
        "bbox_1000": [100, 100, 900, 900],
        "coverage_complete": True,
    }], frame_id=frame_id)
    runtime.entry_review_audits.setdefault("home", {})["results"] = {
        "page_name": "Home", "region_name": "Results", "status": "complete",
    }
    loop._sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_type == "explore_entry"


def test_input_entry_click_cannot_settle_the_input_operation(tmp_path) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    _page_name, issue = runtime.protocol_map.observe(
        name="Alarm",
        summary="Alarm editor",
        identity="new",
        matched_page_name="",
        surface_kind="page",
        regions=(),
        screenshot=screen["screenshot"],
    )
    assert issue == ""
    assert runtime.entry_ledger.record_agent_update(
        page_name="Alarm",
        region_name="Alarm settings",
        frame_id=loop.screenshot_frame_id(screen["screenshot"]),
        observations=[{
            "target": "Name field",
            "operation": "输入名称",
            "subject": "闹钟名称",
            "control_type": "input",
        }],
    ).added == ["ae1"]
    runtime.exploration_task = ExplorationTask(
        task_type="explore_entry",
        task_id="entry:ae1",
        entry_id="ae1",
        page_name="Alarm",
        region_name="Alarm settings",
        target="Name field",
        phase="locate_entry",
    )
    entry_attempt = loop.AutonomousDecision(
        action="CALL_TOOL",
        target="Name field",
        point_1000=[500, 500],
        direction="",
        reason="Try the assigned input operation.",
        purpose="entry_attempt",
        tool_name="click",
        tool_arguments={
            "target": "Name field",
            "entry_id": "ae1",
            "point_1000": [500, 500],
        },
    )

    converted, error = loop._convert_action_tool(
        runtime, screen["screenshot"], entry_attempt, None)

    assert converted is None
    assert error.startswith("input_entry_requires_input_text:")
    locating, error = loop._convert_action_tool(
        runtime,
        screen["screenshot"],
        replace(entry_attempt, purpose="locating"),
        None,
    )
    assert error == ""
    assert locating is not None
    assert locating.action == "CLICK"
    assert locating.purpose == "locating"

    task_view = loop._exploration_map_view(runtime, None)["task"]
    assert task_view["control_type"] == "input"


def test_global_scheduler_reselects_nearest_task_after_page_landing(
    tmp_path,
) -> None:
    remote_shot = _png("blue")
    local_shot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": local_shot}, [])

    remote_name, issue = runtime.protocol_map.observe(
        name="Remote", summary="Remote page", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=remote_shot, commit_regions=False,
    )
    assert issue == ""
    remote_scene = loop._register_scene(
        runtime, remote_shot,
        _turn("Remote", action="NONE", identity="known"), remote_name)
    _complete_fixture_survey(runtime, "Remote", remote_shot)
    remote_entry = runtime.entry_ledger.record_agent_update(
        page_name="Remote", region_name="Main",
        frame_id=loop.screenshot_frame_id(remote_shot),
        observations=[{"target": "Remote function"}],
    ).added[0]

    local_name, issue = runtime.protocol_map.observe(
        name="Local", summary="Local page", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=local_shot, commit_regions=False,
    )
    assert issue == ""
    local_scene = loop._register_scene(
        runtime, local_shot,
        _turn("Local", action="NONE", identity="known"), local_name)
    _complete_fixture_survey(runtime, "Local", local_shot)
    local_entry = runtime.entry_ledger.record_agent_update(
        page_name="Local", region_name="Main",
        frame_id=loop.screenshot_frame_id(local_shot),
        observations=[{"target": "Local function"}],
    ).added[0]
    runtime.graph.add_transition(
        local_scene.state_id,
        remote_scene.state_id,
        {
            "action_type": "CLICK",
            "selector": {"element_label": "Go remote"},
            "parameters": {"button": "left"},
        },
        element_label="Go remote",
        effect_verdict="observed_change",
        landing_verified=True,
        target_page_name="Remote",
    )
    runtime.task_creation_order = {
        f"explore:{remote_entry}": 1,
        f"explore:{local_entry}": 2,
    }
    runtime.next_task_creation_order = 3
    runtime.exploration_task = ExplorationTask(
        task_type="explore_entry",
        task_id=f"explore:{remote_entry}",
        entry_id=remote_entry,
        page_name="Remote",
        region_name="Main",
        target="Remote function",
        phase="route_to_source",
    )

    loop._sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == remote_entry
    assert runtime.exploration_task.phase == "route_to_source"


def test_global_scheduler_uses_entry_creation_order_after_region_probe_retirement(
    tmp_path,
) -> None:
    screenshot = _png("silver")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [], enable_region_probes=True)
    page_name, issue = runtime.protocol_map.observe(
        name="Clock", summary="Clock page", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    loop._register_scene(
        runtime, screenshot,
        _turn("Clock", action="NONE", identity="known"), page_name)
    _complete_fixture_survey(runtime, "Clock", screenshot)
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Clock", region_name="Main",
        frame_id=loop.screenshot_frame_id(screenshot),
        observations=[{"target": "Open settings"}],
    ).added[0]
    runtime.task_creation_order = {
        f"explore:{entry_id}": 1,
    }
    runtime.next_task_creation_order = 3

    loop._sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_type == "explore_entry"
    assert runtime.exploration_task.task_id == f"explore:{entry_id}"


def test_one_page_update_can_complete_multiple_small_regions(tmp_path) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Home", summary="Fixture", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    history = []

    issue = loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            regions=[
                {
                    "name": "Navigation", "bbox_1000": [0, 0, 1000, 200],
                    "coverage_complete": True,
                },
                {"name": "Status", "bbox_1000": [0, 200, 1000, 600],
                 "coverage_complete": True},
                {"name": "Quick actions", "bbox_1000": [0, 600, 1000, 1000],
                 "coverage_complete": True},
            ],
        ),
        loop.ObservedScene(
            state_id="state-home", screenshot=screenshot,
            page_name=page_name, is_new=True,
        ),
        screenshot,
        history,
    )
    loop._sync_exploration_task(runtime)

    assert issue == ""
    assert history[-1]["accepted_regions"] == [
        "Navigation", "Status", "Quick actions",
    ]
    assert runtime.exploration_task is None


def test_region_reviewer_rejects_bad_partition_and_bad_reason(
    tmp_path,
) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clocks", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    captured = {}

    def reviewer(request):
        captured.update(request)
        return {
            "regions": [
                {
                    "name": "World Clock List Area",
                    "summary": "The visible world-clock content.",
                },
                {
                    "name": "Top Navigation Bar",
                    "summary": "The visible global navigation tabs.",
                },
            ],
            "revisions": [{
                "old_region": "World Clock List Area",
                "decision": "keep",
                "reason": "The content Region remains valid.",
            }],
            "reason": "The proposal omits the visible navigation group.",
        }

    runtime.region_reviewer = reviewer
    update = loop.PageUpdate(
        page_name="World",
        regions=[{
            "name": "World Clock List Area",
            "coverage_complete": True,
        }],
        new_entries=[],
    )
    history = []

    reviewed, review_issue = loop._review_region_proposal(
        runtime,
        update,
        loop.ObservedScene(
            state_id="state-world", screenshot=screenshot,
            page_name=page_name, is_new=True,
        ),
        screenshot,
        history,
        main_agent_reason=(
            "Top navigation is global switching and will not be recorded."
        ),
    )

    assert reviewed is None
    assert "当前 regions 新增：Top Navigation Bar" in review_issue
    assert "proposal omits the visible navigation group" in review_issue
    assert captured["main_agent_reason"].startswith("Top navigation")
    assert loop._region_state(runtime, "World").snapshot()["regions"] == []
    assert history[-1]["status"] == "rejected"
    assert history[-1]["rejection"]["code"] == "region_review_rejected"


def test_unknown_region_ref_does_not_create_impossible_reviewer_check(
    tmp_path,
) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Stopwatch", summary="Stopwatch", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    requests = []

    def reviewer(request):
        requests.append(request)
        return _keep_region_review(
            request, "The visible component partition is coherent.")

    runtime.region_reviewer = reviewer
    scene = loop.ObservedScene(
        state_id="state-stopwatch", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    proposal = loop.PageUpdate(
        page_name=page_name,
        regions=[{
            "name": "Stopwatch controls",
            "bbox_1000": [0, 0, 1000, 1000],
            "equivalent_to_region_ref": "invented-region-ref",
            "coverage_complete": True,
        }],
    )
    history = []

    reviewed, review_issue = loop._review_region_proposal(
        runtime, proposal, scene, screenshot, history,
        main_agent_reason="The stopwatch controls form one component.",
    )

    assert review_issue == ""
    assert reviewed == proposal
    assert "equivalence_candidates" not in requests[0]
    apply_issue = loop._apply_main_agent_page_update(
        runtime, reviewed, scene, screenshot, history,
        region_reviewed=True,
    )
    assert apply_issue == ""
    correction = runtime.page_update_corrections[
        "stopwatch"]["region:stopwatch controls"]
    assert correction["error_code"] == "invalid_region_ref"
    assert history[-1]["status"] == "rejected"


def test_approved_region_resubmission_clears_old_partition_correction(
    tmp_path,
) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clocks", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    review_count = 0

    def reviewer(request):
        nonlocal review_count
        review_count += 1
        if review_count == 2:
            return _keep_region_review(
                request, "The revision groups controls by functional component.")
        return {
            "regions": [
                {"name": "Application Toolbar", "summary": "App actions."},
                {"name": "Top Navigation Bar", "summary": "Navigation."},
                {
                    "name": "World Clock Content Area",
                    "summary": "World-clock content.",
                },
            ],
            "revisions": [
                {
                    "old_region": "Title Bar Controls",
                    "decision": "merge",
                    "merged_into": "Application Toolbar",
                    "reason": "The application controls belong together.",
                },
                {
                    "old_region": "Window Control Buttons",
                    "decision": "remove",
                    "reason": "Window management is outside the app Regions.",
                },
                {
                    "old_region": "Application Menu Button",
                    "decision": "merge",
                    "merged_into": "Application Toolbar",
                    "reason": "The menu button belongs to the toolbar.",
                },
                {
                    "old_region": "Top Navigation Bar",
                    "decision": "keep",
                    "reason": "Navigation remains stable.",
                },
                {
                    "old_region": "World Clock Management Area",
                    "decision": "merge",
                    "merged_into": "World Clock Content Area",
                    "reason": "The content has one stable owner.",
                },
            ],
            "reason": "The proposal is fragmented and includes window chrome.",
        }

    runtime.region_reviewer = reviewer
    first = loop.PageUpdate(
        page_name="World",
        regions=[
            {"name": "Title Bar Controls", "coverage_complete": True},
            {"name": "Window Control Buttons", "coverage_complete": True},
            {"name": "Application Menu Button", "coverage_complete": True},
            {"name": "Top Navigation Bar", "coverage_complete": True},
            {"name": "World Clock Management Area", "coverage_complete": True},
        ],
    )
    corrected = loop.PageUpdate(
        page_name="World",
        regions=[
            {"name": "Application Toolbar", "coverage_complete": True},
            {"name": "Top Navigation Bar", "coverage_complete": True},
            {"name": "World Clock Content Area", "coverage_complete": True},
        ],
    )
    history = []

    reviewed, review_issue = loop._review_region_proposal(
        runtime, first, scene, screenshot, history,
        main_agent_reason="Each visible control group is a separate Region.",
    )

    assert reviewed is None
    assert review_issue
    assert runtime.page_update_corrections["world"]["page_update"][
        "error_code"
    ] == "region_review_rejected"

    reviewed, review_issue = loop._review_region_proposal(
        runtime, corrected, scene, screenshot, history,
        main_agent_reason=(
            "I regrouped Add and menu under the application toolbar, excluded "
            "window management, and kept navigation and content separate."
        ),
    )

    assert review_issue == ""
    assert reviewed == corrected
    assert "world" not in runtime.page_update_corrections


def test_region_review_discussion_passes_prior_verdict_and_accepts_revision(
    tmp_path,
) -> None:
    screenshot = _png("white")
    changed_screenshot = _png("yellow")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clocks", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    requests = []
    def reviewer(request):
        requests.append(request)
        if len(requests) > 1:
            return _keep_region_review(
                request, "The revised partition now covers the toolbar.")
        return {
            "regions": [
                {"name": "Toolbar", "summary": "Visible page tools."},
                {"name": "Main", "summary": "Main page content."},
            ],
            "revisions": [{
                "old_region": "Main",
                "decision": "keep",
                "reason": "The main content remains valid.",
            }],
            "reason": "The toolbar is missing.",
        }

    runtime.region_reviewer = reviewer
    history = []
    first = loop.PageUpdate(
        page_name="World",
        regions=[{"name": "Main", "coverage_complete": True}],
    )
    corrected = loop.PageUpdate(
        page_name="World",
        regions=[
            {"name": "Toolbar", "coverage_complete": True},
            {"name": "Main", "coverage_complete": True},
        ],
    )

    reviewed, review_issue = loop._review_region_proposal(
        runtime,
        first,
        scene,
        screenshot,
        history,
        main_agent_reason="Only main content was proposed.",
    )
    assert reviewed is None and review_issue

    reviewed, review_issue = loop._review_region_proposal(
        runtime,
        corrected,
        loop.ObservedScene(
            state_id="state-world", screenshot=changed_screenshot,
            page_name=page_name, is_new=False,
        ),
        changed_screenshot,
        history,
        main_agent_reason=(
            "I accepted the missing-toolbar point and added the complete toolbar."
        ),
    )

    assert review_issue == "" and reviewed == corrected
    assert len(requests) == 2
    assert requests[0]["review_attempt"] == 1
    assert requests[0]["previous_review"] == {}
    assert requests[1]["review_attempt"] == 2
    assert requests[1]["previous_review"]["reason"] == (
        "The toolbar is missing.")
    assert history[-1]["status"] == "accepted"
    assert history[-1]["review_attempt"] == 2
    assert "world" not in runtime.page_update_corrections


def test_region_revision_rejects_missing_old_region_and_accepts_repair(
    tmp_path,
) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clocks", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    requests = []
    def reviewer(request):
        requests.append(request)
        if len(requests) > 1:
            return _keep_region_review(
                request, "The complete revision now settles every Region.")
        return {
            "regions": [
                {"name": "Formatting tools", "summary": "Text tools."},
                {"name": "Document canvas", "summary": "Document content."},
            ],
            "revisions": [{
                "old_region": "Formatting tools",
                "decision": "keep",
                "reason": "The formatting group remains stable.",
            }],
            "reason": "The document canvas remains a current Region.",
        }

    runtime.region_reviewer = reviewer
    first = loop.PageUpdate(
        page_name=page_name,
        regions=[
            {"name": "Formatting tools", "coverage_complete": True},
            {"name": "Document canvas", "coverage_complete": True},
        ],
    )
    history = []

    reviewed, review_issue = loop._review_region_proposal(
        runtime, first, scene, screenshot, history,
        main_agent_reason="Formatting tools and the canvas are visible.",
    )
    assert reviewed is None
    assert "revisions 遗漏已有 Region：Document canvas" in review_issue
    assert len(requests) == 1
    assert history[-1]["status"] == "rejected"
    assert runtime.page_update_corrections["world"]["page_update"][
        "review_attempt"] == 1

    reviewed, review_issue = loop._review_region_proposal(
        runtime, first, scene, screenshot, history,
        main_agent_reason="I preserved both Regions in the complete proposal.",
    )

    assert review_issue == "" and reviewed == first
    assert len(requests) == 2
    assert requests[1]["review_attempt"] == 2
    assert requests[1]["previous_review"]["revisions"][0][
        "old_region"] == "Formatting tools"


def test_region_revision_reports_duplicate_unknown_and_missing_merge_target(
    tmp_path,
) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Alarms", summary="Alarm list", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-alarms", screenshot=screenshot,
        page_name=page_name, is_new=False,
    )
    runtime.region_reviewer = lambda _request: {
        "regions": [
            {"name": "Toolbar", "summary": "Page tools."},
            {"name": "Content", "summary": "Page content."},
        ],
        "revisions": [
            {
                "old_region": "Toolbar",
                "decision": "keep",
                "reason": "Toolbar remains.",
            },
            {
                "old_region": "Toolbar",
                "decision": "keep",
                "reason": "Duplicate settlement.",
            },
            {
                "old_region": "Invented",
                "decision": "remove",
                "reason": "This name was not supplied.",
            },
            {
                "old_region": "Content",
                "decision": "merge",
                "merged_into": "Missing target",
                "reason": "Invalid target reference.",
            },
            {
                "old_region": "Canvas",
                "decision": "remove",
                "merged_into": "Content",
                "reason": "Remove must not carry a target.",
            },
            {
                "old_region": "Header",
                "decision": "keep",
                "reason": "Keep requires the same current name.",
            },
        ],
        "reason": "The response contains invalid exact references.",
    }
    update = loop.PageUpdate(
        page_name=page_name,
        regions=[
            {"name": "Toolbar", "coverage_complete": True},
            {"name": "Content", "coverage_complete": True},
            {"name": "Canvas", "coverage_complete": True},
            {"name": "Header", "coverage_complete": True},
        ],
    )
    history = []

    reviewed, review_issue = loop._review_region_proposal(
        runtime, update, scene, screenshot, history,
        main_agent_reason="Toolbar and content are the visible Regions.",
    )
    assert reviewed is None
    assert "revisions 重复 old_region：Toolbar" in review_issue
    assert "revisions 含未知 old_region：Invented" in review_issue
    assert "合并目标不存在：Content→Missing target" in review_issue
    assert "remove 不得携带 merged_into：Canvas" in review_issue
    assert "keep 名称不存在于 regions：Header" in review_issue


def test_resurvey_reuses_accepted_region_review_within_evidence_generation(
    tmp_path,
) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clocks", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    _register_reviewed_main_region(
        runtime, page_name, scene, screenshot)
    runtime.pending_page_resurveys[loop._page_key(page_name)] = {
        "page_name": page_name,
        "entry_id": "ae-menu",
        "target": "Application menu",
        "reason": "The menu revealed a same-Page surface.",
    }
    requests = []

    def reviewer(request):
        requests.append(request)
        return _keep_region_review(
            request, "The current functional partition is complete.")

    runtime.region_reviewer = reviewer
    existing_update = loop.PageUpdate(
        page_name=page_name,
        regions=[{
            "name": "Main",
            "bbox_1000": [0, 0, 1000, 1000],
            "coverage_complete": True,
        }],
    )
    history = []

    reviewed, review_issue = loop._review_region_proposal(
        runtime, existing_update, scene, screenshot, history,
        main_agent_reason="The same visible partition remains complete.",
    )
    assert review_issue == "" and reviewed == existing_update
    assert len(requests) == 1

    changed_geometry_update = loop.PageUpdate(
        page_name=page_name,
        regions=[{
            "name": "Main",
            "bbox_1000": [0, 0, 500, 500],
            "coverage_complete": True,
        }],
    )
    reviewed, review_issue = loop._review_region_proposal(
        runtime, changed_geometry_update, scene, screenshot, history,
        main_agent_reason="Only Entry coverage changed after the approval.",
    )
    assert review_issue == "" and reviewed is not None
    assert "bbox_1000" not in reviewed.regions[0]
    assert len(requests) == 1

    runtime.entry_review_evidence_generation += 1
    reviewed, review_issue = loop._review_region_proposal(
        runtime, existing_update, scene, screenshot, history,
        main_agent_reason="A real changed action supplied new visual evidence.",
    )
    assert review_issue == "" and reviewed == existing_update
    assert len(requests) == 2

    new_region_update = loop.PageUpdate(
        page_name=page_name,
        regions=[
            *existing_update.regions,
            {
                "name": "Application menu panel",
                "bbox_1000": [700, 100, 950, 400],
                "coverage_complete": False,
            },
        ],
    )
    reviewed, review_issue = loop._review_region_proposal(
        runtime, new_region_update, scene, screenshot, history,
        main_agent_reason="A newly visible Region extends the partition.",
    )
    assert review_issue == "" and reviewed == new_region_update
    assert len(requests) == 3


def test_third_region_review_rejection_is_final(tmp_path) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clocks", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    requests = []

    def reviewer(request):
        requests.append(request)
        return {
            "regions": [
                {"name": "Main", "summary": "Main page content."},
                {"name": "Toolbar", "summary": "Visible page tools."},
            ],
            "revisions": [{
                "old_region": "Main",
                "decision": "keep",
                "reason": "The main content remains valid.",
            }],
            "reason": f"Round {len(requests)} remains incomplete.",
        }

    runtime.region_reviewer = reviewer
    proposal = loop.PageUpdate(
        page_name="World",
        regions=[{"name": "Main", "coverage_complete": True}],
    )
    history = []

    for expected_attempt in (1, 2, 3):
        reviewed, review_issue = loop._review_region_proposal(
            runtime, proposal, scene, screenshot, history,
            main_agent_reason=f"Main Agent response for round {expected_attempt}.",
        )
        assert reviewed is None and review_issue
        assert requests[-1]["review_attempt"] == expected_attempt
        if expected_attempt > 1:
            assert requests[-1]["previous_review"]["reason"] == (
                f"Round {expected_attempt - 1} remains incomplete."
            )

    pending = runtime.page_update_corrections["world"]["page_update"]
    assert pending["error_code"] == "region_review_exhausted"
    assert pending["review_attempt"] == 3
    assert pending["review_exhausted"] is True
    assert history[-1]["status"] == "final_rejected"

    reviewed, review_issue = loop._review_region_proposal(
        runtime, proposal, scene, screenshot, history,
        main_agent_reason="A fourth attempt must not call Reviewer.",
    )
    assert reviewed is None and review_issue
    assert len(requests) == 3
    assert loop._region_state(runtime, "World").snapshot()["regions"] == []

    reopened_requests = []

    def approve_after_new_visual_evidence(request):
        reopened_requests.append(request)
        return _keep_region_review(
            request, "The unobstructed screenshot supports this partition.")

    runtime.region_reviewer = approve_after_new_visual_evidence
    changed_screenshot = _png("black")
    reviewed, review_issue = loop._review_region_proposal(
        runtime,
        proposal,
        loop.ObservedScene(
            state_id="state-world", screenshot=changed_screenshot,
            page_name=page_name, is_new=False,
        ),
        changed_screenshot,
        history,
        main_agent_reason=(
            "The obstruction was dismissed and the visible evidence changed."
        ),
    )

    assert reviewed is None and review_issue
    assert reopened_requests == []

    runtime.entry_review_evidence_generation += 1
    reviewed, review_issue = loop._review_region_proposal(
        runtime,
        proposal,
        loop.ObservedScene(
            state_id="state-world", screenshot=changed_screenshot,
            page_name=page_name, is_new=False,
        ),
        changed_screenshot,
        history,
        main_agent_reason=(
            "A verified changed GUI action supplied new visual evidence."
        ),
    )

    assert review_issue == "" and reviewed == proposal
    assert len(reopened_requests) == 1
    assert reopened_requests[0]["review_attempt"] == 1
    assert reopened_requests[0]["previous_review"] == {}
    assert history[-2]["kind"] == "region_review_discussion_reopened"
    assert history[-1]["status"] == "accepted"
    assert "world" not in runtime.page_update_corrections


def test_region_review_reuses_first_evidence_across_passive_frame_drift(
    tmp_path,
) -> None:
    first_screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": first_screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clocks", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=first_screenshot,
    )
    assert issue == ""
    proposal = loop.PageUpdate(
        page_name="World",
        regions=[{"name": "Main", "coverage_complete": True}],
    )
    requests = []

    def reviewer(request):
        requests.append(request)
        if len(requests) == 1:
            return {
                "regions": [
                    {"name": "Main", "summary": "Main page content."},
                    {
                        "name": "Navigation",
                        "summary": "Visible navigation controls.",
                    },
                ],
                "revisions": [{
                    "old_region": "Main",
                    "decision": "keep",
                    "reason": "The main content remains valid.",
                }],
                "reason": "Revise the partition using the visible tabs.",
            }
        return _keep_region_review(
            request, "The revised partition accounts for the visible tabs.")

    runtime.region_reviewer = reviewer
    history = []
    first_scene = loop.ObservedScene(
        state_id="state-world", screenshot=first_screenshot,
        page_name=page_name, is_new=True,
    )
    reviewed, review_issue = loop._review_region_proposal(
        runtime, proposal, first_scene, first_screenshot, history,
        main_agent_reason="The visible surface has one content Region.",
    )
    assert reviewed is None and review_issue

    drifted_screenshot = _png("black")
    drifted_scene = loop.ObservedScene(
        state_id="state-world", screenshot=drifted_screenshot,
        page_name=page_name, is_new=False,
    )
    reviewed, review_issue = loop._review_region_proposal(
        runtime, proposal, drifted_scene, drifted_screenshot, history,
        main_agent_reason="The fixed evidence supports the revised partition.",
    )

    assert review_issue == "" and reviewed == proposal
    assert len(requests) == 2
    assert requests[0]["current_screenshot"] == first_screenshot
    assert requests[1]["current_screenshot"] == first_screenshot
    assert requests[1]["fixed_evidence"] is True
    assert "world" not in runtime.region_review_screenshots


def test_approved_renamed_region_clears_old_item_correction(tmp_path) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clocks", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="World",
            regions=[{
                "name": "Top Navigation Bar",
                "equivalent_to_region_ref": 17,
                "coverage_complete": True,
            }],
        ),
        scene,
        screenshot,
        history,
    ) == ""
    assert "region:top navigation bar" in (
        runtime.page_update_corrections["world"])
    runtime.region_reviewer = lambda request: _keep_region_review(
        request, "The renamed partition covers all visible Regions.")
    corrected = loop.PageUpdate(
        page_name="World",
        regions=[{
            "bbox_1000": [0, 0, 1000, 1000],
            "name": "Top Navigation Tabs",
            "equivalent_to_region_ref": "",
            "coverage_complete": True,
        }],
    )

    reviewed, review_issue = loop._review_region_proposal(
        runtime, corrected, scene, screenshot, history,
        main_agent_reason="The visible navigation tabs form this Region.",
    )

    assert review_issue == "" and reviewed is not None
    assert loop._apply_main_agent_page_update(
        runtime, reviewed, scene, screenshot, history,
        region_reviewed=True,
    ) == ""
    assert "world" not in runtime.page_update_corrections
    assert loop._region_state(runtime, "World").region(
        "Top Navigation Tabs") is not None


def test_rejected_renamed_region_keeps_old_item_correction(tmp_path) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clocks", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="World",
            regions=[{
                "name": "Top Navigation Bar",
                "equivalent_to_region_ref": 17,
                "coverage_complete": True,
            }],
        ),
        scene,
        screenshot,
        history,
    ) == ""
    runtime.region_reviewer = lambda _request: {
        "regions": [
            {"name": "Top Navigation Tabs", "summary": "Navigation."},
            {"name": "Main content", "summary": "Visible main content."},
        ],
        "revisions": [{
            "old_region": "Top Navigation Tabs",
            "decision": "keep",
            "reason": "Navigation remains a stable Region.",
        }],
        "reason": "The renamed proposal is still incomplete.",
    }
    corrected = loop.PageUpdate(
        page_name="World",
        regions=[{
            "name": "Top Navigation Tabs",
            "equivalent_to_region_ref": "",
            "coverage_complete": True,
        }],
    )

    reviewed, review_issue = loop._review_region_proposal(
        runtime, corrected, scene, screenshot, history,
        main_agent_reason="The navigation is fully covered.",
    )

    assert reviewed is None and review_issue
    assert "region:top navigation bar" in (
        runtime.page_update_corrections["world"])


def test_approved_partition_replaces_old_region_error_with_current_error(
    tmp_path,
) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clocks", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="World",
            regions=[{
                "name": "Top Navigation Bar",
                "equivalent_to_region_ref": 17,
                "coverage_complete": True,
            }],
        ),
        scene,
        screenshot,
        history,
    ) == ""
    runtime.region_reviewer = lambda request: _keep_region_review(
        request, "The proposed partition covers all visible Regions.")
    corrected = loop.PageUpdate(
        page_name="World",
        regions=[
            {"name": "Main content", "coverage_complete": True},
            {
                "name": "Top Navigation Tabs",
                "equivalent_to_region_ref": 17,
                "coverage_complete": True,
            },
        ],
    )

    reviewed, review_issue = loop._review_region_proposal(
        runtime, corrected, scene, screenshot, history,
        main_agent_reason="The visible Regions are fully covered.",
    )

    assert review_issue == "" and reviewed is not None
    assert loop._apply_main_agent_page_update(
        runtime, reviewed, scene, screenshot, history,
        region_reviewed=True,
    ) == ""
    corrections = runtime.page_update_corrections["world"]
    assert "region:top navigation bar" not in corrections
    assert corrections["region:top navigation tabs"]["field"] == (
        "equivalent_to_region_ref")


def test_region_reviewer_invalid_shape_fails_closed(tmp_path) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Home", summary="Home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    runtime.region_reviewer = lambda _request: {
        "decision": "accept",
        "issues": "not-an-array",
        "reason": "Looks complete.",
    }

    reviewed, review_issue = loop._review_region_proposal(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            regions=[{"name": "Main", "coverage_complete": True}],
        ),
        loop.ObservedScene(
            state_id="state-home", screenshot=screenshot,
            page_name=page_name, is_new=True,
        ),
        screenshot,
        [],
        main_agent_reason="The main content is visible.",
    )

    assert reviewed is None
    assert "必须且只能返回 regions、revisions 和 reason" in review_issue
    assert loop._region_state(runtime, "Home").snapshot()["regions"] == []


def test_existing_region_update_does_not_call_region_reviewer(tmp_path) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Home", summary="Fixture", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-home", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    initial = loop.PageUpdate(
        page_name="Home",
        regions=[{"name": "Main", "bbox_1000": [0, 0, 1000, 1000],
                  "coverage_complete": False}],
    )
    assert loop._apply_main_agent_page_update(
        runtime, initial, scene, screenshot, []) == ""
    calls = []
    runtime.region_reviewer = lambda request: calls.append(request)
    ordinary = loop.PageUpdate(
        page_name="Home",
        regions=[{
            "name": "Main",
            "survey_memory": "Observed the remaining content.",
            "coverage_complete": True,
        }],
    )

    reviewed, review_issue = loop._review_region_proposal(
        runtime, ordinary, scene, screenshot, [],
        main_agent_reason="The same Region is now fully observed.",
    )

    assert review_issue == ""
    assert reviewed == ordinary
    assert calls == []


def test_batch_region_mapping_applies_only_exact_one_to_one_matches(
    tmp_path,
) -> None:
    before = _png("white")
    after = _png("black")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": after}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="After", summary="After action", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=after, commit_regions=False,
    )
    assert (page_name, issue) == ("After", "")
    shared_ref, _ = runtime.region_registry.bind(
        page_name="Before", region_name="Persistent panel",
        summary="The content container before the action.",
    )
    runtime.pending_region_mapping_context = {
        "before_screenshot": before,
        "after_screenshot": after,
        "before_page": "Before",
        "after_page": "After",
        "before_regions": [{
            "name": "Persistent panel",
            "summary": "The content container before the action.",
            "region_ref": shared_ref,
        }],
        "action": {"operation": "click", "target": "Open details"},
    }
    runtime.region_mapper = lambda _request: {
        "matches": [{
            "before": ["A1"],
            "after": ["B1"],
            "reason": "The same content container remains visible.",
        }],
        "new": ["B2"],
        "uncertain": [],
    }
    history = []
    update = loop.PageUpdate(
        page_name="After",
        regions=[
            {
                "name": "Persistent panel",
                "summary": "The content container after the action.",
                "coverage_complete": True,
            },
            {
                "name": "Details dialog",
                "summary": "A newly opened foreground dialog.",
                "coverage_complete": True,
            },
        ],
    )

    assert loop._apply_main_agent_page_update(
        runtime,
        update,
        loop.ObservedScene(
            state_id="state-after", screenshot=after,
            page_name="After", is_new=True,
        ),
        after,
        history,
        region_reviewed=True,
    ) == ""

    assert runtime.region_registry.region_ref(
        "After", "Persistent panel") == shared_ref
    assert runtime.region_registry.region_ref(
        "After", "Details dialog") != shared_ref
    mapping_record = next(
        item for item in history
        if item.get("kind") == "region_mapping_result")
    assert mapping_record["applied_one_to_one"] == [{
        "before": "A1", "after": "B1", "region_ref": shared_ref,
    }]


def test_cross_page_region_review_merges_function_identity_without_entry_credit(
    tmp_path,
) -> None:
    home_first = _png("white")
    home = _png("blue")
    search = _png("black")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": search}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Home", summary="Home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=home_first, commit_regions=False)
    assert (page_name, issue) == ("Home", "")
    page_name, issue = runtime.protocol_map.observe(
        name="Home", summary="Home", identity="known",
        matched_page_name="Home", surface_kind="page", regions=(),
        screenshot=home, variant_name="navigation-visible",
        variant_identity="new", commit_regions=False)
    assert (page_name, issue) == ("Home", "")
    home_scene = loop.ObservedScene(
        state_id="state-home", screenshot=home,
        page_name="Home", is_new=True)
    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(page_name="Home", regions=[{
            "name": "Primary navigation",
            "summary": "Switches between the application's main functions.",
            "coverage_complete": False,
        }]),
        home_scene,
        home,
        [],
        region_reviewed=True,
    ) == ""
    shared_ref = runtime.region_registry.region_ref(
        "Home", "Primary navigation")
    source_occurrence = runtime.region_registry.occurrence_ref(
        "Home", "Primary navigation")
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Home",
        region_name="Primary navigation",
        frame_id=loop.screenshot_frame_id(home),
        source_state_id="state-home",
        owner_region_ref=shared_ref,
        representative_occurrence_ref=source_occurrence,
        observations=[{"target": "Search destination"}],
    ).added[0]
    source_entry_status = runtime.entry_ledger.get(entry_id).status

    page_name, issue = runtime.protocol_map.observe(
        name="Search", summary="Search", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=search, commit_regions=False)
    assert (page_name, issue) == ("Search", "")
    reviewer_requests = []

    def reviewer(request):
        reviewer_requests.append(request)
        assert request["candidate_screenshots"] == [home]
        ids = [item["occurrence_id"] for item in request["occurrences"]]
        assert ids == ["N1", "K1"]
        assert all(set(item) == {
            "occurrence_id", "page", "region", "summary", "image",
        } for item in request["occurrences"])
        return {
            "shared_groups": [{
                "members": ["N1", "K1"],
                "reason": (
                    "Both Regions own the same stable primary navigation "
                    "destinations and reuse meaning."),
            }],
            "separate_groups": [],
            "unmatched": [],
            "reason": "The primary navigation persists across both Pages.",
        }

    runtime.cross_page_region_reviewer = reviewer
    history = []
    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(page_name="Search", regions=[{
            "name": "Main navigation",
            "summary": "Switches between the application's main functions.",
            "coverage_complete": False,
        }]),
        loop.ObservedScene(
            state_id="state-search", screenshot=search,
            page_name="Search", is_new=True),
        search,
        history,
        region_reviewed=True,
    ) == ""

    assert len(reviewer_requests) == 1
    assert runtime.region_registry.region_ref(
        "Search", "Main navigation") == shared_ref
    assert runtime.region_registry.occurrence_ref(
        "Search", "Main navigation") != source_occurrence
    assert [entry.entry_id for entry in runtime.entry_ledger.entries] == [entry_id]
    assert runtime.entry_ledger.get(entry_id).status == source_entry_status
    result = next(item for item in history
                  if item.get("kind") == "cross_page_region_review_result")
    assert result["status"] == "accepted"
    assert result["applied"][0]["region_ref"] == shared_ref


def test_cross_page_region_review_keeps_similar_different_functions_separate(
    tmp_path,
) -> None:
    first = _png("white")
    second = _png("black")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": second}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="First", summary="First", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=first, commit_regions=False)
    assert (page_name, issue) == ("First", "")
    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(page_name="First", regions=[{
            "name": "Floating action",
            "summary": "Creates a new message.",
            "coverage_complete": False,
        }]),
        loop.ObservedScene(
            state_id="state-first", screenshot=first,
            page_name="First", is_new=True),
        first, [], region_reviewed=True,
    ) == ""
    first_ref = runtime.region_registry.region_ref(
        "First", "Floating action")
    page_name, issue = runtime.protocol_map.observe(
        name="Second", summary="Second", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=second, commit_regions=False)
    assert (page_name, issue) == ("Second", "")
    runtime.cross_page_region_reviewer = lambda _request: {
        "shared_groups": [],
        "separate_groups": [{
            "members": ["N1", "K1"],
            "reason": (
                "The controls look alike, but one creates a message and the "
                "other starts a call."),
        }],
        "unmatched": [],
        "reason": "Similar presentation does not override different functions.",
    }
    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(page_name="Second", regions=[{
            "name": "Floating action",
            "summary": "Starts a new call.",
            "coverage_complete": False,
        }]),
        loop.ObservedScene(
            state_id="state-second", screenshot=second,
            page_name="Second", is_new=True),
        second, [], region_reviewed=True,
    ) == ""
    second_ref = runtime.region_registry.region_ref(
        "Second", "Floating action")
    assert second_ref and second_ref != first_ref


def test_cross_page_region_review_requires_each_occurrence_exactly_once() -> None:
    result = {
        "shared_groups": [{
            "members": ["N1", "K1"], "reason": "Same function.",
        }],
        "separate_groups": [],
        "unmatched": [
            {"occurrence_id": "K1", "reason": "Duplicated by mistake."},
            {"occurrence_id": "X1", "reason": "Unknown reference."},
        ],
        "reason": "Malformed assignment.",
    }
    shared, errors = autonomous_page_commit._validate_cross_page_region_review(
        result, ["N1", "N2", "K1"])
    assert shared == {}
    assert any("遗漏 occurrence_id：N2" in item for item in errors)
    assert any("重复 occurrence_id：K1" in item for item in errors)
    assert any("引用未知 occurrence_id：X1" in item for item in errors)


def test_invalid_cross_page_review_does_not_replace_action_region_mapping(
    tmp_path,
) -> None:
    before = _png("white")
    after = _png("black")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": after}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Before", summary="Before", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=before, commit_regions=False)
    assert (page_name, issue) == ("Before", "")
    shared_ref, _ = runtime.region_registry.bind(
        page_name="Before", region_name="Persistent panel",
        variant_name="default",
        summary="The persistent application panel.")
    page_name, issue = runtime.protocol_map.observe(
        name="After", summary="After", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=after, commit_regions=False)
    assert (page_name, issue) == ("After", "")
    runtime.pending_region_mapping_context = {
        "before_screenshot": before,
        "after_screenshot": after,
        "before_page": "Before",
        "after_page": "After",
        "before_regions": [{
            "name": "Persistent panel", "region_ref": shared_ref,
        }],
        "action": {"operation": "click", "target": "Open details"},
    }
    mapping_calls = []
    runtime.region_mapper = lambda request: mapping_calls.append(request) or {
        "matches": [{
            "before": ["A1"], "after": ["B1"],
            "reason": "The same panel persists across the action.",
        }],
        "new": ["B2"],
        "uncertain": [],
    }
    cross_page_calls = []
    runtime.cross_page_region_reviewer = (
        lambda request: cross_page_calls.append(request) or {
            "shared_groups": [],
            "separate_groups": [],
            "unmatched": [],
            "reason": "Invalid because occurrences were omitted.",
        })
    history = []
    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(page_name="After", regions=[
            {
                "name": "Persistent panel",
                "summary": "The persistent application panel.",
                "coverage_complete": False,
            },
            {
                "name": "Details surface",
                "summary": "A distinct details function.",
                "coverage_complete": False,
            },
        ]),
        loop.ObservedScene(
            state_id="state-after", screenshot=after,
            page_name="After", is_new=True),
        after,
        history,
        region_reviewed=True,
    ) == ""
    assert len(mapping_calls) == 1
    assert len(cross_page_calls) == 1
    assert runtime.region_registry.region_ref(
        "After", "Persistent panel") == shared_ref
    assert runtime.region_registry.region_ref(
        "After", "Details surface") != shared_ref
    review_record = next(
        item for item in history
        if item.get("kind") == "cross_page_region_review_result")
    assert review_record["status"] == "invalid"


def test_batch_region_mapping_cannot_swap_two_regions_on_the_same_page(
    tmp_path,
) -> None:
    before = _png("white")
    after = _png("black")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": after}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=before, commit_regions=False,
    )
    assert (page_name, issue) == ("Timer", "")
    before_scene = loop.ObservedScene(
        state_id="state-before", screenshot=before,
        page_name="Timer", is_new=True,
    )
    initial = loop.PageUpdate(
        page_name="Timer",
        regions=[
            {"name": "Bottom Navigation", "coverage_complete": False},
            {"name": "Timer Action Area", "coverage_complete": False},
        ],
    )
    assert loop._apply_main_agent_page_update(
        runtime, initial, before_scene, before, [],
        region_reviewed=True,
    ) == ""
    navigation_ref = runtime.region_registry.region_ref(
        "Timer", "Bottom Navigation")
    action_ref = runtime.region_registry.region_ref(
        "Timer", "Timer Action Area")
    assert navigation_ref and action_ref and navigation_ref != action_ref

    runtime.pending_region_mapping_context = {
        "before_screenshot": before,
        "after_screenshot": after,
        "before_page": "Timer",
        "after_page": "Timer",
        "before_regions": [
            {"name": "Bottom Navigation", "region_ref": navigation_ref},
            {"name": "Timer Action Area", "region_ref": action_ref},
        ],
        "action": {"operation": "click", "target": "Open menu"},
    }
    runtime.region_mapper = lambda _request: {
        "matches": [
            {"before": ["A1"], "after": ["B1"],
             "reason": "Incorrectly matched by position."},
            {"before": ["A2"], "after": ["B2"],
             "reason": "Incorrectly matched by position."},
        ],
        "new": [],
        "uncertain": [],
    }
    history = []
    update = loop.PageUpdate(
        page_name="Timer",
        regions=[
            {"name": "Timer Action Area", "coverage_complete": False},
            {"name": "Bottom Navigation", "coverage_complete": False},
        ],
    )

    assert loop._apply_main_agent_page_update(
        runtime,
        update,
        loop.ObservedScene(
            state_id="state-after", screenshot=after,
            page_name="Timer", is_new=False,
        ),
        after,
        history,
        region_reviewed=True,
    ) == ""

    assert runtime.region_registry.region_ref(
        "Timer", "Bottom Navigation") == navigation_ref
    assert runtime.region_registry.region_ref(
        "Timer", "Timer Action Area") == action_ref
    groups = runtime.region_registry.snapshot()["groups"]
    assert all(not {
        item["region_name"] for item in group["occurrences"]
        if item["page_name"] == "Timer"
    }.issuperset({"Bottom Navigation", "Timer Action Area"})
               for group in groups)
    result = next(
        item for item in history if item.get("kind") == "page_update_result")
    assert result["status"] == "accepted"
    assert "Two co-present formal Regions cannot share" in result["feedback"]


def test_exact_batch_mapping_inherits_reviewed_region_coverage_version(
    tmp_path,
) -> None:
    before = _png("white")
    after = _png("black")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": after}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Alarm", summary="Alarm page", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=after, commit_regions=False)
    assert (page_name, issue) == ("Alarm", "")
    shared_ref, _ = runtime.region_registry.bind(
        page_name="Clock", region_name="Navigation",
        state_id="state-clock")
    assert runtime.region_registry.publish_coverage(
        region_ref=shared_ref,
        page_name="Clock",
        region_name="Navigation",
        state_id="state-clock",
        frame_id="frame-clock",
        entry_signature=["timer:timer"],
    ) == 1
    runtime.pending_region_mapping_context = {
        "before_screenshot": before,
        "after_screenshot": after,
        "before_page": "Clock",
        "after_page": "Alarm",
        "before_regions": [{
            "name": "Navigation", "region_ref": shared_ref,
        }],
        "action": {"operation": "click", "target": "Alarm"},
    }
    runtime.region_mapper = lambda _request: {
        "matches": [{
            "before": ["A1"], "after": ["B1"],
            "reason": "The same navigation component remains visible.",
        }],
        "new": [],
        "uncertain": [],
    }
    scene = loop.ObservedScene(
        state_id="state-alarm", screenshot=after,
        page_name="Alarm", is_new=True)
    history = []

    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Alarm",
            regions=[{
                "name": "Navigation",
                "summary": "Shared navigation destinations",
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Navigation",
                "target": "Timer",
                "control_type": "control",
            }],
        ),
        scene,
        after,
        history,
        region_reviewed=True,
        main_agent_reason="The mapped navigation remains fully visible.",
    ) == ""

    region = runtime.region_states["alarm"].region("Navigation")
    assert region is not None
    assert region["coverage_complete"] is True
    assert region["coverage_version"] == 1
    assert region["coverage_basis"] == "batch_region_mapping"
    assert runtime.pending_entry_review is None
    audit = runtime.entry_review_audits["alarm"]["navigation"]
    assert audit["status"] == "complete"
    assert audit["coverage_basis"] == "shared_region_mapping"
    assert any(
        item.get("kind") == "shared_region_coverage_inherited"
        for item in history)


def test_shared_region_entries_are_inherited_and_only_new_semantics_are_reviewed(
    tmp_path,
) -> None:
    before = _png("white")
    after = _png("black")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": after}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Alarm", summary="Alarm page", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=after, commit_regions=False)
    assert (page_name, issue) == ("Alarm", "")
    shared_ref, source_occurrence = runtime.region_registry.bind(
        page_name="Clock", region_name="Navigation",
        state_id="state-clock")
    representative_id = runtime.entry_ledger.record_agent_update(
        page_name="Clock",
        region_name="Navigation",
        frame_id="frame-clock",
        source_state_id="state-clock",
        owner_region_ref=shared_ref,
        representative_occurrence_ref=source_occurrence,
        observations=[{
            "target": "Timer tab",
            "operation": "open page",
            "subject": "Timer workspace",
        }],
    ).added[0]
    pending_representative_id = runtime.entry_ledger.record_agent_update(
        page_name="Clock",
        region_name="Navigation",
        frame_id="frame-clock",
        source_state_id="state-clock",
        owner_region_ref=shared_ref,
        representative_occurrence_ref=source_occurrence,
        observations=[{
            "target": "Alarm tab",
            "operation": "open page",
        }],
    ).added[0]
    attempt = runtime.entry_ledger.begin_explicit_action(
        representative_id, frame_id="frame-clock", page_name="Clock")
    runtime.entry_ledger.finish_action(
        attempt.action_id,
        action_executed=True,
        outcome_verified=True,
        result="Timer page opened",
        destination_page="Timer",
    )
    runtime.pending_region_mapping_context = {
        "before_screenshot": before,
        "after_screenshot": after,
        "before_page": "Clock",
        "after_page": "Alarm",
        "before_regions": [{
            "name": "Navigation", "region_ref": shared_ref,
        }],
        "action": {"operation": "click", "target": "Alarm"},
    }
    runtime.region_mapper = lambda _request: {
        "matches": [{
            "before": ["A1"], "after": ["B1"],
            "reason": "The same application navigation remains visible.",
        }],
        "new": [],
        "uncertain": [],
    }
    scene = loop.ObservedScene(
        state_id="state-alarm", screenshot=after,
        page_name="Alarm", is_new=True)
    history = []

    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Alarm",
            regions=[{
                "name": "Navigation",
                "summary": "Shared application navigation",
                "coverage_complete": True,
            }],
            new_entries=[
                {
                    "region_name": "Navigation",
                    "target": "Timer tab",
                    "operation": "open page",
                    "subject": "Timer destination",
                    "control_type": "input",
                },
                {
                    "region_name": "Navigation",
                    "target": "Alarm tab",
                    "operation": "open page",
                },
                {
                    "region_name": "Navigation",
                    "target": "World tab",
                    "operation": "open page",
                    "subject": "World clocks",
                },
                {
                    "region_name": "Navigation",
                    "target": "World tab",
                    "operation": "select navigation item",
                    "subject": "Navigation customization",
                },
            ],
        ),
        scene,
        after,
        history,
        region_reviewed=True,
        main_agent_reason="The shared navigation and World tab are visible.",
    ) == ""
    assert [
        (item["operation"], item["target"])
        for item in runtime.pending_entry_review["candidates"]
    ] == [
        ("open page", "World tab"),
        ("select navigation item", "World tab"),
    ]
    exposed = runtime.pending_entry_review["shared_region_entries"]
    assert len(exposed) == 1
    assert exposed[0]["region_name"] == "Navigation"
    assert exposed[0]["description"] == "Shared application navigation"
    exposed_entries = exposed[0]["entries"]
    assert all("evidence_page" not in item for item in exposed_entries)
    assert [item["entry_id"] for item in exposed_entries] == [
        representative_id, pending_representative_id,
    ]
    assert exposed_entries[0]["destination"] == "Timer"
    assert exposed_entries[0]["operation"] == "open page"
    assert "destination" not in exposed_entries[1]
    runtime.exploration_task = ExplorationTask(
        task_type="survey_page",
        task_id="survey:Alarm:Navigation",
        page_name="Alarm",
        region_name="Navigation",
        phase="survey_region",
    )
    pending_review = runtime.pending_entry_review
    runtime.pending_entry_review = None
    known_entries = loop._exploration_map_view(
        runtime, None, current_screenshot=after,
    )["survey_page_fact"]["known_entries"]
    runtime.pending_entry_review = pending_review
    assert [item["target"] for item in known_entries] == [
        "Timer tab", "Alarm tab",
    ]
    assert all("page" not in item for item in known_entries)
    assert all("entry_id" not in item for item in known_entries)
    runtime.entry_review_audits.setdefault("alarm", {})["navigation"] = {
        "status": "disagreement",
        "discussion_evidence_generation": runtime.entry_review_evidence_generation,
        "coverage_audit_regions": ["Navigation"],
        "dropped": [{
            "region_name": "Navigation",
            "operation": "open page",
            "target": "World tab",
        }],
    }
    disputed_entries = loop._exploration_map_view(
        runtime, None, current_screenshot=after,
    )["survey_page_fact"]["known_entries"]
    assert [item["entry_id"] for item in disputed_entries] == [
        representative_id, pending_representative_id,
    ]
    runtime.entry_review_audits["alarm"].pop("navigation")
    reviewer_calls = []
    runtime.entry_reviewer = lambda request: reviewer_calls.append(request) or {
        "independent_entries": [
            {
                "region_name": "Navigation",
                "target": "Timer tab",
                "operation": "open page",
            },
            {
                "region_name": "Navigation",
                "target": "World tab",
                "operation": "open page",
                "subject": "World clocks",
            },
            {
                "region_name": "Navigation",
                "target": "World tab",
                "operation": "select navigation item",
            },
        ],
        "deferred_entries": [],
        "deferred_regions": [],
        "reason_consistent": True,
        "reason": "Only World is a new navigation operation on this state.",
    }

    latest = _png("red")
    assert loop._review_pending_entries(runtime, latest, history) == ""
    assert reviewer_calls[0]["current_screenshot"] == after
    assert reviewer_calls[0]["shared_region_entries"] == exposed
    assert not any(
        entry.page_name == "Alarm" and entry.target in {"Timer tab", "Alarm tab"}
        for entry in runtime.entry_ledger.entries
    )
    worlds = [
        entry for entry in runtime.entry_ledger.entries
        if entry.page_name == "Alarm" and entry.target == "World tab"]
    assert [entry.operation for entry in worlds] == [
        "open page", "select navigation item",
    ]
    assert all(entry.status.value == "discovered" for entry in worlds)
    assert [entry.entry_id for entry in runtime.entry_ledger.task_candidates()] == [
        pending_representative_id, worlds[0].entry_id, worlds[1].entry_id,
    ]
    pending_attempt = runtime.entry_ledger.begin_explicit_action(
        pending_representative_id,
        frame_id="frame-clock",
        page_name="Clock",
    )
    runtime.entry_ledger.finish_action(
        pending_attempt.action_id,
        action_executed=True,
        outcome_verified=True,
        result="Alarm page opened",
        destination_page="Alarm",
    )
    assert [entry.entry_id for entry in runtime.entry_ledger.task_candidates()] == [
        worlds[0].entry_id, worlds[1].entry_id,
    ]


def test_target_edge_scope_schedules_only_exact_discovered_button(tmp_path) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path,
        {"screenshot": screenshot},
        [],
        target_edge_scope={
            "source_page": "Kitchen notes",
            "target": "Browse recipes",
            "expected_destination": "Recipe collection",
        },
    )
    page_name, issue = runtime.protocol_map.observe(
        name="Kitchen notes", summary="", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    history = []

    loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{"name": "Actions", "bbox_1000": [0, 0, 1000, 1000],
                      "coverage_complete": True}],
            new_entries=[
                {"region_name": "Actions", "target": "Browse recipes"},
                {"region_name": "Actions", "target": "Open recipe"},
            ],
        ),
        loop.ObservedScene(
            state_id="state-notes", screenshot=screenshot,
            page_name=page_name, is_new=True,
        ),
        screenshot,
        history,
    )
    runtime.entry_review_audits.setdefault("kitchen notes", {})["actions"] = {
        "page_name": "Kitchen notes", "region_name": "Actions",
        "status": "complete",
    }
    loop._sync_exploration_task(runtime)

    target = runtime.entry_ledger.get("ae1")
    background = runtime.entry_ledger.get("ae2")
    assert target.status.value == background.status.value == "discovered"
    assert target.task_eligible is True
    assert background.task_eligible is False
    assert history[-1]["target_edge_scope"]["newly_excluded_entry_ids"] == [
        "ae2",
    ]
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.entry_id == "ae1"


def test_target_edge_scope_reports_discovery_failure_after_source_survey(
    tmp_path,
) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path,
        {"screenshot": screenshot},
        [],
        target_edge_scope={
            "source_page": "Kitchen notes",
            "target": "Browse recipes",
            "expected_destination": "Recipe collection",
        },
    )
    runtime.region_states["kitchen notes"] = (
            AutonomousRegionState.from_snapshot({
            "regions": [{
                "name": "Actions",
                "observations": [{"frame_id": "frame-1"}],
                "coverage_complete": True,
            }],
        })
    )

    assert loop._target_edge_terminal_result(runtime) == {
        "status": "failed",
        "stop_reason": "target_edge_not_discovered",
        "source_page": "Kitchen notes",
        "target": "Browse recipes",
        "entry_id": "",
        "destination_page": "",
        "expected_destination": "Recipe collection",
        "attempt_count": 0,
    }


def test_target_edge_scope_passes_only_after_real_verified_action(tmp_path) -> None:
    screenshot = _png("white")
    runtime, _env, _agent = _runtime(
        tmp_path,
        {"screenshot": screenshot},
        [],
        target_edge_scope={
            "source_page": "Kitchen notes",
            "target": "Browse recipes",
            "expected_destination": "Recipe collection",
        },
    )
    delta = runtime.entry_ledger.record_agent_update(
        page_name="Kitchen notes",
        region_name="Actions",
        frame_id="frame-1",
        observations=[{
            "target": "Browse recipes",
            "bbox_1000": [100, 100, 300, 200],
        }],
    )
    assert loop._target_edge_terminal_result(runtime) is None

    pending = runtime.entry_ledger.begin_explicit_action(
        delta.added[0], frame_id="frame-1", page_name="Kitchen notes")
    runtime.entry_ledger.finish_action(
        pending.action_id,
        action_executed=True,
        outcome_verified=True,
        result="Recipe collection opened",
        destination_page="Recipe collection",
        destination_state_id="state-recipes",
    )

    runtime.entry_ledger.get("ae1").destination_page = "Kitchen notes"
    wrong = loop._target_edge_terminal_result(runtime)
    assert wrong is not None
    assert wrong["stop_reason"] == "target_edge_wrong_destination"
    runtime.entry_ledger.get("ae1").destination_page = "Recipe collection"
    result = loop._target_edge_terminal_result(runtime)
    assert result is not None
    assert result["status"] == "passed"
    assert result["stop_reason"] == "target_edge_verified"
    assert result["entry_id"] == "ae1"
    assert result["destination_page"] == "Recipe collection"
    assert result["expected_destination"] == "Recipe collection"


def test_page_update_commits_good_items_and_defers_completion_for_bad_entry(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Home", summary="Fixture", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-home", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []

    issue = loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            regions=[
                {"name": "Main", "bbox_1000": [0, 0, 1000, 1000],
                 "coverage_complete": True},
                {"name": "Broken", "coverage_complete": "yes"},
            ],
            new_entries=[
                {"region_name": "Main", "target": "Good entry"},
                {
                    "region_name": "Main", "target": "Model ID",
                    "entry_id": "ae13",
                },
                {
                    "region_name": "Main", "target": "Same-turn link",
                    "equivalent_to_entry_id": "ae1",
                },
                {"region_name": "Broken", "target": "Rejected dependency"},
            ],
        ),
        scene,
        screenshot,
        history,
    )

    assert issue == ""
    result = history[-1]
    assert result["kind"] == "page_update_result"
    assert result["status"] == "partial"
    assert result["accepted_regions"] == ["Main"]
    assert result["created_entries"] == [{
        "entry_id": "ae1", "target": "Good entry", "region_name": "Main",
    }]
    rejected = {
        (item["kind"], item["index"], item["error_code"], item["field"])
        for item in result["rejected_items"]
    }
    assert ("region", 1, "invalid_type", "coverage_complete") in rejected
    assert ("new_entry", 1, "unsupported_field", "entry_id") in rejected
    assert (
        "new_entry", 2, "invalid_entry_ref",
        "equivalent_to_entry_id",
    ) in rejected
    assert (
        "new_entry", 3, "unknown_region_reference", "region_name",
    ) in rejected
    assert (
        "region", 0, "coverage_completion_deferred", "coverage_complete",
    ) in rejected
    assert loop._region_state(runtime, "Home").region(
        "Main")["coverage_complete"] is False
    assert [entry.entry_id for entry in runtime.entry_ledger.entries] == ["ae1"]



def test_new_and_existing_regions_may_omit_bbox(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Home", summary="Fixture", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-home", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []

    issue = loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            regions=[
                {"name": "Missing geometry", "coverage_complete": False},
                {
                    "name": "Visible component",
                    "bbox_1000": [100, 100, 900, 900],
                    "coverage_complete": False,
                },
            ],
        ),
        scene,
        screenshot,
        history,
    )

    assert issue == ""
    assert history[-1]["status"] == "accepted"
    assert history[-1]["accepted_regions"] == [
        "Missing geometry", "Visible component"]
    assert history[-1]["rejected_items"] == []
    state = loop._region_state(runtime, "Home")
    assert state.region("Missing geometry") is not None
    assert "missing geometry" not in state.snapshot()["current_bboxes"]
    original_bbox = state.snapshot()["current_bboxes"][
        "visible component"
    ]["bbox_1000"]

    follow_up_history = []
    issue = loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            regions=[{
                "name": "Visible component",
                "summary": "Updated without repeating current geometry",
                "coverage_complete": False,
            }],
        ),
        scene,
        screenshot,
        follow_up_history,
    )

    assert issue == ""
    assert follow_up_history[-1]["status"] == "accepted"
    assert state.snapshot()["current_bboxes"][
        "visible component"
    ]["bbox_1000"] == original_bbox


def test_rejected_page_update_item_keeps_region_stage_for_correction(
    tmp_path,
) -> None:
    registered = _png("navy")
    current = _png("blue")
    turns = [
        _turn(
            "Home",
            action="NONE",
            identity="known",
            page_update=loop.PageUpdate(
                page_name="Home",
                regions=[{
                    "name": "Main",
                    "bbox_1000": [0, 0, 1000, 1000],
                    "coverage_complete": True,
                }],
                new_entries=[{
                    "region_name": "Delivery journey",
                    "target": "View journey",
                }],
            ),
        ),
        _turn(
            "Home",
            action="NONE",
            identity="known",
            page_update=loop.PageUpdate(
                page_name="Home",
                regions=[{
                    "name": "Delivery journey",
                    "bbox_1000": [0, 0, 1000, 1000],
                    "coverage_complete": True,
                }],
                new_entries=[{
                    "region_name": "Delivery journey",
                    "target": "View journey",
                }],
            ),
        ),
    ]
    runtime, _env, agent = _runtime(
        tmp_path, {"screenshot": current}, turns, max_actions=1)
    _bind_incomplete_page(runtime, "Home", registered)

    loop.run_autonomous_traversal(runtime, {"screenshot": current})

    assert len(agent.entry_review_calls) == 1
    second_task = agent.calls[1][2]["exploration_map"]["task"]
    assert second_task["phase"] == "record_regions"
    assert "region" not in second_task
    assert agent.calls[1][2]["exploration_map"]["survey_page_fact"][
        "pending_corrections"]
    assert runtime.entry_ledger.entries[0].target == "View journey"
    assert runtime.entry_ledger.entries[0].task_eligible is True


def test_corrected_entry_region_closes_old_region_binding_rejection(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    _bind_incomplete_page(runtime, "Home", screenshot)
    scene = loop.ObservedScene(
        state_id="state-home", screenshot=screenshot,
        page_name="Home", is_new=False,
    )
    history = []

    loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            new_entries=[{
                "region_name": "Top navigation bar",
                "target": "Daily view toggle",
            }],
        ),
        scene,
        screenshot,
        history,
    )

    assert runtime.page_update_corrections["home"] == {
        "entry:top navigation bar:daily view toggle": {
            "kind": "new_entry",
            "region_name": "Top navigation bar",
            "target": "Daily view toggle",
            "field": "region_name",
            "error_code": "unknown_region_reference",
            "reason": "region_name must reference an existing or accepted Region",
        },
    }

    loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            regions=[{
                "name": "Page header controls",
                "bbox_1000": [0, 0, 1000, 1000],
                "coverage_complete": False,
            }],
            new_entries=[{
                "region_name": "Page header controls",
                "target": "Daily view toggle",
            }],
        ),
        scene,
        screenshot,
        history,
    )

    assert "home" not in runtime.page_update_corrections
    entry = runtime.entry_ledger.entries[0]
    assert entry.target == "Daily view toggle"
    assert entry.region_name == "Page header controls"


def test_framework_completion_needs_no_model_finish_round(tmp_path) -> None:
    screenshot = _png("navy")
    turns = [
        _turn(
            "Home", action="NONE", identity="known",
            page_update=loop.PageUpdate(
                page_name="Home",
                regions=[{
                    "name": "Newly revealed section",
                    "bbox_1000": [0, 0, 1000, 1000],
                    "coverage_complete": True,
                }],
                new_entries=[{
                    "region_name": "Newly revealed section",
                    "target": "Open details",
                }],
            ),
        ),
    ]
    runtime, _env, agent = _runtime(
        tmp_path, {"screenshot": screenshot}, turns, max_actions=1)
    runtime.protocol_map.observe(
        name="Home", summary="Fixture", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    _complete_fixture_survey(runtime, "Home", screenshot)

    graph = loop.run_autonomous_traversal(runtime, {"screenshot": screenshot})

    assert graph.stop_reason == "framework_complete"
    assert agent.calls == []
    assert runtime.entry_ledger.entries == ()


def test_page_identity_arrival_context_includes_latest_semantic_action_only(
    tmp_path,
) -> None:
    screenshot = _png("teal")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    runtime.protocol_map.observe(
        name="Recipe collection",
        summary="Recipes",
        identity="new",
        matched_page_name="",
        surface_kind="page",
        regions=(),
        screenshot=screenshot,
        commit_regions=False,
    )
    history = [{
        "kind": "action",
        "screen": "Recipe collection",
        "landed_screen": "Recipe collection",
        "target": "Recipe list",
        "detail": "The list moved and revealed more recipes.",
        "action_tool_result": {
            "operation": "scroll",
            "before_frame_id": "internal-before",
            "after_frame_id": "internal-after",
        },
    }]

    context = loop._arrival_context_view(runtime, None, history)

    assert context["recent_action"] == {
        "source_page": "Recipe collection",
        "operation": "scroll",
        "target": "Recipe list",
        "landed_page": "Recipe collection",
        "frame_changed": True,
        "result_reason": "The list moved and revealed more recipes.",
    }
    assert not {
        "frame_id", "before_frame_id", "after_frame_id", "hash",
    } & set(context["recent_action"])


def test_region_cannot_flip_incomplete_to_complete_on_same_frame(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Home", summary="Fixture", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-home", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []

    loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            regions=[{"name": "Main", "bbox_1000": [0, 0, 1000, 1000],
                      "coverage_complete": False}],
        ),
        scene,
        screenshot,
        history,
    )
    runtime.exploration_task = ExplorationTask(
        task_type="survey_page", task_id="survey:Home",
        page_name="Home", region_name="Main", phase="survey_region",
    )
    view = loop._exploration_map_view(
        runtime, None, current_screenshot=screenshot)
    assert view["survey_page_fact"]["regions"][0][
        "distinct_frame_since_incomplete"] is False

    loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            regions=[{"name": "Main", "coverage_complete": True}],
        ),
        scene,
        screenshot,
        history,
    )

    result = history[-1]
    assert result["status"] == "rejected"
    assert result["rejected_items"][0]["error_code"] == (
        "coverage_same_frame_without_new_evidence")
    assert loop._region_state(runtime, "Home").region(
        "Main")["coverage_complete"] is False

    changed_screenshot = _png("green")
    loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            regions=[{"name": "Main", "coverage_complete": True}],
        ),
        scene,
        changed_screenshot,
        history,
    )
    assert history[-1]["status"] == "accepted"
    assert loop._region_state(runtime, "Home").region(
        "Main")["coverage_complete"] is True


def test_survey_region_rejects_sibling_only_update_without_ledger_progress(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Help", summary="Help", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-help", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Help",
            regions=[
                {"name": "Top navigation", "bbox_1000": [0, 0, 1000, 200],
                 "coverage_complete": False},
                {"name": "Document content", "bbox_1000": [0, 200, 1000, 1000],
                 "coverage_complete": True},
            ],
        ),
        scene,
        screenshot,
        history,
        allow_same_frame_completion=True,
    )
    runtime.exploration_task = ExplorationTask(
        task_type="survey_page", task_id="survey:Help",
        page_name="Help", region_name="Top navigation",
        phase="survey_region",
    )
    runtime.page_update_corrections["help"] = {
        "region:top navigation": {
            "kind": "region",
            "region_name": "Top navigation",
            "error_code": "coverage_same_frame_without_new_evidence",
        },
    }
    regions_before = loop._region_state(runtime, "Help").snapshot()
    corrections_before = json.loads(json.dumps(
        runtime.page_update_corrections))
    progress_before = loop._rejection_progress_token(runtime)

    reviewed_update, issue = loop._review_region_proposal(
        runtime,
        loop.PageUpdate(
            page_name="Help",
            regions=[{
                "name": "Document content",
                "coverage_complete": True,
            }],
        ),
        scene,
        screenshot,
        history,
        main_agent_reason="The document content is already complete.",
    )

    assert reviewed_update is None
    assert "omitted the assigned Region" in issue
    assert history[-1]["status"] == "rejected"
    assert history[-1]["rejected_items"][0]["error_code"] == (
        "survey_region_target_missing")
    assert loop._region_state(runtime, "Help").snapshot() == regions_before
    assert runtime.page_update_corrections == corrections_before
    assert loop._rejection_progress_token(runtime) == progress_before

    history_length = len(history)
    aligned_update = loop.PageUpdate(
        page_name="Help",
        regions=[
            {"name": "Top navigation", "coverage_complete": False},
            {"name": "Document content", "coverage_complete": True},
        ],
    )
    reviewed_update, issue = loop._review_region_proposal(
        runtime,
        aligned_update,
        scene,
        screenshot,
        history,
        main_agent_reason="Both visible Regions were checked.",
    )
    assert issue == ""
    assert reviewed_update == aligned_update
    assert len(history) == history_length


def test_no_change_scroll_can_be_agent_evidence_for_same_frame_completion(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Home", summary="Fixture", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-home", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            regions=[{"name": "Main", "bbox_1000": [0, 0, 1000, 1000],
                      "coverage_complete": False}],
        ),
        scene,
        screenshot,
        history,
    )

    loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            regions=[{"name": "Main", "coverage_complete": True}],
        ),
        scene,
        screenshot,
        history,
        allow_same_frame_completion=True,
    )

    assert history[-1]["status"] == "accepted"
    assert loop._region_state(runtime, "Home").region(
        "Main")["coverage_complete"] is True


def test_task_local_reuse_links_entry_only_after_explicit_region_merge(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    frame_id = loop.screenshot_frame_id(screenshot)
    first_ref, _ = runtime.region_registry.bind(
        page_name="Home", region_name="Main", summary="Shared controls")
    runtime.region_registry.bind(
        page_name="Other", region_name="Main", summary="Shared controls",
        equivalent_to_region_ref=first_ref,
        reason="The Agent judged both Regions to expose the same controls.",
    )
    runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id=frame_id,
        observations=[{"target": "Representative"}],
    )
    runtime.entry_ledger.record_agent_update(
        page_name="Other", region_name="Main", frame_id=frame_id,
        observations=[{"target": "Equivalent occurrence"}],
    )
    pending = runtime.entry_ledger.begin_explicit_action(
        "ae1", frame_id=frame_id, page_name="Home")
    runtime.entry_ledger.finish_action(
        pending.action_id,
        action_executed=True,
        outcome_verified=True,
        result="Opened shared settings",
        destination_page="Settings",
        destination_state_id="state-settings",
    )
    runtime.exploration_task = ExplorationTask(
        task_type="explore_entry", task_id="entry:ae2", entry_id="ae2",
        page_name="Other", region_name="Main",
        target="Equivalent occurrence",
    )

    evidence = loop._reuse_entry_result(runtime, {
        "entry_id": "ae2",
        "representative_entry_id": "ae1",
        "reason": "The control and the verified outcome are stable across the shared Region.",
    })

    assert evidence.status == "accepted"
    assert runtime.entry_ledger.get("ae2").representative_entry_id == "ae1"
    assert runtime.entry_ledger.get("ae2").destination_page == "Settings"
    assert "ae1" not in evidence.data["feedback"]


def test_nested_region_entry_batch_reuse_auto_binds_owner(tmp_path) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    frame_id = loop.screenshot_frame_id(screenshot)
    runtime.protocol_map.observe(
        name="Today overview", summary="Today", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    region_ref, _ = runtime.region_registry.bind(
        page_name="Today overview", region_name="Team inbox",
        summary="Questions and decisions waiting for review.",
    )
    delta = runtime.entry_ledger.record_agent_update(
        page_name="Today overview", region_name="Team inbox",
        frame_id=frame_id,
        observations=[{"target": "Open weekly review"}],
    )
    pending = runtime.entry_ledger.begin_explicit_action(
        delta.added[0], frame_id=frame_id, page_name="Today overview")
    runtime.entry_ledger.finish_action(
        pending.action_id,
        action_executed=True,
        outcome_verified=True,
        result="Opened Weekly review",
        destination_page="Weekly review",
        destination_state_id="state-review",
    )
    page_name, issue = runtime.protocol_map.observe(
        name="Project workspace", summary="Workspace", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    payload = {
            "screen": {
                "name": page_name, "identity": "known",
                "variant": {
                    "name": "default", "identity": "known",
                    "visible_predicates": ["Project workspace is visible"],
                },
            },
        "reason": "The shared Team inbox card and its entry match the verified candidate.",
        "page_update": {
            "page_name": page_name,
            "regions": [{
                "name": "Team inbox",
                "bbox_1000": [0, 0, 1000, 1000],
                "equivalent_to_region_ref": region_ref,
                "equivalence_reason": "The card components and roles match.",
                "coverage_complete": True,
                "entries": [{
                    "target": "Open weekly review",
                    "equivalent_to_entry_id": "ae1",
                }],
            }],
        },
        "action": None,
    }
    turn, error = parse_turn(payload, has_previous=False)
    assert error == ""
    assert turn is not None and turn.page_update is not None
    assert turn.page_update.new_entries == [{
        "target": "Open weekly review",
        "equivalent_to_entry_id": "ae1",
        "region_name": "Team inbox",
    }]
    history = []
    assert loop._apply_main_agent_page_update(
        runtime,
        turn.page_update,
        loop.ObservedScene(
            state_id="state-workspace", screenshot=screenshot,
            page_name=page_name, is_new=True,
        ),
        screenshot,
        history,
    ) == ""
    assert history[-1]["status"] == "rejected"
    assert history[-1]["rejected_items"][0]["error_code"] == (
        "region_equivalence_review_required")
    assert runtime.entry_ledger.entries == (runtime.entry_ledger.get("ae1"),)
    assert _page_survey_need(runtime, page_name) == (
        "region_equivalence_review_pending", "",
        "review_region_equivalence",
    )

    assert loop._apply_main_agent_page_update(
        runtime,
        turn.page_update,
        loop.ObservedScene(
            state_id="state-workspace", screenshot=screenshot,
            page_name=page_name, is_new=True,
        ),
        screenshot,
        history,
    ) == ""

    linked = runtime.entry_ledger.get("ae2")
    assert linked.page_name == "Project workspace"
    assert linked.region_name == "Team inbox"
    assert linked.representative_entry_id == "ae1"
    assert linked.destination_page == "Weekly review"
    assert linked.status.value == "inferred"
    assert linked.task_eligible is False
    assert history[-1]["status"] == "accepted"
    assert "was confirmed equivalent" in history[-1]["feedback"]
    assert "project workspace" not in runtime.page_update_corrections


def test_region_reference_requires_focused_review_before_binding(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Weekly review", summary="Fixture", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-review", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    region_ref, _ = runtime.region_registry.bind(
        page_name="Today overview",
        region_name="Team inbox",
        summary="Questions and decisions waiting for review.",
    )
    history = []

    loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Weekly review",
            regions=[{
                "name": "Today's focus",
                "bbox_1000": [0, 0, 1000, 1000],
                "summary": "Commitments needing attention.",
                "equivalent_to_region_ref": region_ref,
                "equivalence_reason": "Both have an item badge.",
                "coverage_complete": True,
            }],
        ),
        scene,
        screenshot,
        history,
    )

    result = history[-1]
    assert result["status"] == "rejected"
    assert result["rejected_items"][0]["error_code"] == (
        "region_equivalence_review_required")
    assert result["rejected_items"][0]["canonical_name"] == "Team inbox"
    assert "has not been committed" in (
        result["rejected_items"][0]["reason"])
    assert _page_survey_need(runtime, "Weekly review") == (
        "region_equivalence_review_pending", "",
        "review_region_equivalence",
    )
    assert loop._region_state(runtime, "Weekly review").snapshot()[
        "regions"] == []

    loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Weekly review",
            regions=[{
                "name": "Today's focus",
                "bbox_1000": [0, 0, 1000, 1000],
                "summary": "Commitments needing attention.",
                "equivalent_to_region_ref": "",
                "equivalence_reason": (
                    "The title, content, and primary entry conflict with "
                    "Team inbox."
                ),
                "coverage_complete": True,
            }],
        ),
        scene,
        screenshot,
        history,
    )

    assert history[-1]["status"] == "accepted"
    assert runtime.region_registry.region_ref(
        "Weekly review", "Today's focus") != region_ref
    assert "weekly review" not in runtime.page_update_corrections
    assert "remains distinct" in history[-1]["feedback"]


def test_page_update_reports_exact_entry_replay_as_existing(tmp_path) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Home", summary="Fixture", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-home", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    frame_id = loop.screenshot_frame_id(screenshot)
    state = loop._region_state(runtime, "Home")
    state.observe_frame(frame_id)
    state.apply_agent_update([{
        "name": "Main", "coverage_complete": False,
    }], frame_id=frame_id)
    region_ref, _ = runtime.region_registry.bind(
        page_name="Home", region_name="Main", state_id=scene.state_id)
    state.set_region_ref("Main", region_ref)
    runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id=frame_id,
        observations=[{"target": "Open details"}],
        source_state_id=scene.state_id,
    )
    history = []

    loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Home",
            new_entries=[{
                "region_name": "Main", "target": "Open details",
            }],
        ),
        scene,
        screenshot,
        history,
    )

    assert len(runtime.entry_ledger.entries) == 1
    assert history[-1]["status"] == "accepted"
    assert history[-1]["created_entries"] == []
    assert history[-1]["matched_entries"] == [{
        "entry_id": "ae1",
        "target": "Open details",
        "region_name": "Main",
        "match": "duplicate_entry_exact",
    }]


def test_finish_requires_explicit_main_agent_region_coverage(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.region_states["setup"] = AutonomousRegionState.from_snapshot({
        "regions": [{
            "name": "Alarm Preferences List",
            "observations": [{"frame_id": "frame-1"}],
            "coverage_complete": False,
        }],
    })

    gaps = loop._completion_gaps(runtime)

    assert gaps == [
        "setup: Region Alarm Preferences List has coverage_complete=false",
    ]


def test_prompt_gives_history_without_candidate_contract() -> None:
    prompt = build_prompt(
        [{
            "kind": "action", "screen": "Home", "action": "CLICK",
            "target": "Settings", "outcome": "no_visible_change",
            "rejection": {
                "status": "rejected",
                "reason_code": "page_identity_unresolved",
                "reason": "The landing page is not registered.",
                "suggested_next_tool": "page_identity",
                "retry_after": "identity_resolved",
                "correction": "Resolve the foreground page first.",
            },
        }],
        app_name="fixture",
        platform="local_html",
    )

    assert "Settings" in prompt
    assert "The landing page is not registered" in prompt
    assert "Resolve the foreground page first" in prompt
    assert "当前任务历史（按时间顺序）" in prompt
    assert "最新完整截图是当前界面的依据" in prompt
    assert "不能复用旧截图中的坐标" in prompt
    assert "当前任务是调查页面" in prompt
    assert "page_update" in prompt
    assert "equivalent_to_entry_id" not in prompt
    assert "equivalent_to_region_ref" not in prompt
    assert "finish_exploration" not in prompt
    assert "自然语言全局地图" in prompt
    tool_arguments = RESPONSE_SCHEMA["properties"]["action"][
        "properties"]["tool_arguments"]
    assert tool_arguments["additionalProperties"] is False
    lean_schema = response_schema_for_tools([{
        "name": "navigate",
        "description": "wait",
        "input_schema": {
            "type": "object", "properties": {}, "required": [],
            "additionalProperties": False,
        },
    }])
    assert lean_schema["required"] == [
        "screen", "reason", "task_strategy", "action",
    ]
    assert "previous_action" not in lean_schema["properties"]
    assert "previous_tool_review" not in lean_schema["properties"]
    assert "task_progress" not in lean_schema["properties"]
    assert "page_identity" in {
        item["name"] for item in available_tool_catalog(
            pending_identity=True)
    }


def test_history_summary_keeps_all_current_task_records() -> None:
    history = [{
        "kind": "action",
        "screen": "Home",
        "action": "CLICK",
        "target": f"target-{index}",
        "outcome": "no_visible_change",
        "exploration_task_id": "survey:home",
        "validated_action": {
            "operation": "click",
            "arguments": {
                "target": f"target-{index}",
                "point_1000": [index, index],
            },
        },
    } for index in range(12)]

    summary = _history_summary(
        history, current_task_id="survey:home")

    assert len(summary["recent_results"]) == 12
    assert summary["recent_results"][0]["target"] == "target-0"
    assert "latest_exploration_memory" not in summary
    assert "observed_screens" not in summary
    assert "tried_actions" not in summary

    prompt = build_prompt(
        history,
        app_name="fixture",
        platform="local_html",
        exploration_map={"task": {
            "task_id": "survey:home",
            "type": "survey_page",
            "page": "Home",
            "phase": "record_regions",
        }},
    )
    assert all(f"target-{index}" in prompt for index in range(12))
    assert 'parameters={"target":"target-0","point_1000":[0,0]}' in prompt


def test_history_summary_returns_region_comparison_resolution_to_agent() -> None:
    summary = _history_summary([{
        "kind": "page_update_result",
        "screen": "Alarms",
        "status": "accepted",
        "accepted_regions": ["New Alarm Modal"],
        "feedback": (
            "Region comparison resolved: 'New Alarm Modal' remains distinct "
            "from rg2 ('Main Content Area')."
        ),
        "rejected_items": [],
    }])

    assert summary["recent_results"][0]["feedback"] == (
        "Region comparison resolved: 'New Alarm Modal' remains distinct "
        "from rg2 ('Main Content Area')."
    )


def test_prompt_preserves_full_entry_reviewer_verdict_and_reason() -> None:
    reviewer_reason = (
        "这些候选项都清晰可见，并且只是同一个持续时间参数的不同取值，"
        "不会打开或切换独立功能表面，因此应当丢弃而不是延后。"
        + "完整理由不能被简短记忆截断。" * 20
    )
    history = [{
        "kind": "entry_review_result",
        "screen": "Alarms",
        "status": "accepted",
        "kept": [{
            "region_name": "New Alarm Modal",
            "target": "Ring Duration dropdown",
        }],
        "added": [],
        "dropped": [{
            "region_name": "New Alarm Modal",
            "target": "Cancel button",
        }],
        "deferred": [{
            "region_name": "Ring Duration menu",
            "target": "1 minute option",
        }, {
            "region_name": "Ring Duration menu",
            "target": "5 minutes option",
        }],
        "deferred_regions": ["Ring Duration menu"],
        "reason_consistent": False,
        "reviewer_reason": reviewer_reason,
        "detail": "Entry Reviewer deferred 2 visually unresolved candidates.",
        "exploration_task_id": "survey:alarms",
    }]

    summary = _history_summary(history)
    feedback = summary["recent_results"][0]["entry_review_feedback"]
    assert "New Alarm Modal / Ring Duration dropdown" in feedback
    assert "New Alarm Modal / Cancel button" in feedback
    assert "Ring Duration menu / 1 minute option" in feedback
    assert "Ring Duration menu / 5 minutes option" in feedback
    assert "Reviewer 对主 Agent 理由的一致性判断：不一致" in feedback
    assert reviewer_reason in feedback

    prompt = build_prompt(
        history,
        app_name="Clocks",
        platform="desktop",
        exploration_map={"task": {
            "task_id": "survey:alarms",
            "type": "survey_page",
            "phase": "survey_region",
        }},
    )
    assert reviewer_reason in prompt
    assert "Ring Duration menu / 1 minute option" in prompt
    assert "Entry Reviewer deferred 2 visually unresolved candidates" not in prompt


def test_entry_review_correction_is_not_a_main_agent_tool(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Alarms", summary="Alarm list", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == "" and page_name == "Alarms"
    frame_id = loop.screenshot_frame_id(screenshot)
    region_key = loop._page_key("New Alarm Modal")
    runtime.entry_review_deferred_frames = {
        loop._page_key("Alarms"): {region_key: frame_id},
    }
    page_key = loop._page_key("Alarms")
    matching_correction = "entry:new alarm modal:1 minute option"
    unrelated_correction = "entry:new alarm modal:search field"
    runtime.page_update_corrections[page_key] = {
        matching_correction: {
            "kind": "new_entry",
            "region_name": "New Alarm Modal",
            "target": "1 minute option",
            "field": "equivalent_to_entry_id",
        },
        unrelated_correction: {
            "kind": "new_entry",
            "region_name": "New Alarm Modal",
            "target": "Search field",
            "field": "equivalent_to_entry_id",
        },
    }
    deferred = [{
        "region_name": "New Alarm Modal",
        "target": "1 minute option",
    }, {
        "region_name": "New Alarm Modal",
        "target": "5 minutes option",
    }]
    history = [{
        "kind": "entry_review_result",
        "screen": "Alarms",
        "frame_id": frame_id,
        "status": "accepted",
        "deferred": deferred,
        "deferred_regions": [],
        "reason_consistent": False,
        "reviewer_reason": "These are value selectors and should be dropped.",
    }]

    catalog_names = {
        item["name"] for item in loop._dynamic_tool_catalog(
            runtime, screenshot, history)
    }
    assert "review_entry_record" not in catalog_names


def test_review_entry_record_rejects_non_deferred_candidate_without_mutation(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    runtime.protocol_map.observe(
        name="Alarms", summary="Alarm list", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    frame_id = loop.screenshot_frame_id(screenshot)
    page_key = loop._page_key("Alarms")
    region_key = loop._page_key("New Alarm Modal")
    runtime.entry_review_deferred_frames = {
        page_key: {region_key: frame_id},
    }
    history = [{
        "kind": "entry_review_result",
        "screen": "Alarms",
        "frame_id": frame_id,
        "status": "accepted",
        "deferred": [{
            "region_name": "New Alarm Modal",
            "target": "1 minute option",
        }],
        "deferred_regions": [],
    }]

    result = loop._review_entry_record(
        runtime,
        {"operation": "correct", "drop_deferred_entries": [{
            "region_name": "New Alarm Modal",
            "target": "Add button",
        }], "reason": "Try to remove another control."},
        screenshot,
        history,
    )

    assert result.status == "invalid_arguments"
    assert runtime.entry_review_deferred_frames == {
        page_key: {region_key: frame_id},
    }


def test_history_summary_returns_finish_gap_items_to_the_agent() -> None:
    summary = _history_summary([{
        "kind": "finish_gap",
        "screen": "Settings",
        "outcome": "finish_rejected",
        "detail": "framework evidence gaps remain",
        "remaining": [
            "Settings: Region Timers has coverage_complete=false",
            "Settings: Style needs restore",
        ],
        "rejection": {
            "reason_code": "completion_evidence_missing",
            "reason": "framework evidence gaps remain",
        },
    }])

    assert summary["recent_results"] == []
    record = summary["active_rejection"]
    assert record["remaining"] == [
        "Settings: Region Timers has coverage_complete=false",
        "Settings: Style needs restore",
    ]


def test_finish_rejections_use_one_general_evidence_error(tmp_path) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.exploration_task = ExplorationTask(
        task_type="survey_page", task_id="survey:Home", page_name="Home",
    )
    gaps = ["Home: Region Results has coverage_complete=false"]

    first = _finish_rejection_record(
        runtime, screen_name="Home", gaps=gaps)
    repeated = _finish_rejection_record(
        runtime, screen_name="Home", gaps=gaps)

    assert first["rejection"]["code"] == "completion_evidence_missing"
    assert repeated["rejection"]["code"] == "completion_evidence_missing"
    assert repeated["remaining"] == gaps


def test_general_rejection_boundary_suspends_each_task_and_continues(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.protocol_map.observe(
        name="Home", summary="Home", identity="new", matched_page_name="",
        surface_kind="page", regions=(), screenshot=screen["screenshot"],
        commit_regions=False,
    )
    _complete_fixture_survey(runtime, "Home", screen["screenshot"])
    entry_delta = runtime.entry_ledger.record_agent_update(
        page_name="Home",
        region_name="Main",
        frame_id=loop.screenshot_frame_id(screen["screenshot"]),
        observations=[
            {"target": "First function"},
            {"target": "Second function"},
        ],
    )
    entries = [runtime.entry_ledger.get(entry_id) for entry_id in entry_delta.added]
    loop._sync_exploration_task(runtime)
    first_task_id = runtime.exploration_task.task_id
    assert first_task_id == f"explore:{entries[0].entry_id}"

    history = []
    for _index in range(TASK_REJECTION_LIMIT):
        rejected = {
            "kind": "protocol_feedback",
            "rejection": {
                "status": "rejected", "code": "fixture_rejection",
            },
        }
        history.append(rejected)
        assert loop._update_rejection_boundary(
            runtime, history, [rejected], progress_made=False,
        ) is False

    assert first_task_id in runtime.suspended_task_keys
    assert runtime.exploration_task is None
    assert runtime.run_rejection_streak == 0
    assert history[-1]["kind"] == "task_suspended"

    loop._sync_exploration_task(runtime)
    second_task_id = f"explore:{entries[1].entry_id}"
    assert runtime.exploration_task.task_id == second_task_id
    for _index in range(TASK_REJECTION_LIMIT):
        rejected = {
            "kind": "protocol_feedback",
            "rejection": {
                "status": "rejected", "code": "fixture_rejection",
            },
        }
        history.append(rejected)
        should_stop = loop._update_rejection_boundary(
            runtime, history, [rejected], progress_made=False,
        )

    assert should_stop is False
    assert second_task_id in runtime.suspended_task_keys
    assert runtime.exploration_task is None
    assert runtime.run_rejection_streak == 0
    assert history[-1]["kind"] == "task_suspended"
    assert not any(item.get("kind") == "traversal_stopped"
                   for item in history)


def test_rejected_tool_result_counts_toward_task_rejection_limit(
    tmp_path,
) -> None:
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": _png("navy")}, [])
    runtime.exploration_task = ExplorationTask(
        task_type="explore_entry",
        task_id="explore:ae1",
        entry_id="ae1",
        page_name="Home",
        region_name="Main",
        target="Open menu",
    )
    history = []

    for _index in range(TASK_REJECTION_LIMIT):
        rejected = {
            "kind": "tool",
            "tool_name": "reuse_entry_result",
            "tool_result": {
                "status": "rejected",
                "data": {
                    "feedback": "The cited entry is not a current candidate.",
                },
            },
        }
        history.append(rejected)
        assert loop._update_rejection_boundary(
            runtime, history, [rejected], progress_made=False,
        ) is False

    assert "explore:ae1" in runtime.suspended_task_keys
    assert runtime.exploration_task is None
    assert history[-1]["kind"] == "task_suspended"


def test_pending_action_rejection_limit_stops_without_rescheduling_or_retry(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("navy")}
    frame_id = loop.screenshot_frame_id(screen["screenshot"])
    runtime, env, _agent = _runtime(
        tmp_path,
        screen,
        [
            _turn(
                "Home", action="CALL_TOOL", identity="known",
                target="First function", tool_name="click", tool_arguments={
                    "target": "First function", "entry_id": "ae1",
                    "point_1000": [500, 500],
                }),
            *([None] * TASK_REJECTION_LIMIT),
        ],
    )
    runtime.decision_agent.auto_stage_variants = False
    runtime.protocol_map.observe(
        name="Home", summary="Home", identity="new", matched_page_name="",
        surface_kind="page", regions=(), screenshot=screen["screenshot"],
        commit_regions=False,
    )
    entry_delta = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id=frame_id,
        observations=[
            {"target": "First function"},
            {"target": "Unrelated second function"},
        ],
    )
    first_entry_id, second_entry_id = entry_delta.added
    _complete_fixture_survey(runtime, "Home", screen["screenshot"])
    runtime.click_reviewer = lambda _request: {
        "decision": "approve",
        "observed_target": "First function",
        "point_matches_target": True,
        "target_matches_request": True,
        "risk": "safe",
        "reason": "The point is on the requested visible target.",
    }

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert len(env.actions) == 1
    assert graph.stop_reason == "pending_action_assessment_limit"
    assert runtime.suspended_task_keys == set()
    first = runtime.entry_ledger.get(first_entry_id)
    assert first.status.value == "unresolved"
    assert first.task_eligible is False
    assert runtime.entry_ledger.pending_actions == ()
    assert runtime.entry_ledger.get(second_entry_id).task_eligible is True
    assert any(
        "executed GUI action remains unverified" in gap
        for gap in loop._completion_gaps(runtime))
    attempt = graph.action_edges[0]["attempts"][0]
    assert attempt["outcome"] == "assessment_unavailable"
    assert attempt["landing_verified"] is False
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    assert not any(item.get("kind") == "task_suspended"
                   for item in trace["history"])
    assert any(item.get("kind") == "pending_action_unverified"
               for item in trace["history"])
    entries_snapshot = json.loads(
        (Path(tmp_path) / "autonomous_entries.json").read_text(
            encoding="utf-8"))
    assert entries_snapshot["pending_actions"] == []
    saved_first = next(
        item for item in entries_snapshot["entries"]
        if item["entry_id"] == first_entry_id)
    assert saved_first["task_eligible"] is False


def test_real_progress_resets_both_rejection_streaks(tmp_path) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.exploration_task = ExplorationTask(
        task_type="survey_page", task_id="survey:Home", page_name="Home",
    )
    rejected = {
        "kind": "protocol_feedback",
        "rejection": {"status": "rejected", "code": "fixture_rejection"},
    }
    loop._update_rejection_boundary(
        runtime, [rejected], [rejected], progress_made=False,
    )
    assert runtime.task_rejection_streak == 1
    assert runtime.run_rejection_streak == 1

    read_only = {
        "kind": "tool", "tool_name": "page_identity", "outcome": "known",
        "tool_result": {"status": "known", "data": {"page": "Home"}},
    }
    loop._update_rejection_boundary(
        runtime, [rejected, read_only], [read_only], progress_made=False,
    )
    assert runtime.task_rejection_streak == 1
    assert runtime.run_rejection_streak == 1

    accepted_without_new_fact = {
        "kind": "page_update_result",
        "status": "partial",
        "accepted_regions": ["Main"],
        "rejected_items": [{"kind": "new_entry"}],
    }
    loop._update_rejection_boundary(
        runtime, [rejected, accepted_without_new_fact],
        [accepted_without_new_fact], progress_made=False,
    )
    assert runtime.task_rejection_streak == 1
    assert runtime.run_rejection_streak == 1

    loop._update_rejection_boundary(
        runtime, [rejected, accepted_without_new_fact],
        [accepted_without_new_fact], progress_made=True,
    )
    assert runtime.task_rejection_streak == 0
    assert runtime.run_rejection_streak == 0


def test_repeated_failed_entry_attempts_are_not_stable_progress(tmp_path) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    runtime.protocol_map.observe(
        name="Home", summary="Home", identity="new", matched_page_name="",
        surface_kind="page", regions=(), screenshot=screenshot,
        commit_regions=False,
    )
    frame_id = loop.screenshot_frame_id(screenshot)
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id=frame_id,
        observations=[{"target": "Open details"}],
    ).added[0]
    before = loop._rejection_progress_token(runtime)

    pending = runtime.entry_ledger.begin_explicit_action(
        entry_id, frame_id=frame_id, page_name="Home")
    assert loop._rejection_progress_token(runtime) == before
    runtime.entry_ledger.finish_action(
        pending.action_id, action_executed=True, outcome_verified=False,
        result="wrong control", destination_page="Unrelated",
    )

    assert loop._rejection_progress_token(runtime) == before


def test_action_null_without_stage_or_ledger_progress_hits_shared_boundary(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, env, _agent = _runtime(
        tmp_path,
        screen,
        [
            _turn("Home", action="NONE", identity="known")
            for _index in range(RUN_REJECTION_LIMIT)
        ],
    )
    _bind_incomplete_page(runtime, "Home", screen["screenshot"])

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert env.actions == []
    assert graph.stop_reason == "all_remaining_work_suspended"
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    stalled = [
        item for item in trace["history"]
        if item.get("rejection", {}).get("code")
        == "stage_incomplete_no_action"
    ]
    assert len(stalled) == TASK_REJECTION_LIMIT
    assert any(item.get("kind") == "task_suspended"
               for item in trace["history"])


def test_route_stage_no_action_feedback_names_first_known_step(tmp_path) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.exploration_task = ExplorationTask(
        task_type="explore_entry",
        task_id="explore:ae8",
        entry_id="ae8",
        page_name="Recipe details",
        region_name="Actions",
        target="Browse recipes",
        phase="route_to_source",
        route_hint=[{
            "from": "Pantry",
            "via": "Open recipe button",
            "to": "Recipe details",
        }],
    )

    detail = loop._stage_incomplete_no_action_detail(
        runtime, stage_name="route_to_source", current_page="Pantry")

    assert "current Page 'Pantry'" in detail
    assert "target Page 'Recipe details'" in detail
    assert "'Pantry' --Open recipe button--> 'Recipe details'" in detail
    assert "report_record_error" in detail


def test_reworded_record_error_on_same_task_frame_hits_shared_boundary(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("navy")}
    reports = [
        _turn(
            "Home",
            action="CALL_TOOL",
            identity="known",
            tool_name="report_record_error",
            tool_arguments={
                "kind": "page_identity",
                "subject": f"page identity wording {index}",
                "observed_problem": f"same visual dispute reworded {index}",
            },
        )
        for index in range(12)
    ]
    runtime, env, _agent = _runtime(tmp_path, screen, reports)
    _bind_incomplete_page(runtime, "Home", screen["screenshot"])

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert env.actions == []
    assert graph.stop_reason == "all_remaining_work_suspended"
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    accepted = [
        item for item in trace["history"]
        if item.get("kind") == "tool"
        and item.get("tool_name") == "report_record_error"
    ]
    duplicates = [
        item for item in trace["history"]
        if item.get("rejection", {}).get("code")
        == "duplicate_record_error_same_frame"
    ]
    assert len(accepted) == 1
    assert len(duplicates) == TASK_REJECTION_LIMIT
    assert all(item.get("outcome") == "not_executed" for item in duplicates)


def test_history_summary_keeps_repeated_tool_results_in_order() -> None:
    history = []
    for decision in (1, 2, 3):
        history.extend([{
            "kind": "observation",
            "decision": decision,
            "screen": "Settings",
        }, {
            "kind": "tool",
            "screen": "Settings",
            "tool_name": "page_identity",
            "outcome": "uncertain",
            "tool_result": {
                "status": "uncertain",
                "data": {"reported_current_page": "Settings"},
            },
        }])

    summary = _history_summary(history)

    assert "repeat_warning" not in summary
    assert len(summary["recent_results"]) == 6
    assert [item["history_number"] for item in summary["recent_results"]] == [
        1, 2, 3, 4, 5, 6,
    ]


def test_history_summary_does_not_carry_tool_repetition_across_tasks() -> None:
    history = [{
        "kind": "tool",
        "tool_name": "page_identity",
        "outcome": "uncertain",
        "tool_result": {"status": "uncertain"},
        "exploration_task_id": "survey:old",
    } for _ in range(2)]
    history.append({
        "kind": "tool",
        "tool_name": "page_identity",
        "outcome": "uncertain",
        "tool_result": {"status": "uncertain"},
        "exploration_task_id": "survey:current",
    })

    summary = _history_summary(
        history, current_task_id="survey:current")

    assert "repeat_warning" not in summary


def test_page_identity_specialist_uses_stateless_codex_adapter(tmp_path) -> None:
    agent = loop.CodexAutonomousAgent(
        "codex-fixture-model", str(tmp_path), timeout=1)
    captured = {}

    def invoke_specialist(**values):
        captured.update(values)
        return {"status": "uncertain"}

    agent.invoke_specialist = invoke_specialist
    current = _png("navy")
    candidate = _png("orange")
    result = agent.resolve_page_identity({
        "identity_stage": "page",
        "current_screenshot": current,
        "suspected_pages": ["Home"],
        "proposed_new_name": "Settings",
        "reason": "The current surface is ambiguous.",
        "registered_pages": [{
            "page_name": "Home",
            "summary": "Main page",
            "surface_kind": "page",
            "regions": [],
            "representative_screenshot": candidate,
            "variants": [{
                "variant_name": "default",
                "visible_predicates": ["Main page is visible"],
                "representative_screenshot": candidate,
            }],
        }],
        "previous_tool_feedback": {
            "decision": "reject",
            "reason": "The proposal described the background.",
            "correction": "Judge the foreground Settings dialog.",
        },
        "arrival_context": {
            "source_page": "Home",
            "via_action": "CLICK",
            "via_control": "Settings",
            "source_neighbors": [],
            "recent_action": {
                "operation": "click",
                "target": "Settings",
                "result_reason": "Settings opened.",
            },
        },
    })

    assert result == {"status": "uncertain"}
    assert captured["tool_name"] == "page_identity"
    assert captured["screenshots"] == [current, candidate]
    assert captured["response_schema"] is PAGE_ONLY_IDENTITY_RESPONSE_SCHEMA
    assert "不判断页面状态版本" in captured["system_prompt"]
    assert "临时弹窗、提示或遮挡不是页面" in captured["system_prompt"]
    assert "图片顺序" in captured["prompt"]
    assert "候选 Page “Home”的代表截图" in captured["prompt"]
    assert "此前位于页面 Home" in captured["prompt"]
    assert "最近通过点击可见控件“Settings”" in captured["prompt"]
    assert "最近一次 GUI 动作" in captured["prompt"]
    assert "Settings opened." in captured["prompt"]
    assert "previous_tool_feedback" not in captured["prompt"]
    assert "The proposal described the background." in captured["prompt"]
    assert "Judge the foreground Settings dialog." in captured["prompt"]
    assert '"decision": "reject"' not in captured["prompt"]
    assert '"via_action": "CLICK"' not in captured["prompt"]


def test_codex_specialist_sends_long_prompt_through_stdin(
    tmp_path, monkeypatch,
) -> None:
    captured = {}

    class _Completed:
        returncode = 0
        stdout = json.dumps({
            "type": "thread.started",
            "thread_id": "thread-long-prompt",
        })
        stderr = ""

    def _run(command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = dict(kwargs)
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text(
            json.dumps({"reason": "valid response"}), encoding="utf-8")
        return _Completed()

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.runtime."
        "autonomous_agent.subprocess.run",
        _run,
    )
    agent = loop.CodexAutonomousAgent(
        "gpt-5.6-luna", str(tmp_path), timeout=1)
    prompt = "complex-page-context:" + ("x" * 40000)

    result = agent.invoke_specialist(
        tool_name="modular_main_agent",
        prompt=prompt,
        screenshots=[],
        response_schema={
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    )

    assert result == {"reason": "valid response"}
    assert captured["command"][-1] == "-"
    assert captured["kwargs"]["input"] == prompt


def test_page_identity_adapter_compares_source_and_variant_screenshots(
    tmp_path,
) -> None:
    agent = loop.CodexAutonomousAgent(
        "codex-fixture-model", str(tmp_path), timeout=1)
    captured = {}
    agent.invoke_specialist = lambda **values: (
        captured.update(values) or {"status": "uncertain"}
    )
    current = _png("green")
    source = _png("white")
    empty = _png("silver")
    dialog = _png("blue")

    agent.resolve_page_identity({
        "current_screenshot": current,
        "source_screenshot": source,
        "suspected_pages": ["World"],
        "proposed_new_name": "",
        "reason": "Determine the material World Variant.",
        "registered_page_count": 1,
        "registered_pages": [{
            "page_name": "World",
            "summary": "World clock",
            "surface_kind": "page",
            "regions": [],
            "variants": [
                {
                    "variant_name": "world.empty",
                    "visible_predicates": ["City list is empty"],
                    "representative_screenshot": empty,
                },
                {
                    "variant_name": "world.add_dialog",
                    "visible_predicates": ["City search input is visible"],
                    "representative_screenshot": dialog,
                },
            ],
        }],
    })

    assert captured["screenshots"] == [current, source, empty, dialog]
    assert "source/before" in captured["prompt"]
    assert "world.empty" in captured["prompt"]
    assert "world.add_dialog" in captured["prompt"]


def test_codex_backend_exit_detail_stays_out_of_retry_prompt(tmp_path) -> None:
    screenshot = _png("navy")
    agent = loop.CodexAutonomousAgent(
        "codex-fixture-model", str(tmp_path), timeout=1)
    prompts = []

    def fail_backend(prompt, screenshots):
        prompts.append(prompt)
        raise RuntimeError(
            "codex CLI exited 3: backend-secret-diagnostic")

    agent._invoke = fail_backend
    catalog = [
        item for item in action_tool_catalog()
        if item["name"] == "navigate"
    ]

    result = agent.decide(
        screenshot,
        [],
        app_name="fixture",
        platform="local_html",
        tool_catalog=catalog,
    )

    assert result is None
    assert len(prompts) == 2
    assert "codex CLI exited 3" not in prompts[1]
    assert "backend-secret-diagnostic" not in prompts[1]
    assert "上一份回复没有形成可执行、可解析的本轮判断" in prompts[1]
    debug = [
        json.loads(line)
        for line in (tmp_path / "_autonomous_debug.jsonl").read_text(
            encoding="utf-8").splitlines()
    ]
    assert "codex CLI exited 3" in debug[0]["error"]


def test_qwen_api_agent_handles_main_turn_and_specialist(tmp_path) -> None:
    current = _png("navy")
    turn_response = {
        "screen": {
            "name": "Chats", "summary": "Chat list", "identity": "new",
            "matched_page_name": "", "surface_kind": "page", "regions": [],
            "variant": {
                "name": "default", "identity": "new",
                "visible_predicates": ["Chat list is visible"],
            },
        },
        "reason": "The chat list is a clear new Page and waiting is the current safe step.",
        "previous_action": {
            "outcome": "not_applicable", "summary": "",
        },
        "task_progress": {"status": "working", "summary": "Finding Search"},
        "loop_assessment": {"status": "progress", "summary": ""},
        "previous_tool_review": None,
        "page_update": None,
        "action": {
            "purpose": "navigation",
            "tool_name": "navigate",
            "tool_arguments": {
                "operation": "wait",
            },
        },
    }
    identity_response = {
        "status": "new", "page_name": "Chats", "matched_page_name": "",
            "variant_name": "default", "variant_identity": "new",
            "visible_predicates": ["Chat list is visible"],
        "surface_kind": "page", "summary": "Chat list",
        "supporting_evidence": ["Chats title"], "conflicting_evidence": [],
        "checked_candidates": [], "reason": "Clear initial page",
    }
    transport = _QwenTransport([
        json.dumps(turn_response), json.dumps(identity_response),
    ])
    agent = loop.QwenAutonomousAgent(
        "qwen3.7-plus", str(tmp_path), transport, timeout=10)
    catalog = [item for item in action_tool_catalog()
               if item["name"] == "navigate"]

    turn = agent.decide(
        current,
        [],
        app_name="mingle",
        platform="local_html",
        tool_catalog=catalog,
    )
    identity = agent.resolve_page_identity({
        "current_screenshot": current,
        "suspected_pages": [],
        "proposed_new_name": "Chats",
        "reason": "Register root",
        "registered_pages": [],
        "registered_page_count": 0,
        "previous_tool_feedback": {},
    })

    assert turn is not None and turn.decision.tool_name == "navigate"
    assert identity["status"] == "new"
    assert transport.model_version == "qwen3.7-plus"
    assert len(transport.calls) == 2
    main_prompt = transport.calls[0]["prompt"]
    system_prompt = transport.calls[0]["system_prompt"]
    assert "本轮 JSON Schema" in system_prompt
    assert "你是 GUI 应用自主遍历主 Agent" in system_prompt
    assert "主 Agent 可用工具的固定语义定义" in system_prompt
    assert '"gesture"' not in system_prompt
    assert "你是 GUI 应用自主遍历主 Agent" not in main_prompt
    assert "本轮动态可用工具目录" not in main_prompt
    assert '"navigate"' in system_prompt
    catalog_text, schema_text = system_prompt.split("本轮 JSON Schema", 1)
    assert '"input_schema"' not in catalog_text
    assert '"frame_id"' not in schema_text
    assert transport.calls[0]["images"] == [current]
    assert {item["backend"] for item in agent.backend_runs} == {"qwen_api"}
    debug = [json.loads(line) for line in (
        tmp_path / "_autonomous_debug.jsonl").read_text(
            encoding="utf-8").splitlines()]
    assert debug[0]["backend"]["prompt_tokens"] == 123
    assert debug[0]["system_prompt"] == system_prompt
    assert debug[1]["role"] == "autonomous_page_identity_specialist"


def test_qwen_main_turn_uses_page_then_variant_identity_schemas(tmp_path) -> None:
    page_response = {
        "screen": {"name": "Timer", "identity": "known"},
        "reason": "The Timer navigation and duration setup identify the Page.",
        "action": None,
    }
    variant_response = {
        "screen": {"variant": {
            "name": "initial_state",
            "identity": "known",
            "visible_predicates": ["Select Duration is visible."],
        }},
        "reason": "The registered Timer initial state matches.",
        "action": None,
    }
    transport = _QwenTransport([
        json.dumps(page_response), json.dumps(variant_response),
    ])
    agent = loop.QwenAutonomousAgent(
        "qwen3.7-plus", str(tmp_path), transport, timeout=10)
    catalog = [
        item for item in available_tool_catalog(pending_identity=False)
        if item["name"] == "page_identity"
    ]

    page_turn = agent.decide(
        _png("cyan"),
        [],
        app_name="clock",
        platform="local_html",
        exploration_map={
            "pages": [
                {"name": "Alarms", "summary": "Alarm list"},
                {"name": "Timer", "summary": "Timer setup"},
            ],
            "task": {"type": "explore_entry", "phase": "identify_page"},
        },
        tool_catalog=catalog,
    )
    variant_turn = agent.decide(
        _png("cyan"),
        [],
        app_name="clock",
        platform="local_html",
        exploration_map={
            "selected_page": {"name": "Timer", "identity": "known"},
            "variant_candidates": [{
                "name": "initial_state",
                "visible_predicates": ["Select Duration is visible."],
            }],
            "task": {
                "type": "explore_entry", "phase": "identify_variant",
            },
        },
        tool_catalog=catalog,
    )

    assert page_turn is not None
    assert page_turn.registration.matched_page_name == "Timer"
    assert page_turn.registration.variant_name == ""
    assert variant_turn is not None
    assert variant_turn.screen_name == "Timer"
    assert variant_turn.registration.variant_name == "initial_state"
    assert "本轮不判断页面状态版本" in transport.calls[0]["prompt"]
    assert "当前页面已经确认" in transport.calls[1]["prompt"]
    assert "实质页面状态版本" in transport.calls[1]["prompt"]
    assert transport.calls[0]["system_prompt"].startswith(AUTONOMOUS_PROMPT)
    assert transport.calls[1]["system_prompt"].startswith(AUTONOMOUS_PROMPT)


def test_page_stage_normalizes_one_unique_variant_name_to_its_owner(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.protocol_map.observe(
        name="Alarm", summary="Alarm list", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], variant_name="Collapsed",
        variant_identity="new", commit_regions=False,
    )
    runtime.protocol_map.observe(
        name="Alarm", summary="Alarm list", identity="known",
        matched_page_name="Alarm", surface_kind="page", regions=(),
        screenshot=_png("blue"), variant_name="Alarm - Expanded Card",
        variant_identity="new", commit_regions=False,
    )
    turn = _turn(
        "Alarm - Expanded Card", action="NONE", identity="known",
        variant_identity="uncertain",
    )
    history = []

    normalized = loop._normalize_variant_named_page(
        runtime, turn, history, identity_stage="page")

    assert normalized.screen_name == "Alarm"
    assert normalized.registration.matched_page_name == "Alarm"
    assert history[-1]["outcome"] == "variant_name_mapped_to_owner_page"
    assert history[-1]["reported_name"] == "Alarm - Expanded Card"

    runtime.protocol_map.observe(
        name="Schedules", summary="Schedules", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=_png("green"), variant_name="Alarm - Expanded Card",
        variant_identity="new", commit_regions=False,
    )
    ambiguous_history = []
    ambiguous = loop._normalize_variant_named_page(
        runtime, turn, ambiguous_history, identity_stage="page")

    assert ambiguous == turn
    assert ambiguous_history == []


def test_variant_named_page_does_not_block_pending_action_settlement(
    tmp_path,
) -> None:
    before = {"screenshot": _png("blue")}
    after = {"screenshot": _png("gray")}
    frame_id = loop.screenshot_frame_id(before["screenshot"])
    runtime, env, _agent = _runtime(
        tmp_path, before, [], [after], max_actions=1)
    runtime.protocol_map.observe(
        name="Alarm", summary="Alarm list", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=before["screenshot"],
        variant_name="Alarm - Expanded Card", variant_identity="new",
        commit_regions=False,
    )
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Alarm", region_name="Alarm list", frame_id=frame_id,
        observations=[{"target": "8:30 alarm enabled switch"}],
    ).added[0]
    _complete_fixture_survey(
        runtime, "Alarm", before["screenshot"],
        region_names=("Main", "Alarm list"))
    runtime.click_reviewer = lambda _request: {
        "decision": "approve",
        "observed_target": "8:30 alarm enabled switch",
        "point_matches_target": True,
        "target_matches_request": True,
        "risk": "safe",
        "reason": "The point is on the requested visible switch.",
    }
    runtime.decision_agent.turns = iter([
        _turn(
            "Alarm", action="CALL_TOOL", identity="known",
            variant_name="Alarm - Expanded Card", variant_identity="known",
            target="8:30 alarm enabled switch", tool_name="click",
            tool_arguments={
                "target": "8:30 alarm enabled switch",
                "entry_id": entry_id, "point_1000": [850, 300],
            },
        ),
        _turn(
            "Alarm - Expanded Card", action="NONE", identity="known",
            variant_name="Alarm - Expanded Card", variant_identity="known",
            outcome="changed", matches_intent=True,
            previous_reason="The enabled switch changed from on to off.",
        ),
    ])

    graph = loop.run_autonomous_traversal(runtime, before)

    assert graph.stop_reason == "max_actions"
    assert len(env.actions) == 1
    entry = runtime.entry_ledger.get(entry_id)
    assert entry.status.value == "verified"
    assert entry.task_eligible is False
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(
            encoding="utf-8"))
    assert any(
        item.get("outcome") == "variant_name_mapped_to_owner_page"
        for item in trace["history"]
    )
    assert not any(
        item.get("outcome") == "pending_action_assessment_limit"
        for item in trace["history"]
    )


def test_qwen_record_regions_uses_fixed_reviewed_identity(tmp_path) -> None:
    response = {
        "reason": "The corrected proposal includes the add control.",
        "page_update": {"regions": []},
        "action": None,
    }
    transport = _QwenTransport([json.dumps(response)])
    agent = loop.QwenAutonomousAgent(
        "qwen3.7-plus", str(tmp_path), transport, timeout=10)
    catalog = [
        item for item in available_tool_catalog(pending_identity=False)
        if item["name"] == "page_identity"
    ]

    turn = agent.decide(
        _png("white"),
        [],
        app_name="clocks",
        platform="Linux",
        exploration_map={
            "current_page": "World Clock Empty State",
            "current_variant": "World Clock Empty State",
            "task": {"type": "survey_page", "phase": "record_regions"},
        },
        tool_catalog=catalog,
    )

    assert turn is not None
    assert turn.screen_name == "World Clock Empty State"
    assert turn.registration.variant_name == "World Clock Empty State"
    schema_text = transport.calls[0]["system_prompt"].split(
        "本轮 JSON Schema", 1)[1]
    assert '"screen"' not in schema_text


def test_qwen_region_reviewer_receives_reason_partition_and_screenshot(
    tmp_path,
) -> None:
    screenshot = _png("white")
    response = {
        "regions": [{
            "name": "World Clock List Area",
            "summary": "The visible world-clock content.",
        }],
        "revisions": [{
            "old_region": "World Clock List Area",
            "decision": "keep",
            "reason": "The content Region remains stable.",
        }],
        "reason": "The visible navigation group is missing.",
    }
    transport = _QwenTransport([json.dumps(response)])
    agent = loop.QwenAutonomousAgent(
        "qwen3.7-plus", str(tmp_path), transport, timeout=10)

    result = agent.review_region_proposal({
        "current_screenshot": screenshot,
        "page_name": "World",
        "main_agent_reason": (
            "Top navigation is global switching and will not be recorded."
        ),
        "existing_regions": [{
            "name": "World Clock List Area",
            "summary": "The visible world-clock content.",
            "coverage_complete": False,
            "acceptance_status": "partial",
            "last_incomplete_frame_id": "internal-frame-id",
        }],
        "proposed_entries": [{
            "region_name": "World Clock List Area",
            "target": "Add World Clock button",
        }],
        "equivalence_candidates": [],
        "review_attempt": 2,
        "review_attempt_limit": 3,
        "previous_review": {
            "regions": [{
                "name": "Top Navigation Bar",
                "summary": "Visible navigation.",
            }],
            "revisions": [{
                "old_region": "World Clock List Area",
                "decision": "merge",
                "merged_into": "Top Navigation Bar",
                "reason": "The old Region belongs to navigation.",
            }],
            "reason": "The first proposal omitted the visible navigation.",
        },
    })

    assert result == response
    assert transport.calls[0]["images"][0] == screenshot
    assert len(transport.calls[0]["images"]) == 1
    prompt = _qwen_call_prompt(transport.calls[0])
    assert "bbox_overlay_legend" not in prompt
    assert "bbox_1000" not in prompt
    assert "main_agent_reason" in prompt
    assert "Top navigation is global switching" in prompt
    assert "World Clock List Area" in prompt
    assert "Top Navigation Bar" in prompt
    assert "previous_proposed_regions" not in prompt
    assert "omitted_regions" not in prompt
    assert "proposed_entries" not in prompt
    assert "Add World Clock button" not in prompt
    assert '"issues"' not in prompt
    assert '"regions"' in prompt
    assert '"revisions"' in prompt
    assert "第 2 次复核，最多 3 次" in prompt
    assert '"review_attempt"' not in prompt
    assert '"review_attempt_limit"' not in prompt
    assert '"previous_review"' not in prompt
    assert "The first proposal omitted the visible navigation." in prompt
    assert "不要枚举区域中的按钮、Entry、候选数量、代表操作" in prompt
    assert "acceptance_status" not in prompt
    assert "last_incomplete_frame_id" not in prompt
    debug = [json.loads(line) for line in (
        tmp_path / "_autonomous_debug.jsonl").read_text(
            encoding="utf-8").splitlines()]
    assert debug[0]["role"] == "autonomous_region_reviewer_specialist"


def test_qwen_cross_page_region_reviewer_receives_regions_without_entries(
    tmp_path,
) -> None:
    current = _png("white")
    known = _png("black")
    response = {
        "shared_groups": [{
            "members": ["N1", "K1"],
            "reason": "Both own the same stable primary navigation.",
        }],
        "separate_groups": [],
        "unmatched": [],
        "reason": "The navigation is reusable across both Pages.",
    }
    transport = _QwenTransport([json.dumps(response)])
    agent = loop.QwenAutonomousAgent(
        "qwen3.7-plus", str(tmp_path), transport, timeout=10)

    result = agent.review_cross_page_regions({
        "current_screenshot": current,
        "candidate_screenshots": [known],
        "occurrences": [
            {
                "occurrence_id": "N1", "page": "Search",
                "region": "Main navigation",
                "summary": "Switches main application functions.",
                "image": "图1",
            },
            {
                "occurrence_id": "K1", "page": "Home",
                "region": "Primary navigation",
                "summary": "Switches main application functions.",
                "image": "图2",
            },
        ],
        "image_order": ["图1：Search", "图2：Home"],
        "entries": [{"target": "must not be projected"}],
    })

    assert result == response
    assert transport.calls[0]["images"] == [current, known]
    prompt = _qwen_call_prompt(transport.calls[0])
    assert "Main navigation" in prompt
    assert "Primary navigation" in prompt
    assert "must not be projected" not in prompt
    assert "按钮或入口清单" in prompt
    assert "相同位置、形状、主题、布局" in prompt
    assert "每个输入 occurrence_id 必须且只能出现一次" in prompt


def test_qwen_entry_reviewer_is_stateless_and_checks_main_reason(tmp_path) -> None:
    screenshot = _png("white")
    response = {
        "independent_entries": [{
            "region_name": "Top navigation",
            "target": "Timer tab",
        }],
        "deferred_entries": [],
        "deferred_regions": [],
        "reason_consistent": False,
        "reason": "The window buttons are not application functions.",
    }
    transport = _QwenTransport([json.dumps(response)])
    agent = loop.QwenAutonomousAgent(
        "qwen3.7-plus", str(tmp_path), transport, timeout=10)

    result = agent.review_entry_candidates({
        "current_screenshot": screenshot,
        "page_name": "World",
        "main_agent_reason": "Every toolbar control is an entry.",
        "regions": [{
            "name": "Top navigation",
            "coverage_complete": False,
            "acceptance_status": "partial",
            "last_incomplete_frame_id": "internal-frame-id",
        }],
        "candidates": [
            {"region_name": "Top navigation", "target": "Timer tab"},
            {"region_name": "Top navigation", "target": "maximize button"},
        ],
        "known_entries": [],
        "previous_rejection": {
            "code": "entry_review_invalid",
            "reason": "The prior response selected a non-candidate pair.",
            "correction": "Select only exact pending candidate pairs.",
        },
    })

    assert result == response
    assert transport.calls[0]["images"][0] == screenshot
    assert len(transport.calls[0]["images"]) == 1
    prompt = _qwen_call_prompt(transport.calls[0])
    assert "bbox_overlay_legend" not in prompt
    assert "bbox_1000" not in prompt
    assert "main_agent_reason" in prompt
    assert "Every toolbar control is an entry" in prompt
    assert "主要功能" in prompt
    assert "截图中明确漏报的项" in prompt
    assert "上一份 Reviewer 回复没有被框架采用" in prompt
    assert "previous_rejection" not in prompt
    assert "entry_review_invalid" not in prompt
    assert "Select only exact pending candidate pairs." in prompt
    assert "The prior response selected a non-candidate pair." in prompt
    assert "覆盖判断只依据最新截图" in prompt
    assert "acceptance_status" not in prompt
    assert "last_incomplete_frame_id" not in prompt
    debug = [json.loads(line) for line in (
        tmp_path / "_autonomous_debug.jsonl").read_text(
            encoding="utf-8").splitlines()]
    assert debug[0]["role"] == "autonomous_entry_reviewer_specialist"


def test_qwen_interruption_handler_receives_task_observation_and_screenshot(
    tmp_path,
) -> None:
    screenshot = _png("white")
    response = {
        "surface_is_temporary": True,
        "blocks_current_target": True,
        "strategy": "click",
        "target": "Close button on Software Updates notification card",
        "point_1000": [950, 60],
        "target_is_close_control": True,
        "reason": "The directly visible close button belongs to the blocker.",
    }
    transport = _QwenTransport([json.dumps(response)])
    agent = loop.QwenAutonomousAgent(
        "qwen3.7-plus", str(tmp_path), transport, timeout=10)

    result = agent.review_interruption({
        "current_screenshot": screenshot,
        "platform": "desktop",
        "current_page": "World",
        "current_task": {"task_type": "survey_page", "page_name": "World"},
        "main_agent_observation": {
            "suspected_surface": "Software Updates notification card",
            "obstruction_reason": "It covers the Alarms tab.",
        },
        "handling_round": 1,
        "handling_round_limit": 3,
    })

    assert result == response
    assert transport.calls[0]["images"] == [screenshot]
    prompt = _qwen_call_prompt(transport.calls[0])
    assert "current_assignment" in prompt
    assert "调查当前页面的 Region 与主要功能入口" in prompt
    assert "main_agent_observation" in prompt
    assert "It covers the Alarms tab" in prompt
    assert "第 1 次判断，最多允许 3 次" in prompt
    assert '"current_task"' not in prompt
    assert '"handling_round"' not in prompt
    assert '"handling_round_limit"' not in prompt
    assert "ignore" in prompt and "click" in prompt
    assert "hover" not in prompt
    debug = [json.loads(line) for line in (
        tmp_path / "_autonomous_debug.jsonl").read_text(
            encoding="utf-8").splitlines()]
    assert debug[0]["role"] == "autonomous_interruption_handler_specialist"


def test_click_reviewer_prompt_contains_only_visible_owner_evidence(
    tmp_path,
) -> None:
    stream = io.BytesIO()
    Image.new("RGB", (600, 400), "navy").save(stream, format="PNG")
    current = stream.getvalue()
    response = {
        "decision": "reject",
        "observed_target": "Done",
        "point_matches_target": True,
        "target_matches_request": True,
        "risk": "unsafe",
        "reason": "This would save the configured schedule.",
    }
    transport = _QwenTransport([json.dumps(response)])
    agent = loop.QwenAutonomousAgent(
        "qwen3.7-plus", str(tmp_path), transport, timeout=10)

    result = agent.review_click({
        "current_screenshot": current,
        "target": "Done",
        "point_1000": [800, 900],
        "operation": "click",
        "current_task": {
            "task_type": "survey_page",
            "page_name": "Setup",
            "region_name": "Wizard Footer",
            "target": "Review the visible setup controls",
            "goal": "survey_page",
            "phase": "survey_region",
        },
        "agent_reason": (
            "The visible Done button would save the configured schedule."
        ),
        "requested_entry": {
            "page_name": "Setup",
            "region_name": "Wizard Footer", "target": "Done",
            "control_type": "button", "current_value": "enabled",
        },
    })

    assert result["decision"] == "reject"
    prompt = _qwen_call_prompt(transport.calls[0])
    assert "复核主 Agent 提出的精确界面动作" in prompt
    assert '"point_1000"' not in prompt
    assert '"region_name": "Wizard Footer"' in prompt
    assert '"agent_reason": "The visible Done button' in prompt
    assert '"current_task": {' in prompt
    assert "声明的目标是可见控件" in prompt
    assert "observed_target" in prompt
    images = transport.calls[0]["images"]
    assert images[0] == current
    zoom = Image.open(io.BytesIO(images[1])).convert("RGB")
    assert zoom.size == (256, 256)
    assert zoom.size[0] < 600 and zoom.size[1] < 400
    assert zoom.getpixel((110, 110)) == (255, 0, 255)
    assert '"review_mode": "proposed_action"' in prompt
    assert "四个洋红角标" in prompt
    assert "唯一拟点击点" in prompt


def test_click_reviewer_receives_exact_input_text_without_point_in_prompt(
    tmp_path,
) -> None:
    current = _png("white")
    response = {
        "decision": "approve",
        "observed_target": "City search field in Search panel",
        "point_matches_target": True,
        "target_matches_request": True,
        "risk": "safe",
        "reason": "This is a visible non-sensitive query field.",
    }
    transport = _QwenTransport([json.dumps(response)])
    agent = loop.QwenAutonomousAgent(
        "qwen3.7-plus", str(tmp_path), transport, timeout=10)

    result = agent.review_click({
        "current_screenshot": current,
        "target": "City search field in Search panel",
        "point_1000": [500, 500],
        "operation": "input_text",
        "requested_text": "Oslo",
    })

    assert result["decision"] == "approve"
    prompt = _qwen_call_prompt(transport.calls[0])
    assert '"operation": "input_text"' in prompt
    assert '"requested_text": "Oslo"' in prompt
    assert '"point_1000"' not in prompt
    assert "操作类型是否适合该控件" in prompt
    assert "动作在当前任务中的作用是否一致" in prompt


def test_click_reviewer_without_reason_is_not_accepted(tmp_path) -> None:
    screen = {"screenshot": _png("navy")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [], [])
    runtime.exploration_task = ExplorationTask(
        task_type="survey_page",
        task_id="survey:Workspace",
        page_name="Workspace",
        region_name="Main Canvas",
        target="Inspect the main canvas",
        goal="survey_page",
        phase="survey_region",
    )
    captured = {}

    def reviewer(request):
        captured.update(request)
        return {
            "decision": "approve",
            "point_matches_target": True,
            "target_matches_request": True,
            "risk": "safe",
            "reason": "",
        }

    runtime.click_reviewer = reviewer
    decision = loop.AutonomousDecision(
        action="CALL_TOOL",
        target="Open workspace",
        point_1000=[500, 500],
        reason="Open the assigned workspace entry.",
        direction="",
        tool_name="click",
        tool_arguments={"entry_id": ""},
    )

    approved, review = loop._review_click(
        runtime, screen["screenshot"], decision)

    assert approved is False
    assert review["decision"] == "uncertain"
    assert review["reason"] == "click reviewer returned no non-empty reason"
    assert captured["target"] == "Open workspace"
    assert captured["agent_reason"] == "Open the assigned workspace entry."
    assert captured["current_task"] == {
        "task_type": "survey_page",
        "page_name": "Workspace",
        "region_name": "Main Canvas",
        "target": "Inspect the main canvas",
        "goal": "survey_page",
        "phase": "survey_region",
    }
    assert set(captured) == {
        "current_screenshot", "target", "purpose", "agent_reason",
        "current_task", "point_1000", "operation",
    }


def test_parse_turn_accepts_tool_call_envelope() -> None:
    payload = {
        "screen": {
            "name": "Chats", "summary": "Chat list is visible",
            "identity": "new", "matched_page_name": "",
            "surface_kind": "page",
            "variant": {
                "name": "default",
                "identity": "new",
                "visible_predicates": ["Chat list is visible"],
            },
        },
        "reason": "Chats is a new Page and Weekend Plan is the selected visible entry.",
        "previous_action": {
            "outcome": "not_applicable",
            "summary": "No previous action",
            "matches_intent": True,
        },
        "task_progress": {
            "status": "working", "summary": "Open one conversation",
        },
        "loop_assessment": {"status": "progress", "summary": "First action"},
        "previous_tool_review": None,
        "page_update": None,
        "action": {
            "purpose": "entry_attempt",
            "tool_name": "click", "tool_arguments": {
                "target": "Weekend Plan",
                "point_1000": [420, 315],
                "entry_id": "ae1",
            },
        },
    }

    turn, error = parse_turn(payload, has_previous=False)

    assert error == ""
    assert turn is not None
    assert turn.decision.target == "Weekend Plan"
    assert turn.decision.tool_name == "click"
    assert turn.decision.reason == payload["reason"]
    assert turn.decision.tool_arguments["point_1000"] == [420, 315]
    assert "exploration_memory" not in RESPONSE_SCHEMA["properties"]
    assert not hasattr(turn, "screen_summary")
    assert not hasattr(turn.decision, "safety")
    assert "summary" not in loop.ObservedScene.__dataclass_fields__
    assert not hasattr(turn.registration, "regions")
    assert not hasattr(turn.decision, "expected_result")
    assert not hasattr(turn.registration, "surface_kind")
    assert "regions" not in RESPONSE_SCHEMA["properties"]["screen"][
        "properties"]

    payload["previous_tool_review"] = {
        "decision": "accept", "reason": "The proposal matches.",
    }
    reviewed, error = parse_turn(
        payload, has_previous=False, requires_tool_review=True)
    assert error == ""
    assert reviewed is not None
    assert reviewed.previous_tool_review == PreviousToolReview(
        "accept", "The proposal matches.")

    payload["action"] = {
        "purpose": "locating",
        "tool_name": "page_identity",
        "tool_arguments": {
            "suspected_pages": [], "proposed_new_name": "Home",
            "reason": "Check the page.",
        },
    }
    hidden, error = parse_turn(
        payload,
        has_previous=False,
        requires_tool_review=True,
        available_tools=["show_map"],
    )
    assert hidden is None
    assert "exposed" in error

    payload.pop("previous_tool_review")
    missing, error = parse_turn(
        payload, has_previous=False, requires_tool_review=True)
    assert missing is None
    assert "previous_tool_review" in error


def test_state_specific_schema_and_parser_accept_minimal_main_turn() -> None:
    catalog = [{
        "name": "navigate",
        "description": "wait",
        "input_schema": {
            "type": "object", "properties": {}, "required": [],
            "additionalProperties": False,
        },
    }]
    schema = response_schema_for_tools(catalog)

    assert schema["required"] == [
        "screen", "reason", "task_strategy", "action",
    ]
    assert "previous_action" not in schema["properties"]
    assert "previous_tool_review" not in schema["properties"]
    assert "task_progress" not in schema["properties"]
    assert "page_update" in schema["properties"]
    assert "loop_assessment" not in schema["properties"]

    turn, error = parse_turn({
        "screen": {
            "name": "Settings", "identity": "new",
            "variant": {
                "name": "default", "identity": "new",
                "visible_predicates": ["Settings content is visible"],
            },
        },
        "reason": "Settings remains the current Page and no GUI action is needed.",
        "task_strategy": "Wait for the framework to dispatch the next task.",
        "action": None,
    }, has_previous=False)

    assert error == ""
    assert turn is not None
    assert turn.task_strategy == (
        "Wait for the framework to dispatch the next task.")
    assert turn.decision.action == "NONE"
    assert turn.previous.outcome == "not_applicable"
    assert not hasattr(turn.previous, "temporary_state")
    assert not hasattr(turn, "task_progress")
    assert not hasattr(turn, "loop_assessment")
    assert turn.previous_tool_review is None
    assert turn.page_update is None

    pending_schema = response_schema_for_tools(
        catalog, has_previous=True, requires_tool_review=True)
    assert pending_schema["required"] == [
        "screen", "reason", "task_strategy", "action",
        "previous_action", "previous_tool_review",
    ]
    assert pending_schema["properties"]["previous_tool_review"]["anyOf"][0][
        "required"
    ] == ["decision", "reason"]

    previous_schema = pending_schema["properties"]["previous_action"]
    assert previous_schema["required"] == [
        "outcome", "reason", "matches_intent", "failure_kind",
        "business_effect",
    ]
    assert "temporary_state" not in previous_schema["properties"]
    effect_schema = previous_schema["properties"]["business_effect"]
    assert effect_schema["anyOf"][1] == {"type": "null"}
    assert effect_schema["anyOf"][0]["required"] == [
        "effect_kind", "region_name", "capability_name", "fact",
        "before_value", "after_value", "parameter_bindings",
    ]
    assert effect_schema["anyOf"][0]["properties"]["effect_kind"][
        "enum"] == list(BUSINESS_EFFECT_KINDS)
    assert effect_schema["anyOf"][0]["properties"]["before_value"] == {
        "type": "string",
    }
    assert effect_schema["anyOf"][0]["properties"]["after_value"] == {
        "type": "string",
    }
    assert effect_schema["anyOf"][0]["properties"][
        "same_operation_entry_ids"]["items"] == {"type": "string"}
    assert "same_operation_reason" in effect_schema["anyOf"][0]["properties"]


def test_page_and_variant_identity_stages_use_disjoint_screen_fields() -> None:
    catalog = [{
        "name": "page_identity",
        "description": "resolve identity",
        "input_schema": {
            "type": "object", "properties": {}, "required": [],
            "additionalProperties": False,
        },
    }]
    page_schema = response_schema_for_tools(
        catalog, identity_stage="page")
    assert page_schema["properties"]["screen"]["required"] == [
        "name", "identity",
    ]
    assert "variant" not in page_schema["properties"]["screen"]["properties"]
    assert "page_update" not in page_schema["properties"]

    page_turn, page_error = parse_turn({
        "screen": {"name": "Timer", "identity": "known"},
        "reason": "The Timer navigation and duration surface identify the Page.",
        "action": None,
    }, has_previous=False, identity_stage="page")
    assert page_error == ""
    assert page_turn is not None
    assert page_turn.registration.matched_page_name == "Timer"
    assert page_turn.registration.variant_name == ""

    variant_schema = response_schema_for_tools(
        catalog, identity_stage="variant")
    assert variant_schema["properties"]["screen"]["required"] == ["variant"]
    assert "name" not in variant_schema["properties"]["screen"]["properties"]

    variant_turn, variant_error = parse_turn({
        "screen": {"variant": {
            "name": "initial_state",
            "identity": "known",
            "visible_predicates": ["Select Duration is visible."],
        }},
        "reason": "The registered Timer initial state matches.",
        "action": None,
    },
        has_previous=False,
        identity_stage="variant",
        selected_page_name="Timer",
        selected_page_identity="known",
    )
    assert variant_error == ""
    assert variant_turn is not None
    assert variant_turn.screen_name == "Timer"
    assert variant_turn.registration.matched_page_name == "Timer"
    assert variant_turn.registration.variant_name == "initial_state"


def test_ordinary_stage_omits_and_injects_reviewed_screen_identity() -> None:
    catalog = [{
        "name": "page_identity",
        "description": "resolve identity",
        "input_schema": {
            "type": "object", "properties": {}, "required": [],
            "additionalProperties": False,
        },
    }]
    schema = response_schema_for_tools(catalog, fixed_identity=True)

    assert "screen" not in schema["properties"]
    assert schema["required"] == ["reason", "task_strategy", "action"]

    turn, error = parse_turn({
        "reason": "The corrected Region proposal includes every control.",
        "task_strategy": "Submit the corrected Region proposal without acting.",
        "page_update": {"regions": []},
        "action": None,
    },
        has_previous=False,
        fixed_page_name="World Clock Empty State",
        fixed_variant_name="World Clock Empty State",
    )
    assert error == ""
    assert turn is not None
    assert turn.task_strategy == (
        "Submit the corrected Region proposal without acting.")
    assert turn.screen_name == "World Clock Empty State"
    assert turn.registration.matched_page_name == "World Clock Empty State"
    assert turn.registration.variant_name == "World Clock Empty State"
    assert turn.registration.variant_identity == "known"

    repeated, repeated_error = parse_turn({
        "screen": {
            "name": "World Clock Empty State", "identity": "known",
            "variant": {
                "name": "Default Empty View", "identity": "known",
                "visible_predicates": [],
            },
        },
        "reason": "This repeats the already reviewed identity.",
        "action": None,
    },
        has_previous=False,
        fixed_page_name="World Clock Empty State",
        fixed_variant_name="World Clock Empty State",
    )
    assert repeated is None
    assert "screen is not accepted" in repeated_error


def test_entry_review_turn_uses_exhaustive_independent_entry_contract() -> None:
    catalog = [{
        "name": "navigate",
        "description": "wait",
        "input_schema": {
            "type": "object", "properties": {}, "required": [],
            "additionalProperties": False,
        },
    }]
    schema = response_schema_for_tools(
        catalog, requires_entry_review=True)

    assert schema["required"] == [
        "screen", "reason", "task_strategy", "action", "entry_review",
    ]
    assert schema["properties"]["action"] == {"type": "null"}
    assert "page_update" not in schema["properties"]
    assert schema["properties"]["entry_review"]["anyOf"][0]["required"] == [
        "independent_entries", "record_only_entries", "non_task_entries",
        "deferred_entries", "deferred_regions",
    ]
    review_properties = schema["properties"]["entry_review"]["anyOf"][0][
        "properties"
    ]
    independent_description = review_properties["independent_entries"]["description"]
    deferred_description = review_properties["deferred_entries"]["description"]
    non_task_description = review_properties["non_task_entries"]["description"]
    record_only_description = review_properties[
        "record_only_entries"]["description"]
    assert "当前可见、安全、不同质" in independent_description
    assert "候选漏报的操作" in independent_description
    assert "record_only_entries" in independent_description
    assert "增减方向不同不算不同质" in independent_description
    independent_item = review_properties["independent_entries"]["items"]
    assert independent_item["required"] == [
        "region_name", "target", "operation",
    ]
    assert review_properties["non_task_entries"]["items"]["required"] == [
        "region_name", "operation", "target",
    ]
    assert "obscured, cropped, or visually unclear" in deferred_description
    assert "until a prerequisite is satisfied" in deferred_description
    assert "Every original candidate" in non_task_description
    assert "temporarily unavailable" in non_task_description
    assert "command-relevant operations" in record_only_description
    assert "not verified effects or routes" in record_only_description
    assert "missed_entries" not in review_properties

    payload = {
        "screen": {
            "name": "Timer", "identity": "known",
            "variant": {
                "name": "default", "identity": "known",
                "visible_predicates": ["Timer controls are visible"],
            },
        },
        "reason": (
            "The preset and value controls only configure the current Timer "
            "function, so none opens a new functional surface."
        ),
        "entry_review": {
            "independent_entries": [],
            "record_only_entries": [],
            "non_task_entries": [],
            "deferred_entries": [],
            "deferred_regions": [],
        },
        "action": None,
    }
    turn, error = parse_turn(
        payload, has_previous=False, requires_entry_review=True)

    assert error == ""
    assert turn is not None
    assert turn.entry_review == loop.EntryReview(
        independent_entries=[], non_task_entries=[], deferred_entries=[],
        deferred_regions=[])
    assert turn.page_update is None
    assert turn.decision.action == "NONE"
    assert turn.registration.matched_page_name == "Timer"


def test_complete_region_without_candidates_waits_for_entry_coverage_audit(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    update = loop.PageUpdate(
        page_name=page_name,
        regions=[{
            "name": "Timer controls",
            "bbox_1000": [0, 0, 1000, 1000],
            "coverage_complete": True,
        }],
    )
    history = []

    review_regions = loop._entry_review_region_names(runtime, update)
    issue = loop._stage_main_agent_page_update(
        runtime,
        update,
        scene,
        screenshot,
        history,
        review_region_names=review_regions,
    )

    assert issue == ""
    assert review_regions == ["Timer controls"]
    assert runtime.pending_entry_review["candidates"] == []
    assert runtime.pending_entry_review[
        "coverage_audit_regions"] == ["Timer controls"]
    region = loop._region_state(runtime, page_name).region("Timer controls")
    assert region is not None and region["coverage_complete"] is False

    issue = loop._apply_entry_review(
        runtime, loop.EntryReview(), scene, screenshot, history,
        reviewer_reason="The visible Region contains no independent entry.",
        reason_consistent=True,
    )

    assert issue == ""
    region = loop._region_state(runtime, page_name).region("Timer controls")
    assert region is not None and region["coverage_complete"] is True
    audit = runtime.entry_review_audits["timer"]["timer controls"]
    assert audit["status"] == "complete"
    assert audit["coverage_basis"] == "visual_entry_reviewer"
    assert not any(
        "entry-coverage audit" in gap
        for gap in loop._completion_gaps(runtime)
    )


def test_repeated_formal_entry_does_not_reopen_incomplete_region_review(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    _bind_incomplete_page(runtime, "Alarm sound", screenshot)
    runtime.entry_ledger.record_agent_update(
        page_name="Alarm sound",
        region_name="Main",
        frame_id=loop.screenshot_frame_id(screenshot),
        observations=[{"target": "Argon"}],
    )
    repeated = loop.PageUpdate(
        page_name="Alarm sound",
        regions=[{"name": "Main", "coverage_complete": False}],
        new_entries=[{"region_name": "Main", "target": "Argon"}],
    )

    assert loop._entry_review_region_names(runtime, repeated) == []

    changed_type = replace(
        repeated,
        new_entries=[{
            "region_name": "Main",
            "target": "Argon",
            "control_type": "input",
        }],
    )
    assert loop._entry_review_region_names(runtime, changed_type) == ["Main"]

    new_target = replace(
        repeated,
        new_entries=[{"region_name": "Main", "target": "Barium"}],
    )
    assert loop._entry_review_region_names(runtime, new_target) == ["Main"]


def test_completed_entry_audit_clears_stale_unknown_owner_correction(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clock", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Header Bar",
                "summary": "Application navigation and add action",
                "bbox_1000": [50, 50, 950, 180],
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Header Bar",
                "target": "Add button (+)",
            }],
        ),
        scene,
        screenshot,
        history,
    ) == ""

    page_key = loop._page_key(page_name)
    stale_key = "entry:header bar:+ button"
    runtime.page_update_corrections[page_key] = {
        stale_key: {
            "kind": "new_entry",
            "region_name": "Header Bar",
            "target": "+ button",
            "field": "region_name",
            "error_code": "unknown_region_reference",
        },
    }

    assert loop._apply_entry_review(
        runtime,
        loop.EntryReview(independent_entries=[{
            "region_name": "Header Bar",
            "target": "Add button (+)",
        }]),
        scene,
        screenshot,
        history,
        reviewer_reason="The add control is a visible application entry.",
        reason_consistent=True,
    ) == ""

    assert page_key not in runtime.page_update_corrections
    assert [entry.target for entry in runtime.entry_ledger.entries] == [
        "Add button (+)",
    ]
    region = loop._region_state(runtime, page_name).region("Header Bar")
    assert region is not None and region["coverage_complete"] is True
    assert runtime.entry_review_audits[page_key]["header bar"]["status"] == (
        "complete"
    )
    assert _page_survey_need(runtime, page_name) == ("", "", "")


def test_entry_review_resume_keeps_exact_material_variant_state(
    tmp_path, monkeypatch,
) -> None:
    empty = _png("white")
    dialog = _png("blue")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": empty}, [])
    scenes = []
    for index, (variant_name, screenshot) in enumerate([
        ("world.empty", empty),
        ("world.add_dialog", dialog),
    ]):
        identity = "new" if index == 0 else "known"
        page_name, issue = runtime.protocol_map.observe(
            name="World",
            summary="World clock",
            identity=identity,
            matched_page_name="World" if index else "",
            surface_kind="dialog" if index else "page",
            regions=(),
            screenshot=screenshot,
            variant_name=variant_name,
            variant_identity="new",
            visible_predicates=[f"{variant_name} is visible"],
            commit_regions=False,
        )
        assert issue == ""
        scenes.append(loop._register_scene(
            runtime,
            screenshot,
            _turn(
                "World",
                action="NONE",
                identity=identity,
                variant_name=variant_name,
                variant_identity="new",
                visible_predicates=[f"{variant_name} is visible"],
            ),
            page_name,
        ))

    runtime.pending_entry_review = {
        "page_name": "World",
        "variant_name": scenes[1].variant_name,
        "state_id": scenes[1].state_id,
        "frame_id": loop.screenshot_frame_id(dialog),
        "regions": [],
        "candidates": [],
        "coverage_audit_regions": [],
    }
    loop._checkpoint(runtime, [])
    graph_path = str(tmp_path / "graph.json")

    resumed, _env, _agent = _runtime(
        tmp_path, {"screenshot": dialog}, [])
    resumed.restore(graph_path)
    assert resumed.protocol_map.current_page == ""
    assert resumed.protocol_map.current_variant == ""
    resumed.entry_reviewer = lambda _request: {
        "independent_entries": [],
        "deferred_entries": [],
        "deferred_regions": [],
        "reason_consistent": True,
        "reason": "No entries were proposed in this focused fixture.",
    }
    captured_scenes = []

    def capture_scene(_host, _review, scene, _screenshot, _history, **_values):
        captured_scenes.append(scene)
        return ""

    monkeypatch.setattr(loop, "_apply_entry_review", capture_scene)
    assert loop._review_pending_entries(resumed, dialog, []) == ""
    assert len(captured_scenes) == 1
    assert captured_scenes[0].state_id == scenes[1].state_id
    assert captured_scenes[0].variant_name == "world.add_dialog"

    legacy, _env, _agent = _runtime(
        tmp_path, {"screenshot": dialog}, [])
    legacy.restore(graph_path)
    legacy.pending_entry_review.pop("state_id")
    legacy.pending_entry_review.pop("variant_name")
    legacy_reviewer_calls = []
    legacy.entry_reviewer = lambda request: (
        legacy_reviewer_calls.append(request) or {}
    )
    legacy_history = []

    issue = loop._review_pending_entries(legacy, dialog, legacy_history)

    assert "has 2 candidate States" in issue
    assert legacy.pending_entry_review is None
    assert legacy_reviewer_calls == []
    assert legacy_history[-1]["rejection"]["code"] == (
        "entry_review_source_variant_ambiguous"
    )


def test_entry_reviewer_receives_exact_previous_rejection_on_retry(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Timer controls",
                "bbox_1000": [0, 0, 1000, 1000],
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Timer controls",
                "target": "Start button",
            }],
        ),
        scene,
        screenshot,
        [],
    ) == ""
    outside_entry_id = runtime.entry_ledger.record_agent_update(
        page_name=page_name,
        region_name="Top navigation",
        frame_id=loop.screenshot_frame_id(screenshot),
        observations=[{
            "target": "World tab",
            "operation": "click",
            "subject": "World page",
        }],
        source_state_id=scene.state_id,
    ).added[0]
    requests = []
    responses = iter([{
        "independent_entries": [{
            "region_name": "Top navigation",
            "target": "World tab",
            "operation": "click",
            "subject": "World page",
            "equivalent_to_entry_id": outside_entry_id,
            "equivalence_reason": "It is the known World navigation entry.",
        }],
        "deferred_entries": [],
        "deferred_regions": [],
        "reason_consistent": True,
        "reason": "The World tab is an application function.",
    }, {
        "independent_entries": [],
        "deferred_entries": [],
        "deferred_regions": [],
        "reason_consistent": True,
        "reason": "Start only controls the current Timer function.",
    }])

    def reviewer(request):
        requests.append(request)
        return next(responses)

    runtime.entry_reviewer = reviewer
    stable_token = loop._rejection_progress_token(runtime)
    history = []
    first_issue = loop._review_pending_entries(
        runtime, screenshot, history)

    assert outside_entry_id in first_issue
    assert "not exposed as a canonical Entry" in first_issue
    assert requests[0]["previous_rejection"] == {}
    assert requests[0]["known_entries"] == []
    assert runtime.pending_entry_review["previous_rejection"]["code"] == (
        "entry_review_invalid")
    assert loop._rejection_progress_token(runtime) == stable_token

    second_issue = loop._review_pending_entries(
        runtime, screenshot, history)

    assert second_issue == ""
    assert requests[1]["previous_rejection"]["message"] == first_issue
    feedback = requests[1]["previous_rejection"]["feedback"]
    assert "Timer controls" in feedback
    assert outside_entry_id in feedback
    assert "Top navigation" in feedback
    assert "shared_region_entries" in feedback
    assert "List every valid entry" not in feedback
    assert runtime.pending_entry_review is None


def test_identical_invalid_entry_review_is_deferred_after_one_correction(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Timer controls",
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Timer controls",
                "operation": "click",
                "target": "Start button",
            }],
        ),
        scene,
        screenshot,
        [],
    ) == ""
    invalid_response = {
        "independent_entries": [{
            "region_name": "Other region",
            "operation": "click",
            "target": "Other button",
        }],
        "non_task_entries": [],
        "deferred_entries": [],
        "deferred_regions": [],
        "reason_consistent": True,
        "reason": "Repeated invalid out-of-scope entry.",
    }
    requests = []

    def reviewer(request):
        requests.append(request)
        return invalid_response

    runtime.entry_reviewer = reviewer
    history = []

    assert loop._review_pending_entries(runtime, screenshot, history)
    assert loop._review_pending_entries(runtime, screenshot, history) == ""

    assert len(requests) == 2
    assert runtime.pending_entry_review is None
    assert runtime.entry_ledger.entries == ()
    assert loop._region_state(runtime, page_name).region(
        "Timer controls")["coverage_complete"] is False
    assert runtime.entry_review_audits[
        "timer"]["timer controls"]["status"] == "deferred"
    assert any(
        item.get("kind") == "entry_review_retry_stopped"
        for item in history
    )


def test_entry_resolution_ignores_keep_for_already_retained_candidate(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Timer controls",
                "coverage_complete": True,
            }],
            new_entries=[
                {
                    "region_name": "Timer controls",
                    "operation": "click",
                    "target": "Start button",
                },
                {
                    "region_name": "Timer controls",
                    "operation": "click",
                    "target": "Reset button",
                },
            ],
        ),
        scene,
        screenshot,
        history,
    ) == ""
    assert loop._apply_entry_review(
        runtime,
        loop.EntryReview(
            independent_entries=[{
                "region_name": "Timer controls",
                "operation": "click",
                "target": "Start button",
            }],
            non_task_entries=[{
                "region_name": "Timer controls",
                "operation": "click",
                "target": "Reset button",
            }],
        ),
        scene,
        screenshot,
        history,
        reviewer_reason="Start is retained; Reset is disputed.",
        reason_consistent=True,
    ) == ""

    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Timer controls",
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Timer controls",
                "operation": "click",
                "target": "Start button",
            }],
            entry_resolutions=[
                {
                    "region_name": "Timer controls",
                    "operation": "click",
                    "target": "Start button",
                    "decision": "keep",
                    "reason": "The Reviewer already retained it.",
                },
                {
                    "region_name": "Timer controls",
                    "operation": "click",
                    "target": "Reset button",
                    "decision": "drop",
                    "reason": "It is not a separate function entry.",
                },
            ],
        ),
        scene,
        screenshot,
        history,
    ) == ""

    assert [
        item["target"]
        for item in runtime.pending_entry_review["entry_resolutions"]
    ] == ["Reset button"]
    normalized = next(
        item for item in reversed(history)
        if item.get("kind") == "entry_resolution_scope_normalized"
    )
    assert normalized["ignored_redundant_keeps"][0]["target"] == (
        "Start button")


def test_entry_reviewer_rejects_equivalence_with_different_operation_target(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Alarms", summary="Alarms", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-alarms", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Top navigation",
                "bbox_1000": [0, 0, 1000, 200],
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Top navigation",
                "operation": "click",
                "target": "World tab",
            }],
        ),
        scene,
        screenshot,
        [],
    ) == ""
    runtime.pending_entry_review["shared_region_entries"] = [{
        "region_name": "Top navigation",
        "entries": [{
            "entry_id": "ae2",
            "operation": "click",
            "target": "Alarms tab",
        }],
    }]
    history = []

    issue = loop._apply_entry_review(
        runtime,
        loop.EntryReview(independent_entries=[{
            "region_name": "Top navigation",
            "operation": "click",
            "target": "World tab",
            "equivalent_to_entry_id": "ae2",
            "equivalence_reason": "Both are navigation tabs.",
        }]),
        scene,
        screenshot,
        history,
    )

    assert "exact operation and semantic target" in issue
    assert "Alarms tab" in history[-1]["rejection"]["correction"]
    assert "World tab" in history[-1]["rejection"]["correction"]
    assert runtime.pending_entry_review is not None


def test_completion_rejects_completed_region_without_entry_coverage_audit(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    state = loop._region_state(runtime, "Timer")
    frame_id = loop.screenshot_frame_id(screenshot)
    state.observe_frame(frame_id)
    state.apply_agent_update([{
        "name": "Timer controls",
        "coverage_complete": True,
    }], frame_id=frame_id)

    assert any(
        "Region Timer controls has no accepted entry-coverage audit" in gap
        for gap in loop._completion_gaps(runtime)
    )


def test_entry_review_preserves_main_agent_incomplete_coverage_intent(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Timer controls",
                "bbox_1000": [0, 0, 1000, 1000],
                "coverage_complete": False,
            }],
            new_entries=[{
                "region_name": "Timer controls",
                "target": "Open preset",
            }],
        ),
        scene,
        screenshot,
        [],
    ) == ""
    assert runtime.pending_entry_review["coverage_requested"] == {
        "timer controls": False,
    }

    runtime.entry_reviewer = lambda _request: {
        "independent_entries": [{
            "region_name": "Timer controls",
            "target": "Open preset",
        }],
        "deferred_entries": [],
        "deferred_regions": [],
        "reason_consistent": True,
        "reason": "The preset opens a function surface, but survey continues.",
    }
    assert loop._review_pending_entries(runtime, screenshot, []) == ""

    region = loop._region_state(runtime, page_name).region("Timer controls")
    assert region is not None and region["coverage_complete"] is False
    assert runtime.entry_review_audits[
        "timer"]["timer controls"]["status"] == "partial"
    assert [entry.target for entry in runtime.entry_ledger.entries] == [
        "Open preset",
    ]


def test_entry_reviewer_ignores_formal_region_deferral_outside_its_audit(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[
                {
                    "name": "Top navigation",
                    "bbox_1000": [0, 0, 1000, 200],
                    "coverage_complete": False,
                },
                {
                    "name": "Timer controls",
                    "bbox_1000": [0, 200, 1000, 1000],
                    "coverage_complete": True,
                },
            ],
        ),
        scene,
        screenshot,
        [],
    ) == ""
    assert runtime.pending_entry_review[
        "coverage_audit_regions"] == ["Timer controls"]

    runtime.entry_reviewer = lambda _request: {
        "independent_entries": [],
        "deferred_entries": [],
        "deferred_regions": ["Top navigation"],
        "reason_consistent": True,
        "reason": "Attempted to defer a Region outside this audit.",
    }
    history = []
    issue = loop._review_pending_entries(runtime, screenshot, history)

    assert issue == ""
    assert runtime.pending_entry_review is None
    assert loop._region_state(
        runtime, page_name).region("Top navigation")["coverage_complete"] is False
    assert loop._region_state(
        runtime, page_name).region("Timer controls")["coverage_complete"] is True
    assert history[-2]["kind"] == "entry_review_scope_normalized"
    assert history[-2]["ignored_deferred_regions"] == ["Top navigation"]


def test_region_binding_failure_rolls_back_and_skips_entry_review(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    registry_before = runtime.region_registry.snapshot()

    def reject_binding(**_kwargs):
        raise RegionProtocolError("synthetic binding failure")

    runtime.region_registry.bind = reject_binding
    issue = loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Timer controls",
                "bbox_1000": [0, 0, 1000, 1000],
                "coverage_complete": True,
            }],
        ),
        scene,
        screenshot,
        [],
    )

    assert "entry review was not staged" in issue
    assert runtime.pending_entry_review is None
    assert loop._region_state(
        runtime, page_name).snapshot()["regions"] == []
    assert runtime.region_registry.snapshot() == registry_before


def test_cross_page_region_merge_failure_restores_transient_state(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    scenes = {}
    for page_name in ("A", "B", "C"):
        canonical, issue = runtime.protocol_map.observe(
            name=page_name,
            summary=f"Page {page_name}",
            identity="new",
            matched_page_name="",
            surface_kind="page",
            regions=(),
            screenshot=screenshot,
            commit_regions=False,
        )
        assert (canonical, issue) == (page_name, "")
        scenes[page_name] = loop.ObservedScene(
            state_id=f"state-{page_name.lower()}",
            screenshot=screenshot,
            page_name=page_name,
            is_new=True,
        )

    def record(page_name: str, region_ref: str = "") -> None:
        assert loop._apply_main_agent_page_update(
            runtime,
            loop.PageUpdate(
                page_name=page_name,
                regions=[{
                    "name": "Shared",
                    "bbox_1000": [0, 0, 1000, 1000],
                    "coverage_complete": False,
                    "equivalent_to_region_ref": region_ref,
                    "equivalence_reason": (
                        "The visible component was directly compared."),
                }],
            ),
            scenes[page_name],
            screenshot,
            [],
            region_reviewed=True,
        ) == ""

    record("A")
    record("B")
    ref_a = runtime.region_registry.region_ref("A", "Shared")
    ref_b = runtime.region_registry.region_ref("B", "Shared")
    assert ref_a and ref_b and ref_a != ref_b
    record("C", ref_b)

    states_before = {
        key: state.snapshot()
        for key, state in runtime.region_states.items()
    }
    registry_before = runtime.region_registry.snapshot()
    c_state = runtime.region_states["c"]
    original_remap = c_state.remap_region_ref

    def fail_after_remap(old_ref: str, new_ref: str) -> None:
        original_remap(old_ref, new_ref)
        raise RegionProtocolError(
            "synthetic post-merge remap failure")

    c_state.remap_region_ref = fail_after_remap
    history = []
    record_update = loop.PageUpdate(
        page_name="B",
        regions=[{
            "name": "Shared",
            "bbox_1000": [0, 0, 1000, 1000],
            "coverage_complete": False,
            "equivalent_to_region_ref": ref_a,
            "equivalence_reason": (
                "The visible component was directly compared."),
        }],
    )

    assert loop._apply_main_agent_page_update(
        runtime,
        record_update,
        scenes["B"],
        screenshot,
        history,
        region_reviewed=True,
    ) == ""

    assert history[-1]["status"] == "rejected"
    assert history[-1]["rejected_items"][0]["error_code"] == (
        "region_group_binding_rejected")
    assert {
        key: state.snapshot()
        for key, state in runtime.region_states.items()
    } == states_before
    assert runtime.region_registry.snapshot() == registry_before


def test_entry_reviewer_cannot_change_the_formal_region_partition(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[
                {
                    "name": "Top navigation",
                    "bbox_1000": [0, 0, 1000, 200],
                    "coverage_complete": True,
                },
                {
                    "name": "Timer controls",
                    "bbox_1000": [0, 200, 1000, 1000],
                    "coverage_complete": True,
                },
            ],
        ),
        scene,
        screenshot,
        [],
    ) == ""
    region_snapshot_before = loop._region_state(runtime, page_name).snapshot()
    formal_before = [
        (item["name"], item["region_ref"])
        for item in region_snapshot_before["regions"]
    ]
    groups_before = runtime.region_registry.snapshot()
    review_calls = []

    def reviewer(request):
        review_calls.append(request)
        new_entries = (
            [{
                "region_name": "Invented Reviewer Region",
                "target": "Fake entry",
            }]
            if len(review_calls) == 1 else []
        )
        return {
            "independent_entries": new_entries,
            "deferred_entries": [],
            "deferred_regions": [],
            "reason_consistent": True,
            "reason": "The full screenshot was checked Region by Region.",
        }

    runtime.entry_reviewer = reviewer
    issue = loop._review_pending_entries(runtime, screenshot, [])
    assert "added entries under Regions outside this coverage audit" in issue
    assert runtime.pending_entry_review is not None
    assert runtime.region_registry.snapshot() == groups_before
    assert [
        (item["name"], item["region_ref"])
        for item in loop._region_state(runtime, page_name).snapshot()["regions"]
    ] == formal_before

    runtime.entry_review_deferred_frames["timer"] = {
        "top navigation": "older-frame",
        "timer controls": "older-frame",
    }
    review_screenshot = _png("blue")
    assert loop._review_pending_entries(runtime, review_screenshot, []) == ""
    assert review_calls[0]["coverage_audit_regions"] == [
        "Top navigation", "Timer controls",
    ]
    def group_identity(payload):
        return [(
            item["region_ref"],
            item["representative"],
            [(
                occurrence["page_name"], occurrence["region_name"],
                occurrence["state_ids"],
            ) for occurrence in item["occurrences"]],
        ) for item in payload["groups"]]

    assert group_identity(runtime.region_registry.snapshot()) == group_identity(
        groups_before)
    assert [
        (item["name"], item["region_ref"])
        for item in loop._region_state(runtime, page_name).snapshot()["regions"]
    ] == formal_before
    region_snapshot_after = loop._region_state(runtime, page_name).snapshot()
    assert region_snapshot_after["current_frame_id"] == (
        region_snapshot_before["current_frame_id"])
    assert region_snapshot_after["current_bboxes"] == (
        region_snapshot_before["current_bboxes"])
    audits = runtime.entry_review_audits["timer"]
    assert set(audits) == {"top navigation", "timer controls"}
    assert all(audit["status"] == "complete" for audit in audits.values())
    assert "timer" not in runtime.entry_review_deferred_frames


def test_focused_entry_review_rejects_existing_entries_from_other_region(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[
                {
                    "name": "Time display",
                    "bbox_1000": [0, 0, 1000, 400],
                    "coverage_complete": True,
                },
                {
                    "name": "Clock dial",
                    "bbox_1000": [0, 400, 1000, 1000],
                    "coverage_complete": False,
                },
            ],
            new_entries=[{
                "region_name": "Time display",
                "target": "Hour display",
                "control_type": "input",
            }],
        ),
        scene,
        screenshot,
        [],
        region_reviewed=True,
        review_region_names=["Time display"],
    ) == ""
    runtime.entry_reviewer = lambda _request: {
        "independent_entries": [{
            "region_name": "Time display",
            "target": "Hour display",
            "control_type": "input",
        }],
        "deferred_entries": [],
        "deferred_regions": [],
        "reason_consistent": True,
        "reason": "The exact visible input remains valid.",
    }
    assert loop._review_pending_entries(runtime, screenshot, []) == ""
    assert len(runtime.entry_ledger.entries) == 1

    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Clock dial",
                "bbox_1000": [0, 400, 1000, 1000],
                "coverage_complete": True,
            }],
        ),
        scene,
        screenshot,
        [],
        region_reviewed=True,
        review_region_names=["Clock dial"],
    ) == ""
    requests = []

    def out_of_scope_reviewer(request):
        requests.append(request)
        return {
            "independent_entries": [{
                "region_name": "Time display",
                "target": "Hour display",
                "control_type": "input",
            }],
            "deferred_entries": [],
            "deferred_regions": [],
            "reason_consistent": True,
            "reason": (
                "The full-page exhaustive list repeats the known input; "
                "the focused dial has no discrete entry."
            ),
        }

    runtime.entry_reviewer = out_of_scope_reviewer
    history = []

    issue = loop._review_pending_entries(runtime, screenshot, history)

    assert "added entries under Regions outside this coverage audit" in issue
    assert requests[0]["coverage_audit_regions"] == ["Clock dial"]
    assert requests[0]["known_entries"] == []
    assert runtime.pending_entry_review is not None
    assert len(runtime.entry_ledger.entries) == 1
    feedback = runtime.pending_entry_review[
        "previous_rejection"]["feedback"]
    assert "Clock dial" in feedback
    assert "Time display" in feedback
    assert "Hour display" in feedback
    assert "不属于本轮审核区域" in feedback


def test_repeated_formal_entry_is_not_reopened_as_a_new_candidate(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    initial_update = loop.PageUpdate(
        page_name=page_name,
        regions=[{
            "name": "Timer controls",
            "bbox_1000": [0, 0, 1000, 1000],
            "coverage_complete": True,
        }],
        new_entries=[{
            "region_name": "Timer controls",
            "target": "Start button",
        }],
    )
    assert loop._stage_main_agent_page_update(
        runtime,
        initial_update,
        scene,
        screenshot,
        [],
        region_reviewed=True,
        review_region_names=["Timer controls"],
    ) == ""
    assert loop._apply_entry_review(
        runtime,
        loop.EntryReview(independent_entries=[{
            "region_name": "Timer controls",
            "target": "Start button",
        }]),
        scene,
        screenshot,
        [],
        reviewer_reason="The visible Start button is a distinct operation.",
        reason_consistent=True,
    ) == ""
    assert len(runtime.entry_ledger.entries) == 1
    history = []

    assert loop._stage_main_agent_page_update(
        runtime,
        initial_update,
        scene,
        screenshot,
        history,
        region_reviewed=True,
        review_region_names=["Timer controls"],
    ) == ""

    assert runtime.pending_entry_review is not None
    assert runtime.pending_entry_review["candidates"] == []
    normalized = next(
        item for item in history
        if item.get("kind") == "entry_review_scope_normalized"
    )
    assert normalized["ignored_existing_entries"] == [{
        "region_name": "Timer controls",
        "target": "Start button",
        "operation": "Start button",
        "subject": "Timer controls",
        "entry_id": "ae1",
    }]
    assert loop._apply_entry_review(
        runtime,
        loop.EntryReview(),
        scene,
        screenshot,
        history,
        reviewer_reason=(
            "The known Start button is already formal and no entry is missing."),
        reason_consistent=True,
    ) == ""
    assert len(runtime.entry_ledger.entries) == 1
    assert loop._region_state(runtime, page_name).region(
        "Timer controls")["coverage_complete"] is True
    assert history[-1]["status"] == "accepted"


def test_entry_review_result_keeps_the_originating_survey_task(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot,
        variant_name="default",
        variant_identity="new",
        visible_predicates=[],
        commit_regions=False,
    )
    assert issue == ""
    scene = loop._register_scene(
        runtime,
        screenshot,
        _turn(
            "Timer",
            action="NONE",
            identity="new",
            variant_name="default",
            variant_identity="new",
        ),
        page_name,
    )
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Timer controls",
                "bbox_1000": [0, 0, 1000, 1000],
                "coverage_complete": True,
            }],
        ),
        scene,
        screenshot,
        [],
        region_reviewed=True,
        review_region_names=["Timer controls"],
    ) == ""
    runtime.entry_reviewer = lambda _request: {
        "independent_entries": [],
        "deferred_entries": [],
        "deferred_regions": [],
        "reason_consistent": True,
        "reason": "No independent target is missing from this Region.",
    }
    loop._sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.phase == "review_entries"
    originating_task_id = runtime.exploration_task.task_id

    loop.run_autonomous_traversal(runtime, {"screenshot": screenshot})

    trace = json.loads(
        (tmp_path / "autonomous_trace.json").read_text("utf-8"))
    review_result = next(
        item for item in trace["history"]
        if item.get("kind") == "entry_review_result"
    )
    assert review_result["status"] == "accepted"
    assert review_result["exploration_task_id"] == originating_task_id


def test_same_batch_entry_waits_for_owner_region_without_own_correction(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []

    issue = loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Timer controls",
                "bbox_1000": [0, 0, 1000, 1000],
                "equivalence_reason": None,
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Timer controls",
                "target": "Open presets",
            }],
        ),
        scene,
        screenshot,
        history,
        region_reviewed=True,
    )

    assert "remain deferred until those Regions are accepted" in issue
    assert runtime.pending_entry_review is None
    assert history[-1]["kind"] == "entry_review_result"
    assert history[-1]["status"] == "deferred"
    corrections = runtime.page_update_corrections["timer"]
    assert corrections["region:timer controls"]["error_code"] == (
        "invalid_type")
    assert not any(key.startswith("entry:") for key in corrections)

    runtime.entry_reviewer = lambda _request: {
        "independent_entries": [{
            "region_name": "Timer controls",
            "target": "Open presets",
        }],
        "deferred_entries": [],
        "deferred_regions": [],
        "reason_consistent": True,
        "reason": "The visible presets control opens a distinct surface.",
    }
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Timer controls",
                "bbox_1000": [0, 0, 1000, 1000],
                "equivalence_reason": "",
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Timer controls",
                "target": "Open presets",
            }],
        ),
        scene,
        screenshot,
        history,
        region_reviewed=True,
    ) == ""
    assert runtime.pending_entry_review is not None
    assert loop._review_pending_entries(runtime, screenshot, history) == ""
    assert "timer" not in runtime.page_update_corrections
    assert runtime.entry_ledger.entries[0].target == "Open presets"


def test_stage_rejects_candidate_owned_by_unknown_region_without_mutation(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    _register_reviewed_main_region(
        runtime, page_name, scene, screenshot)
    state_before = loop._region_state(runtime, page_name).snapshot()
    registry_before = runtime.region_registry.snapshot()

    issue = loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[],
            new_entries=[{
                "region_name": "Ghost",
                "target": "Open ghost",
            }],
        ),
        scene,
        screenshot,
        [],
    )

    assert "must already be accepted and bound" in issue
    assert runtime.pending_entry_review is None
    assert loop._region_state(runtime, page_name).snapshot() == state_before
    assert runtime.region_registry.snapshot() == registry_before
    correction = runtime.page_update_corrections["timer"][
        "entry:ghost:open ghost"]
    assert correction["error_code"] == "unknown_region_reference"
    assert any(
        "page-update correction" in gap
        for gap in loop._completion_gaps(runtime)
    )


def test_stage_rejects_malformed_entry_without_mutation(tmp_path) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    _register_reviewed_main_region(
        runtime, page_name, scene, screenshot)
    state_before = loop._region_state(runtime, page_name).snapshot()
    registry_before = runtime.region_registry.snapshot()
    history = []

    issue = loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[],
            new_entries=[{"region_name": "Main"}],
        ),
        scene,
        screenshot,
        history,
    )

    assert issue == ""
    assert runtime.pending_entry_review is None
    assert loop._region_state(runtime, page_name).snapshot() == state_before
    assert runtime.region_registry.snapshot() == registry_before
    correction = runtime.page_update_corrections["timer"]["invalid_entry:0"]
    assert correction["error_code"] == "missing_required"
    assert correction["field"] == "target"
    assert history[-1]["status"] == "rejected"
    assert any(
        "page-update correction" in gap
        for gap in loop._completion_gaps(runtime)
    )


def test_ownerless_rejected_entry_keeps_every_audited_region_partial(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []

    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[
                {
                    "name": "Navigation",
                    "bbox_1000": [0, 0, 1000, 200],
                    "coverage_complete": True,
                },
                {
                    "name": "Timer controls",
                    "bbox_1000": [0, 200, 1000, 1000],
                    "coverage_complete": True,
                },
            ],
            new_entries=[{}],
        ),
        scene,
        screenshot,
        history,
    ) == ""
    assert runtime.pending_entry_review[
        "pre_rejected_entry_all_audits"] is True

    assert loop._apply_entry_review(
        runtime,
        loop.EntryReview(),
        scene,
        screenshot,
        history,
    ) == ""

    state = loop._region_state(runtime, page_name)
    assert state.region("Navigation")["coverage_complete"] is False
    assert state.region("Timer controls")["coverage_complete"] is False
    audits = runtime.entry_review_audits["timer"]
    assert audits["navigation"]["status"] == "partial"
    assert audits["timer controls"]["status"] == "partial"
    assert runtime.page_update_corrections["timer"][
        "invalid_entry:0"]["error_code"] == "missing_required"
    gaps = loop._completion_gaps(runtime)
    assert any("Region Navigation has coverage_complete=false" in gap
               for gap in gaps)
    assert any("Region Timer controls has coverage_complete=false" in gap
               for gap in gaps)


def test_stage_validates_region_before_changing_formal_partition(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    _register_reviewed_main_region(
        runtime, page_name, scene, screenshot)
    regions_before = loop._region_state(
        runtime, page_name).snapshot()["regions"]
    registry_before = runtime.region_registry.snapshot()
    history = []

    issue = loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{"name": "Main"}],
            new_entries=[],
        ),
        scene,
        screenshot,
        history,
    )

    assert issue == ""
    assert runtime.pending_entry_review is None
    assert loop._region_state(
        runtime, page_name).snapshot()["regions"] == regions_before
    assert runtime.region_registry.snapshot() == registry_before
    correction = runtime.page_update_corrections["timer"]["region:main"]
    assert correction["error_code"] == "invalid_type"
    assert correction["field"] == "coverage_complete"
    assert history[-1]["status"] == "rejected"
    assert any(
        "page-update correction" in gap
        for gap in loop._completion_gaps(runtime)
    )


def test_entry_reviewer_drop_resolves_only_matching_stale_correction(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clocks", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Add world clock modal",
                "bbox_1000": [0, 0, 1000, 1000],
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Add world clock modal",
                "target": "Cancel button",
            }],
        ),
        scene,
        screenshot,
        history,
    ) == ""
    page_key = loop._page_key(page_name)
    cancel_key = "entry:add world clock modal:cancel button"
    other_key = "entry:add world clock modal:search field"
    runtime.page_update_corrections[page_key] = {
        cancel_key: {
            "kind": "new_entry",
            "region_name": "Add world clock modal",
            "target": "Cancel button",
            "field": "equivalent_to_entry_id",
        },
        other_key: {
            "kind": "new_entry",
            "region_name": "Add world clock modal",
            "target": "Search field",
            "field": "equivalent_to_entry_id",
        },
    }

    assert loop._apply_entry_review(
        runtime, loop.EntryReview(), scene, screenshot, history) == ""

    assert set(runtime.page_update_corrections[page_key]) == {
        cancel_key, other_key,
    }
    assert history[-1]["status"] == "disagreement"
    assert runtime.entry_ledger.entries == ()

    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Add world clock modal",
                "coverage_complete": True,
            }],
            new_entries=[],
            entry_resolutions=[{
                "region_name": "Add world clock modal",
                "target": "Cancel button",
                "decision": "drop",
                "reason": "Cancel only closes the current modal.",
            }],
        ),
        scene,
        screenshot,
        history,
        main_agent_reason=(
            "I accept that Cancel only closes the current modal, so it is not "
            "a separate function entry."
        ),
    ) == ""
    assert runtime.pending_entry_review["review_attempt"] == 2
    assert loop._apply_entry_review(
        runtime, loop.EntryReview(), scene, screenshot, history,
        reviewer_reason="The revised proposal matches the visible modal.",
        reason_consistent=True,
    ) == ""

    assert set(runtime.page_update_corrections[page_key]) == {other_key}
    assert runtime.entry_ledger.entries == ()
    runtime.page_update_corrections.clear()
    assert _page_survey_need(runtime, page_name) == ("", "", "")


def test_entry_reviewer_records_command_operation_without_scheduling_it(
    tmp_path,
) -> None:
    screenshot = _png("teal")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Player", summary="Content player", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-player", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Player",
            regions=[{
                "name": "Playback controls",
                "summary": "Content and mode controls",
                "coverage_complete": True,
            }],
            new_entries=[
                {
                    "region_name": "Playback controls",
                    "operation": "open",
                    "target": "Options menu",
                },
                {
                    "region_name": "Playback controls",
                    "operation": "activate",
                    "target": "Next item",
                },
            ],
        ),
        scene,
        screenshot,
        history,
    ) == ""

    assert loop._apply_entry_review(
        runtime,
        loop.EntryReview(
            independent_entries=[{
                "region_name": "Playback controls",
                "operation": "open",
                "target": "Options menu",
            }],
            record_only_entries=[{
                "region_name": "Playback controls",
                "operation": "activate",
                "target": "Next item",
            }],
            non_task_entries=[],
        ),
        scene,
        screenshot,
        history,
        reviewer_reason=(
            "The menu needs exploration; the next-item operation is visible "
            "and command-relevant but structurally shallow."
        ),
        reason_consistent=True,
    ) == ""

    by_target = {entry.target: entry for entry in runtime.entry_ledger.entries}
    assert by_target["Options menu"].status.value == "discovered"
    assert by_target["Next item"].status.value == "recorded"
    assert by_target["Next item"].task_eligible is False
    assert [entry.target for entry in runtime.entry_ledger.task_candidates()] == [
        "Options menu",
    ]
    assert history[-1]["recorded"][0]["target"] == "Next item"
    assert _region_exploration_status(
        runtime, "Player", "Playback controls") == "open"
    by_target["Options menu"].status = EntryStatus.VERIFIED
    assert _region_exploration_status(
        runtime, "Player", "Playback controls") == "complete"


def test_pending_entry_review_preserves_record_only_model_output(
    tmp_path,
) -> None:
    screenshot = _png("teal")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Clock", summary="Clock navigation", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-clock", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    runtime.graph.graph.add_node(
        scene.state_id,
        page_name=page_name,
        observed_facts={"variant_name": "default"},
    )
    history = []
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Clock",
            regions=[{
                "name": "Navigation",
                "summary": "Clock views",
                "coverage_complete": True,
            }],
            new_entries=[
                {
                    "region_name": "Navigation",
                    "operation": "switch view",
                    "target": "Alarms tab",
                },
                {
                    "region_name": "Navigation",
                    "operation": "show current view",
                    "target": "World tab",
                },
            ],
        ),
        scene,
        screenshot,
        history,
    ) == ""
    runtime.entry_reviewer = lambda _request: {
        "independent_entries": [{
            "region_name": "Navigation",
            "operation": "switch view",
            "target": "Alarms tab",
        }],
        "record_only_entries": [{
            "region_name": "Navigation",
            "operation": "show current view",
            "target": "World tab",
        }],
        "non_task_entries": [],
        "deferred_entries": [],
        "deferred_regions": [],
        "reason_consistent": True,
        "reason": "The selected tab is recorded without another click.",
    }

    assert loop._review_pending_entries(runtime, screenshot, history) == ""

    by_target = {entry.target: entry for entry in runtime.entry_ledger.entries}
    assert by_target["Alarms tab"].status.value == "discovered"
    assert by_target["World tab"].status.value == "recorded"
    assert runtime.pending_entry_review is None


def test_dropped_entry_candidates_require_main_agent_revision_before_coverage(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer setup", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    internal_targets = [
        "1 minute preset", "2 minute preset", "3 minute preset",
        "5 minute preset", "10 minute preset", "15 minute preset",
        "30 minute preset", "45 minute preset", "1 hour preset",
        "Increase hours", "Decrease hours", "Increase minutes",
        "Decrease minutes", "Increase seconds",
    ]
    history = []
    update = loop.PageUpdate(
        page_name="Timer",
        regions=[{
            "name": "Timer setup controls",
            "bbox_1000": [0, 0, 1000, 1000],
            "summary": "Presets and duration controls",
            "coverage_complete": True,
        }],
        new_entries=[{
            "region_name": "Timer setup controls",
            "target": target,
        } for target in internal_targets],
    )

    issue = loop._stage_main_agent_page_update(
        runtime, update, scene, screenshot, history)

    assert issue == ""
    assert runtime.pending_entry_review is not None
    assert len(runtime.pending_entry_review["candidates"]) == 14
    assert runtime.entry_ledger.entries == ()
    region = loop._region_state(runtime, "Timer").snapshot()["regions"][0]
    assert region["coverage_complete"] is False
    loop._sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.phase == "review_entries"

    issue = loop._apply_entry_review(
        runtime,
        loop.EntryReview(
            independent_entries=[],
            non_task_entries=[{
                "region_name": "Timer setup controls",
                "target": target,
            } for target in internal_targets],
        ),
        scene,
        screenshot,
        history,
    )

    assert issue == ""
    assert runtime.pending_entry_review is None
    assert runtime.entry_ledger.entries == ()
    region = loop._region_state(runtime, "Timer").snapshot()["regions"][0]
    assert region["coverage_complete"] is False
    assert history[-1]["status"] == "disagreement"
    assert len(history[-1]["dropped"]) == 14

    revised = loop.PageUpdate(
        page_name="Timer",
        regions=[{
            "name": "Timer setup controls",
            "summary": "Presets and duration controls",
            "coverage_complete": True,
        }],
        new_entries=[],
    )
    missing_resolution_issue = loop._stage_main_agent_page_update(
        runtime,
        revised,
        scene,
        screenshot,
        history,
        main_agent_reason=(
            "The minute presets and duration steppers only configure the "
            "current Timer and do not open separate functional surfaces."
        ),
    )
    assert "entry_resolutions 遗漏" in missing_resolution_issue
    assert runtime.pending_entry_review is None

    revised = loop.PageUpdate(
        page_name="Timer",
        regions=[{
            "name": "Timer setup controls",
            "summary": "Presets and duration controls",
            "coverage_complete": True,
        }],
        new_entries=[],
        entry_resolutions=[{
            "region_name": "Timer setup controls",
            "target": target,
            "decision": "drop",
            "reason": "It only configures the current Timer duration.",
        } for target in internal_targets],
    )
    assert loop._stage_main_agent_page_update(
        runtime,
        revised,
        scene,
        screenshot,
        history,
        main_agent_reason=(
            "The minute presets and duration steppers only configure the "
            "current Timer and do not open separate functional surfaces."
        ),
    ) == ""
    assert runtime.pending_entry_review["review_attempt"] == 2
    assert runtime.pending_entry_review["previous_review"]["dropped"]
    assert loop._apply_entry_review(
        runtime,
        loop.EntryReview(),
        scene,
        screenshot,
        history,
        reviewer_reason="The revised proposal now matches the visible controls.",
        reason_consistent=True,
    ) == ""
    region = loop._region_state(runtime, "Timer").snapshot()["regions"][0]
    assert region["coverage_complete"] is True
    assert history[-1]["status"] == "accepted"


def test_batched_entry_disagreements_are_retried_per_region(tmp_path) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Alarms", summary="Alarms", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-alarms", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[
                {"name": "Top navigation", "coverage_complete": True},
                {"name": "Main content", "coverage_complete": True},
            ],
            new_entries=[
                {
                    "region_name": "Top navigation",
                    "operation": "click",
                    "target": "World tab",
                },
                {
                    "region_name": "Main content",
                    "operation": "click",
                    "target": "Add Alarm button",
                },
            ],
        ),
        scene,
        screenshot,
        history,
    ) == ""
    assert loop._apply_entry_review(
        runtime,
        loop.EntryReview(
            independent_entries=[{
                "region_name": "Top navigation",
                "operation": "click",
                "target": "World tab",
            }],
            non_task_entries=[{
                "region_name": "Main content",
                "operation": "click",
                "target": "Add Alarm button",
            }],
        ),
        scene,
        screenshot,
        history,
        reviewer_reason="The reviewer disputes both candidates.",
        reason_consistent=True,
    ) == ""

    audits = runtime.entry_review_audits["alarms"]
    assert audits["top navigation"]["coverage_audit_regions"] == [
        "Top navigation"]
    assert audits["top navigation"]["status"] == "complete"
    assert audits["main content"]["coverage_audit_regions"] == [
        "Main content"]
    assert audits["main content"]["status"] == "disagreement"
    assert audits["top navigation"]["dropped"] == []
    assert [item["target"] for item in audits["main content"]["dropped"]] == [
        "Add Alarm button"]
    assert [entry.target for entry in runtime.entry_ledger.entries] == [
        "World tab"]

    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Main content",
                "coverage_complete": True,
            }],
            new_entries=[],
            entry_resolutions=[{
                "region_name": "Main content",
                "operation": "click",
                "target": "Add Alarm button",
                "decision": "drop",
                "reason": "This control has no separate function to explore.",
            }],
        ),
        scene,
        screenshot,
        history,
        review_region_names=["Main content"],
    ) == ""
    assert runtime.pending_entry_review["coverage_audit_regions"] == [
        "Main content"]
    assert [
        item["target"]
        for item in runtime.pending_entry_review["previous_review"]["dropped"]
    ] == ["Add Alarm button"]
    assert runtime.pending_entry_review["candidates"] == []
    requests = []

    def stale_non_task_reviewer(request):
        requests.append(request)
        return {
            "independent_entries": [],
            "non_task_entries": [{
                "region_name": "Main content",
                "operation": "click",
                "target": "Add Alarm button",
            }],
            "deferred_entries": [],
            "deferred_regions": [],
            "reason_consistent": True,
            "reason": "Repeated the already resolved prior classification.",
        }

    runtime.entry_reviewer = stale_non_task_reviewer
    assert loop._review_pending_entries(runtime, screenshot, history) == ""

    assert requests[0]["candidates"] == []
    assert requests[0]["previous_review"] == {}
    assert runtime.pending_entry_review is None
    assert loop._region_state(runtime, page_name).region(
        "Main content")["coverage_complete"] is True
    normalized = next(
        item for item in reversed(history)
        if item.get("kind") == "entry_review_scope_normalized"
    )
    assert normalized["ignored_non_task_entries"][0]["target"] == (
        "Add Alarm button")




def test_entry_review_three_round_limit_survives_resume_and_dynamic_frames(
    tmp_path,
) -> None:
    first_screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": first_screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer setup", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=first_screenshot, commit_regions=False,
    )
    assert issue == ""

    def scene_for(screenshot):
        return loop.ObservedScene(
            state_id="state-timer",
            screenshot=screenshot,
            page_name=page_name,
            is_new=False,
        )

    update = loop.PageUpdate(
        page_name=page_name,
        regions=[
            {
                "name": "Timer setup controls",
                "bbox_1000": [0, 0, 1000, 500],
                "coverage_complete": True,
            },
            {
                "name": "Timer status panel",
                "bbox_1000": [0, 500, 1000, 1000],
                "coverage_complete": True,
            },
        ],
        new_entries=[{
            "region_name": "Timer setup controls",
            "target": "1 minute preset",
        }],
        entry_resolutions=[{
            "region_name": "Timer setup controls",
            "target": "1 minute preset",
            "decision": "keep",
            "reason": "It remains a proposed independent function entry.",
        }],
    )
    history = []
    assert loop._stage_main_agent_page_update(
        runtime,
        update,
        scene_for(first_screenshot),
        first_screenshot,
        history,
        main_agent_reason="The preset opens a separate function.",
        review_region_names=["Timer setup controls"],
    ) == ""
    assert runtime.pending_entry_review["review_attempt"] == 1
    assert loop._apply_entry_review(
        runtime,
        loop.EntryReview(),
        scene_for(first_screenshot),
        first_screenshot,
        history,
        reviewer_reason=(
            "The preset only changes the current Timer duration and opens no "
            "separate functional surface."
        ),
        reason_consistent=True,
    ) == ""
    assert history[-1]["status"] == "disagreement"

    loop._checkpoint(runtime, history)
    resumed, _env, _agent = _runtime(
        tmp_path, {"screenshot": _png("purple")}, [])
    resumed.restore(str(tmp_path / "graph.json"))
    assert resumed.action_count == 0
    assert resumed.entry_review_evidence_generation == 0

    second_screenshot = _png("purple")
    second_history = []
    assert loop._stage_main_agent_page_update(
        resumed,
        update,
        scene_for(second_screenshot),
        second_screenshot,
        second_history,
        main_agent_reason=(
            "The clock pixels changed, but I still consider the preset an entry."
        ),
        review_region_names=[
            "Timer setup controls", "Timer status panel",
        ],
    ) == ""
    assert resumed.pending_entry_review["review_attempt"] == 2
    assert loop._apply_entry_review(
        resumed,
        loop.EntryReview(),
        scene_for(second_screenshot),
        second_screenshot,
        second_history,
        reviewer_reason="It still only changes the current duration.",
        reason_consistent=True,
    ) == ""

    third_screenshot = _png("blue")
    assert loop._stage_main_agent_page_update(
        resumed,
        update,
        scene_for(third_screenshot),
        third_screenshot,
        second_history,
        main_agent_reason=(
            "Another dynamic pixel change does not alter my candidate decision."
        ),
        review_region_names=["Timer setup controls"],
    ) == ""
    assert resumed.pending_entry_review["review_attempt"] == 3
    assert loop._apply_entry_review(
        resumed,
        loop.EntryReview(),
        scene_for(third_screenshot),
        third_screenshot,
        second_history,
        reviewer_reason="The preset remains an internal parameter selector.",
        reason_consistent=True,
    ) == ""
    assert second_history[-1]["status"] == "final_disagreement"
    assert resumed.entry_ledger.entries == ()
    region = loop._region_state(
        resumed, page_name).region("Timer setup controls")
    assert region is not None and region["coverage_complete"] is False

    fourth_issue = loop._stage_main_agent_page_update(
        resumed,
        update,
        scene_for(_png("white")),
        _png("white"),
        second_history,
        main_agent_reason="Resubmit the same unresolved proposal.",
        review_region_names=["Timer setup controls"],
    )
    assert "three allowed reviews" in fourth_issue
    assert resumed.pending_entry_review is None
def test_entry_review_defers_obscured_candidate_and_reopens_owner_region(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clock", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    issue = loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="World",
            regions=[{
                "name": "Top Navigation Bar",
                "bbox_1000": [0, 0, 1000, 1000],
                "summary": "Primary page switches",
                "coverage_complete": True,
            }],
            new_entries=[
                {
                    "region_name": "Top Navigation Bar",
                    "target": "Menu button",
                },
                {
                    "region_name": "Top Navigation Bar",
                    "target": "Alarms tab",
                },
            ],
        ),
        scene,
        screenshot,
        history,
    )
    assert issue == ""

    issue = loop._apply_entry_review(
        runtime,
        loop.EntryReview(
            independent_entries=[{
                "region_name": "Top Navigation Bar",
                "target": "Menu button",
            }],
            deferred_entries=[{
                "region_name": "Top Navigation Bar",
                "target": "Alarms tab",
            }],
        ),
        scene,
        screenshot,
        history,
    )

    assert issue == ""
    assert [entry.target for entry in runtime.entry_ledger.entries] == [
        "Menu button",
    ]
    region = loop._region_state(runtime, "World").region(
        "Top Navigation Bar")
    assert region is not None and region["coverage_complete"] is False
    assert [item["target"] for item in history[-1]["deferred"]] == [
        "Alarms tab",
    ]
    assert history[-1]["frame_id"] == loop.screenshot_frame_id(screenshot)
    assert history[-1]["dropped"] == []
    assert _page_survey_need(
        runtime, "World", state_id="state-world") == ("", "", "")

    runtime.entry_review_evidence_generation += 1
    assert _page_survey_need(
        runtime, "World", state_id="state-world") == (
            "region_has_not_been_fully_inspected",
            "Top Navigation Bar",
            "survey_region",
        )


def test_entry_review_defers_obscured_region_when_missing_entry_is_not_named(
    tmp_path,
) -> None:
    screenshot = _png("purple")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clock", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    issue = loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="World",
            regions=[{
                "name": "Top Header Bar",
                "bbox_1000": [0, 0, 1000, 1000],
                "summary": "Visible actions and partly covered navigation",
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Top Header Bar",
                "target": "Menu button",
            }],
        ),
        scene,
        screenshot,
        history,
    )
    assert issue == ""

    issue = loop._apply_entry_review(
        runtime,
        loop.EntryReview(
            independent_entries=[{
                "region_name": "Top Header Bar",
                "target": "Menu button",
            }],
            deferred_regions=["Top Header Bar"],
        ),
        scene,
        screenshot,
        history,
    )

    assert issue == ""
    assert [entry.target for entry in runtime.entry_ledger.entries] == [
        "Menu button",
    ]
    region = loop._region_state(runtime, "World").region("Top Header Bar")
    assert region is not None and region["coverage_complete"] is False
    assert history[-1]["deferred"] == []
    assert history[-1]["deferred_regions"] == ["Top Header Bar"]
    loop._sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.phase == "survey_region"
    assert runtime.exploration_task.region_name == "Top Header Bar"


def test_entry_review_cannot_complete_deferred_region_on_same_frame(
    tmp_path,
) -> None:
    screenshot = _png("purple")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clock", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    issue = loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="World",
            regions=[{
                "name": "Top Navigation Bar",
                "bbox_1000": [0, 0, 1000, 1000],
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Top Navigation Bar",
                "target": "Alarms tab",
            }],
        ),
        scene,
        screenshot,
        history,
    )
    assert issue == ""
    issue = loop._apply_entry_review(
        runtime,
        loop.EntryReview(
            deferred_regions=["Top Navigation Bar"],
        ),
        scene,
        screenshot,
        history,
    )
    assert issue == ""
    region = loop._region_state(runtime, "World").region(
        "Top Navigation Bar")
    assert region is not None and region["coverage_complete"] is False

    issue = loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="World",
            regions=[
                {
                    "name": "Top Navigation Bar",
                    "coverage_complete": True,
                },
                {
                    "name": "World Clock Content Area",
                    "bbox_1000": [0, 200, 1000, 1000],
                    "coverage_complete": True,
                },
            ],
            new_entries=[{
                "region_name": "World Clock Content Area",
                "target": "Add World Clock button",
            }],
        ),
        scene,
        screenshot,
        history,
    )
    assert issue == ""
    issue = loop._apply_entry_review(
        runtime,
        loop.EntryReview(independent_entries=[{
            "region_name": "World Clock Content Area",
            "target": "Add World Clock button",
        }]),
        scene,
        screenshot,
        history,
    )

    assert issue == ""
    region = loop._region_state(runtime, "World").region(
        "Top Navigation Bar")
    assert region is not None and region["coverage_complete"] is False
    loop._sync_exploration_task(runtime)
    assert runtime.exploration_task is not None
    assert runtime.exploration_task.phase == "survey_region"
    assert runtime.exploration_task.region_name == "Top Navigation Bar"

    fresh_screenshot = _png("green")
    fresh_scene = loop.ObservedScene(
        state_id="state-world", screenshot=fresh_screenshot,
        page_name=page_name, is_new=False,
    )
    issue = loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="World",
            regions=[{
                "name": "Top Navigation Bar",
                "coverage_complete": True,
            }],
        ),
        fresh_scene,
        fresh_screenshot,
        history,
    )
    assert issue == ""
    region = loop._region_state(runtime, "World").region(
        "Top Navigation Bar")
    assert region is not None and region["coverage_complete"] is True
    assert runtime.entry_review_deferred_frames == {}


def test_entry_review_can_add_visible_entries_omitted_by_page_survey(
    tmp_path,
) -> None:
    screenshot = _png("navy")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="World", summary="World clock", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-world", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    issue = loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="World",
            regions=[
                {
                    "name": "Top Navigation Bar",
                    "bbox_1000": [0, 0, 1000, 200],
                    "summary": "Primary page switches",
                    "coverage_complete": True,
                },
                {
                    "name": "World Clock Content",
                    "bbox_1000": [0, 200, 1000, 1000],
                    "summary": "World clock actions",
                    "survey_memory": (
                        "The visible clock rows are repeated content; "
                        "opening one representative remains unresolved."
                    ),
                    "coverage_complete": True,
                },
            ],
            new_entries=[{
                "region_name": "World Clock Content",
                "target": "Add World Clock button",
            }],
        ),
        scene,
        screenshot,
        history,
    )
    assert issue == ""
    loop._sync_exploration_task(runtime)
    view = loop._exploration_map_view(
        runtime, None, current_screenshot=screenshot)
    assert [item["name"] for item in view["pending_entry_review"]["regions"]] == [
        "Top Navigation Bar", "World Clock Content",
    ]
    assert view["pending_entry_review"]["regions"][1]["survey_memory"] == (
        "The visible clock rows are repeated content; "
        "opening one representative remains unresolved."
    )
    assert view["pending_entry_review"]["candidates"] == [{
        "region_name": "World Clock Content",
        "operation": "Add World Clock button",
        "subject": "World Clock Content",
        "target": "Add World Clock button",
    }]

    issue = loop._apply_entry_review(
        runtime,
        loop.EntryReview(
            independent_entries=[
                {
                    "region_name": "World Clock Content",
                    "target": "Add World Clock button",
                },
                {
                    "region_name": "Top Navigation Bar",
                    "target": "Alarms tab",
                },
                {
                    "region_name": "Top Navigation Bar",
                    "target": "Timer tab",
                },
            ],
        ),
        scene,
        screenshot,
        history,
    )

    assert issue == ""
    assert [entry.target for entry in runtime.entry_ledger.entries] == [
        "Add World Clock button", "Alarms tab", "Timer tab",
    ]
    assert [item["target"] for item in history[-1]["added"]] == [
        "Alarms tab", "Timer tab",
    ]


def test_parse_turn_accepts_page_update_without_a_gui_action() -> None:
    payload = {
        "screen": {
            "name": "Alarm", "summary": "Alarm list with one card",
            "identity": "known", "matched_page_name": "Alarm",
            "surface_kind": "page",
            "variant": {
                "name": "default", "identity": "known",
                "visible_predicates": ["Alarm list is visible"],
            },
        },
        "reason": "Alarm is the known Page and its visible structure can be registered now.",
        "page_update": {
            "page_name": "Alarm",
            "regions": [{
                "name": "Alarm List",
                "coverage_complete": True,
                "entries": [{"target": "Add alarm"}],
            }],
            "omitted_regions": [{
                "name": "Legacy Alarm Controls",
                "reason": "Replaced by the complete Alarm List region.",
            }],
        },
        "action": None,
    }

    turn, error = parse_turn(payload, has_previous=False)

    assert error == ""
    assert turn is not None
    assert turn.decision.action == "NONE"
    assert turn.page_update is not None
    assert turn.page_update.page_name == "Alarm"
    assert turn.page_update.regions == [{
        "name": "Alarm List", "coverage_complete": True,
    }]
    assert turn.page_update.new_entries == [{
        "region_name": "Alarm List", "target": "Add alarm",
    }]
    assert turn.page_update.omitted_regions == [{
        "name": "Legacy Alarm Controls",
        "reason": "Replaced by the complete Alarm List region.",
    }]


def test_parse_turn_preserves_independent_invalid_page_update_item() -> None:
    payload = {
        "screen": {
            "name": "Alarm", "summary": "Alarm list",
            "identity": "known", "matched_page_name": "Alarm",
            "surface_kind": "page",
            "variant": {
                "name": "default", "identity": "known",
                "visible_predicates": ["Alarm list is visible"],
            },
        },
        "reason": "Alarm is the known Page; preserve the independent valid update item.",
        "page_update": {
            "page_name": "Alarm",
            "regions": [{
                "name": "Main", "coverage_complete": True,
                "entries": [
                    {"target": "Bad model ID", "entry_id": "ae13"},
                    {"target": "Independent good item"},
                ],
            }],
        },
        "action": None,
    }

    turn, error = parse_turn(payload, has_previous=False)

    assert error == ""
    assert turn is not None and turn.page_update is not None
    assert turn.page_update.new_entries[0]["entry_id"] == "ae13"
    assert turn.page_update.new_entries[1]["target"] == "Independent good item"


def test_parse_turn_keeps_semantic_judgment_with_vlm() -> None:
    payload = {
        "screen": {
            "name": "Chats", "summary": "", "identity": "known",
            "matched_page_name": "Chats", "surface_kind": "page",
            "regions": [],
            "variant": {
                "name": "default", "identity": "known",
                "visible_predicates": ["Chat list is visible"],
            },
        },
        "reason": "Chats is still the current Page, but the identity proposal needs correction.",
        "previous_action": {
            "outcome": "not_applicable",
            "reason": "The screenshots do not provide enough evidence.",
            "matches_intent": True,

        },
        "task_progress": {"status": "working", "summary": ""},
        "loop_assessment": {"status": "progress", "summary": ""},
        "previous_tool_review": {
            "decision": "reject",
            "reason": "The proposal lacks enough visual evidence.",
        },
        "page_update": None,
        "action": {
            "tool_name": "page_identity", "tool_arguments": {
                "suspected_pages": ["Chats"],
                "proposed_new_name": "",
                    "reason": "Compare the current foreground with Chats.",
            },
        },
    }

    turn, error = parse_turn(
        payload,
        has_previous=True,
        requires_tool_review=True,
        available_tools=["page_identity"],
    )

    assert error == ""
    assert turn is not None
    assert turn.previous.outcome == "uncertain"
    assert turn.previous.reason == (
        "The screenshots do not provide enough evidence."
    )
    assert not hasattr(turn, "task_progress")
    assert turn.previous_tool_review == PreviousToolReview(
        "reject", "The proposal lacks enough visual evidence.")


def test_parse_turn_requires_reason_for_abnormal_previous_action() -> None:
    payload = {
        "screen": {
            "name": "Recipes", "identity": "known",
            "variant": {
                "name": "default", "identity": "known",
                "visible_predicates": ["Recipe list is visible"],
            },
        },
        "reason": "Recipes remains the current Page after the attempted click.",
        "previous_action": {
            "outcome": "no_visible_change",
            "reason": "",
            "matches_intent": False,
        },
        "action": None,
    }

    turn, error = parse_turn(payload, has_previous=True)

    assert turn is None
    assert "previous_action.reason is required" in error


def test_parse_turn_accepts_business_effect_kinds_and_rejects_old_key() -> None:
    payload = {
        "screen": {
            "name": "World",
            "identity": "known",
            "variant": {
                "name": "search results",
                "identity": "known",
                "visible_predicates": ["Tokyo appears in the result list"],
            },
        },
        "reason": "The submitted query produced a visible Tokyo result.",
        "previous_action": {
            "outcome": "changed",
            "reason": "No result was visible before; Tokyo is visible now.",
            "matches_intent": True,
            "failure_kind": None,
            "business_effect": {
                "effect_kind": "query_result",
                "region_name": "City search results",
                "capability_name": "Search cities",
                "fact": "city.search_result",
                "before_value": "none",
                "after_value": "Tokyo",
                "parameter_bindings": {"query": "Tokyo"},
            },
        },
        "action": None,
    }

    turn, error = parse_turn(payload, has_previous=True)

    assert error == ""
    assert turn is not None
    assert turn.previous.business_effect == ObservedBusinessEffect(
        effect_kind="query_result",
        region_name="City search results",
        capability_name="Search cities",
        fact="city.search_result",
        before_value="none",
        after_value="Tokyo",
        parameter_bindings={"query": "Tokyo"},
    )

    removal_payload = json.loads(json.dumps(payload))
    removal_payload["previous_action"]["business_effect"].update({
        "effect_kind": "object_removal",
        "capability_name": "Delete city",
        "fact": "city.row",
        "before_value": "Tokyo",
        "after_value": "absent",
        "parameter_bindings": {"city": "Tokyo"},
    })
    removal_turn, removal_error = parse_turn(
        removal_payload, has_previous=True)

    assert removal_error == ""
    assert removal_turn is not None
    assert removal_turn.previous.business_effect is not None
    assert removal_turn.previous.business_effect.effect_kind == "object_removal"

    same_operation_payload = json.loads(json.dumps(payload))
    same_operation_payload["previous_action"]["business_effect"].update({
        "same_operation_entry_ids": ["ae2", "ae3"],
        "same_operation_reason": (
            "Both entries are parameter values of one reviewed control group."
        ),
    })
    same_operation_turn, same_operation_error = parse_turn(
        same_operation_payload, has_previous=True)

    assert same_operation_error == ""
    assert same_operation_turn is not None
    assert same_operation_turn.previous.business_effect is not None
    assert same_operation_turn.previous.business_effect.same_operation_entry_ids == [
        "ae2", "ae3",
    ]

    invalid_binding = json.loads(json.dumps(payload))
    invalid_binding["previous_action"]["business_effect"][
        "parameter_bindings"] = {"city query": "Tokyo"}
    invalid_turn, invalid_error = parse_turn(
        invalid_binding, has_previous=True)

    assert invalid_turn is None
    assert "portable unique identifiers" in invalid_error

    old_previous = dict(payload["previous_action"])
    old_previous["state_change"] = old_previous.pop("business_effect")
    old_payload = {**payload, "previous_action": old_previous}
    old_turn, old_error = parse_turn(old_payload, has_previous=True)

    assert old_turn is None
    assert "unsupported fields: ['state_change']" in old_error


def test_parse_turn_distinguishes_empty_business_effect_values_from_missing(
) -> None:
    payload = {
        "screen": {
            "name": "Alarms",
            "identity": "known",
            "variant": {
                "name": "New Alarm Modal",
                "identity": "known",
                "visible_predicates": ["The New Alarm modal is visible"],
            },
        },
        "reason": "The alarm name field visibly changed.",
        "previous_action": {
            "outcome": "changed",
            "reason": "The Name field changed as requested.",
            "matches_intent": True,
            "failure_kind": None,
            "business_effect": {
                "effect_kind": "state_change",
                "region_name": "Alarm Configuration Fields",
                "capability_name": "Alarm naming",
                "fact": "Name input value",
                "before_value": "",
                "after_value": "Test Alarm",
                "parameter_bindings": {"alarm_name": "Test Alarm"},
            },
        },
        "action": None,
    }

    entered, entered_error = parse_turn(payload, has_previous=True)

    assert entered_error == ""
    assert entered is not None
    assert entered.previous.business_effect is not None
    assert entered.previous.business_effect.before_value == ""
    assert entered.previous.business_effect.after_value == "Test Alarm"

    cleared_payload = json.loads(json.dumps(payload))
    cleared_effect = cleared_payload["previous_action"]["business_effect"]
    cleared_effect["before_value"] = "Test Alarm"
    cleared_effect["after_value"] = ""
    cleared_effect["parameter_bindings"] = {}
    cleared, cleared_error = parse_turn(
        cleared_payload, has_previous=True)

    assert cleared_error == ""
    assert cleared is not None
    assert cleared.previous.business_effect is not None
    assert cleared.previous.business_effect.before_value == "Test Alarm"
    assert cleared.previous.business_effect.after_value == ""

    missing_payload = json.loads(json.dumps(payload))
    del missing_payload["previous_action"]["business_effect"]["before_value"]
    missing, missing_error = parse_turn(
        missing_payload, has_previous=True)

    assert missing is None
    assert "requires fields: ['before_value']" in missing_error

    non_string_payload = json.loads(json.dumps(payload))
    non_string_payload["previous_action"]["business_effect"][
        "after_value"] = None
    non_string, non_string_error = parse_turn(
        non_string_payload, has_previous=True)

    assert non_string is None
    assert "value fields must be strings: ['after_value']" in non_string_error

    unchanged_payload = json.loads(json.dumps(payload))
    unchanged_payload["previous_action"]["business_effect"][
        "after_value"] = ""
    unchanged, unchanged_error = parse_turn(
        unchanged_payload, has_previous=True)

    assert unchanged is None
    assert "requires distinct before/after values" in unchanged_error


def test_parse_turn_requires_reason_for_every_main_turn() -> None:
    turn, error = parse_turn({
        "screen": {"name": "Recipes", "identity": "known"},
        "action": None,
    }, has_previous=False)

    assert turn is None
    assert "reason is required" in error


def test_parse_turn_rejects_removed_direct_click_interface() -> None:
    payload = {
        "screen": {
            "name": "Chats", "summary": "Chat list is visible",
            "identity": "new", "matched_page_name": "",
            "surface_kind": "page", "regions": [],
            "variant": {
                "name": "default", "identity": "new",
                "visible_predicates": ["Chat list is visible"],
            },
        },
        "reason": "Chats is a new Page and Weekend Plan is the next visible entry.",
        "previous_action": {
            "outcome": "not_applicable",
            "summary": "No previous action",

        },
        "task_progress": {
            "status": "working", "summary": "Open one conversation",
        },
        "loop_assessment": {"status": "progress", "summary": "First action"},
        "previous_tool_review": None,
        "page_update": None,
        "action": {
            "type": "CLICK", "target": "Weekend Plan",
            "point_1000": [1200, 315], "direction": None,
            "reason": "Open it",
            "tool_name": "", "tool_arguments": {
                "page_name": "", "region_name": "", "bbox_1000": None,
                "suspected_pages": [], "proposed_new_name": "", "reason": "",
            },
        },
    }

    turn, error = parse_turn(payload, has_previous=False)

    assert turn is None
    assert "action has unsupported fields" in error


def test_completed_map_does_not_run_unassigned_dialog_actions(tmp_path) -> None:
    home = {"screenshot": _png("white")}
    dialog = {"screenshot": _png("gray")}
    details = {"screenshot": _png("blue")}
    runtime, env, agent = _runtime(
        tmp_path,
        home,
        [
            _turn(
                "Home", action="CLICK", identity="known",
                target="More", point=[800, 200],
            ),
            _turn(
                "Notice", action="NONE", identity="known",
                outcome="changed", corrected_target="More",
            ),
            _turn(
                "Notice", action="CLICK", identity="known",
                target="Got it", point=[500, 700],
            ),
            _turn(
                "Details", action="NONE", identity="known",
                outcome="changed", corrected_target="Got it",
            ),
            _turn("Details", action="FINISH", identity="known"),
        ],
        [dialog, details],
    )
    for page_name, screenshot in (
        ("Home", home["screenshot"]),
        ("Notice", dialog["screenshot"]),
        ("Details", details["screenshot"]),
    ):
        runtime.protocol_map.observe(
            name=page_name, summary=f"Visible {page_name}", identity="new",
            matched_page_name="", surface_kind="page", regions=(),
            screenshot=screenshot, commit_regions=False,
        )
        _complete_fixture_survey(runtime, page_name, screenshot)
    runtime.protocol_map.observe(
        name="Home", summary="Visible Home", identity="known",
        matched_page_name="Home", surface_kind="page", regions=(),
        screenshot=home["screenshot"], commit_regions=False,
    )

    graph = loop.run_autonomous_traversal(runtime, home)

    assert graph.stop_reason == "framework_complete"
    assert runtime.action_count == 0
    assert env.actions == []
    assert agent.calls == []


def test_completed_map_does_not_consume_stale_settlement_turns(tmp_path) -> None:
    before = {"screenshot": _png("red")}
    after = {"screenshot": _png("green")}
    runtime, _env, _agent = _runtime(
        tmp_path,
        before,
        [
            _turn(
                "Chat", action="CLICK", identity="known",
                target="Plus", point=[900, 700]),
            _turn(
                "Attachment menu", action="NONE", identity="known",
                outcome="changed",
                corrected_target="Add attachment",
            ),
            _turn("Attachment menu", action="FINISH", identity="known"),
        ],
        [after],
    )
    for page_name, screenshot in (
        ("Chat", before["screenshot"]),
        ("Attachment menu", after["screenshot"]),
    ):
        runtime.protocol_map.observe(
            name=page_name, summary=f"Visible {page_name}", identity="new",
            matched_page_name="", surface_kind="page", regions=(),
            screenshot=screenshot, commit_regions=False,
        )
        _complete_fixture_survey(runtime, page_name, screenshot)
    runtime.protocol_map.observe(
        name="Chat", summary="Visible Chat", identity="known",
        matched_page_name="Chat", surface_kind="page", regions=(),
        screenshot=before["screenshot"], commit_regions=False,
    )

    graph = loop.run_autonomous_traversal(runtime, before)

    assert graph.stop_reason == "framework_complete"
    assert graph.action_edges == []




def test_reviewer_unsafe_task_is_recorded_without_repeated_dispatch(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("black")}
    frame_id = loop.screenshot_frame_id(screen["screenshot"])
    runtime, env, _agent = _runtime(tmp_path, screen, [])
    runtime.protocol_map.observe(
        name="Alarm", summary="Alarm page", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"],
    )
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Alarm", region_name="Alarm List",
        frame_id=frame_id,
        observations=[{"target": "Delete Button"}],
    ).added[0]
    _complete_fixture_survey(
        runtime, "Alarm", screen["screenshot"],
        region_names=("Main", "Alarm List"))
    reviews = []

    def reject_unsafe(request):
        reviews.append(request)
        return {
            "decision": "reject",
            "observed_target": "Delete Button",
            "point_matches_target": True,
            "target_matches_request": True,
            "risk": "unsafe",
            "reason": "The click itself may delete user data.",
        }

    runtime.click_reviewer = reject_unsafe
    runtime.decision_agent.turns = iter([
        _turn(
            "Alarm", action="CALL_TOOL", target="Delete Button",
            identity="known", page_update=_simple_page_update("Alarm"),
            tool_name="click", tool_arguments={
                "target": "Delete Button",
                "point_1000": [500, 600],
                "entry_id": entry_id,
            }),
        _turn(
            "Alarm", action="CALL_TOOL", identity="known",
            tool_name="finish_exploration", tool_arguments={
                "reason": "The unsafe entry is already retired by review.",
                "unreachable_evidence": [],
            }),
    ])

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "framework_partial"
    assert env.actions == []
    record = runtime.entry_ledger.get(entry_id)
    assert record.status.value == "unresolved"
    assert record.task_eligible is False
    assert runtime.exploration_task is None
    assert reviews[0]["requested_entry"] == {
        "page_name": "Alarm",
        "region_name": "Alarm List",
        "target": "Delete Button",
        "operation": "Delete Button",
        "subject": "Alarm List",
        "control_type": "control",
        "current_value": "",
    }
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    rejection = next(
        item for item in trace["history"]
        if item.get("kind") == "click_review")
    assert rejection["entry_disposition"] == {
        "entry_id": entry_id,
        "status": "unresolved",
        "task_eligible": False,
        "reason": "The click itself may delete user data.",
    }


def test_hidden_finish_tool_cannot_override_unverified_entry_tasks(tmp_path) -> None:
    screen = {"screenshot": _png("purple")}
    runtime, _env, _agent = _runtime(
        tmp_path,
        screen,
        [
            _turn(
                "Chats", action="NONE", identity="known",
                page_update=_simple_page_update("Chats"),
            ),
            _turn("Chats", action="NONE", identity="known"),
            _turn(
                "Chats", action="CALL_TOOL", identity="known",
                tool_name="finish_exploration", tool_arguments={
                    "reason": "Propose completion.",
                    "unreachable_evidence": [],
                },
            ),
        ],
    )
    runtime.entry_ledger.record_agent_update(
        page_name="Chats",
        region_name="Main",
        frame_id=loop.screenshot_frame_id(screen["screenshot"]),
        observations=[
            {"target": "Contacts"},
            {"target": "Explore"},
        ],
    )
    runtime.protocol_map.observe(
        name="Chats", summary="Visible Chats", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "all_remaining_work_suspended"
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    assert not any(item.get("kind") == "finish_gap" for item in trace["history"])
    assert all(
        runtime.entry_ledger.get(entry_id).status.value == "discovered"
        for entry_id in ("ae1", "ae2")
    )


def test_hidden_finish_tool_does_not_accept_text_only_unreachable_evidence(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("purple")}
    runtime, _env, _agent = _runtime(
        tmp_path,
        screen,
        [
            _turn(
                "Chats", action="NONE", identity="known",
                page_update=_simple_page_update("Chats"),
            ),
            _turn("Chats", action="NONE", identity="known"),
            _turn(
                "Chats", action="CALL_TOOL", identity="known",
                tool_name="finish_exploration", tool_arguments={
                    "reason": "One repeated task is unreachable.",
                    "unreachable_evidence": [{
                        "page_name": "Chats",
                        "entry_id": "ae1",
                        "subject": "Contacts",
                        "evidence": (
                            "Repeated clicks landed on the same wrong page."
                        ),
                    }],
                },
            ),
        ],
    )
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Chats",
        region_name="Main",
        frame_id=loop.screenshot_frame_id(screen["screenshot"]),
        observations=[{"target": "Contacts"}],
    ).added[0]
    runtime.protocol_map.observe(
        name="Chats", summary="Visible Chats", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert entry_id == "ae1"
    assert graph.stop_reason != "model_finished"
    record = runtime.entry_ledger.get(entry_id)
    assert record.status.value == "discovered"
    assert record.task_eligible is True
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    assert not any(
        item.get("kind") == "unreachable_evidence"
        for item in trace["history"]
    )


def test_completed_map_does_not_run_unassigned_no_effect_probe(tmp_path) -> None:
    screen = {"screenshot": _png("yellow")}
    runtime, env, _agent = _runtime(
        tmp_path,
        screen,
            [
                _turn(
                    "Search", action="CALL_TOOL", identity="known",
                    target="Message",
                    tool_name="click", tool_arguments={
                        "target": "Message", "point_1000": [500, 500],
                        "entry_id": "",
                    }),
                _turn(
                    "Search", action="CALL_TOOL", identity="known",
                    outcome="no_visible_change", corrected_target="Message input",
                    tool_name="finish_exploration", tool_arguments={
                        "reason": "Propose completion.",
                        "unreachable_evidence": [],
                    },
                ),
        ],
        [screen],
    )
    _bind_incomplete_page(runtime, "Search", screen["screenshot"])
    _complete_fixture_survey(runtime, "Search", screen["screenshot"])

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "framework_complete"
    assert env.actions == []
    assert graph.action_edges == []


def test_completed_map_ignores_stale_identical_frame_assessments(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("yellow")}
    frame_id = loop.screenshot_frame_id(screen["screenshot"])
    runtime, env, _agent = _runtime(
        tmp_path,
        screen,
        [
            _turn(
                "Timer", action="CALL_TOOL", identity="known",
                target="00 Shortcut Button",
                tool_name="click", tool_arguments={
                    "target": "00 Shortcut Button",
                    "point_1000": [300, 600],
                    "entry_id": "",
                }),
            _turn(
                "Timer", action="CALL_TOOL", identity="known",
                outcome="changed", corrected_target="Backspace Button",
                target="Backspace Button", tool_name="click",
                tool_arguments={
                    "target": "Backspace Button",
                    "point_1000": [700, 600],
                    "entry_id": "",
                }),
                _turn(
                    "Timer", action="CALL_TOOL", identity="known",
                    outcome="no_visible_change",
                    corrected_target="00 Shortcut Button",
                    tool_name="finish_exploration", tool_arguments={
                        "reason": "No remaining gap.",
                        "unreachable_evidence": [],
                    }),
                _turn(
                    "Timer", action="CALL_TOOL", identity="known",
                    tool_name="finish_exploration", tool_arguments={
                        "reason": "No remaining gap.",
                        "unreachable_evidence": [],
                    }),
            ],
        [screen],
    )
    _bind_incomplete_page(runtime, "Timer", screen["screenshot"])
    _complete_fixture_survey(runtime, "Timer", screen["screenshot"])

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "framework_complete"
    assert env.actions == []
    assert graph.action_edges == []


def test_no_change_cannot_settle_on_another_known_page(
    tmp_path,
) -> None:
    home = {"screenshot": _png("navy")}
    landing = {"screenshot": _png("orange")}
    runtime, env, _agent = _runtime(
        tmp_path,
        home,
        [
            _turn(
                "Home", action="CALL_TOOL", identity="known",
                target="Browse library", tool_name="click",
                tool_arguments={
                    "target": "Browse library", "entry_id": "",
                    "point_1000": [500, 500],
                },
            ),
            _turn(
                "Pantry", action="NONE", identity="known",
                outcome="no_visible_change",
                corrected_target="Browse library", matches_intent=False,
            ),
            _turn(
                "Pantry", action="NONE", identity="known",
                outcome="changed", corrected_target="Browse library",
            ),
        ],
        [landing],
        max_actions=1,
    )
    runtime.protocol_map.observe(
        name="Pantry", summary="Pantry", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=_png("blue"), commit_regions=False,
    )
    runtime.protocol_map.observe(
        name="Home", summary="Home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=home["screenshot"], commit_regions=False,
    )
    _complete_fixture_survey(runtime, "Home", home["screenshot"])

    graph = loop.run_autonomous_traversal(runtime, home)

    assert graph.stop_reason == "framework_partial"
    assert len(env.actions) == 0
    assert runtime.protocol_map.current_page == "Home"


def test_completed_map_does_not_consume_unregistered_page_settlement(
    tmp_path,
) -> None:
    home = {"screenshot": _png("navy")}
    runtime, env, _agent = _runtime(
        tmp_path,
        home,
        [
            _turn(
                "Home", action="CALL_TOOL", identity="known",
                target="Browse library", tool_name="click",
                tool_arguments={
                    "target": "Browse library", "entry_id": "",
                    "point_1000": [500, 500],
                },
            ),
            _turn(
                "Pantry", action="NONE", identity="known",
                outcome="no_visible_change",
                corrected_target="Browse library", matches_intent=False,
            ),
            _turn(
                "Home", action="NONE", identity="known",
                outcome="no_visible_change",
                corrected_target="Browse library", matches_intent=False,
            ),
        ],
        [home],
        max_actions=1,
    )
    runtime.protocol_map.observe(
        name="Home", summary="Home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=home["screenshot"], commit_regions=False,
    )
    _complete_fixture_survey(runtime, "Home", home["screenshot"])

    graph = loop.run_autonomous_traversal(runtime, home)

    assert len(env.actions) == 0
    assert runtime.protocol_map.current_page == "Home"
    assert graph.stop_reason == "framework_complete"


def test_no_visible_change_verifies_bound_entry_and_closes_task(tmp_path) -> None:
    screen = {"screenshot": _png("yellow")}
    frame_id = loop.screenshot_frame_id(screen["screenshot"])
    runtime, env, _agent = _runtime(tmp_path, screen, [], [screen])
    runtime.protocol_map.observe(
        name="Timer", summary="Timer page", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"],
    )
    added = runtime.entry_ledger.record_agent_update(
        page_name="Timer", region_name="Numeric Keypad",
        frame_id=frame_id,
        observations=[{"target": "00 Shortcut Button"}],
    ).added[0]
    _complete_fixture_survey(
        runtime, "Timer", screen["screenshot"],
        region_names=("Main", "Numeric Keypad"))
    runtime.decision_agent.turns = iter([
        _turn(
            "Timer", action="CALL_TOOL", target="00 Shortcut Button",
            identity="known", page_update=_simple_page_update("Timer"),
            tool_name="click", tool_arguments={
                "target": "00 Shortcut Button",
                "point_1000": [300, 600],
                "entry_id": added,
            }),
        _turn(
            "Timer", action="CALL_TOOL", identity="known",
            outcome="no_visible_change",
            corrected_target="00 Shortcut Button",
            tool_name="finish_exploration", tool_arguments={
                "reason": "The no-effect behavior was observed.",
                "unreachable_evidence": [],
            }),
        _turn(
            "Timer", action="CALL_TOOL", identity="known",
            tool_name="finish_exploration", tool_arguments={
                "reason": "The no-effect behavior was observed.",
                "unreachable_evidence": [],
            }),
    ])

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "framework_complete"
    assert len(env.actions) == 1
    record = runtime.entry_ledger.get(added)
    assert record.status.value == "verified"
    assert record.task_eligible is False
    loop._sync_exploration_task(runtime)
    assert runtime.exploration_task is None


def test_changed_result_cannot_rename_reviewer_bound_entry(
    tmp_path,
) -> None:
    expanded = {"screenshot": _png("yellow")}
    collapsed = {"screenshot": _png("green")}
    frame_id = loop.screenshot_frame_id(expanded["screenshot"])
    runtime, env, _agent = _runtime(
        tmp_path, expanded, [], [collapsed], max_actions=1)
    runtime.protocol_map.observe(
        name="Alarm", summary="Expanded alarm card", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=expanded["screenshot"],
    )
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Alarm", region_name="Alarm Card",
        frame_id=frame_id,
        observations=[{"target": "Vibrate Toggle"}],
    ).added[0]
    _complete_fixture_survey(
        runtime, "Alarm", expanded["screenshot"],
        region_names=("Main", "Alarm Card"))
    runtime.decision_agent.turns = iter([
        _turn(
            "Alarm", action="CALL_TOOL", target="Vibrate Toggle",
            identity="known", tool_name="click", tool_arguments={
                "target": "Vibrate Toggle",
                "point_1000": [880, 580],
                "entry_id": entry_id,
            }),
        _turn(
            "Alarm", action="CALL_TOOL", identity="known",
            outcome="changed", corrected_target="Alarm Expand Arrow",
            matches_intent=False,
            tool_name="finish_exploration", tool_arguments={
                "reason": "Review remaining gaps.",
                "unreachable_evidence": [],
            }),
    ])

    graph = loop.run_autonomous_traversal(runtime, expanded)

    assert len(env.actions) == 1
    record = runtime.entry_ledger.get(entry_id)
    assert record.status.value == "unresolved"
    assert record.task_eligible is True
    assert graph.action_edges[0]["attempts"][0]["element_label"] == (
        "Vibrate Toggle")
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    feedback = next(
        item for item in trace["history"]
        if item.get("rejection", {}).get("code")
        == "action_did_not_match_entry"
    )
    assert feedback["entry_id"] == entry_id
    assert feedback["target"] == "Vibrate Toggle"
    assert "actual_target" not in feedback
    assert "Reviewer-confirmed target 'Vibrate Toggle'" in feedback["detail"]


def test_unexplained_page_change_is_rejected_without_screenshot_identity(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("teal")}
    turns = [_turn(
        "Pantry", action="CALL_TOOL", identity="new",
        tool_name="navigate", tool_arguments={"operation": "back"},
    )]
    runtime, env, _agent = _runtime(
        tmp_path, screen, turns, [screen], max_actions=1)
    runtime.protocol_map.observe(
        name="Recipe collection", summary="Recipes", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert len(env.actions) == 0
    assert list(runtime.protocol_map.pages) == ["Recipe collection"]
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    conflict = next(
        item for item in trace["history"]
        if item.get("rejection", {}).get("code") == "page_identity_conflict"
    )
    assert "Recipe collection" in conflict["detail"]
    assert "Pantry" in conflict["detail"]
    assert "call page_identity" in conflict["detail"]


def test_pending_changed_landing_uses_agent_reported_known_page(tmp_path) -> None:
    source = {"screenshot": _png("orange")}
    landing = {"screenshot": _png("teal")}
    runtime, env, _agent = _runtime(
        tmp_path, source, [], [landing], max_actions=1,
    )
    runtime.protocol_map.observe(
        name="Recipe collection", summary="Recipes", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=landing["screenshot"], commit_regions=False,
    )
    runtime.protocol_map.observe(
        name="Sunday tomato pasta", summary="Recipe detail", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=source["screenshot"], commit_regions=False,
    )
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Sunday tomato pasta", region_name="Main",
        frame_id=loop.screenshot_frame_id(source["screenshot"]),
        observations=[{"target": "Back button"}],
    ).added[0]
    _complete_fixture_survey(
        runtime, "Sunday tomato pasta", source["screenshot"])
    runtime.decision_agent.turns = iter([
        _turn(
            "Sunday tomato pasta", action="CALL_TOOL", identity="known",
            target="Back button", tool_name="click",
            tool_arguments={
                "target": "Back button", "entry_id": entry_id,
                "point_1000": [60, 35],
            },
        ),
        _turn(
            "Recipe collection", action="NONE", identity="known",
            outcome="changed", corrected_target="Back button",
        ),
    ])

    graph = loop.run_autonomous_traversal(runtime, source)

    assert len(env.actions) == 1
    assert graph.stop_reason == "max_actions"
    assert runtime.protocol_map.current_page == "Recipe collection"
    assert runtime.protocol_map.connections == [{
        "from": "Sunday tomato pasta", "via": "Back button",
        "action": "CLICK", "to": "Recipe collection",
        "provenance": "observed",
    }]


def test_page_identity_can_propose_a_new_page_without_hash_authority(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("teal")}
    resolver_calls = []

    def resolver(request):
        resolver_calls.append(request)
        return {
            "status": "new",
            "page_name": "Pantry",
            "matched_page_name": "",
            "surface_kind": "page",
            "summary": "Pantry",
            "reason": "The foreground has distinct Pantry content.",
        }

    turns = [
        _turn(
            "Pantry", action="CALL_TOOL", identity="new",
            tool_name="page_identity", tool_arguments={
                "suspected_pages": ["Recipe collection"],
                "proposed_new_name": "Pantry",
            },
        ),
        _turn(
            "Pantry", action="NONE", identity="new",
            tool_review={
                "decision": "accept",
                "reason": "The specialist evidence supports a distinct Page.",
            },
        ),
    ]
    runtime, env, _agent = _runtime(
        tmp_path, screen, turns, [screen], max_actions=1,
        identity_resolver=resolver,
    )
    runtime.protocol_map.observe(
        name="Recipe collection", summary="Recipes", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert len(resolver_calls) == 1
    assert runtime.pending_page_identity is None
    assert list(runtime.protocol_map.pages) == ["Recipe collection", "Pantry"]
    assert len(env.actions) == 0
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    assert any(
        item.get("kind") == "tool" and item.get("tool_name") == "page_identity"
        for item in trace["history"])
    assert not any(
        item.get("rejection", {}).get("code") == "page_identity_conflict"
        for item in trace["history"])


def test_timer_landing_context_resolves_page_before_owned_variant_candidates(
    tmp_path,
) -> None:
    frame = {"screenshot": _png("cyan")}
    runtime, _env, _agent = _runtime(tmp_path, frame, [])
    runtime.protocol_map.observe(
        name="Alarms", summary="Alarm list", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=_png("red"), variant_name="empty_state",
        variant_identity="new", commit_regions=False,
    )
    runtime.protocol_map.observe(
        name="Alarms", summary="New alarm dialog", identity="known",
        matched_page_name="Alarms", surface_kind="dialog", regions=(),
        screenshot=_png("orange"), variant_name="new_alarm_dialog",
        variant_identity="new", commit_regions=False,
    )
    runtime.protocol_map.observe(
        name="Timer", summary="Timer setup", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=_png("blue"), variant_name="initial_state",
        variant_identity="new", commit_regions=False,
    )
    runtime.exploration_task = ExplorationTask(
        task_type="explore_entry",
        task_id="explore:ae10",
        entry_id="ae10",
        page_name="Alarms",
        region_name="Navigation",
        target="Timer tab",
        phase="locate_entry",
    )
    pending = loop.PendingAction(
        source=loop.ObservedScene(
            state_id="alarms-empty",
            screenshot=_png("red"),
            page_name="Alarms",
            variant_name="empty_state",
        ),
        event_index=27,
        primitive={"action_type": "CLICK"},
        target="Timer tab",
        reason="Open Timer",
        history_index=0,
        evidence={},
    )

    page_view = _exploration_map_view(
        runtime, pending, current_screenshot=frame["screenshot"])

    assert page_view["task"]["phase"] == "identify_page"
    assert "known_variants" not in page_view
    assert "variant_candidates" not in page_view
    assert all("variants" not in page for page in page_view["pages"])
    assert page_view["pending_action"]["source_page"] == "Alarms"
    assert "source_variant" not in page_view["pending_action"]

    pending.assessment = PreviousAssessment(
        outcome="changed",
        reason="The Timer setup surface appeared.",
        matches_intent=True,
    )
    runtime.pending_landing_page = PendingLandingPage(
        page_name="Timer",
        identity="known",
    )
    variant_view = _exploration_map_view(
        runtime, pending, current_screenshot=frame["screenshot"])

    assert variant_view["task"]["phase"] == "identify_variant"
    assert variant_view["selected_page"] == {
        "name": "Timer", "identity": "known",
    }
    assert variant_view["variant_candidates"] == [{
        "name": "initial_state",
        "visible_predicates": [],
    }]
    assert "pending_action" not in variant_view
    assert "empty_state" not in json.dumps(variant_view, ensure_ascii=False)
    assert "new_alarm_dialog" not in json.dumps(
        variant_view, ensure_ascii=False)


def test_unbound_restored_map_reenters_page_stage_without_variant_facts(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("cyan")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.protocol_map.observe(
        name="Timer", summary="Timer setup", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], variant_name="initial_state",
        variant_identity="new", commit_regions=False,
    )
    runtime.protocol_map.current_page = ""
    runtime.protocol_map.current_variant = ""
    runtime.exploration_task = ExplorationTask(
        task_type="route_to_page",
        task_id="route:Timer",
        page_name="Timer",
        phase="route_to_page",
    )

    view = _exploration_map_view(runtime, None, screen["screenshot"])

    assert loop._identity_stage(runtime) == "page"
    assert view["task"]["phase"] == "identify_page"
    assert "current_variant" not in view
    assert "variant_candidates" not in view
    assert all("variants" not in page for page in view["pages"])
    assert "initial_state" not in json.dumps(view, ensure_ascii=False)


def test_unbound_resume_identifies_live_frame_before_completion(
    tmp_path, monkeypatch,
) -> None:
    screen = {"screenshot": _png("cyan")}
    runtime, _env, agent = _runtime(tmp_path, screen, [
        _turn(
            "Timer", action="NONE", identity="known",
            variant_name="initial_state", variant_identity="known",
        ),
    ])
    runtime.protocol_map.observe(
        name="Timer", summary="Timer setup", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], variant_name="initial_state",
        variant_identity="new", commit_regions=False,
    )
    runtime.protocol_map.current_page = ""
    runtime.protocol_map.current_variant = ""
    monkeypatch.setattr(loop, "_sync_exploration_task", lambda _host: None)
    monkeypatch.setattr(
        loop, "_completion_gaps", lambda _host: ["one deferred Region"])

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert agent.calls
    phases = [
        call[2]["exploration_map"]["task"]["phase"]
        for call in agent.calls
    ]
    assert phases[0] == "identify_page"
    assert "identify_variant" in phases


def test_page_stage_never_commits_injected_variant_fields_in_same_turn(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [
        _turn(
            "Home", action="NONE", identity="new",
            variant_name="legacy_combined", variant_identity="new",
        ),
    ])
    runtime.decision_agent.auto_stage_variants = False

    loop.run_autonomous_traversal(runtime, screen)

    assert runtime.protocol_map.pages == {}
    assert runtime.pending_landing_page is not None
    assert runtime.pending_landing_page.page_name == "Home"


def test_variant_page_dispute_reopens_page_only_specialist(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("teal")}
    resolver_calls = []

    def resolver(request):
        resolver_calls.append(request)
        return {
            "status": "known",
            "page_name": "Recipe collection",
            "matched_page_name": "Recipe collection",
            "surface_kind": "page",
            "summary": "Recipes",
            "supporting_evidence": ["The recipe list anchor is visible."],
            "conflicting_evidence": [],
            "checked_candidates": ["Recipe collection"],
            "reason": "The selected Timer owner was wrong.",
        }

    runtime, _env, _agent = _runtime(
        tmp_path,
        screen,
        [_turn(
            "Timer", action="CALL_TOOL", identity="known",
            tool_name="report_record_error", tool_arguments={
                "kind": "page_identity",
                "subject": "Timer",
                "observed_problem": "The screenshot is the recipe list.",
            },
        )],
        identity_resolver=resolver,
    )
    runtime.protocol_map.observe(
        name="Recipe collection", summary="Recipes", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], variant_name="default",
        variant_identity="new", commit_regions=False,
    )
    runtime.protocol_map.observe(
        name="Timer", summary="Timer setup", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=_png("blue"), variant_name="initial_state",
        variant_identity="new", commit_regions=False,
    )
    runtime.protocol_map.current_page = "Recipe collection"
    runtime.protocol_map.current_variant = "default"
    runtime.pending_landing_page = PendingLandingPage(
        page_name="Timer", identity="known",
        summary="Timer setup", surface_kind="page",
    )

    loop.run_autonomous_traversal(runtime, screen)

    assert len(resolver_calls) == 1
    request = resolver_calls[0]
    assert request["identity_stage"] == "page"
    assert request["proposed_new_name"] == ""
    assert request["selected_page"] == {}
    assert all("variants" not in page for page in request["registered_pages"])
    assert request["arrival_context"]["page_identity_dispute"] == {
        "disputed_staged_page": "Timer",
        "trusted_source_page": "Recipe collection",
        "observed_problem": "The screenshot is the recipe list.",
    }
    assert runtime.pending_landing_page is None
    assert runtime.pending_page_identity is not None
    assert runtime.pending_page_identity.stage == "page"


def test_prompt_view_uses_current_semantic_page_not_screenshot_bytes(
    tmp_path,
) -> None:
    recipe = _png("teal")
    sunday = _png("red")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": recipe}, [])
    runtime.protocol_map.observe(
        name="Recipe collection", summary="Recipes", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=recipe, commit_regions=False,
    )
    runtime.protocol_map.observe(
        name="Sunday tomato pasta", summary="Recipe detail", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=sunday, commit_regions=False,
    )

    view = loop._exploration_map_view(
        runtime, None, current_screenshot=recipe)

    assert runtime.protocol_map.current_page == "Sunday tomato pasta"
    assert view["current_page"] == "Sunday tomato pasta"


def test_page_identity_dispute_returns_readable_specialist_feedback(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("teal")}
    resolver_calls = []

    def resolver(request):
        resolver_calls.append(request)
        if request.get("identity_stage") == "variant":
            return {
                "variant_identity": "known",
                "variant_name": "default",
                "visible_predicates": [],
                "checked_candidates": ["default"],
                "reason": "The material fixture state is unchanged.",
            }
        return {
            "status": "known",
            "page_name": "Recipe collection",
            "matched_page_name": "Recipe collection",
            "surface_kind": "page",
            "summary": "The same recipe list after scrolling.",
            "checked_candidates": ["Recipe collection"],
            "reason": "The content matches the registered Page.",
        }

    turns = [
        _turn(
            "Pantry", action="CALL_TOOL", identity="new",
            tool_name="report_record_error", tool_arguments={
                "kind": "page_identity", "subject": "Recipe collection",
                "observed_problem": "The sticky shell says Pantry.",
            },
        ),
        _turn(
            "Recipe collection", action="CALL_TOOL", identity="known",
            tool_review={
                "decision": "accept", "reason": "The specialist matched it.",
            },
            tool_name="navigate", tool_arguments={"operation": "back"},
        ),
        _turn(
            "Recipe collection", action="CALL_TOOL", identity="known",
            tool_name="navigate", tool_arguments={"operation": "back"},
        ),
        _turn(
            "Recipe collection", action="NONE", identity="known",
            outcome="no_visible_change", corrected_target="back",
        ),
    ]
    runtime, env, _agent = _runtime(
        tmp_path, screen, turns, [screen], max_actions=1,
        identity_resolver=resolver,
    )
    runtime.protocol_map.observe(
        name="Recipe collection", summary="Recipes", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "max_actions"
    assert len(env.actions) == 1
    assert len(resolver_calls) == 3
    challenge = resolver_calls[0]["arrival_context"]["page_identity_dispute"]
    assert challenge["framework_current_page"] == "Recipe collection"
    assert list(runtime.protocol_map.pages) == ["Recipe collection"]
    assert runtime.protocol_map.current_page == "Recipe collection"
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    report = next(
        item for item in trace["history"]
        if item.get("tool_name") == "report_record_error"
    )
    review = report["tool_result"]["data"]["identity_review"]
    assert review["status"] == "known"
    assert review["data"]["page_name"] == "Recipe collection"
    feedback = report["tool_result"]["data"]["feedback"]
    assert "Page Identity specialist 判断" in feedback
    assert "Recipe collection" in feedback
    assert "The content matches the registered Page" in feedback
    assert "report_id" not in report["tool_result"]["data"]
    model_view = _history_summary([report])["recent_results"][0]
    assert model_view == {"history_number": 1, "feedback": feedback}
    assert report["tool_result"]["pending_review"] is True
    assert not any(
        item.get("rejection", {}).get("code") == "page_identity_conflict"
        for item in trace["history"])


def test_page_identity_dispute_preserves_new_proposal_for_agent_review(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("teal")}
    before = _png("red")
    resolver_calls = []

    def resolver(request):
        resolver_calls.append(request)
        return {
            "status": "new", "page_name": "Pantry",
            "matched_page_name": "", "surface_kind": "page",
            "summary": "A proposed shell-named Page.",
            "reason": "The shell title says Pantry.",
        }

    runtime, _env, _agent = _runtime(
        tmp_path, screen, [], identity_resolver=resolver)
    runtime.protocol_map.observe(
        name="Recipe collection", summary="Recipes", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )
    history = [{
        "kind": "action",
        "screen": "Recipe collection",
        "action": "SCROLL",
        "target": "Recipe list",
        "outcome": "no_visible_change",
        "landed_screen": "Recipe collection",
        "validated_action": {
            "operation": "scroll",
            "arguments": {"container_hint": "Recipe list"},
        },
        "action_tool_result": {
            "operation": "scroll",
            "before_frame_id": loop.screenshot_frame_id(before),
            "after_frame_id": loop.screenshot_frame_id(screen["screenshot"]),
        },
    }]
    report_turn = _turn(
        "Pantry", action="CALL_TOOL", identity="new",
        tool_name="report_record_error", tool_arguments={
            "kind": "page_identity", "subject": "Recipe collection",
            "observed_problem": "The shell title says Pantry.",
        },
    )
    loop._dispatch_tool_call(
        runtime, report_turn, screen["screenshot"],
        "Recipe collection", history,
    )

    assert list(runtime.protocol_map.pages) == ["Recipe collection"]
    assert runtime.pending_page_identity is not None
    result = history[-1]["tool_result"]
    review = result["data"]["identity_review"]
    assert result["status"] == "reported"
    assert result["pending_review"] is True
    assert review["status"] == "new"
    assert review["data"]["page_name"] == "Pantry"
    assert "new Page" not in result["data"]["feedback"]
    assert "新 Page“Pantry”" in result["data"]["feedback"]
    pending_view = loop._pending_tool_view(runtime)
    assert pending_view is not None
    assert set(pending_view) == {"feedback"}
    assert "新 Page“Pantry”" in pending_view["feedback"]
    assert "The shell title says Pantry" in pending_view["feedback"]
    origin = resolver_calls[0]["arrival_context"]["recent_action"]
    assert origin == {
        "source_page": "Recipe collection",
        "operation": "scroll",
        "target": "Recipe list",
        "landed_page": "Recipe collection",
        "frame_changed": True,
        "result_reason": "",
    }


def test_same_task_rejects_exact_visited_frame_action_pair() -> None:
    frame_id = loop.screenshot_frame_id(_png("teal"))
    action = validate_action_tool_call(
        "click",
        {"target": "Back button", "entry_id": "", "point_1000": [60, 35]},
        latest_frame_id=frame_id,
    )
    history = [{
        "kind": "action",
        "exploration_task_id": "explore:ae16",
        "exploration_task_phase": "locate_entry",
        "validated_action": action.to_dict(),
        "action_tool_result": {
            "status": "observed",
            "operation": "click",
            "env_action": True,
        },
    }]

    issue = _repeat_task_frame_action_issue(
        history, action, "explore:ae16", "locate_entry")

    assert "already executed" in issue
    assert _repeat_task_frame_action_issue(
        history, action, "explore:another", "locate_entry") == ""
    assert _repeat_task_frame_action_issue(
        history, action, "explore:ae16", "route_to_source") == ""
    changed_point = validate_action_tool_call(
        "click",
        {"target": "Back button", "entry_id": "", "point_1000": [80, 35]},
        latest_frame_id=frame_id,
    )
    assert _repeat_task_frame_action_issue(
        history, changed_point, "explore:ae16", "locate_entry") == ""
    wait = validate_action_tool_call(
        "navigate", {"operation": "wait"}, latest_frame_id=frame_id)
    assert _repeat_task_frame_action_issue(
        history, wait, "explore:ae16", "locate_entry") == ""


def test_reviewer_bound_target_wins_over_redundant_settlement_name(
    tmp_path,
) -> None:
    home = {"screenshot": _png("navy")}
    details = {"screenshot": _png("orange")}
    frame_id = loop.screenshot_frame_id(home["screenshot"])
    runtime, env, _agent = _runtime(
        tmp_path, home, [], [details], max_actions=1)
    runtime.protocol_map.observe(
        name="Home", summary="Home", identity="new", matched_page_name="",
        surface_kind="page", regions=(), screenshot=home["screenshot"],
        commit_regions=False,
    )
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id=frame_id,
        observations=[{"target": "Browse library"}],
    ).added[0]
    _complete_fixture_survey(runtime, "Home", home["screenshot"])
    runtime.click_reviewer = lambda _request: {
        "decision": "approve",
        "observed_target": "Browse library",
        "point_matches_target": True,
        "target_matches_request": True,
        "risk": "safe",
        "reason": "The point is on the requested visible button.",
    }
    runtime.decision_agent.turns = iter([
        _turn(
            "Home", action="CALL_TOOL", identity="known",
            target="Browse library", tool_name="click", tool_arguments={
                "target": "Browse library", "entry_id": entry_id,
                "point_1000": [500, 500],
            }),
        _turn(
            "Details", action="NONE", identity="new", outcome="changed",
            corrected_target="Open workspace", matches_intent=True),
    ])

    graph = loop.run_autonomous_traversal(runtime, home)

    assert len(env.actions) == 1
    assert runtime.entry_ledger.get(entry_id).status.value == "verified"
    assert runtime.protocol_map.connections == [{
        "from": "Home", "via": "Browse library", "action": "CLICK",
        "to": "Details", "provenance": "observed",
    }]
    attempt = graph.action_edges[0]["attempts"][0]
    assert attempt["element_label"] == "Browse library"
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    conflicts = [
        item for item in trace["history"]
        if item.get("rejection", {}).get("code")
        == "settlement_target_conflict"
    ]
    assert conflicts == []


def test_verified_same_page_entry_requests_one_delta_region_survey(
    tmp_path,
) -> None:
    closed = {"screenshot": _png("navy")}
    menu_open = {"screenshot": _png("orange")}
    frame_id = loop.screenshot_frame_id(closed["screenshot"])
    runtime, env, agent = _runtime(
        tmp_path, closed, [], [menu_open], max_actions=0)
    runtime.protocol_map.observe(
        name="Home", summary="Home", identity="new", matched_page_name="",
        surface_kind="page", regions=(), screenshot=closed["screenshot"],
        commit_regions=False,
    )
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id=frame_id,
        observations=[{"target": "Application menu"}],
    ).added[0]
    _complete_fixture_survey(runtime, "Home", closed["screenshot"])
    runtime.click_reviewer = lambda _request: {
        "decision": "approve",
        "observed_target": "Application menu",
        "point_matches_target": True,
        "target_matches_request": True,
        "risk": "safe",
        "reason": "The point is on the requested visible menu button.",
    }
    runtime.decision_agent.turns = iter([
        _turn(
            "Home", action="CALL_TOOL", identity="known",
            target="Application menu", tool_name="click", tool_arguments={
                "target": "Application menu", "entry_id": entry_id,
                "point_1000": [900, 80],
            }),
        _turn(
            "Home", action="NONE", identity="known", outcome="changed",
            corrected_target="Application menu", matches_intent=True,
            previous_reason="The application menu opened on the same page.",
            visible_effect="page_structure",
        ),
        _turn(
            "Home", action="NONE", identity="known",
            page_update=loop.PageUpdate(
                page_name="Home",
                regions=[{
                    "name": "Application menu panel",
                    "bbox_1000": [0, 0, 1000, 1000],
                    "summary": "Newly revealed menu commands.",
                    "coverage_complete": True,
                }],
            ),
        ),
        _turn(
            "Home", action="CALL_TOOL", identity="known",
            tool_name="finish_exploration", tool_arguments={
                "reason": "All visible work is covered.",
                "unreachable_evidence": [],
            },
        ),
    ])

    graph = loop.run_autonomous_traversal(runtime, closed)

    assert graph.stop_reason == "framework_complete"
    assert len(env.actions) == 1
    assert runtime.pending_page_resurveys == {}
    assert runtime.entry_ledger.get(entry_id).status.value == "verified"
    assert loop._region_state(runtime, "Home").region(
        "Main")["coverage_complete"] is True
    assert loop._region_state(runtime, "Home").region(
        "Application menu panel")["coverage_complete"] is True
    survey_call = next(
        call for call in agent.calls
        if ((call[2]["exploration_map"].get("task") or {}).get("phase")
            == "record_regions")
    )
    assert survey_call[2]["exploration_map"]["task"] == {
        "task_id": "survey:Home",
        "type": "survey_page",
        "page": "Home",
        "phase": "record_regions",
        "reason": (
            "最近一次操作没有切换到新的 Page，但当前 Page 显露或改变了一个可独立调查的"
            "功能表面；只补充这次新出现的 Region 和入口。"),
    }
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    assert any(
        item.get("kind") == "page_resurvey_requested"
        for item in trace["history"]
    )


def test_reviewed_exact_entry_no_effect_without_classification_closes_probe(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    frame_id = loop.screenshot_frame_id(screen["screenshot"])
    runtime, env, _agent = _runtime(tmp_path, screen, [])
    runtime.protocol_map.observe(
        name="Recipe collection", summary="Recipes", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Recipe collection", region_name="Recipe list",
        frame_id=frame_id,
        observations=[{"target": "Garden bowl card"}],
    ).added[0]
    _complete_fixture_survey(
        runtime, "Recipe collection", screen["screenshot"],
        region_names=("Main", "Recipe list"))
    runtime.click_reviewer = lambda _request: {
        "decision": "approve",
        "observed_target": "Garden bowl card",
        "point_matches_target": True,
        "target_matches_request": True,
        "risk": "safe",
        "reason": "The point is on the exact requested card.",
    }
    runtime.decision_agent.turns = iter([
        _turn(
            "Recipe collection", action="CALL_TOOL", identity="known",
            target="Garden bowl card", tool_name="click", tool_arguments={
                "target": "Garden bowl card", "entry_id": entry_id,
                "point_1000": [500, 400],
            },
        ),
        _turn(
            "Recipe collection", action="NONE", identity="known",
            outcome="no_visible_change", corrected_target="Garden bowl card",
            matches_intent=False,
            previous_reason=(
                "The card is static recipe content rather than a functional "
                "control; the before and after screenshots show no response."
            ),
            failure_kind=None,
        ),
        _turn(
            "Recipe collection", action="CALL_TOOL", identity="known",
            tool_name="finish_exploration",
            tool_arguments={"unreachable_evidence": []},
        ),
    ])

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "framework_partial"
    assert len(env.actions) == 1
    record = runtime.entry_ledger.get(entry_id)
    assert record.status.value == "unresolved"
    assert record.task_eligible is False
    assert record.last_result == (
        "The card is static recipe content rather than a functional control; "
        "the before and after screenshots show no response."
    )
    assert graph.graph.number_of_edges() == 0
    attempt = graph.action_edges[0]["attempts"][0]
    attempt_evidence = attempt["evidence"]
    assert attempt_evidence["source_region_ref"] == (
        runtime.region_registry.region_ref(
            "Recipe collection", "Recipe list"))
    assert attempt_evidence["exploration_task_id"] == f"explore:{entry_id}"
    effect = attempt_evidence["effect_observations"][0]
    assert effect["effect_kind"] == "no_effect"
    assert effect["verdict"] == "refuted"


    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    probes = [
        item for item in trace["history"]
        if item.get("kind") == "entry_probe"
    ]
    assert len(probes) == 1
    assert probes[0]["outcome"] == "no_effect_observed"
    assert probes[0]["classification"] == "observed_no_visible_change"
    assert probes[0]["detail"] == record.last_result
    assert not any(
        item.get("rejection", {}).get("code")
        == "no_effect_classification_required"
        for item in trace["history"]
    )
    assert not any(
        item.get("kind") == "unreachable_evidence"
        and item.get("records")
        for item in trace["history"]
    )


def test_public_object_creation_report_feeds_capability_induction(
    tmp_path,
) -> None:
    from gui_rewalk.src.core.scenario.capability_induction import (
        induce_capability_graph,
    )

    before = {"screenshot": _png("white")}
    after = {"screenshot": _png("green")}
    runtime, env, agent = _runtime(
        tmp_path, before, [], [after], max_actions=1)
    runtime.protocol_map.observe(
        name="Notes", summary="Notes page", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=before["screenshot"], commit_regions=False,
    )
    _complete_fixture_survey(
        runtime, "Notes", before["screenshot"],
        region_names=("Toolbar", "Notes list"),
    )
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Notes",
        region_name="Toolbar",
        frame_id=loop.screenshot_frame_id(before["screenshot"]),
        observations=[{"target": "Create quick note"}],
    ).added[0]
    loop._sync_exploration_task(runtime)
    runtime.click_reviewer = lambda _request: {
        "decision": "approve",
        "observed_target": "Create quick note",
        "point_matches_target": True,
        "target_matches_request": True,
        "risk": "safe",
        "reason": "The point is on the exact requested note action.",
    }
    settled, error = parse_turn({
        "screen": {
            "name": "Notes",
            "summary": "The Notes page and new draft remain visible.",
            "identity": "known",
            "matched_page_name": "Notes",
            "surface_kind": "page",
                "variant": {
                    "name": "default", "identity": "known",
                    "visible_predicates": ["A Draft A note is visible"],
                },
        },
        "reason": "The requested Draft A note is visible; no next action is needed.",
        "previous_action": {
            "outcome": "changed",
            "reason": "Draft A was absent before and is now visible in the note list.",
            "matches_intent": True,
            "failure_kind": None,
            "business_effect": {
                "effect_kind": "object_creation",
                "region_name": "Notes list",
                "capability_name": "Create quick note",
                "fact": "note.title",
                "before_value": "absent",
                "after_value": "Draft A",
                "parameter_bindings": {"title": "Draft A"},
            },
        },
        "action": None,
    }, has_previous=True)
    assert error == ""
    assert settled is not None
    runtime.decision_agent.turns = iter([
        _turn(
            "Notes", action="CALL_TOOL", identity="known",
            target="Create quick note", tool_name="click", tool_arguments={
                "target": "Create quick note",
                "entry_id": entry_id,
                "point_1000": [500, 500],
            },
        ),
        settled,
    ])

    graph = loop.run_autonomous_traversal(runtime, before)
    arrival = agent.calls[1][2]["exploration_map"]["arrival_context"]
    assert [item["name"] for item in arrival["source_regions"]] == [
        "Toolbar", "Notes list",
    ]

    assert len(env.actions) == 1
    attempt = graph.action_edges[0]["attempts"][0]
    evidence = attempt["evidence"]
    assert evidence["source_region"] == "Toolbar"
    assert evidence["source_region_ref"] == (
        runtime.region_registry.region_ref("Notes", "Toolbar"))
    expected_element_uid = AUTONOMOUS_ENTRY_UID_PREFIX + entry_id
    assert attempt["element_id"] == expected_element_uid
    assert attempt["region"] == "Toolbar"
    assert evidence["discovery_source"] == "main_agent_page_update"
    assert evidence["exploration_task_id"] == f"explore:{entry_id}"
    effect = evidence["effect_observations"][0]
    assert effect["effect_kind"] == "object_creation"
    assert effect["verdict"] == "supported"
    assert effect["observed_changes"] == [{
        "scope": {"region_ref": runtime.region_registry.region_ref(
            "Notes", "Notes list")},
        "fact": "note.title",
        "before": "absent",
        "after": "Draft A",
    }]
    assert effect["parameter_bindings"] == {"title": "Draft A"}
    induced = induce_capability_graph(graph)
    assert [item["name"] for item in induced["capabilities"]] == [
        "Create quick note",
    ]
    assert induced["capabilities"][0]["verification_level"] == "discovered"
    assert induced["capabilities"][0]["entry_surfaces"][0][
        "element_uid"] == expected_element_uid
    assert induced["capabilities"][0]["execution_recipe"][0]["selector"][
        "element_id"] == expected_element_uid
    assert induced["capabilities"][0]["execution_recipe"][0]["selector"][
        "region_ids"] == [evidence["source_region_ref"]]
    assert induced["capabilities"][0]["parameter_candidates"] == {
        "title": ["Draft A"]}


def test_changed_foreground_does_not_terminalize_reviewed_entry(tmp_path) -> None:
    before = {"screenshot": _png("#ffffff")}
    after = {"screenshot": _png("#fffffe")}
    destination = {"screenshot": _png("#eeeeff")}
    frame_id = loop.screenshot_frame_id(before["screenshot"])
    runtime, env, _agent = _runtime(
        tmp_path, before, [], [after, destination])
    runtime.protocol_map.observe(
        name="Project workspace", summary="Workspace", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=before["screenshot"], commit_regions=False,
    )
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Project workspace", region_name="Page header",
        frame_id=frame_id,
        observations=[{"target": "Project view button"}],
    ).added[0]
    _complete_fixture_survey(
        runtime, "Project workspace", before["screenshot"],
        region_names=("Main", "Page header"))
    runtime.click_reviewer = lambda _request: {
        "decision": "approve",
        "observed_target": "Project view button",
        "point_matches_target": True,
        "target_matches_request": True,
        "risk": "safe",
        "reason": "The point is on the exact requested target.",
    }
    runtime.decision_agent.turns = iter([
        _turn(
            "Project workspace", action="CALL_TOOL", identity="known",
            target="Project view button", tool_name="click", tool_arguments={
                "target": "Project view button", "entry_id": entry_id,
                "point_1000": [870, 180],
            },
        ),
        _turn(
            "Project workspace", action="NONE", identity="known",
            outcome="no_visible_change", matches_intent=False,
            previous_reason=(
                "The foreground menu closed, but the requested control did not "
                "activate."
            ),
        ),
        _turn(
            "Project workspace", action="CALL_TOOL", identity="known",
            target="Project view button", tool_name="click", tool_arguments={
                "target": "Project view button", "entry_id": entry_id,
                "point_1000": [870, 180],
            },
        ),
        _turn(
            "Project workspace", action="NONE", identity="known",
            outcome="changed", matches_intent=True,
            previous_reason=(
                "The clean second click activated the requested project view."
            ),
        ),
    ])

    graph = loop.run_autonomous_traversal(runtime, before)

    assert graph.stop_reason == "all_remaining_work_suspended"
    assert len(env.actions) == 2
    record = runtime.entry_ledger.get(entry_id)
    assert record.status.value == "verified"
    assert record.task_eligible is False
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    assert not [
        item for item in trace["history"]
        if item.get("kind") == "entry_probe"
        and item.get("entry_id") == entry_id
    ]
    assert not any(
        item.get("rejection", {}).get("code")
        == "no_effect_classification_required"
        for item in trace["history"]
    )


def test_record_error_remains_exposed_after_use(
    tmp_path,
) -> None:
    screen = _png("yellow")
    runtime, _env, _agent = _runtime(tmp_path, {"screenshot": screen}, [])

    normal = {
        item["name"] for item in loop._dynamic_tool_catalog(runtime, screen)
    }
    assert "report_record_error" in normal
    assert "report_record_error" in {
        item["name"] for item in loop._dynamic_tool_catalog(runtime, screen)
    }


def test_route_to_is_not_a_public_tool(tmp_path) -> None:
    screen = _png("yellow")
    runtime, _env, _agent = _runtime(tmp_path, {"screenshot": screen}, [])

    names = {
        item["name"] for item in loop._dynamic_tool_catalog(
            runtime,
            screen,
        )
    }

    assert "route_to" not in names


def test_legacy_temporary_state_checkpoint_is_read_only_audit_evidence(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("yellow")}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    runtime.protocol_map.observe(
        name="Clock", summary="Clock page", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )
    _complete_fixture_survey(runtime, "Clock", screen["screenshot"])
    legacy_state = {
        "page_name": "Clock",
        "control": "Overflow menu",
        "before": "closed",
        "current": "open",
        "status": "needs_restore",
    }
    runtime.temporary_states["clock::overflow menu"] = dict(legacy_state)
    loop._checkpoint(runtime, [])

    restored, _env, _agent = _runtime(tmp_path, screen, [])
    restored.restore(str(Path(tmp_path) / "graph.json"))

    assert restored.temporary_states == {
        "clock::overflow menu": legacy_state,
    }
    loop._sync_exploration_task(restored)
    assert restored.exploration_task is None
    assert loop._completion_gaps(restored) == [
        "Clock: 旧 checkpoint 记录的临时状态“Overflow menu”仍未恢复"
        "（原值“closed”，记录值“open”）；当前严格协议只保留"
        "这条审计证据，不会自动修改界面",
    ]

    loop._checkpoint(restored, [])
    saved = json.loads(
        (Path(tmp_path) / "autonomous_temporary_states.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved["states"] == [legacy_state]


def test_new_page_identity_commits_only_after_accept(tmp_path) -> None:
    screen = {"screenshot": _png("white")}
    runtime = None

    def resolver(_request):
        assert runtime is not None
        assert runtime.protocol_map.pages == {}
        assert runtime.graph.graph.number_of_nodes() == 0
        return {
            "status": "new",
            "page_name": "Home",
            "surface_kind": "page",
            "summary": "Primary navigation is visible.",
            "supporting_evidence": ["no registered candidate has this layout"],
            "conflicting_evidence": [],
            "checked_candidates": [],
            "reason": "This is the first distinct application page.",
        }

    runtime, env, agent = _runtime(
        tmp_path,
        screen,
        [
            _turn(
                "Proposed Home", action="CALL_TOOL", target="page identity",
                tool_name="page_identity",
                tool_arguments=_identity_arguments("Home"),
            ),
            _turn(
                "Home", action="FINISH", identity="new",
                tool_review={
                    "decision": "accept",
                    "reason": "The proposal matches the current screenshot.",
                },
            ),
            _turn("Home", action="FINISH", identity="new"),
            _turn("Home", action="FINISH", identity="known"),
        ],
        identity_resolver=resolver,
    )

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert env.actions == []
    assert graph.graph.number_of_nodes() == 1
    assert list(runtime.protocol_map.pages) == ["Home"]
    assert runtime.protocol_map.pages["Home"]["summary"] == (
        "Primary navigation is visible.")
    assert runtime.protocol_map.pages["Home"]["surface_kind"] == "page"
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    tool = next(item for item in trace["history"] if item["kind"] == "tool")
    review = next(
        item for item in trace["history"] if item["kind"] == "tool_review")
    assert tool["tool_result"]["pending_review"] is True
    assert review["outcome"] == "accepted"


def test_rejected_identity_is_not_committed_and_reason_reaches_retry(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("gray")}
    requests = []

    def resolver(request):
        requests.append(request)
        name = "Wrong Home" if len(requests) == 1 else "Settings"
        return {
            "status": "new", "page_name": name, "surface_kind": "page",
            "summary": f"Visible {name}", "supporting_evidence": [],
            "conflicting_evidence": [], "checked_candidates": [],
            "reason": "No known candidate matched.",
        }

    runtime, _env, _agent = _runtime(
        tmp_path,
        screen,
        [
            _turn(
                "Unknown", action="CALL_TOOL", target="page identity",
                tool_name="page_identity",
                tool_arguments=_identity_arguments("Wrong Home"),
            ),
            _turn(
                "Settings", action="WAIT", target="identity correction",
                tool_review={
                    "decision": "reject",
                    "reason": (
                        "The proposal described the background. "
                        "Judge the foreground Settings dialog."
                    ),
                },
            ),
            _turn(
                "Settings", action="CALL_TOOL", target="retry identity",
                tool_name="page_identity",
                tool_arguments=_identity_arguments("Settings"),
            ),
            _turn(
                "Settings", action="FINISH", identity="new",
                tool_review={
                    "decision": "accept",
                    "reason": "The corrected foreground identity is right.",
                },
            ),
            _turn("Settings", action="FINISH", identity="new"),
            _turn("Settings", action="FINISH", identity="known"),
        ],
        identity_resolver=resolver,
    )

    loop.run_autonomous_traversal(runtime, screen)

    assert "Wrong Home" not in runtime.protocol_map.pages
    assert list(runtime.protocol_map.pages) == ["Settings"]
    assert requests[1]["previous_tool_feedback"] == {
        "decision": "reject",
        "reason": (
            "The proposal described the background. "
            "Judge the foreground Settings dialog."
        ),
    }


def test_uncertain_review_keeps_identity_pending_until_later_accept(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("blue")}
    resolver_calls = []

    def resolver(request):
        resolver_calls.append(request)
        return {
            "status": "new", "page_name": "Details",
            "surface_kind": "dialog", "summary": "A detail dialog is visible.",
            "supporting_evidence": [], "conflicting_evidence": [],
            "checked_candidates": [], "reason": "No candidate matched.",
        }

    runtime, _env, _agent = _runtime(
        tmp_path,
        screen,
        [
            _turn(
                "Details", action="CALL_TOOL", target="page identity",
                tool_name="page_identity",
                tool_arguments=_identity_arguments("Details"),
            ),
            _turn(
                "Details", action="CALL_TOOL", target="premature retry",
                tool_name="page_identity",
                tool_arguments=_identity_arguments("Details"),
                tool_review={
                    "decision": "uncertain",
                    "reason": "I need another comparison before accepting.",
                },
            ),
            _turn(
                "Details", action="FINISH", identity="new",
                tool_review={
                    "decision": "accept",
                    "reason": "The additional map check found no conflict.",
                },
            ),
            _turn("Details", action="FINISH", identity="new"),
            _turn("Details", action="FINISH", identity="known"),
        ],
        identity_resolver=resolver,
    )

    loop.run_autonomous_traversal(runtime, screen)

    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    outcomes = [item["outcome"] for item in trace["history"]
                if item["kind"] == "tool_review"]
    assert outcomes[:2] == ["unresolved", "accepted"]
    assert len(resolver_calls) == 2
    assert not any(item.get("detail") == "tool is not exposed in the current turn"
                   for item in trace["history"])
    assert list(runtime.protocol_map.pages) == ["Details"]


def test_pending_identity_can_be_reviewed_after_passive_frame_change(
    tmp_path,
) -> None:
    first = {"screenshot": _png("red")}
    changed = {"screenshot": _png("green")}

    class _ChangingEnv(_Env):
        def __init__(self):
            super().__init__(first)
            self.reads = 0

        def _get_obs(self):
            self.reads += 1
            if self.reads == 1:
                self.current = changed
            return self.current

    def resolver(_request):
        return {
            "status": "new", "page_name": "Transient",
            "surface_kind": "dialog", "summary": "A transient dialog.",
            "supporting_evidence": [], "conflicting_evidence": [],
            "checked_candidates": [], "reason": "No candidate matched.",
        }

    agent = _Agent([
        _turn(
            "Transient", action="CALL_TOOL", target="page identity",
            tool_name="page_identity",
            tool_arguments=_identity_arguments("Transient"),
        ),
        _turn(
            "Transient", action="FINISH", identity="new",
            tool_review={
                "decision": "accept",
                "reason": "Only dynamic pixels changed; the surface is the same.",
            },
        ),
        _turn("Transient", action="FINISH", identity="new"),
    ])
    runtime = loop.AutonomousTraversalRuntime(
        env=_ChangingEnv(), decision_agent=agent, app_name="fixture",
        output_root=str(tmp_path), max_states=20, max_actions=6,
        identity_resolver=resolver,
    )

    loop.run_autonomous_traversal(runtime, first)

    assert "Transient" in runtime.protocol_map.pages
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    assert not any(item.get("outcome") == "stale_screenshot"
                   for item in trace["history"])
    assert any(item.get("outcome") == "accepted"
               for item in trace["history"])


def _reviewable_entry_dispute_runtime(tmp_path):
    screenshot = _png("teal")
    screen = {"screenshot": screenshot}
    runtime, _env, _agent = _runtime(tmp_path, screen, [])
    canonical, issue = runtime.protocol_map.observe(
        name="Alarm editor",
        summary="Alarm settings",
        identity="new",
        matched_page_name="",
        surface_kind="page",
        regions=(),
        screenshot=screenshot,
        commit_regions=False,
    )
    assert (canonical, issue) == ("Alarm editor", "")
    scene = loop.ObservedScene(
        state_id="state-alarm-editor",
        screenshot=screenshot,
        page_name="Alarm editor",
        is_new=False,
    )
    _register_reviewed_main_region(
        runtime, "Alarm editor", scene, screenshot)
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Alarm editor",
        region_name="Main",
        frame_id=loop.screenshot_frame_id(screenshot),
        observations=[{
            "target": "Name input field",
        }],
    ).added[0]
    runtime.exploration_task = ExplorationTask(
        task_type="explore_entry",
        task_id=f"explore:{entry_id}",
        entry_id=entry_id,
        page_name="Alarm editor",
        region_name="Main",
        target="Name input field",
        phase="locate_entry",
    )
    return runtime, screenshot, entry_id


def test_exact_entry_dispute_needs_reconciliation_before_ledger_change(
    tmp_path,
) -> None:
    runtime, screenshot, entry_id = _reviewable_entry_dispute_runtime(
        tmp_path)
    requests = []

    def reviewer(request):
        requests.append(request)
        return {
            "independent_entries": [],
            "deferred_entries": [],
            "deferred_regions": [],
            "reason_consistent": True,
            "reason": (
                "The visible text field only edits the current alarm and "
                "opens no separate functional surface."
            ),
        }

    runtime.entry_reviewer = reviewer
    turn = _turn(
        "Alarm editor",
        action="CALL_TOOL",
        identity="known",
        tool_name="report_record_error",
        tool_arguments={
            "kind": "entry",
            "subject": entry_id,
            "observed_problem": (
                "The visible Name field edits the current alarm; it is not a "
                "separate function entry."
            ),
        },
    )
    history = []

    loop._dispatch_tool_call(
        runtime, turn, screenshot, "Alarm editor", history)

    assert len(requests) == 1
    assert requests[0]["entry_dispute"]["entry_id"] == entry_id
    assert requests[0]["candidates"] == [{
        "region_name": "Main",
        "target": "Name input field",
        "operation": "Name input field",
        "subject": "Main",
    }]
    record = runtime.entry_ledger.get(entry_id)
    assert record.status.value == "discovered"
    assert record.task_eligible is True
    assert record.target == "Name input field"
    review = history[-1]["tool_result"]["data"]["entry_review"]
    assert review["verdict"] == "needs_reconciliation"
    assert review["ledger_changed"] is False
    assert history[-1]["tool_result"]["status"] == "reported"
    assert runtime.protocol_map.record_errors[-1]["subject"] == entry_id

    loop._sync_exploration_task(runtime)

    assert runtime.exploration_task is not None
    assert runtime.exploration_task.task_type == "explore_entry"
    assert runtime.exploration_task.entry_id == entry_id
    assert any(
        "Name input field" in gap and "尚未探索" in gap
        for gap in loop._completion_gaps(runtime))


def test_entry_dispute_reviewer_retention_preserves_task(
    tmp_path,
) -> None:
    runtime, screenshot, entry_id = _reviewable_entry_dispute_runtime(
        tmp_path)
    runtime.entry_reviewer = lambda _request: {
        "independent_entries": [{
            "region_name": "Main", "target": "Name input field",
        }],
        "deferred_entries": [],
        "deferred_regions": [],
        "reason_consistent": True,
        "reason": "The control opens a separate editor surface.",
    }
    turn = _turn(
        "Alarm editor",
        action="CALL_TOOL",
        identity="known",
        tool_name="report_record_error",
        tool_arguments={
            "kind": "entry",
            "subject": entry_id,
            "observed_problem": "The control appears internal.",
        },
    )
    history = []

    loop._dispatch_tool_call(
        runtime, turn, screenshot, "Alarm editor", history)

    record = runtime.entry_ledger.get(entry_id)
    assert record.status.value == "discovered"
    assert record.task_eligible is True
    review = history[-1]["tool_result"]["data"]["entry_review"]
    assert review["verdict"] == "retained_entry"
    assert review["ledger_changed"] is False


def test_missing_entry_is_invalidated_only_after_two_frame_review(
    tmp_path,
) -> None:
    runtime, screenshot, entry_id = _reviewable_entry_dispute_runtime(
        tmp_path)
    record = runtime.entry_ledger.get(entry_id)
    current_state_id = runtime.region_states["alarm editor"].current_state_id
    assert current_state_id
    record.source_state_id = current_state_id
    record.source_state_ids = [current_state_id]
    record.discovery_screenshot_path = (
        runtime.writer.save_entry_discovery_frame(_png("navy")))
    requests = []

    def presence_reviewer(request):
        requests.append(request)
        return {
            "discovery_presence": "unsupported",
            "current_presence": "missing",
            "reason": (
                "Neither full screenshot contains a visible control matching "
                "the registered Unknown icon target inside Main."
            ),
        }

    runtime.entry_presence_reviewer = presence_reviewer
    turn = _turn(
        "Alarm editor",
        action="CALL_TOOL",
        identity="known",
        tool_name="report_record_error",
        tool_arguments={
            "kind": "entry",
            "subject": entry_id,
            "observed_problem": (
                "I scanned the Main Region in the recorded source State and "
                "the registered target is absent."
            ),
            "problem_type": "target_not_found",
        },
    )
    history = []

    loop._dispatch_tool_call(
        runtime, turn, screenshot, "Alarm editor", history)

    assert len(requests) == 1
    assert requests[0]["discovery_screenshot"] == _png("navy")
    assert requests[0]["current_screenshot"] == screenshot
    assert record.status.value == "invalidated"
    assert record.task_eligible is False
    review = history[-1]["tool_result"]["data"]["entry_review"]
    assert review["verdict"] == "invalidated_hallucination"
    assert review["ledger_changed"] is True


def test_reviewed_entry_commit_saves_fixed_discovery_frame(tmp_path) -> None:
    runtime, screenshot, _entry_id = _reviewable_entry_dispute_runtime(
        tmp_path)
    scene = loop.ObservedScene(
        state_id=runtime.region_states["alarm editor"].current_state_id,
        screenshot=screenshot,
        page_name="Alarm editor",
        is_new=False,
    )

    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name="Alarm editor",
            regions=[],
            new_entries=[{
                "region_name": "Main",
                "operation": "open",
                "target": "Open details",
            }],
        ),
        scene,
        screenshot,
        [],
    ) == ""

    record = next(
        item for item in runtime.entry_ledger.entries
        if item.target == "Open details")
    evidence_path = Path(record.discovery_screenshot_path)
    assert evidence_path.is_file()
    assert evidence_path.read_bytes() == screenshot


def test_entry_dispute_cannot_reclassify_a_different_task_entry(
    tmp_path,
) -> None:
    runtime, screenshot, entry_id = _reviewable_entry_dispute_runtime(
        tmp_path)
    reviewer_calls = []
    runtime.entry_reviewer = lambda request: reviewer_calls.append(request)
    turn = _turn(
        "Alarm editor",
        action="CALL_TOOL",
        identity="known",
        tool_name="report_record_error",
        tool_arguments={
            "kind": "entry",
            "subject": "ae999",
            "observed_problem": "This is not the dispatched Entry.",
        },
    )
    history = []

    loop._dispatch_tool_call(
        runtime, turn, screenshot, "Alarm editor", history)

    assert reviewer_calls == []
    record = runtime.entry_ledger.get(entry_id)
    assert record.status.value == "discovered"
    assert record.task_eligible is True
    review = history[-1]["tool_result"]["data"]["entry_review"]
    assert review["verdict"] == "not_reviewed"
    assert review["ledger_changed"] is False


def test_existing_region_identity_fields_are_stable_and_resurvey_forces_review(
    tmp_path,
) -> None:
    screenshot = _png("teal")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Home", summary="Home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-home", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(page_name=page_name, regions=[{
            "name": "Primary actions",
            "bbox_1000": [0, 0, 1000, 1000],
            "summary": "Reviewed primary application actions.",
            "equivalence_reason": "Reviewed as one stable functional component.",
            "coverage_complete": False,
        }]),
        scene,
        screenshot,
        history,
        region_reviewed=True,
    ) == ""

    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(page_name=page_name, regions=[{
            "name": "Primary actions",
            "summary": "A newly worded summary.",
            "equivalence_reason": "A newly worded identity reason.",
            "coverage_complete": False,
        }]),
        scene,
        screenshot,
        history,
    ) == ""

    region = loop._region_state(runtime, page_name).region("Primary actions")
    assert region is not None
    assert region["summary"] == "Reviewed primary application actions."
    assert region["equivalence_reason"] == (
        "Reviewed as one stable functional component.")
    assert "summary" in history[-1]["feedback"]
    runtime.pending_page_resurveys[loop._page_key(page_name)] = {
        "page_name": page_name,
    }
    assert loop._region_review_required(
        runtime,
        loop.PageUpdate(page_name=page_name, regions=[{
            "name": "Primary actions",
            "coverage_complete": False,
        }]),
    ) is True


def test_page_update_cannot_reuse_entry_evidence_across_region_refs(
    tmp_path,
) -> None:
    screenshot = _png("olive")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Home", summary="Home", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-home", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(page_name=page_name, regions=[
            {"name": "Navigation", "bbox_1000": [0, 0, 1000, 200],
             "coverage_complete": False},
            {"name": "Content", "bbox_1000": [0, 200, 1000, 1000],
             "coverage_complete": False},
        ]),
        scene,
        screenshot,
        [],
        region_reviewed=True,
    ) == ""
    representative_id = runtime.entry_ledger.record_agent_update(
        page_name=page_name,
        region_name="Navigation",
        frame_id=loop.screenshot_frame_id(screenshot),
        observations=[{"target": "Settings"}],
    ).added[0]
    pending = runtime.entry_ledger.begin_explicit_action(
        representative_id,
        frame_id=loop.screenshot_frame_id(screenshot),
        page_name=page_name,
    )
    runtime.entry_ledger.finish_action(
        pending.action_id,
        action_executed=True,
        outcome_verified=True,
        result="Settings opened",
    )

    result = {}
    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(page_name=page_name, new_entries=[{
            "region_name": "Content",
            "target": "Settings shortcut",
            "equivalent_to_entry_id": representative_id,
        }]),
        scene,
        screenshot,
        [],
        result_out=result,
    ) == ""

    assert result["created_entries"] == []
    assert result["rejected_items"][0]["error_code"] == (
        "entry_region_scope_mismatch")


def test_inconsistent_entry_review_commits_neither_entries_nor_coverage(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Timer", summary="Timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-timer", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    history = []
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Timer controls",
                "bbox_1000": [0, 0, 1000, 1000],
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Timer controls",
                "target": "Start button",
            }],
        ),
        scene,
        screenshot,
        history,
        review_region_names=["Timer controls"],
    ) == ""
    runtime.pending_page_resurveys[loop._page_key(page_name)] = {
        "page_name": page_name,
    }

    assert loop._apply_entry_review(
        runtime,
        loop.EntryReview(independent_entries=[{
            "region_name": "Timer controls",
            "target": "Start button",
        }]),
        scene,
        screenshot,
        history,
        reviewer_reason="The stated coverage reason contradicts the screenshot.",
        reason_consistent=False,
    ) == ""

    region = loop._region_state(runtime, page_name).region("Timer controls")
    assert region is not None and region["coverage_complete"] is False
    assert runtime.entry_ledger.entries == ()
    assert loop._page_key(page_name) in runtime.pending_page_resurveys
    audit = runtime.entry_review_audits["timer"]["timer controls"]
    assert audit["status"] == "disagreement"
    assert history[-1]["status"] == "disagreement"
    assert history[-1]["ledger_committed"] is False
    assert any(
        "disagrees with the main survey reason" in gap
        for gap in loop._completion_gaps(runtime)
    )


def test_focused_resurvey_closes_without_reopening_hidden_regions(
    tmp_path,
) -> None:
    screenshot = _png("orange")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": screenshot}, [])
    page_name, issue = runtime.protocol_map.observe(
        name="Alarm", summary="Alarm", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screenshot, commit_regions=False,
    )
    assert issue == ""
    scene = loop.ObservedScene(
        state_id="state-alarm-modal", screenshot=screenshot,
        page_name=page_name, is_new=True,
    )
    assert loop._apply_main_agent_page_update(
        runtime,
        loop.PageUpdate(page_name=page_name, regions=[
            {
                "name": "Alarm list",
                "bbox_1000": [0, 0, 1000, 1000],
                "coverage_complete": False,
            },
            {
                "name": "Time picker modal",
                "bbox_1000": [100, 100, 900, 900],
                "coverage_complete": False,
            },
        ]),
        scene,
        screenshot,
        [],
        region_reviewed=True,
    ) == ""
    runtime.pending_page_resurveys["alarm"] = {
        "page_name": "Alarm",
        "entry_id": "ae-add",
        "target": "Add alarm",
    }
    assert loop._stage_main_agent_page_update(
        runtime,
        loop.PageUpdate(
            page_name=page_name,
            regions=[{
                "name": "Time picker modal",
                "bbox_1000": [100, 100, 900, 900],
                "coverage_complete": True,
            }],
            new_entries=[{
                "region_name": "Time picker modal",
                "target": "Cancel",
            }],
        ),
        scene,
        screenshot,
        [],
        region_reviewed=True,
        review_region_names=["Time picker modal"],
    ) == ""
    history = []

    assert loop._apply_entry_review(
        runtime,
        loop.EntryReview(independent_entries=[{
            "region_name": "Time picker modal",
            "target": "Cancel",
        }]),
        scene,
        screenshot,
        history,
        reviewer_reason="The visible modal entry is complete.",
        reason_consistent=True,
    ) == ""
    assert runtime.pending_page_resurveys == {}
    assert loop._region_state(runtime, page_name).region(
        "Time picker modal")["coverage_complete"] is True
    assert loop._region_state(runtime, page_name).region(
        "Alarm list")["coverage_complete"] is False
    assert history[-1]["completed_resurvey"]["target"] == "Add alarm"


def test_repeated_wait_on_same_task_and_frame_is_rejected() -> None:
    history = [{
        "kind": "action",
        "action": "WAIT",
        "exploration_task_id": "survey:Home",
        "frame_id": "frame-1",
    }]
    assert "already requested" in loop._repeat_wait_issue(
        history,
        task_id="survey:Home",
        frame_id="frame-1",
    )
    assert loop._repeat_wait_issue(
        history,
        task_id="survey:Home",
        frame_id="frame-2",
    ) == ""



def test_hidden_finish_tool_cannot_retire_entry_after_recorded_attempts(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("purple")}
    runtime, _env, _agent = _runtime(
        tmp_path,
        screen,
        [_turn(
            "Chats", action="CALL_TOOL", identity="known",
            tool_name="finish_exploration", tool_arguments={
                "reason": "The exact active entry remained unreachable.",
                "unreachable_evidence": [{
                    "page_name": "Chats",
                    "entry_id": "ae1",
                    "subject": "Contacts",
                    "evidence": "Two recorded route attempts could not locate it.",
                }],
            },
        )],
    )
    runtime.protocol_map.observe(
        name="Chats", summary="Visible Chats", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )
    _complete_fixture_survey(runtime, "Chats", screen["screenshot"])
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Chats",
        region_name="Main",
        frame_id=loop.screenshot_frame_id(screen["screenshot"]),
        observations=[{"target": "Contacts"}],
    ).added[0]
    runtime.resume_history = [
        {
            "kind": "action",
            "action": "SCROLL",
            "outcome": "no_visible_change",
            "exploration_task_id": f"explore:{entry_id}",
        },
        {
            "kind": "action",
            "action": "CLICK",
            "outcome": "observed_change",
            "exploration_task_id": f"explore:{entry_id}",
        },
    ]

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "all_remaining_work_suspended"
    record = runtime.entry_ledger.get(entry_id)
    assert record.status.value == "discovered"
    assert record.task_eligible is True
    trace = json.loads(
        (Path(tmp_path) / "autonomous_trace.json").read_text(encoding="utf-8"))
    assert not any(
        item.get("kind") == "unreachable_evidence"
        for item in trace["history"]
    )


def test_optional_equivalence_nulls_are_normalized_as_absent() -> None:
    region, region_rejection = _normalize_page_region_item({
        "name": "Courier information card",
        "coverage_complete": True,
        "equivalent_to_region_ref": None,
    }, 0)
    entry, entry_rejection = _normalize_new_entry_item({
        "region_name": "Courier information card",
        "target": "View courier button",
        "equivalent_to_entry_id": None,
    }, 0)

    assert region_rejection is None
    assert region is not None
    assert region["equivalent_to_region_ref"] == ""
    assert entry_rejection is None
    assert entry is not None
    assert entry["equivalent_to_entry_id"] == ""


def test_region_entry_records_local_effect_and_capability(tmp_path) -> None:
    before = {"screenshot": _png("navy")}
    after = {"screenshot": _png("green")}
    changed_turn = _turn(
        "Stopwatch", action="NONE", identity="known",
        outcome="changed",
        previous_reason="Start visibly changed the running status.",
    )
    changed_turn = replace(
        changed_turn,
        previous=replace(
            changed_turn.previous,
            business_effect=ObservedBusinessEffect(
                effect_kind="state_change",
                region_name="Stopwatch controls",
                capability_name="Start stopwatch",
                fact="stopwatch.status",
                before_value="stopped",
                after_value="running",
                parameter_bindings={},
            ),
        ),
    )
    runtime, env, _agent = _runtime(
        tmp_path, before, [
            _turn(
                "Stopwatch", action="CALL_TOOL", identity="known",
                target="Start", tool_name="click",
                tool_arguments={
                    "target": "Start", "entry_id": "ae1",
                    "point_1000": [500, 500],
                },
            ),
            changed_turn,
        ], [after], enable_region_probes=True,
    )
    runtime.protocol_map.observe(
        name="Stopwatch", summary="Visible stopwatch", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=before["screenshot"], commit_regions=False,
    )
    loop._register_scene(
        runtime,
        before["screenshot"],
        _turn("Stopwatch", action="NONE", identity="known"),
        "Stopwatch",
    )
    _complete_fixture_survey(
        runtime, "Stopwatch", before["screenshot"],
        region_names=("Stopwatch controls",),
    )
    assert runtime.entry_ledger.record_agent_update(
        page_name="Stopwatch", region_name="Stopwatch controls",
        frame_id=loop.screenshot_frame_id(before["screenshot"]),
        observations=[{"target": "Start"}],
    ).added == ["ae1"]
    runtime.click_reviewer = lambda _request: {
        "decision": "approve",
        "point_matches_target": True,
        "target_matches_request": True,
        "observed_target": "Start",
        "risk": "safe",
        "reason": "The point is centered on the visible Start control.",
    }

    graph = loop.run_autonomous_traversal(runtime, before)

    assert graph.stop_reason in {
        "framework_complete", "all_remaining_work_suspended",
    }
    assert len(env.actions) == 1
    assert runtime.entry_ledger.get("ae1").status.value == "verified"
    attempt = graph.action_edges[0]["attempts"][0]
    evidence = attempt["evidence"]
    expected_region_ref = runtime.region_registry.region_ref(
        "Stopwatch", "Stopwatch controls")
    expected_element_uid = AUTONOMOUS_ENTRY_UID_PREFIX + "ae1"
    assert attempt["element_id"] == expected_element_uid
    assert attempt["region"] == "Stopwatch controls"
    assert evidence["entry_id"] == "ae1"
    assert evidence["effect_observations"][0]["verdict"] == "supported"
    capability_graph = induce_capability_graph(graph)
    assert len(capability_graph["capabilities"]) == 1
    capability = capability_graph["capabilities"][0]
    assert capability["name"] == "Start stopwatch"
    assert capability["entry_surfaces"][0]["entry_id"] == "ae1"
    assert capability["entry_surfaces"][0]["region_ref"]
    assert capability["entry_surfaces"][0]["element_uid"] == (
        expected_element_uid)
    assert capability["execution_recipe"][0]["action_type"] == "CLICK"
    assert capability["execution_recipe"][0]["selector"]["element_id"] == (
        expected_element_uid)
    assert capability["execution_recipe"][0]["selector"]["region_ids"] == [
        expected_region_ref]


def test_region_entry_input_text_records_reviewed_query_recipe(
    tmp_path,
) -> None:
    before = {"screenshot": _png("white")}
    after = {"screenshot": _png("blue")}
    changed_turn = _turn(
        "Search", action="NONE", identity="known",
        outcome="changed",
        previous_reason="Typing Oslo visibly revealed matching results.",
    )
    changed_turn = replace(
        changed_turn,
        previous=replace(
            changed_turn.previous,
            business_effect=ObservedBusinessEffect(
                effect_kind="query_result",
                region_name="Search panel",
                capability_name="Search cities",
                fact="city.search_results",
                before_value="empty",
                after_value="Oslo result visible",
                parameter_bindings={"query": "Oslo"},
            ),
        ),
    )
    runtime, env, _agent = _runtime(
        tmp_path, before, [
            _turn(
                "Search", action="CALL_TOOL", identity="known",
                target="City search field in Search panel",
                tool_name="input_text",
                tool_arguments={
                    "target": "City search field in Search panel",
                    "point_1000": [500, 500],
                    "text": "Oslo",
                },
            ),
            changed_turn,
        ], [after], enable_region_probes=True,
    )
    runtime.protocol_map.observe(
        name="Search", summary="Visible search", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=before["screenshot"], commit_regions=False,
    )
    loop._register_scene(
        runtime,
        before["screenshot"],
        _turn("Search", action="NONE", identity="known"),
        "Search",
    )
    _complete_fixture_survey(
        runtime, "Search", before["screenshot"],
        region_names=("Search panel",),
    )
    assert runtime.entry_ledger.record_agent_update(
        page_name="Search", region_name="Search panel",
        frame_id=loop.screenshot_frame_id(before["screenshot"]),
        observations=[{
            "target": "City search field in Search panel",
            "control_type": "input",
        }],
    ).added == ["ae1"]
    review_requests = []

    def review(request):
        review_requests.append(dict(request))
        return {
            "decision": "approve",
            "point_matches_target": True,
            "target_matches_request": True,
            "observed_target": "City search field in Search panel",
            "risk": "safe",
            "reason": "The point is inside the visible non-sensitive query field.",
        }

    runtime.click_reviewer = review

    graph = loop.run_autonomous_traversal(runtime, before)

    assert graph.stop_reason in {
        "framework_complete", "all_remaining_work_suspended",
    }
    assert env.actions[0][0] == {
        "action_type": "TYPING",
        "parameters": {"x": 50, "y": 40, "text": "Oslo"},
    }
    assert len(review_requests) == 1
    assert review_requests[0]["purpose"] == "entry_attempt"
    assert review_requests[0]["operation"] == "input_text"
    assert review_requests[0]["requested_text"] == "Oslo"
    assert runtime.entry_ledger.get("ae1").status.value == "verified"
    attempt = graph.action_edges[0]["attempts"][0]
    region_ref = runtime.region_registry.region_ref(
        "Search", "Search panel")
    assert attempt["element_id"] == AUTONOMOUS_ENTRY_UID_PREFIX + "ae1"
    assert attempt["region"] == "Search panel"
    assert attempt["evidence"]["entry_id"] == "ae1"
    assert attempt["evidence"]["validated_action"]["arguments"]["text"] == (
        "Oslo")
    action_record = next(
        item for item in json.loads(
            (Path(tmp_path) / "autonomous_trace.json").read_text("utf-8")
        )["history"]
        if item.get("kind") == "action"
        and item.get("action") == "INPUT_TEXT"
    )
    assert action_record["action_tool_result"]["operation"] == "input_text"
    assert action_record["action_tool_result"]["point_1000"] == [500.0, 500.0]
    capability = induce_capability_graph(graph)["capabilities"][0]
    assert capability["name"] == "Search cities"
    assert capability["execution_recipe"][0]["action_type"] == "TYPING"
    assert capability["execution_recipe"][0]["parameters"]["text"] == (
        "{{query}}")
    assert capability["execution_recipe"][0]["selector"] == {
        "element_id": attempt["element_id"],
        "element_label": "City search field in Search panel",
        "region": "Search panel",
        "region_ids": [region_ref],
        "description": (
            "enter reviewed query text in visible target "
            "City search field in Search panel"
        ),
    }


def test_verified_entry_covers_same_operation_parameter_siblings(
    tmp_path,
) -> None:
    before = {"screenshot": _png("navy")}
    after = {"screenshot": _png("green")}
    changed_turn = _turn(
        "Alarm sound", action="NONE", identity="known",
        outcome="changed",
        previous_reason="Selecting Argon visibly replaced Default.",
        visible_effect="owner_state",
    )
    changed_turn = replace(
        changed_turn,
        previous=replace(
            changed_turn.previous,
            business_effect=ObservedBusinessEffect(
                effect_kind="state_change",
                region_name="Device sounds",
                capability_name="Choose device sound",
                fact="selected device sound",
                before_value="Default",
                after_value="Argon",
                parameter_bindings={"sound": "Argon"},
                same_operation_entry_ids=["ae2", "ae3"],
                same_operation_reason=(
                    "Silent and Barium are values in the same device-sound "
                    "single-choice list; only the selected sound differs."
                ),
            ),
        ),
    )
    runtime, env, _agent = _runtime(
        tmp_path,
        before,
        [
            _turn(
                "Alarm sound", action="CALL_TOOL", identity="known",
                target="Argon", tool_name="click",
                tool_arguments={
                    "target": "Argon",
                    "entry_id": "ae1",
                    "point_1000": [500, 700],
                },
            ),
            changed_turn,
        ],
        [after],
        enable_region_probes=True,
    )
    runtime.protocol_map.observe(
        name="Alarm sound", summary="Alarm sound", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=before["screenshot"], commit_regions=False,
    )
    loop._register_scene(
        runtime,
        before["screenshot"],
        _turn("Alarm sound", action="NONE", identity="known"),
        "Alarm sound",
    )
    _complete_fixture_survey(
        runtime,
        "Alarm sound",
        before["screenshot"],
        region_names=("Device sounds",),
    )
    device_sounds_ref = runtime.region_registry.region_ref(
        "Alarm sound", "Device sounds")
    assert runtime.entry_ledger.record_agent_update(
        page_name="Alarm sound",
        region_name="Device sounds",
        frame_id=loop.screenshot_frame_id(before["screenshot"]),
        owner_region_ref=device_sounds_ref,
        observations=[
            {
                "target": "Argon",
                "operation": "Select alarm sound",
                "subject": "Alarm sound",
            },
            {
                "target": "Silent",
                "operation": "Select alarm sound",
                "subject": "Alarm sound",
            },
            {
                "target": "Barium",
                "operation": "Select alarm sound",
                "subject": "Alarm sound",
            },
        ],
    ).added == ["ae1", "ae2", "ae3"]
    runtime.click_reviewer = lambda _request: {
        "decision": "approve",
        "point_matches_target": True,
        "target_matches_request": True,
        "observed_target": "Argon",
        "risk": "safe",
        "reason": "The point is centered on the visible Argon row.",
    }
    readable_history = _page_entry_history(runtime, "Alarm sound")
    assert "“Select alarm sound”操作" in readable_history
    assert "对象是“Alarm sound”" in readable_history
    assert "代表目标为“Argon”" in readable_history

    graph = loop.run_autonomous_traversal(runtime, before)

    assert graph.stop_reason == "framework_complete"
    assert len(env.actions) == 1
    assert runtime.entry_ledger.get("ae1").status.value == "verified"
    for entry_id in ("ae2", "ae3"):
        record = runtime.entry_ledger.get(entry_id)
        assert record.status.value == "inferred"
        assert record.task_eligible is False
        assert record.same_operation_source_entry_id == "ae1"
        assert record.representative_entry_id == ""
    pending_views = [
        values["exploration_map"]
        for _screenshot, _history, values in _agent.calls
        if (values.get("exploration_map") or {}).get("pending_action")
    ]
    assert pending_views[-1]["pending_action"][
        "same_region_pending_entries"] == [
        {
            "entry_id": "ae2",
            "operation": "Select alarm sound",
            "subject": "Alarm sound",
            "target": "Silent",
        },
        {
            "entry_id": "ae3",
            "operation": "Select alarm sound",
            "subject": "Alarm sound",
            "target": "Barium",
        },
    ]
    assert pending_views[-1]["task"]["operation"] == "Select alarm sound"
    assert pending_views[-1]["task"]["subject"] == "Alarm sound"
    restored = type(runtime.entry_ledger).from_snapshot(
        runtime.entry_ledger.snapshot())
    for entry_id in ("ae2", "ae3"):
        record = restored.get(entry_id)
        assert record.status.value == "inferred"
        assert record.task_eligible is False
        assert record.same_operation_source_entry_id == "ae1"
        assert record.same_operation_reason
    assert {entry.entry_id for entry in restored.task_candidates()} == set()
    assert not any(
        edge.get("provenance") == "agent_inferred_equivalence"
        for edge in runtime.protocol_map.connections
    )
    assert not any(
        (attempt.get("evidence") or {}).get("provenance")
        == "agent_inferred_equivalence"
        for edge in graph.action_edges
        for attempt in edge.get("attempts") or []
    )


def test_region_probe_prioritizes_uncovered_region_and_does_not_request_repeat(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("silver")}
    runtime, _env, _agent = _runtime(
        tmp_path, screen, [], enable_region_probes=True)
    runtime.protocol_map.observe(
        name="Clock", summary="Visible clock", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )
    _complete_fixture_survey(
        runtime, "Clock", screen["screenshot"],
        region_names=("Untouched controls", "Observed controls"),
    )
    untouched_ref = _region_probe_ref(
        runtime, "Clock", "Untouched controls")
    observed_ref = _region_probe_ref(
        runtime, "Clock", "Observed controls")

    def append_supported_probe(probe_id: str, action_index: int) -> None:
        runtime.graph.action_edges.append({
            "action_edge_id": f"edge-{action_index}",
            "attempts": [{
                "attempt_id": f"attempt-{action_index}",
                "action_index": action_index,
                "committed": True,
                "action": {
                    "action_type": "CLICK",
                    "selector": {"element_label": "Start"},
                },
                "evidence": {
                    "region_probe_task": True,
                    "region_probe_start": True,
                    "probe_id": probe_id,
                    "source_region_ref": observed_ref,
                    "effect_observations": [{
                        "capability_name": "Start stopwatch",
                        "reason": (
                            "The visible status changed from stopped to running."
                        ),
                        "effect_kind": "state_change",
                        "observed_changes": [{
                            "scope": {"region_ref": untouched_ref},
                            "fact": "stopwatch.status",
                            "before": "stopped",
                            "after": "running",
                        }],
                        "parameter_bindings": {},
                        "predicate_candidate": (
                            "The stopwatch status visibly reads running."
                        ),
                        "verdict": "supported",
                    }],
                },
            }],
        })

    append_supported_probe(f"probe:{observed_ref}:1", 1)
    candidates = _region_probe_candidates(runtime)

    assert candidates[0]["region_ref"] == untouched_ref
    assert _region_probe_capability_evidence(
        runtime, untouched_ref) == []
    observed_candidate = next(
        item for item in candidates if item["region_ref"] == observed_ref)
    runtime.exploration_task = _region_probe_task(
        runtime, observed_candidate)
    task_view = loop._exploration_map_view(
        runtime, None, screen["screenshot"])["task"]
    assert "already demonstrates its operation type" in task_view["reason"]
    assert task_view["known_capabilities"] == [{
        "name": "Start stopwatch",
        "effect": "The stopwatch status visibly reads running.",
        "evidence": (
            "This operation type is covered for traversal. Its separate "
            "evidence level is discovered; do not repeat the same control "
            "solely to upgrade that level."
        ),
    }]

    append_supported_probe(f"probe:{observed_ref}:2", 2)
    candidates = _region_probe_candidates(runtime)

    assert candidates[0]["region_ref"] == untouched_ref
    repeated = _region_probe_effect_memory(runtime, observed_ref)
    assert repeated[0]["evidence"].startswith(
        "This operation type is covered for traversal")

    runtime.region_probe_progress[observed_ref] = {"status": "complete"}
    assert observed_ref not in {
        item["region_ref"] for item in _region_probe_candidates(runtime)
    }


def test_region_probe_rejects_another_value_for_covered_input_operation(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("white")}
    runtime, _env, _agent = _runtime(
        tmp_path, screen, [], enable_region_probes=True)
    runtime.protocol_map.observe(
        name="Search", summary="Visible query surface", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )
    _complete_fixture_survey(
        runtime, "Search", screen["screenshot"],
        region_names=("Query panel",),
    )
    region_ref = _region_probe_ref(runtime, "Search", "Query panel")
    runtime.exploration_task = _region_probe_task(
        runtime,
        next(item for item in _region_probe_candidates(runtime)
             if item["region_ref"] == region_ref),
    )
    covered_key = (
        f"input_text:{_action_element_uid(region_ref, 'Visible query field')}")
    runtime.region_probe_progress[region_ref] = {
        "status": "pending",
        "covered_operations": [covered_key],
    }

    issue = _covered_region_probe_operation_issue(runtime, covered_key)

    assert "already covered for traversal" in issue
    assert "homogeneous example" in issue
    assert _covered_region_probe_operation_issue(
        runtime,
        f"input_text:{_action_element_uid(region_ref, 'Distinct filter field')}",
    ) == ""


def test_region_task_closes_on_no_action_without_gui_action(
    tmp_path,
) -> None:
    screen = {"screenshot": _png("purple")}
    runtime, env, _agent = _runtime(
        tmp_path, screen, [
            _turn(
                "Clock", action="NONE", identity="known",
            ),
        ], enable_region_probes=True,
    )
    runtime.protocol_map.observe(
        name="Clock", summary="Visible clock", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )
    _complete_fixture_survey(
        runtime, "Clock", screen["screenshot"],
        region_names=("Status",),
    )

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason == "framework_complete"
    assert env.actions == []
    assert runtime.region_probe_progress == {}
    saved = json.loads(
        (Path(tmp_path) / "autonomous_regions.json").read_text("utf-8"))
    assert saved["schema"] == "gui_rewalk.autonomous_regions_by_page.v8"
    assert saved["region_probe_progress"] == {}


def test_region_no_action_completion_requires_owning_variant(
    tmp_path,
) -> None:
    empty = _png("white")
    modal = _png("silver")
    runtime, _env, _agent = _runtime(
        tmp_path, {"screenshot": empty}, [], enable_region_probes=True)
    page_name, issue = runtime.protocol_map.observe(
        name="Alarms", summary="Alarm clock", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=empty, variant_name="Empty State",
        variant_identity="new", visible_predicates=["Add Alarm is visible"],
        commit_regions=False,
    )
    assert issue == ""
    empty_scene = loop._register_scene(
        runtime, empty,
        _turn(
            "Alarms", action="NONE", identity="new",
            variant_name="Empty State", variant_identity="new",
            visible_predicates=["Add Alarm is visible"],
        ),
        page_name,
    )
    _complete_fixture_survey(
        runtime, "Alarms", empty, region_names=("Empty State Content",))
    entry_id = runtime.entry_ledger.record_agent_update(
        page_name="Alarms",
        region_name="Empty State Content",
        frame_id=loop.screenshot_frame_id(empty),
        observations=[{"target": "Add Alarm"}],
        source_state_id=empty_scene.state_id,
    ).added[0]

    page_name, issue = runtime.protocol_map.observe(
        name="Alarms", summary="Alarm clock", identity="known",
        matched_page_name="Alarms", surface_kind="dialog", regions=(),
        screenshot=modal, variant_name="New Alarm Modal",
        variant_identity="new", visible_predicates=["Name field is visible"],
        commit_regions=False,
    )
    assert issue == ""
    modal_scene = loop._register_scene(
        runtime, modal,
        _turn(
            "Alarms", action="NONE", identity="known",
            variant_name="New Alarm Modal", variant_identity="new",
            visible_predicates=["Name field is visible"],
        ),
        page_name,
    )
    _complete_fixture_survey(
        runtime, "Alarms", modal,
        region_names=("Alarm Configuration Fields",),
    )

    page_name, issue = runtime.protocol_map.observe(
        name="Alarms", summary="Alarm clock", identity="known",
        matched_page_name="Alarms", surface_kind="page", regions=(),
        screenshot=empty, variant_name="Empty State",
        variant_identity="known", visible_predicates=["Add Alarm is visible"],
        commit_regions=False,
    )
    assert issue == ""
    rebound = loop._register_scene(
        runtime, empty,
        _turn(
            "Alarms", action="NONE", identity="known",
            variant_name="Empty State", variant_identity="known",
            visible_predicates=["Add Alarm is visible"],
        ),
        page_name,
    )
    assert rebound.state_id == empty_scene.state_id
    assert modal_scene.state_id != empty_scene.state_id

    pending_entry = runtime.entry_ledger.begin_explicit_action(
        entry_id,
        frame_id=loop.screenshot_frame_id(empty),
        page_name="Alarms",
    )
    runtime.entry_ledger.finish_action(
        pending_entry.action_id,
        action_executed=True,
        outcome_verified=True,
        result="Add Alarm revealed the New Alarm modal.",
        destination_page="Alarms",
        destination_state_id=modal_scene.state_id,
    )
    action = {
        "action_type": "CLICK",
        "selector": {
            "element_label": "Add Alarm",
            "region": "Empty State Content",
            "description": "click visible Add Alarm",
        },
        "parameters": {"button": "left"},
    }
    runtime.graph.add_transition(
        empty_scene.state_id,
        modal_scene.state_id,
        action,
        element_id=AUTONOMOUS_ENTRY_UID_PREFIX + entry_id,
        element_label="Add Alarm",
        region="Empty State Content",
        effect_verdict="observed_change",
        landing_verified=True,
        target_page_name="Alarms",
    )

    region_ref = _region_probe_ref(
        runtime, "Alarms", "Alarm Configuration Fields")
    candidate = next(
        item for item in _region_probe_candidates(runtime)
        if item["region_ref"] == region_ref
    )
    scheduled = _region_probe_task(runtime, candidate)
    assert scheduled.phase == "route_to_page"
    assert scheduled.route_hint == [{
        "from": "Alarms (Empty State)",
        "via": "Add Alarm",
        "action": "CLICK",
        "to": "Alarms (New Alarm Modal)",
        "provenance": "landing_verified",
        "entry_id": entry_id,
    }]
    runtime.exploration_task = scheduled
    task_view = _exploration_map_view(runtime, None, empty)["task"]
    assert task_view["route"][0]["entry_id"] == entry_id
    route_decision = loop.AutonomousDecision(
        action="CLICK",
        target="Add Alarm",
        point_1000=[500, 650],
        direction="",
        reason="Follow the verified route to the owning Variant.",
        tool_name="click",
        tool_arguments={
            "target": "Add Alarm",
            "entry_id": entry_id,
            "point_1000": [500, 650],
        },
    )
    assert loop._covered_entry_click_issue(
        runtime, "Alarms", route_decision) == ""

    runtime.exploration_task = replace(
        scheduled, phase="explore_region", route_hint=[])

    assert loop._complete_region_task_from_no_action(
        runtime,
        reason="The configuration fields are not visible on this screen.",
    ) is False
    assert region_ref not in runtime.region_probe_progress

    page_name, issue = runtime.protocol_map.observe(
        name="Alarms", summary="Alarm clock", identity="known",
        matched_page_name="Alarms", surface_kind="dialog", regions=(),
        screenshot=modal, variant_name="New Alarm Modal",
        variant_identity="known", visible_predicates=["Name field is visible"],
        commit_regions=False,
    )
    assert issue == ""
    arrived = loop._register_scene(
        runtime, modal,
        _turn(
            "Alarms", action="NONE", identity="known",
            variant_name="New Alarm Modal", variant_identity="known",
            visible_predicates=["Name field is visible"],
        ),
        page_name,
    )
    assert arrived.state_id == modal_scene.state_id
    runtime.exploration_task = _region_probe_task(runtime, candidate)
    assert runtime.exploration_task.phase == "explore_region"
    assert loop._complete_region_task_from_no_action(
        runtime,
        reason="No additional safe visible operation remains.",
    ) is True
    assert runtime.region_probe_progress[region_ref]["status"] == "complete"


def test_region_probe_records_reviewer_bound_no_effect(tmp_path) -> None:
    screen = {"screenshot": _png("teal")}
    runtime, _env, _agent = _runtime(
        tmp_path, screen, [
            _turn(
                "Timer", action="CALL_TOOL", identity="known",
                target="Pause", tool_name="click",
                tool_arguments={
                    "target": "Pause", "entry_id": "ae1",
                    "point_1000": [500, 500],
                },
            ),
            _turn(
                "Timer", action="NONE", identity="known",
                tool_name="",
                outcome="no_visible_change", matches_intent=False,
                previous_reason="Pause was activated but nothing changed.",
            ),
        ], [screen], enable_region_probes=True,
    )
    runtime.protocol_map.observe(
        name="Timer", summary="Visible timer", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )
    loop._register_scene(
        runtime,
        screen["screenshot"],
        _turn("Timer", action="NONE", identity="known"),
        "Timer",
    )
    _complete_fixture_survey(
        runtime, "Timer", screen["screenshot"],
        region_names=("Timer controls",),
    )
    assert runtime.entry_ledger.record_agent_update(
        page_name="Timer", region_name="Timer controls",
        frame_id=loop.screenshot_frame_id(screen["screenshot"]),
        observations=[{"target": "Pause"}],
    ).added == ["ae1"]
    runtime.click_reviewer = lambda _request: {
        "decision": "approve",
        "point_matches_target": True,
        "target_matches_request": True,
        "observed_target": "Pause",
        "risk": "safe",
        "reason": "The point is centered on the visible Pause control.",
    }

    graph = loop.run_autonomous_traversal(runtime, screen)

    assert graph.stop_reason in {
        "framework_partial", "all_remaining_work_suspended",
    }
    evidence = graph.action_edges[0]["attempts"][0]["evidence"]
    assert evidence["entry_id"] == "ae1"
    assert induce_capability_graph(graph)["capabilities"] == []
    assert runtime.entry_ledger.get("ae1").entry_id == "ae1"


def test_region_probe_progress_survives_resume(tmp_path) -> None:
    screen = {"screenshot": _png("orange")}
    runtime, _env, _agent = _runtime(
        tmp_path, screen, [], enable_region_probes=True)
    runtime.protocol_map.observe(
        name="Clock", summary="Visible clock", identity="new",
        matched_page_name="", surface_kind="page", regions=(),
        screenshot=screen["screenshot"], commit_regions=False,
    )
    _complete_fixture_survey(
        runtime, "Clock", screen["screenshot"],
        region_names=("Controls",),
    )
    region_ref = _region_probe_ref(runtime, "Clock", "Controls")
    runtime.region_probe_progress[region_ref] = {
        "status": "pending",
        "page_name": "Clock",
        "region_name": "Controls",
        "completed_attempts": 2,
        "covered_operations": ["input_text:autonomous-element:query"],
        "successful_probes": 1,
        "last_result": "One more safe visible operation may remain.",
    }
    runtime.task_creation_order = {f"explore-region:{region_ref}": 7}
    runtime.next_task_creation_order = 8
    loop._checkpoint(runtime, [])

    restored, _env, _agent = _runtime(
        tmp_path, screen, [], enable_region_probes=True)
    restored.restore(str(Path(tmp_path) / "graph.json"))

    expected_progress = {
        region_ref: {
            key: value
            for key, value in runtime.region_probe_progress[region_ref].items()
            if key not in {"successful_probes", "last_result"}
        },
    }
    assert restored.region_probe_progress == expected_progress
    assert restored.task_creation_order == {
        f"explore-region:{region_ref}": 7,
    }
    assert restored.next_task_creation_order == 8
    assert restored.exploration_task is None
