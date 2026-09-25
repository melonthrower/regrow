"""Atomic reconstruction of a visual traversal run from a persisted graph.

This module owns the resume data transformation, but deliberately knows nothing
about :class:`VisualTraversalEngine`.  It builds every mutable runtime ledger on
fresh objects and returns a snapshot.  The engine may then publish that snapshot
in one short commit step; a malformed graph therefore cannot leave a half-resumed
engine behind.
"""

from __future__ import annotations

import copy
import dataclasses
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Mapping

import imagehash

from .grounding.region import element_is_action, element_member_token
from .navigation.router import is_peer_navigation_role
from .state.block_identity import (
    semantic_surface_host_token,
    semantic_surface_kind,
)

logger = logging.getLogger(__name__)


def _is_function_surface_control(value: Any) -> bool:
    """Schema-tolerant predicate for stateful controls with node-local coverage."""
    get = value.get if isinstance(value, dict) else \
        lambda key, default=None: getattr(value, key, default)
    return (bool(get("stateful", False))
            and str(get("effect_scope", "") or "").strip().lower()
            == "function_set")


@dataclass(frozen=True)
class ResumeSnapshot:
    """A completely rebuilt, not-yet-published visual traversal runtime."""

    graph: Any
    state_data: Dict[str, Dict[str, Any]]
    registry: Any
    region_registry: Any
    memory: Any
    visited_uids: set[str]
    explored_groups: set[tuple[str, str]]
    abnormal_buttons: set[tuple[str, str, str]]
    frontier: deque[str]
    action_count: int


def element_from_dict(ed: Dict[str, Any], element_type) -> Any:
    """Reconstruct one persisted element while tolerating schema drift."""
    keep = {field.name for field in dataclasses.fields(element_type)}
    values = {key: value for key, value in (ed or {}).items() if key in keep}
    values.setdefault("id", -1)
    values.setdefault("name", "")
    values.setdefault("bbox_xywh", [0, 0, 1, 1])
    values.setdefault("center", [0, 0])
    return element_type(**values)


def abnormal_button_key(
    state_id: str,
    name: str,
    uid: str,
    region_id: str,
    normalize_name: Callable[[str], str],
) -> tuple[str, str, str]:
    """Stable source-local skip key for one observed terminal outcome."""
    normalized = normalize_name(name or "")
    token = str(uid or normalized or name or "")
    if region_id and normalized:
        token = f"{region_id}:{normalized}"
    return "state", str(state_id), token


def region_set_from_elements(
    elements,
    identity_chrome_roles: FrozenSet[str],
    normalize_name: Callable[[str], str],
) -> set:
    """Rebuild role-independent ``region:<rid>`` page-identity tokens."""
    by_region: Dict[str, Dict[str, Any]] = {}
    selected_tabs: set[str] = set()
    for element in elements:
        region_id = getattr(element, "region_id", "") or ""
        role = getattr(element, "region", "") or ""
        semantic = (
            str(getattr(element, "geometry_status", "") or "") == "semantic_only"
            or str(getattr(element, "source", "") or "") == "semantic_inventory")
        if not region_id or (role in identity_chrome_roles and not semantic):
            continue
        slot = by_region.setdefault(region_id, {"role": role, "names": set()})
        name = (element.name or "").strip()
        if not name:
            continue
        slot["names"].add(name)
        category = str(getattr(element, "category", "") or "").casefold().strip()
        if ((semantic and category in {"navigation", "nav"})
                or role == "tab_bar") and getattr(element, "selected", False):
            selected_name = normalize_name(name)
            if selected_name:
                selected_tabs.add(f"tab_selected:{selected_name}")
    return (
        {
            f"region:{region_id}"
            for region_id, facts in by_region.items()
            if facts["names"]
        }
        | selected_tabs
    )


