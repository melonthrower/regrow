"""Source-local candidate ledger for VLM-directed exploration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, MutableSet, Protocol, Sequence, Tuple

logger = logging.getLogger(__name__)


class RegionCoverageLedger(Protocol):
    def shared_button_names(self): ...
    def mark_clicked(self, region_id: str, name: str) -> None: ...
    def is_clicked(self, region_id: str, name: str) -> bool: ...


class ExplorationLedger(Protocol):
    def is_explored(self, name: str) -> bool: ...
    def is_explored_in_state(self, state_id: str, name: str) -> bool: ...


class FrontierDebugSink(Protocol):
    enabled: bool

    def record_candidate_breakdown(
        self, state_id: str, *, kept: Sequence[str],
        dropped: Sequence[Tuple[str, str]],
    ) -> None: ...


@dataclass(frozen=True)
class FrontierContext:
    state_data: Mapping[str, Mapping[str, Any]]
    region_registry: RegionCoverageLedger | None
    memory: ExplorationLedger
    explored_groups: MutableSet[Tuple[str, str]]
    debug_sink: FrontierDebugSink
    stateful_discover_only: bool
    record_abnormal_button: Callable[..., Any]
    is_abnormal_button: Callable[[str, Any], bool]
    stateful_scope_candidates: Callable[[str, List[Any]], List[Any]]
    is_generic_name: Callable[[str], bool]
    is_chrome_name: Callable[[str], bool]
    has_direct_edge: Callable[[str, str, str], bool] = (
        lambda _state_id, _name, _region_id: False)
    live_observation_state_id: str = ""
    live_observation_elements: Sequence[Any] | None = None
    normalize_name: Callable[[str], str] = (
        lambda value: " ".join(str(value or "").casefold().split()))
    has_complete_region_map: Callable[[str, Any], bool] = (
        lambda _state_id, _element: False)


def unvisited_candidates(state_id: str, context: FrontierContext) -> List[Any]:
    """Return source-local work without making Explorer's semantic decision.

    Inventory already asks the VLM for operable targets. This boundary removes
    only occurrences that the framework can prove are finished: an explicit
    Explorer completion state, a terminal result, a visibly disabled control,
    or an explicit semantic safety veto. A verified action is history
    for the next Explorer decision, not proof that every useful action on the
    same button is complete. Attribute guesses such as
    category, type, selected, or group never hide a target. enabled=false is
    retained as terminal audit evidence rather than treated as a click target.
    """
    data = context.state_data.get(state_id)
    if not data:
        return []
    if data.get("is_system_dialog"):
        return []
    debug = context.debug_sink.enabled
    dropped = []
    out = []
    deferred_returns = []
    live_elements = context.live_observation_elements
    live_authoritative = (
        str(state_id) == str(context.live_observation_state_id or "")
        and live_elements is not None
    )
    live_object_ids = {id(element) for element in (live_elements or [])}
    durable_name_counts = {}
    live_name_counts = {}
    live_by_name = {}
    if live_authoritative:
        for element in data.get("elements", []):
            name = context.normalize_name(
                str(getattr(element, "name", "") or ""))
            if name:
                durable_name_counts[name] = durable_name_counts.get(name, 0) + 1
        for element in live_elements or []:
            name = context.normalize_name(
                str(getattr(element, "name", "") or ""))
            if name:
                live_name_counts[name] = live_name_counts.get(name, 0) + 1
                live_by_name.setdefault(name, []).append(element)

    def current_live_match(element):
        try:
            below_fold = int(
                getattr(element, "scroll_steps", 0) or 0) > 0
        except (TypeError, ValueError):
            below_fold = False
        if (below_fold
                and not context.has_complete_region_map(state_id, element)):
            # This condition is durable and therefore applies equally while the
            # State is remote and after Router reaches it. Without that symmetry
            # the scheduler repeatedly routes to work that disappears on arrival.
            return False, None
        if not live_authoritative:
            return True, None
        if id(element) in live_object_ids:
            return True, element
        name = context.normalize_name(
            str(getattr(element, "name", "") or ""))
        present = bool(
            name
            and durable_name_counts.get(name) == 1
            and live_name_counts.get(name) == 1
        )
        if present:
            return True, live_by_name[name][0]
        # The durable inventory is the registered functional target set. A fresh
        # whole-screen inventory can omit a visible icon or name it as its parent
        # row; omission alone is not evidence that the target disappeared.
        # Execution still performs target-specific current-frame grounding.
        return True, None

    def drop(element, reason):
        if debug:
            dropped.append((str(getattr(element, "name", "") or ""), reason))

    for element in data.get("elements", []):
        status = str(getattr(element, "exploration_status", "") or "")
        if status in {"complete", "covered", "semantic_only", "terminal"}:
            element.visited = True
            drop(element, status)
            continue
        present_now, live_match = current_live_match(element)
        if not present_now:
            element.visited = False
            drop(element, "offscreen_without_complete_region_map")
            continue
        if (live_match is not None
                and getattr(live_match, "enabled", None) is False):
            # Availability belongs to the current screenshot. Do not turn a
            # temporarily disabled occurrence into a durable terminal result;
            # a later revisit may expose the same target as enabled.
            element.visited = False
            drop(element, "disabled_in_live_inventory")
            continue
        if status == "deferred_return":
            element.visited = False
            deferred_returns.append(element)
            continue
        if context.is_abnormal_button(state_id, element):
            element.visited = True
            element.exploration_status = "terminal"
            element.abnormal_reason = (
                element.abnormal_reason or "terminal_observed_outcome")
            drop(element, "terminal_observed_outcome")
            continue
        category = " ".join(
            (getattr(element, "category", "") or "").casefold().split())
        if (getattr(element, "enabled", None) is False
                and not (live_match is not None
                         and getattr(live_match, "enabled", None) is True)):
            context.record_abnormal_button(
                state_id, element, "disabled",
                "the current screenshot explicitly marks this control disabled",
                action=None,
            )
            drop(element, "disabled")
            continue
        if category == "display":
            element.visited = True
            element.exploration_status = "semantic_only"
            element.exploration_reason = "read-only display element"
            drop(element, "display")
            continue
        if element.is_dangerous():
            context.record_abnormal_button(
                state_id, element, "blocked",
                "safety policy forbids executing a dangerous or uncertain-risk "
                "control during exploration",
                action=None,
            )
            drop(element, "safety_veto")
            continue
        # ``visited`` in older graphs meant only that one action happened.
        # Reopen it until Explorer assigns a terminal exploration status.
        element.visited = False
        out.append(element)

    out = context.stateful_scope_candidates(state_id, out)
    if not out and deferred_returns:
        out = context.stateful_scope_candidates(state_id, deferred_returns)
    elif deferred_returns:
        for element in deferred_returns:
            drop(element, "deferred_return")
    if debug:
        context.debug_sink.record_candidate_breakdown(
            state_id, kept=[item.name for item in out], dropped=dropped)
    return out
