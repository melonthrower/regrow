"""Observed page-mode and application-state facts for autonomous traversal.

The ledger stores only states reported from real before/after observations.  It
does not enumerate application domains, selection combinations, or hidden
capability profiles.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping, Sequence


def _key(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


class AutonomousScopeStateLedger:
    """Small durable ledger for discovered page modes and app-wide states."""

    def __init__(self) -> None:
        self.page_modes: Dict[str, Dict[str, Any]] = {}
        self.app_states: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _remember(values: list[str], value: str) -> None:
        if value and value not in values:
            values.append(value)

    def record_page_mode(
        self,
        *,
        page_name: str,
        scope_name: str,
        before_value: str,
        after_value: str,
        selected_occurrence_refs: Sequence[str],
        evidence_action_id: str,
        trigger_entry_id: str = "",
        trigger_operation: str = "",
    ) -> Dict[str, Any]:
        page_name = _text(page_name, 160)
        scope_name = _text(scope_name, 160)
        before_value = _text(before_value, 200)
        after_value = _text(after_value, 200)
        if not page_name or not scope_name or not before_value or not after_value:
            raise ValueError("page mode observation requires page, scope and values")
        key = f"{_key(page_name)}::{_key(scope_name)}"
        record = self.page_modes.setdefault(key, {
            "page_name": page_name,
            "scope_name": scope_name,
            "initial_value": before_value,
            "current_value": before_value,
            "observed_values": [],
            "selected_occurrence_refs": [],
            "transitions": [],
            "observations": [],
        })
        self._remember(record["observed_values"], before_value)
        self._remember(record["observed_values"], after_value)
        record["current_value"] = after_value
        record["selected_occurrence_refs"] = list(dict.fromkeys(
            _text(item, 80) for item in selected_occurrence_refs
            if _text(item, 80)
        ))
        evidence = _text(evidence_action_id, 80)
        if before_value != after_value:
            transition = {
                "from": before_value,
                "to": after_value,
                "evidence_action_id": evidence,
                "trigger_entry_id": _text(trigger_entry_id, 80),
                "trigger_operation": _text(trigger_operation, 40).casefold(),
            }
            if transition not in record["transitions"]:
                record["transitions"].append(transition)
        observation = {
            "value": after_value,
            "evidence_action_id": evidence,
        }
        if observation not in record["observations"]:
            record["observations"].append(observation)
        return deepcopy(record)

    def record_app_state(
        self,
        *,
        scope_name: str,
        before_value: str,
        after_value: str,
        page_name: str,
        state_id: str,
        evidence_action_id: str,
    ) -> Dict[str, Any]:
        scope_name = _text(scope_name, 160)
        before_value = _text(before_value, 200)
        after_value = _text(after_value, 200)
        if not scope_name or not before_value or not after_value:
            raise ValueError("application state observation requires scope and values")
        key = _key(scope_name)
        record = self.app_states.setdefault(key, {
            "scope_name": scope_name,
            "current_value": before_value,
            "observed_values": [],
            "transitions": [],
            "observations": [],
        })
        self._remember(record["observed_values"], before_value)
        self._remember(record["observed_values"], after_value)
        record["current_value"] = after_value
        evidence = _text(evidence_action_id, 80)
        if before_value != after_value:
            transition = {
                "from": before_value,
                "to": after_value,
                "evidence_action_id": evidence,
            }
            if transition not in record["transitions"]:
                record["transitions"].append(transition)
        observation = {
            "value": after_value,
            "page_name": _text(page_name, 160),
            "state_id": _text(state_id, 200),
            "evidence_action_id": evidence,
        }
        if observation not in record["observations"]:
            record["observations"].append(observation)
        return deepcopy(record)

    def page_mode_context(self, page_name: str) -> list[Dict[str, Any]]:
        page_key = _key(page_name)
        return [
            deepcopy(record) for record in self.page_modes.values()
            if _key(record.get("page_name")) == page_key
        ]

    def current_page_mode_requirements(self, page_name: str) -> Dict[str, str]:
        """Return only non-initial modes that constrain newly seen Entries."""
        return {
            str(record.get("scope_name") or ""): str(
                record.get("current_value") or "")
            for record in self.page_mode_context(page_name)
            if record.get("scope_name")
            and record.get("current_value")
            and record.get("current_value") != record.get("initial_value")
        }

    def completion_gaps(self) -> list[str]:
        gaps: list[str] = []
        for record in self.page_modes.values():
            initial = str(record.get("initial_value") or "")
            transitions = record.get("transitions") or []
            entered = {
                str(item.get("to") or "") for item in transitions
                if str(item.get("to") or "") != initial
            }
            exited = {
                str(item.get("from") or "") for item in transitions
                if str(item.get("to") or "") == initial
            }
            for mode in sorted(entered - exited):
                gaps.append(
                    f"{record.get('page_name')}: page mode "
                    f"{record.get('scope_name')} entered {mode!r} without "
                    "an observed exit transition"
                )
        return gaps

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema": "gui_rewalk.autonomous_scope_states.v1",
            "page_modes": deepcopy(self.page_modes),
            "app_states": deepcopy(self.app_states),
        }

    @classmethod
    def from_snapshot(
        cls, payload: Mapping[str, Any] | None,
    ) -> "AutonomousScopeStateLedger":
        ledger = cls()
        source = payload if isinstance(payload, Mapping) else {}
        for field_name, target in (
            ("page_modes", ledger.page_modes),
            ("app_states", ledger.app_states),
        ):
            raw_records = source.get(field_name)
            if not isinstance(raw_records, Mapping):
                continue
            for raw_key, raw_record in raw_records.items():
                if isinstance(raw_record, Mapping):
                    target[str(raw_key)] = deepcopy(dict(raw_record))
        return ledger
