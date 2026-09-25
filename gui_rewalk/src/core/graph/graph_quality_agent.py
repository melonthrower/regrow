"""Read-only structural and semantic quality audit for visual GUI graphs.

The traversal graph is evidence, not something an evaluator may repair in place.
``GraphQualityAgent`` therefore only reads ``graph.json`` and referenced
screenshots and returns a JSON-serialisable report.  A VLM judge is optional and
is supplied by dependency injection; this module never constructs a network
client.

The deterministic rules deliberately remain useful without a VLM.  When one is
provided, every request and response follows a small versioned JSON contract so
the caller can cache and audit semantic decisions.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol

from PIL import Image


REPORT_SCHEMA = "gui_rewalk_graph_quality_report_v1"
VLM_REQUEST_SCHEMA = "gui_rewalk_graph_quality_vlm_request_v1"
VLM_RESPONSE_SCHEMA = "gui_rewalk_graph_quality_vlm_response_v1"

COVERAGE_STATUSES = frozenset(
    {"verified", "conditional", "blocked", "unknown", "unsupported"}
)
CORRECTNESS_VALUES = frozenset({"correct", "incorrect", "unknown"})

_NAV_CATEGORIES = frozenset({"navigation", "nav"})
_DATA_CONTROL_TYPES = frozenset(
    {
        "input",
        "textbox",
        "text field",
        "text_field",
        "checkbox",
        "radio",
        "radio button",
        "switch",
        "toggle",
        "slider",
        "combobox",
        "combo box",
        "select",
        "dropdown",
    }
)
_SUSPICIOUS_SCREEN_TERMS = (
    "traceback (most recent call last)",
    "system program problem detected",
    "application error",
    "application has stopped",
    "not responding",
    "has experienced an internal error",
    "程序错误",
    "应用崩溃",
)
_PERMISSION_GATE_TERMS = (
    "unlock to ",
    "authentication required",
    "permission required",
    "authorization required",
    "sign in to continue",
    "需要解锁",
    "需要授权",
    "需要认证",
    "请先登录",
)
_BLOCKED_TERMS = _PERMISSION_GATE_TERMS + (
    "blocked by login",
    "blocked_by_login",
    "blocked_by_auth",
)
_SUCCESS_OUTCOMES = frozenset(
    {"success", "succeeded", "verified", "committed", "transitioned",
     "transitioned_consistent"}
)
_FAILED_EDGE_OUTCOMES = frozenset(
    {
        "no_effect",
        "transitioned_inconsistent",
        "permission_blocked",
        "blocked",
        "external_app",
        "app_crash",
        "perception_failed",
        "quarantined",
    }
)


class VLMJudge(Protocol):
    """Dependency-injected semantic judge; no transport is assumed."""

    def __call__(self, request: Mapping[str, Any]) -> Mapping[str, Any] | str:
        ...


def _nodes(graph: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = graph.get("nodes") or graph.get("states") or []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _edges(graph: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = graph.get("edges") or graph.get("links") or []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _state_id(node: Mapping[str, Any]) -> str:
    return str(node.get("state_id") or node.get("id") or "")


def _normalise(text: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(text or "").casefold())


def _tokens(text: Any) -> set[str]:
    value = str(text or "").casefold()
    tokens = set(re.findall(r"[0-9a-z]+|[\u4e00-\u9fff]", value))
    return {token for token in tokens if token}


def _labels_agree(left: Any, right: Any) -> bool:
    a, b = _normalise(left), _normalise(right)
    if not a or not b:
        return True
    if a == b or a in b or b in a:
        return True
    ta, tb = _tokens(left), _tokens(right)
    return bool(ta and tb and ta.intersection(tb))


def _is_navigation(element: Mapping[str, Any]) -> bool:
    if str(element.get("category") or "").casefold() not in _NAV_CATEGORIES:
        return False
    if element.get("back"):
        return False
    el_type = " ".join(str(element.get("el_type") or "").casefold().split())
    return bool(str(element.get("name") or "").strip()) and el_type not in _DATA_CONTROL_TYPES


def _safe_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _compact_element(element: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep evidence fields while avoiding model/runtime-only objects."""
    fields = (
        "id",
        "uid",
        "name",
        "category",
        "el_type",
        "interactive",
        "visited",
        "selected",
        "back",
        "enabled",
        "disabled",
        "requires_permission",
        "region",
        "region_id",
        "bbox",
        "bbox_xyxy",
        "bbox_xywh",
        "center",
        "region_bbox",
        "region_bbox_xywh",
        "abnormal_reason",
        "abnormal_detail",
    )
    return {field: copy.deepcopy(element.get(field)) for field in fields if field in element}


def _mapping_get(mapping: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = mapping
        ok = True
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                ok = False
                break
            current = current[part]
        if ok and current is not None:
            return current
    return None


def _as_point(value: Any) -> Optional[List[float]]:
    if isinstance(value, Mapping):
        value = [value.get("x"), value.get("y")]
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return [float(value[0]), float(value[1])]
    except (TypeError, ValueError):
        return None


def _as_bbox(value: Any, *, xywh: bool = False) -> Optional[List[float]]:
    if isinstance(value, Mapping):
        if {"x", "y", "width", "height"} <= set(value):
            value = [value["x"], value["y"], value["width"], value["height"]]
            xywh = True
        elif {"x0", "y0", "x1", "y1"} <= set(value):
            value = [value["x0"], value["y0"], value["x1"], value["y1"]]
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        x0, y0, third, fourth = (float(value[index]) for index in range(4))
    except (TypeError, ValueError):
        return None
    if xywh:
        return [x0, y0, x0 + max(0.0, third), y0 + max(0.0, fourth)]
    return [x0, y0, third, fourth]


def _inside(point: Optional[List[float]], bbox: Optional[List[float]]) -> bool:
    return bool(
        point
        and bbox
        and bbox[0] <= point[0] <= bbox[2]
        and bbox[1] <= point[1] <= bbox[3]
    )


def _modal_bbox(node: Mapping[str, Any]) -> Optional[List[float]]:
    is_modal = bool(
        _mapping_get(
            node,
            "is_modal",
            "perception.is_modal",
            "perception_meta.is_modal",
            "surface.is_modal",
        )
    )
    if not is_modal:
        return None
    xywh_value = _mapping_get(
        node,
        "modal_bbox_xywh",
        "perception.modal_bbox_xywh",
        "perception_meta.modal_bbox_xywh",
    )
    if xywh_value is not None:
        return _as_bbox(xywh_value, xywh=True)
    value = _mapping_get(
        node,
        "modal_bbox",
        "modal",
        "active_surface_bbox",
        "perception.modal_bbox",
        "perception_meta.modal_bbox",
        "surface.bbox",
    )
    return _as_bbox(value)


def _region_bbox(edge: Mapping[str, Any], element: Mapping[str, Any]) -> Optional[List[float]]:
    xywh_value = _mapping_get(
        edge,
        "region_bbox_xywh",
        "retarget.region_bbox_xywh",
        "evidence.region_bbox_xywh",
    )
    if xywh_value is None:
        xywh_value = element.get("region_bbox_xywh")
    if xywh_value is not None:
        return _as_bbox(xywh_value, xywh=True)
    value = _mapping_get(
        edge,
        "region_bbox",
        "retarget.region_bbox",
        "evidence.region_bbox",
    )
    if value is None:
        value = element.get("region_bbox")
    return _as_bbox(value)


def _executed_point(edge: Mapping[str, Any]) -> Optional[List[float]]:
    value = _mapping_get(
        edge,
        "retarget_to",
        "resolved_center",
        "live_center",
        "click_center",
        "retarget.to",
        "retarget.resolved_center",
        "evidence.retarget_to",
        "evidence.resolved_center",
    )
    point = _as_point(value)
    if point:
        return point
    action = edge.get("action")
    if isinstance(action, Mapping):
        parameters = action.get("parameters")
        if isinstance(parameters, Mapping) and "x" in parameters and "y" in parameters:
            return _as_point(parameters)
    return None


def _find_element(node: Mapping[str, Any], edge: Mapping[str, Any]) -> Dict[str, Any]:
    elements = [item for item in (node.get("elements") or []) if isinstance(item, Mapping)]
    element_id = str(edge.get("element_id") or "")
    label = _normalise(edge.get("element_label"))
    if element_id:
        for element in elements:
            if str(element.get("id") or "") == element_id:
                return dict(element)
    if label:
        for element in elements:
            if _normalise(element.get("name")) == label:
                return dict(element)
    return {}


def _record_matches_element(
    record: Mapping[str, Any], element: Mapping[str, Any]
) -> bool:
    record_id = str(record.get("element_id") or "")
    element_id = str(element.get("id") or "")
    if record_id and element_id and record_id == element_id:
        return True
    record_label = _normalise(
        record.get("element_label") or record.get("element_name")
        or record.get("semantic_description"))
    element_label = _normalise(element.get("name"))
    if not record_label or not element_label or record_label != element_label:
        return False
    record_region = str(record.get("region_id") or record.get("region") or "")
    element_region = str(element.get("region_id") or element.get("region") or "")
    return not record_region or not element_region or record_region == element_region


def _resolve_screenshot(
    declared: Any,
    *,
    graph_path: Optional[Path],
    workspace: Path,
    node_id: str,
) -> Optional[Path]:
    candidates: List[Path] = []
    if declared:
        raw = Path(str(declared).replace("\\", "/"))
        candidates.append(raw)
        if graph_path:
            candidates.append(graph_path.parent / raw)
        candidates.append(workspace / raw)
    if graph_path:
        candidates.extend(
            [
                graph_path.parent / "screenshots" / f"{node_id}.png",
                graph_path.parent / "node_artifacts" / node_id / "screenshot.png",
            ]
        )
    candidates.append(workspace / "node_artifacts" / node_id / "screenshot.png")
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        key = str(resolved).casefold()
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file():
            return resolved
    return None


def _dhash(image: Image.Image) -> str:
    pixels = list(image.convert("L").resize((9, 8)).getdata())
    bits: List[str] = []
    for row in range(8):
        offset = row * 9
        bits.extend(
            "1" if pixels[offset + col] > pixels[offset + col + 1] else "0"
            for col in range(8)
        )
    return f"{int(''.join(bits), 2):016x}"


def _hamming_hex(left: str, right: str) -> int:
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except (TypeError, ValueError):
        return 64


def _screenshot_evidence(path: Optional[Path], declared: Any) -> Dict[str, Any]:
    evidence: Dict[str, Any] = {
        "declared_path": str(declared or ""),
        "resolved_path": str(path) if path else None,
        "exists": bool(path),
    }
    if not path:
        return evidence
    try:
        payload = path.read_bytes()
        with Image.open(path) as image:
            evidence.update(
                {
                    "width": image.width,
                    "height": image.height,
                    "format": image.format,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "dhash": _dhash(image),
                }
            )
    except Exception as exc:  # report corrupt evidence rather than failing the audit
        evidence.update({"readable": False, "error": f"{type(exc).__name__}: {exc}"})
    else:
        evidence["readable"] = True
    return evidence


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    scope: str = "graph",
    evidence: Optional[Mapping[str, Any]] = None,
    **references: Any,
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "severity": severity.upper(),
        "code": code,
        "scope": scope,
        "message": message,
    }
    item.update({key: value for key, value in references.items() if value is not None})
    if evidence:
        item["evidence"] = copy.deepcopy(dict(evidence))
    return item


