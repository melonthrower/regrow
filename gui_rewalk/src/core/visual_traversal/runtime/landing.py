"""Landing registration, verification result commit, and graph transition."""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .contracts import (
    AttemptContext, PerceptionUnavailable, RunCursor, StageDirective,
    TraversalRuntimeHost,
)
from .recovery import (
    recover_route_observation,
    refresh_verified_landing as _refresh_verified_return_landing,
)
from ..stateful import (
    normalize_state_key,
    stateful_candidate_keys_match,
    unresolved_stateful_probe_requires_restore,
)

logger = logging.getLogger(__name__)


def _element_id_text(value) -> str:
    """Stringify an element id without treating numeric zero as missing."""
    return "" if value is None else str(value)


def _change_evidence_from_hash(unchanged, *, same_node: bool):
    """Normalize Python/numpy boolean hash results into landing evidence."""
    if unchanged is None:
        return None
    if bool(unchanged):
        evidence = {
            "verdict": "no_effect",
            "note": "before/after perceptual hashes are identical",
        }
    elif same_node:
        evidence = {
            "verdict": "transitioned_consistent",
            "note": "visible local change retained the same state identity",
        }
    else:
        evidence = {
            "verdict": "transitioned_consistent",
            "note": "landing resolved to a different state identity",
        }
    evidence["same_node"] = bool(same_node)
    return evidence


def _observe_navigation_effect(
        host, *, source_id: str, target_id: str, element,
        before_shot: bytes, after_shot: bytes, live_elements):
    """Ask the read-only Observer whether a visually changed landing fits."""
    observer = getattr(host, "observer", None)
    observe = getattr(observer, "observe_transition", None)
    if not callable(observe):
        return None
    return observe(before_shot, after_shot, {
        "target": str(getattr(element, "name", "") or ""),
    })


def _observer_effect_evidence(result):
    if not isinstance(result, dict):
        return None
    mapping = {
        "related": "transitioned_consistent",
        "unrelated": "transitioned_inconsistent",
        "no_relevant_change": "no_effect",
        "uncertain": "uncertain",
    }
    verdict = mapping.get(str(
        result.get("relation_to_target") or "").lower())
    if not verdict:
        return None
    observed = str(result.get("observed_outcome") or "").strip()
    return {"verdict": verdict, "note": observed}


def _correct_transition_target_semantics(
        host, *, source_id: str, target_id: str, element, result,
        ledger_action, event_index, click_hint):
    """Apply one Observer-proven target name before the ActionEdge is committed."""
    if not isinstance(result, dict):
        return str(getattr(element, "name", "") or ""), ledger_action, False
    original = " ".join(str(
        getattr(element, "name", "") or "").split())[:160]
    corrected = " ".join(str(result.get("target") or "").split())[:160]
    if not corrected:
        result["target"] = original
        return original, ledger_action, False
    result["target"] = corrected
    if corrected.casefold() == original.casefold():
        return original, ledger_action, False

    corrected_action = copy.deepcopy(
        ledger_action if isinstance(ledger_action, dict) else {})
    selector = dict(corrected_action.get("selector") or {})
    selector["element_label"] = corrected
    selector["description"] = corrected
    corrected_action["selector"] = selector
    correct_event = getattr(
        getattr(host, "graph", None), "correct_action_event_semantics", None)
    if event_index is None or not callable(correct_event):
        logger.warning(
            "transition target correction could not update its action attempt")
        result["target"] = original
        result["relation_to_target"] = "uncertain"
        return original, ledger_action, False
    correct_event(
        int(event_index), action=corrected_action,
        element_label=corrected, semantic_description=corrected,
        region=str(getattr(element, "region", "") or ""),
    )

    result["original_target"] = original
    source = (getattr(host, "_state_data", {}).get(str(source_id)) or {})
    elements = list(source.get("elements") or [])
    wanted_id = _element_id_text(getattr(element, "id", None))
    wanted_region = str(getattr(element, "region_id", "") or "")
    for candidate in elements:
        same_element = candidate is element
        if not same_element and wanted_id:
            same_element = (
                _element_id_text(getattr(candidate, "id", None)) == wanted_id
                and (not wanted_region or str(
                    getattr(candidate, "region_id", "") or "")
                    == wanted_region)
            )
        if same_element:
            candidate.name = corrected
    element.name = corrected

    by_id = {
        _element_id_text(getattr(candidate, "id", None)): candidate
        for candidate in elements
    }
    for block in source.get("semantic_blocks") or []:
        ids = [
            _element_id_text(value) for value in block.get("element_ids") or []]
        if ids and all(value in by_id for value in ids):
            block["element_names"] = [by_id[value].name for value in ids]

    rename_button = getattr(getattr(host, "registry", None),
                            "rename_button", None)
    if callable(rename_button):
        rename_button(str(source_id), original, corrected)
    rename_action = getattr(getattr(host, "region_registry", None),
                            "rename_action", None)
    if callable(rename_action) and wanted_region:
        rename_action(wanted_region, original, corrected)

    if isinstance(click_hint, dict):
        click_hint["name"] = corrected
    target_hints = list(
        (getattr(host, "_state_data", {}).get(str(target_id)) or {}).get(
            "replay_hints") or [])
    if target_hints and isinstance(target_hints[-1], dict):
        old_hint = " ".join(str(
            target_hints[-1].get("name") or "").split())
        if old_hint.casefold() == original.casefold():
            target_hints[-1]["name"] = corrected

    logger.info(
        "transition observer corrected target semantics: %r -> %r",
        original, corrected)
    return corrected, corrected_action, True


@dataclass
class LandingRegistration:
    state_id: str
    is_new: bool
    observation_fresh: bool = True
    live_elements: Optional[List[object]] = None

@dataclass
class LandingCommitContext:
    source_id: str
    target_id: str
    element: object
    is_seed: bool
    click_effect: Optional[Dict[str, object]]
    verify_effect: bool
    ledger_action: Dict[str, object]
    event_index: int
    is_stateful: bool
    is_restore: bool
    mutation_id: str
    before_value: str
    after_value: str
    edge_label: str
    source_path: List[Dict[str, object]]
    source_hints: List[Optional[Dict[str, object]]]
    source_observation: Dict[str, object]
    new_path: List[Dict[str, object]]
    new_hints: List[Optional[Dict[str, object]]]
    observation: Dict[str, object]
    explore_local_functions: bool = True
    transient_inverse: object = None
    baseline_candidates: List[str] = field(default_factory=list)
    probe_candidate_key: str = ""
    restore_candidate_key: str = ""
    restore_before_value: str = ""
    targeted: bool = True

@dataclass
class CommittedLanding:
    state_id: str
    path: List[Dict[str, object]]
    replay_hints: List[Optional[Dict[str, object]]]
    observation: Dict[str, object]


def _state_value_from_elements(
    elements, state_key: str, candidate_key: str = "", key_fn=None,
) -> str:
    """Read one state axis from this observation, never from node history."""
    elements = list(elements or [])
    wanted = normalize_state_key(state_key)
    if candidate_key and callable(key_fn):
        identity_matches = [
            element for element in elements
            if stateful_candidate_keys_match(candidate_key, key_fn(element))
        ]
        if len(identity_matches) == 1:
            return str(
                getattr(identity_matches[0], "state_value", "") or "unknown")
        if len(identity_matches) > 1:
            exact_axis = [
                element for element in identity_matches
                if normalize_state_key(
                    getattr(element, "state_key", "")) == wanted
            ]
            if len(exact_axis) == 1:
                return str(
                    getattr(exact_axis[0], "state_value", "") or "unknown")
            return "unknown"
    matches = []
    for element in elements:
        key = normalize_state_key(getattr(element, "state_key", ""))
        if wanted and key == wanted:
            matches.append(element)
    if candidate_key:
        return "unknown"
    if matches:
        return str(getattr(matches[0], "state_value", "") or "unknown")
    return "unknown"


