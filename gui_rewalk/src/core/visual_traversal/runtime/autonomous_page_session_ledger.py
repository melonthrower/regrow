"""Framework-owned status records for the single-Agent page experiment."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from typing import Any, Dict, Mapping, Optional, Sequence

from .autonomous_turn import PreviousAssessment, _page_key


def _text(value: Any, *, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _key(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


class PageSessionLedger:
    """Page-local plans and semantic records with framework-assigned IDs."""

    SCHEMA = "gui_rewalk.autonomous_page_sessions.v1"

    def __init__(self) -> None:
        self.pages: Dict[str, Dict[str, Any]] = {}
        self.next_todo = self.next_region = self.next_operation = 1

    @classmethod
    def load(cls, path: str) -> "PageSessionLedger":
        ledger = cls()
        if not os.path.isfile(path):
            return ledger
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        for raw in payload.get("pages") or []:
            page_name = _text(raw.get("page_name"), limit=160)
            if page_name:
                ledger.pages[_page_key(page_name)] = deepcopy(raw)
        counters = payload.get("next_ids") or {}
        for field in ("todo", "region", "operation"):
            try:
                value = max(1, int(counters.get(field) or 1))
            except (TypeError, ValueError):
                value = 1
            setattr(ledger, f"next_{field}", value)
        return ledger

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "next_ids": {name: getattr(self, f"next_{name}") for name in (
                "todo", "region", "operation")},
            "pages": deepcopy(list(self.pages.values())),
        }

    def save(self, host: Any) -> None:
        host.writer._write_json_atomic(
            os.path.join(host.output_root, "autonomous_page_sessions.json"),
            self.snapshot(),
        )

    def has_page(self, page_name: str) -> bool:
        return _page_key(page_name) in self.pages

    def ensure_page(self, page_name: str, summary: str = "") -> Dict[str, Any]:
        page = self.pages.setdefault(_page_key(page_name), {
            "page_name": page_name, "summary": "", "strategy": "",
            "status": "active", "last_reason": "", "todos": [],
            "regions": [], "operations": [],
        })
        if summary:
            page["summary"] = _text(summary, limit=500)
        return page

    def page(self, page_name: str) -> Optional[Dict[str, Any]]:
        value = self.pages.get(_page_key(page_name))
        return deepcopy(value) if value is not None else None

    def known_pages_view(self) -> list[Dict[str, Any]]:
        return [{
            "page_name": page["page_name"],
            "summary": page.get("summary", ""),
            "status": page.get("status", "active"),
            "open_todos": self._open_count(page.get("todos") or []),
            "open_operations": self._open_count(page.get("operations") or []),
        } for page in self.pages.values()]

    def model_view(self, page_name: str) -> Dict[str, Any]:
        return self.page(page_name) or {
            "page_name": "", "status": "unbound", "strategy": "",
            "todos": [], "regions": [], "operations": [],
        }

    @staticmethod
    def _open_count(records: Sequence[Dict[str, Any]]) -> int:
        return sum(item.get("status") in {"pending", "in_progress"}
                   for item in records)

    @staticmethod
    def _by_id(records: Sequence[Dict[str, Any]], record_id: str) -> Any:
        return next((item for item in records if item.get("id") == record_id), None)

    @staticmethod
    def _by_field(records: Sequence[Dict[str, Any]], field: str, value: str) -> Any:
        return next((item for item in records
                     if _key(item.get(field)) == _key(value)), None)

    @staticmethod
    def _signature(raw: Mapping[str, Any]) -> tuple[str, str, str]:
        return tuple(_key(raw.get(name)) for name in (
            "region_name", "operation", "target"))

    @classmethod
    def _by_operation(cls, records: Sequence[Dict[str, Any]], raw: Mapping[str, Any]) -> Any:
        signature = cls._signature(raw)
        return next((item for item in records
                     if cls._signature(item) == signature), None)

    def _record(
        self, page: Dict[str, Any], kind: str, raw: Mapping[str, Any],
        *, identity_field: str,
    ) -> tuple[Optional[Dict[str, Any]], str]:
        records = page[kind]
        record_id = _text(raw.get("id"), limit=40)
        record = (self._by_id(records, record_id) if record_id else
                  self._by_field(records, identity_field, str(raw.get(identity_field) or "")))
        if record_id and record is None:
            return None, f"unknown {kind[:-1]} id: {record_id}"
        if record is None:
            counter = "todo" if kind == "todos" else "region"
            prefix = "t" if kind == "todos" else "r"
            record = {"id": f"{prefix}{getattr(self, f'next_{counter}')}"}
            setattr(self, f"next_{counter}", getattr(self, f"next_{counter}") + 1)
            records.append(record)
        return record, ""

    def apply(
        self, page_name: str, summary: str, update: Mapping[str, Any],
        *, reason: str,
    ) -> tuple[Optional["PageSessionLedger"], str]:
        staged = deepcopy(self)
        page = staged.ensure_page(page_name, summary)
        strategy = update.get("strategy")
        if not isinstance(strategy, str) or not strategy.strip():
            return None, "workspace_update.strategy must be a non-empty string"
        page["strategy"] = _text(strategy, limit=240)
        page["last_reason"] = _text(reason, limit=500)
        for name in ("todos", "regions", "operations"):
            if not isinstance(update.get(name), list):
                return None, f"workspace_update.{name} must be an array"

        for raw in update["todos"]:
            text = _text(raw.get("text"), limit=240)
            status = _text(raw.get("status"), limit=40).casefold()
            if not text or status not in {"pending", "in_progress", "completed", "cancelled"}:
                return None, "todo requires text and a valid status"
            record, issue = staged._record(page, "todos", raw, identity_field="text")
            if issue:
                return None, issue
            record.update(text=text, status=status,
                          reason=_text(raw.get("reason"), limit=300))

        for raw in update["regions"]:
            name = _text(raw.get("name"), limit=160)
            region_summary = _text(raw.get("summary"), limit=500)
            if not name or not region_summary:
                return None, "Region requires a non-empty name and summary"
            record, issue = staged._record(page, "regions", raw, identity_field="name")
            if issue:
                return None, issue
            record.update(name=name, summary=region_summary)

        for raw in update["operations"]:
            values = {name: _text(raw.get(name), limit=200) for name in (
                "region_name", "operation", "target")}
            status = _text(raw.get("status"), limit=40).casefold()
            if not all(values.values()) or status not in {
                "pending", "recorded", "deferred", "cancelled"}:
                return None, "operation requires Region, operation, target and a valid status"
            if staged._by_field(page["regions"], "name", values["region_name"]) is None:
                return None, f"operation references unknown Region: {values['region_name']}"
            record_id = _text(raw.get("id"), limit=40)
            record = (staged._by_id(page["operations"], record_id)
                      if record_id else staged._by_operation(page["operations"], values))
            if record_id and record is None:
                return None, f"unknown operation id: {record_id}"
            if record is None:
                record = {"id": f"o{staged.next_operation}"}
                staged.next_operation += 1
                page["operations"].append(record)
            if record.get("status") == "verified" and status != "recorded":
                status = "verified"
            record.update(**values, status=status,
                          reason=_text(raw.get("reason"), limit=300),
                          result=_text(raw.get("result"), limit=500),
                          entry_id=str(record.get("entry_id") or ""))

        requested = _text(update.get("page_status"), limit=40).casefold()
        if requested not in {"active", "complete"}:
            return None, "workspace_update.page_status must be active or complete"
        open_ids = [item["id"] for item in page["todos"] + page["operations"]
                    if item.get("status") in {"pending", "in_progress"}]
        if requested == "complete" and open_ids:
            return None, "page cannot complete while records remain open: " + ", ".join(open_ids)
        page["status"] = requested
        return staged, ""

    def action_operation(
        self, page_name: str, operation: str, target: str,
    ) -> Optional[Dict[str, Any]]:
        page = self.pages.get(_page_key(page_name))
        matches = [item for item in (page or {}).get("operations") or []
                   if _key(item.get("operation")) == _key(operation)
                   and _key(item.get("target")) == _key(target)]
        return matches[0] if len(matches) == 1 else None

    def mark_operation_in_progress(self, page_name: str, operation_id: str) -> None:
        page = self.pages.get(_page_key(page_name))
        record = self._by_id((page or {}).get("operations") or [], operation_id)
        if record is not None:
            record["status"] = "in_progress"

    def settle_operation(
        self, page_name: str, operation_id: str, assessment: PreviousAssessment,
    ) -> None:
        page = self.pages.get(_page_key(page_name))
        record = self._by_id((page or {}).get("operations") or [], operation_id)
        if record is None:
            return
        if assessment.outcome in {"changed", "no_visible_change"} and assessment.matches_intent:
            record["status"] = "verified"
        elif assessment.failure_kind:
            record["status"] = "deferred"
        else:
            record["status"] = "pending"
        record["result"] = _text(assessment.reason, limit=500)

    def gaps(self) -> list[str]:
        gaps = []
        for page in self.pages.values():
            if page.get("status") != "complete":
                gaps.append(f"Page {page['page_name']} is not agent-complete")
            for kind in ("todos", "operations"):
                gaps.extend(
                    f"open {kind[:-1]} {item['id']} on {page['page_name']}"
                    for item in page[kind]
                    if item.get("status") in {"pending", "in_progress"}
                )
        return gaps


__all__ = ["PageSessionLedger"]
