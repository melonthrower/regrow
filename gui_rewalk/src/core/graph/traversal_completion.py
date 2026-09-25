"""Fail-closed traversal completion certificate for visual capability graphs.

The evaluator is deliberately independent from ``VisualTraversalEngine`` and
``StateGraph``.  It accepts either an in-memory graph-like object or the raw
schema-v3 ``graph.json`` mapping and derives every conclusion from persisted
evidence.  In particular, ``action_edges[].attempts`` is the only action truth;
``visited`` flags and the cached ``routing_verified`` bit are never sufficient
proof by themselves.

The function is pure: it performs no file I/O and never mutates its input.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .state_graph import scroll_evidence_complete


CERTIFICATE_SCHEMA = "gui_rewalk.traversal_completion.v1"
REQUIRED_GRAPH_SCHEMA = 3

_SUCCESS_OUTCOMES = frozenset({
    "success",
    "succeeded",
    "verified",
    "committed",
    "transitioned",
    "transitioned_consistent",
    "observable_change",
    "state_changed",
})
_NON_EFFECT_OUTCOMES = frozenset({
    "",
    "attempted",
    "executed",
    "no_effect",
    "stateful_no_effect",
    "transitioned_inconsistent",
    "uncertain",
    "permission_blocked",
    "disabled",
    "blocked",
    "external_app",
    "app_crash",
    "perception_failed",
    "quarantined",
    "quarantined_source_mismatch",
    "failed",
    "failure",
    "error",
    "cancelled",
    "canceled",
    "prerequisite_setup_step",
    "prerequisite_cleanup",
})
_TERMINAL_FAILURES = frozenset({
    "no_effect",
    "stateful_no_effect",
    "stateful_verification_failed",
    "transitioned_inconsistent",
    "permission_blocked",
    "disabled",
    "blocked",
    "external_app",
    "app_crash",
    "perception_failed",
    "quarantined",
    "quarantined_source_mismatch",
    "failed",
    "failure",
    "error",
    "cancelled",
    "canceled",
})
_CERTIFIABLE_ABNORMAL_REASONS = frozenset({
    "disabled",
    "permission_blocked",
    "blocked",
    "no_effect",
    "stateful_no_effect",
    "stateful_risk_blocked",
    "external_app",
    "app_crash",
})
_BOUNDED_LOCAL_ABNORMAL_REASONS = frozenset({
    "target_rebind_failed",
    "action_execution_failed",
    "action_verification_failed",
})

_PEER_NAVIGATION_ROLES = frozenset({
    "tabbar", "tabs", "primarynavigation", "navigationsidebar",
    "navsidebar", "sidebar", "bottomnavigation", "bottomnav",
    "navigationbar", "navbar", "navigationrail",
})


def _is_peer_navigation_record(record: Mapping[str, Any]) -> bool:
    role = _normalise(record.get("region"))
    return role in _PEER_NAVIGATION_ROLES
_STATIC_CATEGORIES = frozenset({"display", "static", "chrome"})
_CONTROL_CATEGORIES = frozenset({
    "navigation", "nav", "shallow", "dangerous", "control", "input",
})
_CONTROL_TYPES = frozenset({
    "button", "push button", "push-button", "link", "tab", "menu item",
    "menuitem", "input", "entry", "textbox", "text box", "text field",
    "textarea", "searchbox", "checkbox", "radio", "radio button", "switch",
    "toggle", "slider", "combobox", "combo box", "select", "dropdown",
    "listbox", "list item", "row", "spin button", "spinner",
})
_DRAG_CONTROL_TYPES = frozenset({
    "slider", "range", "range slider", "drag", "draggable",
    "drag handle", "drag_handle",
})
_SCROLL_FAILURE_MARKERS = (
    "hard_cap", "cap", "error", "failed", "failure", "off_app", "unknown",
    "budget", "timeout",
)


def _normalise(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def _text(value: Any) -> str:
    return str(value or "").strip()


def _as_index(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_json_safe(item) for item in value]
        if isinstance(value, (set, frozenset)):
            items.sort(key=lambda item: json.dumps(item, sort_keys=True))
        return items
    return str(value)


def _issue(code: str, message: str, **evidence: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {"code": code, "message": message}
    if evidence:
        result["evidence"] = _json_safe(evidence)
    return result


def _check(
    issues: Iterable[Dict[str, Any]],
    *,
    passed_summary: str,
    failed_summary: str,
    evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    failures = list(issues)
    passed = not failures
    return {
        "passed": passed,
        "status": "passed" if passed else "failed",
        "summary": passed_summary if passed else failed_summary,
        "issues": failures,
        "evidence": _json_safe(dict(evidence or {})),
    }


def _coerce_graph_data(graph_or_data: Any) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Return an isolated mapping without importing graph or engine classes."""
    if isinstance(graph_or_data, Mapping):
        try:
            return copy.deepcopy(dict(graph_or_data)), []
        except Exception as exc:  # pragma: no cover - defensive custom Mapping
            return {}, [_issue(
                "input_copy_failed",
                "graph mapping could not be copied safely",
                error=str(exc),
            )]

    topology = getattr(graph_or_data, "graph", None)
    action_edges = getattr(graph_or_data, "action_edges", None)
    if topology is None or action_edges is None:
        return {}, [_issue(
            "unsupported_input",
            "expected a raw graph mapping or an in-memory graph-like object",
            input_type=type(graph_or_data).__name__,
        )]
    try:
        nodes: List[Dict[str, Any]] = []
        for state_id, attrs in topology.nodes(data=True):
            item = copy.deepcopy(dict(attrs or {}))
            item.setdefault("state_id", str(state_id))
            nodes.append(item)
        edges: List[Dict[str, Any]] = []
        for source, target, attrs in topology.edges(data=True):
            item = copy.deepcopy(dict(attrs or {}))
            item["source"] = str(source)
            item["target"] = str(target)
            edges.append(item)
        data = {
            "graph_schema_version": REQUIRED_GRAPH_SCHEMA,
            "app_name": _text(getattr(graph_or_data, "app_name", "")),
            "stop_reason": _text(getattr(graph_or_data, "stop_reason", "")),
            "nodes": nodes,
            "edges": edges,
            "pages": copy.deepcopy(getattr(graph_or_data, "pages", {})),
            "capabilities": copy.deepcopy(
                getattr(graph_or_data, "capabilities", {})),
            "action_edges": copy.deepcopy(action_edges),
            "scroll_ledger": copy.deepcopy(
                getattr(graph_or_data, "scroll_ledger", {})),
            "abnormal_buttons": copy.deepcopy(
                getattr(graph_or_data, "abnormal_buttons", [])),
        }
        return data, []
    except Exception as exc:
        return {}, [_issue(
            "graph_object_unreadable",
            "in-memory graph-like object could not be inspected",
            error=str(exc),
        )]


def _container_items(
    raw: Any, id_key: str
) -> Tuple[List[Tuple[str, Dict[str, Any]]], bool]:
    if isinstance(raw, Mapping):
        result: List[Tuple[str, Dict[str, Any]]] = []
        for key, value in raw.items():
            if isinstance(value, Mapping):
                result.append((str(key), dict(value)))
        return result, len(result) == len(raw)
    if isinstance(raw, list):
        result = []
        valid = True
        for ordinal, value in enumerate(raw):
            if not isinstance(value, Mapping):
                valid = False
                continue
            identifier = _text(value.get(id_key)) or str(ordinal)
            result.append((identifier, dict(value)))
        return result, valid
    return [], False