def _explicit_page_names(node: Mapping[str, Any]) -> set[str]:
    values: List[Any] = [node.get("page_name")]
    for key in ("merged_page_names", "observed_page_names", "page_name_history"):
        raw = node.get(key)
        if isinstance(raw, (list, tuple, set)):
            values.extend(raw)
    for key in ("observations", "merge_history"):
        raw = node.get(key)
        if isinstance(raw, list):
            values.extend(item.get("page_name") for item in raw if isinstance(item, Mapping))
    return {_normalise(value) for value in values if _normalise(value)}


def _functional_signature(node: Mapping[str, Any]) -> set[str]:
    signature = set()
    for element in node.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        if element.get("interactive") is False and not _is_navigation(element):
            continue
        name = _normalise(element.get("name"))
        if name:
            signature.add(
                "|".join(
                    (
                        str(element.get("region") or ""),
                        str(element.get("category") or ""),
                        name,
                    )
                )
            )
    return signature


def _selected_signature(node: Mapping[str, Any]) -> set[str]:
    return {
        _normalise(element.get("name"))
        for element in node.get("elements") or []
        if isinstance(element, Mapping)
        and element.get("selected")
        and _normalise(element.get("name"))
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _permission_blocked(node: Mapping[str, Any], element: Mapping[str, Any]) -> bool:
    if element.get("enabled") is False or element.get("disabled") is True:
        return True
    reason = str(element.get("blocked_reason") or "").strip().casefold()
    if element.get("requires_permission") is True or reason:
        return True
    return False


def _possible_permission_blocked(
    node: Mapping[str, Any], element: Mapping[str, Any]
) -> bool:
    """Return a low-confidence clue for legacy graphs lacking access fields."""

    if _permission_blocked(node, element):
        return False
    label = str(element.get("name") or "")
    region = str(element.get("region") or "").casefold()
    if not label or region in {"nav_sidebar", "sidebar"}:
        return False
    gate_fragments = [str(node.get("blocked_reason") or "")]
    for item in node.get("elements") or []:
        if not isinstance(item, Mapping):
            continue
        fragment = " ".join((
            str(item.get("name") or ""),
            str(item.get("blocked_reason") or ""),
        )).strip()
        if item.get("requires_permission") is True \
                or item.get("enabled") is False \
                or any(term in fragment.casefold() for term in _PERMISSION_GATE_TERMS):
            gate_fragments.append(fragment)
    gate_text = " ".join(gate_fragments).casefold()
    return bool(
        any(term in gate_text for term in _PERMISSION_GATE_TERMS)
        and _tokens(label) & _tokens(gate_text)
    )


def _has_permission_gate(node: Mapping[str, Any]) -> bool:
    if node.get("requires_permission") is True or node.get("permission_blocked") is True:
        return True
    text = " ".join(
        [
            str(node.get("page_name") or ""),
            str(node.get("blocked_reason") or ""),
            *(
                str(item.get("name") or "")
                for item in node.get("elements") or []
                if isinstance(item, Mapping)
            ),
        ]
    ).casefold()
    return any(term in text for term in _PERMISSION_GATE_TERMS)


def _unexplored_navigation(
    node: Mapping[str, Any], nav: Sequence[Mapping[str, Any]]
) -> List[Mapping[str, Any]]:
    pending: List[Mapping[str, Any]] = []
    for item in nav:
        if item.get("visited") or item.get("selected"):
            continue
        if str(item.get("abnormal_reason") or "").strip():
            continue
        if _permission_blocked(node, item):
            continue
        pending.append(item)
    return pending


def _node_baseline_coverage(
    node: Mapping[str, Any],
    *,
    screenshot_ok: bool,
    nav: List[Mapping[str, Any]],
    node_findings: List[Mapping[str, Any]],
) -> str:
    explicit = str(node.get("coverage_status") or "").casefold()
    if explicit in {"blocked", "conditional", "verified"}:
        return explicit
    if explicit == "unsupported":
        justification = node.get("coverage_evidence") or node.get("unsupported_reason")
        return "unsupported" if justification else "unknown"
    element_items = [
        item for item in node.get("elements") or []
        if isinstance(item, Mapping)
    ]
    if any(_permission_blocked(node, item) for item in element_items):
        return "blocked"
    if any(item.get("requires_permission") is True for item in element_items):
        return "conditional"
    text = " ".join(
        [
            str(node.get("page_name") or ""),
            str(node.get("blocked_reason") or ""),
            str(node.get("abnormal_reason") or ""),
            *(
                f"{item.get('name', '')} {item.get('abnormal_reason', '')}"
                for item in node.get("elements") or []
                if isinstance(item, Mapping)
            ),
        ]
    ).casefold()
    if any(term in text for term in _BLOCKED_TERMS):
        return "blocked"
    if node.get("requires") or node.get("preconditions") or node.get("setup_recipe"):
        return "conditional"
    if not screenshot_ok or not (node.get("elements") or []):
        return "unknown"
    if _unexplored_navigation(node, nav):
        return "unknown"
    if any(item.get("severity") == "ERROR" for item in node_findings):
        return "unknown"
    return "verified"


def _correctness(findings: List[Mapping[str, Any]]) -> str:
    if any(item.get("severity") == "ERROR" for item in findings):
        return "incorrect"
    uncertain_codes = {
        "suspicious_screen_text",
        "duplicate_node_visual",
        "near_duplicate_function_node",
        "possible_overmerge",
        "overmerge_page_identity_conflict",
        "vlm_judge_error",
    }
    if any(item.get("code") in uncertain_codes for item in findings):
        return "unknown"
    return "correct"


def _append_report_finding(report, findings, finding) -> None:
    report["findings"].append(finding)
    findings.append(finding)


def _schema_v3_catalogs(data):
    pages_raw = data.get("pages") or {}
    pages = (
        dict(pages_raw) if isinstance(pages_raw, Mapping)
        else {
            str(item.get("page_id") or ""): dict(item)
            for item in pages_raw
            if isinstance(item, Mapping) and item.get("page_id")
        } if isinstance(pages_raw, list) else {}
    )
    capabilities_raw = data.get("capabilities") or {}
    capabilities = (
        dict(capabilities_raw)
        if isinstance(capabilities_raw, Mapping)
        else {
            str(item.get("capability_id") or ""): dict(item)
            for item in capabilities_raw
            if isinstance(item, Mapping) and item.get("capability_id")
        } if isinstance(capabilities_raw, list) else {}
    )
    action_edges = [
        dict(item) for item in data.get("action_edges") or []
        if isinstance(item, Mapping)
    ]
    action_edge_ids = {
        str(item.get("action_edge_id") or "") for item in action_edges
        if item.get("action_edge_id")
    }
    verified_action_edges = {
        str(item.get("action_edge_id") or "") for item in action_edges
        if item.get("routing_verified") is True
    }
    action_edge_by_id = {
        str(item.get("action_edge_id") or ""): item
        for item in action_edges if item.get("action_edge_id")
    }
    catalog_memberships: Dict[str, List[tuple[str, str]]] = defaultdict(list)
    page_variants: Dict[str, Dict[str, Mapping[str, Any]]] = {}
    for catalog_page_id, raw_page in pages.items():
        if not isinstance(raw_page, Mapping):
            page_variants[str(catalog_page_id)] = {}
            continue
        raw_variants = raw_page.get("variants") or {}
        variants = (
            {str(key): value for key, value in raw_variants.items()
             if isinstance(value, Mapping)}
            if isinstance(raw_variants, Mapping)
            else {
                str(value.get("variant_id") or ""): value
                for value in raw_variants
                if isinstance(value, Mapping) and value.get("variant_id")
            } if isinstance(raw_variants, list) else {}
        )
        page_variants[str(catalog_page_id)] = variants
        for catalog_variant_id, raw_variant in variants.items():
            for member in raw_variant.get("state_ids") or []:
                catalog_memberships[str(member)].append((
                    str(catalog_page_id), str(catalog_variant_id)))
    return (pages, capabilities, action_edges, action_edge_ids,
            verified_action_edges, action_edge_by_id, catalog_memberships,
            page_variants)


def _check_schema_v3_pages(
    data, nodes, by_id, pages, page_variants, catalog_memberships, findings,
) -> None:
    if "transition_events" in data:
        findings.append(_finding(
            "ERROR", "duplicate_transition_event_ledger",
            "schema-v3 graph must store attempts under action_edges, not a second top-level transition_events ledger",
            scope="graph",
        ))
    for node in nodes:
        state_id = _state_id(node)
        page_id = str(node.get("page_id") or "")
        variant_id = str(node.get("variant_id") or "")
        if not page_id or not variant_id:
            findings.append(_finding(
                "ERROR", "missing_page_variant_identity",
                "schema-v3 execution node has no page_id/variant_id",
                scope="node", node_id=state_id,
            ))
        elif page_id not in pages:
            findings.append(_finding(
                "ERROR", "node_page_missing_from_catalog",
                "execution node references a page absent from the page catalog",
                scope="node", node_id=state_id,
                evidence={"page_id": page_id, "variant_id": variant_id},
            ))
        else:
            variant = page_variants.get(page_id, {}).get(variant_id)
            if not isinstance(variant, Mapping):
                findings.append(_finding(
                    "ERROR", "node_variant_missing_from_catalog",
                    "execution node references a variant absent from its page",
                    scope="node", node_id=state_id,
                    evidence={"page_id": page_id, "variant_id": variant_id},
                ))
            memberships = catalog_memberships.get(state_id, [])
            expected = (page_id, variant_id)
            if memberships.count(expected) != 1 or len(memberships) != 1:
                findings.append(_finding(
                    "ERROR", "stale_page_variant_membership",
                    "execution state must occur exactly once in its declared page/variant",
                    scope="node", node_id=state_id,
                    evidence={"expected": list(expected),
                              "memberships": [list(v) for v in memberships]},
                ))
    for member, memberships in catalog_memberships.items():
        if member not in by_id:
            findings.append(_finding(
                "ERROR", "catalog_variant_unknown_state",
                "page catalog variant references an unknown execution state",
                scope="graph",
                evidence={"state_id": member,
                          "memberships": [list(v) for v in memberships]},
            ))


def _check_schema_v3_action_edges(action_edges, by_id, findings) -> None:
    seen_attempt_indices: Dict[int, str] = {}
    non_routing = _FAILED_EDGE_OUTCOMES | {
        "attempted", "executed", "disabled", "failed", "failure",
        "error", "cancelled", "canceled", "prerequisite_cleanup",
    }
    for action_edge in action_edges:
        edge_id = str(action_edge.get("action_edge_id") or "")
        attempts = action_edge.get("attempts") or []
        if not edge_id or not isinstance(attempts, list) or not attempts:
            findings.append(_finding(
                "ERROR", "action_edge_without_attempt",
                "semantic action edge must own at least one executed attempt",
                scope="action_edge", evidence={"action_edge_id": edge_id},
            ))
            continue
        source = str(action_edge.get("source") or "")
        target = str(action_edge.get("target") or "")
        source_node = by_id.get(source)
        target_node = by_id.get(target) if target else None
        if source_node is None or (target and target_node is None):
            findings.append(_finding(
                "ERROR", "action_edge_unknown_endpoint",
                "semantic action edge references an unknown execution state",
                scope="action_edge",
                evidence={"action_edge_id": edge_id,
                          "source": source, "target": target},
            ))
        expected_identity = {
            "source_page_id": str((source_node or {}).get("page_id") or source),
            "source_variant_id": str((source_node or {}).get("variant_id") or source),
            "target_page_id": str((target_node or {}).get("page_id") or target),
            "target_variant_id": str((target_node or {}).get("variant_id") or target),
        }
        mismatched_identity = {
            key: {"stored": str(action_edge.get(key) or ""),
                  "expected": expected}
            for key, expected in expected_identity.items()
            if str(action_edge.get(key) or "") != expected
        }
        if mismatched_identity:
            findings.append(_finding(
                "ERROR", "action_edge_page_variant_mismatch",
                "action edge Page/Variant endpoints disagree with its execution nodes",
                scope="action_edge",
                evidence={"action_edge_id": edge_id,
                          "mismatches": mismatched_identity},
            ))
        for attempt in attempts:
            if not isinstance(attempt, Mapping):
                findings.append(_finding(
                    "ERROR", "malformed_action_attempt",
                    "action edge contains a non-object attempt",
                    scope="action_edge", evidence={"action_edge_id": edge_id},
                ))
                continue
            index = _safe_int(attempt.get("action_index"))
            owner = str(attempt.get("action_edge_id") or "")
            if owner != edge_id:
                findings.append(_finding(
                    "ERROR", "attempt_owner_mismatch",
                    "attempt action_edge_id does not match its owning edge",
                    scope="action_edge",
                    evidence={"action_edge_id": edge_id,
                              "attempt_owner": owner,
                              "action_index": index},
                ))
            if index is not None:
                prior_owner = seen_attempt_indices.get(index)
                if prior_owner is not None:
                    findings.append(_finding(
                        "ERROR", "duplicate_action_index",
                        "action_index must be unique across all attempts",
                        scope="action_edge",
                        evidence={"action_index": index,
                                  "owners": [prior_owner, edge_id]},
                    ))
                else:
                    seen_attempt_indices[index] = edge_id
            attempt_target = str(attempt.get("target") or "")
            if str(attempt.get("source") or "") != source \
                    or (attempt_target and target
                        and attempt_target != target):
                findings.append(_finding(
                    "ERROR", "attempt_endpoint_mismatch",
                    "attempt endpoints disagree with their owning action edge",
                    scope="action_edge",
                    evidence={"action_edge_id": edge_id,
                              "action_index": index},
                ))
        computed_routing = bool(target) and any(
            isinstance(attempt, Mapping)
            and attempt.get("committed") is True
            and attempt.get("landing_verified") is True
            and str(attempt.get("target") or "") == target
            and str(attempt.get("outcome") or "").strip().casefold()
            not in non_routing
            for attempt in attempts
        )
        if (action_edge.get("routing_verified") is True) != computed_routing:
            findings.append(_finding(
                "ERROR", "action_edge_routing_flag_mismatch",
                "routing_verified must be derived from committed verified attempts",
                scope="action_edge",
                evidence={"action_edge_id": edge_id,
                          "stored": action_edge.get("routing_verified"),
                          "computed": computed_routing},
            ))


def _matches_capability(action_edge, capability_page, source_refs) -> bool:
    if capability_page and str(
            action_edge.get("source_page_id") or "") != capability_page:
        return False
    if not source_refs:
        return True
    edge_variant = str(action_edge.get("source_variant_id") or "")
    edge_element = str(action_edge.get("element_id") or "")
    edge_label = _normalise(action_edge.get("element_label"))
    for source_ref in source_refs:
        ref_variant = str(source_ref.get("variant_id") or "")
        if ref_variant and ref_variant != edge_variant:
            continue
        ref_element = str(source_ref.get("element_id") or "")
        if edge_element and ref_element:
            if edge_element == ref_element:
                return True
            continue
        if edge_label and edge_label == _normalise(source_ref.get("element_label")):
            return True
    return False


def _check_schema_v3_routes_and_capabilities(
    edges, capabilities, action_edge_ids, verified_action_edges,
    action_edge_by_id, findings,
) -> None:
    for edge in edges:
        refs = edge.get("action_edge_ids")
        if not isinstance(refs, list):
            refs = [edge.get("action_edge_id")] if edge.get("action_edge_id") else []
        missing_refs = sorted(
            str(ref) for ref in refs if str(ref) not in action_edge_ids)
        if missing_refs:
            findings.append(_finding(
                "ERROR", "route_missing_action_edge",
                "topology edge references an unknown semantic action edge",
                scope="edge", source=edge.get("source"),
                target=edge.get("target"),
                evidence={"action_edge_ids": missing_refs},
            ))
    for capability_id, capability in capabilities.items():
        if not isinstance(capability, Mapping):
            continue
        if str(capability.get("status") or "") != "verified":
            continue
        refs = {
            str(value) for value in capability.get("action_edge_ids") or []
            if str(value)
        }
        if not refs or not refs.intersection(verified_action_edges):
            findings.append(_finding(
                "ERROR", "verified_capability_without_verified_action",
                "verified capability has no routing-verified action evidence",
                scope="capability",
                evidence={"capability_id": capability_id,
                              "action_edge_ids": sorted(refs)},
            ))
            continue
        source_refs = [
            item for item in capability.get("source_elements") or []
            if isinstance(item, Mapping)]
        capability_page = str(capability.get("page_id") or "")

        verified_refs = [
            action_edge_by_id[ref] for ref in refs
            if ref in verified_action_edges and ref in action_edge_by_id]
        if not any(_matches_capability(item, capability_page, source_refs) for item in verified_refs):
            findings.append(_finding(
                "ERROR", "verified_capability_foreign_action_evidence",
                "verified capability evidence does not match its source page/variant/element",
                scope="capability",
                evidence={"capability_id": capability_id,
                          "action_edge_ids": sorted(refs)},
            ))


def _check_schema_v3_invariants(data, nodes, edges, by_id, findings) -> None:
    if (_safe_int(data.get("graph_schema_version")) or 0) < 3:
        return
    (pages, capabilities, action_edges, action_edge_ids,
     verified_action_edges, action_edge_by_id, catalog_memberships,
     page_variants) = _schema_v3_catalogs(data)
    _check_schema_v3_pages(
        data, nodes, by_id, pages, page_variants, catalog_memberships, findings)
    _check_schema_v3_action_edges(action_edges, by_id, findings)
    _check_schema_v3_routes_and_capabilities(
        edges, capabilities, action_edge_ids, verified_action_edges,
        action_edge_by_id, findings)


def _check_open_stateful_mutations(ledger_events, findings) -> None:
    open_stateful_mutations: Dict[str, Dict[str, Any]] = {}
    for event in ledger_events:
        evidence = event.get("evidence") or {}
        if not isinstance(evidence, Mapping) or not evidence.get("stateful"):
            continue
        mutation_id = str(evidence.get("mutation_id") or "")
        purpose = str(evidence.get("purpose") or "").strip().casefold()
        if not mutation_id:
            findings.append(_finding(
                "ERROR", "stateful_mutation_missing_id",
                "stateful action event has no mutation_id",
                scope="graph",
                evidence={"action_index": event.get("action_index")},
            ))
            continue
        if purpose == "probe" and event.get("committed"):
            open_stateful_mutations[mutation_id] = {
                "action_index": event.get("action_index"),
                "source": event.get("source"),
                "target": event.get("target"),
                "state_key": evidence.get("state_key"),
                "before_value": evidence.get("before_value"),
                "after_value": evidence.get("after_value"),
            }
        elif purpose == "restore" and event.get("committed"):
            open_stateful_mutations.pop(mutation_id, None)
    for mutation_id, mutation in open_stateful_mutations.items():
        findings.append(_finding(
            "ERROR", "stateful_mutation_unrestored",
            "functional-state probe has no committed inverse restoration",
            scope="graph",
            evidence={"mutation_id": mutation_id, **mutation},
        ))


def _check_pending_shared_controls(nodes):
    shared_key_nodes: Dict[tuple[str, str], set[str]] = defaultdict(set)
    shared_key_owner: Dict[tuple[str, str], str] = {}
    for node in nodes:
        peer_id = _state_id(node)
        for item in node.get("elements") or []:
            if not isinstance(item, Mapping) or not _is_navigation(item):
                continue
            key = (
                str(item.get("region_id") or ""),
                _normalise(item.get("name")),
            )
            if not peer_id or not all(key):
                continue
            shared_key_nodes[key].add(peer_id)
            shared_key_owner.setdefault(key, peer_id)
    return shared_key_nodes, shared_key_owner


def _is_non_owner_shared_control(
    node_id, element, shared_key_nodes, shared_key_owner,
) -> bool:
    key = (str(element.get("region_id") or ""), _normalise(element.get("name")))
    return (len(shared_key_nodes.get(key, set())) > 1
            and shared_key_owner.get(key) != node_id)


def _control_outcome_scope(
    node_id, element, nodes, edges, by_id, outgoing, ledger_events,
    abnormal_records,
) -> str:
    direct_records = [
        *outgoing.get(node_id, []),
        *(item for item in ledger_events
          if str(item.get("source") or "") == node_id),
        *(item for item in abnormal_records
          if str(item.get("state_id") or "") == node_id),
    ]
    if any(_record_matches_element(item, element) for item in direct_records):
        return "direct"
    region_id = str(element.get("region_id") or "")
    label = _normalise(element.get("name"))
    if not region_id or not label:
        return ""
    for peer in nodes:
        for peer_element in peer.get("elements") or []:
            if not isinstance(peer_element, Mapping):
                continue
            if (peer_element.get("selected")
                    and str(peer_element.get("region_id") or "") == region_id
                    and _normalise(peer_element.get("name")) == label):
                return "shared"
    for edge in edges:
        source_node = by_id.get(str(edge.get("source") or ""), {})
        source_element = _find_element(source_node, edge)
        if (str(source_element.get("region_id") or "") == region_id
                and _normalise(source_element.get("name")) == label):
            return "shared"
    if any(str(item.get("region_id") or "") == region_id
           and _normalise(item.get("element_name")) == label
           for item in abnormal_records):
        return "shared"
    return ""


def _control_has_outcome(
    node_id, element, nodes, edges, by_id, outgoing, ledger_events,
    abnormal_records,
) -> bool:
    return bool(_control_outcome_scope(
        node_id, element, nodes, edges, by_id, outgoing, ledger_events,
        abnormal_records))


def _collapsed_group_has_representative(
    node_id, element, navigation, nodes, edges, by_id, outgoing,
    ledger_events, abnormal_records,
) -> bool:
    group = str(element.get("group") or "").strip()
    if not group:
        return False
    peers = [item for item in navigation
             if str(item.get("group") or "").strip() == group]
    for peer in peers:
        if (peer.get("selected")
                or str(peer.get("abnormal_reason") or "").strip()
                or _permission_blocked(by_id.get(node_id, {}), peer)
                or _control_has_outcome(
                    node_id, peer, nodes, edges, by_id, outgoing,
                    ledger_events, abnormal_records)):
            return True
        if not peer.get("visited"):
            return True
    return False


def _audit_nodes(
    nodes, edges, by_id, incoming, outgoing, ledger_events,
    abnormal_records, shared_key_nodes, shared_key_owner, *,
    graph_path, workspace, findings,
):
    node_reports, node_report_by_id = [], {}
    for ordinal, node in enumerate(nodes):
        node_id = _state_id(node) or f"<missing-id:{ordinal}>"
        screenshot_path = _resolve_screenshot(
            node.get("screenshot_path"),
            graph_path=graph_path,
            workspace=workspace,
            node_id=node_id,
        )
        screenshot = _screenshot_evidence(screenshot_path, node.get("screenshot_path"))
        element_items = [
            dict(item) for item in (node.get("elements") or []) if isinstance(item, Mapping)
        ]
        nav = [item for item in element_items if _is_navigation(item)]
        # Shared regions (Settings sidebar, tab bars) are explored once for
        # the whole graph.  Do not report the same control as pending on an
        # older node merely because that immutable node snapshot predates a
        # successful click from a later sibling surface.
        pending_nav = [
            item for item in _unexplored_navigation(node, nav)
            if not _control_has_outcome(node_id, item, nodes, edges, by_id, outgoing, ledger_events, abnormal_records)
            and not _is_non_owner_shared_control(node_id, item, shared_key_nodes, shared_key_owner)
        ]
        report = {
            "node_id": node_id,
            "page_name": str(node.get("page_name") or ""),
            "correctness": "unknown",
            "coverage_status": "unknown",
            "confidence": 0.0,
            "evidence": {
                "screenshot": screenshot,
                "elements": {
                    "count": len(element_items),
                    "navigation_count": len(nav),
                    "visited_navigation": sum(bool(item.get("visited")) for item in nav),
                    "pending_navigation": len(pending_nav),
                    "items": [_compact_element(item) for item in element_items],
                },
                "incoming_action_indexes": [item.get("action_index") for item in incoming[node_id]],
                "outgoing_action_indexes": [item.get("action_index") for item in outgoing[node_id]],
            },
            "findings": [],
            "vlm_evaluation": None,
        }
        node_reports.append(report)
        node_report_by_id[node_id] = report

        if node_id.startswith("<missing-id:"):
            _append_report_finding(
                report,
                findings,
                _finding(
                    "ERROR",
                    "missing_node_id",
                    "node has neither state_id nor id",
                    scope="node",
                    node_id=node_id,
                ),
            )
        if not str(node.get("page_name") or "").strip():
            _append_report_finding(
                report,
                findings,
                _finding(
                    "WARN",
                    "missing_page_name",
                    "node has no semantic page_name",
                    scope="node",
                    node_id=node_id,
                ),
            )
        if not screenshot.get("exists"):
            _append_report_finding(
                report,
                findings,
                _finding(
                    "ERROR",
                    "missing_screenshot",
                    "node has no readable screenshot path",
                    scope="node",
                    node_id=node_id,
                    evidence={"declared_path": node.get("screenshot_path")},
                ),
            )
        elif not screenshot.get("readable"):
            _append_report_finding(
                report,
                findings,
                _finding(
                    "ERROR",
                    "unreadable_screenshot",
                    str(screenshot.get("error") or "unreadable image"),
                    scope="node",
                    node_id=node_id,
                    evidence=screenshot,
                ),
            )
        elif int(screenshot.get("width") or 0) < 320 or int(screenshot.get("height") or 0) < 240:
            _append_report_finding(
                report,
                findings,
                _finding(
                    "WARN",
                    "small_screenshot",
                    "screenshot is too small for strong semantic evidence",
                    scope="node",
                    node_id=node_id,
                    evidence={
                        "width": screenshot.get("width"),
                        "height": screenshot.get("height"),
                    },
                ),
            )
        if not element_items:
            _append_report_finding(
                report,
                findings,
                _finding(
                    "WARN",
                    "missing_element_evidence",
                    "node has no grounded element evidence",
                    scope="node",
                    node_id=node_id,
                ),
            )
        if pending_nav:
            names = [str(item.get("name") or "?") for item in pending_nav]
            _append_report_finding(
                report,
                findings,
                _finding(
                    "WARN",
                    "node_exploration_incomplete",
                    f"{len(names)}/{len(nav)} navigation controls are not explored",
                    scope="node",
                    node_id=node_id,
                    evidence={"unvisited": names},
                ),
            )
        unexplained_visited = [
            item for item in nav
            if item.get("visited")
            and not item.get("selected")
            and not str(item.get("abnormal_reason") or "")
            and not _permission_blocked(node, item)
            and not _control_has_outcome(node_id, item, nodes, edges, by_id, outgoing, ledger_events, abnormal_records)
            and not _collapsed_group_has_representative(node_id, item, nav, nodes, edges, by_id, outgoing, ledger_events, abnormal_records)
        ]
        if unexplained_visited:
            _append_report_finding(
                report,
                findings,
                _finding(
                    "WARN",
                    "visited_control_without_outcome",
                    "navigation control is marked visited but has no edge, "
                    "action event, or terminal abnormal outcome",
                    scope="node",
                    node_id=node_id,
                    evidence={
                        "controls": [
                            str(item.get("name") or "?")
                            for item in unexplained_visited
                        ]
                    },
                ),
            )
        stale_unvisited = [
            item for item in nav
            if not item.get("visited")
            and not item.get("selected")
            and _control_outcome_scope(
                node_id, item, nodes, edges, by_id, outgoing,
                ledger_events, abnormal_records,
            ) == "direct"
        ]
        if stale_unvisited:
            _append_report_finding(
                report,
                findings,
                _finding(
                    "WARN",
                    "outcome_control_marked_unvisited",
                    "an edge/event exists for a navigation control whose "
                    "node artifact still says unvisited",
                    scope="node",
                    node_id=node_id,
                    evidence={
                        "controls": [
                            str(item.get("name") or "?")
                            for item in stale_unvisited
                        ]
                    },
                ),
            )
        screen_text = " ".join(
            [
                str(node.get("page_name") or ""),
                *(str(item.get("name") or "") for item in element_items),
                *(str(item.get("abnormal_detail") or "") for item in element_items),
            ]
        ).casefold()
        suspicious = [term for term in _SUSPICIOUS_SCREEN_TERMS if term in screen_text]
        if suspicious:
            _append_report_finding(
                report,
                findings,
                _finding(
                    "WARN",
                    "suspicious_screen_text",
                    "possible desktop/crash/error surface in application graph",
                    scope="node",
                    node_id=node_id,
                    evidence={"matched_terms": suspicious},
                ),
            )
        observed_names = _explicit_page_names(node)
        if len(observed_names) > 1:
            _append_report_finding(
                report,
                findings,
                _finding(
                    "ERROR",
                    "overmerge_page_identity_conflict",
                    "one node contains observations with conflicting page identities",
                    scope="node",
                    node_id=node_id,
                    evidence={"normalised_page_names": sorted(observed_names)},
                ),
            )
    return node_reports, node_report_by_id


def _audit_cross_node_duplicates(
    node_reports, node_report_by_id, by_id, incoming, findings,
) -> None:
    by_sha: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for report in node_reports:
        sha = report["evidence"]["screenshot"].get("sha256")
        if sha:
            by_sha[str(sha)].append(report)
    for sha, group in by_sha.items():
        if len(group) < 2:
            continue
        ids = [item["node_id"] for item in group]
        findings.append(
            _finding(
                "WARN",
                "duplicate_visual_nodes",
                f"{len(ids)} nodes use byte-identical screenshot evidence",
                evidence={"nodes": ids, "sha256": sha},
            )
        )
        for report in group:
            _append_report_finding(
                report,
                findings,
                _finding(
                    "WARN",
                    "duplicate_node_visual",
                    "another node has the same screenshot evidence",
                    scope="node",
                    node_id=report["node_id"],
                    evidence={"peers": [item for item in ids if item != report["node_id"]]},
                ),
            )

    for left_index, left_report in enumerate(node_reports):
        left_hash = left_report["evidence"]["screenshot"].get("dhash")
        if not left_hash:
            continue
        left_node = by_id.get(left_report["node_id"], {})
        for right_report in node_reports[left_index + 1 :]:
            right_hash = right_report["evidence"]["screenshot"].get("dhash")
            if not right_hash or left_report["page_name"] != right_report["page_name"]:
                continue
            hash_distance = _hamming_hex(str(left_hash), str(right_hash))
            if hash_distance > 2:
                continue
            right_node = by_id.get(right_report["node_id"], {})
            left_selected = _selected_signature(left_node)
            right_selected = _selected_signature(right_node)
            if left_selected and right_selected and left_selected != right_selected:
                continue
            similarity = _jaccard(_functional_signature(left_node), _functional_signature(right_node))
            # Equal/near-equal images with the same page identity are still a
            # useful over-splitting clue when perception produced different
            # controls.  That disagreement lowers certainty; it should not
            # suppress the evidence completely.
            if similarity < 0.45 and hash_distance > 0:
                continue
            for report, peer in (
                (left_report, right_report["node_id"]),
                (right_report, left_report["node_id"]),
            ):
                _append_report_finding(
                    report,
                    findings,
                    _finding(
                        "WARN",
                        "near_duplicate_function_node",
                        "same-page visual evidence is near-identical to another function node",
                        scope="node",
                        node_id=report["node_id"],
                        evidence={
                            "peer": peer,
                            "dhash_distance": hash_distance,
                            "functional_jaccard": round(similarity, 4),
                        },
                    ),
                )

    # Incoming edge target names provide an independent over-merge clue.
    for node_id, incident in incoming.items():
        expected = {
            _normalise(item.get("target_page_name"))
            for item in incident
            if _normalise(item.get("target_page_name"))
        }
        if len(expected) > 1 and node_id in node_report_by_id:
            _append_report_finding(
                node_report_by_id[node_id],
                findings,
                _finding(
                    "WARN",
                    "possible_overmerge",
                    "incoming verified transitions disagree on the target page identity",
                    scope="node",
                    node_id=node_id,
                    evidence={"incoming_target_page_names": sorted(expected)},
                ),
            )


def _build_edge_report(index, edge, by_id, node_report_by_id):
    source = str(edge.get("source") or "")
    target = str(edge.get("target") or "")
    source_node = by_id.get(source, {})
    target_node = by_id.get(target, {})
    element = _find_element(source_node, edge)
    edge_id = str(edge.get("event_id") or edge.get("action_index") or f"edge:{index}")
    report = {
        "edge_id": edge_id,
        "edge_index": index,
        "action_index": edge.get("action_index"),
        "source": source,
        "target": target,
        "element_label": str(edge.get("element_label") or ""),
        "correctness": "unknown",
        "confidence": 0.0,
        "evidence": {
            "source_screenshot": (
                node_report_by_id.get(source, {}).get("evidence", {}).get("screenshot")
            ),
            "target_screenshot": (
                node_report_by_id.get(target, {}).get("evidence", {}).get("screenshot")
            ),
            "source_element": _compact_element(element),
            "source_element_bbox": (
                _as_bbox(element.get("bbox_xywh"), xywh=True)
                or _as_bbox(element.get("bbox_xyxy"))
                or _as_bbox(element.get("bbox"), xywh=True)
            ),
            "region_bbox": _region_bbox(edge, element),
            "resolved_point": _executed_point(edge),
            "landing_verified": edge.get("landing_verified"),
            "effect_verdict": edge.get("effect_verdict"),
            "target_page_name": edge.get("target_page_name"),
            "semantic_description": edge.get("semantic_description"),
        },
        "findings": [],
        "vlm_evaluation": None,
    }
    return report, source, target, source_node, target_node, element


def _audit_edge(
    index, edge, report, source, target, source_node, target_node,
    element, by_id, findings,
) -> None:

    if not source or source not in by_id:
        _append_report_finding(
            report,
            findings,
            _finding(
                "ERROR",
                "edge_source_missing",
                "edge references a source node absent from the graph",
                scope="edge",
                edge_index=index,
                source=source,
                target=target,
            ),
        )
    if not target or target not in by_id:
        _append_report_finding(
            report,
            findings,
            _finding(
                "ERROR",
                "edge_target_missing",
                "edge references a target node absent from the graph",
                scope="edge",
                edge_index=index,
                source=source,
                target=target,
            ),
        )
    verdict = str(edge.get("effect_verdict") or edge.get("outcome") or "").casefold()
    if verdict in _FAILED_EDGE_OUTCOMES:
        _append_report_finding(
            report,
            findings,
            _finding(
                "ERROR",
                "failed_outcome_has_topology_edge",
                f"outcome {verdict!r} must remain an action event, not a success edge",
                scope="edge",
                edge_index=index,
                source=source,
                target=target,
            ),
        )
    if edge.get("landing_verified") is False:
        _append_report_finding(
            report,
            findings,
            _finding(
                "ERROR",
                "landing_rejected_but_edge_committed",
                "edge was committed although landing verification is false",
                scope="edge",
                edge_index=index,
                source=source,
                target=target,
            ),
        )
    elif edge.get("landing_verified") is not True:
        _append_report_finding(
            report,
            findings,
            _finding(
                "WARN",
                "landing_unverified",
                "topology edge lacks an explicit successful landing verdict",
                scope="edge",
                edge_index=index,
                source=source,
                target=target,
            ),
        )
    expected_page = edge.get("target_page_name")
    actual_page = target_node.get("page_name") if target_node else None
    if expected_page and actual_page and not _labels_agree(expected_page, actual_page):
        _append_report_finding(
            report,
            findings,
            _finding(
                "WARN",
                "landing_page_name_mismatch",
                "edge target_page_name conflicts with target node page_name",
                scope="edge",
                edge_index=index,
                source=source,
                target=target,
                evidence={"expected": expected_page, "actual": actual_page},
            ),
        )
    if source_node and not element:
        _append_report_finding(
            report,
            findings,
            _finding(
                "WARN",
                "edge_source_element_missing",
                "edge label/id cannot be tied to source element evidence",
                scope="edge",
                edge_index=index,
                source=source,
                target=target,
                evidence={
                    "element_id": edge.get("element_id"),
                    "element_label": edge.get("element_label"),
                },
            ),
        )
    elif (element and edge.get("element_label")
          and str(edge.get("transition_kind") or "") != "stateful_surface"
          and not _labels_agree(
        element.get("name"), edge.get("element_label")
    )):
        _append_report_finding(
            report,
            findings,
            _finding(
                "ERROR",
                "edge_element_label_mismatch",
                "edge label does not describe the referenced source element",
                scope="edge",
                edge_index=index,
                source=source,
                target=target,
                evidence={
                    "source_element_name": element.get("name"),
                    "edge_element_label": edge.get("element_label"),
                },
            ),
        )

    modal = _modal_bbox(source_node)
    element_center = _as_point(element.get("center")) if element else None
    element_region = str(element.get("region") or "").casefold()
    explicit_background = any(
        marker in element_region for marker in ("background", "underlay", "underlying")
    ) or str(element.get("surface") or "").casefold() in {"background", "underlying"}
    if modal and element and (explicit_background or not _inside(element_center, modal)):
        _append_report_finding(
            report,
            findings,
            _finding(
                "ERROR",
                "modal_background_leakage",
                "edge acts on an element outside the active modal surface",
                scope="edge",
                edge_index=index,
                source=source,
                target=target,
                evidence={
                    "modal_bbox": modal,
                    "element_center": element_center,
                    "element_region": element.get("region"),
                    "element_name": element.get("name"),
                },
            ),
        )

    success = edge.get("landing_verified") is True or verdict in _SUCCESS_OUTCOMES
    if success and element and _permission_blocked(source_node, element):
        _append_report_finding(
            report,
            findings,
            _finding(
                "ERROR",
                "permission_recorded_as_success",
                "a disabled/permission-gated control was recorded as a successful function edge",
                scope="edge",
                edge_index=index,
                source=source,
                target=target,
                evidence={
                    "element": _compact_element(element),
                    "effect_verdict": edge.get("effect_verdict"),
                    "landing_verified": edge.get("landing_verified"),
                },
            ),
        )
    elif success and element and _possible_permission_blocked(
            source_node, element):
        _append_report_finding(
            report,
            findings,
            _finding(
                "WARN",
                "possible_permission_gated_success",
                "legacy graph lacks explicit enabled/permission fields; "
                "the clicked control overlaps a visible permission gate",
                scope="edge",
                edge_index=index,
                source=source,
                target=target,
                evidence={
                    "element": _compact_element(element),
                    "effect_verdict": edge.get("effect_verdict"),
                    "landing_verified": edge.get("landing_verified"),
                },
            ),
        )
    clicked_name = str(element.get("name") or edge.get("element_label") or "").casefold()
    clicked_unlock = any(
        term in clicked_name
        for term in ("unlock", "authenticate", "authorize", "解锁", "认证", "授权")
    )
    if success and clicked_unlock and target_node and _has_permission_gate(target_node):
        _append_report_finding(
            report,
            findings,
            _finding(
                "ERROR",
                "permission_gate_not_cleared",
                "unlock/authentication action was recorded as success but the target remains locked",
                scope="edge",
                edge_index=index,
                source=source,
                target=target,
                evidence={
                    "element_name": element.get("name") or edge.get("element_label"),
                    "target_page_name": target_node.get("page_name"),
                },
            ),
        )

    point = _executed_point(edge)
    region = _region_bbox(edge, element)
    if point and region and not _inside(point, region):
        _append_report_finding(
            report,
            findings,
            _finding(
                "ERROR",
                "retarget_outside_region",
                "executed/retargeted click point lies outside its source region",
                scope="edge",
                edge_index=index,
                source=source,
                target=target,
                evidence={"executed_point": point, "region_bbox": region},
            ),
        )


def _audit_edges(edges, by_id, node_report_by_id, findings):
    edge_reports = []
    for index, edge in enumerate(edges):
        values = _build_edge_report(index, edge, by_id, node_report_by_id)
        report, source, target, source_node, target_node, element = values
        edge_reports.append(report)
        _audit_edge(
            index, edge, report, source, target, source_node, target_node,
            element, by_id, findings)
    return edge_reports


def _summarise_findings(
    data, path, nodes, edges, node_reports, edge_reports, findings,
    ledger, completion_certificate, assessment_confidence,
):
    severity = Counter(item["severity"] for item in findings)
    error_penalty = min(70.0, 12.0 * severity["ERROR"])
    warning_penalty = min(25.0, 4.0 * severity["WARN"])
    info_penalty = min(5.0, 0.5 * severity["INFO"])
    score = round(max(0.0, 100.0 - error_penalty - warning_penalty - info_penalty), 2)
    status = "error" if severity["ERROR"] else "warn" if severity["WARN"] else "pass"
    coverage_counts = Counter(item["coverage_status"] for item in node_reports)
    node_correctness = Counter(item["correctness"] for item in node_reports)
    edge_correctness = Counter(item["correctness"] for item in edge_reports)

    return {
        "schema_version": REPORT_SCHEMA,
        "read_only": True,
        "graph_path": str(path) if path else None,
        "app_name": data.get("app_name"),
        "status": status,
        "score": score,
        "confidence": assessment_confidence,
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "action_counter": _safe_int(data.get("action_counter")) or 0,
            "stop_reason": data.get("stop_reason"),
            "errors": severity["ERROR"],
            "warnings": severity["WARN"],
            "infos": severity["INFO"],
            "node_correctness": dict(node_correctness),
            "edge_correctness": dict(edge_correctness),
            "coverage_statuses": {
                status_name: coverage_counts.get(status_name, 0)
                for status_name in sorted(COVERAGE_STATUSES)
            },
        },
        "ledger": ledger,
        "completion_certificate": completion_certificate,
        "nodes": node_reports,
        "edges": edge_reports,
        "findings": findings,
    }



