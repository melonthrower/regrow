#!/usr/bin/env python3
"""Standalone ref-only contract for the Luna Region harness.

This module deliberately does not import the production exploration runtime.
It uses the same stable ID shape (r/rv/co/o/a/e) while the harness, rather
than Luna, owns allocation and validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
import argparse
import base64
import datetime as dt
import json
import requests
from urllib.request import Request, urlopen


OUTCOMES = frozenset({"success", "no_effect", "failed", "uncertain"})
PURPOSES = frozenset({"execute", "route", "recover"})
ACTION_KINDS = frozenset({"click", "scroll", "back", "wait"})

STABLE_DEVELOPER_CONTRACT = """You are the semantic planner for a GUI Region harness.
Only reference r/co/o IDs shown below. Never allocate an ID. Report unknown
surfaces only as status=new candidates. One pending attempt must be settled by
its exact aN before another action. A foreground surface blocks background
operations. Coordinates do not belong in this response; a fresh grounder owns
them. no_effect is terminal for the same logical operation."""


def _text(value: Any, field_name: str, *, required: bool = True) -> str:
    text = " ".join(str(value or "").split()).strip()
    if required and not text:
        raise ValueError(f"{field_name} is required")
    return text


def _object(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _array(value: Any, field_name: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    return value


@dataclass(frozen=True)
class OperationBinding:
    region_ref: str
    canonical_operation_ref: str
    operation_ref: str
    action: str
    target: str
    variant_ref: str = ""
    direction: str = ""


@dataclass(frozen=True)
class PreviousAction:
    attempt_ref: str
    outcome: str
    reason: str


@dataclass(frozen=True)
class NextAction:
    region_ref: str
    canonical_operation_ref: str
    operation_ref: str
    purpose: str
    reason: str


@dataclass(frozen=True)
class RegionUpdate:
    status: str
    region_ref: str
    candidate: Mapping[str, Any] | None


@dataclass(frozen=True)
class HarnessTurn:
    previous_action: PreviousAction | None
    region_updates: Sequence[RegionUpdate]
    next_action: NextAction | None
    finish: bool
    reason: str


@dataclass(frozen=True)
class DynamicInput:
    screenshot: bytes
    step: str
    pending_result: Mapping[str, Any] | None = None
    short_diff: str = ""
    before_screenshot: bytes | None = None


class CompiledRoute:
    """One high-level plan whose bindings need fresh grounding per step."""

    def __init__(self, operation_refs: Sequence[str]) -> None:
        if not operation_refs or len(set(operation_refs)) != len(operation_refs):
            raise ValueError("compiled route requires unique operation refs")
        self.operation_refs = list(operation_refs)
        self.index = 0
        self._last_grounded_frame = ""

    def next_operation(self) -> str:
        if self.index >= len(self.operation_refs):
            return "complete"
        return self.operation_refs[self.index]

    def consume_grounding(
        self,
        operation_ref: str,
        frame_ref: str,
        grounding: Mapping[str, Any],
    ) -> str:
        if operation_ref != self.next_operation():
            return "replan_required"
        if not frame_ref or frame_ref == self._last_grounded_frame:
            return "replan_required"
        if not all(grounding.get(key) is True for key in (
                "target_visible", "identity_matches", "unique", "safe")):
            return "replan_required"
        self._last_grounded_frame = frame_ref
        self.index += 1
        return self.next_operation()


class LunaResponses:
    """Minimal OpenAI-compatible client that preserves the message split."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        reasoning_effort: str,
        timeout: int,
    ) -> None:
        self.base_url = _text(base_url, "base_url").rstrip("/")
        self.api_key = _text(api_key, "api_key")
        self.model = _text(model, "model")
        self.reasoning_effort = _text(reasoning_effort, "reasoning_effort")
        self.timeout = int(timeout)

    def call(
        self,
        *,
        role: str,
        messages: Sequence[Mapping[str, Any]],
        schema: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = {
            "model": self.model,
            "input": list(messages),
            "reasoning": {"effort": self.reasoning_effort},
            "text": {"format": {
                "type": "json_schema",
                "name": _text(role, "role"),
                "schema": dict(schema),
                "strict": True,
            }},
            "store": False,
        }
        try:
            response = requests.post(
                self.base_url + "/responses",
                headers={
                    "Authorization": "Bearer " + self.api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Luna Responses request failed: {type(exc).__name__}") from None
        try:
            body = response.json()
        except ValueError:
            raise RuntimeError("Luna Responses returned invalid JSON") from None
        if not isinstance(body, Mapping):
            raise RuntimeError("Luna Responses returned an invalid object")
        output_text = body.get("output_text")
        if not isinstance(output_text, str):
            parts = []
            for message in body.get("output") or []:
                if not isinstance(message, Mapping):
                    continue
                for content in message.get("content") or []:
                    if (isinstance(content, Mapping)
                            and content.get("type") == "output_text"
                            and isinstance(content.get("text"), str)):
                        parts.append(content["text"])
            output_text = "".join(parts)
        try:
            parsed = json.loads(output_text or "")
        except json.JSONDecodeError:
            raise RuntimeError("Luna Responses output is not valid JSON") from None
        if not isinstance(parsed, dict):
            raise RuntimeError("Luna Responses output is not an object")
        usage = body.get("usage")
        usage = usage if isinstance(usage, Mapping) else {}
        details = usage.get("input_tokens_details")
        details = details if isinstance(details, Mapping) else {}
        telemetry = {
            "requested_model": self.model,
            "effective_model": _text(body.get("model"), "response.model", required=False),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cached_tokens": details.get("cached_tokens", 0),
            "cache_write_tokens": details.get("cache_write_tokens", 0),
        }
        return parsed, telemetry


@dataclass
class RegionHarnessState:
    """Stable refs and deterministic terminal facts for one harness run."""

    regions: dict[str, dict[str, str]] = field(default_factory=dict)
    canonical_operations: dict[str, dict[str, str]] = field(default_factory=dict)
    operations: dict[str, OperationBinding] = field(default_factory=dict)
    terminal_no_effect_operations: set[str] = field(default_factory=set)
    completed_operations: set[str] = field(default_factory=set)
    deferred_operations: dict[str, str] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=lambda: {
        "region": 1,
        "region_variant": 1,
        "canonical_operation": 1,
        "operation": 1,
        "attempt": 1,
        "event": 1,
    })

    @classmethod
    def with_operation(
        cls,
        region_ref: str,
        canonical_operation_ref: str,
        operation_ref: str,
        action: str,
        target: str,
    ) -> "RegionHarnessState":
        state = cls()
        state.regions[region_ref] = {"name": region_ref, "variant_ref": ""}
        state.canonical_operations[canonical_operation_ref] = {
            "region_ref": region_ref,
            "action": action,
            "target": target,
        }
        state.operations[operation_ref] = OperationBinding(
            region_ref=region_ref,
            canonical_operation_ref=canonical_operation_ref,
            operation_ref=operation_ref,
            action=action,
            target=target,
        )
        state._advance_counters_from_refs()
        return state

    def _advance_counters_from_refs(self) -> None:
        prefixes = {
            "region": "r",
            "region_variant": "rv",
            "canonical_operation": "co",
            "operation": "o",
            "attempt": "a",
            "event": "e",
        }
        all_refs = [*self.regions, *self.canonical_operations, *self.operations]
        for kind, prefix in prefixes.items():
            values = [
                int(ref[len(prefix):]) for ref in all_refs
                if ref.startswith(prefix) and ref[len(prefix):].isdigit()
            ]
            if values:
                self.counters[kind] = max(self.counters[kind], max(values) + 1)

    def mint(self, kind: str) -> str:
        prefix = {
            "region": "r",
            "region_variant": "rv",
            "canonical_operation": "co",
            "operation": "o",
            "attempt": "a",
            "event": "e",
        }.get(kind)
        if prefix is None:
            raise ValueError(f"unsupported ID kind: {kind}")
        value = f"{prefix}{self.counters[kind]}"
        self.counters[kind] += 1
        return value

    def operation_cards(self) -> list[dict[str, str]]:
        return [
            {
                "region_ref": item.region_ref,
                "canonical_operation_ref": item.canonical_operation_ref,
                "operation_ref": item.operation_ref,
                "action": item.action,
                "target": item.target,
                "variant_ref": item.variant_ref,
                "direction": item.direction,
                "status": (
                    "deferred" if item.operation_ref in self.deferred_operations
                    else "completed" if item.operation_ref in self.completed_operations
                    else "open"
                ),
            }
            for item in self.operations.values()
        ]


def build_messages(
    state: RegionHarnessState,
    dynamic: DynamicInput,
) -> list[dict[str, Any]]:
    """Separate cache-stable contract/workset from fresh-frame observations."""
    developer_text = STABLE_DEVELOPER_CONTRACT + "\n\nKnown Region and operation cards:\n" + json.dumps({
        "regions": state.regions,
        "operations": state.operation_cards(),
    }, ensure_ascii=False, separators=(",", ":"))
    dynamic_text = json.dumps({
        "current_step": dynamic.step,
        "pending_result": dynamic.pending_result,
        "short_diff": dynamic.short_diff,
    }, ensure_ascii=False, separators=(",", ":"))
    user_content: list[dict[str, Any]] = [
        {"type": "input_text", "text": dynamic_text},
    ]
    if dynamic.before_screenshot is not None:
        user_content.append({
            "type": "input_image",
            "image_url": "data:image/png;base64," + base64.b64encode(
                dynamic.before_screenshot).decode("ascii"),
        })
    user_content.append({
        "type": "input_image",
        "image_url": "data:image/png;base64," + base64.b64encode(
            dynamic.screenshot).decode("ascii"),
    })
    return [
        {
            "role": "developer",
            "content": [{"type": "input_text", "text": developer_text}],
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]


def _parse_previous(raw: Any) -> PreviousAction | None:
    if raw is None:
        return None
    value = _object(raw, "previous_action")
    outcome = _text(value.get("outcome"), "previous_action.outcome").casefold()
    if outcome not in OUTCOMES:
        raise ValueError("previous_action.outcome is invalid")
    return PreviousAction(
        attempt_ref=_text(value.get("attempt_ref"), "previous_action.attempt_ref"),
        outcome=outcome,
        reason=_text(value.get("reason"), "previous_action.reason"),
    )


def _parse_region_updates(raw: Any, state: RegionHarnessState) -> list[RegionUpdate]:
    updates: list[RegionUpdate] = []
    for index, item in enumerate(_array(raw, "region_updates")):
        value = _object(item, f"region_updates[{index}]")
        status = _text(value.get("status"), f"region_updates[{index}].status").casefold()
        region_ref = _text(
            value.get("region_ref"), f"region_updates[{index}].region_ref", required=False)
        candidate_raw = value.get("candidate")
        if status == "known":
            if region_ref not in state.regions:
                raise ValueError(f"unknown region_ref: {region_ref}")
            if candidate_raw is not None:
                raise ValueError("known region update must not include candidate")
            candidate = None
        elif status == "new":
            if region_ref:
                raise ValueError("new region update must not allocate region_ref")
            candidate = _object(candidate_raw, f"region_updates[{index}].candidate")
            _text(candidate.get("name"), "new region candidate.name")
        elif status == "uncertain":
            if region_ref and region_ref not in state.regions:
                raise ValueError(f"unknown region_ref: {region_ref}")
            candidate = None
        else:
            raise ValueError("region update status is invalid")
        updates.append(RegionUpdate(status, region_ref, candidate))
    return updates


def _parse_next(raw: Any, state: RegionHarnessState) -> NextAction | None:
    if raw is None:
        return None
    value = _object(raw, "next_action")
    operation_ref = _text(value.get("operation_ref"), "next_action.operation_ref")
    binding = state.operations.get(operation_ref)
    if binding is None:
        raise ValueError(f"unknown operation_ref: {operation_ref}")
    region_ref = _text(value.get("region_ref"), "next_action.region_ref")
    canonical_ref = _text(
        value.get("canonical_operation_ref"), "next_action.canonical_operation_ref")
    if binding.region_ref != region_ref:
        raise ValueError(f"operation_ref {operation_ref} does not own region_ref {region_ref}")
    if binding.canonical_operation_ref != canonical_ref:
        raise ValueError(
            f"operation_ref {operation_ref} does not own canonical_operation_ref {canonical_ref}")
    purpose = _text(value.get("purpose"), "next_action.purpose").casefold()
    if purpose not in PURPOSES:
        raise ValueError("next_action.purpose is invalid")
    if operation_ref in state.terminal_no_effect_operations:
        raise ValueError(f"operation_ref {operation_ref} is terminal after no_effect")
    if operation_ref in state.deferred_operations:
        raise ValueError(f"operation_ref {operation_ref} is deferred: {state.deferred_operations[operation_ref]}")
    return NextAction(
        region_ref=region_ref,
        canonical_operation_ref=canonical_ref,
        operation_ref=operation_ref,
        purpose=purpose,
        reason=_text(value.get("reason"), "next_action.reason"),
    )


def parse_turn(
    raw: Mapping[str, Any],
    state: RegionHarnessState,
    pending_ref: str,
) -> HarnessTurn:
    """Parse a Luna turn without letting it create or reinterpret refs."""
    if not isinstance(raw, Mapping):
        raise ValueError("turn must be an object")
    previous = _parse_previous(raw.get("previous_action"))
    if bool(pending_ref) != (previous is not None):
        expected = "an object" if pending_ref else "null"
        raise ValueError(f"previous_action must be {expected}")
    if previous is not None and previous.attempt_ref != pending_ref:
        raise ValueError(
            f"previous_action.attempt_ref must equal pending {pending_ref}")
    next_action = _parse_next(raw.get("next_action"), state)
    finish = raw.get("finish")
    if not isinstance(finish, bool):
        raise ValueError("finish must be boolean")
    return HarnessTurn(
        previous_action=previous,
        region_updates=_parse_region_updates(raw.get("region_updates"), state),
        next_action=next_action,
        finish=finish,
        reason=_text(raw.get("reason"), "reason"),
    )


def register_new_candidates(
    turn: HarnessTurn,
    state: RegionHarnessState,
) -> list[OperationBinding]:
    """Allocate all new Region/Variant/Operation refs after parsing succeeds."""
    created: list[OperationBinding] = []
    for update in turn.region_updates:
        if update.status != "new" or update.candidate is None:
            continue
        region_ref = state.mint("region")
        variant_ref = state.mint("region_variant")
        state.regions[region_ref] = {
            "name": _text(update.candidate.get("name"), "new region candidate.name"),
            "variant_ref": variant_ref,
        }
        raw_operations = update.candidate.get("operations", [])
        for index, raw_operation in enumerate(_array(raw_operations, "new region candidate.operations")):
            item = _object(raw_operation, f"new operation[{index}]")
            action = _text(item.get("action"), "new operation.action").casefold()
            if action not in ACTION_KINDS:
                raise ValueError("new operation.action is invalid")
            target = _text(item.get("target"), "new operation.target")
            canonical_ref = state.mint("canonical_operation")
            operation_ref = state.mint("operation")
            state.canonical_operations[canonical_ref] = {
                "region_ref": region_ref,
                "action": action,
                "target": target,
            }
            binding = OperationBinding(
                region_ref=region_ref,
                canonical_operation_ref=canonical_ref,
                operation_ref=operation_ref,
                action=action,
                target=target,
                variant_ref=variant_ref,
                direction=_text(item.get("direction"), "new operation.direction", required=False).casefold(),
            )
            state.operations[operation_ref] = binding
            created.append(binding)
    return created


def settle_no_effect(state: RegionHarnessState, operation_ref: str) -> None:
    if operation_ref not in state.operations:
        raise ValueError(f"unknown operation_ref: {operation_ref}")
    state.terminal_no_effect_operations.add(operation_ref)


def to_controller_action(
    binding: OperationBinding,
    grounding: Mapping[str, Any],
) -> dict[str, Any]:
    """Translate only a freshly grounded local binding into controller input."""
    if binding.action == "click":
        try:
            x, y = int(grounding["x"]), int(grounding["y"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("click grounding requires integer x and y") from None
        if x < 0 or y < 0:
            raise ValueError("click grounding coordinates must be non-negative")
        return {"action_type": "CLICK", "parameters": {"x": x, "y": y}}
    if binding.action == "scroll":
        try:
            x, y = int(grounding["x"]), int(grounding["y"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("scroll grounding requires integer x and y") from None
        if binding.direction not in {"up", "down", "left", "right"}:
            raise ValueError("scroll binding requires direction")
        return {
            "action_type": "SCROLL",
            "parameters": {"x": x, "y": y, "direction": binding.direction, "amount": 650},
        }
    if binding.action == "back":
        return {"action_type": "PRESS", "parameters": {"key": "ESC"}}
    if binding.action == "wait":
        return {"action_type": "WAIT", "parameters": {}}
    raise ValueError(f"unsupported controller action: {binding.action}")


def append_teacher_error(
    path: Path,
    *,
    raw_response: Mapping[str, Any],
    screenshot_ref: str,
    correction: str,
    category: str,
    disposition: str,
) -> None:
    """Persist one supervised correction without leaking it into Luna-only data."""
    if category not in {
        "missing_context", "semantic", "schema-owner", "grounding",
        "action-space", "safety-stop", "app_disappeared", "environment_failure",
    }:
        raise ValueError("teacher error category is invalid")
    if disposition not in {"prompt", "retrieval", "gate", "grounder"}:
        raise ValueError("teacher error disposition is invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "raw_luna_response": raw_response,
        "screenshot_ref": screenshot_ref,
        "minimal_correction": correction,
        "category": category,
        "disposition": disposition,
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_completion(
    *,
    teacher_mode: bool,
    status: str,
    stop_reason: str,
    actions: int,
    gaps: Sequence[str],
) -> dict[str, Any]:
    """Keep supervised pilots explicitly separate from Luna-only acceptance."""
    if status not in {"complete", "partial"}:
        raise ValueError("completion status is invalid")
    return {
        "schema": "luna_region_harness.v1",
        "status": status,
        "stop_reason": stop_reason,
        "actions": actions,
        "gaps": list(gaps),
        "evidence_class": (
            "teacher_student_live_pilot" if teacher_mode
            else "luna_only_live_acceptance"
        ),
        "luna_only_acceptance": not teacher_mode,
    }


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(dict(payload), ensure_ascii=False) + "\n")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _is_grounding_safe(grounding: Mapping[str, Any]) -> bool:
    return all(grounding.get(key) is True for key in (
        "target_visible", "identity_matches", "unique", "safe"))


def run_pilot(
    *,
    root: Path,
    controller: Any,
    planner: Any,
    grounder: Any,
    teacher_mode: bool,
    max_actions: int,
    max_turns: int,
) -> dict[str, Any]:
    """Run the smallest supervised loop against a controller-like object.

    The injected planner and grounder make the control boundary testable. The
    live CLI below supplies Luna API callables; this loop owns only facts,
    action evidence, ref gates, and the completion boundary.
    """
    root.mkdir(parents=True, exist_ok=True)
    status = controller.status()
    if status.get("status") != "ready":
        raise RuntimeError("controller is not ready")
    current = Path(_text(status.get("current_frame"), "controller.current_frame"))
    state = RegionHarnessState()
    pending: dict[str, Any] | None = None
    gaps: list[str] = []
    actions = 0
    stop_reason = "turn_limit"
    correction = ""
    rejection_count = 0
    finish_rejection_count = 0
    grounding_rejection_count = 0

    for turn_number in range(1, max_turns + 1):
        if not current.exists():
            gaps.append("environment_failure: current screenshot is unavailable")
            stop_reason = "screenshot_unavailable"
            break
        dynamic = DynamicInput(
            screenshot=current.read_bytes(),
            step=f"turn {turn_number}",
            pending_result=(
                {"attempt_ref": pending["attempt_ref"], "action": pending["action"]}
                if pending else None
            ),
            short_diff=correction,
            before_screenshot=(
                Path(pending["before_ref"]).read_bytes()
                if pending and Path(pending["before_ref"]).exists() else None
            ),
        )
        raw = planner(state, dynamic)
        try:
            turn = parse_turn(
                raw, state, pending_ref=(pending or {}).get("attempt_ref", ""))
        except ValueError as exc:
            rejection_count += 1
            issue = str(exc)
            correction = "Harness rejected the last response: " + issue
            if issue == "new region update must not allocate region_ref":
                correction += (
                    '. For status="new", send region_ref="" exactly and put '
                    "the semantic description only in candidate."
                )
            _append_jsonl(root / "harness_rejections.jsonl", {
                "turn": turn_number,
                "reason": correction,
                "raw_luna_response": raw,
                "screenshot_ref": str(current),
            })
            if teacher_mode:
                append_teacher_error(
                    root / "teacher_error_log.jsonl",
                    raw_response=raw,
                    screenshot_ref=str(current),
                    correction=correction,
                    category="schema-owner",
                    disposition="gate",
                )
            if rejection_count >= 3:
                gaps.append("schema-owner: three rejected responses without progress")
                stop_reason = "schema_rejection_budget"
                break
            continue
        correction = ""
        rejection_count = 0
        created = register_new_candidates(turn, state)

        if pending is not None:
            outcome = turn.previous_action.outcome if turn.previous_action else ""
            operation_ref = str(pending["operation_ref"])
            if outcome == "no_effect":
                settle_no_effect(state, operation_ref)
                state.completed_operations.add(operation_ref)
            elif outcome == "success":
                state.completed_operations.add(operation_ref)
            elif outcome in {"failed", "uncertain"}:
                gaps.append(f"{outcome}: {operation_ref}")
            _append_jsonl(root / "attempts.jsonl", {
                **pending,
                "outcome": outcome,
                "settlement_reason": turn.previous_action.reason if turn.previous_action else "",
            })
            pending = None

        if turn.finish:
            open_operations = [
                item.operation_ref for item in state.operations.values()
                if item.operation_ref not in state.completed_operations
                and item.operation_ref not in state.terminal_no_effect_operations
                and item.operation_ref not in state.deferred_operations
            ]
            if open_operations:
                finish_rejection_count += 1
                correction = (
                    "Harness rejected finish: these known operations are still open: "
                    + ", ".join(open_operations)
                    + ". Continue with one safe known operation; do not finish yet."
                )
                _append_jsonl(root / "harness_rejections.jsonl", {
                    "turn": turn_number,
                    "reason": correction,
                    "raw_luna_response": raw,
                    "screenshot_ref": str(current),
                })
                if teacher_mode:
                    append_teacher_error(
                        root / "teacher_error_log.jsonl",
                        raw_response=raw,
                        screenshot_ref=str(current),
                        correction=correction,
                        category="semantic",
                        disposition="gate",
                    )
                if finish_rejection_count >= 3:
                    gaps.extend(f"open operation: {item}" for item in open_operations)
                    stop_reason = "finish_rejection_budget"
                    break
                continue
            stop_reason = "complete"
            break

        if actions >= max_actions:
            stop_reason = "action_budget"
            break
        if turn.next_action is None:
            if created:
                continue
            stop_reason = "planner_no_action"
            gaps.append("planner supplied neither a finish nor an executable known operation")
            break

        binding = state.operations[turn.next_action.operation_ref]
        grounding = (
            {
                "target_visible": True,
                "identity_matches": True,
                "unique": True,
                "safe": True,
                "x": 0,
                "y": 0,
                "reason": "non-pointer action does not require grounding",
            }
            if binding.action in {"back", "wait"}
            else grounder(binding, current)
        )
        if not _is_grounding_safe(grounding):
            reason = _text(grounding.get("reason"), "grounding.reason", required=False)
            failure_kind = (
                "safety-stop" if reason.startswith("safety-stop:")
                else "grounding_error"
            )
            if failure_kind == "safety-stop":
                state.deferred_operations[binding.operation_ref] = reason
                correction = (
                    f"Harness deferred {binding.operation_ref} for safety: {reason}. "
                    "Do not repeat it; choose another non-deferred known operation."
                )
            else:
                correction = (
                    f"Grounding could not safely locate {binding.operation_ref}: {reason}. "
                    "Use the latest screenshot to choose a different known operation or report a new candidate."
                )
            _append_jsonl(root / "grounding_calls.jsonl", {
                "operation_ref": binding.operation_ref,
                "screenshot": str(current),
                "grounding": dict(grounding),
            })
            _append_jsonl(root / "harness_rejections.jsonl", {
                "turn": turn_number,
                "reason": correction,
                "raw_luna_response": raw,
                "screenshot_ref": str(current),
            })
            if teacher_mode:
                append_teacher_error(
                    root / "teacher_error_log.jsonl",
                    raw_response=raw,
                    screenshot_ref=str(current),
                    correction=correction,
                    category=("safety-stop" if failure_kind == "safety-stop" else "grounding"),
                    disposition=("gate" if failure_kind == "safety-stop" else "grounder"),
                )
            grounding_rejection_count += 1
            if grounding_rejection_count >= 3:
                gaps.append(f"{failure_kind}: {binding.operation_ref}: {reason}")
                stop_reason = "grounding_replan_budget"
                break
            continue
        grounding_rejection_count = 0
        controller_record = controller.action(to_controller_action(binding, grounding))
        attempt_ref = state.mint("attempt")
        pending = {
            "attempt_ref": attempt_ref,
            "controller_attempt_ref": _text(
                controller_record.get("attempt_id"), "controller.attempt_id"),
            "operation_ref": binding.operation_ref,
            "canonical_operation_ref": binding.canonical_operation_ref,
            "region_ref": binding.region_ref,
            "action": to_controller_action(binding, grounding),
            "before_ref": _text(controller_record.get("before"), "controller.before"),
            "after_ref": _text(controller_record.get("after"), "controller.after"),
            "controller_error": _text(
                controller_record.get("controller_error"), "controller.controller_error", required=False),
        }
        actions += 1
        _append_jsonl(root / "grounding_calls.jsonl", {
            "operation_ref": binding.operation_ref,
            "screenshot": str(current),
            "grounding": dict(grounding),
        })
        if pending["controller_error"]:
            gaps.append("environment_failure: " + pending["controller_error"])
            stop_reason = "controller_error"
            _append_jsonl(root / "attempts.jsonl", pending)
            pending = None
            break
        current = Path(pending["after_ref"])
    else:
        stop_reason = "turn_limit"

    if pending is not None:
        gaps.append(f"pending action: {pending['attempt_ref']}")
    for operation_ref in state.deferred_operations:
        gap = f"safety-stop: {operation_ref}"
        if gap not in gaps:
            gaps.append(gap)
    status_name = "complete" if stop_reason == "complete" and not gaps else "partial"
    completion = build_completion(
        teacher_mode=teacher_mode,
        status=status_name,
        stop_reason=stop_reason,
        actions=actions,
        gaps=gaps,
    )
    _write_json(root / "completion.json", completion)
    _write_json(root / "region_graph.json", {
        "schema": "luna_region_harness_graph.v1",
        "regions": state.regions,
        "canonical_operations": state.canonical_operations,
        "operation_bindings": state.operation_cards(),
        "completed_operations": sorted(state.completed_operations),
        "terminal_no_effect_operations": sorted(state.terminal_no_effect_operations),
        "deferred_operations": state.deferred_operations,
    })
    return completion


TURN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "previous_action": {
            "anyOf": [
                {"type": "null"},
                {"type": "object", "properties": {
                    "attempt_ref": {"type": "string"},
                    "outcome": {"type": "string", "enum": sorted(OUTCOMES)},
                    "reason": {"type": "string"},
                }, "required": ["attempt_ref", "outcome", "reason"], "additionalProperties": False},
            ],
        },
        "region_updates": {"type": "array", "items": {
            "type": "object", "properties": {
                "status": {"type": "string", "enum": ["known", "new", "uncertain"]},
                "region_ref": {"type": "string"},
                "candidate": {"anyOf": [
                    {"type": "null"},
                    {"type": "object", "properties": {
                        "name": {"type": "string"},
                        "operations": {"type": "array", "items": {
                            "type": "object", "properties": {
                                "action": {"type": "string", "enum": sorted(ACTION_KINDS)},
                                "target": {"type": "string"},
                                "direction": {"type": "string"},
                            }, "required": ["action", "target", "direction"], "additionalProperties": False,
                        }},
                    }, "required": ["name", "operations"], "additionalProperties": False},
                ]},
            }, "required": ["status", "region_ref", "candidate"], "additionalProperties": False,
        }},
        "next_action": {"anyOf": [
            {"type": "null"},
            {"type": "object", "properties": {
                "region_ref": {"type": "string"},
                "canonical_operation_ref": {"type": "string"},
                "operation_ref": {"type": "string"},
                "purpose": {"type": "string", "enum": sorted(PURPOSES)},
                "reason": {"type": "string"},
            }, "required": [
                "region_ref", "canonical_operation_ref", "operation_ref", "purpose", "reason",
            ], "additionalProperties": False},
        ]},
        "finish": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["previous_action", "region_updates", "next_action", "finish", "reason"],
    "additionalProperties": False,
}

GROUND_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target_visible": {"type": "boolean"},
        "identity_matches": {"type": "boolean"},
        "unique": {"type": "boolean"},
        "safe": {"type": "boolean"},
        "x": {"type": "integer"},
        "y": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["target_visible", "identity_matches", "unique", "safe", "x", "y", "reason"],
    "additionalProperties": False,
}


class ControllerClient:
    """The narrow HTTP boundary used by the existing isolated pilot controller."""

    def __init__(self, port: int) -> None:
        self.base_url = f"http://127.0.0.1:{int(port)}"

    def _request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict) or result.get("error"):
            raise RuntimeError(str(result.get("error") if isinstance(result, dict) else "controller response"))
        return result

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/status")

    def action(self, action: Mapping[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/action", action)


def _safe_reversible_operation(binding: OperationBinding) -> bool:
    target = binding.target.casefold()
    forbidden = ("add", "create", "save", "delete", "remove", "apply", "confirm", "install", "send")
    if any(word in target for word in forbidden):
        return False
    return binding.action in ACTION_KINDS


def _log_call(
    root: Path,
    *,
    role: str,
    messages: Sequence[Mapping[str, Any]],
    response: Mapping[str, Any],
    telemetry: Mapping[str, Any],
) -> None:
    _append_jsonl(root / "prompt_calls.jsonl", {
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "role": role,
        "messages": messages,
        "parsed_response": response,
        "telemetry": telemetry,
        "store": False,
    })


def run_live(args: argparse.Namespace) -> dict[str, Any]:
    """Adapt the testable loop to Luna API and the existing controller service."""
    from gui_rewalk.src.core.explore.api_config import (
        load_explore_api_config,
        local_explore_api_config_path,
    )

    root = Path(args.run_root).resolve()
    config = load_explore_api_config(local_explore_api_config_path())
    if config.model != "gpt-5.6-luna":
        raise ValueError("live harness requires model=gpt-5.6-luna")
    client = LunaResponses(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
        timeout=config.timeout_seconds,
    )
    teacher_feedback = _text(args.teacher_feedback, "teacher_feedback", required=False)

    def planner(state: RegionHarnessState, dynamic: DynamicInput) -> dict[str, Any]:
        prompted = DynamicInput(
            screenshot=dynamic.screenshot,
            step=dynamic.step,
            pending_result=dynamic.pending_result,
            short_diff=(dynamic.short_diff + ("\nTeacher feedback: " + teacher_feedback if teacher_feedback else "")),
            before_screenshot=dynamic.before_screenshot,
        )
        messages = build_messages(state, prompted)
        response, telemetry = client.call(
            role="luna_region_planner", messages=messages, schema=TURN_SCHEMA)
        _log_call(root, role="luna_region_planner", messages=messages, response=response, telemetry=telemetry)
        effective = str(telemetry.get("effective_model") or "")
        if effective and not effective.startswith("gpt-5.6-luna"):
            raise RuntimeError("effective model is not gpt-5.6-luna")
        return response

    def grounder(binding: OperationBinding, frame: Path) -> dict[str, Any]:
        messages = [
            {"role": "developer", "content": [{"type": "input_text", "text": (
                "You are a fresh-frame GUI grounder. Do not plan or allocate IDs. "
                "Return raw pixel coordinates only for this supplied local binding; "
                "return false flags when it is absent, ambiguous, unsafe, or background-obscured."
            )}]},
            {"role": "user", "content": [
                {"type": "input_text", "text": json.dumps({
                    "operation_ref": binding.operation_ref,
                    "canonical_operation_ref": binding.canonical_operation_ref,
                    "region_ref": binding.region_ref,
                    "action": binding.action,
                    "target": binding.target,
                    "direction": binding.direction,
                }, ensure_ascii=False)},
                {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(frame.read_bytes()).decode("ascii")},
            ]},
        ]
        response, telemetry = client.call(
            role="luna_fresh_grounder", messages=messages, schema=GROUND_SCHEMA)
        _log_call(root, role="luna_fresh_grounder", messages=messages, response=response, telemetry=telemetry)
        return response

    def guarded_grounder(binding: OperationBinding, frame: Path) -> dict[str, Any]:
        if not _safe_reversible_operation(binding):
            return {
                "target_visible": False, "identity_matches": False,
                "unique": False, "safe": False, "x": 0, "y": 0,
                "reason": "safety-stop: persistent or external action is forbidden in this pilot",
            }
        return grounder(binding, frame)

    completion = run_pilot(
        root=root,
        controller=ControllerClient(args.port),
        planner=planner,
        grounder=guarded_grounder,
        teacher_mode=bool(args.teacher_mode),
        max_actions=args.max_actions,
        max_turns=args.max_turns,
    )
    if teacher_feedback:
        append_teacher_error(
            root / "teacher_error_log.jsonl",
            raw_response={},
            screenshot_ref="",
            correction=teacher_feedback,
            category=args.teacher_category,
            disposition=args.teacher_disposition,
        )
    return completion


def main() -> int:
    parser = argparse.ArgumentParser(description="Standalone Luna Region harness")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--max-actions", type=int, default=40)
    parser.add_argument("--max-turns", type=int, default=120)
    parser.add_argument("--teacher-mode", action="store_true")
    parser.add_argument("--teacher-feedback", default="")
    parser.add_argument("--teacher-category", default="semantic", choices=[
        "missing_context", "semantic", "schema-owner", "grounding",
        "action-space", "safety-stop", "app_disappeared", "environment_failure",
    ])
    parser.add_argument("--teacher-disposition", default="prompt", choices=[
        "prompt", "retrieval", "gate", "grounder",
    ])
    args = parser.parse_args()
    completion = run_live(args)
    print(json.dumps(completion, ensure_ascii=False, indent=2))
    return 0 if completion["status"] == "complete" else 3


__all__ = [
    "CompiledRoute", "ControllerClient", "DynamicInput", "HarnessTurn", "LunaResponses", "NextAction", "OperationBinding", "PreviousAction",
    "RegionHarnessState", "RegionUpdate", "append_teacher_error",
    "build_completion", "build_messages", "parse_turn", "register_new_candidates", "settle_no_effect", "to_controller_action",
    "run_pilot",
]


if __name__ == "__main__":
    raise SystemExit(main())
