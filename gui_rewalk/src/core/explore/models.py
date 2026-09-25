"""Pure data records for the modular exploration kernel."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


OPEN_TASK_STATES = frozenset({"pending", "active", "deferred"})
FINAL_TASK_STATES = frozenset({"done", "failed", "cancelled"})
OPEN_OPERATION_STATES = frozenset({"pending", "active", "deferred"})
FINAL_OPERATION_STATES = frozenset({"verified", "recorded", "failed", "cancelled"})
PARAMETER_STATUSES = frozenset({"unknown", "none", "observed"})


@dataclass
class Page:
    page_id: str
    name: str
    summary: str
    state_ids: List[str] = field(default_factory=list)


@dataclass
class PageState:
    state_id: str
    page_id: str
    name: str
    summary: str
    screenshot_ref: str
    region_occurrence_ids: List[str] = field(default_factory=list)
    survey_complete: bool = False
    inventory_passes: int = 0


@dataclass
class Region:
    region_id: str
    name: str
    summary: str
    operation_ids: List[str] = field(default_factory=list)
    occurrence_ids: List[str] = field(default_factory=list)
    variant_ids: List[str] = field(default_factory=list)
    canonical_operation_ids: List[str] = field(default_factory=list)
    element_ids: List[str] = field(default_factory=list)
    memory: str = ""


@dataclass
class RegionVariant:
    variant_id: str
    region_id: str
    occurrence_ids: List[str] = field(default_factory=list)
    operation_ids: List[str] = field(default_factory=list)
    element_ids: List[str] = field(default_factory=list)


@dataclass
class Element:
    element_id: str
    region_id: str
    variant_id: str
    name: str
    operation_ids: List[str] = field(default_factory=list)
    source_occurrence_ids: List[str] = field(default_factory=list)
    observations: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CanonicalOperation:
    canonical_operation_id: str
    region_id: str
    action: str
    target: str
    operation_ids: List[str] = field(default_factory=list)
    scope: str = "element"
    direction: str = ""
    representative_goal: str = ""
    representative_member_operation_ids: List[str] = field(default_factory=list)
    representative_operation_ids: List[str] = field(default_factory=list)
    representative_result: str = ""


@dataclass
class RegionOccurrence:
    occurrence_id: str
    region_id: str
    state_id: str
    name: str
    summary: str
    variant_id: str = ""
    parent_occurrence_id: str = ""


@dataclass
class Operation:
    operation_id: str
    region_id: str
    action: str
    target: str
    status: str
    reason: str = ""
    source_occurrence_ids: List[str] = field(default_factory=list)
    result: str = ""
    attempt_count: int = 0
    reuse_candidate_operation_id: str = ""
    variant_id: str = ""
    canonical_operation_id: str = ""
    scope: str = "element"
    element_id: str = ""
    direction: str = ""
    parameter_status: str = "unknown"
    parameter_summary: str = ""
    parameter_evidence_refs: List[str] = field(default_factory=list)


@dataclass
class Task:
    task_id: str
    kind: str
    status: str
    state_id: str = ""
    operation_id: str = ""
    strategy: str = ""
    reason: str = ""
    attempt_count: int = 0
    created_seq: int = 0


@dataclass
class ActionAttempt:
    attempt_id: str
    task_id: str
    source_state_id: str
    purpose: str
    action: Dict[str, Any]
    before_ref: str
    after_ref: str = ""
    outcome: str = "pending"
    visible_result: str = ""
    target_state_id: str = ""
    anchor_ref: str = ""
    anchor_offset_px: List[int] = field(default_factory=list)
    agent_reason: str = ""


@dataclass
class Transition:
    transition_id: str
    source_state_id: str
    target_state_id: str
    attempt_id: str
    action: Dict[str, Any]
    visible_result: str
    revealed_region_ids: List[str] = field(default_factory=list)
    hidden_region_ids: List[str] = field(default_factory=list)


@dataclass
class HistoryItem:
    seq: int
    task_id: str
    purpose: str
    action: str
    target: str
    parameters: Dict[str, Any]
    result: str
    source_state_id: str
    target_state_id: str = ""


def record_dict(value: Any) -> Dict[str, Any]:
    """Return a JSON-ready shallow data-record view."""
    return asdict(value)


__all__ = [
    "ActionAttempt", "CanonicalOperation", "Element", "FINAL_OPERATION_STATES",
    "FINAL_TASK_STATES", "HistoryItem", "OPEN_OPERATION_STATES",
    "OPEN_TASK_STATES", "Operation",
    "PARAMETER_STATUSES",
    "Page", "PageState", "Region", "RegionOccurrence", "RegionVariant",
    "Task", "Transition", "record_dict",
]
