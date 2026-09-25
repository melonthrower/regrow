"""Offline induction of evidence-backed capabilities from ActionAttempts."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Tuple

from gui_rewalk.src.core.graph.effect_observation import (
    EffectObservationValidationError,
    normalize_effect_observation,
)


CAPABILITY_GRAPH_SCHEMA = "gui_rewalk.capability_graph.v1"
AUTONOMOUS_ENTRY_UID_PREFIX = "autonomous-entry:"
AUTONOMOUS_ELEMENT_UID_PREFIX = "autonomous-element:"
_BUSINESS_EFFECTS = {
    "state_change", "object_creation", "object_removal", "query_result",
}
_NEGATIVE_EFFECTS = {"no_effect", "blocked", "error"}
_GEOMETRY_KEYS = {
    "x", "y", "x1", "x2", "y1", "y2", "bbox", "bbox_1000", "center",
    "center_1000", "point", "point_1000", "coordinates", "coordinate",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _portable(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _portable(item)
            for key, item in value.items()
            if str(key).lower() not in _GEOMETRY_KEYS
        }
    if isinstance(value, list):
        return [_portable(item) for item in value]
    if isinstance(value, tuple):
        return [_portable(item) for item in value]
    return copy.deepcopy(value)


def _parameterized_value(value: Any, bindings: Dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _parameterized_value(item, bindings)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_parameterized_value(item, bindings) for item in value]
    if isinstance(value, tuple):
        return [_parameterized_value(item, bindings) for item in value]
    encoded = _stable(value)
    matches = [
        name for name, bound in sorted(bindings.items())
        if encoded == _stable(bound)
    ]
    if len(matches) == 1:
        return "{{" + matches[0] + "}}"
    return copy.deepcopy(value)


def _parameterized_recipe(
    recipe: List[Dict[str, Any]], observation: Dict[str, Any],
) -> List[Dict[str, Any]]:
    bindings = dict(observation.get("parameter_bindings") or {})
    result = copy.deepcopy(recipe)
    if not bindings:
        return result
    for action in result:
        for field in ("selector", "parameters", "text"):
            if field in action:
                action[field] = _parameterized_value(
                    action[field], bindings)
    return result


def _recipe_parameter_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            keys.update(_recipe_parameter_keys(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys.update(_recipe_parameter_keys(item))
    elif (isinstance(value, str) and value.startswith("{{")
          and value.endswith("}}")):
        keys.add(value[2:-2])
    return keys


def _attempts(graph: Any) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    edges = getattr(graph, "action_edges", None)
    if edges is None and isinstance(graph, dict):
        edges = graph.get("action_edges")
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for edge in edges or []:
        if not isinstance(edge, dict):
            continue
        for attempt in edge.get("attempts") or []:
            if isinstance(attempt, dict):
                pairs.append((edge, attempt))
    return sorted(pairs, key=lambda pair: int(pair[1].get("action_index", 0) or 0))


def _observation_items(evidence: Dict[str, Any]) -> Iterable[Any]:
    raw = evidence.get("effect_observations")
    return raw if isinstance(raw, list) else []


def _valid_start(attempt: Dict[str, Any], evidence: Dict[str, Any]) -> bool:
    entry_start = (
        evidence.get("explicit_entry_task") is True
        and bool(_text(evidence.get("entry_id")))
        and bool(_text(evidence.get("source_region_ref")))
    )
    region_start = (
        evidence.get("region_probe_task") is True
        and evidence.get("region_probe_start") is True
        and not _text(evidence.get("entry_id"))
        and bool(_text(evidence.get("source_region_ref")))
    )
    return (
        attempt.get("committed") is True
        and (entry_start or region_start)
        and evidence.get("direct_action_backfill") is not True
        and evidence.get("no_gui_action") is not True
        and _text(evidence.get("discovery_source")) != "direct_action_backfill"
    )


def _probe_key(evidence: Dict[str, Any], *, allow_legacy_entry: bool = False) -> str:
    key = _text(evidence.get("probe_id") or evidence.get("exploration_task_id"))
    if key or not allow_legacy_entry:
        return key
    entry_id = _text(evidence.get("entry_id"))
    return f"legacy_entry:{entry_id}" if entry_id else ""


def _attempt_ref(edge: Dict[str, Any], attempt: Dict[str, Any], role: str) -> Dict[str, Any]:
    return {
        "action_edge_id": _text(attempt.get("action_edge_id") or edge.get("action_edge_id")),
        "attempt_id": _text(attempt.get("attempt_id") or attempt.get("event_id")),
        "role": role,
    }



def _normalized_attempt_observations(
    edge: Dict[str, Any], attempt: Dict[str, Any], evidence: Dict[str, Any],
) -> List[Dict[str, Any]]:
    observations: List[Dict[str, Any]] = []
    for index, raw in enumerate(_observation_items(evidence)):
        try:
            observation = normalize_effect_observation(raw)
        except EffectObservationValidationError:
            continue
        observation = copy.deepcopy(observation)
        observation["evidence_ref"] = {
            **_attempt_ref(edge, attempt, "effect"),
            "observation_index": index,
        }
        observations.append(observation)
    return observations


def _attempt_action(
    edge: Dict[str, Any], attempt: Dict[str, Any],
) -> Dict[str, Any]:
    action = _portable(
        attempt.get("action") or edge.get("action") or {})
    evidence = attempt.get("evidence") or {}
    if not isinstance(evidence, dict):
        return action
    element_uid = _text(
        attempt.get("element_id") or edge.get("element_id"))
    if not element_uid.startswith((
            AUTONOMOUS_ENTRY_UID_PREFIX,
            AUTONOMOUS_ELEMENT_UID_PREFIX)):
        element_uid = ""
    region_ref = _text(evidence.get("source_region_ref"))
    if element_uid or region_ref:
        selector = dict(action.get("selector") or {})
        if element_uid:
            selector["element_id"] = element_uid
        if region_ref:
            selector["region_ids"] = [region_ref]
        action["selector"] = selector
    return action


def _entry_surface(graph: Any, edge: Dict[str, Any], attempt: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    state_id = _text(attempt.get("source") or edge.get("source"))
    node: Dict[str, Any] = {}
    state_graph = getattr(graph, "graph", None)
    nodes = getattr(state_graph, "nodes", {})
    if state_id in nodes:
        node = dict(nodes[state_id] or {})
    entry_id = _text(evidence.get("entry_id"))
    element_uid = _text(
        attempt.get("element_id") or edge.get("element_id"))
    if not element_uid.startswith((
            AUTONOMOUS_ENTRY_UID_PREFIX,
            AUTONOMOUS_ELEMENT_UID_PREFIX)):
        element_uid = ""
    if not element_uid and entry_id:
        element_uid = AUTONOMOUS_ENTRY_UID_PREFIX + entry_id
    return {
        "page_id": _text(edge.get("source_page_id") or node.get("page_id")),
        "variant_id": _text(edge.get("source_variant_id") or node.get("variant_id")),
        "state_id": state_id,
        "region_ref": _text(evidence.get("source_region_ref")),
        "entry_id": entry_id,
        "element_uid": element_uid,
        "selector": _attempt_action(edge, attempt).get("selector", {}),
    }


@dataclass
class ProbeEpisode:
    probe_id: str
    entry_surface: Dict[str, Any]
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    recipe: List[Dict[str, Any]] = field(default_factory=list)
    observations: List[Dict[str, Any]] = field(default_factory=list)
    outcome: str = "inconclusive"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "entry_surface": copy.deepcopy(self.entry_surface),
            "attempt_refs": copy.deepcopy(self.attempts),
            "effect_refs": [
                copy.deepcopy(item["evidence_ref"])
                for item in self.observations if "evidence_ref" in item
            ],
            "outcome": self.outcome,
        }


def _append_attempt(
    episode: ProbeEpisode, edge: Dict[str, Any], attempt: Dict[str, Any], role: str,
) -> None:
    episode.attempts.append(_attempt_ref(edge, attempt, role))
    action = _attempt_action(edge, attempt)
    if attempt.get("committed") is True and action:
        episode.recipe.append(action)


def build_probe_episodes(graph: Any) -> List[ProbeEpisode]:
    """Group real explicit-entry attempts into closed or inconclusive probes."""
    active: Dict[str, ProbeEpisode] = {}
    finished: List[ProbeEpisode] = []
    for edge, attempt in _attempts(graph):
        evidence = attempt.get("evidence") or {}
        if not isinstance(evidence, dict):
            continue
        start = _valid_start(attempt, evidence)
        key = _probe_key(evidence, allow_legacy_entry=start)
        if not key:
            continue
        if start:
            surface = _entry_surface(graph, edge, attempt, evidence)
            prior = active.get(key)
            if (prior is not None
                    and prior.entry_surface.get("entry_id") == surface.get("entry_id")
                    and prior.entry_surface.get("region_ref") == surface.get("region_ref")):
                episode = prior
                episode.recipe.clear()
                episode.outcome = "inconclusive"
                _append_attempt(episode, edge, attempt, "entry_retry")
            else:
                if prior is not None:
                    finished.append(prior)
                episode = ProbeEpisode(key, surface)
                active[key] = episode
                _append_attempt(episode, edge, attempt, "entry")
        else:
            episode = active.get(key)
            if episode is None:
                continue
            _append_attempt(episode, edge, attempt, "step")

        episode = active.get(key)
        if episode is None:
            continue
        if attempt.get("committed") is not True:
            continue
        observations = _normalized_attempt_observations(edge, attempt, evidence)
        episode.observations.extend(observations)
        closes_positive = any(
            item["verdict"] == "supported"
            and item["effect_kind"] in _BUSINESS_EFFECTS
            for item in observations)
        closes_negative = (
            _text(attempt.get("outcome")).lower()
            in {"no_effect", "no_visible_change", "blocked", "error", "execution_error"}
            or any(
                item["verdict"] == "refuted"
                or item["effect_kind"] in _NEGATIVE_EFFECTS
                for item in observations)
        )
        if closes_positive:
            episode.outcome = "supported"
            finished.append(episode)
            del active[key]
        elif closes_negative:
            episode.outcome = "negative"
    finished.extend(active[key] for key in sorted(active))
    return finished


def _observed_entry_prefix(
    graph: Any,
    trace: List[Tuple[Dict[str, Any], Dict[str, Any]]],
    episode: ProbeEpisode,
    observation: Dict[str, Any],
) -> Tuple[ProbeEpisode, Dict[str, Any]]:
    """Use only the real connected path from a formal Entry to this effect."""
    effect_ref = observation.get("evidence_ref") or {}
    effect_key = (
        _text(effect_ref.get("action_edge_id")),
        _text(effect_ref.get("attempt_id")),
    )
    position = next((
        index for index, (edge, attempt) in enumerate(trace)
        if (
            _text(attempt.get("action_edge_id") or edge.get("action_edge_id")),
            _text(attempt.get("attempt_id") or attempt.get("event_id")),
        ) == effect_key
    ), -1)
    if position < 0:
        return episode, observation

    effect_edge, effect_attempt = trace[position]
    if (effect_attempt.get("committed") is not True
            or effect_attempt.get("landing_verified") is not True):
        return episode, observation
    effect_source = _text(
        effect_attempt.get("source") or effect_edge.get("source"))
    if not effect_source:
        return episode, observation

    chain = [(effect_edge, effect_attempt)]
    merged_bindings = copy.deepcopy(
        observation.get("parameter_bindings") or {})
    current_source = effect_source
    entry_pair: Tuple[Dict[str, Any], Dict[str, Any]] | None = None
    effect_evidence = effect_attempt.get("evidence") or {}
    if (isinstance(effect_evidence, dict)
            and effect_evidence.get("explicit_entry_task") is True
            and _valid_start(effect_attempt, effect_evidence)):
        entry_pair = (effect_edge, effect_attempt)

    for edge, attempt in reversed(trace[:position]):
        if attempt.get("committed") is not True:
            continue
        if attempt.get("landing_verified") is not True:
            break
        source = _text(attempt.get("source") or edge.get("source"))
        target = _text(attempt.get("target") or edge.get("target"))
        if not source or target != current_source:
            break
        evidence = attempt.get("evidence") or {}
        if not isinstance(evidence, dict):
            break
        prior_observations = [
            item for item in _normalized_attempt_observations(
                edge, attempt, evidence)
            if item.get("verdict") == "supported"
            and item.get("effect_kind") in _BUSINESS_EFFECTS
        ]
        if any(item.get("effect_kind") in {
                "state_change", "object_creation", "object_removal"}
               for item in prior_observations):
            break
        for item in prior_observations:
            for name, value in (item.get("parameter_bindings") or {}).items():
                if (name in merged_bindings
                        and _stable(merged_bindings[name]) != _stable(value)):
                    return episode, observation
                merged_bindings[name] = copy.deepcopy(value)
        chain.insert(0, (edge, attempt))
        current_source = source
        if (evidence.get("explicit_entry_task") is True
                and _valid_start(attempt, evidence)):
            entry_pair = (edge, attempt)
            break

    if entry_pair is None or len(chain) == 1:
        return episode, observation
    first_edge, first_attempt = entry_pair
    first_evidence = first_attempt.get("evidence") or {}
    expanded = ProbeEpisode(
        probe_id=episode.probe_id,
        entry_surface=_entry_surface(
            graph, first_edge, first_attempt, first_evidence),
        outcome=episode.outcome,
    )
    for index, (edge, attempt) in enumerate(chain):
        expanded.attempts.append(_attempt_ref(
            edge, attempt, "entry" if index == 0 else "step"))
        action = _attempt_action(edge, attempt)
        if not action:
            return episode, observation
        expanded.recipe.append(action)
    expanded_observation = copy.deepcopy(observation)
    expanded_observation["parameter_bindings"] = merged_bindings
    expanded.observations.append(expanded_observation)
    return expanded, expanded_observation


def _predicate(
    observation: Dict[str, Any], confirmed_parameters: set[str] | None = None,
) -> Dict[str, Any]:
    bindings = observation.get("parameter_bindings") or {}
    confirmed_parameters = confirmed_parameters or set()
    clauses = []
    for change in observation.get("observed_changes") or []:
        value: Any = copy.deepcopy(change.get("after"))
        for key, bound in bindings.items():
            if key in confirmed_parameters and _stable(bound) == _stable(value):
                value = {"value_from_parameter": key}
                break
        clauses.append({"equals": {
            "scope": copy.deepcopy(change.get("scope") or {}),
            "fact": _text(change.get("fact")), "value": value,
        }})
    return {"all": clauses}


def _capability_id(name: str, observation: Dict[str, Any]) -> str:
    payload = {
        "name": name.casefold(),
        "effect_kind": observation.get("effect_kind"),
        "facts": sorted(
            (_text(item.get("scope", {}).get("region_ref")), _text(item.get("fact")))
            for item in observation.get("observed_changes") or []),
        "parameter_keys": sorted((observation.get("parameter_bindings") or {}).keys()),
    }
    return "cap_" + hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()[:16]


def _effects(observation: Dict[str, Any], confirmed_parameters: set[str]) -> List[Dict[str, Any]]:
    changes = []
    bindings = observation.get("parameter_bindings") or {}
    for change in observation.get("observed_changes") or []:
        value: Any = copy.deepcopy(change.get("after"))
        for key, bound in bindings.items():
            if key in confirmed_parameters and _stable(bound) == _stable(value):
                value = {"value_from_parameter": key}
                break
        changes.append({
            "scope": copy.deepcopy(change.get("scope") or {}),
            "fact": _text(change.get("fact")), "value": value,
        })
    return [{"kind": observation.get("effect_kind"), "changes": changes}]


def _attempt_lookup(
    graph: Any,
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    lookup: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for edge, attempt in _attempts(graph):
        key = (
            _text(attempt.get("action_edge_id") or edge.get("action_edge_id")),
            _text(attempt.get("attempt_id") or attempt.get("event_id")),
        )
        if not all(key):
            continue
        if key in lookup and lookup[key] is not attempt:
            raise ValueError(f"duplicate ActionAttempt reference: {key!r}")
        lookup[key] = attempt
    return lookup


def _episode_state_path(
    episode: ProbeEpisode,
    observation: Dict[str, Any],
    attempts: Dict[Tuple[str, str], Dict[str, Any]],
) -> Tuple[str, str] | None:
    start = _text(episode.entry_surface.get("state_id"))
    effect_ref = observation.get("evidence_ref") or {}
    if not start or not isinstance(effect_ref, dict):
        return None
    effect_key = (
        _text(effect_ref.get("action_edge_id")),
        _text(effect_ref.get("attempt_id")),
    )
    current = start
    final_key: Tuple[str, str] | None = None
    for ref in episode.attempts:
        key = (
            _text(ref.get("action_edge_id")),
            _text(ref.get("attempt_id")),
        )
        attempt = attempts.get(key)
        if attempt is None or attempt.get("committed") is not True:
            continue
        if (attempt.get("landing_verified") is not True
                or _text(attempt.get("source")) != current):
            return None
        target = _text(attempt.get("target"))
        if not target:
            return None
        current = target
        final_key = key
    if final_key != effect_key:
        return None
    return start, current


def _inverse_object_change(
    created: Dict[str, Any], removed: Dict[str, Any],
) -> bool:
    if (created.get("effect_kind") != "object_creation"
            or removed.get("effect_kind") != "object_removal"):
        return False
    created_changes = created.get("observed_changes") or []
    removed_changes = removed.get("observed_changes") or []
    if len(created_changes) != 1 or len(removed_changes) != 1:
        return False
    before, after = created_changes[0], removed_changes[0]
    return (
        _text(before.get("scope", {}).get("region_ref"))
        == _text(after.get("scope", {}).get("region_ref"))
        and _text(before.get("fact")) == _text(after.get("fact"))
        and _stable(before.get("before")) == _stable(after.get("after"))
        and _stable(before.get("after")) == _stable(after.get("before"))
    )


def _confirmed_parameter_names(capability: Dict[str, Any]) -> set[str]:
    return {
        _text(item.get("name"))
        for item in capability.get("parameters") or []
        if isinstance(item, dict) and _text(item.get("name"))
    }


def _cleanup_parameter_map(
    created: Dict[str, Any], removed: Dict[str, Any],
) -> Dict[str, str]:
    source_bindings = created.get("parameter_bindings") or {}
    cleanup_bindings = removed.get("parameter_bindings") or {}
    result: Dict[str, str] = {}
    for cleanup_name, cleanup_value in cleanup_bindings.items():
        matches = [
            source_name for source_name, source_value
            in source_bindings.items()
            if _stable(source_value) == _stable(cleanup_value)
        ]
        if len(matches) == 1:
            result[_text(cleanup_name)] = _text(matches[0])
    return result


def _cleanup_relations(
    graph: Any,
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    attempts = _attempt_lookup(graph)
    creations = [
        item for item in candidates
        if item["capability"].get("verification_level") == "effect_verified"
        and item["effect_kind"] == "object_creation"
    ]
    removals = [
        item for item in candidates
        if item["capability"].get("verification_level") == "effect_verified"
        and item["effect_kind"] == "object_removal"
    ]
    relations: List[Dict[str, Any]] = []
    for creation in creations:
        for removal in removals:
            cleanup_parameter_names = _confirmed_parameter_names(
                removal["capability"])
            witnesses: List[Dict[str, Any]] = []
            seen_witnesses: set[str] = set()
            for source_episode, source_observation in creation["matching"]:
                source_path = _episode_state_path(
                    source_episode, source_observation, attempts)
                if source_path is None:
                    continue
                baseline_state, effect_state = source_path
                for cleanup_episode, cleanup_observation in removal["matching"]:
                    if not _inverse_object_change(
                            source_observation, cleanup_observation):
                        continue
                    cleanup_path = _episode_state_path(
                        cleanup_episode, cleanup_observation, attempts)
                    if cleanup_path is None:
                        continue
                    if cleanup_path != (effect_state, baseline_state):
                        continue
                    parameter_map = _cleanup_parameter_map(
                        source_observation, cleanup_observation)
                    if not cleanup_parameter_names.issubset(parameter_map):
                        continue
                    witness = {
                        "baseline_state_id": baseline_state,
                        "effect_state_id": effect_state,
                        "parameter_map": parameter_map,
                        "source_observation": source_observation,
                        "cleanup_observation": cleanup_observation,
                    }
                    key = _stable({
                        "source": source_observation.get("evidence_ref"),
                        "cleanup": cleanup_observation.get("evidence_ref"),
                    })
                    if key not in seen_witnesses:
                        witnesses.append(witness)
                        seen_witnesses.add(key)
            if len(witnesses) < 2:
                continue
            state_pairs = {
                (item["baseline_state_id"], item["effect_state_id"])
                for item in witnesses
            }
            parameter_maps = {
                tuple(sorted(item["parameter_map"].items()))
                for item in witnesses
            }
            if len(state_pairs) != 1 or len(parameter_maps) != 1:
                continue
            baseline_state, effect_state = next(iter(state_pairs))
            parameter_map = dict(next(iter(parameter_maps)))
            parameter_links = []
            valid_links = True
            for cleanup_name, source_name in sorted(parameter_map.items()):
                values = {
                    _stable(item["source_observation"][
                        "parameter_bindings"][source_name]):
                    item["source_observation"][
                        "parameter_bindings"][source_name]
                    for item in witnesses
                }
                if len(values) < 2:
                    valid_links = False
                    break
                parameter_links.append({
                    "source_parameter": source_name,
                    "cleanup_parameter": cleanup_name,
                    "values": sorted(values.values(), key=_stable),
                })
            if not valid_links:
                continue
            source_id = _text(
                creation["capability"].get("capability_id"))
            cleanup_id = _text(
                removal["capability"].get("capability_id"))
            identity = {
                "source_capability_id": source_id,
                "cleanup_capability_id": cleanup_id,
                "baseline_state_id": baseline_state,
                "effect_state_id": effect_state,
                "parameter_links": parameter_links,
            }
            relations.append({
                "relation_id": (
                    "rel_" + hashlib.sha256(
                        _stable(identity).encode("utf-8")).hexdigest()[:16]),
                "relation_type": "cleanup_cycle",
                **identity,
                "evidence_refs": [{
                    "source_effect_ref": copy.deepcopy(
                        item["source_observation"]["evidence_ref"]),
                    "cleanup_effect_ref": copy.deepcopy(
                        item["cleanup_observation"]["evidence_ref"]),
                } for item in witnesses],
            })
    return sorted(relations, key=lambda item: item["relation_id"])


def _snapshot_parts(entries_snapshot: Any, regions_snapshot: Any) -> Tuple[List[Any], List[Any]]:
    if not isinstance(entries_snapshot, dict) or not isinstance(regions_snapshot, dict):
        raise ValueError("entries and Region snapshots must be JSON objects")
    entries = entries_snapshot.get("entries")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise ValueError("entries must be a list")
    nested = regions_snapshot.get("region_groups")
    if nested is None:
        groups = regions_snapshot.get("groups")
    else:
        if not isinstance(nested, dict):
            raise ValueError("region_groups must be an object")
        groups = nested.get("groups")
    if groups is None:
        groups = []
    if not isinstance(groups, list):
        raise ValueError("Region groups must be a list")
    return entries, groups


def _snapshot_mapping(entries_snapshot: Any, regions_snapshot: Any) -> Dict[str, str]:
    entries, groups = _snapshot_parts(entries_snapshot, regions_snapshot)
    region_refs: Dict[Tuple[str, str], str] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        ref = _text(group.get("region_ref"))
        if not ref:
            continue
        occurrences = [group.get("representative")] + list(group.get("occurrences") or [])
        for occurrence in occurrences:
            if not isinstance(occurrence, dict):
                continue
            key = (_text(occurrence.get("page_name")).casefold(),
                   _text(occurrence.get("region_name")).casefold())
            if not all(key):
                continue
            previous = region_refs.get(key)
            if previous and previous != ref:
                raise ValueError("conflicting Region refs for entry occurrence")
            region_refs[key] = ref
    mapping: Dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = _text(entry.get("entry_id"))
        key = (_text(entry.get("page_name")).casefold(),
               _text(entry.get("region_name")).casefold())
        ref = region_refs.get(key, "")
        if not entry_id or not ref:
            continue
        previous = mapping.get(entry_id)
        if previous and previous != ref:
            raise ValueError("conflicting Region refs for entry_id")
        mapping[entry_id] = ref
    return mapping


def _page_states(graph: Any, page_name: str) -> List[str]:
    wanted = _text(page_name).casefold()
    return [
        str(state_id)
        for state_id, node in graph.graph.nodes(data=True)
        if _text(node.get("page_name")).casefold() == wanted
    ]


def _resolve_occurrence_states(
    graph: Any,
    page_name: str,
    state_ids: List[str],
    *,
    subject: str,
) -> List[str]:
    resolved: List[str] = []
    for raw_state_id in state_ids:
        state_id = _text(raw_state_id)
        if state_id and state_id not in resolved:
            resolved.append(state_id)
    if not resolved:
        page_states = _page_states(graph, page_name)
        if len(page_states) != 1:
            raise ValueError(
                f"{subject} on autonomous Page {page_name!r} needs explicit "
                f"State occurrence membership; found {len(page_states)} "
                "candidate States")
        resolved = page_states
    for state_id in resolved:
        if state_id not in graph.graph:
            raise ValueError(f"{subject} references unknown State {state_id!r}")
        actual_page = _text(graph.graph.nodes[state_id].get("page_name"))
        if actual_page.casefold() != _text(page_name).casefold():
            raise ValueError(
                f"{subject} State {state_id!r} belongs to Page "
                f"{actual_page!r}, not {page_name!r}")
    return resolved


def _formal_region_occurrences(
    graph: Any, groups: List[Any],
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    occurrences: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("each Region group must be an object")
        region_ref = _text(group.get("region_ref"))
        if not region_ref:
            raise ValueError("each Region group needs region_ref")
        raw_occurrences = [group.get("representative")] + list(
            group.get("occurrences") or [])
        for raw in raw_occurrences:
            if not isinstance(raw, dict):
                raise ValueError("each Region occurrence must be an object")
            page_name = _text(raw.get("page_name"))
            region_name = _text(raw.get("region_name"))
            if not page_name or not region_name:
                raise ValueError(
                    "each Region occurrence needs page_name and region_name")
            raw_state_ids = raw.get("state_ids") or []
            if not isinstance(raw_state_ids, list):
                raise ValueError("Region occurrence state_ids must be a list")
            legacy_state_id = _text(raw.get("state_id"))
            state_ids = (
                ([legacy_state_id] if legacy_state_id else [])
                + [_text(item) for item in raw_state_ids]
            )
            key = (page_name.casefold(), region_name.casefold())
            previous = occurrences.get(key)
            if previous and previous["region_ref"] != region_ref:
                raise ValueError("conflicting Region refs for one occurrence")
            if previous is None:
                previous = {
                    "page_name": page_name,
                    "region_name": region_name,
                    "region_ref": region_ref,
                    "state_ids": [],
                }
                occurrences[key] = previous
            for state_id in state_ids:
                if state_id and state_id not in previous["state_ids"]:
                    previous["state_ids"].append(state_id)
    for region in occurrences.values():
        region["state_ids"] = _resolve_occurrence_states(
            graph,
            region["page_name"],
            region["state_ids"],
            subject=f"Region {region['region_ref']!r}",
        )
    return occurrences


def project_autonomous_inventory(
    graph: Any, entries_snapshot: Any, regions_snapshot: Any,
) -> int:
    """Project formal autonomous Regions/Entries into a collection graph.

    The sidecars remain the traversal ledger.  This projection adds only stable
    semantic identity to the annotated graph: observation-local bboxes and
    frame ids are deliberately ignored so M13 must ground every pointer action
    on its current screenshot.
    """
    entries, groups = _snapshot_parts(entries_snapshot, regions_snapshot)
    pending_actions = entries_snapshot.get("pending_actions") or []
    if not isinstance(pending_actions, list):
        raise ValueError("pending_actions must be a list")
    if pending_actions:
        raise ValueError("cannot project autonomous inventory with a pending action")

    regions = _formal_region_occurrences(graph, groups)

    records: List[Dict[str, Any]] = []
    seen_entry_ids = set()
    seen_targets: Dict[Tuple[str, str, str, str, str, str], str] = {}
    for raw in entries:
        if not isinstance(raw, dict):
            raise ValueError("each autonomous Entry must be an object")
        if _text(raw.get("status")) == "invalidated":
            continue
        entry_id = _text(raw.get("entry_id"))
        page_name = _text(raw.get("page_name"))
        region_name = _text(raw.get("region_name"))
        target = _text(raw.get("target"))
        operation = _text(raw.get("operation")) or target
        operation_scope = _text(raw.get("operation_scope")) or "element"
        direction = _text(raw.get("direction"))
        if not entry_id or not page_name or not region_name or not target:
            raise ValueError(
                "each autonomous Entry needs entry_id, page_name, region_name "
                "and target")
        if entry_id in seen_entry_ids:
            raise ValueError(f"duplicate autonomous entry_id: {entry_id}")
        seen_entry_ids.add(entry_id)
        region = regions.get((page_name.casefold(), region_name.casefold()))
        if region is None:
            raise ValueError(
                f"Entry {entry_id!r} has no formal Region occurrence")

        raw_state_ids = raw.get("source_state_ids")
        if raw_state_ids is not None and not isinstance(raw_state_ids, list):
            raise ValueError("Entry source_state_ids must be a list")
        source_state_id = _text(raw.get("source_state_id"))
        declared_state_ids = [
            _text(item) for item in (raw_state_ids or [])
        ]
        if raw_state_ids is not None:
            if source_state_id and source_state_id not in declared_state_ids:
                raise ValueError(
                    f"Entry {entry_id!r} source_state_id is not present in "
                    "source_state_ids")
        elif source_state_id:
            declared_state_ids.append(source_state_id)
        state_ids = _resolve_occurrence_states(
            graph,
            page_name,
            declared_state_ids,
            subject=f"Entry {entry_id!r}",
        )
        for state_id in state_ids:
            if state_id not in region["state_ids"]:
                raise ValueError(
                    f"Entry {entry_id!r} State {state_id!r} has no owner "
                    f"Region {region['region_ref']!r} occurrence")
            target_key = (
                state_id, region["region_ref"], operation_scope.casefold(),
                operation.casefold(), direction.casefold(), target.casefold())
            previous = seen_targets.get(target_key)
            if previous and previous != entry_id:
                raise ValueError(
                    f"Entries {previous!r} and {entry_id!r} ambiguously name "
                    "the same Region operation target in one State")
            seen_targets[target_key] = entry_id
            records.append({
                "entry_id": entry_id,
                "uid": AUTONOMOUS_ENTRY_UID_PREFIX + entry_id,
                "target": target,
                "operation": operation,
                "subject": _text(raw.get("subject")) or region["region_name"],
                "control_type": _text(raw.get("control_type")) or "control",
                "entry_status": _text(raw.get("status")) or "discovered",
                "exploration_policy": (
                    _text(raw.get("exploration_policy")) or "explore"),
                "category": "navigation",
                "source": "semantic_inventory",
                "state_id": state_id,
                "region_name": region["region_name"],
                "region_ref": region["region_ref"],
            })

    entry_occurrences = {
        (record["entry_id"], record["state_id"]): record
        for record in records
    }
    seen_action_elements: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for edge, attempt in _attempts(graph):
        evidence = attempt.get("evidence") or {}
        if not isinstance(evidence, dict):
            continue
        element_uid = _text(
            attempt.get("element_id") or edge.get("element_id"))
        if not element_uid.startswith((
                AUTONOMOUS_ENTRY_UID_PREFIX,
                AUTONOMOUS_ELEMENT_UID_PREFIX)):
            continue
        state_id = _text(attempt.get("source") or edge.get("source"))
        region_ref = _text(evidence.get("source_region_ref"))
        target = _text(
            attempt.get("element_label") or edge.get("element_label"))
        entry_id = _text(evidence.get("entry_id"))
        if not state_id or not region_ref or not target:
            raise ValueError(
                "action Element evidence needs source State, Region and name")
        edge_uid = _text(edge.get("element_id"))
        if edge_uid and edge_uid != element_uid:
            raise ValueError("ActionEdge and ActionAttempt Element UIDs conflict")
        review = evidence.get("click_review")
        if not isinstance(review, dict) or not (
            _text(review.get("decision")).casefold() == "approve"
            and review.get("point_matches_target") is True
            and review.get("target_matches_request") is True
            and _text(review.get("risk")).casefold() == "safe"
            and bool(_text(review.get("observed_target")))
            and (
                bool(entry_id)
                or _text(review.get("observed_target")).casefold()
                == target.casefold())
        ):
            raise ValueError(
                "action Element evidence needs one approved exact target review")
        owners = [
            region for region in regions.values()
            if region["region_ref"] == region_ref
            and state_id in region["state_ids"]
        ]
        if len(owners) != 1:
            raise ValueError(
                f"action Element {element_uid!r} does not resolve to one "
                "formal Region occurrence")
        region = owners[0]
        if entry_id:
            if element_uid != AUTONOMOUS_ENTRY_UID_PREFIX + entry_id:
                raise ValueError(
                    f"Entry {entry_id!r} action Element UID is inconsistent")
            entry_record = entry_occurrences.get((entry_id, state_id))
            if entry_record is None or (
                entry_record["region_ref"] != region_ref
                or entry_record["target"].casefold() != target.casefold()
            ):
                raise ValueError(
                    f"Entry {entry_id!r} action has no matching occurrence")
            continue
        if not element_uid.startswith(AUTONOMOUS_ELEMENT_UID_PREFIX):
            raise ValueError(
                f"ordinary action Element has invalid UID: {element_uid!r}")
        key = (state_id, element_uid)
        raw_action = attempt.get("action") or edge.get("action") or {}
        action_type = (
            _text(raw_action.get("action_type")).casefold()
            if isinstance(raw_action, dict) else ""
        )
        is_text_input = action_type in {"input_text", "type", "typing"}
        record = {
            "uid": element_uid,
            "target": target,
            "control_type": "input" if is_text_input else "control",
            "category": "input" if is_text_input else "shallow",
            "source": "autonomous_action_evidence",
            "state_id": state_id,
            "region_name": region["region_name"],
            "region_ref": region_ref,
        }
        previous = seen_action_elements.get(key)
        if previous is not None and previous != record:
            raise ValueError(
                f"conflicting occurrences for action Element {element_uid!r}")
        if previous is None:
            seen_action_elements[key] = record
            records.append(record)

    state_regions: Dict[str, List[Dict[str, Any]]] = {}
    for region in regions.values():
        for state_id in region["state_ids"]:
            state_regions.setdefault(state_id, [])
            if not any(
                    item["region_ref"] == region["region_ref"]
                    for item in state_regions[state_id]):
                state_regions[state_id].append(region)

    updates: Dict[str, Dict[str, Any]] = {}
    for state_id, formal_regions in state_regions.items():
        node = graph.graph.nodes[state_id]
        if _text(node.get("perception_mode")) not in {
                "autonomous_vlm", "luna_autonomous"}:
            raise ValueError(
                f"State {state_id!r} is not an autonomous VLM producer State")
        if node.get("elements") or node.get("semantic_blocks"):
            raise ValueError(
                f"State {state_id!r} already contains an element inventory")
        elements: List[Dict[str, Any]] = []
        blocks: List[Dict[str, Any]] = []
        next_id = 0

        block_by_ref: Dict[str, Dict[str, Any]] = {}
        for region in sorted(
                formal_regions,
                key=lambda item: (item["region_ref"], item["region_name"])):
            block = {
                "region_id": region["region_ref"],
                "role": region["region_name"],
                "element_ids": [],
                "element_names": [],
            }
            blocks.append(block)
            block_by_ref[region["region_ref"]] = block

        for record in sorted(
                (item for item in records
                 if item["state_id"] == state_id),
                key=lambda item: item["uid"]):
            element = {
                "id": next_id,
                "name": record["target"],
                "bbox_xywh": [0, 0, 1, 1],
                "center": [0, 0],
                "el_type": record["control_type"],
                "interactive": True,
                "category": record["category"],
                "source": record["source"],
                "uid": record["uid"],
                "region": record["region_name"],
                "region_id": record["region_ref"],
                "geometry_status": "semantic_only",
            }
            if record["source"] == "semantic_inventory":
                element.update({
                    "operation": record.get("operation") or record["target"],
                    "subject": record.get("subject") or record["region_name"],
                    "entry_status": record.get("entry_status") or "",
                    "exploration_policy": (
                        record.get("exploration_policy") or "explore"),
                })
            elements.append(element)
            block = block_by_ref[record["region_ref"]]
            block["element_ids"].append(next_id)
            block["element_names"].append(record["target"])
            next_id += 1
        updates[state_id] = {
            "elements": elements,
            "semantic_blocks": blocks,
        }

    for state_id, update in updates.items():
        node = graph.graph.nodes[state_id]
        node["elements"] = update["elements"]
        node["semantic_blocks"] = update["semantic_blocks"]
    return len({record["uid"] for record in records})


def _semantic_operation_catalog(graph: Any) -> List[Dict[str, Any]]:
    """Collect observed operation semantics without inventing action evidence."""
    state_graph = getattr(graph, "graph", None)
    nodes = getattr(state_graph, "nodes", {})
    grouped: Dict[str, Dict[str, Any]] = {}
    for state_id, raw_node in nodes.items():
        node = dict(raw_node or {})
        for element in node.get("elements") or []:
            if not isinstance(element, dict):
                continue
            uid = _text(element.get("uid"))
            if (
                not uid.startswith(AUTONOMOUS_ENTRY_UID_PREFIX)
                or _text(element.get("source")) != "semantic_inventory"
            ):
                continue
            status = _text(element.get("entry_status")) or "discovered"
            evidence_level = {
                "recorded": "observed_only",
                "verified": "action_verified",
                "inferred": "inferred",
            }.get(status, "pending")
            record = grouped.setdefault(uid, {
                "entry_id": uid[len(AUTONOMOUS_ENTRY_UID_PREFIX):],
                "operation": _text(element.get("operation"))
                or _text(element.get("name")),
                "subject": _text(element.get("subject"))
                or _text(element.get("region")),
                "target": _text(element.get("name")),
                "region_ref": _text(element.get("region_id")),
                "page_id": _text(node.get("page_id")),
                "exploration_policy": _text(
                    element.get("exploration_policy")) or "explore",
                "evidence_level": evidence_level,
                "state_ids": [],
            })
            if _text(state_id) not in record["state_ids"]:
                record["state_ids"].append(_text(state_id))
    return sorted(grouped.values(), key=lambda item: item["entry_id"])


def attach_source_region_refs(
    graph: Any, entries_snapshot: Any, regions_snapshot: Any,
) -> int:
    """Attach only formally matched Region refs, failing closed on conflicts."""
    entry_refs = _snapshot_mapping(entries_snapshot, regions_snapshot)
    pending = []
    for _edge, attempt in _attempts(graph):
        evidence = attempt.get("evidence") or {}
        if not isinstance(evidence, dict):
            continue
        formal_ref = entry_refs.get(_text(evidence.get("entry_id")), "")
        existing_ref = _text(evidence.get("source_region_ref"))
        if existing_ref and formal_ref and existing_ref != formal_ref:
            raise ValueError("attempt source_region_ref conflicts with formal Region snapshot")
        if not existing_ref and formal_ref:
            pending.append((attempt, copy.deepcopy(evidence), formal_ref))
    for attempt, evidence, formal_ref in pending:
        evidence["source_region_ref"] = formal_ref
        attempt["evidence"] = evidence
    return len(pending)

def induce_capability_graph(
    graph: Any,
    source_graph_digest: str = "",
    *,
    region_probe_source_ref: str = "",
) -> Dict[str, Any]:
    """Derive a read-only phase-1 capability graph from ActionAttempt evidence."""
    episodes = build_probe_episodes(graph)
    source_ref = _text(region_probe_source_ref)
    if source_ref:
        episodes = [
            episode for episode in episodes
            if not _text(episode.entry_surface.get("entry_id"))
            and _text(episode.entry_surface.get("region_ref")) == source_ref
        ]
    attempt_trace = _attempts(graph)
    groups: Dict[Tuple[str, str, Tuple[str, ...], Tuple[str, ...]], List[Tuple[ProbeEpisode, Dict[str, Any]]]] = {}
    for episode in episodes:
        if episode.outcome != "supported":
            continue
        for observation in episode.observations:
            if (observation.get("verdict") != "supported"
                    or observation.get("effect_kind") not in _BUSINESS_EFFECTS):
                continue
            capability_episode, capability_observation = (
                _observed_entry_prefix(
                    graph, attempt_trace, episode, observation))
            name = _text(capability_observation.get("capability_name"))
            if not name:
                continue
            key = (
                name.casefold(), capability_observation["effect_kind"],
                tuple(sorted(
                    (_text(item.get("scope", {}).get("region_ref")), _text(item.get("fact")))
                    for item in capability_observation["observed_changes"])),
                tuple(sorted((
                    capability_observation.get("parameter_bindings") or {}
                ).keys())),
            )
            groups.setdefault(key, []).append(
                (capability_episode, capability_observation))

    capabilities: List[Dict[str, Any]] = []
    relation_candidates: List[Dict[str, Any]] = []
    for _key, evidence in sorted(groups.items(), key=lambda item: item[0]):
        first_episode, first = evidence[0]
        recipes: Dict[str, List[Tuple[ProbeEpisode, Dict[str, Any]]]] = {}
        for item in evidence:
            recipe = _parameterized_recipe(item[0].recipe, item[1])
            recipes.setdefault(_stable(recipe), []).append(item)
        best_recipe, matching = max(recipes.items(), key=lambda item: (len(item[1]), item[0]))
        parsed_recipe = json.loads(best_recipe)
        recipe_parameter_keys = _recipe_parameter_keys(parsed_recipe)
        parameter_values: Dict[str, List[Any]] = {}
        parameter_confirmed: set[str] = set()
        for _episode, observation in matching:
            for key, value in (observation.get("parameter_bindings") or {}).items():
                parameter_values.setdefault(key, []).append(copy.deepcopy(value))
        for key, values in parameter_values.items():
            distinct = {_stable(value) for value in values}
            if len(distinct) >= 2 and key in recipe_parameter_keys:
                parameter_confirmed.add(key)
        predicates = {_stable(_predicate(observation, parameter_confirmed))
                      for _episode, observation in matching}
        deterministic = len(predicates) == 1 and bool(
            _predicate(first, parameter_confirmed)["all"])
        status = "discovered"
        if len(matching) >= 2:
            status = "executable"
        if len(matching) >= 2 and deterministic and (
                not parameter_values or len(parameter_confirmed) == len(parameter_values)):
            status = "effect_verified"
        entry_surfaces = []
        evidence_refs = []
        effect_refs = []
        seen_surfaces, seen_attempts, seen_effects = set(), set(), set()
        for episode, observation in matching:
            surface_key = _stable(episode.entry_surface)
            if surface_key not in seen_surfaces:
                entry_surfaces.append(copy.deepcopy(episode.entry_surface))
                seen_surfaces.add(surface_key)
            for attempt_ref in episode.attempts:
                attempt_key = _stable(attempt_ref)
                if attempt_key not in seen_attempts:
                    evidence_refs.append(copy.deepcopy(attempt_ref))
                    seen_attempts.add(attempt_key)
            effect_ref = observation["evidence_ref"]
            effect_key = _stable(effect_ref)
            if effect_key not in seen_effects:
                effect_refs.append(copy.deepcopy(effect_ref))
                seen_effects.add(effect_key)
        capability = {
            "capability_id": _capability_id(_text(first["capability_name"]), first),
            "name": _text(first["capability_name"]),
            "verification_level": status,
            "entry_surfaces": entry_surfaces,
            "execution_recipe": parsed_recipe,
            "preconditions": [],
            "effects": _effects(first, parameter_confirmed),
            "success_predicate": _predicate(first, parameter_confirmed),
            "predicate_description": _text(first.get("predicate_candidate")),
            "evidence_refs": evidence_refs,
            "effect_refs": effect_refs,
        }
        if parameter_confirmed:
            capability["parameters"] = [
                {"name": key, "domain": {"values": sorted(
                    {_stable(value): value for value in parameter_values[key]}.values(),
                    key=_stable)}}
                for key in sorted(parameter_confirmed)
            ]
            examples: Dict[str, Dict[str, Any]] = {}
            for _episode, observation in matching:
                bindings = observation.get("parameter_bindings") or {}
                if not parameter_confirmed.issubset(bindings):
                    continue
                example = {
                    key: copy.deepcopy(bindings[key])
                    for key in sorted(parameter_confirmed)
                }
                examples[_stable(example)] = example
            capability["parameter_examples"] = sorted(
                examples.values(), key=_stable)
        unconfirmed = {
            key: sorted({_stable(value): value for value in values}.values(), key=_stable)
            for key, values in parameter_values.items() if key not in parameter_confirmed
        }
        if unconfirmed:
            capability["parameter_candidates"] = unconfirmed
        capabilities.append(capability)
        relation_candidates.append({
            "capability": capability,
            "effect_kind": first.get("effect_kind"),
            "matching": matching,
        })
    app_id = _text(getattr(graph, "app_name", ""))
    if not app_id and isinstance(graph, dict):
        app_id = _text(graph.get("app_name"))
    return {
        "schema_version": CAPABILITY_GRAPH_SCHEMA,
        "app_id": app_id,
        "source_graph_digest": _text(source_graph_digest),
        "capabilities": capabilities,
        "operation_catalog": _semantic_operation_catalog(graph),
        "probe_episodes": [episode.to_dict() for episode in episodes],
        "relations": _cleanup_relations(graph, relation_candidates),
    }


def save_capability_graph(path: str, capability_graph: Dict[str, Any]) -> None:
    """Atomically save an already induced capability graph."""
    if capability_graph.get("schema_version") != CAPABILITY_GRAPH_SCHEMA:
        raise ValueError("unsupported capability graph schema")
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(capability_graph, stream, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(temporary, path)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def load_capability_graph(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("schema_version") != CAPABILITY_GRAPH_SCHEMA:
        raise ValueError("unsupported capability graph schema")
    return data


def compile_collection_bundle(
    graph_path: str,
    capability_graph_path: str,
    *,
    annotated_graph_path: str = "",
    entries_path: str = "",
    regions_path: str = "",
) -> Dict[str, Any]:
    """Compile saved Qwen traversal evidence into the formal collection bundle."""
    from gui_rewalk.src.core.graph.state_graph import StateGraph

    graph_path = os.path.abspath(graph_path)
    capability_graph_path = os.path.abspath(capability_graph_path)
    annotated_graph_path = (
        os.path.abspath(annotated_graph_path)
        if annotated_graph_path else "")
    entries_path = os.path.abspath(entries_path) if entries_path else ""
    regions_path = os.path.abspath(regions_path) if regions_path else ""

    if bool(entries_path) != bool(regions_path):
        raise ValueError(
            "entries_path and regions_path must be supplied together")
    if entries_path and not annotated_graph_path:
        raise ValueError(
            "annotated_graph_path is required for autonomous inventory")
    if annotated_graph_path and not entries_path:
        raise ValueError(
            "annotated_graph_path requires autonomous entries and regions")

    inputs = {
        path for path in (graph_path, entries_path, regions_path) if path
    }
    outputs = {
        path for path in (capability_graph_path, annotated_graph_path) if path
    }
    if len(outputs) != (2 if annotated_graph_path else 1):
        raise ValueError(
            "annotated graph and capability graph outputs must differ")
    if inputs & outputs:
        raise ValueError("bundle outputs must not overwrite compiler inputs")

    graph = StateGraph.load(graph_path)
    projected_elements = 0
    source_path = graph_path
    if entries_path:
        with open(entries_path, "r", encoding="utf-8") as stream:
            entries_snapshot = json.load(stream)
        with open(regions_path, "r", encoding="utf-8") as stream:
            regions_snapshot = json.load(stream)
        attach_source_region_refs(
            graph, entries_snapshot, regions_snapshot)
        projected_elements = project_autonomous_inventory(
            graph, entries_snapshot, regions_snapshot)
        graph.save(annotated_graph_path)
        # Compile from the serialized graph that collection will actually load.
        graph = StateGraph.load(annotated_graph_path)
        source_path = annotated_graph_path

    with open(source_path, "rb") as stream:
        digest = hashlib.sha256(stream.read()).hexdigest()
    capability_graph = induce_capability_graph(
        graph, source_graph_digest=digest)
    save_capability_graph(capability_graph_path, capability_graph)
    return {
        "annotated_graph_path": annotated_graph_path or graph_path,
        "capability_graph_path": capability_graph_path,
        "source_graph_digest": digest,
        "projected_elements": projected_elements,
        "capabilities": len(capability_graph.get("capabilities") or []),
        "relations": len(capability_graph.get("relations") or []),
    }
