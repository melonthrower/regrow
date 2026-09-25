"""Strict, additive device fixtures for one visual-collection scenario."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping


SCHEMA = "guitraverse.scenario_delta.v1"
_ROOT_FIELDS = {"schema", "task_id", "base_snapshot", "mutations", "assertions"}
_PHONE_PREFIX = "55501"
_MAX_TEXT_LENGTH = 4096
_SAFE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_SMS_ADDRESS = re.compile(r"(?:^|[\s,])address=([^,\s]+)(?=,|$)")
_SMS_BODY = re.compile(r"(?:^|[\s,])body=(.*)$")


class DeltaError(ValueError):
    """Raised when a scenario delta is malformed or cannot be safely applied."""


@dataclass(frozen=True)
class ScenarioMutation:
    kind: str
    sender: str = ""
    body: str = ""
    path: str = ""
    content: str = ""


@dataclass(frozen=True)
class ScenarioAssertion:
    kind: str
    recipient: str = ""
    path: str = ""
    from_slot: str = ""


@dataclass(frozen=True)
class ScenarioDelta:
    schema: str
    task_id: str
    base_snapshot: str
    mutations: tuple[ScenarioMutation, ...]
    assertions: tuple[ScenarioAssertion, ...]
    digest: str


def load_scenario_delta(path: str | Path) -> ScenarioDelta:
    """Load one schema-v1, additive-only scenario delta."""
    try:
        with Path(path).open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise DeltaError(f"unable to load scenario delta: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise DeltaError("scenario delta root must be an object")
    if set(payload) != _ROOT_FIELDS:
        raise DeltaError("scenario delta root fields must match schema v1 exactly")
    if payload["schema"] != SCHEMA:
        raise DeltaError(f"unsupported scenario delta schema: {payload['schema']!r}")

    task_id = _required_text(payload["task_id"], "task_id")
    base_snapshot = _required_text(payload["base_snapshot"], "base_snapshot")
    mutations = _load_mutations(payload["mutations"])
    assertions = _load_assertions(payload["assertions"])
    canonical = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return ScenarioDelta(
        schema=SCHEMA,
        task_id=task_id,
        base_snapshot=base_snapshot,
        mutations=mutations,
        assertions=assertions,
        digest=hashlib.sha256(canonical).hexdigest(),
    )


def apply_scenario_delta(
    delta: ScenarioDelta, device: Any, expected_snapshot: str,
) -> dict[str, Any]:
    """Apply only declared additive mutations after an exact snapshot guard."""
    if delta.base_snapshot != expected_snapshot:
        raise DeltaError(
            f"base_snapshot mismatch: expected {delta.base_snapshot!r}, got {expected_snapshot!r}"
        )
    items = []
    for mutation in delta.mutations:
        if mutation.kind == "inbound_sms":
            device.run(
                "emu", "sms", "send", mutation.sender, mutation.body,
                timeout=30, check=True,
            )
            observed = device.run(
                "shell", "content", "query", "--uri", "content://sms/inbox",
                "--projection", "address:body",
                timeout=30, check=True,
            )
            items.append({
                "kind": mutation.kind,
                "ok": _sms_row_contains(observed, mutation.sender, mutation.body),
                "sender": mutation.sender,
            })
        else:
            remote = _remote_path(mutation.path)
            device.run(
                "shell", "mkdir", "-p", remote.rsplit("/", 1)[0],
                timeout=30, check=True,
            )
            with tempfile.TemporaryDirectory(prefix="scenario_delta_") as directory:
                local = Path(directory) / "content"
                local.write_text(mutation.content, encoding="utf-8")
                device.push(local, remote)
            observed = device.run("shell", "cat", remote, timeout=30, check=True)
            items.append({
                "kind": mutation.kind,
                "ok": observed == mutation.content,
                "path": mutation.path,
            })
    return _report(delta, items, "guitraverse.scenario_setup.v1")


def evaluate_scenario_delta(
    delta: ScenarioDelta, device: Any, bindings: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate declared assertions without treating failed evidence as success."""
    _validate_bindings(bindings)
    items = []
    for assertion in delta.assertions:
        if assertion.from_slot not in bindings:
            raise DeltaError(f"binding is missing required slot: {assertion.from_slot}")
        expected = str(bindings[assertion.from_slot])
        if assertion.kind == "outgoing_sms_equals":
            observed = device.run(
                "shell", "content", "query", "--uri", "content://sms/sent",
                "--projection", "address:body",
                timeout=30, check=True,
            )
            items.append({
                "kind": assertion.kind,
                "ok": _sms_row_contains(observed, assertion.recipient, expected),
                "recipient": assertion.recipient,
                "from_slot": assertion.from_slot,
            })
        else:
            observed = device.run(
                "shell", "cat", _remote_path(assertion.path), timeout=30, check=True,
            )
            items.append({
                "kind": assertion.kind,
                "ok": observed == expected,
                "path": assertion.path,
                "from_slot": assertion.from_slot,
            })
    return _report(delta, items, "guitraverse.scenario_evaluation.v1")


