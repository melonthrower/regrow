"""Autonomous traversal host, ledger restore and inferred-edge projection."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from typing import Any, Dict, List, Optional, Sequence

from .autonomous_agent import CodexAutonomousAgent
from .autonomous_entry_tools import AutonomousEntryLedger
from .autonomous_map import NaturalExplorationMap
from .autonomous_region_tools import (
    AutonomousRegionRegistry,
    AutonomousRegionState,
)
from .autonomous_turn import (
    AutonomousTurn,
    ExplorationTask,
    ObservedScene,
    PendingLandingPage,
    PendingPageIdentity,
    _page_key,
)
from .autonomous_scope_state import AutonomousScopeStateLedger


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _page_state_id(
    host: "AutonomousTraversalRuntime", page_name: str,
    variant_name: str,
) -> str:
    """Return the private State for one registered Page material Variant."""
    page_id = host.protocol_map.page_id(page_name)
    if not page_id:
        raise ValueError(f"registered Page has no internal id: {page_name}")
    variant_id = host.protocol_map.variant_id(page_name, variant_name)
    if not variant_id:
        raise ValueError(
            f"registered Page has no material Variant: {page_name}")
    preferred = f"auto_state_{variant_id}"
    if preferred in host.graph.graph:
        return preferred
    matches = [
        str(state_id)
        for state_id, node in host.graph.graph.nodes(data=True)
        if str(node.get("page_id") or "") == page_id
        and str(node.get("variant_id") or "") == variant_id
    ]
    return matches[-1] if matches else preferred


def _current_page_state_id(host: "AutonomousTraversalRuntime") -> str:
    """Resolve the exact currently bound Page and material Variant State."""
    page_name = str(host.protocol_map.current_page or "").strip()
    variant_name = str(host.protocol_map.current_variant or "").strip()
    if not page_name or not variant_name:
        return ""
    try:
        state_id = _page_state_id(host, page_name, variant_name)
    except ValueError:
        return ""
    return state_id if state_id in host.graph.graph else ""


def _register_scene(
    host: AutonomousTraversalRuntime,
    screenshot: bytes,
    turn: AutonomousTurn,
    page_name: str,
) -> ObservedScene:
    page_id = host.protocol_map.page_id(page_name)
    variant_name = host.protocol_map.current_variant
    variant = host.protocol_map.variant_facts(page_name, variant_name)
    variant_id = str(variant.get("internal_variant_id") or "")
    if not variant_id:
        raise ValueError(
            f"current Page Variant is not registered: {page_name}")
    state_id = _page_state_id(host, page_name, variant_name)
    visible_predicates = list(variant.get("visible_predicates") or [])
    observed_facts = {
        "summary": turn.screen_name,
        "variant_name": variant_name,
        "visible_predicates": visible_predicates,
    }
    fingerprint: Dict[str, Any] = {}
    screenshot_path = host.writer.save_screenshot(state_id, screenshot)
    is_new = host.graph.add_state(
        state_id,
        elements=[],
        screenshot_path=screenshot_path,
        app_name=host.app_name,
        visual_fingerprint=fingerprint,
        page_name=page_name,
        page_id=page_id,
        variant_id=variant_id,
        variant_signature={
            "variant_name": variant_name,
            "visible_predicates": visible_predicates,
        },
        observed_facts=observed_facts,
        visible_capabilities=[],
        semantic_blocks=[],
        perception_mode="autonomous_vlm",
        geometry_mode="full_screenshot_1000",
    )
    if is_new:
        host.writer.save_node(
            state_id,
            screenshot,
            [],
            fingerprint,
            page_name=page_name,
            app_id=host.app_name,
            page_id=page_id,
            variant_id=variant_id,
            variant_signature={
                "variant_name": variant_name,
                "visible_predicates": visible_predicates,
            },
            observed_facts=observed_facts,
            visible_capabilities=[],
            semantic_blocks=[],
            perception_mode="autonomous_vlm",
            geometry_mode="full_screenshot_1000",
        )
    return ObservedScene(
        state_id=state_id,
        screenshot=screenshot,
        page_name=page_name,
        variant_name=variant_name,
        is_new=bool(is_new),
    )


def _checkpoint(
    host: AutonomousTraversalRuntime,
    history: Sequence[Dict[str, Any]],
) -> None:
    host.graph.save(host.graph_path)
    host.protocol_map.save(host.output_root)
    host.writer._write_json_atomic(
        os.path.join(host.output_root, "autonomous_regions.json"),
        {
            "schema": "gui_rewalk.autonomous_regions_by_page.v8",
            "pages": {
                page_key: state.snapshot()
                for page_key, state in host.region_states.items()
            },
            "region_groups": host.region_registry.snapshot(),
            "pending_corrections": deepcopy(
                host.page_update_corrections),
            "pending_resurveys": deepcopy(host.pending_page_resurveys),
            "empty_region_surveys": {
                page_key: sorted(state_ids)
                for page_key, state_ids in sorted(
                    host.empty_region_surveys.items())
                if state_ids
            },
            "pending_entry_review": deepcopy(host.pending_entry_review),
            "entry_review_deferred_frames": deepcopy(
                host.entry_review_deferred_frames),
            "entry_review_audits": deepcopy(
                host.entry_review_audits),
            "entry_review_evidence_generation": (
                host.entry_review_evidence_generation),
            "region_probe_progress": deepcopy(host.region_probe_progress),
            "scope_states": host.scope_state_ledger.snapshot(),
            "task_dependencies": deepcopy(host.task_dependencies),
            "task_creation_order": deepcopy(host.task_creation_order),
            "next_task_creation_order": host.next_task_creation_order,
        },
    )
    host.writer._write_json_atomic(
        os.path.join(host.output_root, "autonomous_entries.json"),
        host.entry_ledger.snapshot(),
    )
    host.writer._write_json_atomic(
        os.path.join(host.output_root, "autonomous_temporary_states.json"),
        {
            "schema": "gui_rewalk.autonomous_temporary_states.v1",
            "states": list(host.temporary_states.values()),
        },
    )
    host.writer._write_json_atomic(
        os.path.join(host.output_root, "autonomous_trace.json"),
        {
            "schema": "gui_rewalk.autonomous_trace.v2",
            "app_name": host.app_name,
            "model": host.decision_agent.model,
            "stop_reason": host.graph.stop_reason,
            "actions": host.action_count,
            "history": list(history),
            "backend_runs": list(host.decision_agent.backend_runs),
            "fixture_audit": list(host.fixture_audit_records),
            "target_edge_test": (
                {
                    **host.target_edge_scope,
                    "excluded_entry_ids": sorted(
                        host.target_edge_excluded_ids),
                    "matched_entries": [
                        entry.serializable()
                        for entry in _target_edge_matches(host)
                    ],
                }
                if host.target_edge_scope else None
            ),
        },
    )


def _temporary_state_key(page_name: str, control: str) -> str:
    return f"{_page_key(page_name)}::{_page_key(control)}"


class AutonomousTraversalRuntime:
    """Small host that captures, executes and records the model's decisions."""

    def __init__(
        self,
        env: Any,
        decision_agent: CodexAutonomousAgent,
        app_name: str,
        output_root: str,
        *,
        max_states: int,
        max_actions: int,
        fixture_audit: Any = None,
        identity_resolver: Any = None,
        target_edge_scope: Optional[Dict[str, str]] = None,
        enable_region_probes: bool = True,
        relaunch_fn: Any = None,
        desktop_window_owner: Any = None,
    ) -> None:
        from gui_rewalk.src.core.graph.state_graph import StateGraph
        from ..artifacts import ArtifactWriter

        self.env = env
        self.decision_agent = decision_agent
        self.app_name = app_name
        self.output_root = os.path.abspath(output_root)
        self.max_states = int(max_states)
        self.max_actions = int(max_actions)
        self.action_count = 0
        self.fixture_audit = fixture_audit
        self.target_edge_scope = (
            {
                "source_page": str(target_edge_scope.get("source_page") or "").strip(),
                "target": str(target_edge_scope.get("target") or "").strip(),
                "expected_destination": str(
                    target_edge_scope.get("expected_destination") or ""
                ).strip(),
            }
            if target_edge_scope else None
        )
        self.enable_region_probes = bool(enable_region_probes)
        self.relaunch_fn = relaunch_fn
        self.desktop_window_owner = desktop_window_owner
        if self.target_edge_scope and not all(self.target_edge_scope.values()):
            raise ValueError("target edge scope requires source_page and target")
        self.target_edge_excluded_ids: set[str] = set()
        self.identity_resolver = (
            identity_resolver
            if identity_resolver is not None
            else getattr(decision_agent, "resolve_page_identity", None)
        )
        self.region_reviewer = getattr(
            decision_agent, "review_region_proposal", None)
        self.cross_page_region_reviewer = getattr(
            decision_agent, "review_cross_page_regions", None)
        self.region_mapper = getattr(
            decision_agent, "map_region_partitions", None)
        self.entry_reviewer = getattr(
            decision_agent, "review_entry_candidates", None)
        self.entry_presence_reviewer = getattr(
            decision_agent, "review_entry_presence", None)
        self.click_reviewer = getattr(decision_agent, "review_click", None)
        self.interruption_reviewer = getattr(
            decision_agent, "review_interruption", None)
        self.fixture_audit_records: List[Dict[str, Any]] = []
        self.protocol_map = NaturalExplorationMap()
        self.tool_images: List[bytes] = []
        self.tool_image_labels: List[str] = []
        self.exploration_task: Optional[ExplorationTask] = None
        self.task_rejection_streak = 0
        self.run_rejection_streak = 0
        self.rejection_task_key = ""
        self.suspended_task_keys: set[str] = set()
        self.interruption_task_key = ""
        self.interruption_rounds = 0
        self.resume_history: List[Dict[str, Any]] = []
        self.pending_connection: Optional[Dict[str, str]] = None
        self.pending_page_identity: Optional[PendingPageIdentity] = None
        self.pending_landing_page: Optional[PendingLandingPage] = None
        self.identity_feedback: Optional[Dict[str, str]] = None
        self.region_states: Dict[str, AutonomousRegionState] = {}
        self.region_registry = AutonomousRegionRegistry()
        self.page_update_corrections: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.region_review_screenshots: Dict[str, bytes] = {}
        self.entry_review_screenshot = b""
        self.pending_page_resurveys: Dict[str, Dict[str, str]] = {}
        self.empty_region_surveys: Dict[str, set[str]] = {}
        self.pending_entry_review: Optional[Dict[str, Any]] = None
        self.entry_review_deferred_frames: Dict[
            str, Dict[str, str]
        ] = {}
        self.entry_review_audits: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.entry_review_evidence_generation = 0
        self.region_probe_progress: Dict[str, Dict[str, Any]] = {}
        self.scope_state_ledger = AutonomousScopeStateLedger()
        self.task_dependencies: Dict[str, Dict[str, Any]] = {}
        self.task_creation_order: Dict[str, int] = {}
        self.next_task_creation_order = 1
        self.pending_region_mapping_context: Optional[Dict[str, Any]] = None
        self.entry_ledger = AutonomousEntryLedger()
        self.temporary_states: Dict[str, Dict[str, Any]] = {}
        self.graph = StateGraph(app_name)
        self.writer = ArtifactWriter(self.output_root)
        self.graph_path = os.path.join(self.output_root, "graph.json")
        self.platform = str(
            getattr(env, "vm_platform", "")
            or getattr(getattr(env, "controller", None), "vm_platform", "")
            or "desktop"
        )

    def restore(self, resume_path: str) -> None:
        """Restore one autonomous run from its own persisted ledgers."""
        from gui_rewalk.src.core.graph.state_graph import StateGraph

        graph_path = os.path.abspath(resume_path)
        if os.path.normcase(os.path.dirname(graph_path)) != os.path.normcase(
                self.output_root):
            raise ValueError("autonomous resume graph must live in output_root")
        graph = StateGraph.load(graph_path)
        if (self.app_name and graph.app_name not in {self.app_name, "unknown"}):
            raise ValueError(
                f"resume app mismatch: graph={graph.app_name!r}, "
                f"requested={self.app_name!r}"
            )
        previous_stop = str(graph.stop_reason or "incomplete")
        graph.stop_reason = "incomplete"
        self.graph = graph
        self.graph_path = graph_path
        self.protocol_map = NaturalExplorationMap.from_output(
            self.output_root, graph)

        regions_path = os.path.join(
            self.output_root, "autonomous_regions.json")
        if os.path.isfile(regions_path):
            with open(regions_path, "r", encoding="utf-8") as stream:
                region_payload = json.load(stream)
            pages = (
                region_payload.get("pages")
                if isinstance(region_payload, dict) else None)
            if isinstance(pages, dict):
                self.region_states = {
                    str(page_key): AutonomousRegionState.from_snapshot(snapshot)
                    for page_key, snapshot in pages.items()
                    if isinstance(snapshot, dict)
                }
            groups = (
                region_payload.get("region_groups")
                if isinstance(region_payload, dict) else None
            )
            self.region_registry = AutonomousRegionRegistry.from_snapshot(
                groups if isinstance(groups, dict) else {},
                page_states=self.region_states,
            )
            scope_states = (
                region_payload.get("scope_states")
                if isinstance(region_payload, dict) else None
            )
            self.scope_state_ledger = AutonomousScopeStateLedger.from_snapshot(
                scope_states if isinstance(scope_states, dict) else {})
            corrections = (
                region_payload.get("pending_corrections")
                if isinstance(region_payload, dict) else None
            )
            if isinstance(corrections, dict):
                self.page_update_corrections = {
                    str(page_key): {
                        str(item_key): dict(item)
                        for item_key, item in items.items()
                        if isinstance(item, dict)
                    }
                    for page_key, items in corrections.items()
                    if isinstance(items, dict)
                }
            pending_resurveys = (
                region_payload.get("pending_resurveys")
                if isinstance(region_payload, dict) else None
            )
            if isinstance(pending_resurveys, dict):
                self.pending_page_resurveys = {
                    str(page_key): {
                        str(key): str(value)
                        for key, value in record.items()
                        if value not in (None, "")
                    }
                    for page_key, record in pending_resurveys.items()
                    if isinstance(record, dict)
                }
            empty_region_surveys = (
                region_payload.get("empty_region_surveys")
                if isinstance(region_payload, dict) else None
            )
            if isinstance(empty_region_surveys, dict):
                self.empty_region_surveys = {
                    str(page_key): {
                        str(state_id) for state_id in state_ids
                        if str(state_id).strip()
                    }
                    for page_key, state_ids in empty_region_surveys.items()
                    if isinstance(state_ids, list)
                }
            pending_entry_review = (
                region_payload.get("pending_entry_review")
                if isinstance(region_payload, dict) else None
            )
            if isinstance(pending_entry_review, dict):
                candidates = pending_entry_review.get("candidates")
                regions = pending_entry_review.get("regions")
                if isinstance(candidates, list) and isinstance(regions, list):
                    self.pending_entry_review = deepcopy(pending_entry_review)
            deferred_frames = (
                region_payload.get("entry_review_deferred_frames")
                if isinstance(region_payload, dict) else None
            )
            if isinstance(deferred_frames, dict):
                self.entry_review_deferred_frames = {
                    str(page_key): {
                        str(region_key): str(frame_id)
                        for region_key, frame_id in regions.items()
                        if str(region_key) and str(frame_id)
                    }
                    for page_key, regions in deferred_frames.items()
                    if isinstance(regions, dict)
                }
            review_audits = (
                region_payload.get("entry_review_audits")
                if isinstance(region_payload, dict) else None
            )
            if isinstance(review_audits, dict):
                self.entry_review_audits = {
                    str(page_key): {
                        str(region_key): deepcopy(audit)
                        for region_key, audit in regions.items()
                        if isinstance(audit, dict)
                    }
                    for page_key, regions in review_audits.items()
                    if isinstance(regions, dict)
                }
            try:
                self.entry_review_evidence_generation = max(
                    0, int(region_payload.get(
                        "entry_review_evidence_generation") or 0))
            except (TypeError, ValueError):
                self.entry_review_evidence_generation = 0

            probe_progress = region_payload.get("region_probe_progress")
            if isinstance(probe_progress, dict):
                self.region_probe_progress = {
                    str(region_ref): {
                        key: deepcopy(value)
                        for key, value in record.items()
                        if key not in {"successful_probes", "last_result"}
                    }
                    for region_ref, record in probe_progress.items()
                    if str(region_ref).strip() and isinstance(record, dict)
                }
            dependencies = region_payload.get("task_dependencies")
            if isinstance(dependencies, dict):
                self.task_dependencies = {
                    str(task_key): {
                        field: str(record.get(field) or "")[:500]
                        for field in (
                            "prerequisite_task_id", "prerequisite_entry_id",
                            "prerequisite_target", "reason", "status",
                            "previous_prerequisite_entry_id",
                            "rechecked_prerequisite_entry_id",
                            "prerequisite_result", "failure_kind",
                            "prerequisite_release_consumed",
                        )
                    } | {
                        "recheck_count": _nonnegative_int(
                            record.get("recheck_count"))
                    }
                    for task_key, record in dependencies.items()
                    if str(task_key).strip() and isinstance(record, dict)
                }
            task_creation_order = region_payload.get("task_creation_order")
            if isinstance(task_creation_order, dict):
                self.task_creation_order = {
                    str(task_key): int(order)
                    for task_key, order in task_creation_order.items()
                    if str(task_key).strip()
                    and isinstance(order, int)
                    and not isinstance(order, bool)
                    and order > 0
                }
            stored_next_order = region_payload.get("next_task_creation_order")
            if isinstance(stored_next_order, int) and not isinstance(
                    stored_next_order, bool):
                self.next_task_creation_order = max(
                    stored_next_order,
                    max(self.task_creation_order.values(), default=0) + 1,
                )

        entries_path = os.path.join(
            self.output_root, "autonomous_entries.json")
        if os.path.isfile(entries_path):
            with open(entries_path, "r", encoding="utf-8") as stream:
                entry_payload = json.load(stream)
            if isinstance(entry_payload, dict):
                prior_entry_action_ids = [
                    str((attempt.get("evidence") or {}).get(
                        "entry_action_id") or "")
                    for edge in self.graph.action_edges
                    if isinstance(edge, dict)
                    for attempt in edge.get("attempts") or []
                    if isinstance(attempt, dict)
                ]
                self.entry_ledger = AutonomousEntryLedger.from_snapshot(
                    entry_payload,
                    prior_action_ids=prior_entry_action_ids,
                )

        temporary_path = os.path.join(
            self.output_root, "autonomous_temporary_states.json")
        if os.path.isfile(temporary_path):
            with open(temporary_path, "r", encoding="utf-8") as stream:
                temporary_payload = json.load(stream)
            for raw in (
                    temporary_payload.get("states")
                    if isinstance(temporary_payload, dict) else []) or []:
                if not isinstance(raw, dict):
                    continue
                page_name = str(raw.get("page_name") or "").strip()
                control = str(raw.get("control") or "").strip()
                if page_name and control:
                    self.temporary_states[
                        _temporary_state_key(page_name, control)] = dict(raw)

        trace_path = os.path.join(self.output_root, "autonomous_trace.json")
        if os.path.isfile(trace_path):
            with open(trace_path, "r", encoding="utf-8") as stream:
                trace_payload = json.load(stream)
            if isinstance(trace_payload, dict):
                self.resume_history = [
                    dict(item) for item in trace_payload.get("history") or []
                    if isinstance(item, dict)
                ][-8:]
        self.resume_history.append({
            "kind": "resume",
            "outcome": "restored_autonomous_ledgers",
            "detail": f"continued after previous stop={previous_stop}",
        })
        self.action_count = 0
        self.exploration_task = None
        _record_agent_inferred_edges(self)

    def audit_fixture(
        self, action: Optional[Dict[str, Any]], phase: str,
        event_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not callable(self.fixture_audit):
            return {}
        try:
            payload = dict(self.fixture_audit(action) or {})
        except Exception as exc:
            payload = {"error": str(exc)[:300]}
        record = {"phase": phase, "event_index": event_index, **payload}
        self.fixture_audit_records.append(record)
        return record

    def fresh_observation(self, fallback: Dict[str, Any]) -> Dict[str, Any]:
        try:
            observation = self.env._get_obs()
            if (observation or {}).get("screenshot"):
                return observation
        except Exception:
            pass
        return fallback


def _unique_state_for_page(
    host: AutonomousTraversalRuntime, page_name: str,
) -> str:
    matches = [
        str(state_id) for state_id, node in host.graph.graph.nodes(data=True)
        if _page_key(node.get("page_name")) == _page_key(page_name)
    ]
    return matches[0] if len(matches) == 1 else ""


def _record_agent_inferred_edges(host: AutonomousTraversalRuntime) -> None:
    """Materialize only explicit Agent equivalence as non-verified infer edges."""
    for occurrence in host.entry_ledger.entries:
        if (not occurrence.representative_entry_id
                or occurrence.inferred_edge_recorded):
            continue
        try:
            representative_id = host.entry_ledger.canonical_entry_id(
                occurrence.representative_entry_id)
            representative = host.entry_ledger.get(representative_id)
        except (KeyError, ValueError):
            continue
        if representative.status.value != "verified":
            continue
        destination_page = (
            occurrence.destination_page or representative.destination_page)
        if not destination_page:
            continue
        explicit_source_states = [
            state_id for state_id in occurrence.source_state_ids
            if state_id in host.graph.graph
        ]
        source_state = occurrence.source_state_id
        if source_state not in host.graph.graph:
            source_state = (
                explicit_source_states[0]
                if len(explicit_source_states) == 1
                else _unique_state_for_page(host, occurrence.page_name)
            )
        destination_state = occurrence.destination_state_id
        if destination_state not in host.graph.graph:
            destination_state = representative.destination_state_id
        if destination_state not in host.graph.graph:
            destination_state = _unique_state_for_page(
                host, destination_page)
        if not source_state or not destination_state:
            continue
        host.protocol_map.connect_inferred(
            occurrence.page_name,
            destination_page,
            occurrence.target,
            entry_id=occurrence.entry_id,
            equivalent_to_entry_id=representative.entry_id,
            reason=occurrence.equivalence_reason,
        )
        host.graph.record_action_event(
            source=source_state,
            target=destination_state,
            action={"action_type": "INFERRED"},
            element_label=occurrence.target,
            semantic_description=occurrence.equivalence_reason,
            region=occurrence.region_name,
            outcome="inferred_from_agent_equivalence",
            detail=(
                f"Agent declared {occurrence.entry_id} equivalent to "
                f"{representative.entry_id}"
            ),
            landing_verified=False,
            target_page_name=destination_page,
            committed=False,
            evidence={
                "provenance": "agent_inferred_equivalence",
                "entry_id": occurrence.entry_id,
                "equivalent_to_entry_id": representative.entry_id,
                "equivalence_reason": occurrence.equivalence_reason,
                "no_gui_action": True,
            },
        )
        occurrence.inferred_edge_recorded = True

def _target_edge_matches(
    host: AutonomousTraversalRuntime,
) -> List[Any]:
    scope = host.target_edge_scope
    if not scope:
        return []
    return [
        entry for entry in host.entry_ledger.entries
        if _page_key(entry.page_name) == _page_key(scope["source_page"])
        and _page_key(entry.target) == _page_key(scope["target"])
    ]


def _apply_target_edge_scope(
    host: AutonomousTraversalRuntime,
) -> Dict[str, Any]:
    """Exclude non-target tasks without fabricating coverage or action evidence."""
    scope = host.target_edge_scope
    if not scope:
        return {}
    newly_excluded: List[str] = []
    matched_ids = {entry.entry_id for entry in _target_edge_matches(host)}
    for entry in host.entry_ledger.entries:
        if entry.entry_id in matched_ids:
            continue
        if entry.status.value not in {"discovered", "unresolved"}:
            continue
        entry.task_eligible = False
        if entry.entry_id not in host.target_edge_excluded_ids:
            host.target_edge_excluded_ids.add(entry.entry_id)
            newly_excluded.append(entry.entry_id)
    return {
        "source_page": scope["source_page"],
        "target": scope["target"],
        "matched_entry_ids": sorted(matched_ids),
        "newly_excluded_entry_ids": newly_excluded,
    }


def _target_edge_terminal_result(
    host: AutonomousTraversalRuntime,
) -> Optional[Dict[str, Any]]:
    scope = host.target_edge_scope
    if not scope:
        return None
    matches = _target_edge_matches(host)
    verified = [entry for entry in matches if entry.status.value == "verified"]
    if verified:
        entry = verified[0]
        if (_page_key(entry.destination_page)
                != _page_key(scope["expected_destination"])):
            return {
                "status": "failed",
                "stop_reason": "target_edge_wrong_destination",
                "source_page": scope["source_page"],
                "target": scope["target"],
                "entry_id": entry.entry_id,
                "destination_page": entry.destination_page,
                "expected_destination": scope["expected_destination"],
                "attempt_count": entry.attempt_count,
            }
        return {
            "status": "passed",
            "stop_reason": "target_edge_verified",
            "source_page": scope["source_page"],
            "target": scope["target"],
            "entry_id": entry.entry_id,
            "destination_page": entry.destination_page,
            "expected_destination": scope["expected_destination"],
            "attempt_count": entry.attempt_count,
        }

    source_state = host.region_states.get(_page_key(scope["source_page"]))
    source_regions = (
        source_state.snapshot().get("regions") or []
        if source_state is not None else []
    )
    source_survey_complete = bool(source_regions) and all(
        bool(region.get("coverage_complete")) for region in source_regions)
    if source_survey_complete and not matches:
        return {
            "status": "failed",
            "stop_reason": "target_edge_not_discovered",
            "source_page": scope["source_page"],
            "target": scope["target"],
            "entry_id": "",
            "destination_page": "",
            "expected_destination": scope["expected_destination"],
            "attempt_count": 0,
        }
    if matches and all(
            entry.status.value == "inferred" or not entry.task_eligible
            for entry in matches):
        entry = matches[0]
        return {
            "status": "failed",
            "stop_reason": "target_edge_not_directly_verified",
            "source_page": scope["source_page"],
            "target": scope["target"],
            "entry_id": entry.entry_id,
            "destination_page": entry.destination_page,
            "expected_destination": scope["expected_destination"],
            "attempt_count": entry.attempt_count,
        }
    return None