def _clear_mutation_on_verified_baseline_return(
    host, state_id: str, live_elements, *, observation_fresh: bool,
    record_restore=None,
) -> bool:
    """Close a pending mutation when a fresh return proves the baseline.

    A stateful control can first open a confirmation surface without changing
    its value.  If a later non-stateful dismiss/deny action returns to the
    source and the fresh inventory still reports the original value, there is
    nothing left to restore.
    """
    active = getattr(host, "_active_state_mutation", None)
    if not active or not observation_fresh:
        return False
    if str(state_id or "") != str(active.get("source_state") or ""):
        return False
    restore_before_value = str(
        active.get("restore_before_value") or "").strip().lower()
    if restore_before_value not in {"off", "on"}:
        restore_key = str(active.get("restore_candidate_key") or "")
        key_fn = getattr(host, "_stateful_candidate_key", None)
        if restore_key and callable(key_fn):
            source_elements = list(
                (getattr(host, "_state_data", {}).get(
                    str(active.get("source_state") or "")) or {}).get(
                        "elements") or [])
            restore_element = next((
                element for element in source_elements
                if stateful_candidate_keys_match(
                    restore_key, key_fn(element))
            ), None)
            restore_before_value = str(
                getattr(restore_element, "state_value", "") or ""
            ).strip().lower()
    if restore_before_value not in {"off", "on"}:
        restore_before_value = str(
            active.get("before_value") or "").strip().lower()
    if restore_before_value not in {"off", "on"}:
        return False
    observed_value = _state_value_from_elements(
        live_elements,
        str(active.get("state_key") or ""),
        candidate_key=str(
            active.get("restore_candidate_key")
            or active.get("probe_candidate_key")
            or ""),
        key_fn=getattr(host, "_stateful_candidate_key", None),
    ).strip().lower()
    if observed_value != restore_before_value:
        key_fn = getattr(host, "_stateful_candidate_key", None)
        live_state_evidence = [
            {
                "name": str(getattr(element, "name", "") or ""),
                "state_key": str(
                    getattr(element, "state_key", "") or ""),
                "state_value": str(
                    getattr(element, "state_value", "") or ""),
                "candidate_key": (
                    str(key_fn(element)) if callable(key_fn) else ""),
            }
            for element in live_elements or []
            if normalize_state_key(getattr(element, "state_key", ""))
            == normalize_state_key(active.get("state_key", ""))
        ]
        logger.info(
            "stateful mutation %s baseline return still pending: "
            "expected=%s observed=%s restore_key=%s live=%s",
            str(active.get("mutation_id") or "?"),
            restore_before_value,
            observed_value,
            str(active.get("restore_candidate_key") or ""),
            live_state_evidence,
        )
        return False
    mutation_id = str(active.get("mutation_id") or "")
    restore_evidence = {
        "mutation_id": mutation_id,
        "purpose": "restore",
        "stateful": True,
        "state_key": str(active.get("state_key") or ""),
        "before_value": str(active.get("after_value") or "unknown"),
        "after_value": observed_value,
        "restore_before_value": str(
            active.get("restore_before_value") or ""),
        "restoration_kind": "verified_baseline_return",
        "fresh_post_action_observation": True,
    }
    if callable(record_restore):
        record_restore(restore_evidence)
    host._active_state_mutation = None
    host._stateful_inflight = None
    logger.info(
        "stateful mutation %s cancelled/restored by verified baseline "
        "return: %s=%s",
        mutation_id or "?",
        str(active.get("state_key") or ""),
        observed_value,
    )
    review = getattr(host, "review_debug", None)
    if review is not None:
        review.record_event(
            "stateful_baseline_return",
            mutation_id=mutation_id,
            state_id=str(state_id or ""),
            state_key=str(active.get("state_key") or ""),
            observed_value=observed_value,
        )
    return True


def _record_restore_on_latest_verified_landing(
    host, state_id: str, evidence,
) -> bool:
    """Attach baseline proof to the real Router action that produced it."""
    graph = getattr(host, "graph", None)
    events = list(getattr(graph, "transition_events", []) or [])
    if not events or not callable(getattr(graph, "update_action_event", None)):
        return False
    latest = max(
        events, key=lambda event: int(event.get("action_index", 0) or 0))
    if (
        str(latest.get("target") or "") != str(state_id)
        or latest.get("committed") is not True
        or latest.get("landing_verified") is not True
    ):
        return False
    event_index = int(latest.get("action_index", 0) or 0)
    if event_index <= 0:
        return False
    merged = dict(latest.get("evidence") or {})
    merged.update(dict(evidence or {}))
    graph.update_action_event(event_index, evidence=merged)
    return True


def _frame_phash_text(host, observation) -> str:
    """Return one serializable live-frame fingerprint when available."""
    shot = (
        observation.get("screenshot")
        if isinstance(observation, dict) else None
    )
    hasher = getattr(host, "_frame_phash", None)
    if not shot or not callable(hasher):
        return ""
    try:
        return str(hasher(shot))
    except Exception:
        return ""


def _stateful_restore_effect(active_mutation, after_value: str,
                             observation_fresh: bool,
                             baseline_frame_match: bool = False):
    """Judge restoration against the transaction baseline, not stale node data."""
    expected = str(
        (active_mutation or {}).get("before_value") or "unknown"
    ).strip().lower()
    observed = str(after_value or "unknown").strip().lower()
    known = {"off", "on"}
    if not observation_fresh:
        return {
            "verdict": "uncertain",
            "note": "state restore lacks fresh structured state facts",
        }
    if expected not in known or observed not in known:
        if expected in known and baseline_frame_match:
            return {
                "verdict": "transitioned_consistent",
                "note": (
                    "live frame returned to the exact pre-mutation baseline "
                    f"for state {expected}"),
            }
        return {
            "verdict": "uncertain",
            "note": (
                f"state restore requires known baseline and observed values "
                f"(expected {expected}, landed {observed})"),
        }
    if observed == expected:
        return {
            "verdict": "transitioned_consistent",
            "note": f"structured state restored to baseline {expected}",
        }
    return {
        "verdict": "transitioned_inconsistent",
        "note": f"restore expected {expected}, landed {observed}",
    }


def _stateful_function_delta(
    host, source_id: str, target_id: str, state_key: str, *,
    target_elements=None, restore_candidate_key: str = "",
):
    """Compare reusable function descriptions while ignoring one state axis."""
    wanted = normalize_state_key(state_key)

    def _key(element):
        element_state_key = normalize_state_key(
            getattr(element, "state_key", ""))
        if wanted and element_state_key == wanted:
            return None
        if not getattr(element, "interactive", False):
            return None
        if getattr(element, "enabled", True) is False:
            return None
        norm = lambda value: " ".join(str(value or "").casefold().split())
        return (
            norm(getattr(element, "region", "")),
            norm(getattr(element, "name", "")),
            norm(getattr(element, "category", "")),
            norm(getattr(element, "el_type", "")),
        )

    source_elements = list(
        (host._state_data.get(source_id) or {}).get("elements", []) or [])
    target_elements = list(
        target_elements
        if target_elements is not None
        else (host._state_data.get(target_id) or {}).get("elements", []) or [])
    source_set = {key for element in source_elements
                  if (key := _key(element)) is not None}
    target_set = {key for element in target_elements
                  if (key := _key(element)) is not None}
    inverse = next((
        element for element in target_elements
        if normalize_state_key(getattr(element, "state_key", "")) == wanted
        and getattr(element, "interactive", False)
        and getattr(element, "enabled", True) is not False
        and (
            not restore_candidate_key
            or stateful_candidate_keys_match(
                restore_candidate_key,
                host._stateful_candidate_key(element))
        )
    ), None)
    added = sorted(" | ".join(key) for key in target_set - source_set)
    removed = sorted(" | ".join(key) for key in source_set - target_set)
    return bool(added or removed), added, removed, inverse


def _clear_stale_inherited_marker(host, current_id: str) -> None:
    """Keep the one-shot guard only while its inherited state is current."""
    marker = getattr(host, "_map_guided_inherited", None)
    if isinstance(marker, dict) and marker.get("state_id") != current_id:
        host._map_guided_inherited = None


