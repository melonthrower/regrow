"""Shared semantic helpers for reversible stateful controls."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping


def normalize_state_key(value: Any) -> str:
    """Canonicalize equivalent VLM spellings such as ``show_notifications``."""
    return " ".join(
        str(value or "").replace("_", " ").replace("-", " ")
        .casefold().split())


def stateful_candidate_keys_match(expected: Any, current: Any) -> bool:
    """Match one control across observation-local Region/group formatting drift."""
    expected_text = str(expected or "")
    current_text = str(current or "")
    if expected_text == current_text:
        return True
    expected_parts = expected_text.split("|")
    current_parts = current_text.split("|")
    if len(expected_parts) != 4 or len(current_parts) != 4:
        return False
    return (
        expected_parts[0] == current_parts[0]
        and expected_parts[2] == current_parts[2]
        and normalize_state_key(expected_parts[3])
        == normalize_state_key(current_parts[3])
    )


def unresolved_stateful_probe_requires_restore(
    evidence: Mapping[str, Any] | None,
    *,
    outcome: Any,
    committed: bool,
) -> bool:
    """Recognize a safe probe whose physical effect is still unresolved."""
    facts = evidence or {}
    try:
        pixel_distance = int(facts.get("post_action_phash_distance") or 0)
    except (TypeError, ValueError):
        pixel_distance = 0
    risk = " ".join(str(facts.get("risk") or "").casefold().split())
    before_value = str(
        facts.get("before_value") or "").strip().casefold()
    return bool(
        not committed
        and facts.get("stateful") is True
        and str(facts.get("purpose") or "").strip().casefold() == "probe"
        and str(outcome or "").strip().casefold()
        in {"uncertain", "transitioned_inconsistent"}
        and facts.get("fresh_post_action_observation") is True
        and pixel_distance > 0
        and facts.get("reversible") is True
        and risk in {"", "none"}
        and before_value in {"off", "on"}
        and str(facts.get("restore_candidate_key") or "").strip()
    )


def resume_stateful_probe_state(
    transition_events: Iterable[Mapping[str, Any]],
) -> tuple[set[tuple[str, str, str]], dict[str, Any] | None]:
    """Rebuild open reversible-probe state from persisted action evidence."""
    open_mutations: dict[str, dict[str, Any]] = {}
    probe_sources: set[tuple[str, str, str]] = set()
    for event in transition_events:
        evidence = event.get("evidence") or {}
        unresolved_probe = unresolved_stateful_probe_requires_restore(
            evidence,
            outcome=event.get("outcome"),
            committed=bool(event.get("committed")),
        )
        if ((not event.get("committed") and not unresolved_probe)
                or not evidence.get("stateful")):
            continue
        mutation_id = str(evidence.get("mutation_id") or "")
        if not mutation_id:
            continue
        purpose = str(evidence.get("purpose") or "").strip().lower()
        if purpose == "probe":
            source = str(event.get("source") or "")
            state_key = str(evidence.get("state_key") or "")
            before_value = str(evidence.get("before_value") or "unknown")
            probe_sources.add((source, state_key, before_value))
            open_mutations[mutation_id] = {
                "mutation_id": mutation_id,
                "source_state": source,
                "mutated_state": str(event.get("target") or ""),
                "state_key": state_key,
                "before_value": before_value,
                "after_value": (
                    "unknown" if unresolved_probe else
                    str(evidence.get("after_value") or "unknown")),
                "baseline_frame_phash": str(
                    evidence.get("baseline_frame_phash") or ""),
                "probe_candidate_key": str(
                    evidence.get("probe_candidate_key") or ""),
                "restore_candidate_key": str(
                    evidence.get("restore_candidate_key") or ""),
                "restore_before_value": str(
                    evidence.get("restore_before_value") or ""),
                "baseline_candidates": list(
                    evidence.get("baseline_candidates") or []),
                "explore_local_functions": bool(
                    False if unresolved_probe else
                    evidence.get("explore_local_functions", True)),
            }
        elif purpose == "restore":
            open_mutations.pop(mutation_id, None)
    active_mutation = (
        list(open_mutations.values())[-1] if open_mutations else None)
    return probe_sources, active_mutation


def is_active_restore_candidate(
    active: Mapping[str, Any] | None,
    element: Any,
    *,
    candidate_key: Callable[[Any], str],
) -> bool:
    """Match the live inverse using the already-approved probe contract.

    The original function-set probe established safety. A later inventory may
    spell the state key differently or downgrade ``effect_scope`` after the
    function set disappears, so restoration relies on the exact stored control
    identity plus current reversible/value/risk evidence instead.
    """
    if not active or not bool(getattr(element, "stateful", False)):
        return False
    restore_key = str(active.get("restore_candidate_key") or "")
    current_key = str(candidate_key(element))
    if restore_key and not stateful_candidate_keys_match(
            restore_key, current_key):
        return False
    if not restore_key and \
            normalize_state_key(getattr(element, "state_key", "")) != \
            normalize_state_key(active.get("state_key", "")):
        return False
    value = str(getattr(element, "state_value", "") or "").casefold()
    if value not in {"off", "on"}:
        return False
    probe_key = str(active.get("probe_candidate_key") or "")
    before_value = str(active.get("before_value") or "").casefold()
    after_value = str(active.get("after_value") or "").casefold()
    if restore_key and restore_key == probe_key:
        if after_value in {"off", "on"} and value != after_value:
            return False
        if after_value not in {"off", "on"} \
                and before_value in {"off", "on"} \
                and value == before_value:
            return False
    if getattr(element, "enabled", None) is False:
        return False
    if getattr(element, "reversible", None) is not True:
        return False
    if bool(getattr(element, "requires_permission", False)):
        return False
    if str(getattr(element, "blocked_reason", "") or "").strip():
        return False
    risk = " ".join(
        str(getattr(element, "risk", "") or "").casefold().split())
    return risk in {"", "none"}


__all__ = [
    "is_active_restore_candidate",
    "normalize_state_key",
    "resume_stateful_probe_state",
    "stateful_candidate_keys_match",
    "unresolved_stateful_probe_requires_restore",
]