class GraphQualityAgent:
    """Audit a visual traversal graph without mutating it.

    Args:
        vlm_judge: callable or object with ``judge(request)``.  It receives only a
            structured request and may load the referenced screenshots itself.
        min_vlm_confidence: semantic decisions below this threshold are retained
            as evidence but cannot override deterministic status.
        workspace: base directory used to resolve repository-relative screenshots.
    """

    def __init__(
        self,
        vlm_judge: Optional[VLMJudge | Callable[[Mapping[str, Any]], Any]] = None,
        *,
        min_vlm_confidence: float = 0.70,
        workspace: str | Path | None = None,
    ) -> None:
        self.vlm_judge = vlm_judge
        self.min_vlm_confidence = _clamp_confidence(min_vlm_confidence)
        self.workspace = Path(workspace).resolve() if workspace else Path.cwd().resolve()

    def evaluate(self, graph_path: str | Path) -> Dict[str, Any]:
        """Read and audit ``graph_path``; never write to it or its screenshots."""
        path = Path(graph_path).resolve()
        try:
            graph = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return self._invalid_report(path, exc)
        if not isinstance(graph, Mapping):
            return self._invalid_report(path, ValueError("graph root must be a JSON object"))
        return self.evaluate_data(graph, graph_path=path)

    def evaluate_data(
        self,
        graph: Mapping[str, Any],
        *,
        graph_path: str | Path | None = None,
    ) -> Dict[str, Any]:
        """Audit an in-memory graph defensively; the supplied mapping is untouched."""
        data: Dict[str, Any] = copy.deepcopy(dict(graph))
        path = Path(graph_path).resolve() if graph_path else None
        nodes = _nodes(data)
        edges = _edges(data)
        by_id = {_state_id(node): node for node in nodes if _state_id(node)}
        findings: List[Dict[str, Any]] = []

        from gui_rewalk.src.core.graph.traversal_completion import (
            evaluate_traversal_completion,
        )
        completion_certificate = evaluate_traversal_completion(data)
        if completion_certificate.get("status") != "certified":
            failed_checks = [
                check_id for check_id, check in
                completion_certificate.get("checks", {}).items()
                if check.get("passed") is not True
            ]
            findings.append(_finding(
                "ERROR", "traversal_completion_incomplete",
                "graph does not satisfy the shared traversal completion certificate",
                scope="graph",
                evidence={"failed_checks": failed_checks},
            ))
        if not nodes:
            findings.append(
                _finding("ERROR", "no_nodes", "graph has no visual nodes"))

        incoming: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        outgoing: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            incoming[str(edge.get("target") or "")].append(edge)
            outgoing[str(edge.get("source") or "")].append(edge)
        _ledger_key, ledger_events = self._event_ledger(data)
        abnormal_records = [
            item for item in data.get("abnormal_buttons") or []
            if isinstance(item, Mapping)
        ]
        _check_schema_v3_invariants(data, nodes, edges, by_id, findings)
        _check_open_stateful_mutations(ledger_events, findings)
        shared_key_nodes, shared_key_owner = _check_pending_shared_controls(nodes)
        node_reports, node_report_by_id = _audit_nodes(
            nodes, edges, by_id, incoming, outgoing, ledger_events,
            abnormal_records, shared_key_nodes, shared_key_owner,
            graph_path=path, workspace=self.workspace, findings=findings,
        )
        _audit_cross_node_duplicates(
            node_reports, node_report_by_id, by_id, incoming, findings)
        edge_reports = _audit_edges(edges, by_id, node_report_by_id, findings)
        ledger = self._audit_action_ledger(data, edges, findings)
        self._apply_vlm_review(
            node_reports, edge_reports, by_id, incoming, outgoing, findings)
        assessment_confidence = self._overall_confidence(
            node_reports, edge_reports, ledger)
        return _summarise_findings(
            data, path, nodes, edges, node_reports, edge_reports, findings,
            ledger, completion_certificate, assessment_confidence,
        )

    def _apply_vlm_review(
        self, node_reports, edge_reports, by_id, incoming, outgoing, findings,
    ) -> None:
        for report in node_reports:
            node = by_id.get(report["node_id"], {})
            nav = [item for item in node.get("elements") or [] if isinstance(item, Mapping) and _is_navigation(item)]
            baseline_coverage = _node_baseline_coverage(
                node,
                screenshot_ok=bool(
                    report["evidence"]["screenshot"].get("exists")
                    and report["evidence"]["screenshot"].get("readable")
                ),
                nav=nav,
                node_findings=report["findings"],
            )
            report["correctness"] = _correctness(report["findings"])
            report["coverage_status"] = baseline_coverage
            report["confidence"] = self._node_rule_confidence(report)
            if self.vlm_judge:
                request = self._node_vlm_request(report, incoming[report["node_id"]], outgoing[report["node_id"]])
                self._apply_vlm(report, request, is_node=True, global_findings=findings)

        for report in edge_reports:
            report["correctness"] = _correctness(report["findings"])
            endpoint_evidence = bool(
                report["evidence"].get("source_screenshot")
                and report["evidence"].get("target_screenshot")
            )
            report["confidence"] = round(
                min(0.98, 0.70 + (0.15 if endpoint_evidence else 0.0) + (0.10 if report["evidence"].get("source_element") else 0.0)),
                4,
            )
            if self.vlm_judge:
                request = self._edge_vlm_request(report)
                self._apply_vlm(report, request, is_node=False, global_findings=findings)


    def _invalid_report(self, path: Path, exc: Exception) -> Dict[str, Any]:
        finding = _finding("ERROR", "invalid_graph_json", f"{type(exc).__name__}: {exc}")
        return {
            "schema_version": REPORT_SCHEMA,
            "read_only": True,
            "graph_path": str(path),
            "app_name": None,
            "status": "error",
            "score": 0.0,
            "confidence": 1.0,
            "summary": {
                "nodes": 0,
                "edges": 0,
                "action_counter": 0,
                "errors": 1,
                "warnings": 0,
                "infos": 0,
                "node_correctness": {},
                "edge_correctness": {},
                "coverage_statuses": {
                    item: 0 for item in sorted(COVERAGE_STATUSES)
                },
            },
            "ledger": {"present": False, "history_status": "unavailable"},
            "nodes": [],
            "edges": [],
            "findings": [finding],
        }

    @staticmethod
    def _node_rule_confidence(report: Mapping[str, Any]) -> float:
        screenshot = report.get("evidence", {}).get("screenshot", {})
        elements = report.get("evidence", {}).get("elements", {})
        confidence = 0.55
        confidence += 0.25 if screenshot.get("readable") else 0.0
        confidence += 0.10 if int(elements.get("count") or 0) else 0.0
        confidence += 0.05 if report.get("page_name") else 0.0
        confidence += 0.05 if not report.get("findings") else 0.0
        return round(min(0.98, confidence), 4)

    def _invoke_vlm(self, request: Mapping[str, Any]) -> Any:
        judge = self.vlm_judge
        if judge is None:
            return None
        method = getattr(judge, "judge", None)
        return method(request) if callable(method) else judge(request)  # type: ignore[misc]

    def _apply_vlm(
        self,
        report: Dict[str, Any],
        request: Mapping[str, Any],
        *,
        is_node: bool,
        global_findings: List[Dict[str, Any]],
    ) -> None:
        try:
            raw = self._invoke_vlm(request)
            if isinstance(raw, str):
                raw = json.loads(raw)
            if not isinstance(raw, Mapping):
                raise ValueError("VLM judge must return an object or JSON object string")
            confidence = _clamp_confidence(raw.get("confidence"))
            reasons = raw.get("reasons") or []
            evidence = raw.get("evidence") or []
            if isinstance(reasons, str):
                reasons = [reasons]
            if isinstance(evidence, str):
                evidence = [evidence]
            result = {
                "schema_version": VLM_RESPONSE_SCHEMA,
                "received_schema_version": str(raw.get("schema_version") or ""),
                "correctness": str(raw.get("correctness") or "unknown").casefold(),
                "coverage_status": str(raw.get("coverage_status") or "unknown").casefold(),
                "confidence": confidence,
                "reasons": [str(item) for item in reasons],
                "evidence": [str(item) for item in evidence],
                "accepted": False,
                "applied_fields": [],
            }
            if result["correctness"] not in CORRECTNESS_VALUES:
                result["correctness"] = "unknown"
            if result["coverage_status"] not in COVERAGE_STATUSES:
                result["coverage_status"] = "unknown"
            has_explanation = bool(result["reasons"] or result["evidence"])
            accepted = confidence >= self.min_vlm_confidence and has_explanation
            # "unsupported" is an assertion of absence.  It needs both high
            # confidence and concrete evidence; a weak judge must leave unknown.
            if is_node and result["coverage_status"] == "unsupported" and not accepted:
                result["coverage_status"] = "unknown"
            result["accepted"] = accepted
            report["vlm_evaluation"] = result
            if accepted:
                # Semantic review may discover an error, but cannot erase a
                # deterministic integrity failure (missing evidence, invalid
                # endpoints, an out-of-region click, and so on).
                if report.get("correctness") != "incorrect" or result["correctness"] == "incorrect":
                    report["correctness"] = result["correctness"]
                    result["applied_fields"].append("correctness")
                if is_node:
                    hard_coverage_codes = {
                        "missing_screenshot",
                        "unreadable_screenshot",
                        "missing_element_evidence",
                        "node_exploration_incomplete",
                        "visited_control_without_outcome",
                        "outcome_control_marked_unvisited",
                        "overmerge_page_identity_conflict",
                    }
                    hard_gap = any(
                        item.get("code") in hard_coverage_codes
                        for item in report.get("findings") or []
                    )
                    baseline = str(report.get("coverage_status") or "unknown")
                    proposed = result["coverage_status"]
                    can_apply_coverage = not (
                        proposed == "verified" and hard_gap
                    ) and not (
                        baseline in {"blocked", "conditional"}
                        and proposed in {"verified", "unsupported"}
                    )
                    if can_apply_coverage:
                        report["coverage_status"] = proposed
                        result["applied_fields"].append("coverage_status")
                report["confidence"] = round(
                    0.4 * float(report.get("confidence") or 0.0) + 0.6 * confidence, 4
                )
        except Exception as exc:
            finding = _finding(
                "WARN",
                "vlm_judge_error",
                f"{type(exc).__name__}: {exc}",
                scope="node" if is_node else "edge",
                node_id=report.get("node_id") if is_node else None,
                edge_index=report.get("edge_index") if not is_node else None,
            )
            report["findings"].append(finding)
            global_findings.append(finding)
            report["vlm_evaluation"] = {
                "schema_version": VLM_RESPONSE_SCHEMA,
                "accepted": False,
                "error": finding["message"],
            }

    @staticmethod
    def _node_vlm_request(
        report: Mapping[str, Any],
        incoming: Iterable[Mapping[str, Any]],
        outgoing: Iterable[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "schema_version": VLM_REQUEST_SCHEMA,
            "task": "judge_node_semantics_and_function_coverage",
            "policy": {
                "node_identity": "one stable operation surface with one available-function set",
                "coverage_values": sorted(COVERAGE_STATUSES),
                "correctness_values": sorted(CORRECTNESS_VALUES),
                "unsupported_rule": "use unsupported only with visible evidence that the function is absent; otherwise unknown",
                "do_not_modify_graph": True,
            },
            "evidence": {
                "node": {
                    "node_id": report.get("node_id"),
                    "page_name": report.get("page_name"),
                    "screenshot": report.get("evidence", {}).get("screenshot"),
                    "elements": report.get("evidence", {}).get("elements", {}).get("items", []),
                },
                "incoming_edges": [
                    {
                        "source": item.get("source"),
                        "element_label": item.get("element_label"),
                        "target_page_name": item.get("target_page_name"),
                        "landing_verified": item.get("landing_verified"),
                    }
                    for item in incoming
                ],
                "outgoing_edges": [
                    {
                        "target": item.get("target"),
                        "element_label": item.get("element_label"),
                        "target_page_name": item.get("target_page_name"),
                        "landing_verified": item.get("landing_verified"),
                    }
                    for item in outgoing
                ],
                "rule_findings": list(report.get("findings") or []),
            },
            "response_schema": {
                "schema_version": VLM_RESPONSE_SCHEMA,
                "correctness": "correct|incorrect|unknown",
                "coverage_status": "verified|conditional|blocked|unknown|unsupported",
                "confidence": "number in [0,1]",
                "reasons": ["short reason"],
                "evidence": ["visible screenshot/element fact"],
            },
        }

    @staticmethod
    def _edge_vlm_request(report: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "schema_version": VLM_REQUEST_SCHEMA,
            "task": "judge_transition_semantics",
            "policy": {
                "correctness_values": sorted(CORRECTNESS_VALUES),
                "check": [
                    "source element label matches intended function",
                    "target screenshot matches target_page_name",
                    "modal background was not clicked",
                    "permission-gated action was not recorded as success",
                ],
                "do_not_modify_graph": True,
            },
            "evidence": {
                "edge": {
                    "edge_id": report.get("edge_id"),
                    "source": report.get("source"),
                    "target": report.get("target"),
                    "element_label": report.get("element_label"),
                },
                **dict(report.get("evidence") or {}),
                "rule_findings": list(report.get("findings") or []),
            },
            "response_schema": {
                "schema_version": VLM_RESPONSE_SCHEMA,
                "correctness": "correct|incorrect|unknown",
                "coverage_status": "unknown",
                "confidence": "number in [0,1]",
                "reasons": ["short reason"],
                "evidence": ["visible source/target screenshot fact"],
            },
        }

    @staticmethod
    def _event_ledger(graph: Mapping[str, Any]) -> tuple[Optional[str], List[Dict[str, Any]]]:
        containers: List[tuple[str, Mapping[str, Any]]] = [("", graph)]
        metadata = graph.get("graph")
        if isinstance(metadata, Mapping):
            containers.append(("graph.", metadata))
        for prefix, container in containers:
            action_edges = container.get("action_edges")
            if isinstance(action_edges, list):
                attempts: List[Dict[str, Any]] = []
                for raw_edge in action_edges:
                    if not isinstance(raw_edge, Mapping):
                        continue
                    for raw_attempt in raw_edge.get("attempts") or []:
                        if not isinstance(raw_attempt, Mapping):
                            continue
                        attempt = dict(raw_attempt)
                        attempt.setdefault(
                            "action_edge_id", raw_edge.get("action_edge_id"))
                        for key in (
                            "source", "target", "action", "element_id",
                            "element_label", "semantic_description", "region",
                        ):
                            attempt.setdefault(key, raw_edge.get(key))
                        attempts.append(attempt)
                return f"{prefix}action_edges[].attempts", attempts
            for key in (
                "transition_events",
                "action_events",
                "action_event_ledger",
                "event_ledger",
            ):
                raw = container.get(key)
                if isinstance(raw, list):
                    return f"{prefix}{key}", [
                        dict(item) for item in raw if isinstance(item, Mapping)
                    ]
        return None, []

    def _audit_action_ledger(
        self,
        graph: Mapping[str, Any],
        edges: List[Mapping[str, Any]],
        findings: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        ledger_key, events = self._event_ledger(graph)
        counter = max(0, _safe_int(graph.get("action_counter")) or 0)
        edge_indexes: List[int] = []
        for edge in edges:
            raw_indexes = edge.get("action_indices")
            if not isinstance(raw_indexes, list):
                raw_indexes = [edge.get("action_index")]
            edge_indexes.extend(
                index for index in (_safe_int(value) for value in raw_indexes)
                if index is not None
            )
        event_indexes = [
            index for index in (_safe_int(event.get("action_index") or event.get("index") or event.get("sequence")) for event in events) if index is not None
        ]
        expected = set(range(1, counter + 1))
        event_set = set(event_indexes)
        edge_set = set(edge_indexes)
        missing_events = sorted(expected - event_set) if ledger_key else []
        duplicate_events = sorted(index for index, count in Counter(event_indexes).items() if count > 1)
        duplicate_edge_indexes = sorted(
            index for index, count in Counter(edge_indexes).items() if count > 1
        )
        edge_gaps = sorted(expected - edge_set)

        if counter and not ledger_key:
            findings.append(
                _finding(
                    "WARN",
                    "missing_action_event_ledger",
                    "action_counter exists but no append-only action event ledger is persisted",
                    scope="ledger",
                    evidence={"action_counter": counter, "retained_edges": len(edges)},
                )
            )
            if edge_gaps:
                findings.append(
                    _finding(
                        "ERROR",
                        "possible_digraph_overwrite",
                        "retained edge action indexes have gaps and no event ledger can explain them",
                        scope="ledger",
                        evidence={"missing_action_indexes": edge_gaps},
                    )
                )
        if ledger_key and len(events) != counter:
            findings.append(
                _finding(
                    "ERROR",
                    "action_ledger_count_mismatch",
                    "event ledger length differs from action_counter",
                    scope="ledger",
                    evidence={"action_counter": counter, "ledger_events": len(events)},
                )
            )
        if missing_events:
            findings.append(
                _finding(
                    "ERROR",
                    "action_event_index_gaps",
                    "event ledger does not contain every action index",
                    scope="ledger",
                    evidence={"missing_action_indexes": missing_events},
                )
            )
        if duplicate_events:
            findings.append(
                _finding(
                    "ERROR",
                    "duplicate_action_event_indexes",
                    "multiple ledger events share the same action index",
                    scope="ledger",
                    evidence={"duplicate_action_indexes": duplicate_events},
                )
            )
        if duplicate_edge_indexes:
            findings.append(
                _finding(
                    "ERROR",
                    "duplicate_edge_action_indexes",
                    "multiple retained topology edges share the same action index",
                    scope="ledger",
                    evidence={"duplicate_action_indexes": duplicate_edge_indexes},
                )
            )
        invalid_event_indexes = sorted(
            index for index in event_set if index < 1 or (counter and index > counter)
        )
        if invalid_event_indexes:
            findings.append(
                _finding(
                    "ERROR",
                    "action_event_index_out_of_range",
                    "one or more ledger action indexes are outside action_counter",
                    scope="ledger",
                    evidence={"action_indexes": invalid_event_indexes, "action_counter": counter},
                )
            )
        invalid_edge_indexes = sorted(index for index in edge_set if index < 1 or (counter and index > counter))
        if invalid_edge_indexes:
            findings.append(
                _finding(
                    "ERROR",
                    "edge_action_index_out_of_range",
                    "one or more edge action indexes are outside action_counter",
                    scope="ledger",
                    evidence={"action_indexes": invalid_edge_indexes, "action_counter": counter},
                )
            )
        if ledger_key:
            edge_not_in_ledger = sorted(edge_set - event_set)
            if edge_not_in_ledger:
                findings.append(
                    _finding(
                        "ERROR",
                        "edge_missing_from_action_ledger",
                        "retained success edge has no matching action event",
                        scope="ledger",
                        evidence={"action_indexes": edge_not_in_ledger},
                    )
                )

            successful: List[Dict[str, Any]] = []
            for event in events:
                outcome = str(
                    event.get("outcome")
                    or event.get("effect_verdict")
                    or event.get("result")
                    or ""
                ).casefold()
                committed = (
                    event.get("committed") is True
                    or event.get("committed_edge") is True
                    or event.get("edge_committed") is True
                )
                if outcome in _SUCCESS_OUTCOMES or committed:
                    successful.append(event)
            success_indexes = {
                index
                for index in (
                    _safe_int(item.get("action_index") or item.get("index") or item.get("sequence"))
                    for item in successful
                )
                if index is not None
            }
            missing_success_edges = sorted(success_indexes - edge_set)
            if missing_success_edges:
                findings.append(
                    _finding(
                        "ERROR",
                        "committed_event_missing_topology_edge",
                        "successful/committed events are absent from retained topology edges",
                        scope="ledger",
                        evidence={"action_indexes": missing_success_edges},
                    )
                )
            pairs = Counter(
                (str(item.get("source") or ""), str(item.get("target") or ""))
                for item in successful
                if item.get("source") is not None and item.get("target") is not None
            )
            repeated_pairs = [
                {"source": pair[0], "target": pair[1], "events": count}
                for pair, count in sorted(pairs.items())
                if count > 1
            ]
            if (repeated_pairs and graph.get("multigraph") is not True
                    and not isinstance(graph.get("action_edges"), list)):
                findings.append(
                    _finding(
                        "WARN",
                        "digraph_pair_overwrite_risk",
                        "multiple successful events share source/target pairs in a non-multigraph",
                        scope="ledger",
                        evidence={"pairs": repeated_pairs},
                    )
                )
        else:
            repeated_pairs = []

        complete = bool(
            ledger_key
            and len(events) == counter
            and not missing_events
            and not duplicate_events
            and not (edge_set - event_set)
        )
        return {
            "present": bool(ledger_key),
            "field": ledger_key,
            "history_status": "complete" if complete else "incomplete" if counter else "empty",
            "action_counter": counter,
            "event_count": len(events),
            "event_action_indexes": sorted(event_indexes),
            "edge_action_indexes": sorted(edge_indexes),
            "missing_event_indexes": missing_events,
            "duplicate_event_indexes": duplicate_events,
            "duplicate_edge_indexes": duplicate_edge_indexes,
            "edge_index_gaps": edge_gaps,
            "retained_edge_ratio": round(len(edge_set) / counter, 4) if counter else None,
            "repeated_success_pairs": repeated_pairs,
        }

    @staticmethod
    def _overall_confidence(
        node_reports: List[Mapping[str, Any]],
        edge_reports: List[Mapping[str, Any]],
        ledger: Mapping[str, Any],
    ) -> float:
        if not node_reports:
            return 1.0
        readable = sum(
            bool(item.get("evidence", {}).get("screenshot", {}).get("readable"))
            for item in node_reports
        ) / len(node_reports)
        element_evidence = sum(
            int(item.get("evidence", {}).get("elements", {}).get("count") or 0) > 0
            for item in node_reports
        ) / len(node_reports)
        endpoint_evidence = 1.0
        if edge_reports:
            endpoint_evidence = sum(
                bool(item.get("evidence", {}).get("source_screenshot"))
                and bool(item.get("evidence", {}).get("target_screenshot"))
                for item in edge_reports
            ) / len(edge_reports)
        ledger_factor = 1.0 if ledger.get("history_status") == "complete" else 0.35
        vlm_results = [
            evaluation
            for item in [*node_reports, *edge_reports]
            for evaluation in [item.get("vlm_evaluation")]
            if isinstance(evaluation, Mapping) and evaluation.get("accepted")
        ]
        vlm_factor = (
            sum(float(item.get("confidence") or 0.0) for item in vlm_results) / len(vlm_results)
            if vlm_results
            else 0.5
        )
        confidence = (
            0.35
            + 0.25 * readable
            + 0.10 * element_evidence
            + 0.10 * endpoint_evidence
            + 0.10 * ledger_factor
            + 0.10 * vlm_factor
        )
        return round(min(0.99, confidence), 4)

    @staticmethod
    def write_report(report: Mapping[str, Any], destination: str | Path) -> Path:
        """Write only the derived report; the source graph remains untouched."""
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only quality audit of a visual graph")
    parser.add_argument("graph", type=Path)
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--fail-on", choices=("none", "error", "warning"), default="none")
    args = parser.parse_args(list(argv) if argv is not None else None)
    agent = GraphQualityAgent(workspace=args.workspace)
    report = agent.evaluate(args.graph)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_out:
        agent.write_report(report, args.json_out)
    if args.fail_on == "error" and report["status"] == "error":
        return 1
    if args.fail_on == "warning" and report["status"] != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