def _accumulate_region_facts(
    state_id,
    elements,
    names_by_region,
    member_tokens_by_region,
    action_names_by_region,
    role_by_region,
    seen_by_region,
    clicked_by_region,
) -> None:
    for element in elements:
        region_id = getattr(element, "region_id", "") or ""
        if not region_id:
            continue
        role_by_region.setdefault(
            region_id, getattr(element, "region", "") or ""
        )
        name = (element.name or "").strip()
        if name:
            names_by_region.setdefault(region_id, set()).add(name)
            token = element_member_token(element)
            if token:
                member_tokens_by_region.setdefault(region_id, set()).add(token)
            if element_is_action(element):
                action_names_by_region.setdefault(region_id, set()).add(name)
            if (element_is_action(element)
                    and getattr(element, "visited", False)
                    and not _is_function_surface_control(element)
                    and not getattr(element, "abnormal_reason", "")):
                clicked_by_region.setdefault(region_id, set()).add(name)
        seen_by_region.setdefault(region_id, set()).add(state_id)


def _rebuild_registry_node(
    registry,
    state_id,
    node_data,
    elements,
    identity_chrome_roles,
    normalize_name,
) -> tuple[str, str]:
    fingerprint = node_data.get("visual_fingerprint", {}) or {}
    phash_hex = fingerprint.get("phash")
    screenshot_path = node_data.get("screenshot_path", "") or ""
    if phash_hex:
        try:
            registry._states[state_id] = (
                imagehash.hex_to_hash(phash_hex),
                screenshot_path,
            )
        except Exception:
            # Preserve the old fail-soft contract: a corrupt diagnostic pHash
            # does not discard otherwise usable button/region identity.
            logger.debug("bad phash hex for %s; skipping pHash tuple", state_id)
    registry.set_buttons(state_id, elements)
    rebuilt_region_set = region_set_from_elements(
        elements, identity_chrome_roles, normalize_name
    )
    surface_kind = semantic_surface_kind(
        node_data.get("semantic_blocks") or [],
        node_data.get("surface_kind") or "",
    )
    host_token = semantic_surface_host_token(
        node_data.get("semantic_blocks") or [],
        surface_kind=surface_kind,
        page_name=node_data.get("page_name") or "",
    )
    if host_token:
        rebuilt_region_set.add(host_token)
    registry._region_sets[state_id] = rebuilt_region_set
    if hasattr(registry, "_page_names"):
        registry._page_names[state_id] = str(node_data.get("page_name", "") or "")
    page_id = str(node_data.get("page_id", "") or state_id)
    variant_id = str(node_data.get("variant_id", "") or state_id)
    if hasattr(registry, "record_page_variant"):
        persisted_page = str(node_data.get("page_id", "") or "")
        persisted_variant = str(node_data.get("variant_id", "") or "")
        rebuilt_page, rebuilt_variant = registry.record_page_variant(
            state_id,
            str(node_data.get("page_name", "") or ""),
            elements=elements,
            namespace=str(node_data.get("app_name", "") or ""),
            persisted_page_id=persisted_page,
        )
        identity_version = str(
            node_data.get("page_identity_version") or "")
        strict_identity = identity_version in {
            "semantic_page_variant_v1", "hierarchical_page_identity_v1"}
        # External ids are issued by the autonomous Page/State producer. They
        # are authoritative opaque ids, not hashes of the collection
        # projection's reconstructed element inventory.
        producer_identity = strict_identity or identity_version == "external"
        page_id, variant_id = rebuilt_page, rebuilt_variant
        persisted_facts = node_data.get("observed_facts")
        if (producer_identity and persisted_variant
                and isinstance(persisted_facts, Mapping)):
            # A revisit can enrich one node's persisted functional inventory
            # without keeping every historical alias in ``elements``. Rebuilding
            # a strict v1 variant from the final element snapshot therefore loses
            # facts and changes its id. The graph's canonical observed_facts are
            # the durable identity material: validate their hash, then hydrate the
            # fresh registry with that exact identity. Corrupt graphs still fail
            # closed; only a lossy element re-derivation is bypassed.
            from .visual_state import compute_variant_id

            if strict_identity:
                expected_variant = compute_variant_id(
                    persisted_page or rebuilt_page, persisted_facts)
                if expected_variant != persisted_variant:
                    raise ValueError(
                        f"persisted variant facts mismatch for {state_id}: "
                        f"{persisted_variant} != {expected_variant}"
                    )
            if rebuilt_variant != persisted_variant:
                rebuilt_members = registry._variant_states.get(rebuilt_variant)
                if rebuilt_members is not None:
                    rebuilt_members.discard(state_id)
                    if not rebuilt_members:
                        registry._variant_states.pop(rebuilt_variant, None)
                        registry._variant_facts.pop(rebuilt_variant, None)
                registry._state_variant_ids[state_id] = persisted_variant
                registry._variant_states.setdefault(
                    persisted_variant, set()).add(state_id)
            registry._variant_facts[persisted_variant] = copy.deepcopy(
                dict(persisted_facts))
            variant_id = persisted_variant
        elif (strict_identity and persisted_variant
              and persisted_variant != rebuilt_variant):
            raise ValueError(
                f"variant identity mismatch for {state_id}: "
                f"{persisted_variant} != {rebuilt_variant}"
            )
    registry._clicked[state_id] = {
        (element.name or "").strip()
        for element in elements
        if (getattr(element, "visited", False)
            and not _is_function_surface_control(element)
            and not getattr(element, "abnormal_reason", "")
            and (element.name or "").strip())
    }
    return page_id, variant_id


