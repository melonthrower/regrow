"""Parsed Qwen turns and autonomous runtime value objects."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ...graph.effect_observation import valid_parameter_name
from .autonomous_action_tools import PreviousToolReview
from .autonomous_protocol import TOOL_NAMES
from .autonomous_schema import BUSINESS_EFFECT_KINDS, VALID_OUTCOMES


def _page_key(page_name: str) -> str:
    return " ".join(str(page_name or "").strip().casefold().split())


@dataclass(frozen=True)
class ObservedBusinessEffect:
    effect_kind: str
    region_name: str
    capability_name: str
    fact: str
    before_value: str
    after_value: str
    parameter_bindings: Dict[str, str] = field(default_factory=dict)
    same_operation_entry_ids: List[str] = field(default_factory=list)
    same_operation_reason: str = ""


@dataclass(frozen=True)
class ObservedScopeEffect:
    scope_type: str
    scope_name: str
    change_kind: str
    before_value: str
    after_value: str
    selected_region_names: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreviousAssessment:
    outcome: str
    reason: str
    matches_intent: bool = True
    failure_kind: str = ""
    business_effect: Optional[ObservedBusinessEffect] = None
    visible_effect: str = ""
    effects: List[ObservedScopeEffect] = field(default_factory=list)


@dataclass(frozen=True)
class AutonomousDecision:
    action: str
    target: str
    point_1000: Optional[List[float]]
    direction: str
    reason: str
    purpose: str = ""
    tool_name: str = ""
    tool_arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SurfaceRegistration:
    identity: str = "uncertain"
    matched_page_name: str = ""
    variant_name: str = ""
    variant_identity: str = "uncertain"
    visible_predicates: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExplorationTask:
    task_type: str = "explore_entry"
    task_id: str = ""
    entry_id: str = ""
    page_name: str = ""
    region_name: str = ""
    target: str = ""
    goal: str = "explore_function"
    phase: str = ""
    reason: str = ""
    route_hint: List[Dict[str, Any]] = field(default_factory=list)


def _exploration_task_key(task: Optional[ExplorationTask]) -> str:
    if task is None:
        return ""
    if task.task_id:
        return task.task_id
    if task.task_type == "explore_entry":
        return f"explore:{task.entry_id}"
    if task.task_type == "explore_region":
        return f"explore-region:{task.page_name}:{task.region_name}"
    return f"survey:{task.page_name or 'current_visible_page'}"


@dataclass(frozen=True)
class PageUpdate:
    page_name: str
    regions: List[Any] = field(default_factory=list)
    new_entries: List[Any] = field(default_factory=list)
    omitted_regions: List[Any] = field(default_factory=list)
    entry_resolutions: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class EntryReview:
    independent_entries: List[Dict[str, str]] = field(default_factory=list)
    record_only_entries: List[Dict[str, str]] = field(default_factory=list)
    non_task_entries: Optional[List[Dict[str, str]]] = None
    deferred_entries: List[Dict[str, str]] = field(default_factory=list)
    deferred_regions: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AutonomousTurn:
    screen_name: str
    previous: PreviousAssessment
    decision: AutonomousDecision
    task_strategy: str = ""
    registration: SurfaceRegistration = field(default_factory=SurfaceRegistration)
    previous_tool_review: Optional[PreviousToolReview] = None
    page_update: Optional[PageUpdate] = None
    entry_review: Optional[EntryReview] = None


@dataclass(frozen=True)
class ObservedScene:
    state_id: str
    screenshot: bytes
    page_name: str
    variant_name: str = ""
    is_new: bool = False


@dataclass
class PendingAction:
    source: ObservedScene
    event_index: int
    primitive: Dict[str, Any]
    target: str
    reason: str
    history_index: int
    evidence: Dict[str, Any]
    entry_action_id: str = ""
    before_frame_id: str = ""
    validated_action: Any = None
    assessment: Optional[PreviousAssessment] = None


def _reviewed_pending_target(pending: PendingAction) -> str:
    review = pending.evidence.get("click_review")
    if not isinstance(review, dict):
        return ""
    if (str(review.get("decision") or "").casefold() != "approve"
            or review.get("point_matches_target") is not True
            or review.get("target_matches_request") is not True
            or str(review.get("risk") or "").casefold() != "safe"):
        return ""
    return str(review.get("observed_target") or "").strip()[:160]


@dataclass(frozen=True)
class PendingPageIdentity:
    status: str
    data: Dict[str, Any]
    arguments: Dict[str, Any]
    stage: str = "combined"


@dataclass(frozen=True)
class PendingLandingPage:
    page_name: str
    identity: str
    summary: str = ""
    surface_kind: str = "other"


def _point(value: Any) -> tuple[Optional[List[float]], str]:
    if value is None:
        return None, ""
    if not isinstance(value, list) or len(value) != 2:
        return None, "point_1000 must be [x,y] or null"
    try:
        point = [float(value[0]), float(value[1])]
    except (TypeError, ValueError):
        return None, "point_1000 values must be numbers"
    if not all(0.0 <= coordinate <= 1000.0 for coordinate in point):
        return None, "point_1000 is outside the full-screen 0..1000 range"
    return point, ""


def _optional_bbox(value: Any, field_name: str) -> tuple[Optional[List[float]], str]:
    if value is None:
        return None, ""
    if not isinstance(value, list) or len(value) != 4:
        return None, f"{field_name} must be [x1,y1,x2,y2] or null"
    try:
        bbox = [float(item) for item in value]
    except (TypeError, ValueError):
        return None, f"{field_name} values must be numbers"
    if not (0 <= bbox[0] < bbox[2] <= 1000
            and 0 <= bbox[1] < bbox[3] <= 1000):
        return None, f"{field_name} is outside the full-screen 0..1000 range"
    return bbox, ""


def _parse_page_update(value: Any) -> tuple[Optional[PageUpdate], str]:
    if value is None:
        return None, ""
    if not isinstance(value, dict):
        return None, "page_update must be an object or null"
    unknown = sorted(set(value) - {
        "page_name", "regions", "omitted_regions", "entry_resolutions",
    })
    if unknown:
        return None, f"page_update has unsupported fields: {unknown}"
    page_name_value = value.get("page_name")
    if page_name_value is not None and not isinstance(page_name_value, str):
        return None, "page_update.page_name must be a string when supplied"
    page_name = str(page_name_value or "").strip()
    raw_regions = value.get("regions", [])
    if not isinstance(raw_regions, list):
        return None, "page_update.regions must be an array"
    raw_omitted_regions = value.get("omitted_regions", [])
    if not isinstance(raw_omitted_regions, list):
        return None, "page_update.omitted_regions must be an array"
    raw_entry_resolutions = value.get("entry_resolutions", [])
    if not isinstance(raw_entry_resolutions, list):
        return None, "page_update.entry_resolutions must be an array"
    parsed_regions: List[Any] = []
    raw_entries: List[Any] = []
    for region_index, raw_region in enumerate(raw_regions):
        if not isinstance(raw_region, dict):
            parsed_regions.append(deepcopy(raw_region))
            continue
        region = deepcopy(raw_region)
        entries = region.pop("entries", [])
        if not isinstance(entries, list):
            return None, (
                f"page_update.regions[{region_index}].entries must be an array")
        region_name = region.get("name")
        for entry_index, raw_entry in enumerate(entries):
            if isinstance(raw_entry, dict):
                if "region_name" in raw_entry:
                    return None, (
                        "page_update Region entries inherit their owner and must "
                        f"not repeat region_name at regions[{region_index}]."
                        f"entries[{entry_index}]")
                entry = deepcopy(raw_entry)
                entry["region_name"] = region_name
                raw_entries.append(entry)
            else:
                raw_entries.append(deepcopy(raw_entry))
        parsed_regions.append(region)
    return PageUpdate(
        page_name=page_name[:160],
        regions=parsed_regions,
        new_entries=raw_entries,
        omitted_regions=deepcopy(raw_omitted_regions),
        entry_resolutions=deepcopy(raw_entry_resolutions),
    ), ""


def _parse_entry_review(value: Any) -> tuple[Optional[EntryReview], str]:
    if value is None:
        return None, ""
    if not isinstance(value, dict):
        return None, "entry_review must be an object or null"
    fields = (
        "independent_entries", "record_only_entries", "deferred_entries",
    )
    unknown = sorted(set(value) - {
        *fields, "non_task_entries", "deferred_regions",
    })
    if unknown:
        return None, f"entry_review has unsupported fields: {unknown}"
    parsed: Dict[str, List[Dict[str, str]]] = {}
    for field_name in fields:
        raw_entries = value.get(field_name, [])
        if not isinstance(raw_entries, list):
            return None, f"entry_review.{field_name} must be an array"
        entries: List[Dict[str, str]] = []
        for index, raw in enumerate(raw_entries):
            if not isinstance(raw, dict):
                return None, (
                    f"entry_review.{field_name}[{index}] must be an object")
            allowed_item_fields = {
                "region_name", "target", "operation", "subject",
                "control_type",
            }
            if field_name == "independent_entries":
                allowed_item_fields.update({
                    "equivalent_to_entry_id", "equivalence_reason",
                })
            unknown_item = sorted(set(raw) - allowed_item_fields)
            if unknown_item:
                return None, (
                    f"entry_review.{field_name}[{index}] has unsupported "
                    f"fields: {unknown_item}")
            region_name = str(raw.get("region_name") or "").strip()
            target = str(raw.get("target") or "").strip()
            if not region_name or not target:
                return None, (
                    "entry_review entries require non-empty region_name and "
                    "target")
            control_type = str(raw.get("control_type") or "control").strip()
            if control_type not in {"control", "input"}:
                return None, (
                    "entry_review.control_type must be control or input")
            entry = {
                "region_name": region_name[:160],
                "target": target[:160],
                # Older checkpoints and focused fixtures may omit these fields;
                # current model schemas require them.
                "operation": str(
                    raw.get("operation") or target).strip()[:160],
                "subject": str(
                    raw.get("subject") or region_name).strip()[:160],
            }
            if control_type != "control":
                entry["control_type"] = control_type
            if field_name == "independent_entries":
                equivalent_to = str(
                    raw.get("equivalent_to_entry_id") or "").strip()
                equivalence_reason = str(
                    raw.get("equivalence_reason") or "").strip()
                if bool(equivalent_to) != bool(equivalence_reason):
                    return None, (
                        "entry_review equivalence requires both "
                        "equivalent_to_entry_id and equivalence_reason")
                if equivalent_to:
                    entry["equivalent_to_entry_id"] = equivalent_to[:80]
                    entry["equivalence_reason"] = equivalence_reason[:500]
            entries.append(entry)
        parsed[field_name] = entries
    raw_non_tasks = value.get("non_task_entries")
    non_task_entries: Optional[List[Dict[str, str]]] = None
    if raw_non_tasks is not None:
        if not isinstance(raw_non_tasks, list):
            return None, "entry_review.non_task_entries must be an array"
        non_task_entries = []
        for index, raw in enumerate(raw_non_tasks):
            if not isinstance(raw, dict):
                return None, (
                    f"entry_review.non_task_entries[{index}] must be an object")
            unknown_item = sorted(
                set(raw) - {"region_name", "operation", "target"})
            if unknown_item:
                return None, (
                    f"entry_review.non_task_entries[{index}] has unsupported "
                    f"fields: {unknown_item}")
            region_name = str(raw.get("region_name") or "").strip()
            target = str(raw.get("target") or "").strip()
            if not region_name or not target:
                return None, (
                    "entry_review.non_task_entries require non-empty "
                    "region_name and target")
            non_task_entries.append({
                "region_name": region_name[:160],
                "operation": str(
                    raw.get("operation") or target).strip()[:160],
                "target": target[:160],
            })
    raw_deferred_regions = value.get("deferred_regions")
    if not isinstance(raw_deferred_regions, list):
        return None, "entry_review.deferred_regions must be an array"
    deferred_regions: List[str] = []
    for index, raw in enumerate(raw_deferred_regions):
        if not isinstance(raw, str) or not raw.strip():
            return None, (
                f"entry_review.deferred_regions[{index}] must be a non-empty string")
        deferred_regions.append(raw.strip()[:160])
    return EntryReview(
        independent_entries=parsed["independent_entries"],
        record_only_entries=parsed["record_only_entries"],
        non_task_entries=non_task_entries,
        deferred_entries=parsed["deferred_entries"],
        deferred_regions=deferred_regions,
    ), ""


def parse_turn(
    payload: Any,
    *,
    has_previous: bool,
    requires_tool_review: bool = False,
    requires_entry_review: bool = False,
    available_tools: Optional[Sequence[str]] = None,
    identity_stage: str = "",
    selected_page_name: str = "",
    selected_page_identity: str = "",
    fixed_page_name: str = "",
    fixed_variant_name: str = "",
) -> tuple[
        Optional[AutonomousTurn], str]:
    if not isinstance(payload, dict):
        return None, "response must be a JSON object"
    screen = payload.get("screen")
    previous = payload.get("previous_action")
    previous_tool_review = payload.get("previous_tool_review")
    page_update_value = payload.get("page_update")
    entry_review_value = payload.get("entry_review")
    action = payload.get("action")
    identity_stage = str(identity_stage or "").strip().casefold()
    app_scope_stage = identity_stage == "app_scope"
    fixed_identity = bool(
        str(fixed_page_name or "").strip()
        and str(fixed_variant_name or "").strip()
    )
    if app_scope_stage:
        if "screen" in payload:
            return None, "screen is not accepted during app-scope review"
        screen = {}
    elif fixed_identity:
        if "screen" in payload:
            return None, "screen is not accepted when current identity is fixed"
        screen = {
            "name": str(fixed_page_name).strip(),
            "identity": "known",
            "variant": {
                "name": str(fixed_variant_name).strip(),
                "identity": "known",
                "visible_predicates": [],
            },
        }
    elif not isinstance(screen, dict):
        return None, "screen must be an object"
    response_reason = str(payload.get("reason") or "").strip()
    if not response_reason:
        return None, (
            "reason is required and must explain the stage conclusion and "
            "chosen tool or lack of action"
        )
    task_strategy = str(payload.get("task_strategy") or "").strip()
    if has_previous and not isinstance(previous, dict):
        return None, "a pending GUI action requires previous_action"
    if not isinstance(previous, dict):
        previous = {
            "outcome": "not_applicable",
            "reason": "",
            "matches_intent": True,
        }
    if has_previous:
        expected_previous_fields = {
            "outcome", "reason", "matches_intent", "failure_kind",
            "business_effect", "visible_effect", "effects",
        }
        unknown_previous_fields = sorted(
            set(previous) - expected_previous_fields)
        if unknown_previous_fields:
            return None, (
                "previous_action has unsupported fields: "
                f"{unknown_previous_fields}"
            )
    if "action" not in payload:
        return None, "action must be present (object or null)"
    if action is not None and not isinstance(action, dict):
        return None, "action must be an object or null"
    page_update, page_update_error = _parse_page_update(page_update_value)
    if page_update_error:
        return None, page_update_error
    entry_review, entry_review_error = _parse_entry_review(entry_review_value)
    if entry_review_error:
        return None, entry_review_error
    if requires_entry_review and entry_review is None:
        return None, "pending entry candidates require entry_review"
    if requires_entry_review and page_update is not None:
        return None, "page_update is not valid during entry review"
    if requires_entry_review and action is not None:
        return None, "action must be null during entry review"
    if not requires_entry_review and entry_review is not None:
        return None, "entry_review is only valid while candidate review is pending"
    if page_update is not None and action is not None:
        return None, "page_update and a new action must be submitted in separate turns"
    if previous_tool_review is not None and not isinstance(
            previous_tool_review, dict):
        return None, "previous_tool_review must be an object"
    if requires_tool_review and not isinstance(previous_tool_review, dict):
        return None, "pending analysis proposal requires previous_tool_review"

    if app_scope_stage:
        screen_name = ""
        identity = "uncertain"
        matched_page_name = ""
    elif identity_stage == "variant":
        screen_name = str(selected_page_name or "").strip()
        identity = str(selected_page_identity or "").strip().casefold()
        if not screen_name or identity not in {"new", "known"}:
            return None, "variant identity requires one resolved Page"
        matched_page_name = screen_name if identity == "known" else ""
        unexpected_screen_fields = sorted(set(screen) - {"variant"})
        if unexpected_screen_fields:
            return None, (
                "variant stage screen has unsupported fields: "
                f"{unexpected_screen_fields}"
            )
    else:
        screen_name = str(screen.get("name") or "").strip()
        if not screen_name:
            return None, "screen name is required"
        identity = str(screen.get("identity") or "").strip().lower()
        if identity not in {"new", "known", "uncertain"}:
            return None, "invalid screen identity"
        matched_page_name = screen_name if identity == "known" else ""
        if identity_stage == "page":
            unexpected_screen_fields = sorted(
                set(screen) - {"name", "identity"})
            if unexpected_screen_fields:
                return None, (
                    "page stage screen has unsupported fields: "
                    f"{unexpected_screen_fields}"
                )

    raw_variant = screen.get("variant")
    if app_scope_stage:
        variant_name = ""
        variant_identity = "uncertain"
        raw_predicates = []
    elif identity_stage == "page":
        variant_name = ""
        variant_identity = "uncertain"
        raw_predicates: Any = []
    else:
        if not isinstance(raw_variant, dict):
            return None, "screen.variant is required"
        variant_name = str(raw_variant.get("name") or "").strip()
        if not variant_name:
            return None, "screen.variant.name is required"
        variant_identity = str(
            raw_variant.get("identity") or "").strip().casefold()
        if variant_identity not in {"new", "known", "uncertain"}:
            return None, "invalid screen.variant.identity"
        raw_predicates = raw_variant.get("visible_predicates")
        if not isinstance(raw_predicates, list) or not all(
                isinstance(item, str) for item in raw_predicates):
            return None, (
                "screen.variant.visible_predicates must be an array of strings"
            )
    visible_predicates = []
    for raw_predicate in raw_predicates:
        predicate = raw_predicate.strip()[:240]
        if predicate and predicate not in visible_predicates:
            visible_predicates.append(predicate)
    if identity_stage != "page" and identity == "new" and variant_identity != "new":
        return None, "a new Page requires a new initial Variant"
    if identity_stage != "page" and identity == "uncertain" and variant_identity != "uncertain":
        return None, (
            "an uncertain Page requires an uncertain Variant identity")

    outcome = str(previous.get("outcome") or "").strip()
    if outcome not in VALID_OUTCOMES:
        return None, "invalid previous_action outcome"
    if has_previous and outcome == "not_applicable":
        # Preserve the executed action and continue with an unresolved result.
        # Whether the visual outcome matched the intent belongs to the VLM; an
        # omitted assessment must not invalidate the whole turn.
        outcome = "uncertain"
    if not has_previous and outcome != "not_applicable":
        outcome = "not_applicable"
    raw_matches_intent = previous.get("matches_intent", True)
    if not isinstance(raw_matches_intent, bool):
        return None, "previous_action.matches_intent must be a boolean"
    matches_intent = bool(raw_matches_intent) if has_previous else True
    previous_reason = str(previous.get("reason") or "").strip()
    if has_previous and not previous_reason:
        return None, (
            "previous_action.reason is required and must explain the result "
            "from the attached before/after screenshots"
        )
    raw_failure_kind = previous.get("failure_kind")
    failure_kind = (
        str(raw_failure_kind or "").strip().casefold()
        if raw_failure_kind is not None else ""
    )
    if failure_kind not in {
        "", "temporarily_unavailable", "not_interactive",
    }:
        return None, "invalid previous_action.failure_kind"
    visible_effect = str(
        previous.get("visible_effect") or "").strip().casefold()
    if visible_effect not in {
        "", "owner_structure", "owner_state", "page_structure",
        "none", "uncertain",
    }:
        return None, "invalid previous_action.visible_effect"
    raw_scope_effects = previous.get("effects", [])
    if not isinstance(raw_scope_effects, list):
        return None, "previous_action.effects must be an array"
    scope_effects: List[ObservedScopeEffect] = []
    seen_scope_effects: set[tuple[str, str, str]] = set()
    for index, raw_scope_effect in enumerate(raw_scope_effects):
        prefix = f"previous_action.effects[{index}]"
        if not isinstance(raw_scope_effect, dict):
            return None, f"{prefix} must be an object"
        expected_scope_fields = {
            "scope_type", "scope_name", "change_kind", "before_value",
            "after_value", "selected_region_names",
        }
        unknown_scope_fields = sorted(
            set(raw_scope_effect) - expected_scope_fields)
        if unknown_scope_fields:
            return None, (
                f"{prefix} has unsupported fields: {unknown_scope_fields}")
        scope_type = str(
            raw_scope_effect.get("scope_type") or "").strip().casefold()
        change_kind = str(
            raw_scope_effect.get("change_kind") or "").strip().casefold()
        if scope_type not in {
            "owner_region", "region", "page_mode", "app_state",
        }:
            return None, f"invalid {prefix}.scope_type"
        if change_kind not in {"structure", "state", "value"}:
            return None, f"invalid {prefix}.change_kind"
        scope_name = raw_scope_effect.get("scope_name")
        if not isinstance(scope_name, str) or not scope_name.strip():
            return None, f"{prefix}.scope_name must be a non-empty string"
        value_fields = {"before_value", "after_value"}
        missing_value_fields = sorted(
            value_fields - raw_scope_effect.keys())
        if missing_value_fields:
            return None, (
                f"{prefix} requires fields: {missing_value_fields}")
        non_string_value_fields = sorted(
            field_name for field_name in value_fields
            if not isinstance(raw_scope_effect[field_name], str)
        )
        if non_string_value_fields:
            return None, (
                f"{prefix} value fields must be strings: "
                f"{non_string_value_fields}"
            )
        text_values = {
            "scope_name": scope_name.strip(),
            "before_value": raw_scope_effect["before_value"].strip(),
            "after_value": raw_scope_effect["after_value"].strip(),
        }
        if _page_key(text_values["before_value"]) == _page_key(
                text_values["after_value"]):
            return None, f"{prefix} requires distinct before/after values"
        raw_selected = raw_scope_effect.get("selected_region_names", [])
        if not isinstance(raw_selected, list) or not all(
                isinstance(item, str) for item in raw_selected):
            return None, f"{prefix}.selected_region_names must be an array of strings"
        selected_region_names: List[str] = []
        for raw_name in raw_selected:
            name = raw_name.strip()[:160]
            if not name or name in selected_region_names:
                return None, (
                    f"{prefix}.selected_region_names must contain unique "
                    "non-empty names")
            selected_region_names.append(name)
        if selected_region_names and scope_type != "page_mode":
            return None, (
                f"{prefix}.selected_region_names is only valid for page_mode")
        signature = (
            scope_type, _page_key(text_values["scope_name"]), change_kind)
        if signature in seen_scope_effects:
            return None, f"{prefix} duplicates an earlier scope effect"
        seen_scope_effects.add(signature)
        scope_effects.append(ObservedScopeEffect(
            scope_type=scope_type,
            scope_name=text_values["scope_name"][:160],
            change_kind=change_kind,
            before_value=text_values["before_value"][:200],
            after_value=text_values["after_value"][:200],
            selected_region_names=selected_region_names,
        ))
    if scope_effects and outcome != "changed":
        return None, "previous_action.effects requires outcome=changed"
    business_effect: Optional[ObservedBusinessEffect] = None
    raw_business_effect = previous.get("business_effect")
    if raw_business_effect is not None:
        if not isinstance(raw_business_effect, dict):
            return None, (
                "previous_action.business_effect must be an object or null"
            )
        expected_fields = {
            "effect_kind", "region_name", "capability_name", "fact",
            "before_value", "after_value", "parameter_bindings",
            "same_operation_entry_ids", "same_operation_reason",
        }
        unknown_fields = sorted(set(raw_business_effect) - expected_fields)
        if unknown_fields:
            return None, (
                "previous_action.business_effect has unsupported fields: "
                f"{unknown_fields}"
            )
        effect_kind = str(
            raw_business_effect.get("effect_kind") or "").strip().casefold()
        if effect_kind not in BUSINESS_EFFECT_KINDS:
            return None, "invalid previous_action.business_effect.effect_kind"
        value_fields = {"before_value", "after_value"}
        missing_value_fields = sorted(
            value_fields - raw_business_effect.keys())
        if missing_value_fields:
            return None, (
                "previous_action.business_effect requires fields: "
                f"{missing_value_fields}"
            )
        non_string_value_fields = sorted(
            field_name for field_name in value_fields
            if not isinstance(raw_business_effect[field_name], str)
        )
        if non_string_value_fields:
            return None, (
                "previous_action.business_effect value fields must be strings: "
                f"{non_string_value_fields}"
            )
        text_fields = {"region_name", "capability_name", "fact"}
        effect_values = {
            field_name: str(
                raw_business_effect.get(field_name) or "").strip()
            for field_name in text_fields
        }
        effect_values.update({
            field_name: raw_business_effect[field_name].strip()
            for field_name in value_fields
        })
        missing_fields = sorted(
            field_name for field_name in text_fields
            if not effect_values[field_name]
        )
        if missing_fields:
            return None, (
                "previous_action.business_effect requires non-empty fields: "
                f"{missing_fields}"
            )
        raw_bindings = raw_business_effect.get("parameter_bindings")
        if not isinstance(raw_bindings, dict):
            return None, (
                "previous_action.business_effect.parameter_bindings must be "
                "an object"
            )
        parameter_bindings: Dict[str, str] = {}
        for raw_key, raw_value in raw_bindings.items():
            if not isinstance(raw_key, str) or not isinstance(raw_value, str):
                return None, (
                    "business-effect parameter names and values must be strings"
                )
            key = raw_key.strip()[:80]
            value = raw_value.strip()[:200]
            if (not valid_parameter_name(key) or not value
                    or key in parameter_bindings):
                return None, (
                    "business-effect parameter names must be portable unique "
                    "identifiers and values must be non-empty"
                )
            parameter_bindings[key] = value
        raw_same_operation_ids = raw_business_effect.get(
            "same_operation_entry_ids", [])
        if not isinstance(raw_same_operation_ids, list) or not all(
                isinstance(item, str) for item in raw_same_operation_ids):
            return None, (
                "previous_action.business_effect.same_operation_entry_ids "
                "must be an array of strings"
            )
        same_operation_entry_ids: List[str] = []
        for raw_entry_id in raw_same_operation_ids:
            entry_id = raw_entry_id.strip()[:80]
            if not entry_id or entry_id in same_operation_entry_ids:
                return None, (
                    "same_operation_entry_ids must contain unique non-empty "
                    "entry IDs"
                )
            same_operation_entry_ids.append(entry_id)
        same_operation_reason = str(
            raw_business_effect.get("same_operation_reason") or ""
        ).strip()[:500]
        if bool(same_operation_entry_ids) != bool(same_operation_reason):
            return None, (
                "same_operation_entry_ids and same_operation_reason must be "
                "provided together"
            )
        if outcome != "changed":
            return None, (
                "previous_action.business_effect requires outcome=changed"
            )
        if _page_key(effect_values["before_value"]) == _page_key(
                effect_values["after_value"]):
            return None, (
                "previous_action.business_effect requires distinct "
                "before/after values"
            )
        business_effect = ObservedBusinessEffect(
            effect_kind=effect_kind,
            region_name=effect_values["region_name"][:160],
            capability_name=effect_values["capability_name"][:160],
            fact=effect_values["fact"][:160],
            before_value=effect_values["before_value"][:200],
            after_value=effect_values["after_value"][:200],
            parameter_bindings=parameter_bindings,
            same_operation_entry_ids=same_operation_entry_ids,
            same_operation_reason=same_operation_reason,
        )

    action_name = "NONE"
    target = ""
    point: Optional[List[float]] = None
    direction = ""
    tool_name = ""
    purpose = ""
    tool_arguments: Dict[str, Any] = {}
    if isinstance(action, dict):
        unknown_action_fields = sorted(
            set(action) - {"purpose", "tool_name", "tool_arguments"})
        if unknown_action_fields:
            return None, (
                "action has unsupported fields: "
                f"{unknown_action_fields}"
            )
        action_name = "CALL_TOOL"
        tool_name = str(action.get("tool_name") or "").strip()
        purpose = str(action.get("purpose") or "").strip().casefold()
        raw_tool_arguments = action.get("tool_arguments")
        if not isinstance(raw_tool_arguments, dict):
            return None, "action.tool_arguments must be an object"
        tool_arguments = dict(raw_tool_arguments)
        target = str(
            tool_arguments.get("target")
            or tool_arguments.get("container_hint")
            or tool_arguments.get("region_name")
            or tool_arguments.get("operation")
            or tool_arguments.get("target_page")
            or tool_arguments.get("proposed_new_name")
            or tool_arguments.get("prerequisite_target")
            or tool_arguments.get("subject")
            or ("exploration" if tool_name == "finish_exploration" else "")
        ).strip()
        point, point_error = _point(tool_arguments.get("point_1000"))
        if point_error:
            return None, point_error
        direction = str(
            tool_arguments.get("direction") or "").strip().lower()
        allowed_tools = set(
            TOOL_NAMES if available_tools is None else available_tools)
        if tool_name not in allowed_tools:
            return None, "CALL_TOOL requires a tool exposed in the current turn"
        action_tools = {
            "click", "input_text", "hover", "scroll", "navigate", "gesture",
        }
        purposes = {
            "navigation", "locating", "entry_attempt",
            "interruption_recovery", "region_survey", "operation_attempt",
        }
        if tool_name in action_tools and purpose not in purposes:
            return None, "GUI action requires a valid action.purpose"
        if tool_name not in action_tools and purpose:
            return None, "action.purpose is only valid for GUI action tools"
    if action_name == "CALL_TOOL" and tool_name == "page_identity":
        suspected = tool_arguments.get("suspected_pages")
        proposed_name = tool_arguments.get("proposed_new_name")
        if not isinstance(suspected, list) or not all(
                isinstance(item, str) for item in suspected):
            return None, "page_identity requires suspected_pages"
        if not isinstance(proposed_name, str):
            return None, "page_identity requires proposed_new_name"
        if not isinstance(tool_arguments.get("reason"), str) or not str(
                tool_arguments.get("reason") or "").strip():
            return None, "page_identity requires a non-empty reason"
    if action_name == "CALL_TOOL" and tool_name == "defer_current_task":
        if set(tool_arguments) != {"prerequisite_target", "reason"}:
            return None, (
                "defer_current_task requires only prerequisite_target and reason")
        if not all(
                isinstance(tool_arguments.get(field), str)
                and str(tool_arguments.get(field) or "").strip()
                for field in ("prerequisite_target", "reason")):
            return None, (
                "defer_current_task requires non-empty prerequisite_target and reason")
    review = None
    if isinstance(previous_tool_review, dict):
        review_decision = str(
            previous_tool_review.get("decision") or ""
        ).strip().casefold()
        if review_decision not in {"accept", "reject", "uncertain"}:
            return None, "invalid previous_tool_review decision"
        review_reason = str(
            previous_tool_review.get("reason") or ""
        ).strip()
        if not review_reason:
            return None, (
                "previous_tool_review.reason is required and must explain "
                "the review decision"
            )
        review = PreviousToolReview(
            review_decision, review_reason[:500])

    if page_update is not None and not page_update.page_name:
        page_update = PageUpdate(
            page_name=screen_name,
            regions=page_update.regions,
            new_entries=page_update.new_entries,
            omitted_regions=page_update.omitted_regions,
            entry_resolutions=page_update.entry_resolutions,
        )
    return AutonomousTurn(
        screen_name=screen_name[:160],
        previous=PreviousAssessment(
            outcome=outcome,
            business_effect=business_effect,
            reason=str(
                previous_reason
                or outcome
            ).strip()[:500],
            matches_intent=matches_intent,
            failure_kind=failure_kind,
            visible_effect=visible_effect,
            effects=scope_effects,
        ),
        decision=AutonomousDecision(
            action=action_name,
            target=target[:160],
            point_1000=point,
            direction=direction,
            reason=response_reason[:500],
            purpose=purpose,
            tool_name=tool_name,
            tool_arguments=dict(tool_arguments),
        ),
        task_strategy=task_strategy[:240],
        registration=SurfaceRegistration(
            identity=identity,
            matched_page_name=matched_page_name[:160],
            variant_name=variant_name[:160],
            variant_identity=variant_identity,
            visible_predicates=visible_predicates[:12],
        ),
        previous_tool_review=review,
        page_update=page_update,
        entry_review=entry_review,
    ), ""