def _return_probe_policy(host, *, is_new: bool, source_id: str,
                         target_id: str, element, action, pre_actions,
                         is_stateful: bool, is_restore: bool):
    """Choose immediate reverse-edge exploration for an ordinary transition."""
    if not getattr(host, "_proactive_return_verification", False):
        return False, "disabled"
    if source_id == target_id:
        return False, "no_state_transition"
    source_page_id = str(
        (host._state_data.get(source_id) or {}).get("page_id") or "")
    target_page_id = str(
        (host._state_data.get(target_id) or {}).get("page_id") or "")
    source_surface = str(
        (host._state_data.get(source_id) or {}).get("surface_kind") or "page"
    ).strip().casefold()
    target_surface = str(
        (host._state_data.get(target_id) or {}).get("surface_kind") or "page"
    ).strip().casefold()
    if (source_page_id and source_page_id == target_page_id
            and source_surface == target_surface):
        # A new State/Variant is not necessarily a new Page. Transient banners,
        # filters, selection, and local content changes must never trigger an
        # automatic Back/swipe merely because registration created a new node.
        # A page-to-popup/dialog transition remains independently verifiable
        # even when the overlay deliberately inherits its host page identity.
        return False, "same_page_variant"
    if is_stateful or is_restore:
        return False, "stateful_transaction"
    if bool(getattr(element, "back", False)):
        # The transition being committed is already the observed return edge.
        # Probing an inverse immediately would press Back twice and can leave
        # the application instead of proving anything about this edge.
        return False, "opening_action_is_return"
    action_type = str((action or {}).get("action_type") or "").upper()
    if action_type != "CLICK":
        return False, "non_click_action"
    if pre_actions:
        return False, "compound_opening_action"
    return True, "ordinary_navigation"


def _has_verified_direct_reverse(host, source_id: str, target_id: str) -> bool:
    """Check only a direct, context-compatible verified target->source edge."""
    router = getattr(host, "router", None)
    node_out_edges = getattr(router, "node_out_edges", None)
    if not callable(node_out_edges):
        return False
    try:
        edges = node_out_edges(str(target_id), str(source_id))
    except Exception:
        return False
    return any(
        str(edge.get("dst") or "") == str(source_id)
        and str(edge.get("provenance") or "") == "direct_verified"
        for edge in (edges or {}).values()
        if isinstance(edge, dict)
    )


def _forward_attempt_id(host, event_index: Optional[int]) -> str:
    if event_index is None:
        return ""
    try:
        attempt = host.graph.action_attempt(int(event_index))
    except Exception:
        return ""
    return str(attempt.get("attempt_id") or "")


def _record_forward_reverse_probe(
        host, event_index: Optional[int], payload: Dict[str, object]) -> None:
    """Attach reverse-probe planning/result evidence to the forward attempt."""
    if event_index is None:
        return
    try:
        attempt = host.graph.action_attempt(int(event_index))
        evidence = dict(attempt.get("evidence") or {})
        evidence["reverse_probe"] = dict(payload)
        host.graph.update_action_event(int(event_index), evidence=evidence)
    except Exception as exc:
        logger.warning("failed to persist forward reverse-probe evidence: %s",
                       exc)


def _probe_effect_kind(host, state_id: str, *, visible_target: bool) -> str:
    """Use existing structural semantics without naming special controls."""
    surface_kind = str(
        (host._state_data.get(str(state_id)) or {}).get("surface_kind") or ""
    ).strip().casefold().replace("-", "_").replace(" ", "_")
    if surface_kind in {
            "dialog", "popup", "popup_menu", "menu", "overlay", "drawer",
            "bottom_sheet"}:
        return "dismiss_overlay"
    return "peer_navigation" if visible_target else "return"


def _reverse_probe_result_status(host, probe_event_index: int, result) -> str:
    """Read the persisted landing result or classify a non-landing failure."""
    try:
        attempt = host.graph.action_attempt(probe_event_index)
    except Exception:
        attempt = {}
    reverse = (attempt.get("evidence") or {}).get("reverse_probe") or {}
    persisted = str(reverse.get("status") or "")
    if persisted not in {"", "attempted", "executed"}:
        return persisted
    if result.failure_kind == "return_control_not_attempted":
        return "grounding_failed"
    if getattr(result, "status", "") == "dispatch_unknown":
        return "dispatch_unknown"
    if result.failure_kind == "return_identity_unknown":
        return "identity_unknown"
    if result.failure_kind == "return_no_effect":
        return "no_effect"
    if result.failure_kind == "return_off_app":
        return "off_app"
    return str(result.failure_kind or result.status or "failed")


def register_landing(host: TraversalRuntimeHost, observation, path, replay_hints,
                     transition=None):
    """Register with one-call post-click context and never leak that context."""
    sentinel = object()
    prior = getattr(host, "_pending_transition", sentinel)
    if transition is not None:
        host._pending_transition = dict(transition)
    else:
        try:
            delattr(host, "_pending_transition")
        except AttributeError:
            pass
    host._last_live_observation_elements = None
    host._last_live_observation_state_id = None
    try:
        state_id, is_new = host._register(observation, path, replay_hints)
    finally:
        if prior is sentinel:
            try:
                delattr(host, "_pending_transition")
            except AttributeError:
                pass
        else:
            host._pending_transition = prior
    inherited = getattr(host, "_map_guided_inherited", None)
    observation_fresh = not (
        isinstance(inherited, dict)
        and str(inherited.get("state_id") or "") == str(state_id or "")
    )
    live_elements = (list(getattr(
        host, "_last_live_observation_elements", None) or [])
        if observation_fresh else None)
    return LandingRegistration(
        state_id, is_new, observation_fresh, live_elements)


def _known_return_failure_landing(host, result, target_id):
    """Keep traversing from a known actual landing after probe recovery fails."""
    if getattr(result, "status", "") == "dispatch_unknown":
        return None
    landed_id = str(result.landed_id or "")
    if landed_id not in host._state_data:
        return None
    if not result.action_dispatched and landed_id != str(target_id):
        return None
    landed = host._state_data[landed_id]
    if landed_id != str(target_id):
        host._route_blocked_targets.add(str(target_id))
    return (
        landed_id,
        list(landed.get("path") or []),
        list(landed.get("replay_hints") or []),
    )