def _install_regions(
    region_registry,
    names_by_region,
    member_tokens_by_region,
    action_names_by_region,
    role_by_region,
    seen_by_region,
    clicked_by_region,
) -> None:
    for region_id in names_by_region.keys() | role_by_region.keys():
        region_registry.rebuild_region(
            region_id=region_id,
            role=role_by_region.get(region_id, ""),
            names=names_by_region.get(region_id, set()),
            member_tokens=member_tokens_by_region.get(region_id, set()),
            action_names=action_names_by_region.get(region_id, set()),
            seen_on=seen_by_region.get(region_id, set()),
            clicked=clicked_by_region.get(region_id, set()),
        )


def _is_shared_button(name: str, region_registry) -> bool:
    normalized = " ".join((name or "").lower().split())
    return bool(normalized) and normalized in region_registry.shared_button_names()


def _verified_source_action_keys(action_edges, normalize_name):
    """Return source-local element ids/labels backed by committed landings."""
    result: Dict[str, Dict[str, set[str]]] = {}
    for edge in action_edges or []:
        attempts = list(edge.get("attempts") or [])
        verified = any(
            attempt.get("committed") is True
            and attempt.get("landing_verified") is True
            for attempt in attempts
        )
        if not verified and not (not attempts and edge.get("routing_verified") is True):
            continue
        source = str(edge.get("source") or "")
        if not source:
            continue
        slot = result.setdefault(source, {"ids": set(), "labels": set()})
        raw_id = edge.get("element_id")
        element_id = "" if raw_id is None else str(raw_id)
        if element_id:
            slot["ids"].add(element_id)
        label = str(edge.get("element_label") or "")
        action = edge.get("action") if isinstance(edge.get("action"), dict) else {}
        selector = action.get("selector") if isinstance(action.get("selector"), dict) else {}
        label = label or str(selector.get("element_label") or "")
        normalized = normalize_name(label)
        if normalized:
            slot["labels"].add(normalized)
    return result


