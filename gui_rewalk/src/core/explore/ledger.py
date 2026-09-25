"""Single in-memory and JSON-serializable source of traversal truth."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Type, TypeVar
import copy
import json

from .models import (
    ActionAttempt,
    CanonicalOperation,
    Element,
    HistoryItem,
    Operation,
    Page,
    PageState,
    Region,
    RegionOccurrence,
    RegionVariant,
    Task,
    Transition,
    record_dict,
)


T = TypeVar("T")


class ExplorationLedger:
    """Mutable records with stable framework-owned identifiers.

    Semantic decisions arrive from the Agent.  This class only allocates IDs,
    stores accepted records, and exposes deterministic queries.
    """

    schema = "modular_exploration.v7"
    legacy_schemas = frozenset({
        "modular_exploration.v3", "modular_exploration.v4",
        "modular_exploration.v5", "modular_exploration.v6",
    })

    def __init__(self) -> None:
        self.pages: Dict[str, Page] = {}
        self.states: Dict[str, PageState] = {}
        self.regions: Dict[str, Region] = {}
        self.region_variants: Dict[str, RegionVariant] = {}
        self.canonical_operations: Dict[str, CanonicalOperation] = {}
        self.elements: Dict[str, Element] = {}
        self.occurrences: Dict[str, RegionOccurrence] = {}
        self.operations: Dict[str, Operation] = {}
        self.tasks: Dict[str, Task] = {}
        self.attempts: Dict[str, ActionAttempt] = {}
        self.transitions: List[Transition] = []
        self.history: List[HistoryItem] = []
        self.events: List[Dict[str, Any]] = []
        self.current_page_id = ""
        self.current_state_id = ""
        self.current_task_id = ""
        self._counters: Dict[str, int] = {
            key: 1 for key in (
                "page", "state", "region", "region_variant",
                "canonical_operation", "occurrence", "operation",
                "element", "task", "attempt", "transition", "event", "history",
            )
        }

    def clone(self) -> "ExplorationLedger":
        return copy.deepcopy(self)

    def mint(self, kind: str) -> str:
        prefixes = {
            "page": "p", "state": "s", "region": "r",
            "region_variant": "rv", "occurrence": "ro",
            "canonical_operation": "co",
            "element": "el",
            "operation": "o", "task": "t",
            "attempt": "a", "transition": "e", "event": "ev",
            "history": "h",
        }
        number = self._counters[kind]
        self._counters[kind] = number + 1
        return f"{prefixes[kind]}{number}"

    def event(self, kind: str, **payload: Any) -> Dict[str, Any]:
        event = {
            "event_id": self.mint("event"),
            "seq": len(self.events) + 1,
            "kind": kind,
            "payload": payload,
        }
        self.events.append(event)
        return event

    def current_task(self) -> Optional[Task]:
        return self.tasks.get(self.current_task_id)

    def page_states(self, page_id: str) -> List[PageState]:
        page = self.pages.get(page_id)
        return [self.states[sid] for sid in (page.state_ids if page else [])]

    def state_occurrences(self, state_id: str) -> List[RegionOccurrence]:
        state = self.states.get(state_id)
        return [
            self.occurrences[oid]
            for oid in (state.region_occurrence_ids if state else [])
        ]

    def region_operations(self, region_id: str) -> List[Operation]:
        region = self.regions.get(region_id)
        return [
            self.operations[oid]
            for oid in (region.operation_ids if region else [])
        ]

    def variant_operations(self, variant_id: str) -> List[Operation]:
        variant = self.region_variants.get(variant_id)
        return [
            self.operations[oid]
            for oid in (variant.operation_ids if variant else [])
        ]

    def variant_elements(self, variant_id: str) -> List[Element]:
        variant = self.region_variants.get(variant_id)
        return [
            self.elements[element_id]
            for element_id in (variant.element_ids if variant else [])
            if element_id in self.elements
        ]

    def element_operations(self, element_id: str) -> List[Operation]:
        element = self.elements.get(element_id)
        return [
            self.operations[operation_id]
            for operation_id in (element.operation_ids if element else [])
            if operation_id in self.operations
        ]

    def occurrence_operations(self, occurrence_id: str) -> List[Operation]:
        occurrence = self.occurrences.get(occurrence_id)
        if occurrence is None:
            return []
        if occurrence.variant_id in self.region_variants:
            return self.variant_operations(occurrence.variant_id)
        return [
            item for item in self.region_operations(occurrence.region_id)
            if occurrence_id in item.source_occurrence_ids
        ]

    def region_canonical_operations(
        self,
        region_id: str,
    ) -> List[CanonicalOperation]:
        region = self.regions.get(region_id)
        return [
            self.canonical_operations[item]
            for item in (region.canonical_operation_ids if region else [])
        ]

    def ensure_operation_identity(
        self,
        operation_id: str,
    ) -> CanonicalOperation:
        operation = self.operations[operation_id]
        existing = self.canonical_operations.get(
            operation.canonical_operation_id)
        if existing is not None:
            return existing
        canonical_operation_id = self.mint("canonical_operation")
        identity = CanonicalOperation(
            canonical_operation_id=canonical_operation_id,
            region_id=operation.region_id,
            action=operation.action,
            target=operation.target,
            operation_ids=[operation_id],
            scope=operation.scope,
            direction=operation.direction,
        )
        self.canonical_operations[canonical_operation_id] = identity
        operation.canonical_operation_id = canonical_operation_id
        region = self.regions[operation.region_id]
        if canonical_operation_id not in region.canonical_operation_ids:
            region.canonical_operation_ids.append(canonical_operation_id)
        return identity

    def ensure_occurrence_variant(self, occurrence_id: str) -> RegionVariant:
        """Create the structural Variant for a legacy/manual occurrence."""
        occurrence = self.occurrences[occurrence_id]
        existing = self.region_variants.get(occurrence.variant_id)
        if existing is not None:
            return existing
        region = self.regions[occurrence.region_id]
        variant_id = self.mint("region_variant")
        operation_ids = [
            item.operation_id
            for item in self.region_operations(region.region_id)
            if occurrence_id in item.source_occurrence_ids
        ]
        element_ids = [
            element_id for element_id in region.element_ids
            if self.elements.get(element_id) is not None
            and occurrence_id in self.elements[element_id].source_occurrence_ids
            and self.elements[element_id].variant_id in {"", variant_id}
        ]
        variant = RegionVariant(
            variant_id=variant_id,
            region_id=region.region_id,
            occurrence_ids=[occurrence_id],
            operation_ids=operation_ids,
            element_ids=element_ids,
        )
        self.region_variants[variant_id] = variant
        occurrence.variant_id = variant_id
        if variant_id not in region.variant_ids:
            region.variant_ids.append(variant_id)
        for element_id in element_ids:
            self.elements[element_id].variant_id = variant_id
        for operation_id in operation_ids:
            operation = self.operations[operation_id]
            operation.variant_id = operation.variant_id or variant_id
            self.ensure_operation_identity(operation_id)
        return variant

    def operation_task(self, operation_id: str) -> Optional[Task]:
        exact = next(
            (task for task in self.tasks.values()
             if task.kind == "explore_operation"
             and task.operation_id == operation_id),
            None,
        )
        if exact is not None:
            return exact
        operation = self.operations.get(operation_id)
        identity = self.canonical_operations.get(
            operation.canonical_operation_id if operation else "")
        if (identity is None or identity.region_id != operation.region_id
                or identity.representative_operation_ids):
            return None
        return next((task for task in self.tasks.values()
                     if task.kind == "explore_operation"
                     and task.operation_id in identity.operation_ids), None)

    def coalesce_operation_tasks(self) -> None:
        """Share a goal after identity is known; keep action evidence local."""
        groups: Dict[str, List[Task]] = {}
        for task in self.tasks.values():
            operation = self.operations.get(task.operation_id)
            identity = self.canonical_operations.get(
                operation.canonical_operation_id if operation else "")
            if (task.kind == "explore_operation" and identity is not None
                    and identity.region_id == operation.region_id
                    and not identity.representative_operation_ids):
                groups.setdefault(identity.canonical_operation_id, []).append(task)
        priority = {"active": 0, "pending": 1, "deferred": 2,
                    "done": 3, "failed": 4, "cancelled": 5}
        for canonical_id, tasks in groups.items():
            if len(tasks) < 2:
                continue
            kept = min(tasks, key=lambda task: (
                0 if task.task_id == self.current_task_id and task.status == "active" else 1,
                priority[task.status], task.created_seq))
            removed = {task.task_id for task in tasks if task is not kept}
            kept.attempt_count = sum(task.attempt_count for task in tasks)
            kept.created_seq = min(task.created_seq for task in tasks)
            kept.reason = kept.reason or next((task.reason for task in tasks if task.reason), "")
            for record in [*self.attempts.values(), *self.history]:
                if record.task_id in removed:
                    record.task_id = kept.task_id
            if self.current_task_id in removed:
                self.current_task_id = kept.task_id
            for task_id in removed:
                del self.tasks[task_id]
            self.event("operation_tasks_coalesced", canonical_operation_ref=canonical_id,
                       task_ref=kept.task_id, merged_task_refs=sorted(removed),
                       reason="Reviewed shared operation; local bindings and action evidence retained.")

    def representative_probe_identity(
        self,
        operation_id: str,
    ) -> Optional[CanonicalOperation]:
        return next((
            identity for identity in self.canonical_operations.values()
            if operation_id in identity.representative_operation_ids
        ), None)

    def survey_task(self, state_id: str) -> Optional[Task]:
        return next(
            (task for task in self.tasks.values()
             if task.kind == "survey_page" and task.state_id == state_id),
            None,
        )

    def add_history(
        self,
        *,
        task_id: str,
        purpose: str,
        action: str,
        target: str,
        parameters: Mapping[str, Any],
        result: str,
        source_state_id: str,
        target_state_id: str = "",
    ) -> HistoryItem:
        item = HistoryItem(
            seq=self._counters["history"],
            task_id=task_id,
            purpose=purpose,
            action=action,
            target=target,
            parameters=dict(parameters),
            result=result,
            source_state_id=source_state_id,
            target_state_id=target_state_id,
        )
        self._counters["history"] += 1
        self.history.append(item)
        return item

    def snapshot(self) -> Dict[str, Any]:
        def persisted_record(
            item: Any,
            *,
            derived_fields: Iterable[str] = (),
        ) -> Dict[str, Any]:
            record = record_dict(item)
            for key in derived_fields:
                record.pop(key, None)
            return record

        return {
            "schema": self.schema,
            "current_page_id": self.current_page_id,
            "current_state_id": self.current_state_id,
            "current_task_id": self.current_task_id,
            "counters": dict(self._counters),
            "pages": [record_dict(item) for item in self.pages.values()],
            "states": [record_dict(item) for item in self.states.values()],
            "regions": [
                persisted_record(item, derived_fields=(
                    "operation_ids", "occurrence_ids", "variant_ids",
                    "canonical_operation_ids", "element_ids",
                ))
                for item in self.regions.values()
            ],
            "region_variants": [
                persisted_record(item, derived_fields=(
                    "occurrence_ids", "operation_ids", "element_ids",
                ))
                for item in self.region_variants.values()
            ],
            "canonical_operations": [
                persisted_record(item, derived_fields=("operation_ids",))
                for item in self.canonical_operations.values()
            ],
            "elements": [
                persisted_record(item, derived_fields=("operation_ids",))
                for item in self.elements.values()
            ],
            "occurrences": [record_dict(item) for item in self.occurrences.values()],
            "operations": [record_dict(item) for item in self.operations.values()],
            "tasks": [record_dict(item) for item in self.tasks.values()],
            "attempts": [record_dict(item) for item in self.attempts.values()],
            "transitions": [record_dict(item) for item in self.transitions],
            "history": [record_dict(item) for item in self.history],
            "events": copy.deepcopy(self.events),
        }

    def validate_region_parentage(self) -> None:
        for occurrence in self.occurrences.values():
            seen = {occurrence.occurrence_id}
            parent_id = occurrence.parent_occurrence_id
            while parent_id:
                parent = self.occurrences.get(parent_id)
                if parent is None or parent.state_id != occurrence.state_id:
                    raise ValueError(f"Region parent_ref for {occurrence.occurrence_id} is not in its State")
                if parent_id in seen:
                    raise ValueError(f"Region parent_ref forms a cycle at {occurrence.occurrence_id}")
                if parent.region_id == occurrence.region_id:
                    raise ValueError(f"Region parent_ref collapses parent and child identity at {occurrence.occurrence_id}")
                seen.add(parent_id)
                parent_id = parent.parent_occurrence_id

    def save(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.snapshot(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(output)

    @staticmethod
    def _restore_record(record_type: Type[T], raw: Mapping[str, Any]) -> T:
        allowed = {item.name for item in fields(record_type)}
        return record_type(**{key: value for key, value in raw.items()
                              if key in allowed})

    def _rebuild_derived_indexes(self) -> None:
        """Rebuild in-memory reverse indexes from persisted parent refs."""
        for region in self.regions.values():
            region.operation_ids = []
            region.occurrence_ids = []
            region.variant_ids = []
            region.canonical_operation_ids = []
            region.element_ids = []
        for variant in self.region_variants.values():
            variant.occurrence_ids = []
            variant.operation_ids = []
            variant.element_ids = []
            self.regions[variant.region_id].variant_ids.append(
                variant.variant_id)
        for identity in self.canonical_operations.values():
            identity.operation_ids = []
            self.regions[identity.region_id].canonical_operation_ids.append(
                identity.canonical_operation_id)
        for element in self.elements.values():
            element.operation_ids = []
            self.regions[element.region_id].element_ids.append(
                element.element_id)
            if element.variant_id:
                self.region_variants[element.variant_id].element_ids.append(
                    element.element_id)
        for occurrence in self.occurrences.values():
            self.regions[occurrence.region_id].occurrence_ids.append(
                occurrence.occurrence_id)
            if occurrence.variant_id:
                self.region_variants[occurrence.variant_id].occurrence_ids.append(
                    occurrence.occurrence_id)
        for operation in self.operations.values():
            self.regions[operation.region_id].operation_ids.append(
                operation.operation_id)
            if operation.variant_id:
                self.region_variants[operation.variant_id].operation_ids.append(
                    operation.operation_id)
            if operation.element_id:
                self.elements[operation.element_id].operation_ids.append(
                    operation.operation_id)
            if operation.canonical_operation_id:
                self.canonical_operations[
                    operation.canonical_operation_id
                ].operation_ids.append(operation.operation_id)

    @classmethod
    def load(cls, path: str | Path) -> "ExplorationLedger":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("schema") not in {cls.schema, *cls.legacy_schemas}:
            raise ValueError("unsupported modular exploration ledger schema")
        ledger = cls()
        ledger.schema = str(raw.get("schema") or cls.schema)
        collections: Iterable[tuple[str, Type[Any], str]] = (
            ("pages", Page, "page_id"),
            ("states", PageState, "state_id"),
            ("regions", Region, "region_id"),
            ("region_variants", RegionVariant, "variant_id"),
            ("canonical_operations", CanonicalOperation,
             "canonical_operation_id"),
            ("elements", Element, "element_id"),
            ("occurrences", RegionOccurrence, "occurrence_id"),
            ("operations", Operation, "operation_id"),
            ("tasks", Task, "task_id"),
            ("attempts", ActionAttempt, "attempt_id"),
        )
        for name, record_type, key in collections:
            restored = [cls._restore_record(record_type, item)
                        for item in raw.get(name, [])]
            setattr(ledger, name, {getattr(item, key): item for item in restored})
        ledger.transitions = [
            cls._restore_record(Transition, item)
            for item in raw.get("transitions", [])
        ]
        ledger.history = [
            cls._restore_record(HistoryItem, item)
            for item in raw.get("history", [])
        ]
        ledger.events = list(raw.get("events") or [])
        ledger.current_page_id = str(raw.get("current_page_id") or "")
        ledger.current_state_id = str(raw.get("current_state_id") or "")
        ledger.current_task_id = str(raw.get("current_task_id") or "")
        for key, value in dict(raw.get("counters") or {}).items():
            if key in ledger._counters and isinstance(value, int) and value > 0:
                ledger._counters[key] = value
        ledger._rebuild_derived_indexes()
        ledger.validate_region_parentage()
        return ledger


__all__ = ["ExplorationLedger"]