def commit_landing(host: TraversalRuntimeHost, context: LandingCommitContext):
    current_id = context.source_id
    new_id = context.target_id
    elem = context.element
    is_seed = context.is_seed
    _ce = context.click_effect
    _verify_effect = context.verify_effect
    _ledger_action = context.ledger_action
    _event_index = context.event_index
    _is_stateful_action = context.is_stateful
    _is_state_restore = context.is_restore
    _mutation_id = context.mutation_id
    _stateful_before_value = context.before_value
    _stateful_after_value = context.after_value
    edge_label = context.edge_label
    source_path = context.source_path
    source_hints = context.source_hints
    source_obs = context.source_observation
    new_path = context.new_path
    new_hints = context.new_hints
    obs = context.observation

    if context.targeted:
        host._commit_explored(current_id, elem, is_seed)
    _effect_verdict = (_ce or {}).get("verdict", "")
    _landing_verified = bool(
        _verify_effect
        and _effect_verdict == "transitioned_consistent"
    )
    _target_page = str((host._state_data.get(new_id) or {}).get(
        "page_name", "") or "")
    effect_kind = (
        "return_via_control"
        if context.targeted and bool(getattr(elem, "back", False))
        else ""
    )
    host.graph.add_transition(
        src=current_id, dst=new_id, action=_ledger_action,
        element_id=(str(elem.id) if context.targeted else ""),
        element_label=(str(elem.name or edge_label)
                       if context.targeted else ""),
        semantic_description=edge_label,
        region=(getattr(elem, "region", "") or ""
                if context.targeted else ""),
        effect_verdict=_effect_verdict,
        effect_note=(_ce or {}).get("note", ""),
        landing_verified=_landing_verified,
        target_page_name=_target_page,
        event_index=_event_index,
        transition_kind=("stateful_surface"
                         if _is_stateful_action else ""),
        effect_kind=effect_kind,
    )
    host._persist_online_capabilities(current_id)
    if _is_stateful_action:
        host._stateful_inflight = None
        if _is_state_restore:
            logger.info("stateful mutation %s restored: %s=%s",
                        _mutation_id, elem.state_key,
                        _stateful_after_value or "unknown")
            host._active_state_mutation = None
        else:
            host._stateful_probe_count += 1
            host._stateful_probe_sources.add(
                (current_id, elem.state_key, _stateful_before_value))
            host._active_state_mutation = {
                "mutation_id": _mutation_id,
                "source_state": current_id,
                "mutated_state": new_id,
                "state_key": elem.state_key,
                "before_value": _stateful_before_value,
                "after_value": _stateful_after_value or "unknown",
                "baseline_frame_phash": _frame_phash_text(host, source_obs),
                "explore_local_functions": bool(
                    context.explore_local_functions),
                "inverse_element": context.transient_inverse,
                "probe_candidate_key": context.probe_candidate_key,
                "restore_candidate_key": context.restore_candidate_key,
                "restore_before_value": context.restore_before_value,
                "baseline_candidates": list(context.baseline_candidates),
            }
            logger.info("stateful mutation %s active: %s %s->%s; "
                        "explore gated local functions before restore",
                        _mutation_id, elem.state_key, _stateful_before_value,
                        _stateful_after_value or "unknown")
    if host.review_debug.enabled:
        _prev = host._classify_edge_consistency(
            host._edge_dsts, current_id, edge_label, new_id)
        if _prev is not None:
            host.review_debug.record_event(
                "nondeterministic_edge", node=current_id, elem=edge_label,
                prior_dst=_prev, now_dst=new_id)
    if new_id == current_id:
        logger.debug("same-state no-op on '%s'", elem.name)
        current_path = list(source_path)
        current_hints = list(source_hints)
        # State-changing same-page actions still have a new physical frame.
        # Reusing the source observation here made the next step operate on a
        # stale screenshot even after the action was verified.
        current_obs = obs
    else:
        current_id, current_path, current_hints = (
            new_id, list(new_path), list(new_hints))
        current_obs = obs
    host._maybe_save()
    return CommittedLanding(current_id, current_path, current_hints, current_obs)


@dataclass
class LandingOutcome:
    directive: StageDirective
    cursor: RunCursor