def _reopen_unverified_persisted_control(
    state_id, element, verified_keys, normalize_name
) -> None:
    """Derive executable-control completion from source-local action evidence."""
    if not element_is_action(element):
        return
    # Older frontier filtering copied a shared Region's abnormal result onto a
    # different source element with this synthetic marker.  It is not an
    # observed outcome and must not survive resume as source-local evidence.
    if str(getattr(element, "abnormal_reason", "") or "") == \
            "terminal_observed_outcome":
        element.abnormal_reason = ""
        element.abnormal_detail = ""
        if str(getattr(element, "exploration_status", "") or "") == "terminal":
            element.exploration_status = ""
        element.visited = False
    source = verified_keys.get(str(state_id), {})
    raw_id = getattr(element, "id", None)
    element_id = "" if raw_id is None else str(raw_id)
    label = normalize_name(getattr(element, "name", "") or "")
    status = str(getattr(element, "exploration_status", "") or "")
    if status in {"complete", "covered", "semantic_only", "terminal"}:
        element.visited = True
        return
    if not getattr(element, "visited", False):
        return
    if (getattr(element, "selected", False)
            or getattr(element, "back", False)
            or getattr(element, "abnormal_reason", "")):
        return
    element.visited = False


_EVIDENCE_BOUNDED_ABNORMAL_REASONS = frozenset({
    "target_rebind_failed",
    "action_execution_failed",
    "action_verification_failed",
    "route_unavailable",
})


def _has_bounded_terminal_evidence(record) -> bool:
    reason = str(record.get("reason", "") or "").casefold()
    if reason not in _EVIDENCE_BOUNDED_ABNORMAL_REASONS:
        return True
    evidence = record.get("evidence")
    if not isinstance(evidence, dict):
        return False
    try:
        attempts = int(evidence.get("attempts_used", 0) or 0)
    except (TypeError, ValueError):
        return False
    if attempts < 2:
        return False
    if reason == "route_unavailable":
        landed = str(evidence.get("landed_state_id", "") or "")
        return (
            evidence.get("kind") == "route_unavailable"
            and bool(landed)
            and landed != str(record.get("state_id", "") or "")
        )
    return (
        evidence.get("kind") == "bounded_local_failure"
        and bool(str(evidence.get("failure_kind", "") or ""))
    )


def _rebuild_cross_node_ledgers(
    state_data,
    node_ids,
    region_registry,
    memory,
    visited_uids,
    explored_groups,
    is_chrome_name,
) -> None:
    for state_id in node_ids:
        for element in state_data[state_id].get("elements", []) or []:
            if not getattr(element, "visited", False):
                continue
            is_function_surface = _is_function_surface_control(element)
            uid = getattr(element, "uid", "")
            if uid and not is_function_surface:
                visited_uids.add(uid)
            if getattr(element, "abnormal_reason", ""):
                # Terminal failure is not successful functional/region coverage.
                continue
            if is_function_surface:
                # OFF and ON nodes may carry the same visual UID/region/name.  The
                # source element's own visited flag is sufficient; rebuilding a
                # global/share ledger here would erase the inverse transition.
                continue
            group = (getattr(element, "group", "") or "").strip()
            if group and not is_peer_navigation_role(
                    getattr(element, "region", "") or ""):
                explored_groups.add((state_id, group))
            name = getattr(element, "name", "") or ""
            if name.strip():
                memory.mark_explored(
                    state_id,
                    name,
                    global_scope=(
                        is_chrome_name(name)
                        or _is_shared_button(name, region_registry)
                    ),
                )


_STATE_OBSERVATION_FIELDS = (
    "page_name",
    "page_id",
    "variant_id",
    "observed_facts",
    "visible_capabilities",
    "semantic_blocks",
    "region_observation",
    "perception_mode",
    "node_local_functions",
)


def _serialized_elements(elements) -> list[dict]:
    result = []
    for element in elements or []:
        payload = (
            dict(element) if isinstance(element, dict)
            else element.to_dict() if hasattr(element, "to_dict")
            else dataclasses.asdict(element)
            if dataclasses.is_dataclass(element)
            else None
        )
        if not isinstance(payload, dict):
            raise TypeError(
                f"runtime element is not serializable: {type(element).__name__}")
        result.append(payload)
    return result


