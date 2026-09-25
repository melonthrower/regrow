"""Append-only, JSON-safe evidence for an ActionAttempt's observed effect."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, Iterable, List


EFFECT_OBSERVATION_SCHEMA = "gui_rewalk.effect_observation.v1"
EFFECT_KINDS = {
    "navigation", "state_change", "region_introduction", "object_creation",
    "object_removal", "query_result", "no_effect", "blocked", "error", "uncertain",
}
VERDICTS = {"supported", "refuted", "inconclusive"}
_PARAMETER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")



class EffectObservationValidationError(ValueError):
    """Raised when effect evidence cannot be safely interpreted."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def valid_parameter_name(value: Any) -> bool:
    """Return whether a binding name can be consumed by recipe placeholders."""
    return isinstance(value, str) and bool(_PARAMETER_NAME.fullmatch(value))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise EffectObservationValidationError(
        f"effect observation contains non-JSON value: {type(value).__name__}")


def _normalize_changes(raw: Any, *, required: bool) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        raise EffectObservationValidationError("observed_changes must be a list")
    changes: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise EffectObservationValidationError("each observed change must be a dict")
        scope = item.get("scope")
        if not isinstance(scope, dict):
            raise EffectObservationValidationError("observed change scope must be a dict")
        region_ref = _text(scope.get("region_ref"))
        fact = _text(item.get("fact"))
        if required and not region_ref:
            raise EffectObservationValidationError(
                "supported effect observation requires scope.region_ref")
        if required and not fact:
            raise EffectObservationValidationError(
                "supported effect observation requires observed_changes[].fact")
        if required and ("before" not in item or "after" not in item):
            raise EffectObservationValidationError(
                "supported effect observation requires before and after")
        normalized_scope = {"region_ref": region_ref}
        for key in ("page_id", "variant_id", "state_id"):
            if key in scope:
                normalized_scope[key] = _text(scope.get(key))
        changes.append({
            "scope": normalized_scope,
            "fact": fact,
            "before": _json_safe(item.get("before")),
            "after": _json_safe(item.get("after")),
        })
    if required and not changes:
        raise EffectObservationValidationError(
            "supported effect observation requires observed_changes")
    return changes


def normalize_effect_observation(raw: Any) -> Dict[str, Any]:
    """Validate and normalize one observation without touching its attempt.

    A supported observation is intentionally strict: it must name a capability,
    explain the inference, and ground each changed fact in a durable Region ref.
    Non-supported terminal observations may omit those business-effect details.
    """
    if not isinstance(raw, dict):
        raise EffectObservationValidationError("effect observation must be a dict")
    schema_version = _text(raw.get("schema_version") or raw.get("schema"))
    if schema_version and schema_version != EFFECT_OBSERVATION_SCHEMA:
        raise EffectObservationValidationError(
            f"unsupported effect observation schema: {schema_version}")
    effect_kind = _text(raw.get("effect_kind")).lower()
    verdict = _text(raw.get("verdict")).lower()
    if effect_kind not in EFFECT_KINDS:
        raise EffectObservationValidationError(f"unsupported effect_kind: {effect_kind}")
    if verdict not in VERDICTS:
        raise EffectObservationValidationError(f"unsupported verdict: {verdict}")
    bindings = raw.get("parameter_bindings")
    if bindings is None:
        bindings = {}
    if not isinstance(bindings, dict):
        raise EffectObservationValidationError("parameter_bindings must be a dict")
    normalized_bindings: Dict[str, Any] = {}
    for raw_name, raw_value in bindings.items():
        if not valid_parameter_name(raw_name):
            raise EffectObservationValidationError(
                "parameter binding names must be portable identifiers")
        value = _json_safe(raw_value)
        if value is None or isinstance(value, (dict, list)):
            raise EffectObservationValidationError(
                "parameter binding values must be non-null JSON scalars")
        normalized_bindings[raw_name] = value
    supported_business_effect = (
        verdict == "supported"
        and effect_kind in {
            "state_change", "object_creation", "object_removal", "query_result"}
    )
    capability_name = _text(raw.get("capability_name"))
    reason = _text(raw.get("reason"))
    predicate_candidate = _text(raw.get("predicate_candidate"))
    if supported_business_effect and not capability_name:
        raise EffectObservationValidationError(
            "supported effect observation requires capability_name")
    if supported_business_effect and not reason:
        raise EffectObservationValidationError(
            "supported effect observation requires reason")
    if supported_business_effect and not predicate_candidate:
        raise EffectObservationValidationError(
            "supported effect observation requires predicate_candidate")
    return {
        "schema_version": EFFECT_OBSERVATION_SCHEMA,
        "capability_name": capability_name,
        "reason": reason,
        "effect_kind": effect_kind,
        "observed_changes": _normalize_changes(
            raw.get("observed_changes") if raw.get("observed_changes") is not None else [],
            required=supported_business_effect),
        "parameter_bindings": normalized_bindings,
        "predicate_candidate": predicate_candidate,
        "verdict": verdict,
    }


def append_effect_observation(
    observations: Iterable[Dict[str, Any]] | None, raw: Any,
) -> List[Dict[str, Any]]:
    """Return a new append-only observation list; never mutate an attempt."""
    normalized = normalize_effect_observation(raw)
    result = [deepcopy(item) for item in (observations or [])]
    result.append(normalized)
    return result