def process_landing(host: TraversalRuntimeHost, cursor: RunCursor,
                    attempt: AttemptContext) -> LandingOutcome:
    """Register, verify, quarantine or commit one executed landing."""
    plan = attempt.candidate
    elem = plan.element
    current_id = cursor.state_id
    current_path = list(cursor.path)
    current_hints = list(cursor.replay_hints)
    current_obs = cursor.observation
    obs = attempt.observation
    action = attempt.action
    pre_actions = attempt.pre_actions
    _before_shot = attempt.before_shot
    _verify_effect = attempt.verify_effect
    _attempt_label = attempt.attempt_label
    _ledger_action = attempt.ledger_action
    _event_index = attempt.event_index
    _update_event = attempt.update_event
    is_seed = plan.is_seed
    _is_stateful_action = plan.is_stateful
    _is_state_restore = plan.is_restore
    _active_mutation = plan.active_mutation
    _mutation_id = plan.mutation_id
    _stateful_evidence = dict(plan.stateful_evidence)
    _stateful_before_value = str(
        _stateful_evidence.get("before_value")
        or getattr(elem, "state_value", "") or "unknown"
    ).strip().lower()
    pre_click_id = plan.pre_click_id

    def done(directive):
        _clear_stale_inherited_marker(host, current_id)
        return LandingOutcome(directive, RunCursor(
            current_id, current_obs, list(current_path),
            list(current_hints), cursor.off_app_streak,
        ))

    click_hint = {
        "template": getattr(elem, "_template", None),
        "post_shot": obs.get("screenshot"),
        "name": (getattr(elem, "name", "") or ""),
    }
    new_path = current_path + pre_actions + [action]
    new_hints = (list(current_hints)
                 + [None] * len(pre_actions) + [click_hint])
    _after_shot = obs.get("screenshot")
    _phash_distance = None
    _visual_unchanged = None
    if (_verify_effect or host.review_debug.enabled) \
            and _before_shot and _after_shot:
        try:
            _phash_distance = int(
                host._frame_phash(_before_shot)
                - host._frame_phash(_after_shot))
            _visual_unchanged = _phash_distance == 0
        except Exception:
            _visual_unchanged = None
    try:
        action_parameters = (
            action.get("parameters")
            if isinstance(action.get("parameters"), dict) else action
        )
        clicked_point = [
            action_parameters.get("x"), action_parameters.get("y")]
        if any(value is None for value in clicked_point):
            clicked_point = list(getattr(elem, "center", None) or [])
        landing = register_landing(
            host, obs, new_path, new_hints,
            transition={"source_id": current_id,
                        "clicked_label": str(getattr(elem, "name", "") or ""),
                        "clicked_bbox": list(
                            getattr(elem, "bbox_xywh", None) or []),
                        "clicked_point": clicked_point,
                        "event_index": _event_index,
                        "requires_fresh_observation": bool(
                            _is_stateful_action or _is_state_restore),
                        "visual_changed": _visual_unchanged is False,
                        "effect_verification": bool(_verify_effect)},
        )
        new_id, is_new = landing.state_id, landing.is_new
        region_transition = dict(
            (host._state_data.get(new_id) or {}).get(
                "region_transition") or {})
        if region_transition:
            _update_event(evidence={
                "region_transition": region_transition,
            })
    except PerceptionUnavailable as exc:
        logger.error(
            "post-click perception unavailable for '%s'; preserving "
            "the last good graph: %s",
            elem.name, exc)
        host.review_debug.record_event(
            "post_click_perception_unavailable",
            node=current_id, elem=elem.name, step=host._action_count)
        _update_event(
            outcome="perception_failed",
            detail=str(exc),
        )
        if _is_stateful_action:
            host.graph.stop_reason = "perception_unavailable"
            return done(StageDirective.STOP)

        failure_count = host._record_click_failure(
            current_id, elem, "perception_unavailable")
        recovered_obs = None
        recovered_id = None
        recovered_path = []
        recovered_hints = []
        recovery_action = ""

        def accept_known_landing(candidate_obs):
            if not isinstance(candidate_obs, dict):
                return None, [], []
            candidate_id = host._router_identify(candidate_obs)
            if (not candidate_id
                    or candidate_id not in host.graph.graph
                    or candidate_id not in host._state_data):
                return None, [], []
            return _refresh_verified_return_landing(
                host, candidate_obs, str(candidate_id), strict=True)

        try:
            recovered_obs = host._router_back(obs, source_id=None)
            recovered_id, recovered_path, recovered_hints = \
                accept_known_landing(recovered_obs)
            if recovered_id:
                recovery_action = "navigate_back"
        except Exception as recovery_exc:
            logger.warning(
                "post-click perception BACK recovery failed: %s",
                recovery_exc)

        if not recovered_id and callable(getattr(host, "relaunch_fn", None)):
            try:
                recovered_obs = host.relaunch_fn()
                recovered_obs, _relaunched, on_app = \
                    host._ensure_on_app(recovered_obs)
                if on_app:
                    recovered_id, recovered_path, recovered_hints = \
                        accept_known_landing(recovered_obs)
                    if recovered_id:
                        recovery_action = "relaunch"
            except Exception as recovery_exc:
                logger.warning(
                    "post-click perception relaunch recovery failed: %s",
                    recovery_exc)

        _update_event(evidence={
            "failure_count": failure_count,
            "recovered": bool(recovered_id),
            "recovery_action": recovery_action,
            "recovered_state": str(recovered_id or ""),
        })
        if not recovered_id:
            logger.error(
                "post-click perception failure could not restore a known "
                "landing; stopping fail-closed")
            host.graph.stop_reason = "state_restore_failed"
            host.graph.save(host.graph_save_path)
            return done(StageDirective.STOP)

        current_id = str(recovered_id)
        current_path = list(recovered_path)
        current_hints = list(recovered_hints)
        current_obs = recovered_obs
        logger.warning(
            "post-click perception failure recovered by %s to %s; "
            "continuing traversal",
            recovery_action, current_id[:8])
        host._maybe_save()
        return done(StageDirective.CONTINUE)
    _stateful_after_value = ""
    _stateful_function_changed = True
    _stateful_added_functions = []
    _stateful_removed_functions = []
    _stateful_inverse = None
    if _is_stateful_action:
        _stateful_after_value = _state_value_from_elements(
            landing.live_elements, elem.state_key,
            candidate_key=str(
                _stateful_evidence.get("probe_candidate_key") or ""),
            key_fn=host._stateful_candidate_key)
        _stateful_evidence = {
            **_stateful_evidence,
            "after_value": _stateful_after_value,
            "registered_target": new_id,
            "fresh_post_action_observation": landing.observation_fresh,
            "post_action_phash_distance": _phash_distance,
        }
        _update_event(evidence=_stateful_evidence)
    elif _event_index is not None:
        _update_event(evidence={
            "fresh_post_action_observation": landing.observation_fresh,
            "post_action_phash_distance": _phash_distance,
        })
    edge_label = _attempt_label
    if pre_click_id is not None and pre_click_id != current_id:
        _update_event(
            target=new_id,
            outcome="quarantined_source_mismatch",
            detail=(f"believed source {current_id}; actual pre-click "
                    f"state {pre_click_id}"),
            evidence={"actual_pre_click": pre_click_id},
        )
        host.review_debug.record_event(
            "quarantine_edge", elem=edge_label, believed=current_id,
            actual_pre_click=pre_click_id, dst=new_id)
        logger.warning(
            "QUARANTINE edge '%s': pre-click frame was state %s, not the "
            "believed current %s (stranded after a loose backtrack "
            "arrival) — dropping mis-attributed %s->%s transition; "
            "resyncing to actual state",
            edge_label, pre_click_id, current_id, current_id, new_id)
        if (_is_stateful_action
                and host._verified_state_value_changed(
                    _stateful_before_value, _stateful_after_value)):
            host._active_state_mutation = {
                "mutation_id": _mutation_id,
                "source_state": current_id,
                "mutated_state": new_id,
                "state_key": elem.state_key,
                "before_value": _stateful_before_value,
                "after_value": _stateful_after_value or "unknown",
                "probe_candidate_key": str(
                    _stateful_evidence.get("probe_candidate_key") or ""),
                "restore_candidate_key": str(
                    _stateful_evidence.get("restore_candidate_key") or ""),
                "restore_before_value": str(
                    _stateful_evidence.get("restore_before_value") or ""),
                "baseline_candidates": list(
                    _stateful_evidence.get("baseline_candidates") or []),
            }
            host._stateful_inflight = None
            host.graph.stop_reason = "state_restore_failed"
            logger.error("stateful click source was mismatched; physical "
                         "state may be mutated, stopping fail-closed")
            return done(StageDirective.STOP)
        if _is_stateful_action:
            host._stateful_inflight = None
            host._record_abnormal_button(
                current_id, elem, "stateful_source_mismatch",
                "pre-click source identity mismatched and no structured "
                "state-value change was observed",
                action=action)
        landed = host._state_data.get(new_id)
        if landed is not None:
            current_id = new_id
            current_path = list(landed.get("path", new_path))
            current_hints = list(landed.get("replay_hints", []) or new_hints)
        else:
            current_id, current_path, current_hints = new_id, new_path, new_hints
        host._maybe_save()
        return done(StageDirective.CONTINUE)
    _ce = None
    if _visual_unchanged is not None:
        _ce = _change_evidence_from_hash(
            _visual_unchanged, same_node=bool(new_id == current_id))
    elif (_verify_effect or host.review_debug.enabled) \
            and _before_shot and _after_shot:
        _ce = {"verdict": "uncertain",
               "note": "perceptual hash unavailable",
               "same_node": bool(new_id == current_id)}
    _observer_result = None
    _target_semantics_corrected = False
    if (
        _verify_effect
        and not _is_stateful_action
        and _visual_unchanged is False
        and _before_shot
        and _after_shot
    ):
        _observer_result = _observe_navigation_effect(
            host,
            source_id=current_id,
            target_id=new_id,
            element=elem,
            before_shot=_before_shot,
            after_shot=_after_shot,
            live_elements=landing.live_elements,
        )
        edge_label, _ledger_action, _target_semantics_corrected = \
            _correct_transition_target_semantics(
                host, source_id=current_id, target_id=new_id,
                element=elem, result=_observer_result,
                ledger_action=_ledger_action, event_index=_event_index,
                click_hint=click_hint,
            )
        _observer_effect = _observer_effect_evidence(_observer_result)
        if _observer_effect is not None:
            _ce = _observer_effect
            _update_event(evidence={
                "transition_observer": dict(_observer_result),
            })
    _equivalent_stateful_no_effect = False
    if (_is_stateful_action
            and (_ce or {}).get("verdict") != "blocked"):
        _before_value = _stateful_before_value
        _after_value = (_stateful_after_value or "unknown").strip().lower()
        _known_values = {"off", "on"}
        if _before_value in _known_values and _after_value in _known_values:
            if _before_value == _after_value:
                if not landing.observation_fresh:
                    _ce = {
                        "verdict": "uncertain",
                        "note": (
                            "stateful result reused historical structure; "
                            "fresh post-action facts are required"),
                    }
                elif _visual_unchanged is False:
                    _ce = {
                        "verdict": "uncertain",
                        "note": (
                            "live pixels changed but fresh structured state "
                            "did not; refusing to overwrite live evidence"),
                    }
                else:
                    _equivalent_stateful_no_effect = \
                        host._stateful_landing_equivalent(
                            current_id,
                            new_id,
                            state_key=elem.state_key,
                            before_value=_before_value,
                            after_value=_after_value,
                        )
                if _equivalent_stateful_no_effect:
                    _ce = {
                        "verdict": "no_effect",
                        "note": (
                            "fresh pixels, structured state, and semantic "
                            "page facts did not change"),
                    }
                elif (_ce or {}).get("verdict") not in {"uncertain"}:
                    _ce = {
                        "verdict": "transitioned_inconsistent",
                        "note": (
                            "state value did not change but landing page "
                            "or structured facts differ"),
                    }
            else:
                _ce = {
                    "verdict": "transitioned_consistent",
                    "note": (f"structured state changed {_before_value}"
                             f"->{_after_value}"),
                }
        elif not landing.observation_fresh:
            _ce = {
                "verdict": "uncertain",
                "note": "stateful result lacks fresh structured state facts",
            }
        if _is_state_restore:
            _baseline_frame_phash = str(
                (_active_mutation or {}).get("baseline_frame_phash") or "")
            _restored_frame_phash = _frame_phash_text(host, obs)
            _baseline_frame_match = bool(
                _baseline_frame_phash
                and _restored_frame_phash == _baseline_frame_phash
            )
            _ce = _stateful_restore_effect(
                _active_mutation,
                _after_value,
                landing.observation_fresh,
                _baseline_frame_match,
            )
            _stateful_evidence["baseline_frame_match"] = \
                _baseline_frame_match
            if (_ce.get("verdict") == "transitioned_consistent"
                    and _after_value not in _known_values
                    and _baseline_frame_match):
                _stateful_evidence["observed_after_value"] = _after_value
                _stateful_after_value = str(
                    (_active_mutation or {}).get("before_value")
                    or "unknown"
                ).strip().lower()
                _stateful_evidence.update({
                    "after_value": _stateful_after_value,
                    "after_value_source": "baseline_frame_match",
                })
            _update_event(evidence=_stateful_evidence)
    if (_is_stateful_action and not _is_state_restore
            and landing.observation_fresh
            and host._verified_state_value_changed(
                _stateful_before_value, _stateful_after_value)):
        (_stateful_function_changed,
         _stateful_added_functions,
         _stateful_removed_functions,
        _stateful_inverse) = _stateful_function_delta(
            host, current_id, new_id, elem.state_key,
            target_elements=landing.live_elements,
            restore_candidate_key=str(
                _stateful_evidence.get("restore_candidate_key") or ""))
        _stateful_evidence.update({
            "functional_delta": _stateful_function_changed,
            "added_functions": _stateful_added_functions,
            "removed_functions": _stateful_removed_functions,
        })
        _update_event(evidence=_stateful_evidence)

    # A reversible value change that exposes no new function is transaction
    # evidence, not a durable Page@Variant.  Preserve its fresh inverse
    # selector, compact the uncommitted observation, then restore from the
    # current live frame on the next scheduler turn.
    if ((_ce or {}).get("verdict") == "transitioned_consistent"
            and _is_stateful_action and not _is_state_restore
            and not _stateful_function_changed
            and _stateful_inverse is not None
            and is_new and new_id != current_id
            and host._discard_uncommitted_equivalent_state(
                new_id,
                current_id,
                reason="transient state change exposed no new functions",
            )):
        new_id = current_id
        is_new = False
        _stateful_evidence.update({
            "registered_target": current_id,
            "transient_observation_compacted": True,
        })
        _update_event(evidence=_stateful_evidence)
    if _ce is not None:
        _shots = None
        if _ce["verdict"] in {"no_effect", "transitioned_inconsistent"}:
            host._click_shot_seq = getattr(host, "_click_shot_seq", 0) + 1
            _shots = host.review_debug.save_click_shots(
                f"{str(current_id)[:8]}_{edge_label}_{host._click_shot_seq}",
                _before_shot, _after_shot)
        host.review_debug.record_event(
            "click_effect", node=current_id, elem=edge_label,
            dst=new_id, verdict=_ce["verdict"], note=_ce.get("note", ""),
            step=host._action_count, shots=_shots)
    if _verify_effect and (
            _ce is None
            or _ce.get("verdict") in (
                "no_effect", "blocked",
                "transitioned_inconsistent", "uncertain")
        ):
        verdict = (_ce or {}).get("verdict", "uncertain")
        if verdict == "blocked":
            source_page = str(
                (host._state_data.get(current_id) or {}).get(
                    "page_id") or "")
            target_page = str(
                (host._state_data.get(new_id) or {}).get(
                    "page_id") or "")
            if _is_state_restore or not source_page \
                    or source_page != target_page:
                verdict = "transitioned_inconsistent"
                _ce = {
                    "verdict": verdict,
                    "note": (
                        "blocked verdict rejected because the landing "
                        "was a restore or not the same semantic page"),
                }
            else:
                terminal_evidence = dict(
                    _stateful_evidence if _is_stateful_action else {})
                if isinstance(_observer_result, dict):
                    terminal_evidence["transition_observer"] = dict(
                        _observer_result)
                terminal_evidence.update({
                    "terminal_landing": True,
                    "terminal_reason": "blocked",
                    "mutation_observed": False,
                })
                _update_event(
                    target=new_id,
                    outcome="blocked",
                    detail=(_ce or {}).get(
                        "note", "explicit environment block"),
                    landing_verified=True,
                    evidence=terminal_evidence,
                )
                host._record_abnormal_button(
                    current_id,
                    elem,
                    "blocked",
                    (_ce or {}).get(
                        "note", "explicit environment block"),
                    action=_ledger_action,
                )
                if _is_stateful_action:
                    host._stateful_inflight = None
                if new_id != current_id:
                    landed = host._state_data.get(new_id)
                    current_id = new_id
                    current_path = list(
                        (landed or {}).get("path", new_path))
                    current_hints = list((landed or {}).get(
                        "replay_hints", new_hints) or new_hints)
                    current_obs = obs
                host._maybe_save()
                return done(StageDirective.CONTINUE)
        if verdict == "uncertain" and isinstance(_observer_result, dict):
            source_id = current_id
            unresolved = getattr(
                host, "_observer_unresolved_controls", None)
            if unresolved is None:
                unresolved = set()
                host._observer_unresolved_controls = unresolved
            unresolved.add((source_id, elem.uid or elem.name))
            result_evidence = dict(_stateful_evidence)
            result_evidence["transition_observer"] = dict(_observer_result)
            _update_event(
                target=new_id,
                outcome="uncertain",
                detail=(_ce or {}).get(
                    "note", "transition observation remained uncertain"),
                landing_verified=False,
                evidence=result_evidence,
            )
            landed = host._state_data.get(new_id)
            if landed is not None:
                current_id = new_id
                current_path = list(landed.get("path", new_path))
                current_hints = list(
                    landed.get("replay_hints", []) or new_hints)
            else:
                current_id = new_id
                current_path = list(new_path)
                current_hints = list(new_hints)
            current_obs = obs
            host.review_debug.record_event(
                "observer_unresolved_landing",
                source_state=source_id,
                observed_state=new_id,
                control=edge_label,
            )
            logger.warning(
                "transition observation remained uncertain for '%s'; "
                "keeping the actual landing %s and deferring the source "
                "control for this run",
                edge_label, new_id[:8],
            )
            host._maybe_save()
            return done(StageDirective.CONTINUE)
        _stateful_value_changed = (
            _is_stateful_action
            and host._verified_state_value_changed(
                _stateful_before_value, _stateful_after_value)
        )
        _discard_rejected_provisional = (
            is_new and new_id != current_id
            and verdict in {"no_effect", "uncertain"}
            and not _stateful_value_changed
        )
        if (_discard_rejected_provisional
                and host._discard_uncommitted_equivalent_state(
                    new_id,
                    current_id,
                    reason=("stateful no-effect preserved page and facts"
                            if verdict == "no_effect"
                            else "conflicting live/structured effect evidence"),
                )):
            new_id = current_id
            is_new = False
            _stateful_evidence.update({
                "registered_target": current_id,
                "equivalent_provisional_state_discarded": True,
            })
            # The graph node remains canonical, but the runtime frame must stay
            # live so a retry rebinds against what is physically on screen.
            current_obs = obs
        result_evidence = dict(
            _stateful_evidence if _is_stateful_action else {})
        if isinstance(_observer_result, dict):
            result_evidence["transition_observer"] = dict(_observer_result)
        _update_event(
            target=new_id,
            outcome=verdict,
            detail=(_ce or {}).get("note", "verification unavailable"),
            landing_verified=False,
            evidence=result_evidence,
        )
        logger.error("QUARANTINE navigation click '%s': %s (%s)",
                     edge_label, verdict, (_ce or {}).get("note", ""))
        if _is_state_restore:
            host._stateful_inflight = None
            host.graph.stop_reason = "state_restore_failed"
            host.graph.save(host.graph_save_path)
            logger.error(
                "stateful restore result is not proven; refusing to repeat "
                "the non-idempotent control")
            return done(StageDirective.STOP)
        if unresolved_stateful_probe_requires_restore(
                _stateful_evidence, outcome=verdict, committed=False):
            baseline_frame_phash = _frame_phash_text(
                host, {"screenshot": _before_shot})
            _stateful_evidence.update({
                "after_value": "unknown",
                "potential_mutation": True,
                "restore_required": True,
                "baseline_frame_phash": baseline_frame_phash,
                "explore_local_functions": False,
            })
            _update_event(evidence=_stateful_evidence)
            host._stateful_inflight = None
            host._stateful_probe_count += 1
            host._stateful_probe_sources.add(
                (current_id, elem.state_key, _stateful_before_value))
            host._active_state_mutation = {
                "mutation_id": _mutation_id,
                "source_state": current_id,
                "mutated_state": new_id,
                "state_key": elem.state_key,
                "before_value": _stateful_before_value,
                "after_value": "unknown",
                "probe_candidate_key": str(
                    _stateful_evidence.get("probe_candidate_key") or ""),
                "restore_candidate_key": str(
                    _stateful_evidence.get("restore_candidate_key") or ""),
                "restore_before_value": str(
                    _stateful_evidence.get("restore_before_value") or ""),
                "baseline_frame_phash": baseline_frame_phash,
                "baseline_candidates": list(
                    _stateful_evidence.get("baseline_candidates") or []),
                "explore_local_functions": False,
            }
            host._record_abnormal_button(
                current_id,
                elem,
                "stateful_effect_uncertain",
                (
                    "fresh pixels changed but structured state did not prove "
                    "the result; restoring the frozen baseline before any "
                    "further exploration"
                ),
                action=_ledger_action,
                evidence=_stateful_evidence,
            )
            current_obs = obs
            logger.warning(
                "stateful probe %s may have mutated physical state; "
                "scheduling its frozen inverse before any further work",
                _mutation_id or "?",
            )
            host._maybe_save()
            return done(StageDirective.CONTINUE)
        host._record_click_failure(current_id, elem, verdict)
        if verdict == "transitioned_inconsistent":
            host._quarantined_edges.add((current_id, new_id))
            recovered_obs = obs
            recovered_ok = False
            if host.router is not None:
                try:
                    recovered = host.router.route_to(
                        obs, new_id, current_id)
                    if hasattr(recovered, "arrived"):
                        recovered_ok = recovered.arrived
                        recovered_obs = recovered.observation
                    else:
                        recovered_ok, recovered_obs = recovered
                except Exception as ex:
                    logger.warning(
                        "quarantine recovery from %s to %s failed: %s",
                        new_id, current_id, ex)
            recovered_id = (
                host._router_identify(recovered_obs)
                if recovered_ok and recovered_obs is not None
                else None
            )
            if is_new and new_id != current_id:
                host._discard_uncommitted_equivalent_state(
                    new_id,
                    current_id,
                    reason="rejected inconsistent landing",
                )
            if not recovered_ok or recovered_id != current_id:
                logger.error(
                    "failed to restore source page %s after inconsistent "
                    "landing on %s",
                    current_id[:8], new_id[:8])
                host.graph.stop_reason = "state_restore_failed"
                host.graph.save(host.graph_save_path)
                return done(StageDirective.STOP)
            current_obs = recovered_obs
            host._maybe_save()
            return done(StageDirective.CONTINUE)
        if (verdict == "no_effect"
                and not _is_stateful_action
                and new_id != current_id
                and not is_new):
            landed = host._state_data.get(new_id)
            if isinstance(landed, dict):
                source_id = current_id
                current_id = new_id
                current_path = list(landed.get("path") or [])
                current_hints = list(landed.get("replay_hints") or [])
                current_obs = obs
                host.review_debug.record_event(
                    "no_effect_cursor_resync",
                    source_state=source_id,
                    observed_state=new_id,
                )
                logger.info(
                    "resynced cursor from %s to known observed state %s "
                    "after rejected no-effect click",
                    source_id[:8], new_id[:8])
        if _is_stateful_action:
            host._stateful_inflight = None
            if (not _is_state_restore
                    and host._verified_state_value_changed(
                        _stateful_before_value, _stateful_after_value)):
                host._active_state_mutation = {
                    "mutation_id": _mutation_id,
                    "source_state": current_id,
                    "mutated_state": new_id,
                    "state_key": elem.state_key,
                    "before_value": _stateful_before_value,
                    "after_value": _stateful_after_value or "unknown",
                    "probe_candidate_key": str(
                        _stateful_evidence.get("probe_candidate_key") or ""),
                    "restore_candidate_key": str(
                        _stateful_evidence.get("restore_candidate_key") or ""),
                    "restore_before_value": str(
                        _stateful_evidence.get("restore_before_value") or ""),
                    "baseline_frame_phash": _frame_phash_text(
                        host, {"screenshot": _before_shot}),
                    "baseline_candidates": list(
                        _stateful_evidence.get("baseline_candidates") or []),
                }
        host._maybe_save()
        return done(StageDirective.CONTINUE)
    if (
        not _is_stateful_action
        and (_ce or {}).get("verdict") == "transitioned_consistent"
    ):
        _clear_mutation_on_verified_baseline_return(
            host,
            new_id,
            landing.live_elements,
            observation_fresh=landing.observation_fresh,
            record_restore=lambda evidence: _update_event(
                evidence=evidence),
        )
    source_id = current_id
    committed = commit_landing(host, LandingCommitContext(
        source_id=current_id, target_id=new_id, element=elem,
        is_seed=is_seed, click_effect=_ce, verify_effect=_verify_effect,
        ledger_action=_ledger_action,
        event_index=_event_index, is_stateful=_is_stateful_action,
        is_restore=_is_state_restore, mutation_id=_mutation_id,
        before_value=_stateful_before_value,
        after_value=_stateful_after_value, edge_label=edge_label,
        source_path=current_path, source_hints=current_hints,
        source_observation=(
            {"screenshot": _before_shot}
            if _before_shot else current_obs
        ),
        new_path=new_path, new_hints=new_hints, observation=obs,
        explore_local_functions=_stateful_function_changed,
        transient_inverse=_stateful_inverse,
        baseline_candidates=list(
            _stateful_evidence.get("baseline_candidates") or []),
        probe_candidate_key=str(
            _stateful_evidence.get("probe_candidate_key") or ""),
        restore_candidate_key=str(
            _stateful_evidence.get("restore_candidate_key") or ""),
        restore_before_value=str(
            _stateful_evidence.get("restore_before_value") or ""),
        targeted=plan.targeted,
    ))
    current_id = committed.state_id
    current_path = committed.path
    current_hints = committed.replay_hints
    current_obs = committed.observation
    if _target_semantics_corrected:
        persist_source = getattr(host, "_persist_exploration_state", None)
        if callable(persist_source):
            persist_source(source_id)
    note_arrival = getattr(getattr(host, "router", None), "note_arrival", None)
    if new_id != source_id and callable(note_arrival):
        note_arrival(new_id, source_id, {
            "action": dict(_ledger_action),
            "effect_kind": (
                "return_via_control"
                if bool(getattr(elem, "back", False)) else ""
            ),
        })
    if is_new and new_id != source_id:
        blocked_targets = getattr(host, "_route_blocked_targets", None)
        if blocked_targets is not None:
            blocked_targets.clear()
    forward_verified = bool(
        _verify_effect
        and str((_ce or {}).get("verdict") or "")
        == "transitioned_consistent"
    )
    if new_id != source_id and not forward_verified:
        _record_forward_reverse_probe(host, _event_index, {
            "status": "deferred",
            "intended_target": source_id,
            "reason": "forward_transition_not_verified",
        })
        return done(StageDirective.CONTINUE)
    probe_now, probe_reason = _return_probe_policy(
        host, is_new=is_new, source_id=source_id, target_id=new_id,
        element=elem, action=action, pre_actions=pre_actions,
        is_stateful=_is_stateful_action, is_restore=_is_state_restore,
    )
    if not probe_now:
        if getattr(host, "_proactive_return_verification", False) \
                and new_id != source_id:
            _record_forward_reverse_probe(host, _event_index, {
                "status": "deferred",
                "intended_target": source_id,
                "reason": probe_reason,
            })
            host._return_probe_status[(source_id, new_id)] = {
                "status": "deferred", "reason": probe_reason,
            }
            host.review_debug.record_event(
                "return_probe_deferred", source=source_id, target=new_id,
                reason=probe_reason)
        return done(StageDirective.CONTINUE)
    if _has_verified_direct_reverse(host, source_id, new_id):
        _record_forward_reverse_probe(host, _event_index, {
            "status": "already_has_verified_direct_edge",
            "intended_target": source_id,
        })
        host._return_probe_status[(source_id, new_id)] = {
            "status": "already_has_verified_direct_edge",
        }
        host.review_debug.record_event(
            "reverse_probe_skipped", source=source_id, target=new_id,
            reason="already_has_verified_direct_edge")
        return done(StageDirective.CONTINUE)

    judge = getattr(host, "page_judge", None)
    source_shot = _before_shot or (
        (source_obs or {}).get("screenshot")
        if isinstance(source_obs, dict) else None)
    target_shot = ((current_obs or {}).get("screenshot")
                   if isinstance(current_obs, dict) else None)
    if judge is None or not hasattr(judge, "choose_return"):
        decision = {
            "action": None, "target": "",
            "reason": "reverse-edge explorer unavailable",
        }
    else:
        decision = judge.choose_return(
            source_shot, target_shot,
            source_name=str((host._state_data.get(source_id) or {}).get(
                "page_name") or ""),
            target_name=str((host._state_data.get(new_id) or {}).get(
                "page_name") or ""),
            transition=edge_label,
            platform=("android" if getattr(host, "_is_touch", False)
                      else "desktop"),
        )
    reverse_action = (dict(decision.get("action") or {})
                      if isinstance(decision.get("action"), dict) else {})
    visible_target = str(decision.get("target") or "").strip()
    action_type = str(reverse_action.get("action_type") or "")
    return_record = {
        "node": new_id,
        "step": host._action_count,
        "verdict": "action" if reverse_action else "null",
        "reason": str(decision.get("reason") or "")[:200],
        "source": source_id,
        "action_type": action_type,
        "target": visible_target,
    }
    host.review_debug.record_agent(
        "reverse_edge_explorer", **return_record)
    logger.info(
        "Reverse-edge decision %s -> %s: action=%s target=%s reason=%s",
        source_id, new_id,
        action_type or "null", visible_target,
        str(decision.get("reason") or "")[:200])
    if not reverse_action:
        reason = str(decision.get("reason") or "no reliable action")
        _record_forward_reverse_probe(host, _event_index, {
            "status": "candidate_not_found",
            "intended_target": source_id,
            "reason": reason[:200],
        })
        host._return_probe_status[(source_id, new_id)] = {
            "status": "candidate_not_found", "reason": reason[:200],
        }
        return done(StageDirective.CONTINUE)

    effect_kind = _probe_effect_kind(
        host, new_id, visible_target=bool(visible_target))
    description = (
        f"Reverse-edge probe through visible target: {visible_target}"
        if visible_target else "Reverse-edge probe through platform return"
    )
    trigger_attempt_id = _forward_attempt_id(host, _event_index)
    probe_evidence = {
        "route_context": source_id,
        "prediction_provenance": "reverse_probe",
        "reverse_probe": {
            "status": "attempted",
            "trigger_forward_attempt_id": trigger_attempt_id,
            "intended_target": source_id,
        },
    }
    probe_event_index = host.graph.record_action_event(
        source=new_id, target="", action=reverse_action,
        element_label=visible_target,
        semantic_description=description,
        outcome="attempted", committed=False,
        landing_verified=None, evidence=probe_evidence,
    )
    probe_attempt_id = _forward_attempt_id(host, probe_event_index)
    _record_forward_reverse_probe(host, _event_index, {
        "status": "attempted",
        "intended_target": source_id,
        "probe_action_attempt_id": probe_attempt_id,
    })
    return_step = {
        "source_id": new_id,
        "source_region_id": "",
        "name": visible_target or "__NATIVE_ACTION__return",
        "region": "",
        "dst": source_id,
        "route_context": source_id,
        "provenance": "reverse_probe",
        "effect_kind": effect_kind,
        "element_id": "",
        "action": reverse_action,
        "probe_event_index": probe_event_index,
        "trigger_forward_attempt_id": trigger_attempt_id,
        "intended_target": source_id,
        "virtual_action": not bool(visible_target),
        "explore_on_verify": bool(visible_target),
        # Ephemeral live evidence only.  The graph stores the persisted forward
        # attempt screenshot path, not these bytes.
        "_source_reference_screenshot": source_shot,
    }
    result = host.router.verify_return_path(
        current_obs, source_id, new_id, return_step=return_step)
    probe_status = _reverse_probe_result_status(
        host, probe_event_index, result)
    try:
        probe_attempt = host.graph.action_attempt(probe_event_index)
    except Exception:
        probe_attempt = {}
    if probe_attempt.get("committed") is not True:
        evidence = dict(probe_attempt.get("evidence") or probe_evidence)
        reverse_evidence = dict(evidence.get("reverse_probe") or {})
        reverse_evidence.update({
            "status": probe_status,
            "trigger_forward_attempt_id": trigger_attempt_id,
            "intended_target": source_id,
        })
        evidence["reverse_probe"] = reverse_evidence
        failure_outcomes = {
            "grounding_failed": "grounding_failed",
            "dispatch_unknown": "dispatch_unknown",
            "identity_unknown": "identity_unknown",
            "no_effect": "no_effect",
            "off_app": "off_app",
        }
        host.graph.update_action_event(
            probe_event_index,
            target=(new_id if probe_status == "no_effect" else ""),
            outcome=failure_outcomes.get(probe_status, "not_attempted"),
            detail=str(result.failure_kind or probe_status),
            landing_verified=(
                True if probe_status == "no_effect" else False),
            committed=False,
            evidence=evidence,
        )
        probe_attempt = host.graph.action_attempt(probe_event_index)
    actual_target = str(probe_attempt.get("target") or "")
    _record_forward_reverse_probe(host, _event_index, {
        "status": probe_status,
        "intended_target": source_id,
        "actual_target": actual_target,
        "probe_action_attempt_id": probe_attempt_id,
    })
    host._return_probe_status[(source_id, new_id)] = {
        "status": probe_status,
        "reason": result.failure_kind,
        "landed_id": result.landed_id,
        "action_type": action_type,
        "control": visible_target,
        "probe_action_attempt_id": probe_attempt_id,
    }
    host.review_debug.record_event(
        "reverse_probe", source=source_id, target=new_id,
        status=probe_status, failure_kind=result.failure_kind,
        landed=result.landed_id)
    if result.arrived:
        current_obs = result.observation
        current_id, current_path, current_hints = \
            _refresh_verified_return_landing(
                host, current_obs, new_id)
        return done(StageDirective.CONTINUE)
    current_obs = result.observation
    if result.status == "dispatch_unknown":
        host.graph.stop_reason = "routing_incomplete"
        host.graph.save(host.graph_save_path)
        logger.error(
            "reverse action dispatch for %s -> %s is uncertain; the supplied "
            "observation may be stale, stopping fail-closed",
            new_id, source_id)
        return done(StageDirective.STOP)
    known_actual = _known_return_failure_landing(host, result, new_id)
    if known_actual is not None:
        current_id, current_path, current_hints = known_actual
        host.graph.save(host.graph_save_path)
        logger.warning(
            "return-path verification for %s -> %s could not restore the "
            "probe target (%s); continuing from verified actual landing %s",
            source_id, new_id, result.failure_kind, current_id)
        return done(StageDirective.CONTINUE)
    recovered = recover_route_observation(host, result.observation)
    if recovered.on_app and recovered.observation is not None:
        restored_id, restored_path, restored_hints, _ = \
            host._register_landed(recovered.observation)
        if restored_id is not None:
            current_obs = recovered.observation
            current_id = restored_id
            current_path = list(restored_path)
            current_hints = list(restored_hints)
            host._return_probe_status[(source_id, new_id)].update({
                "status": "recovered_after_probe_failure",
                "landed_id": restored_id,
            })
            host.review_debug.record_event(
                "return_probe_recovered", source=source_id, target=new_id,
                failure_kind=result.failure_kind, landed=restored_id)
            logger.warning(
                "return-path probe for %s -> %s failed (%s); recovered "
                "the app at verified landing %s and continued",
                source_id, new_id, result.failure_kind, restored_id)
            return done(StageDirective.CONTINUE)
    host.graph.stop_reason = "routing_incomplete"
    host.graph.save(host.graph_save_path)
    logger.error(
        "return-path verification for %s -> %s failed (%s); actual landing=%s",
        source_id, new_id, result.failure_kind, result.landed_id)
    return done(StageDirective.STOP)