def runtime_state_consistency_issues(
    graph: Any,
    state_data: Mapping[str, Mapping[str, Any]],
    registry: Any = None,
) -> list[str]:
    """Return contradictions between live, persisted, and identity ledgers."""
    issues: list[str] = []
    graph_nodes = {str(state_id) for state_id in graph.graph.nodes()}
    live_nodes = {str(state_id) for state_id in state_data}
    for state_id in sorted(graph_nodes - live_nodes):
        issues.append(f"graph node {state_id!r} is missing from live state_data")
    for state_id in sorted(live_nodes - graph_nodes):
        issues.append(f"live state {state_id!r} is missing from graph nodes")

    for state_id in sorted(graph_nodes & live_nodes):
        data = state_data[state_id]
        node = graph.graph.nodes[state_id]
        for field in _STATE_OBSERVATION_FIELDS:
            if field not in data:
                continue
            live_value = data.get(field)
            graph_value = node.get(field)
            if live_value != graph_value:
                issues.append(
                    f"state {state_id!r} field {field!r} differs between "
                    "live state_data and graph node")
        try:
            live_elements = _serialized_elements(data.get("elements") or [])
        except TypeError as exc:
            issues.append(f"state {state_id!r} {exc}")
            live_elements = []
        if live_elements != list(node.get("elements") or []):
            issues.append(
                f"state {state_id!r} elements differ between live state_data "
                "and graph node")

        observation = data.get("region_observation") or {}
        blocks = list(data.get("semantic_blocks") or [])
        if str(data.get("perception_mode") or "") == "region_lazy":
            for block in blocks:
                region_id = str(block.get("region_id") or "")
                if not region_id:
                    issues.append(
                        f"region-lazy state {state_id!r} has a Region without id")
                    continue
                status = observation.get(region_id)
                if not isinstance(status, dict):
                    issues.append(
                        f"region-lazy state {state_id!r} Region {region_id!r} "
                        "has no observation record")
                    continue
                block_status = str(
                    block.get("observation_status") or "pending")
                record_status = str(status.get("status") or "pending")
                if block_status != record_status:
                    issues.append(
                        f"region-lazy state {state_id!r} Region {region_id!r} "
                        "has different block and observation statuses")

        page_id = str(data.get("page_id") or state_id)
        variant_id = str(data.get("variant_id") or state_id)
        page = (getattr(graph, "pages", {}) or {}).get(page_id)
        variant = (
            (page.get("variants") or {}).get(variant_id)
            if isinstance(page, dict) else None)
        if not isinstance(variant, dict) or state_id not in {
                str(value) for value in variant.get("state_ids") or []}:
            issues.append(
                f"state {state_id!r} is absent from its Page/Variant catalog")
        if registry is not None:
            registered_page = str(registry.page_id_of(state_id) or "")
            registered_variant = str(registry.variant_id_of(state_id) or "")
            if registered_page != page_id:
                issues.append(
                    f"state {state_id!r} Page id differs between registry and "
                    "live state_data")
            if registered_variant != variant_id:
                issues.append(
                    f"state {state_id!r} Variant id differs between registry "
                    "and live state_data")

    for page_id, page in (getattr(graph, "pages", {}) or {}).items():
        for variant_id, variant in (page.get("variants") or {}).items():
            for state_id in variant.get("state_ids") or []:
                state_id = str(state_id)
                if state_id not in graph_nodes:
                    issues.append(
                        f"Page/Variant catalog references missing state "
                        f"{state_id!r}")
                    continue
                node = graph.graph.nodes[state_id]
                if str(node.get("page_id") or state_id) != str(page_id) \
                        or str(node.get("variant_id") or state_id) != \
                        str(variant_id):
                    issues.append(
                        f"Page/Variant catalog membership for state "
                        f"{state_id!r} contradicts its graph node")

    from gui_rewalk.src.core.graph.state_graph import (
        region_scroll_scope_id,
        scroll_evidence_complete,
    )
    for key, record in (getattr(graph, "scroll_ledger", {}) or {}).items():
        scope_id = str(record.get("scope_id") or key)
        region_id = str(record.get("region_id") or "")
        if scope_id != str(key):
            issues.append(
                f"scroll ledger key {key!r} differs from scope_id {scope_id!r}")
        if region_id and scope_id != region_scroll_scope_id(region_id):
            issues.append(
                f"Region {region_id!r} uses non-canonical scroll scope "
                f"{scope_id!r}")
        if not region_id and scope_id.startswith("region:"):
            issues.append(
                f"Region scroll scope {scope_id!r} has no region_id")
        expected_complete = scroll_evidence_complete(
            classification=record.get("classification"),
            termination=record.get("termination"),
            bottom_reached=record.get("bottom_reached"),
            top_restored=record.get("top_restored"),
        )
        if bool(record.get("complete")) != expected_complete:
            issues.append(
                f"scroll scope {scope_id!r} complete flag contradicts evidence")

    edge_ids: set[str] = set()
    action_edges = list(getattr(graph, "action_edges", {}) or [])
    for edge in action_edges:
        edge_id = str(edge.get("action_edge_id") or "")
        if not edge_id or edge_id in edge_ids:
            issues.append(f"action edge id {edge_id!r} is missing or duplicated")
        edge_ids.add(edge_id)
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in graph_nodes:
            issues.append(
                f"action edge {edge_id!r} references missing source {source!r}")
        if target and target not in graph_nodes:
            issues.append(
                f"action edge {edge_id!r} references missing target {target!r}")
        if source in graph_nodes:
            source_node = graph.graph.nodes[source]
            if str(edge.get("source_page_id") or "") != str(
                    source_node.get("page_id") or source):
                issues.append(
                    f"action edge {edge_id!r} has stale source Page id")
            if str(edge.get("source_variant_id") or "") != str(
                    source_node.get("variant_id") or source):
                issues.append(
                    f"action edge {edge_id!r} has stale source Variant id")
        if target in graph_nodes:
            target_node = graph.graph.nodes[target]
            if str(edge.get("target_page_id") or "") != str(
                    target_node.get("page_id") or target):
                issues.append(
                    f"action edge {edge_id!r} has stale target Page id")
            if str(edge.get("target_variant_id") or "") != str(
                    target_node.get("variant_id") or target):
                issues.append(
                    f"action edge {edge_id!r} has stale target Variant id")
        for attempt in edge.get("attempts") or []:
            if str(attempt.get("action_edge_id") or "") != edge_id:
                issues.append(
                    f"action edge {edge_id!r} has an attempt linked elsewhere")
            if str(attempt.get("source") or source) != source:
                issues.append(
                    f"action edge {edge_id!r} has an attempt from another source")

    for source, target, topology in graph.graph.edges(data=True):
        for edge_id in topology.get("action_edge_ids") or []:
            edge_id = str(edge_id)
            edge = next((
                item for item in action_edges
                if str(item.get("action_edge_id") or "") == edge_id), None)
            if edge is None:
                issues.append(
                    f"topology edge {source!r}->{target!r} references missing "
                    f"action edge {edge_id!r}")
            elif str(edge.get("source") or "") != str(source) \
                    or str(edge.get("target") or "") != str(target):
                issues.append(
                    f"topology edge {source!r}->{target!r} references action "
                    f"edge {edge_id!r} with different endpoints")
    return issues


