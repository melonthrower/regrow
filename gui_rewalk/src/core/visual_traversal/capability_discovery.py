"""Online capability discovery for the screenshot-only traversal.

The traversal must not equate a visible control with a verified capability.
This module therefore turns grounded controls into portable ``discovered``
capability records.  ``StateGraph`` promotes the matching record only after a
real action has produced a verified landing.

The records deliberately contain semantic selectors rather than screenshot
paths or historical coordinates.  Screenshots remain local observation
artifacts used by perception and quality review; they are not part of the
portable capability contract.
"""

from __future__ import annotations

import hashlib
import copy
import json
import unicodedata
from typing import Any, Dict, Iterable, List, Mapping, Sequence


_INPUT_TYPES = frozenset({
    "input", "textbox", "text box", "text field", "textarea", "entry",
    "searchbox", "search box", "search field", "password field",
})
_DROPDOWN_TYPES = frozenset({
    "dropdown", "drop down", "combobox", "combo box", "select", "spinner",
})
_RANGE_TYPES = frozenset({"slider", "range", "range slider"})
_DRAG_TYPES = frozenset({"drag", "draggable", "drag handle"})
_RANGE_LEVELS = ("最小", "一半", "最大")
_SKIP_CATEGORIES = frozenset({"display", "static", "chrome"})