def _string_refs(raw: Any, id_key: str = "capability_id") -> List[str]:
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return []
    result: List[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            value = _text(item.get(id_key))
        else:
            value = _text(item)
        if value and value not in result:
            result.append(value)
    return result


def _attempt_is_verified(edge: Mapping[str, Any], attempt: Mapping[str, Any]) -> bool:
    target = _text(edge.get("target"))
    outcome = _text(attempt.get("outcome")).casefold()
    return bool(
        target
        and attempt.get("committed") is True
        and attempt.get("landing_verified") is True
        and _text(attempt.get("source") or edge.get("source"))
        == _text(edge.get("source"))
        and _text(attempt.get("target")) == target
        and outcome in _SUCCESS_OUTCOMES
        and outcome not in _NON_EFFECT_OUTCOMES
    )


def _attempt_is_same_page_terminal_landing(
    edge: Mapping[str, Any], attempt: Mapping[str, Any]
) -> bool:
    """A real target-app variant reached by an explicit environment block.

    This is *not* a successful route and can never verify a capability.  It only
    prevents a truthfully observed same-page blocked variant from becoming an
    artificial orphan in the completion audit.  The explicit evidence marker,
    exact ``blocked`` outcome, positive landing check, and stable same-page ids
    make the exception deliberately narrow; inconsistent/wrong-page landings do
    not qualify.
    """
    evidence = attempt.get("evidence") or {}
    source_page = _text(edge.get("source_page_id"))
    target_page = _text(edge.get("target_page_id"))
    return bool(
        isinstance(evidence, Mapping)
        and evidence.get("terminal_landing") is True
        and _text(attempt.get("outcome")).casefold() == "blocked"
        and attempt.get("committed") is not True
        and attempt.get("landing_verified") is True
        and _text(attempt.get("source") or edge.get("source"))
        == _text(edge.get("source"))
        and _text(attempt.get("target")) == _text(edge.get("target"))
        and _text(edge.get("target"))
        and source_page
        and source_page == target_page
    )


def _element_id(element: Mapping[str, Any]) -> str:
    value = element.get("id")
    if value is None:
        value = element.get("element_id")
    # Numeric zero is the first valid element id, not a missing value.
    return "" if value is None else str(value).strip()


def _element_uid(element: Mapping[str, Any]) -> str:
    return _text(element.get("uid") or element.get("element_uid"))


def _element_label(element: Mapping[str, Any]) -> str:
    return _text(element.get("name") or element.get("element_label"))




def _semantic_element_match(
    record: Mapping[str, Any], element: Mapping[str, Any]
) -> bool:
    record_id = _element_id(record)
    element_id = _element_id(element)
    record_label = _normalise(
        record.get("element_label") or record.get("element_name")
        or record.get("name")
    )
    element_label = _normalise(_element_label(element))
    if record_id and element_id:
        return record_id == element_id and (
            not record_label or not element_label or record_label == element_label)
    record_uid = _text(record.get("element_uid") or record.get("uid"))
    element_uid = _element_uid(element)
    if record_uid and element_uid:
        return record_uid == element_uid and (
            not record_label or not element_label or record_label == element_label)
    if not record_label or record_label != element_label:
        return False
    record_region = _normalise(record.get("region_id") or record.get("region"))
    element_regions = {
        _normalise(element.get("region_id")),
        _normalise(element.get("region")),
    } - {""}
    return not record_region or not element_regions or record_region in element_regions


def _is_control(element: Mapping[str, Any]) -> bool:
    if element.get("back") or element.get("stateful") or element.get("selected"):
        return True
    if element.get("interactive") is False:
        return False
    category = " ".join(_text(element.get("category")).casefold().split())
    element_type = " ".join(
        _text(element.get("el_type") or element.get("type")).casefold().split())
    if category in _STATIC_CATEGORIES:
        return False
    if category in _CONTROL_CATEGORIES or element_type in _CONTROL_TYPES:
        return bool(_element_label(element) or _element_id(element))
    return element.get("interactive") is True and bool(
        _element_label(element) or _element_id(element))


def _is_navigation(element: Mapping[str, Any]) -> bool:
    return _text(element.get("category")).casefold() in {"navigation", "nav"}


def _capability_matches_control(
    capability: Mapping[str, Any],
    *,
    capability_id: str,
    node: Mapping[str, Any],
    element: Mapping[str, Any],
) -> bool:
    node_visible = set(_string_refs(node.get("visible_capabilities")))
    state_id = _text(node.get("state_id"))
    variant_id = _text(node.get("variant_id"))
    page_id = _text(node.get("page_id"))
    for source in capability.get("source_elements") or []:
        if not isinstance(source, Mapping):
            continue
        if _text(source.get("state_id")) not in {"", state_id}:
            continue
        if _text(source.get("variant_id")) not in {"", variant_id}:
            continue
        if _semantic_element_match(source, element):
            return True
    if capability_id not in node_visible:
        return False
    if _text(capability.get("page_id")) not in {"", page_id}:
        return False
    element_id = _element_id(element)
    if element_id and element_id in _string_refs(
            capability.get("elements"), id_key="element_id"):
        return True
    label = _normalise(_element_label(element))
    for recipe in capability.get("execution_recipe") or []:
        if not isinstance(recipe, Mapping):
            continue
        selector = recipe.get("selector") or {}
        if isinstance(selector, Mapping) and label \
                and _normalise(selector.get("element_label")) == label:
            return True
    return False


def _nonempty_predicate(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, (list, tuple)):
        return bool(value)
    return False


def _certifiable_abnormal_reason(
    value: Any,
    *,
    record: Optional[Mapping[str, Any]] = None,
    state_id: str = "",
    node_by_id: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> bool:
    reason = _text(value).casefold()
    if (
        reason in _CERTIFIABLE_ABNORMAL_REASONS
        or reason.startswith("external_app_")
        or reason.startswith("app_crash_")
    ):
        return True
    evidence = (
        record.get("evidence")
        if isinstance(record, Mapping)
        and isinstance(record.get("evidence"), Mapping)
        else {}
    )
    attempts = _as_index(evidence.get("attempts_used"))
    if reason in _BOUNDED_LOCAL_ABNORMAL_REASONS:
        return (
            evidence.get("kind") == "bounded_local_failure"
            and attempts is not None
            and attempts >= 2
            and bool(_text(evidence.get("failure_kind")))
        )
    if reason == "route_unavailable":
        landed = _text(evidence.get("landed_state_id"))
        return (
            evidence.get("kind") == "route_unavailable"
            and attempts is not None
            and attempts >= 2
            and landed
            and landed != _text(state_id)
            and isinstance(node_by_id, Mapping)
            and landed in node_by_id
        )
    return False


def _state_restoration_check(
    data: Mapping[str, Any],
    action_edges: Iterable[Mapping[str, Any]],
    raw_action_edges: Any,
) -> Dict[str, Any]:
    """Audit chronological stateful probe/restore evidence."""
    mutation_issues: List[Dict[str, Any]] = []
    stateful_records: List[
        Tuple[int, Mapping[str, Any], Dict[str, Any]]
    ] = []
    for edge in action_edges:
        for attempt in edge.get("attempts") or []:
            if not isinstance(attempt, Mapping):
                continue
            evidence = attempt.get("evidence") or {}
            if isinstance(evidence, Mapping) and evidence.get("stateful"):
                stateful_records.append((
                    _as_index(attempt.get("action_index")) or 10**18,
                    edge,
                    dict(attempt),
                ))
    stateful_records.sort(key=lambda item: item[0])
    open_mutations: Dict[str, Dict[str, Any]] = {}
    for action_index, edge, attempt in stateful_records:
        evidence = dict(attempt.get("evidence") or {})
        mutation_id = _text(evidence.get("mutation_id"))
        purpose = _text(evidence.get("purpose")).casefold()
        if _text(evidence.get("mutation_status")).casefold() == "unknown":
            mutation_issues.append(_issue(
                "stateful_mutation_outcome_unknown",
                "a stateful action ended without a known post-recovery value",
                mutation_id=mutation_id,
                action_index=action_index,
                state_key=evidence.get("state_key")))
        if not mutation_id:
            mutation_issues.append(_issue(
                "stateful_mutation_missing_id",
                "stateful attempt lacks mutation_id",
                action_index=action_index))
            continue
        if purpose not in {"probe", "restore"}:
            mutation_issues.append(_issue(
                "stateful_mutation_missing_purpose",
                "stateful attempt must declare probe or restore",
                mutation_id=mutation_id, action_index=action_index,
                purpose=purpose or "<missing>"))
            continue
        outcome = _text(attempt.get("outcome")).casefold()
        committed = attempt.get("committed") is True
        before_value = _text(evidence.get("before_value")).casefold()
        after_value = _text(evidence.get("after_value")).casefold()
        observed_change = bool(
            before_value and after_value
            and before_value not in {"unknown", "none"}
            and after_value not in {"unknown", "none"}
            and before_value != after_value
        )
        could_have_mutated = committed or observed_change \
            or outcome in _SUCCESS_OUTCOMES or outcome == "executed"
        if purpose == "probe" and could_have_mutated:
            if mutation_id in open_mutations:
                mutation_issues.append(_issue(
                    "stateful_mutation_reopened",
                    "a mutation id was probed again before restoration",
                    mutation_id=mutation_id, action_index=action_index))
            open_mutations[mutation_id] = {
                "action_index": action_index,
                "source": _text(attempt.get("source") or edge.get("source")),
                "target": _text(attempt.get("target") or edge.get("target")),
                "state_key": _text(evidence.get("state_key")),
                "before_value": before_value,
                "restore_before_value": _text(
                    evidence.get("restore_before_value")).casefold(),
                "after_value": after_value,
                "committed": committed,
            }
            if not committed:
                mutation_issues.append(_issue(
                    "stateful_probe_commit_unknown",
                    "a physically executed stateful probe lacks committed restoration evidence",
                    mutation_id=mutation_id, action_index=action_index,
                    outcome=outcome))
        elif purpose == "restore" and could_have_mutated:
            opened = open_mutations.get(mutation_id)
            if opened is None:
                mutation_issues.append(_issue(
                    "stateful_restore_without_probe",
                    "restore attempt has no preceding open probe",
                    mutation_id=mutation_id, action_index=action_index))
                continue
            if not committed or attempt.get("landing_verified") is not True \
                    or outcome not in _SUCCESS_OUTCOMES:
                mutation_issues.append(_issue(
                    "stateful_restore_unverified",
                    "inverse action was not committed and semantically verified",
                    mutation_id=mutation_id, action_index=action_index,
                    outcome=outcome,
                    landing_verified=attempt.get("landing_verified")))
                continue
            expected = _text(
                opened.get("restore_before_value")
                or opened.get("before_value")).casefold()
            if expected and expected not in {"unknown", "none"} \
                    and after_value and after_value not in {"unknown", "none"} \
                    and expected != after_value:
                mutation_issues.append(_issue(
                    "stateful_restore_value_mismatch",
                    "restore did not return to the probe's before value",
                    mutation_id=mutation_id, expected=expected,
                    observed=after_value, action_index=action_index))
                continue
            open_mutations.pop(mutation_id, None)
    for mutation_id, record in sorted(open_mutations.items()):
        mutation_issues.append(_issue(
            "stateful_mutation_open",
            "stateful probe has no verified inverse restoration",
            mutation_id=mutation_id, **record))
    if "action_edges" not in data or not isinstance(raw_action_edges, list):
        mutation_issues.append(_issue(
            "mutation_ledger_unavailable",
            "open mutations cannot be audited without raw action edge attempts"))
    return _check(
        mutation_issues,
        passed_summary="no stateful mutation remains open",
        failed_summary="stateful mutation evidence is missing, inconsistent, or unrestored",
        evidence={
            "stateful_attempts": len(stateful_records),
            "open_mutation_ids": sorted(open_mutations),
        },
    )

def evaluate_traversal_completion(graph_or_data: Any) -> Dict[str, Any]:
    """Evaluate and return a deterministic traversal completion certificate.

    Certification is conjunctive: every fixed check must pass.  Unsupported
    schemas, absent ledgers, malformed containers, ambiguous roots, or any other
    missing proof yield ``status="incomplete"`` rather than an exception or an
    optimistic inference.
    """
    data, input_issues = _coerce_graph_data(graph_or_data)

    raw_nodes = data.get("nodes")
    nodes = [dict(item) for item in raw_nodes or [] if isinstance(item, Mapping)] \
        if isinstance(raw_nodes, list) else []
    node_by_id: Dict[str, Dict[str, Any]] = {}
    duplicate_node_ids: set[str] = set()
    for node in nodes:
        state_id = _text(node.get("state_id"))
        if not state_id:
            continue
        if state_id in node_by_id:
            duplicate_node_ids.add(state_id)
        node_by_id[state_id] = node

    page_items, pages_container_valid = _container_items(data.get("pages"), "page_id")
    capability_items, capabilities_container_valid = _container_items(
        data.get("capabilities"), "capability_id")
    scroll_items, scroll_container_valid = _container_items(
        data.get("scroll_ledger"), "scope_id")
    raw_action_edges = data.get("action_edges")
    action_edges = [dict(item) for item in raw_action_edges or []
                    if isinstance(item, Mapping)] \
        if isinstance(raw_action_edges, list) else []
    raw_topology = data.get("edges") if "edges" in data else data.get("links")
    topology_edges = [dict(item) for item in raw_topology or []
                      if isinstance(item, Mapping)] \
        if isinstance(raw_topology, list) else []
    raw_abnormal = data.get("abnormal_buttons")
    abnormal_records = [dict(item) for item in raw_abnormal or []
                        if isinstance(item, Mapping)] \
        if isinstance(raw_abnormal, list) else []

    schema_issues = list(input_issues)
    schema_version = data.get("graph_schema_version")
    if schema_version != REQUIRED_GRAPH_SCHEMA:
        schema_issues.append(_issue(
            "unsupported_graph_schema",
            "only native graph schema v3 can be certified",
            observed=schema_version,
            required=REQUIRED_GRAPH_SCHEMA,
        ))
    required_types = {
        "nodes": list,
        "action_edges": list,
        "abnormal_buttons": list,
    }
    for field, expected in required_types.items():
        if field not in data:
            schema_issues.append(_issue(
                "missing_material", f"required {field} material is absent", field=field))
        elif not isinstance(data.get(field), expected):
            schema_issues.append(_issue(
                "invalid_material_type",
                f"{field} must be a {expected.__name__}",
                field=field,
                observed_type=type(data.get(field)).__name__,
            ))
    if "edges" not in data and "links" not in data:
        schema_issues.append(_issue(
            "missing_material", "compact topology edge material is absent", field="edges"))
    elif not isinstance(raw_topology, list):
        schema_issues.append(_issue(
            "invalid_material_type", "compact topology edges must be a list",
            field="edges", observed_type=type(raw_topology).__name__))
    for field, valid, present in (
        ("pages", pages_container_valid, "pages" in data),
        ("capabilities", capabilities_container_valid, "capabilities" in data),
        ("scroll_ledger", scroll_container_valid, "scroll_ledger" in data),
    ):
        if not present:
            schema_issues.append(_issue(
                "missing_material", f"required {field} material is absent", field=field))
        elif not valid:
            schema_issues.append(_issue(
                "invalid_material_type",
                f"{field} must be a mapping or a list of records",
                field=field,
                observed_type=type(data.get(field)).__name__,
            ))
    if "stop_reason" not in data or not isinstance(data.get("stop_reason"), str):
        schema_issues.append(_issue(
            "missing_stop_reason", "a persisted string stop_reason is required"))
    if "transition_events" in data:
        schema_issues.append(_issue(
            "legacy_transition_events_present",
            "schema v3 must use only action_edges[].attempts, not a parallel event ledger"))
    if not nodes:
        schema_issues.append(_issue(
            "missing_nodes", "a traversal certificate requires at least one node"))
    if len(nodes) != len(raw_nodes or []) if isinstance(raw_nodes, list) else False:
        schema_issues.append(_issue(
            "malformed_node_record", "nodes contains a non-object record"))
    if duplicate_node_ids:
        schema_issues.append(_issue(
            "duplicate_state_id", "state ids must be unique",
            state_ids=sorted(duplicate_node_ids)))
    for ordinal, node in enumerate(nodes):
        missing = [field for field in (
            "state_id", "page_id", "variant_id", "page_identity_version",
            "variant_signature", "observed_facts", "elements",
            "visible_capabilities", "action_path_from_root",
        ) if field not in node]
        if missing:
            schema_issues.append(_issue(
                "node_missing_v3_material",
                "node lacks native page/variant or coverage material",
                node=_text(node.get("state_id")) or ordinal,
                fields=missing,
            ))
        if "elements" in node and not isinstance(node.get("elements"), list):
            schema_issues.append(_issue(
                "invalid_node_elements", "node elements must be a list",
                node=_text(node.get("state_id")) or ordinal))
        if "visible_capabilities" in node \
                and not isinstance(node.get("visible_capabilities"), list):
            schema_issues.append(_issue(
                "invalid_node_capability_refs",
                "node visible_capabilities must be a list",
                node=_text(node.get("state_id")) or ordinal))
        if "action_path_from_root" in node \
                and not isinstance(node.get("action_path_from_root"), list):
            schema_issues.append(_issue(
                "invalid_root_path_material", "node action_path_from_root must be a list",
                node=_text(node.get("state_id")) or ordinal))

    edge_by_id: Dict[str, Dict[str, Any]] = {}
    duplicate_edge_ids: set[str] = set()
    verified_attempt_records: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    terminal_landing_records: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    attempt_indexes: Dict[int, str] = {}
    attempt_count = 0
    for ordinal, edge in enumerate(action_edges):
        edge_id = _text(edge.get("action_edge_id"))
        if not edge_id:
            schema_issues.append(_issue(
                "action_edge_missing_id", "action edge has no stable id", edge_index=ordinal))
            edge_id = f"<missing:{ordinal}>"
        elif edge_id in edge_by_id:
            duplicate_edge_ids.add(edge_id)
        edge_by_id[edge_id] = edge
        source = _text(edge.get("source"))
        target = _text(edge.get("target"))
        if not source or source not in node_by_id:
            schema_issues.append(_issue(
                "action_edge_source_missing",
                "action edge source is absent from the node catalog",
                action_edge_id=edge_id, source=source))
        if target and target not in node_by_id:
            schema_issues.append(_issue(
                "action_edge_target_missing",
                "action edge target is absent from the node catalog",
                action_edge_id=edge_id, target=target))
        attempts = edge.get("attempts")
        if not isinstance(attempts, list):
            schema_issues.append(_issue(
                "action_edge_attempts_missing",
                "action edge must own its raw attempts list",
                action_edge_id=edge_id))
            attempts = []
        elif not attempts:
            schema_issues.append(_issue(
                "action_edge_without_attempt",
                "an action edge without a raw attempt cannot prove coverage",
                action_edge_id=edge_id))
        derived_verified = False
        for attempt_ordinal, attempt in enumerate(attempts):
            if not isinstance(attempt, Mapping):
                schema_issues.append(_issue(
                    "malformed_attempt", "attempt must be an object",
                    action_edge_id=edge_id, attempt_index=attempt_ordinal))
                continue
            attempt = dict(attempt)
            attempt_count += 1
            index = _as_index(attempt.get("action_index"))
            if index is None:
                schema_issues.append(_issue(
                    "attempt_missing_action_index",
                    "attempt requires a positive action_index",
                    action_edge_id=edge_id, attempt_index=attempt_ordinal))
            elif index in attempt_indexes:
                schema_issues.append(_issue(
                    "duplicate_action_index",
                    "action_index must be globally unique across raw attempts",
                    action_index=index,
                    action_edge_ids=[attempt_indexes[index], edge_id]))
            else:
                attempt_indexes[index] = edge_id
            if _text(attempt.get("source") or source) != source:
                schema_issues.append(_issue(
                    "attempt_source_mismatch",
                    "attempt source conflicts with its action edge",
                    action_edge_id=edge_id, action_index=index))
            if _attempt_is_verified(edge, attempt):
                verified_attempt_records.append((edge, attempt))
                derived_verified = True
            elif _attempt_is_same_page_terminal_landing(edge, attempt):
                terminal_landing_records.append((edge, attempt))
        # ``routing_verified`` is only a cache.  Its absence cannot erase raw
        # attempt evidence; when present, however, disagreement is corruption.
        if isinstance(edge.get("routing_verified"), bool) \
                and bool(edge.get("routing_verified")) != derived_verified:
            schema_issues.append(_issue(
                "routing_flag_disagrees_with_attempts",
                "cached routing_verified disagrees with raw attempt evidence",
                action_edge_id=edge_id,
                cached=bool(edge.get("routing_verified")),
                derived=derived_verified))
    if duplicate_edge_ids:
        schema_issues.append(_issue(
            "duplicate_action_edge_id", "action edge ids must be unique",
            action_edge_ids=sorted(duplicate_edge_ids)))

    checks: Dict[str, Dict[str, Any]] = {}
    checks["schema_materials"] = _check(
        schema_issues,
        passed_summary="native schema-v3 audit materials are present and coherent",
        failed_summary="native schema-v3 audit materials are missing or malformed",
        evidence={
            "graph_schema_version": schema_version,
            "nodes": len(nodes),
            "action_edges": len(action_edges),
            "attempts": attempt_count,
        },
    )

    stop_reason = _text(data.get("stop_reason"))
    frontier_issues: List[Dict[str, Any]] = []
    if stop_reason != "frontier_empty":
        frontier_issues.append(_issue(
            "frontier_not_exhausted",
            "only stop_reason=frontier_empty proves deterministic frontier exhaustion",
            stop_reason=stop_reason or "<missing>"))
    checks["frontier_exhaustion"] = _check(
        frontier_issues,
        passed_summary="the persisted frontier ended because it was empty",
        failed_summary="the traversal stopped before proven frontier exhaustion",
        evidence={"stop_reason": stop_reason},
    )

    scroll_issues: List[Dict[str, Any]] = []
    scroll_scope_ids: set[str] = set()
    scroll_covered_states: set[str] = set()
    scroll_covered_regions: set[str] = set()
    completed_scroll_scopes = 0
    if not scroll_container_valid or "scroll_ledger" not in data:
        scroll_issues.append(_issue(
            "scroll_ledger_unavailable",
            "scroll completion cannot be inferred without the native ledger"))
    for container_key, scope in scroll_items:
        scope_id = _text(scope.get("scope_id")) or container_key
        if not _text(scope.get("scope_id")):
            scroll_issues.append(_issue(
                "scroll_scope_missing_id", "scroll scope has no stable scope_id",
                container_key=container_key))
        if scope_id in scroll_scope_ids:
            scroll_issues.append(_issue(
                "duplicate_scroll_scope", "scroll scope ids must be unique",
                scope_id=scope_id))
        scroll_scope_ids.add(scope_id)
        state_ids = _string_refs(scope.get("state_ids"), id_key="state_id")
        if _text(scope.get("state_id")):
            state_ids.append(_text(scope.get("state_id")))
        scroll_covered_states.update(state_ids)
        region_id = _text(scope.get("region_id"))
        classification = _text(scope.get("classification")).casefold()
        termination = _text(scope.get("termination")).casefold()
        detail = _text(scope.get("detail")).casefold()
        top_restored = scope.get("top_restored") is True
        bottom_reached = scope.get("bottom_reached") is True
        explicit_complete = scope.get("complete") is True
        failure_marker = next((
            marker for marker in _SCROLL_FAILURE_MARKERS
            if marker in termination or marker in detail
        ), "")
        if failure_marker:
            scroll_issues.append(_issue(
                "scroll_scope_aborted",
                "scroll scope ended at a cap/error rather than an absorbing boundary",
                scope_id=scope_id, termination=termination,
                detail=detail, marker=failure_marker))
        if not top_restored:
            scroll_issues.append(_issue(
                "scroll_top_not_restored",
                "scope was not returned to its canonical top viewport",
                scope_id=scope_id))
        complete_by_evidence = scroll_evidence_complete(
            classification=classification,
            termination=termination,
            bottom_reached=bottom_reached,
            top_restored=top_restored,
        ) and not failure_marker
        if classification == "scrollable":
            if not bottom_reached:
                scroll_issues.append(_issue(
                    "scroll_bottom_not_reached",
                    "scrollable scope lacks a real bottom boundary",
                    scope_id=scope_id, termination=termination))
        elif classification != "static":
            scroll_issues.append(_issue(
                "scroll_classification_unknown",
                "scope must be classified static or scrollable",
                scope_id=scope_id, classification=classification or "<missing>"))
        # ``complete`` is a convenient StateGraph cache, not the primary proof.
        # Older native-v3 producers may omit it; an explicit false value must not
        # contradict otherwise-looking boundary fields.
        if "complete" in scope and not explicit_complete:
            scroll_issues.append(_issue(
                "scroll_scope_not_complete",
                "scope lacks the persisted complete=true conclusion",
                scope_id=scope_id))
        if complete_by_evidence and ("complete" not in scope or explicit_complete):
            completed_scroll_scopes += 1
            if region_id:
                scroll_covered_regions.add(region_id)
    required_scroll_regions: set[str] = set()
    state_scoped_nodes: set[str] = set()
    for state_id, node in node_by_id.items():
        region_ids = {
            _text(block.get("region_id"))
            for block in node.get("semantic_blocks") or []
            if (
                isinstance(block, Mapping)
                and _text(block.get("region_id"))
                and block.get("scrollable") is True
            )
        }
        if region_ids:
            required_scroll_regions.update(region_ids)
        elif node.get("surface_scrollable") is True:
            state_scoped_nodes.add(state_id)
    uncovered_scroll_regions = sorted(
        required_scroll_regions - scroll_covered_regions)
    if uncovered_scroll_regions:
        scroll_issues.append(_issue(
            "region_without_scroll_evidence",
            "every stable Region requires one static/scroll boundary observation",
            region_ids=uncovered_scroll_regions))
    uncovered_scroll_states = sorted(
        state_scoped_nodes - scroll_covered_states)
    if node_by_id and uncovered_scroll_states:
        scroll_issues.append(_issue(
            "node_without_scroll_evidence",
            "nodes without stable Regions require page-scoped scroll evidence",
            state_ids=uncovered_scroll_states))
    checks["scroll_exhaustion"] = _check(
        scroll_issues,
        passed_summary="every scroll scope reached static/bottom and restored top",
        failed_summary="one or more surfaces lack complete scroll-boundary evidence",
        evidence={
            "scopes": len(scroll_items),
            "completed_scopes": completed_scroll_scopes,
            "required_regions": len(required_scroll_regions),
            "covered_regions": len(scroll_covered_regions),
            "covered_states": sorted(scroll_covered_states),
        },
    )

    # Page/variant consistency is evaluated before capability and control checks,
    # but all checks are independent and retained in the final report.
    page_variant_issues: List[Dict[str, Any]] = []
    page_by_id: Dict[str, Dict[str, Any]] = {}
    variant_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    state_catalog_memberships: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for container_key, page in page_items:
        page_id = _text(page.get("page_id")) or container_key
        if not _text(page.get("page_id")):
            page_variant_issues.append(_issue(
                "page_missing_id", "page catalog entry lacks page_id",
                container_key=container_key))
        elif isinstance(data.get("pages"), Mapping) and page_id != container_key:
            page_variant_issues.append(_issue(
                "page_key_mismatch", "page mapping key conflicts with page_id",
                container_key=container_key, page_id=page_id))
        if page_id in page_by_id:
            page_variant_issues.append(_issue(
                "duplicate_page_id", "page ids must be unique", page_id=page_id))
        page_by_id[page_id] = page
        if _text(page.get("semantic_name")).casefold() in {"", "unknown"}:
            page_variant_issues.append(_issue(
                "page_semantic_name_missing",
                "page requires a reusable semantic name for later live recognition",
                page_id=page_id))
        variant_items, variants_valid = _container_items(
            page.get("variants"), "variant_id")
        if not variants_valid or not variant_items:
            page_variant_issues.append(_issue(
                "page_variants_missing",
                "each page requires a non-empty variant catalog",
                page_id=page_id))
            continue
        for variant_key, variant in variant_items:
            variant_id = _text(variant.get("variant_id")) or variant_key
            if isinstance(page.get("variants"), Mapping) \
                    and _text(variant.get("variant_id")) \
                    and variant_id != variant_key:
                page_variant_issues.append(_issue(
                    "variant_key_mismatch",
                    "variant mapping key conflicts with variant_id",
                    page_id=page_id, container_key=variant_key,
                    variant_id=variant_id))
            key = (page_id, variant_id)
            if key in variant_by_key:
                page_variant_issues.append(_issue(
                    "duplicate_variant_id", "variant id repeats within one page",
                    page_id=page_id, variant_id=variant_id))
            variant_by_key[key] = variant
            if not _nonempty_predicate(variant.get("variant_signature")):
                page_variant_issues.append(_issue(
                    "variant_signature_missing",
                    "variant requires a stable observed-facts signature",
                    page_id=page_id, variant_id=variant_id))
            if not isinstance(variant.get("observed_facts"), Mapping):
                page_variant_issues.append(_issue(
                    "variant_facts_missing",
                    "variant requires a structured observed_facts mapping",
                    page_id=page_id, variant_id=variant_id))
            state_ids = _string_refs(variant.get("state_ids"), id_key="state_id")
            if not state_ids:
                page_variant_issues.append(_issue(
                    "variant_without_state",
                    "variant requires at least one execution state",
                    page_id=page_id, variant_id=variant_id))
            for state_id in state_ids:
                state_catalog_memberships[state_id].append(key)
                node = node_by_id.get(state_id)
                if node is None:
                    page_variant_issues.append(_issue(
                        "variant_state_missing",
                        "variant references a state absent from nodes",
                        page_id=page_id, variant_id=variant_id,
                        state_id=state_id))
                elif (_text(node.get("page_id")), _text(node.get("variant_id"))) != key:
                    page_variant_issues.append(_issue(
                        "variant_state_backref_mismatch",
                        "variant state points back to a different page/variant",
                        page_id=page_id, variant_id=variant_id,
                        state_id=state_id,
                        node_page_id=_text(node.get("page_id")),
                        node_variant_id=_text(node.get("variant_id"))))
    for state_id, node in node_by_id.items():
        key = (_text(node.get("page_id")), _text(node.get("variant_id")))
        if _text(node.get("page_identity_version")) \
                != "semantic_page_variant_v1":
            page_variant_issues.append(_issue(
                "page_identity_version_stale",
                "execution state was not produced by the current Page/Variant identity",
                state_id=state_id,
                observed=node.get("page_identity_version"),
                required="semantic_page_variant_v1"))
        if key not in variant_by_key:
            page_variant_issues.append(_issue(
                "node_variant_missing",
                "node page/variant is absent from the page catalog",
                state_id=state_id, page_id=key[0], variant_id=key[1]))
        memberships = state_catalog_memberships.get(state_id, [])
        if key not in memberships:
            page_variant_issues.append(_issue(
                "node_variant_backref_missing",
                "node is not listed by its page variant",
                state_id=state_id, page_id=key[0], variant_id=key[1]))
        if len(memberships) > 1:
            page_variant_issues.append(_issue(
                "state_in_multiple_variants",
                "an execution state may belong to exactly one page variant",
                state_id=state_id, memberships=memberships))
    for edge in action_edges:
        source = node_by_id.get(_text(edge.get("source")))
        target = node_by_id.get(_text(edge.get("target")))
        edge_id = _text(edge.get("action_edge_id"))
        for side, node in (("source", source), ("target", target)):
            if node is None:
                continue
            declared_page = _text(edge.get(f"{side}_page_id"))
            declared_variant = _text(edge.get(f"{side}_variant_id"))
            if declared_page != _text(node.get("page_id")) \
                    or declared_variant != _text(node.get("variant_id")):
                page_variant_issues.append(_issue(
                    "action_edge_page_variant_mismatch",
                    "action edge page/variant fields disagree with its endpoint",
                    action_edge_id=edge_id, side=side,
                    declared_page_id=declared_page,
                    declared_variant_id=declared_variant,
                    node_page_id=_text(node.get("page_id")),
                    node_variant_id=_text(node.get("variant_id"))))
    if not nodes or not page_items:
        page_variant_issues.append(_issue(
            "page_variant_material_unavailable",
            "both nodes and the native page catalog are required"))
    checks["page_variant_consistency"] = _check(
        page_variant_issues,
        passed_summary="node and page/variant catalogs agree bidirectionally",
        failed_summary="node and page/variant catalogs contain inconsistent references",
        evidence={
            "pages": len(page_by_id),
            "variants": len(variant_by_key),
            "states": len(node_by_id),
        },
    )

    checks["state_restoration"] = _state_restoration_check(
        data, action_edges, raw_action_edges)

    # Successful routing remains derived only from verified attempts.  For node
    # inventory reachability, a narrowly audited same-page ``blocked`` landing
    # may also connect the observed terminal variant; it never enters
    # ``verified_edge_ids`` or the routing view and cannot verify a capability.
    routing_issues: List[Dict[str, Any]] = []
    verified_edge_ids: set[str] = set()
    adjacency: Dict[str, set[str]] = defaultdict(set)
    for edge, _attempt in verified_attempt_records:
        edge_id = _text(edge.get("action_edge_id"))
        source = _text(edge.get("source"))
        target = _text(edge.get("target"))
        verified_edge_ids.add(edge_id)
        if source in node_by_id and target in node_by_id:
            adjacency[source].add(target)
    for edge, _attempt in terminal_landing_records:
        source = _text(edge.get("source"))
        target = _text(edge.get("target"))
        if source in node_by_id and target in node_by_id:
            adjacency[source].add(target)
    topology_refs: Dict[Tuple[str, str], set[str]] = defaultdict(set)
    for topology in topology_edges:
        pair = (_text(topology.get("source")), _text(topology.get("target")))
        topology_refs[pair].update(_string_refs(
            topology.get("action_edge_ids"), id_key="action_edge_id"))
        if topology.get("routing_verified") is True and not (
            topology_refs[pair] & verified_edge_ids
        ):
            routing_issues.append(_issue(
                "topology_route_without_verified_attempt",
                "compact topology claims a route without verified raw attempt evidence",
                source=pair[0], target=pair[1],
                action_edge_ids=sorted(topology_refs[pair])))
    for edge_id in sorted(verified_edge_ids):
        edge = edge_by_id.get(edge_id, {})
        pair = (_text(edge.get("source")), _text(edge.get("target")))
        if edge_id not in topology_refs.get(pair, set()):
            routing_issues.append(_issue(
                "verified_action_edge_not_linked",
                "verified action edge is absent from compact topology references",
                action_edge_id=edge_id, source=pair[0], target=pair[1]))

    explicit_root = _text(data.get("root_state_id"))
    if explicit_root:
        root_candidates = [explicit_root] if explicit_root in node_by_id else []
        if not root_candidates:
            routing_issues.append(_issue(
                "declared_root_missing", "root_state_id is absent from nodes",
                root_state_id=explicit_root))
    else:
        root_candidates = [
            state_id for state_id, node in node_by_id.items()
            if isinstance(node.get("action_path_from_root"), list)
            and len(node.get("action_path_from_root")) == 0
        ]
    root_candidates = sorted(set(root_candidates))
    if len(root_candidates) != 1:
        routing_issues.append(_issue(
            "root_not_unique",
            "routing certification requires exactly one persisted root",
            root_candidates=root_candidates))
    reachable: set[str] = set()
    if len(root_candidates) == 1:
        queue: deque[str] = deque(root_candidates)
        reachable.add(root_candidates[0])
        while queue:
            source = queue.popleft()
            for target in sorted(adjacency.get(source, set())):
                if target not in reachable:
                    reachable.add(target)
                    queue.append(target)
    unreachable_nodes = sorted(set(node_by_id) - reachable)
    if unreachable_nodes:
        routing_issues.append(_issue(
            "routing_unreachable_nodes",
            "registered nodes are not reachable from the root by verified attempts "
            "or audited same-page terminal blocked landings",
            state_ids=unreachable_nodes))
    flagged_unreachable = sorted(
        state_id for state_id, node in node_by_id.items()
        if node.get("unreachable") is True)
    if flagged_unreachable:
        routing_issues.append(_issue(
            "nodes_marked_unreachable",
            "completion cannot include nodes explicitly marked unreachable",
            state_ids=flagged_unreachable))
    if not node_by_id or "action_edges" not in data:
        routing_issues.append(_issue(
            "routing_material_unavailable",
            "nodes and raw action edges are required for reachability"))
    checks["routing_reachability"] = _check(
        routing_issues,
        passed_summary=(
            "every node is observed from one root through verified routes or "
            "audited same-page terminal block landings"),
        failed_summary=(
            "verified routing/terminal-landing evidence does not reach the "
            "complete node catalog"),
        evidence={
            "root_state_ids": root_candidates,
            "reachable_state_ids": sorted(reachable),
            "unreachable_state_ids": unreachable_nodes,
            "verified_action_edge_ids": sorted(verified_edge_ids),
            "terminal_landing_action_indices": sorted(
                _as_index(attempt.get("action_index")) or 0
                for _edge, attempt in terminal_landing_records),
        },
    )

    capability_issues: List[Dict[str, Any]] = []
    capability_by_id: Dict[str, Dict[str, Any]] = {}
    for container_key, capability in capability_items:
        capability_id = _text(capability.get("capability_id")) or container_key
        if not _text(capability.get("capability_id")):
            capability_issues.append(_issue(
                "capability_missing_id", "capability lacks capability_id",
                container_key=container_key))
        elif isinstance(data.get("capabilities"), Mapping) \
                and capability_id != container_key:
            capability_issues.append(_issue(
                "capability_key_mismatch",
                "capability mapping key conflicts with capability_id",
                container_key=container_key, capability_id=capability_id))
        if capability_id in capability_by_id:
            capability_issues.append(_issue(
                "duplicate_capability_id", "capability ids must be unique",
                capability_id=capability_id))
        capability_by_id[capability_id] = capability

    def require_capability_refs(
        owner_kind: str, owner_id: str, refs: Iterable[str]
    ) -> None:
        for capability_id in refs:
            if capability_id not in capability_by_id:
                capability_issues.append(_issue(
                    "unknown_capability_reference",
                    f"{owner_kind} references a capability absent from the catalog",
                    owner_id=owner_id, capability_id=capability_id))

    for state_id, node in node_by_id.items():
        node_refs = set(_string_refs(node.get("visible_capabilities")))
        require_capability_refs("node", state_id, node_refs)
        variant = variant_by_key.get((
            _text(node.get("page_id")), _text(node.get("variant_id"))), {})
        variant_refs = set(_string_refs(
            variant.get("visible_capabilities") if isinstance(variant, Mapping)
            else []))
        missing_from_variant = sorted(node_refs - variant_refs)
        if missing_from_variant:
            capability_issues.append(_issue(
                "node_capability_missing_from_variant",
                "node capability references are absent from its variant catalog",
                state_id=state_id,
                capability_ids=missing_from_variant))
    for page_id, page in page_by_id.items():
        page_refs = set(_string_refs(page.get("capability_ids")))
        require_capability_refs("page", page_id, page_refs)
        variant_refs: set[str] = set()
        for (candidate_page, _variant_id), variant in variant_by_key.items():
            if candidate_page == page_id:
                variant_refs.update(_string_refs(
                    variant.get("visible_capabilities")))
        missing_from_page = sorted(variant_refs - page_refs)
        if missing_from_page:
            capability_issues.append(_issue(
                "variant_capability_missing_from_page",
                "variant capability references are absent from their page catalog",
                page_id=page_id,
                capability_ids=missing_from_page))
    for (page_id, variant_id), variant in variant_by_key.items():
        require_capability_refs(
            "variant", f"{page_id}@{variant_id}",
            _string_refs(variant.get("visible_capabilities")))

    all_variant_ids = defaultdict(set)
    for page_id, variant_id in variant_by_key:
        all_variant_ids[variant_id].add(page_id)
    for capability_id, capability in capability_by_id.items():
        page_id = _text(capability.get("page_id"))
        if not page_id or page_id not in page_by_id:
            capability_issues.append(_issue(
                "capability_page_missing",
                "capability page_id is absent from the page catalog",
                capability_id=capability_id, page_id=page_id))
        entry_variants = set(_string_refs(capability.get("entry_variants"), "variant_id"))
        entry_variants.update(_string_refs(
            capability.get("evidence_variants"), "variant_id"))
        available_when = capability.get("available_when") or {}
        if isinstance(available_when, Mapping):
            entry_variants.update(_string_refs(
                available_when.get("variant_ids"), "variant_id"))
        for variant_id in sorted(entry_variants):
            if (page_id, variant_id) not in variant_by_key:
                capability_issues.append(_issue(
                    "capability_variant_missing",
                    "capability references a variant absent from its page",
                    capability_id=capability_id,
                    page_id=page_id, variant_id=variant_id))
        source_refs = capability.get("source_elements")
        if not isinstance(source_refs, list) or not source_refs:
            capability_issues.append(_issue(
                "capability_source_missing",
                "capability requires at least one grounded source element reference",
                capability_id=capability_id))
            source_refs = []
        for source_ref in source_refs:
            if not isinstance(source_ref, Mapping):
                capability_issues.append(_issue(
                    "capability_source_malformed",
                    "capability source element reference must be an object",
                    capability_id=capability_id))
                continue
            state_id = _text(source_ref.get("state_id"))
            variant_id = _text(source_ref.get("variant_id"))
            source_node = node_by_id.get(state_id)
            if not state_id or source_node is None:
                capability_issues.append(_issue(
                    "capability_source_state_missing",
                    "capability source references an absent state",
                    capability_id=capability_id, state_id=state_id))
                continue
            if variant_id and variant_id != _text(source_node.get("variant_id")):
                capability_issues.append(_issue(
                    "capability_source_variant_mismatch",
                    "capability source variant disagrees with its state",
                    capability_id=capability_id, state_id=state_id,
                    variant_id=variant_id,
                    node_variant_id=_text(source_node.get("variant_id"))))
            source_elements = [
                item for item in source_node.get("elements") or []
                if isinstance(item, Mapping)
            ]
            if not any(_semantic_element_match(source_ref, item)
                       for item in source_elements):
                capability_issues.append(_issue(
                    "capability_source_element_missing",
                    "capability source cannot be tied to grounded node evidence",
                    capability_id=capability_id, state_id=state_id,
                    element_id=_text(source_ref.get("element_id")),
                    element_label=_text(source_ref.get("element_label"))))
        action_refs = set(_string_refs(
            capability.get("action_edge_ids"), "action_edge_id"))
        missing_action_refs = sorted(action_refs - set(edge_by_id))
        if missing_action_refs:
            capability_issues.append(_issue(
                "capability_action_edge_missing",
                "capability references unknown action edges",
                capability_id=capability_id,
                action_edge_ids=missing_action_refs))
        status = _text(capability.get("status")).casefold()
        availability = _text(capability.get("availability_status")).casefold()
        source_types = {
            " ".join(_text(source.get("element_type")).casefold().split())
            for source in capability.get("source_elements") or []
            if isinstance(source, Mapping)
        }
        if source_types & _DRAG_CONTROL_TYPES \
                and not list(capability.get("execution_recipe") or []):
            if (_text(capability.get("execution_support")).casefold()
                    != "unsupported"
                    or not _nonempty_predicate(
                        capability.get("unsupported_reason"))):
                capability_issues.append(_issue(
                    "unsupported_drag_contract_missing",
                    "a drag/slider without a semantic endpoint must be explicitly unsupported",
                    capability_id=capability_id,
                    source_types=sorted(source_types),
                ))
        is_verified = status == "verified" or availability == "verified"
        if is_verified:
            verified_refs = sorted(action_refs & verified_edge_ids)
            if not verified_refs:
                capability_issues.append(_issue(
                    "verified_capability_without_verified_edge",
                    "verified capability lacks a raw verified action edge",
                    capability_id=capability_id,
                    action_edge_ids=sorted(action_refs)))
            effects = capability.get("effects")
            if not isinstance(effects, (list, tuple, Mapping)) or not effects:
                capability_issues.append(_issue(
                    "verified_capability_without_effect",
                    "verified capability requires a non-empty observable effect",
                    capability_id=capability_id))
            if not _nonempty_predicate(capability.get("success_predicate")):
                capability_issues.append(_issue(
                    "verified_capability_without_predicate",
                    "verified capability requires an explicit success predicate",
                    capability_id=capability_id))
        target_pages = set(_string_refs(capability.get("target_pages"), "page_id"))
        for target_page in sorted(target_pages):
            if target_page not in page_by_id:
                capability_issues.append(_issue(
                    "capability_target_page_missing",
                    "capability target page is absent from the catalog",
                    capability_id=capability_id, target_page_id=target_page))
        for target_variant in _string_refs(
                capability.get("target_variants"), "variant_id"):
            candidate_pages = target_pages or all_variant_ids.get(target_variant, set())
            if not any((candidate_page, target_variant) in variant_by_key
                       for candidate_page in candidate_pages):
                capability_issues.append(_issue(
                    "capability_target_variant_missing",
                    "capability target variant is absent from its target pages",
                    capability_id=capability_id,
                    target_variant_id=target_variant,
                    target_page_ids=sorted(candidate_pages)))
    if not capabilities_container_valid or "capabilities" not in data:
        capability_issues.append(_issue(
            "capability_catalog_unavailable",
            "native capability references cannot be audited"))
    checks["capability_integrity"] = _check(
        capability_issues,
        passed_summary="capability references and verified contracts are grounded",
        failed_summary="capability references or verified contracts are incomplete",
        evidence={
            "capabilities": len(capability_by_id),
            "verified_capabilities": sum(
                _text(item.get("status")).casefold() == "verified"
                or _text(item.get("availability_status")).casefold() == "verified"
                for item in capability_by_id.values()),
            "verified_action_edge_ids": sorted(verified_edge_ids),
        },
    )

    # Build semantic evidence indexes for per-control outcomes.
    node_elements: Dict[str, List[Dict[str, Any]]] = {
        state_id: [dict(item) for item in node.get("elements") or []
                   if isinstance(item, Mapping)]
        for state_id, node in node_by_id.items()
    }
    verified_direct: Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]] = \
        defaultdict(list)
    for edge, attempt in verified_attempt_records:
        source = _text(edge.get("source"))
        verified_direct[source].append((edge, attempt))

    abnormal_direct: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for abnormal in abnormal_records:
        state_id = _text(abnormal.get("state_id"))
        abnormal_direct[state_id].append(abnormal)

    control_outcomes: List[Dict[str, Any]] = []

    def _fresh_stateful_no_effect_proof(
            state_id: str, element: Mapping[str, Any]) -> bool:
        for edge in action_edges:
            if _text(edge.get("source")) != state_id \
                    or not _semantic_element_match(edge, element):
                continue
            for attempt in edge.get("attempts") or []:
                if not isinstance(attempt, Mapping):
                    continue
                evidence = attempt.get("evidence") or {}
                phash_distance = evidence.get(
                    "post_action_phash_distance") \
                    if isinstance(evidence, Mapping) else None
                if (_text(attempt.get("outcome")).casefold() == "no_effect"
                        and isinstance(evidence, Mapping)
                        and evidence.get("fresh_post_action_observation") is True
                        and isinstance(phash_distance, (int, float))
                        and not isinstance(phash_distance, bool)
                        and float(phash_distance) == 0.0):
                    return True
        return False

    for state_id in sorted(node_by_id):
        node = node_by_id[state_id]
        for ordinal, element in enumerate(node_elements.get(state_id, [])):
            if not _is_control(element):
                continue
            element_id = _element_id(element)
            label = _element_label(element)
            category = _text(element.get("category")).casefold()
            stateful = bool(element.get("stateful"))
            navigation = _is_navigation(element)
            strong_required = navigation or stateful
            evidence: Dict[str, Any] = {}
            outcome = "unresolved"
            exploration_status = _text(
                element.get("exploration_status")).casefold()
            if element.get("back"):
                outcome = "back"
                evidence = {"reason": "explicit back control"}
            elif exploration_status == "semantic_only":
                outcome = "semantic_only"
                evidence = {"reason": _text(element.get("exploration_reason"))
                            or "Explorer resolved visible semantics"}
            elif exploration_status == "covered":
                representative_id = _text(element.get("covered_by"))
                representative_state_id = _text(
                    element.get("covered_by_state")) or state_id
                representative = next((
                    item for item in node_elements.get(
                        representative_state_id, [])
                    if _element_id(item) == representative_id
                ), None)
                current_region_id = _text(element.get("region_id"))
                representative_region_id = _text(
                    (representative or {}).get("region_id"))
                shared_region_valid = (
                    representative_state_id == state_id
                    or bool(current_region_id)
                    and current_region_id == representative_region_id
                )
                representative_attempt = next((
                    attempt
                    for edge, attempt in verified_direct.get(
                        representative_state_id, [])
                    if representative is not None
                    and shared_region_valid
                    and _semantic_element_match(edge, representative)
                ), None)
                if representative_attempt is not None:
                    outcome = "explorer_covered"
                    evidence = {
                        "scope": ("direct" if representative_state_id == state_id
                                  else "shared_region"),
                        "representative_state_id": representative_state_id,
                        "representative_element_id": representative_id,
                        "action_index": _as_index(
                            representative_attempt.get("action_index")),
                        "reason": _text(element.get("exploration_reason")),
                    }
                else:
                    evidence = {
                        "reason": "covered representative lacks a verified action",
                        "representative_state_id": representative_state_id,
                        "representative_element_id": representative_id,
                    }
            else:
                matched_verified: Optional[Tuple[Dict[str, Any], Dict[str, Any]]] = None
                for candidate in verified_direct.get(state_id, []):
                    edge, attempt = candidate
                    if not _semantic_element_match(edge, element):
                        continue
                    attempt_evidence = attempt.get("evidence") or {}
                    stateful_transaction = (
                        stateful
                        and _normalise(element.get("effect_scope"))
                        == "functionset"
                    )
                    if stateful_transaction and not (
                        isinstance(attempt_evidence, Mapping)
                        and attempt_evidence.get("stateful")
                        and _text(attempt_evidence.get("mutation_id"))
                    ):
                        continue
                    matched_verified = candidate
                    break
                if matched_verified is not None:
                    edge, attempt = matched_verified
                    outcome = "verified_attempt"
                    evidence = {
                        "scope": "direct",
                        "action_edge_id": _text(edge.get("action_edge_id")),
                        "action_index": _as_index(attempt.get("action_index")),
                        "outcome": _text(attempt.get("outcome")),
                    }
                else:
                    direct_abnormal = next((
                        record for record in abnormal_direct.get(state_id, [])
                        if _semantic_element_match(record, element)
                    ), None)
                    embedded_abnormal = _text(element.get("abnormal_reason"))
                    abnormal_reason = _text(
                        (direct_abnormal or {}).get("reason")
                        or embedded_abnormal)
                    abnormal_is_certifiable = (
                        (direct_abnormal is not None or embedded_abnormal)
                        and _certifiable_abnormal_reason(
                            abnormal_reason,
                            record=direct_abnormal,
                            state_id=state_id,
                            node_by_id=node_by_id,
                        )
                    )
                    if abnormal_reason == "stateful_no_effect" \
                            and not _fresh_stateful_no_effect_proof(
                                state_id, element):
                        abnormal_is_certifiable = False
                    if abnormal_is_certifiable:
                        outcome = "abnormal"
                        evidence = {
                            "scope": "direct",
                            "reason": abnormal_reason,
                        }
                    else:
                        inventory_ids = [
                            capability_id
                            for capability_id, capability in capability_by_id.items()
                            if _capability_matches_control(
                                capability,
                                capability_id=capability_id,
                                node=node,
                                element=element,
                            )
                        ]
                        if inventory_ids and not strong_required:
                            outcome = "inventory_capability"
                            evidence = {"capability_ids": sorted(inventory_ids)}
                        else:
                            failed_attempts = [
                                _text(attempt.get("outcome"))
                                for edge, attempt in verified_direct.get(state_id, [])
                                if _semantic_element_match(edge, element)
                            ]
                            evidence = {
                                "reason": (
                                    "visited is not execution evidence for navigation/stateful controls"
                                    if element.get("visited") and strong_required
                                    else "no accepted terminal outcome"
                                ),
                                "observed_attempt_outcomes": failed_attempts,
                                "inventory_capability_ids": sorted(inventory_ids),
                            }
                            if abnormal_reason:
                                evidence["rejected_abnormal_reason"] = (
                                    abnormal_reason)
            control_outcomes.append({
                "state_id": state_id,
                "page_id": _text(node.get("page_id")),
                "variant_id": _text(node.get("variant_id")),
                "element_index": ordinal,
                "element_id": element_id,
                "element_uid": _element_uid(element),
                "label": label,
                "category": category,
                "stateful": stateful,
                "visited": element.get("visited") is True,
                "exploration_status": exploration_status,
                "outcome": outcome,
                "resolved": outcome != "unresolved",
                "evidence": evidence,
                "group": _text(element.get("group")),
                "region": _text(element.get("region")),
            })

    # A homogeneous group is parameterized by one real representative.  Alias
    # retirement never chains through another alias.  Navigation aliases are
    # stronger than terminal retirement of one concrete row: only a real
    # verified attempt can prove that the parameterized navigation operation
    # works for the group.  In particular, an abnormal/no-effect representative
    # retires itself but cannot retire sibling navigation rows.
    representatives: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for record in control_outcomes:
        group = _normalise(record.get("group"))
        if (not group or not record.get("resolved")
                or _is_peer_navigation_record(record)):
            continue
        navigation = record.get("category") in {"navigation", "nav"}
        strong = record.get("outcome") in {
            "verified_attempt", "abnormal", "back",
        }
        if navigation and record.get("outcome") != "verified_attempt":
            continue
        if record.get("stateful"):
            if not strong:
                continue
        key = (record.get("page_id") or record.get("state_id"), group)
        representatives.setdefault(key, record)
    for record in control_outcomes:
        if record.get("resolved"):
            continue
        group = _normalise(record.get("group"))
        if _is_peer_navigation_record(record):
            continue
        key = (record.get("page_id") or record.get("state_id"), group)
        representative = representatives.get(key) if group else None
        if representative is None:
            continue
        if record.get("category") in {"navigation", "nav"}:
            if representative.get("category") not in {"navigation", "nav"} \
                    or representative.get("outcome") != "verified_attempt":
                continue
        record["outcome"] = "group_alias"
        record["resolved"] = True
        record["evidence"] = {
            "representative": {
                "state_id": representative.get("state_id"),
                "element_id": representative.get("element_id"),
                "label": representative.get("label"),
                "outcome": representative.get("outcome"),
            }
        }

    control_issues: List[Dict[str, Any]] = []
    unresolved_controls = [
        record for record in control_outcomes if not record.get("resolved")]
    for record in unresolved_controls:
        control_issues.append(_issue(
            "control_without_outcome",
            "interactive control lacks verified, terminal, inventory, or alias evidence",
            state_id=record.get("state_id"),
            element_id=record.get("element_id"),
            label=record.get("label"),
            category=record.get("category"),
            stateful=record.get("stateful"),
            visited=record.get("visited"),
            reason=(record.get("evidence") or {}).get("reason")))
    if not node_by_id:
        control_issues.append(_issue(
            "control_inventory_unavailable",
            "node element inventories are required for coverage"))
    for state_id, node in node_by_id.items():
        if _text(node.get("perception_mode")) != "region_lazy":
            continue
        regions = node.get("region_observation")
        if not isinstance(regions, Mapping) or not regions:
            control_issues.append(_issue(
                "region_inventory_unavailable",
                "Region-lazy State lacks its persisted Region observation ledger",
                state_id=state_id))
            continue
        incomplete = {
            str(region_id): _text((record or {}).get("status"))
            for region_id, record in regions.items()
            if not isinstance(record, Mapping)
            or _text(record.get("status")) != "complete"
        }
        if incomplete:
            control_issues.append(_issue(
                "region_inventory_incomplete",
                "every registered Region must be observed before control "
                "coverage can be certified",
                state_id=state_id, regions=incomplete))
    checks["control_coverage"] = _check(
        control_issues,
        passed_summary="every interactive control has an accepted coverage outcome",
        failed_summary="one or more interactive controls have no authoritative outcome",
        evidence={
            "controls": len(control_outcomes),
            "resolved": len(control_outcomes) - len(unresolved_controls),
            "unresolved": len(unresolved_controls),
            "outcome_counts": {
                outcome: sum(item.get("outcome") == outcome
                             for item in control_outcomes)
                for outcome in sorted({
                    _text(item.get("outcome")) for item in control_outcomes
                })
            },
        },
    )

    ordered_check_ids = (
        "schema_materials",
        "frontier_exhaustion",
        "scroll_exhaustion",
        "control_coverage",
        "state_restoration",
        "page_variant_consistency",
        "routing_reachability",
        "capability_integrity",
    )
    checks = {check_id: checks[check_id] for check_id in ordered_check_ids}
    failed_checks = [
        check_id for check_id, check in checks.items() if not check["passed"]]

    digest_material = {
        "graph_schema_version": schema_version,
        "stop_reason": stop_reason,
        "nodes": [{
            "state_id": state_id,
            "page_id": node.get("page_id"),
            "variant_id": node.get("variant_id"),
            "unreachable": node.get("unreachable"),
            "action_path_from_root": node.get("action_path_from_root"),
            "elements": node.get("elements"),
            "visible_capabilities": node.get("visible_capabilities"),
        } for state_id, node in sorted(node_by_id.items())],
        "pages": data.get("pages"),
        "capabilities": data.get("capabilities"),
        "action_edges": data.get("action_edges"),
        "scroll_ledger": data.get("scroll_ledger"),
        "abnormal_buttons": data.get("abnormal_buttons"),
    }
    canonical = json.dumps(
        _json_safe(digest_material),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    graph_evidence_digest = {
        "algorithm": "sha256",
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "graph_schema_version": schema_version,
        "app_name": _text(data.get("app_name")),
        "counts": {
            "nodes": len(node_by_id),
            "pages": len(page_by_id),
            "variants": len(variant_by_key),
            "scroll_scopes": len(scroll_items),
            "controls": len(control_outcomes),
            "resolved_controls": len(control_outcomes) - len(unresolved_controls),
            "action_edges": len(action_edges),
            "attempts": attempt_count,
            "verified_action_edges": len(verified_edge_ids),
            "capabilities": len(capability_by_id),
        },
        "root_state_ids": root_candidates,
        "reachable_state_ids": sorted(reachable),
        "unreachable_state_ids": unreachable_nodes,
        "open_mutation_ids": list(
            checks["state_restoration"]["evidence"]["open_mutation_ids"]
        ),
        "failed_checks": failed_checks,
    }
    return {
        "schema": CERTIFICATE_SCHEMA,
        "status": "certified" if not failed_checks else "incomplete",
        "checks": checks,
        "control_outcomes": control_outcomes,
        "graph_evidence_digest": graph_evidence_digest,
    }


__all__ = ["CERTIFICATE_SCHEMA", "evaluate_traversal_completion"]