def assert_runtime_state_consistent(
    graph: Any,
    state_data: Mapping[str, Mapping[str, Any]],
    registry: Any = None,
) -> None:
    issues = runtime_state_consistency_issues(
        graph, state_data, registry=registry)
    if issues:
        preview = "; ".join(issues[:8])
        if len(issues) > 8:
            preview += f"; ... ({len(issues)} total)"
        raise RuntimeError(f"runtime state consistency violation: {preview}")


def sync_live_to_graph(graph, state_data, visited_uids) -> None:
    """Project authoritative live State observations into persisted nodes."""
    # ``visited_uids`` is retained in the callback signature for compatibility
    # and diagnostics only.  Appearance UIDs can recur on unrelated hosts and
    # must never propagate action coverage across source states.
    for state_id, data in state_data.items():
        if state_id not in graph.graph:
            continue
        node = graph.graph.nodes[state_id]
        old_page_id = str(node.get("page_id") or state_id)
        old_variant_id = str(node.get("variant_id") or state_id)
        node["elements"] = copy.deepcopy(
            _serialized_elements(data.get("elements") or []))
        for field in _STATE_OBSERVATION_FIELDS:
            if field in data:
                node[field] = copy.deepcopy(data.get(field))
        new_page_id = str(node.get("page_id") or state_id)
        new_variant_id = str(node.get("variant_id") or state_id)
        if old_page_id != new_page_id or old_variant_id != new_variant_id:
            graph._cascade_state_identity_refinement(
                state_id=str(state_id),
                old_page_id=old_page_id,
                old_variant_id=old_variant_id,
                new_page_id=new_page_id,
                new_variant_id=new_variant_id,
            )
    graph._rebuild_page_catalog()