def normalize_semantic_text(value: Any) -> str:
    """Return a locale-tolerant stable token string for ids and matching."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    tokens: List[str] = []
    current: List[str] = []
    for character in text:
        if character.isalnum():
            current.append(character)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return " ".join(tokens)


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def observed_facts(elements: Iterable[Any]) -> Dict[str, Any]:
    """Extract only screenshot-observable facts useful for variant conditions.

    Concrete list item labels are intentionally omitted: a different alarm time
    or contact name must not create a new page identity.  Presence of a semantic
    group and structured function-set state are stable enough to retain.
    """
    states: Dict[str, str] = {}
    groups: set[str] = set()
    selected_modes: set[str] = set()
    for element in elements or ():
        group = normalize_semantic_text(_get(element, "group", ""))
        if group:
            groups.add(group)
        if (
            bool(_get(element, "stateful", False))
            and normalize_semantic_text(_get(element, "effect_scope", ""))
            == "function set"
        ):
            key = normalize_semantic_text(_get(element, "state_key", ""))
            value = normalize_semantic_text(_get(element, "state_value", ""))
            if key and value:
                states[key] = value
        if bool(_get(element, "selected", False)) and not group:
            category = normalize_semantic_text(_get(element, "category", ""))
            name = normalize_semantic_text(_get(element, "name", ""))
            if category == "navigation" and name:
                selected_modes.add(name)
    return {
        "states": dict(sorted(states.items())),
        "present_groups": sorted(groups),
        "selected_modes": sorted(selected_modes),
    }


def _requirement(element: Any) -> List[Dict[str, str]]:
    if not bool(_get(element, "requires_permission", False)):
        return []
    reason = normalize_semantic_text(_get(element, "blocked_reason", ""))
    kind = "authorization"
    if reason in {"application login", "login"}:
        kind = "login"
    return [{
        "kind": kind,
        "fact": reason or "permission required",
        "description": "Visible control is currently gated",
    }]


def _semantic_key(element: Any) -> str:
    explicit = normalize_semantic_text(
        _get(element, "function_name", "")
        or _get(element, "semantic_function", "")
    )
    if explicit:
        return explicit
    state_key = normalize_semantic_text(_get(element, "state_key", ""))
    if bool(_get(element, "stateful", False)) and state_key:
        return f"set {state_key}"
    group = normalize_semantic_text(_get(element, "group", ""))
    category = normalize_semantic_text(_get(element, "category", ""))
    label = normalize_semantic_text(_get(element, "name", ""))
    if group:
        return f"open {group}" if category == "navigation" else f"use {group}"
    if category == "navigation":
        return f"open {label}"
    if normalize_semantic_text(_get(element, "el_type", "")) in _INPUT_TYPES:
        return f"set {label}"
    return f"use {label}"


def _display_name(element: Any, semantic_key: str) -> str:
    explicit = str(
        _get(element, "function_name", "")
        or _get(element, "semantic_function", "")
    ).strip()
    return explicit or semantic_key


def _stable_capability_id(page_id: str, semantic_key: str) -> str:
    raw = f"{page_id}|{semantic_key}".encode("utf-8")
    return "cap_" + hashlib.sha256(raw).hexdigest()[:16]


def _source_ref(element: Any, state_id: str, variant_id: str) -> Dict[str, Any]:
    element_id = _get(element, "id", "")
    return {
        "state_id": str(state_id or ""),
        "variant_id": str(variant_id or ""),
        "element_id": str(element_id if element_id is not None else ""),
        "element_uid": str(_get(element, "uid", "") or ""),
        "element_label": str(_get(element, "name", "") or ""),
        "element_type": str(_get(element, "el_type", "") or ""),
        "category": str(_get(element, "category", "") or ""),
        "region": str(_get(element, "region", "") or ""),
        "group": str(_get(element, "group", "") or ""),
    }


def _portable_recipe(element: Any) -> List[Dict[str, Any]]:
    """Return only actions that can be rebound from live visual semantics.

    Numeric sliders use a portable semantic level.  Runtime grounding derives
    the target point from the freshly perceived slider track; no historical
    coordinate is persisted.  Free-form drag controls remain unsupported.
    """
    label = str(_get(element, "name", "") or "")
    selector = {
        "element_label": label,
        "visible_action_label": str(_get(element, "action_label", "") or ""),
        "element_type": str(_get(element, "el_type", "") or ""),
        "region": str(_get(element, "region", "") or ""),
        "group": str(_get(element, "group", "") or ""),
    }
    selector = {key: value for key, value in selector.items() if value}
    element_type = normalize_semantic_text(_get(element, "el_type", ""))
    if element_type in _DRAG_TYPES:
        return []
    if element_type in _RANGE_TYPES:
        return [{
            "action_type": "SET_SLIDER",
            "selector": selector,
            "parameters": {"level": "{{level}}"},
        }]
    if element_type in _INPUT_TYPES:
        return [{
            "action_type": "TYPE",
            "selector": selector,
            "parameters": {"text": "{{text}}"},
        }]
    click: Dict[str, Any] = {"action_type": "CLICK", "selector": selector}
    if element_type in _DROPDOWN_TYPES:
        click["runtime_options"] = {
            "required": True,
            "slot": "option",
            "source": "discover_at_runtime",
        }
    return [click]


def _portable_input_slots(element: Any) -> List[Dict[str, str]]:
    """Describe values that cannot be taken from the historical observation."""
    element_type = normalize_semantic_text(_get(element, "el_type", ""))
    if element_type in _INPUT_TYPES:
        return [{
            "name": "text",
            "type": "string",
            "source": "runtime_parameter",
        }]
    if element_type in _RANGE_TYPES:
        return [{
            "name": "level",
            "type": "enum",
            "source": "fixed_semantic_anchors",
            "values": list(_RANGE_LEVELS),
        }]
    if element_type in _DROPDOWN_TYPES:
        return [{
            "name": "option",
            "type": "enum",
            "source": "discover_at_runtime",
        }]
    return []


def discover_capabilities(
    *,
    page_id: str,
    variant_id: str,
    state_id: str,
    elements: Sequence[Any],
    extra_functions: Sequence[Any] = (),
) -> List[Dict[str, Any]]:
    """Build deduplicated ``discovered`` capabilities for one observation."""
    facts = observed_facts(elements)
    candidates: Dict[str, Dict[str, Any]] = {}
    for element in [*(elements or ()), *(extra_functions or ())]:
        name = str(_get(element, "name", "") or "").strip()
        category = normalize_semantic_text(_get(element, "category", ""))
        interactive = _get(element, "interactive", True)
        if not name or category in _SKIP_CATEGORIES or interactive is False:
            continue
        if bool(_get(element, "back", False)):
            continue
        semantic_key = _semantic_key(element)
        if not semantic_key.strip() or semantic_key in {"open", "use", "set"}:
            continue
        capability_id = _stable_capability_id(page_id, semantic_key)
        element_type = normalize_semantic_text(
            _get(element, "el_type", ""))
        unsupported_drag = element_type in _DRAG_TYPES
        source = _source_ref(element, state_id, variant_id)
        group = source.get("group") or ""
        input_slots = _portable_input_slots(element)
        if group:
            input_slots.append({
                "name": "item",
                "type": "object",
                "source": "runtime_visible_group",
                "group": group,
            })
        if group:
            legacy_param = {
                "type": "object", "current": "", "values": [],
                "source": "discover_at_runtime", "slot": "item",
                "element_map": {},
            }
        elif input_slots:
            slot = input_slots[0]
            legacy_param = {
                "type": slot.get("type", "none"), "current": "",
                "values": list(slot.get("values") or []),
                "source": slot.get("source", "runtime_parameter"),
                "slot": slot.get("name", "value"), "element_map": {},
            }
        else:
            legacy_param = {
                "type": "none", "current": "", "values": [],
                "source": "", "slot": "", "element_map": {},
            }
        availability = "blocked" if (
            _get(element, "enabled", None) is False
            or bool(_get(element, "requires_permission", False))
        ) else "unsupported" if unsupported_drag else "discovered"
        requirements = _requirement(element)
        record = candidates.get(capability_id)
        if record is None:
            record = {
                "schema_version": "capability.discovery.v1",
                "capability_id": capability_id,
                "page_id": str(page_id or ""),
                "name": _display_name(element, semantic_key),
                "semantic_key": semantic_key,
                "status": "discovered",
                "availability_status": availability,
                "execution_support": (
                    "unsupported" if unsupported_drag else "rebindable"),
                "unsupported_reason": (
                    "semantic drag destination is not observable from one control"
                    if unsupported_drag else ""
                ),
                "param": legacy_param,
                "elements": (
                    [source["element_id"]] if source.get("element_id") else []),
                "element_map": {},
                "input_slots": input_slots,
                "requires": requirements,
                "effects": [],
                "success_predicate": "",
                "observables": [],
                "execution_recipe": _portable_recipe(element),
                "risk_level": (
                    "high" if category == "dangerous" else
                    str(_get(element, "risk", "") or "normal")
                ),
                "available_when": {
                    "variant_ids": [str(variant_id or "")],
                    "observed_facts": facts,
                    "facts_by_variant": {
                        str(variant_id or ""): facts,
                    },
                    "availability_by_variant": {
                        str(variant_id or ""): availability,
                    },
                    "requires_by_variant": {
                        str(variant_id or ""): requirements,
                    },
                },
                "evidence_variants": [str(variant_id or "")],
                "entry_variants": [str(variant_id or "")],
                "source_elements": [source],
                "target_pages": [],
                "target_variants": [],
                "action_edge_ids": [],
            }
            candidates[capability_id] = record
            continue
        if source not in record["source_elements"]:
            record["source_elements"].append(source)
        element_id = source.get("element_id")
        if element_id and element_id not in record["elements"]:
            record["elements"].append(element_id)
    return list(candidates.values())


def merge_capability_records(
    existing: Mapping[str, Any], incoming: Mapping[str, Any]
) -> Dict[str, Any]:
    """Merge observations without downgrading verified semantic evidence."""
    merged = copy.deepcopy(dict(existing or {}))
    if not merged:
        return copy.deepcopy(dict(incoming or {}))
    for key in (
        "evidence_variants", "entry_variants", "source_elements",
        "target_pages", "target_variants", "action_edge_ids", "elements",
    ):
        values = list(merged.get(key) or [])
        for value in list(incoming.get(key) or []):
            if value not in values:
                values.append(value)
        merged[key] = values
    available = dict(merged.get("available_when") or {})
    variants = list(available.get("variant_ids") or [])
    for variant in (incoming.get("available_when") or {}).get("variant_ids", []):
        if variant not in variants:
            variants.append(variant)
    available["variant_ids"] = variants
    facts_by_variant = dict(available.get("facts_by_variant") or {})
    facts_by_variant.update(dict(
        (incoming.get("available_when") or {}).get("facts_by_variant") or {}
    ))
    available["facts_by_variant"] = facts_by_variant
    availability_by_variant = dict(
        available.get("availability_by_variant") or {})
    requires_by_variant = copy.deepcopy(dict(
        available.get("requires_by_variant") or {}))

    def _project_variant_contract(record: Mapping[str, Any]) -> None:
        when = record.get("available_when") or {}
        if not isinstance(when, Mapping):
            when = {}
        record_variants = list(when.get("variant_ids") or [])
        status_map = when.get("availability_by_variant") or {}
        requirement_map = when.get("requires_by_variant") or {}
        fallback_status = str(
            record.get("availability_status") or "discovered")
        fallback_requires = copy.deepcopy(list(record.get("requires") or []))
        for variant in record_variants:
            variant = str(variant)
            status = (status_map.get(variant)
                      if isinstance(status_map, Mapping) else None)
            requirements = (requirement_map.get(variant)
                            if isinstance(requirement_map, Mapping) else None)
            availability_by_variant[variant] = str(
                status or fallback_status or "discovered")
            requires_by_variant[variant] = copy.deepcopy(
                fallback_requires if requirements is None else list(requirements or []))

    _project_variant_contract(existing or {})
    _project_variant_contract(incoming or {})
    available["availability_by_variant"] = availability_by_variant
    available["requires_by_variant"] = requires_by_variant
    if not available.get("observed_facts"):
        available["observed_facts"] = dict(
            (incoming.get("available_when") or {}).get("observed_facts") or {}
        )
    merged["available_when"] = available
    if incoming.get("status") == "verified":
        merged["status"] = "verified"
    if merged.get("status") == "verified":
        merged["availability_status"] = "verified"
    else:
        variant_statuses = set(availability_by_variant.values())
        if variant_statuses and variant_statuses <= {"blocked"}:
            merged["availability_status"] = "blocked"
        elif variant_statuses and variant_statuses <= {"unsupported"}:
            merged["availability_status"] = "unsupported"
        elif ("blocked" in variant_statuses
              or "unsupported" in variant_statuses
              or "conditional" in variant_statuses):
            merged["availability_status"] = "conditional"
        elif variant_statuses:
            merged["availability_status"] = "discovered"

    # ``requires`` remains a compatibility field.  Keep it only when every
    # observed variant has the same requirement set; variant-dependent gates
    # live under available_when.requires_by_variant and must not become a false
    # global prerequisite.
    requirement_values = list(requires_by_variant.values())
    requirement_keys = {
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for value in requirement_values
    }
    merged["requires"] = (
        copy.deepcopy(requirement_values[0])
        if requirement_values and len(requirement_keys) == 1 else []
    )
    for key in ("effects", "success_predicate", "observables"):
        if incoming.get(key):
            merged[key] = incoming[key]
    return merged
