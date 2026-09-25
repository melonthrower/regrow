"""Pure entry ledger contracts for autonomous Page Entry updates.

This module deliberately has no GUI or model dependency.  It accepts model
observations as discoveries, while action attempts and verification remain
framework-owned facts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


class EntryStatus(str, Enum):
    DISCOVERED = "discovered"
    RECORDED = "recorded"
    ATTEMPTED = "attempted"
    VERIFIED = "verified"
    UNRESOLVED = "unresolved"
    INFERRED = "inferred"
    INVALIDATED = "invalidated"


def _key(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _bbox(value: Any) -> Optional[Tuple[float, float, float, float]]:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("bbox_1000 must be [x1,y1,x2,y2]")
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError("bbox_1000 values must be numbers") from exc
    x1, y1, x2, y2 = result
    if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
        raise ValueError("bbox_1000 is outside the 0..1000 frame")
    return result


@dataclass
class EntryRecord:
    entry_id: str
    page_name: str
    region_name: str
    target: str
    operation: str = ""
    subject: str = ""
    control_type: str = "control"
    current_value: str = ""
    status: EntryStatus = EntryStatus.DISCOVERED
    temporary_bbox_1000: Optional[Tuple[float, float, float, float]] = None
    bbox_frame_id: str = ""
    discovery_source: str = "main_agent_page_update"
    discovery_screenshot_path: str = ""
    observation_count: int = 1
    attempt_count: int = 0
    last_result: str = ""
    recent_results: List[Dict[str, str]] = field(default_factory=list)
    source_state_id: str = ""
    source_state_ids: List[str] = field(default_factory=list)
    owner_region_ref: str = ""
    representative_occurrence_ref: str = ""
    required_states: List[str] = field(default_factory=list)
    required_page_modes: Dict[str, str] = field(default_factory=dict)
    destination_page: str = ""
    destination_state_id: str = ""
    representative_entry_id: str = ""
    equivalence_reason: str = ""
    same_operation_source_entry_id: str = ""
    same_operation_reason: str = ""
    equivalent_occurrences: List[Dict[str, Any]] = field(default_factory=list)
    inferred_edge_recorded: bool = False
    task_eligible: bool = True
    exploration_policy: str = "explore"

    def serializable(self) -> Dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["equivalent_occurrences"] = [
            {"target": str(item.get("target") or "").strip()}
            for item in self.equivalent_occurrences if item.get("target")
        ]
        if self.temporary_bbox_1000 is not None:
            result["temporary_bbox_1000"] = list(self.temporary_bbox_1000)
        return result


@dataclass
class EntryUpdateDelta:
    added: List[str] = field(default_factory=list)
    matched: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PendingEntryAction:
    action_id: str
    entry_id: str
    frame_id: str


class AutonomousEntryLedger:
    """Small in-memory ledger for autonomous entry discovery and action facts."""

    def __init__(self) -> None:
        self._entries: Dict[str, EntryRecord] = {}
        self._pending: Dict[str, PendingEntryAction] = {}
        self._next_entry = 1
        self._next_action = 1

    @property
    def entries(self) -> Tuple[EntryRecord, ...]:
        return tuple(self._entries.values())

    @property
    def pending_actions(self) -> Tuple[PendingEntryAction, ...]:
        return tuple(self._pending.values())

    def get(self, entry_id: str) -> EntryRecord:
        try:
            return self._entries[str(entry_id)]
        except KeyError as exc:
            raise KeyError(f"unknown autonomous entry: {entry_id}") from exc

    def record_agent_update(
        self,
        *,
        page_name: str,
        region_name: str,
        frame_id: str,
        observations: Sequence[Mapping[str, Any]],
        source_state_id: str = "",
        owner_region_ref: str = "",
        representative_occurrence_ref: str = "",
        discovery_screenshot_path: str = "",
        required_state_ref: str = "",
        required_page_modes: Optional[Mapping[str, str]] = None,
    ) -> EntryUpdateDelta:
        """Merge entries reported directly by the persistent main Agent."""
        page_name = _required_text(page_name, "page_name")
        region_name = _required_text(region_name, "region_name")
        frame_id = _required_text(frame_id, "frame_id")
        source_state_id = str(source_state_id or "").strip()
        owner_region_ref = str(owner_region_ref or "").strip()
        representative_occurrence_ref = str(
            representative_occurrence_ref or "").strip()
        discovery_screenshot_path = str(
            discovery_screenshot_path or "").strip()
        required_state_ref = str(required_state_ref or "").strip()
        normalized_page_modes = {
            _required_text(name, "page mode name")[:160]:
            _required_text(value, "page mode value")[:200]
            for name, value in (required_page_modes or {}).items()
        }
        delta = EntryUpdateDelta()
        preexisting_entry_ids = set(self._entries)
        for raw in observations:
            if not isinstance(raw, Mapping):
                raise ValueError("each Agent entry update must be an object")
            unknown = sorted(set(raw) - {
                "region_name", "target", "bbox_1000",
                "control_type", "equivalent_to_entry_id",
                "equivalence_reason", "equivalent_occurrences",
                "operation", "subject",
                "exploration_policy",
            })
            if unknown:
                raise ValueError(
                    f"new entry has unsupported fields: {unknown}")
            equivalent_to = str(raw.get("equivalent_to_entry_id") or "").strip()
            equivalence_reason = str(
                raw.get("equivalence_reason") or "").strip()
            if equivalent_to and not equivalence_reason:
                equivalence_reason = (
                    "Agent linked this visible occurrence to the canonical "
                    "Entry in the committed shared Region during page survey.")
            if equivalent_to and equivalent_to not in preexisting_entry_ids:
                raise ValueError(
                    "equivalent_to_entry_id must reference an entry that existed "
                    "before this page_update")
            representative_id = ""
            if equivalent_to:
                representative_id = self.canonical_entry_id(equivalent_to)
                representative = self.get(representative_id)
                if (
                    representative.status is not EntryStatus.VERIFIED
                    and (
                        not owner_region_ref
                        or representative.owner_region_ref != owner_region_ref
                    )
                ):
                    raise ValueError(
                        "an unverified equivalent_to_entry_id must reference "
                        "the same committed shared Region")
            occurrences = raw.get("equivalent_occurrences", [])
            if not isinstance(occurrences, list):
                raise ValueError("equivalent_occurrences must be an array")
            normalized_occurrences = []
            for occurrence in occurrences:
                if not isinstance(occurrence, Mapping):
                    raise ValueError("each equivalent occurrence must be an object")
                occurrence_unknown = sorted(
                    set(occurrence) - {"target", "bbox_1000"})
                if occurrence_unknown:
                    raise ValueError(
                        "equivalent occurrence has unsupported fields: "
                        f"{occurrence_unknown}")
                occurrence_target = _required_text(
                    occurrence.get("target"), "equivalent occurrence target")
                occurrence_bbox = _bbox(occurrence.get("bbox_1000"))
                normalized_occurrences.append({
                    "target": occurrence_target,
                    "bbox_1000": (
                        list(occurrence_bbox)
                        if occurrence_bbox is not None else None
                    ),
                })
            target_key = _key(_required_text(raw.get("target"), "target"))
            operation = _required_text(
                raw.get("operation") or raw.get("target"), "operation")
            subject = _required_text(
                raw.get("subject") or region_name, "subject")
            control_type = str(raw.get("control_type") or "control").strip()
            if control_type not in {"control", "input"}:
                raise ValueError("control_type must be control or input")
            exploration_policy = str(
                raw.get("exploration_policy") or "explore").strip()
            if exploration_policy not in {"explore", "record_only"}:
                raise ValueError(
                    "exploration_policy must be explore or record_only")
            exact_existing = next((
                entry for entry in self._entries.values()
                if (_key(entry.page_name) == _key(page_name)
                    and _key(entry.region_name) == _key(region_name)
                    and _key(entry.operation or entry.target) == _key(operation)
                    and _key(entry.target) == target_key)
            ), None)
            if exact_existing is not None:
                exact_existing.observation_count += 1
                if (
                    discovery_screenshot_path
                    and not exact_existing.discovery_screenshot_path
                ):
                    exact_existing.discovery_screenshot_path = (
                        discovery_screenshot_path)
                bbox = _bbox(raw.get("bbox_1000"))
                if bbox is not None:
                    exact_existing.temporary_bbox_1000 = bbox
                    exact_existing.bbox_frame_id = frame_id
                if source_state_id:
                    if not exact_existing.source_state_id:
                        exact_existing.source_state_id = source_state_id
                    if source_state_id not in exact_existing.source_state_ids:
                        exact_existing.source_state_ids.append(
                            source_state_id)
                if owner_region_ref:
                    if (
                        exact_existing.owner_region_ref
                        and exact_existing.owner_region_ref != owner_region_ref
                    ):
                        raise ValueError(
                            "existing entry owner_region_ref cannot change")
                    exact_existing.owner_region_ref = owner_region_ref
                if representative_occurrence_ref:
                    if (
                        exact_existing.representative_occurrence_ref
                        and exact_existing.representative_occurrence_ref
                        != representative_occurrence_ref
                    ):
                        raise ValueError(
                            "existing entry occurrence_ref cannot change")
                    exact_existing.representative_occurrence_ref = (
                        representative_occurrence_ref)
                if (
                    required_state_ref
                    and required_state_ref not in exact_existing.required_states
                ):
                    exact_existing.required_states.append(required_state_ref)
                exact_existing.required_page_modes.update(
                    normalized_page_modes)
                if "equivalent_occurrences" in raw:
                    exact_existing.equivalent_occurrences = normalized_occurrences
                if "operation" in raw:
                    exact_existing.operation = operation
                if "subject" in raw:
                    exact_existing.subject = subject
                if control_type != "control":
                    exact_existing.control_type = control_type
                if exploration_policy == "record_only":
                    exact_existing.exploration_policy = "record_only"
                    if exact_existing.status in {
                            EntryStatus.DISCOVERED, EntryStatus.UNRESOLVED}:
                        exact_existing.status = EntryStatus.RECORDED
                        exact_existing.task_eligible = False
                elif exact_existing.status is EntryStatus.RECORDED:
                    exact_existing.exploration_policy = "explore"
                    exact_existing.status = EntryStatus.DISCOVERED
                    exact_existing.task_eligible = True
                if equivalent_to:
                    if representative_id == exact_existing.entry_id:
                        raise ValueError("entry cannot be equivalent to itself")
                    if representative.status is EntryStatus.VERIFIED:
                        self.declare_equivalence(
                            exact_existing.entry_id,
                            representative_entry_id=representative_id,
                            reason=equivalence_reason,
                        )
                    else:
                        self.link_shared_region_occurrence(
                            exact_existing.entry_id,
                            representative_entry_id=representative_id,
                            reason=equivalence_reason,
                        )
                if exact_existing.entry_id not in delta.matched:
                    delta.matched.append(exact_existing.entry_id)
                continue
            bbox = _bbox(raw.get("bbox_1000"))
            entry_id = f"ae{self._next_entry}"
            self._next_entry += 1
            record = EntryRecord(
                entry_id=entry_id,
                page_name=page_name,
                region_name=region_name,
                target=_required_text(raw.get("target"), "target"),
                operation=operation,
                subject=subject,
                control_type=control_type,
                temporary_bbox_1000=bbox,
                bbox_frame_id=frame_id if bbox is not None else "",
                discovery_source="main_agent_page_update",
                discovery_screenshot_path=discovery_screenshot_path,
                source_state_id=source_state_id,
                source_state_ids=[source_state_id] if source_state_id else [],
                owner_region_ref=owner_region_ref,
                representative_occurrence_ref=representative_occurrence_ref,
                required_states=(
                    [required_state_ref] if required_state_ref else []),
                required_page_modes=dict(normalized_page_modes),
                equivalent_occurrences=normalized_occurrences,
                status=(
                    EntryStatus.RECORDED
                    if exploration_policy == "record_only"
                    else EntryStatus.DISCOVERED
                ),
                task_eligible=exploration_policy == "explore",
                exploration_policy=exploration_policy,
            )
            self._entries[entry_id] = record
            if equivalent_to:
                if representative.status is EntryStatus.VERIFIED:
                    record = self.declare_equivalence(
                        record.entry_id,
                        representative_entry_id=representative_id,
                        reason=equivalence_reason,
                    )
                else:
                    record = self.link_shared_region_occurrence(
                        record.entry_id,
                        representative_entry_id=representative_id,
                        reason=equivalence_reason,
                    )
            delta.added.append(record.entry_id)
        return delta

    def canonical_entry_id(self, entry_id: str) -> str:
        """Resolve only Agent-declared equivalence links; never infer by text."""
        current = self.get(entry_id)
        seen = {current.entry_id}
        while current.representative_entry_id:
            next_id = current.representative_entry_id
            if next_id in seen:
                raise ValueError("entry equivalence cycle")
            seen.add(next_id)
            current = self.get(next_id)
        return current.entry_id

    def task_candidates(self) -> Tuple[EntryRecord, ...]:
        return tuple(
            record for record in self._entries.values()
            if not record.representative_entry_id
            and record.task_eligible
            and record.status in {EntryStatus.DISCOVERED, EntryStatus.UNRESOLVED}
        )

    def inherit_region_state_entries(
        self,
        *,
        region_ref: str,
        source_state_ref: str,
        destination_state_ref: str,
    ) -> Tuple[str, ...]:
        """Keep reviewed Entries runnable across one owner-only state change."""
        region_ref = str(region_ref or "").strip()
        source_state_ref = str(source_state_ref or "").strip()
        destination_state_ref = str(destination_state_ref or "").strip()
        if (
            not region_ref
            or not source_state_ref
            or not destination_state_ref
            or source_state_ref == destination_state_ref
        ):
            return ()
        inherited = []
        for record in self._entries.values():
            if (
                record.owner_region_ref != region_ref
                or source_state_ref not in record.required_states
                or destination_state_ref in record.required_states
            ):
                continue
            record.required_states.append(destination_state_ref)
            inherited.append(record.entry_id)
        return tuple(inherited)

    def reopen_occurrence_after_group_conflict(
        self,
        *,
        occurrence_ref: str,
        new_region_ref: str,
        reason: str,
    ) -> Tuple[str, ...]:
        """Remove inference links that no longer apply after a reviewed split."""
        occurrence_ref = _required_text(
            occurrence_ref, "occurrence_ref")
        new_region_ref = _required_text(new_region_ref, "new_region_ref")
        reopened: List[str] = []
        for record in self._entries.values():
            if record.representative_occurrence_ref != occurrence_ref:
                continue
            record.owner_region_ref = new_region_ref
            inferred = bool(
                record.representative_entry_id
                or record.same_operation_source_entry_id
                or record.status is EntryStatus.INFERRED
            )
            if not inferred:
                continue
            record.representative_entry_id = ""
            record.equivalence_reason = ""
            record.same_operation_source_entry_id = ""
            record.same_operation_reason = ""
            record.destination_page = ""
            record.destination_state_id = ""
            record.status = EntryStatus.DISCOVERED
            record.task_eligible = True
            record.last_result = str(reason or "group conflict observed").strip()[:500]
            self._remember_result(
                record,
                outcome="reopened_after_group_conflict",
                result=record.last_result,
            )
            reopened.append(record.entry_id)
        return tuple(reopened)

    @staticmethod
    def _remember_result(
        record: EntryRecord,
        *,
        outcome: str,
        result: str,
        destination_page: str = "",
        classification: str = "",
    ) -> None:
        item = {
            "outcome": str(outcome or "uncertain").strip()[:80],
            "result": str(result or "").strip()[:500],
        }
        if destination_page:
            item["destination_page"] = str(destination_page).strip()[:160]
        if classification:
            item["classification"] = str(classification).strip()[:80]
        record.recent_results = [
            *record.recent_results[-1:], item,
        ]

    def declare_equivalence(
        self,
        entry_id: str,
        *,
        representative_entry_id: str,
        reason: str,
    ) -> EntryRecord:
        """Apply one explicit task-local Agent judgment of stable semantics."""
        record = self.get(entry_id)
        representative_id = self.canonical_entry_id(representative_entry_id)
        if representative_id == record.entry_id:
            raise ValueError("entry cannot be equivalent to itself")
        representative = self.get(representative_id)
        if representative.status is not EntryStatus.VERIFIED:
            raise ValueError("representative entry must have a verified result")
        record.representative_entry_id = representative_id
        record.equivalence_reason = str(reason or "").strip()[:500]
        record.destination_page = representative.destination_page
        record.destination_state_id = representative.destination_state_id
        record.status = EntryStatus.INFERRED
        record.task_eligible = False
        record.last_result = (
            str(reason or "Agent judged the two entry semantics stable").strip()
            [:500]
        )
        self._remember_result(
            record,
            outcome="inferred",
            result=record.last_result,
            destination_page=record.destination_page,
        )
        return record

    def cover_same_operation(
        self,
        source_entry_id: str,
        *,
        entry_ids: Sequence[str],
        reason: str,
    ) -> List[EntryRecord]:
        """Close same-Region parameter instances from one verified action."""
        source = self.get(source_entry_id)
        if source.status is not EntryStatus.VERIFIED:
            raise ValueError("same-operation source entry must be verified")
        if (
            source.discovery_source == "direct_action_backfill"
            or not source.owner_region_ref
            or source.representative_entry_id
            or source.same_operation_source_entry_id
        ):
            raise ValueError(
                "same-operation source must be one exact formal Region entry"
            )
        reason = _required_text(reason, "same_operation_reason")[:500]
        requested_ids = [str(item or "").strip() for item in entry_ids]
        if not requested_ids or any(not item for item in requested_ids):
            raise ValueError("same-operation entry IDs must be non-empty")
        if len(set(requested_ids)) != len(requested_ids):
            raise ValueError("same-operation entry IDs must be unique")
        records = [self.get(entry_id) for entry_id in requested_ids]
        for record in records:
            if record.entry_id == source.entry_id:
                raise ValueError("same-operation coverage cannot cite itself")
            if (
                _key(record.page_name) != _key(source.page_name)
                or _key(record.region_name) != _key(source.region_name)
                or record.owner_region_ref != source.owner_region_ref
            ):
                raise ValueError(
                    "same-operation entries must share the source Page and Region"
                )
            if (
                not record.task_eligible
                or record.status not in {
                    EntryStatus.DISCOVERED, EntryStatus.UNRESOLVED,
                }
                or record.discovery_source == "direct_action_backfill"
                or record.representative_entry_id
                or record.same_operation_source_entry_id
                or _key(record.control_type) != _key(source.control_type)
            ):
                raise ValueError(
                    "same-operation coverage accepts only pending formal entries"
                )
        for record in records:
            record.status = EntryStatus.INFERRED
            record.task_eligible = False
            record.same_operation_source_entry_id = source.entry_id
            record.same_operation_reason = reason
            record.last_result = reason
            self._remember_result(
                record,
                outcome="inferred_same_operation",
                result=reason,
            )
        return records

    def link_shared_region_occurrence(
        self,
        entry_id: str,
        *,
        representative_entry_id: str,
        reason: str,
    ) -> EntryRecord:
        """Attach one Page occurrence to an existing Entry in the same Region."""
        record = self.get(entry_id)
        representative_id = self.canonical_entry_id(representative_entry_id)
        if representative_id == record.entry_id:
            raise ValueError("entry cannot be equivalent to itself")
        representative = self.get(representative_id)
        if (
            not record.owner_region_ref
            or record.owner_region_ref != representative.owner_region_ref
        ):
            raise ValueError(
                "shared-Region occurrence must keep the same owner_region_ref")
        if representative.status is EntryStatus.VERIFIED:
            return self.declare_equivalence(
                entry_id,
                representative_entry_id=representative_id,
                reason=reason,
            )
        record.representative_entry_id = representative_id
        record.equivalence_reason = str(reason or "").strip()[:500]
        record.task_eligible = False
        return record

    def _sync_verified_occurrences(self, representative: EntryRecord) -> None:
        if representative.status is not EntryStatus.VERIFIED:
            return
        for occurrence in self._entries.values():
            if (
                occurrence.entry_id == representative.entry_id
                or not occurrence.representative_entry_id
                or occurrence.status is EntryStatus.INFERRED
            ):
                continue
            try:
                canonical_id = self.canonical_entry_id(occurrence.entry_id)
            except (KeyError, ValueError):
                continue
            if canonical_id != representative.entry_id:
                continue
            self.declare_equivalence(
                occurrence.entry_id,
                representative_entry_id=representative.entry_id,
                reason=occurrence.equivalence_reason,
            )

    def begin_explicit_action(
        self,
        entry_id: str,
        *,
        frame_id: str,
        page_name: str,
        source_state_id: str = "",
    ) -> PendingEntryAction:
        """Bind a model click to an explicit ledger ID without text matching."""
        record = self.get(entry_id)
        if _key(record.page_name) != _key(page_name):
            raise ValueError(
                f"entry {entry_id} belongs to page {record.page_name!r}, "
                f"not {page_name!r}"
            )
        source_state_id = str(source_state_id or "").strip()[:200]
        if source_state_id:
            if not record.source_state_id:
                record.source_state_id = source_state_id
            if source_state_id not in record.source_state_ids:
                record.source_state_ids.append(source_state_id)
        return self._begin(record, frame_id=frame_id)

    def finish_action(
        self,
        action_id: str,
        *,
        action_executed: bool,
        outcome_verified: bool,
        result: str = "",
        destination_page: str = "",
        destination_state_id: str = "",
    ) -> EntryRecord:
        """Apply a framework-observed action result to its pending entry."""
        try:
            pending = self._pending.pop(str(action_id))
        except KeyError as exc:
            raise KeyError(f"unknown pending autonomous action: {action_id}") from exc
        record = self.get(pending.entry_id)
        record.last_result = str(result or "").strip()[:500]
        record.destination_page = str(destination_page or "").strip()[:160]
        record.destination_state_id = str(destination_state_id or "").strip()[:200]
        record.status = (
            EntryStatus.VERIFIED
            if bool(action_executed) and bool(outcome_verified)
            else EntryStatus.UNRESOLVED
        )
        record.task_eligible = (
            record.status is EntryStatus.UNRESOLVED
            and record.discovery_source != "direct_action_backfill"
        )
        self._remember_result(
            record,
            outcome=("verified" if record.status is EntryStatus.VERIFIED
                     else "unresolved"),
            result=record.last_result,
            destination_page=record.destination_page,
        )
        self._sync_verified_occurrences(record)
        return record

    def mark_unsafe_to_execute(
        self, entry_id: str, *, reason: str,
    ) -> EntryRecord:
        """Keep an independently rejected entry as evidence without rescheduling it."""
        record = self.get(entry_id)
        record.status = EntryStatus.UNRESOLVED
        record.task_eligible = False
        record.last_result = str(reason or "unsafe to execute").strip()[:500]
        self._remember_result(
            record, outcome="unsafe", result=record.last_result)
        return record

    def mark_no_effect_probe(
        self, entry_id: str, *, result: str, classification: str,
    ) -> EntryRecord:
        """Record one reviewed no-effect probe and stop redispatching it."""
        normalized_classification = str(classification or "").strip().casefold()
        if normalized_classification not in {
            "temporarily_unavailable", "not_interactive",
            "observed_no_visible_change",
        }:
            raise ValueError(
                "no-effect classification must be temporarily_unavailable "
                "or not_interactive, or observed_no_visible_change"
            )
        record = self.get(entry_id)
        record.status = EntryStatus.UNRESOLVED
        record.task_eligible = False
        record.last_result = str(
            result or "exact target probed; no visible effect"
        ).strip()[:500]
        self._remember_result(
            record,
            outcome="no_visible_change",
            result=record.last_result,
            classification=normalized_classification,
        )
        return record

    def mark_unreachable(
        self, entry_id: str, *, evidence: str,
    ) -> EntryRecord:
        """Retire one exact Agent-declared unreachable task without verifying it."""
        record = self.get(entry_id)
        record.status = EntryStatus.UNRESOLVED
        record.task_eligible = False
        record.last_result = str(evidence or "declared unreachable").strip()[:500]
        self._remember_result(
            record, outcome="unreachable", result=record.last_result)
        return record

    def mark_invalidated(
        self, entry_id: str, *, reason: str,
    ) -> EntryRecord:
        """Retire a candidate rejected by two-frame discovery verification."""
        record = self.get(entry_id)
        record.status = EntryStatus.INVALIDATED
        record.task_eligible = False
        record.last_result = str(
            reason or "discovery screenshot did not support the candidate"
        ).strip()[:500]
        self._remember_result(
            record, outcome="invalidated", result=record.last_result)
        return record

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema": "gui_rewalk.autonomous_entries.v8",
            "next_action": self._next_action,
            "entries": [entry.serializable() for entry in self.entries],
            "pending_actions": [asdict(item) for item in self.pending_actions],
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        *,
        prior_action_ids: Sequence[str] = (),
    ) -> "AutonomousEntryLedger":
        ledger = cls()
        max_entry = 0
        for raw in payload.get("entries") or []:
            if not isinstance(raw, Mapping):
                continue
            entry_id = str(raw.get("entry_id") or "").strip()
            if not entry_id:
                continue
            try:
                status = EntryStatus(str(raw.get("status") or "discovered"))
            except ValueError:
                status = EntryStatus.UNRESOLVED
            source_state_id = str(
                raw.get("source_state_id") or "").strip()
            raw_source_state_ids = raw.get("source_state_ids") or []
            if not isinstance(raw_source_state_ids, list):
                raw_source_state_ids = []
            source_state_ids = []
            values = (
                ([source_state_id] if source_state_id else [])
                + raw_source_state_ids
            )
            for value in values:
                normalized_state_id = str(value or "").strip()
                if (
                    normalized_state_id
                    and normalized_state_id not in source_state_ids
                ):
                    source_state_ids.append(normalized_state_id)
            if not source_state_id and source_state_ids:
                source_state_id = source_state_ids[0]
            raw_required_states = raw.get("required_states") or []
            if not isinstance(raw_required_states, list):
                raw_required_states = []
            required_states = list(dict.fromkeys(
                str(item or "").strip()
                for item in raw_required_states
                if str(item or "").strip()
            ))
            record = EntryRecord(
                entry_id=entry_id,
                page_name=str(raw.get("page_name") or "").strip(),
                region_name=str(raw.get("region_name") or "").strip(),
                target=str(raw.get("target") or "").strip(),
                operation=str(
                    raw.get("operation") or raw.get("target") or "").strip(),
                subject=str(
                    raw.get("subject") or raw.get("region_name") or "").strip(),
                control_type=str(raw.get("control_type") or "control").strip(),
                current_value=str(raw.get("current_value") or "").strip(),
                status=status,
                temporary_bbox_1000=None,
                bbox_frame_id="",
                discovery_source=str(raw.get("discovery_source") or "resume"),
                discovery_screenshot_path=str(
                    raw.get("discovery_screenshot_path") or "").strip(),
                observation_count=max(1, int(raw.get("observation_count") or 1)),
                attempt_count=max(0, int(raw.get("attempt_count") or 0)),
                last_result=str(raw.get("last_result") or "").strip(),
                recent_results=[
                    {
                        key: str(item.get(key) or "").strip()
                        for key in (
                            "outcome", "result", "destination_page",
                            "classification",
                        )
                        if item.get(key) not in (None, "")
                    }
                    for item in (raw.get("recent_results") or [])[-2:]
                    if isinstance(item, Mapping)
                ],
                source_state_id=source_state_id,
                source_state_ids=source_state_ids,
                owner_region_ref=str(
                    raw.get("owner_region_ref") or "").strip(),
                representative_occurrence_ref=str(
                    raw.get("representative_occurrence_ref") or "").strip(),
                required_states=required_states,
                required_page_modes={
                    str(name).strip(): str(value).strip()
                    for name, value in (
                        raw.get("required_page_modes") or {}).items()
                    if str(name).strip() and str(value).strip()
                } if isinstance(raw.get("required_page_modes"), Mapping) else {},
                destination_page=str(raw.get("destination_page") or "").strip(),
                destination_state_id=str(raw.get("destination_state_id") or "").strip(),
                representative_entry_id=str(
                    raw.get("representative_entry_id") or "").strip(),
                equivalence_reason=str(raw.get("equivalence_reason") or "").strip(),
                same_operation_source_entry_id=str(
                    raw.get("same_operation_source_entry_id") or "").strip(),
                same_operation_reason=str(
                    raw.get("same_operation_reason") or "").strip(),
                equivalent_occurrences=[
                    dict(item) for item in raw.get("equivalent_occurrences") or []
                    if isinstance(item, Mapping)
                ],
                inferred_edge_recorded=bool(raw.get("inferred_edge_recorded")),
                task_eligible=bool(raw.get(
                    "task_eligible",
                    str(raw.get("discovery_source") or "")
                    != "direct_action_backfill",
                )),
                exploration_policy=str(
                    raw.get("exploration_policy")
                    or ("record_only" if status is EntryStatus.RECORDED
                        else "explore")
                ).strip(),
            )
            if record.discovery_source == "direct_action_backfill":
                record.task_eligible = False
            if record.status is EntryStatus.RECORDED:
                record.task_eligible = False
                record.exploration_policy = "record_only"
            if record.status is EntryStatus.INVALIDATED:
                record.task_eligible = False
            if record.representative_entry_id:
                record.task_eligible = False
            if record.same_operation_source_entry_id:
                record.task_eligible = False
            ledger._entries[entry_id] = record
            if entry_id.startswith("ae") and entry_id[2:].isdigit():
                max_entry = max(max_entry, int(entry_id[2:]))
        pending_payload = [
            item for item in payload.get("pending_actions") or []
            if isinstance(item, Mapping)
        ]
        pending_by_entry = {
            str(item.get("entry_id") or ""): item
            for item in pending_payload
        }
        for entry_id in pending_by_entry:
            if entry_id in ledger._entries:
                ledger._entries[entry_id].status = EntryStatus.UNRESOLVED
                if (
                    ledger._entries[entry_id].discovery_source
                    != "direct_action_backfill"
                    and not ledger._entries[entry_id].representative_entry_id
                    and not ledger._entries[
                        entry_id].same_operation_source_entry_id
                ):
                    ledger._entries[entry_id].task_eligible = True
        ledger._next_entry = max_entry + 1
        action_ids = list(prior_action_ids) + [
            str(item.get("action_id") or "") for item in pending_payload
        ]
        max_action = max((
            int(action_id[2:])
            for action_id in action_ids
            if action_id.startswith("aa") and action_id[2:].isdigit()
        ), default=0)
        ledger._next_action = max(
            max_action + 1,
            int(payload.get("next_action") or 1),
        )
        return ledger

    def _begin(self, record: EntryRecord, *, frame_id: str) -> PendingEntryAction:
        action_id = f"aa{self._next_action}"
        self._next_action += 1
        record.status = EntryStatus.ATTEMPTED
        record.attempt_count += 1
        pending = PendingEntryAction(
            action_id=action_id,
            entry_id=record.entry_id,
            frame_id=str(frame_id),
        )
        self._pending[action_id] = pending
        return pending

__all__ = [
    "AutonomousEntryLedger",
    "EntryRecord",
    "EntryStatus",
    "EntryUpdateDelta",
    "PendingEntryAction",
]