class VisualResumeRebuilder:
    """Build atomic resume snapshots from explicit, engine-owned dependencies."""

    def __init__(
        self,
        *,
        registry_factory: Callable[[], Any],
        region_registry_factory: Callable[[], Any],
        memory_factory: Callable[[], Any],
        element_type,
        identity_chrome_roles: FrozenSet[str],
        normalize_name: Callable[[str], str],
        is_chrome_name: Callable[[str], bool],
    ):
        self._registry_factory = registry_factory
        self._region_registry_factory = region_registry_factory
        self._memory_factory = memory_factory
        self._element_type = element_type
        self._identity_chrome_roles = identity_chrome_roles
        self._normalize_name = normalize_name
        self._is_chrome_name = is_chrome_name

    def build(self, graph: Any) -> ResumeSnapshot:
        """Build a complete snapshot without mutating ``graph`` or live engine state."""
        graph_data = graph.graph
        node_ids = tuple(graph_data.nodes())
        action_count = int(getattr(graph, "_action_counter", 0) or 0)
        persisted_state = {}
        for state_id in node_ids:
            node = graph_data.nodes[state_id]
            persisted_state[str(state_id)] = {
                field: copy.deepcopy(node.get(field))
                for field in _STATE_OBSERVATION_FIELDS
                if field in node
            }
            persisted_state[str(state_id)]["elements"] = copy.deepcopy(
                node.get("elements") or [])
        assert_runtime_state_consistent(graph, persisted_state)

        registry = self._registry_factory()
        region_registry = self._region_registry_factory()
        memory = self._memory_factory()
        state_data: Dict[str, Dict[str, Any]] = {}
        visited_uids: set[str] = set()
        explored_groups: set[tuple[str, str]] = set()
        abnormal_buttons: set[tuple[str, str, str]] = set()
        abnormal_records = list(
            getattr(graph, "abnormal_buttons", []) or [])
        valid_abnormal: Dict[tuple[str, str, str], Dict[str, Any]] = {}
        invalid_bounded_abnormal = set()
        for record in abnormal_records:
            key = abnormal_button_key(
                str(record.get("state_id", "") or ""),
                str(record.get("element_name", "") or ""),
                str(record.get("element_uid", "") or ""),
                str(record.get("region_id", "") or ""),
                self._normalize_name,
            )
            if _has_bounded_terminal_evidence(record):
                if str(record.get("reason", "") or "") != \
                        "terminal_observed_outcome":
                    valid_abnormal[key] = record
            else:
                invalid_bounded_abnormal.add(key)
        invalid_bounded_abnormal.difference_update(valid_abnormal)

        names_by_region: Dict[str, set] = {}
        member_tokens_by_region: Dict[str, set] = {}
        action_names_by_region: Dict[str, set] = {}
        role_by_region: Dict[str, str] = {}
        seen_by_region: Dict[str, set] = {}
        clicked_by_region: Dict[str, set] = {}
        verified_keys = _verified_source_action_keys(
            getattr(graph, "action_edges", []) or [], self._normalize_name)

        for state_id in node_ids:
            node_data = graph_data.nodes[state_id]
            element_dicts = node_data.get("elements", []) or []
            elements = [
                element_from_dict(element, self._element_type)
                for element in element_dicts
            ]
            for element in elements:
                key = abnormal_button_key(
                    str(state_id),
                    str(getattr(element, "name", "") or ""),
                    str(getattr(element, "uid", "") or ""),
                    str(getattr(element, "region_id", "") or ""),
                    self._normalize_name,
                )
                if key in invalid_bounded_abnormal:
                    element.abnormal_reason = ""
                    element.abnormal_detail = ""
                    if str(getattr(
                            element, "exploration_status", "") or "") \
                            == "terminal":
                        element.exploration_status = ""
                    element.visited = False
                valid_record = valid_abnormal.get(key)
                if valid_record is not None:
                    element.abnormal_reason = str(
                        valid_record.get("reason", "") or "")
                    element.abnormal_detail = str(
                        valid_record.get("detail", "") or "")
                    element.exploration_status = "terminal"
                    element.visited = True
                _reopen_unverified_persisted_control(
                    state_id, element, verified_keys, self._normalize_name)
            state_data[state_id] = {
                "elements": elements,
                "path": list(node_data.get("action_path_from_root", []) or []),
                "replay_hints": [],
                "page_name": str(node_data.get("page_name", "") or ""),
                "surface_kind": semantic_surface_kind(
                    node_data.get("semantic_blocks") or [],
                    node_data.get("surface_kind") or ""),
                "page_id": str(node_data.get("page_id", "") or ""),
                "variant_id": str(node_data.get("variant_id", "") or state_id),
                "observed_facts": dict(node_data.get("observed_facts") or {}),
                "visible_capabilities": list(
                    node_data.get("visible_capabilities") or []),
                "semantic_blocks": copy.deepcopy(
                    node_data.get("semantic_blocks") or []),
                "region_observation": copy.deepcopy(
                    node_data.get("region_observation") or {}),
                "perception_mode": str(
                    node_data.get("perception_mode") or ""),
                "node_local_functions": copy.deepcopy(
                    node_data.get("node_local_functions") or []),
                "is_system_dialog": False,
            }
            page_id, variant_id = _rebuild_registry_node(
                registry,
                state_id,
                node_data,
                elements,
                self._identity_chrome_roles,
                self._normalize_name,
            )
            state_data[state_id]["page_id"] = page_id
            state_data[state_id]["variant_id"] = variant_id
            _accumulate_region_facts(
                state_id,
                elements,
                names_by_region,
                member_tokens_by_region,
                action_names_by_region,
                role_by_region,
                seen_by_region,
                clicked_by_region,
            )

        _install_regions(
            region_registry,
            names_by_region,
            member_tokens_by_region,
            action_names_by_region,
            role_by_region,
            seen_by_region,
            clicked_by_region,
        )
        _rebuild_cross_node_ledgers(
            state_data,
            node_ids,
            region_registry,
            memory,
            visited_uids,
            explored_groups,
            self._is_chrome_name,
        )
        for record in abnormal_records:
            if not _has_bounded_terminal_evidence(record):
                continue
            key = abnormal_button_key(
                str(record.get("state_id", "") or ""),
                str(record.get("element_name", "") or ""),
                str(record.get("element_uid", "") or ""),
                str(record.get("region_id", "") or ""),
                self._normalize_name,
            )
            if key in valid_abnormal:
                abnormal_buttons.add(key)

        return ResumeSnapshot(
            graph=graph,
            state_data=state_data,
            registry=registry,
            region_registry=region_registry,
            memory=memory,
            visited_uids=visited_uids,
            explored_groups=explored_groups,
            abnormal_buttons=abnormal_buttons,
            frontier=deque(node_ids),
            action_count=action_count,
        )