def _load_mutations(value: Any) -> tuple[ScenarioMutation, ...]:
    if not isinstance(value, list):
        raise DeltaError("mutations must be a list")
    loaded = []
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("kind"), str):
            raise DeltaError("mutation must be an object with a kind")
        if item["kind"] == "inbound_sms":
            _require_exact_fields(item, {"kind", "sender", "body"}, "inbound_sms")
            loaded.append(ScenarioMutation(
                kind="inbound_sms",
                sender=_phone(item["sender"], "sender"),
                body=_required_text(item["body"], "body", limit=_MAX_TEXT_LENGTH),
            ))
        elif item["kind"] == "text_file":
            _require_exact_fields(item, {"kind", "path", "content"}, "text_file")
            loaded.append(ScenarioMutation(
                kind="text_file",
                path=_scenario_path(item["path"]),
                content=_text(item["content"], "content", limit=_MAX_TEXT_LENGTH),
            ))
        else:
            raise DeltaError(f"unsupported mutation kind: {item['kind']!r}")
    return tuple(loaded)


def _load_assertions(value: Any) -> tuple[ScenarioAssertion, ...]:
    if not isinstance(value, list):
        raise DeltaError("assertions must be a list")
    loaded = []
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("kind"), str):
            raise DeltaError("assertion must be an object with a kind")
        if item["kind"] == "outgoing_sms_equals":
            _require_exact_fields(item, {"kind", "recipient", "from_slot"}, "outgoing_sms_equals")
            loaded.append(ScenarioAssertion(
                kind="outgoing_sms_equals",
                recipient=_phone(item["recipient"], "recipient"),
                from_slot=_required_text(item["from_slot"], "from_slot"),
            ))
        elif item["kind"] == "file_text_equals":
            _require_exact_fields(item, {"kind", "path", "from_slot"}, "file_text_equals")
            loaded.append(ScenarioAssertion(
                kind="file_text_equals",
                path=_scenario_path(item["path"]),
                from_slot=_required_text(item["from_slot"], "from_slot"),
            ))
        else:
            raise DeltaError(f"unsupported assertion kind: {item['kind']!r}")
    return tuple(loaded)


def _require_exact_fields(item: Mapping[str, Any], fields: set[str], kind: str) -> None:
    if set(item) != fields:
        raise DeltaError(f"{kind} fields must match schema v1 exactly")


def _required_text(value: Any, label: str, *, limit: int = _MAX_TEXT_LENGTH) -> str:
    text = _text(value, label, limit=limit)
    if not text:
        raise DeltaError(f"{label} must be non-empty")
    return text


def _text(value: Any, label: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise DeltaError(f"{label} must be a string")
    if len(value) > limit:
        raise DeltaError(f"{label} exceeds {limit} characters")
    return value


def _phone(value: Any, label: str) -> str:
    number = _required_text(value, label)
    if len(number) != 7 or not number.startswith(_PHONE_PREFIX) or not number.isdigit():
        raise DeltaError(f"{label} must use a reserved 55501xx number")
    return number


def _scenario_path(value: Any) -> str:
    path = _required_text(value, "path")
    if not path.isascii() or "\\" in path or path.startswith("/"):
        raise DeltaError("path must be a relative ASCII POSIX path")
    parts = path.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise DeltaError("path cannot contain empty or dot segments")
    if any(_SAFE_PATH_SEGMENT.fullmatch(part) is None for part in parts):
        raise DeltaError("path segments must use safe ASCII filename characters")
    allowed = (
        len(parts) >= 3 and parts[:2] == ["Documents", "GUITRAVERSE"]
    ) or (
        len(parts) >= 4 and parts[:3] == ["Documents", "Markor", "GUITRAVERSE"]
    )
    if not allowed or not path.endswith((".txt", ".md")):
        raise DeltaError("path must be under an allowed GUITRAVERSE directory with .txt or .md")
    return path


def _remote_path(path: str) -> str:
    return "/sdcard/" + path


def _sms_row_contains(output: Any, address: str, body: str) -> bool:
    for line in str(output).splitlines():
        address_match = _SMS_ADDRESS.search(line)
        body_match = _SMS_BODY.search(line)
        if (
            address_match is not None
            and body_match is not None
            and address_match.group(1) == address
            and body_match.group(1) == body
        ):
            return True
    return False


def _validate_bindings(bindings: Mapping[str, Any]) -> None:
    if not isinstance(bindings, Mapping):
        raise DeltaError("bindings must be a mapping")
    for slot, value in bindings.items():
        if not isinstance(slot, str) or not slot:
            raise DeltaError("binding slots must be non-empty strings")
        if isinstance(value, str):
            if not value:
                raise DeltaError(f"binding {slot!r} must be non-empty")
        elif isinstance(value, bool) or isinstance(value, int):
            continue
        elif isinstance(value, float) and math.isfinite(value):
            continue
        else:
            raise DeltaError(f"binding {slot!r} must be a non-empty scalar")


def _report(
    delta: ScenarioDelta, items: list[dict[str, Any]], report_schema: str,
) -> dict[str, Any]:
    return {
        "schema": report_schema,
        "task_id": delta.task_id,
        "digest": delta.digest,
        "ok": all(item["ok"] for item in items),
        "items": items,
    }
