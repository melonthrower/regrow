"""Post-run acceptance for the four quick autonomous traversal fixtures.

The validator reads fixture truth only after the visual run has stopped.  DOM
IDs and oracle labels are never exposed to the traversal Agent.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence


FIXTURE_SCENARIO = {
    "scroll": "multi_region_scroll",
    "loop": "multi_hop_regression",
    "back": "history_return",
    "region_merge": "shared_region_reposition",
}


def _norm(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _semantic_norm(value: Any) -> str:
    words = _norm(value).split()
    while words and words[-1] in {
        "area", "button", "card", "control", "link", "panel", "region",
        "section",
    }:
        words.pop()
    return " ".join(words)


def _read(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _scenario(oracle: Mapping[str, Any], fixture: str) -> Dict[str, Any]:
    scenario_id = FIXTURE_SCENARIO[fixture]
    return next(
        dict(item) for item in oracle.get("scenarios") or []
        if item.get("id") == scenario_id
    )


def _title_to_page_id(scenario: Mapping[str, Any]) -> Dict[str, str]:
    if scenario.get("id") == "multi_region_scroll":
        return {_norm("Wednesday plan"): str(scenario["page_id"])}
    if scenario.get("id") == "multi_hop_regression":
        return {
            _norm(title): str(page_id)
            for title, page_id in zip(
                scenario.get("page_titles") or [],
                scenario.get("page_chain") or [],
            )
        }
    return {
        _norm(item.get("title")): str(item.get("page_id"))
        for item in scenario.get("pages") or []
    }


def _attempts_by_event(graph: Mapping[str, Any]) -> Dict[int, Dict[str, Any]]:
    attempts: Dict[int, Dict[str, Any]] = {}
    for edge in graph.get("action_edges") or []:
        for raw in edge.get("attempts") or []:
            event = raw.get("action_index")
            if not isinstance(event, int):
                continue
            attempts[event] = {
                **dict(raw),
                "source_page_id": str(edge.get("source_page_id") or ""),
                "target_page_id": str(edge.get("target_page_id") or ""),
            }
    return attempts


def _audit_pairs(trace: Mapping[str, Any]) -> List[Dict[str, Any]]:
    grouped: Dict[int, Dict[str, Any]] = defaultdict(dict)
    for row in trace.get("fixture_audit") or []:
        event = row.get("event_index")
        phase = str(row.get("phase") or "")
        if isinstance(event, int) and phase in {"before", "after"}:
            grouped[event][phase] = dict(row)
    return [
        {"event": event, **grouped[event]}
        for event in sorted(grouped)
        if "before" in grouped[event] and "after" in grouped[event]
    ]


def _verified(attempt: Mapping[str, Any]) -> bool:
    return (
        attempt.get("landing_verified") is True
        and attempt.get("committed") is True
    )


def _cases_for(
    edge_manifest: Mapping[str, Any], scenario: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    filename = str(scenario.get("file") or "")
    return [
        dict(item) for item in edge_manifest.get("cases") or []
        if item.get("file") == filename
    ]


def _case_events(
    case: Mapping[str, Any], pairs: Sequence[Mapping[str, Any]],
    attempts: Mapping[int, Mapping[str, Any]],
    title_pages: Mapping[str, str],
) -> List[int]:
    source = title_pages.get(_norm(case.get("source_page")), "")
    destination = title_pages.get(_norm(case.get("expected_destination")), "")
    events: List[int] = []
    for pair in pairs:
        before, after = pair["before"], pair["after"]
        event = int(pair["event"])
        if not _verified(attempts.get(event) or {}):
            continue
        if str(before.get("page") or "") != source:
            continue
        if _norm(before.get("action_label")) != _norm(case.get("target")):
            continue
        if str(after.get("page") or "") != destination:
            continue
        events.append(event)
    return events


def _entry_verified_for_event(
    event: int, attempts: Mapping[int, Mapping[str, Any]],
    entries: Mapping[str, Any],
) -> bool:
    attempt = attempts.get(event) or {}
    entry_id = str((attempt.get("evidence") or {}).get("entry_id") or "")
    records = {
        str(item.get("entry_id") or ""): item
        for item in entries.get("entries") or []
    }
    return bool(entry_id and (records.get(entry_id) or {}).get("status") == "verified")


def _identity_mapping(
    pairs: Sequence[Mapping[str, Any]],
    attempts: Mapping[int, Mapping[str, Any]],
) -> Dict[str, set[str]]:
    result: Dict[str, set[str]] = defaultdict(set)
    for pair in pairs:
        attempt = attempts.get(int(pair["event"])) or {}
        source = str(pair["before"].get("page") or "")
        target = str(pair["after"].get("page") or "")
        if source and attempt.get("source_page_id"):
            result[source].add(str(attempt["source_page_id"]))
        if target and attempt.get("target_page_id"):
            result[target].add(str(attempt["target_page_id"]))
    return dict(result)


def _identity_check(
    expected_pages: Iterable[str], mapping: Mapping[str, set[str]],
) -> bool:
    page_ids = [str(page) for page in expected_pages]
    groups = [mapping.get(page) or set() for page in page_ids]
    return (
        all(len(group) == 1 for group in groups)
        and len({next(iter(group)) for group in groups}) == len(page_ids)
    )


def _contains_subsequence(values: Sequence[Any], expected: Sequence[Any]) -> bool:
    index = 0
    for value in values:
        if index < len(expected) and value == expected[index]:
            index += 1
    return index == len(expected)


def _scroll_report(
    scenario: Mapping[str, Any], cases: Sequence[Mapping[str, Any]],
    trace: Mapping[str, Any], pairs: Sequence[Mapping[str, Any]],
    attempts: Mapping[int, Mapping[str, Any]], entries: Mapping[str, Any],
) -> Dict[str, Any]:
    title_pages = _title_to_page_id(scenario)
    case_hits = {
        str(case["id"]): _case_events(case, pairs, attempts, title_pages)
        for case in cases
    }
    independent: Dict[str, bool] = {}
    reached_hidden_depth: Dict[str, bool] = {}
    for region, case in zip(scenario.get("regions") or [], cases):
        region_id = str(region["id"])
        independent[region_id] = False
        reached_hidden_depth[region_id] = False
        for pair in pairs:
            event = int(pair["event"])
            attempt = attempts.get(event) or {}
            action_type = _norm((attempt.get("action") or {}).get("action_type"))
            before_regions = pair["before"].get("scroll_regions") or {}
            after_regions = pair["after"].get("scroll_regions") or {}
            changed = {
                key for key in set(before_regions) | set(after_regions)
                if (before_regions.get(key) or {}).get("y")
                != (after_regions.get(key) or {}).get("y")
            }
            if (
                action_type == "scroll"
                and changed == {region_id}
                and (pair["before"].get("scroll") or {}).get("y")
                == (pair["after"].get("scroll") or {}).get("y")
            ):
                independent[region_id] = True
        for pair in pairs:
            if _norm(pair["before"].get("action_label")) != _norm(
                case.get("target")
            ):
                continue
            state = (pair["before"].get("scroll_regions") or {}).get(region_id) or {}
            if float(state.get("y") or 0) > 0:
                reached_hidden_depth[region_id] = True
    all_events = [event for values in case_hits.values() for event in values]
    checks = {
        "model_finished": trace.get("stop_reason") == "model_finished",
        "all_three_entries_verified": (
            all(case_hits.values())
            and all(_entry_verified_for_event(event, attempts, entries)
                    for event in all_events)
        ),
        "three_independent_scroll_containers": all(independent.values()),
        "hidden_entry_depth_reached": all(reached_hidden_depth.values()),
    }
    return {
        "checks": checks,
        "observed": {
            "target_edges": {key: bool(value) for key, value in case_hits.items()},
            "independent_scroll": independent,
            "entry_reached_after_scroll": reached_hidden_depth,
        },
    }


def _loop_report(
    scenario: Mapping[str, Any], cases: Sequence[Mapping[str, Any]],
    trace: Mapping[str, Any], pairs: Sequence[Mapping[str, Any]],
    attempts: Mapping[int, Mapping[str, Any]], entries: Mapping[str, Any],
) -> Dict[str, Any]:
    title_pages = _title_to_page_id(scenario)
    case_hits = {
        str(case["id"]): _case_events(case, pairs, attempts, title_pages)
        for case in cases
    }
    final = next((row for row in reversed(trace.get("fixture_audit") or [])
                  if row.get("phase") == "final"), {})
    visits = list(final.get("visits") or [])
    page_chain = list(scenario.get("page_chain") or [])
    mapping = _identity_mapping(pairs, attempts)
    scroll_entry = str(scenario.get("scroll_required_entry") or "")
    scrolled_target = any(
        pair["before"].get("action_id") == scroll_entry
        and (pair["before"].get("scroll") or {}).get("y", 0) > 0
        for pair in pairs
    )
    all_events = [event for values in case_hits.values() for event in values]
    checks = {
        "model_finished": trace.get("stop_reason") == "model_finished",
        "four_edges_verified": (
            all(case_hits.values())
            and all(_entry_verified_for_event(event, attempts, entries)
                    for event in all_events)
        ),
        "ordered_loop_observed": _contains_subsequence(visits, page_chain),
        "scroll_required_entry_reached": scrolled_target,
        "page_identity_reused_on_return": _identity_check(
            set(page_chain), mapping),
    }
    return {
        "checks": checks,
        "observed": {
            "target_edges": {key: bool(value) for key, value in case_hits.items()},
            "visits": visits,
            "fixture_to_internal_pages": {
                key: sorted(value) for key, value in mapping.items()
            },
        },
    }


def _is_back_pair(
    pair: Mapping[str, Any], attempt: Mapping[str, Any],
) -> bool:
    label = _norm(pair["before"].get("action_label"))
    control_id = _norm(pair["before"].get("control_id"))
    action_type = _norm((attempt.get("action") or {}).get("action_type"))
    return control_id == "back" or label == "back" or action_type == "back"


def _back_report(
    scenario: Mapping[str, Any], cases: Sequence[Mapping[str, Any]],
    trace: Mapping[str, Any], pairs: Sequence[Mapping[str, Any]],
    attempts: Mapping[int, Mapping[str, Any]], entries: Mapping[str, Any],
) -> Dict[str, Any]:
    title_pages = _title_to_page_id(scenario)
    pair_by_event = {int(pair["event"]): pair for pair in pairs}
    case_hits = {
        str(case["id"]): _case_events(case, pairs, attempts, title_pages)
        for case in cases
    }
    all_case_events = sorted(event for values in case_hits.values() for event in values)
    source_returns: Dict[str, bool] = {}
    scroll_restores: Dict[str, bool] = {}
    for case in cases:
        case_id = str(case["id"])
        source = title_pages[_norm(case["source_page"])]
        destination = title_pages[_norm(case["expected_destination"])]
        source_returns[case_id] = False
        scroll_restores[case_id] = False
        for click_event in case_hits[case_id]:
            click_pair = pair_by_event[click_event]
            next_case = next(
                (event for event in all_case_events if event > click_event),
                10**12,
            )
            source_y = (click_pair["before"].get("scroll") or {}).get("y")
            if not isinstance(source_y, (int, float)) or source_y <= 0:
                continue
            for pair in pairs:
                event = int(pair["event"])
                if not click_event < event < next_case:
                    continue
                attempt = attempts.get(event) or {}
                after_y = (pair["after"].get("scroll") or {}).get("y")
                if (
                    _verified(attempt)
                    and _is_back_pair(pair, attempt)
                    and pair["before"].get("page") == destination
                    and pair["after"].get("page") == source
                ):
                    source_returns[case_id] = True
                    scroll_restores[case_id] = (
                        isinstance(after_y, (int, float))
                        and abs(after_y - source_y) <= 2
                    )
                    break
            if source_returns[case_id]:
                break
    all_events = [event for values in case_hits.values() for event in values]
    checks = {
        "model_finished": trace.get("stop_reason") == "model_finished",
        "six_direct_edges_verified": (
            all(case_hits.values())
            and all(_entry_verified_for_event(event, attempts, entries)
                    for event in all_events)
        ),
        "every_edge_returns_to_actual_source": all(source_returns.values()),
        "source_scroll_position_restored": all(scroll_restores.values()),
    }
    return {
        "checks": checks,
        "observed": {
            "target_edges": {key: bool(value) for key, value in case_hits.items()},
            "return_contract": {
                case_id: {
                    "source_return": source_returns[case_id],
                    "scroll_restored": scroll_restores[case_id],
                }
                for case_id in source_returns
            },
        },
    }


def _canonical_entry(entry_id: str, records: Mapping[str, Mapping[str, Any]]) -> str:
    seen: set[str] = set()
    current = entry_id
    while current and current not in seen:
        seen.add(current)
        parent = str((records.get(current) or {}).get("representative_entry_id") or "")
        if not parent:
            return current
        current = parent
    return current


def _region_merge_report(
    scenario: Mapping[str, Any], cases: Sequence[Mapping[str, Any]],
    trace: Mapping[str, Any], pairs: Sequence[Mapping[str, Any]],
    attempts: Mapping[int, Mapping[str, Any]], entries: Mapping[str, Any],
    regions: Mapping[str, Any], natural_map: Mapping[str, Any],
) -> Dict[str, Any]:
    title_pages = _title_to_page_id(scenario)
    mapping = _identity_mapping(pairs, attempts)
    internal_to_fixture = {
        next(iter(internal)): fixture_page
        for fixture_page, internal in mapping.items()
        if len(internal) == 1
    }
    details = natural_map.get("page_details") or []
    page_name_to_fixture = {
        _norm(detail.get("name")): internal_to_fixture.get(
            str(detail.get("internal_page_id") or ""), "")
        for detail in details
    }
    page_key_to_id = {
        str(item["key"]): str(item["page_id"])
        for item in scenario.get("pages") or []
    }
    records = {
        str(item.get("entry_id") or ""): dict(item)
        for item in entries.get("entries") or []
    }
    region_pages = regions.get("pages") or {}
    ledger_regions_by_fixture: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for natural_page, page_state in region_pages.items():
        fixture_page = page_name_to_fixture.get(_norm(natural_page), "")
        ledger_regions_by_fixture[fixture_page].extend(
            dict(item) for item in page_state.get("regions") or [])

    matched_entries: Dict[str, List[str]] = {}
    matched_regions: Dict[str, List[str]] = {}
    matched_region_refs: Dict[str, List[str]] = {}
    group_ok: Dict[str, bool] = {}
    region_group_ok: Dict[str, bool] = {}
    behavior_ok: Dict[str, bool] = {}
    for truth in scenario.get("regions") or []:
        stable_id = str(truth["stable_id"])
        entry_ids: List[str] = []
        region_hits: List[str] = []
        region_refs: List[str] = []
        for occurrence in truth.get("occurrences") or []:
            fixture_page = page_key_to_id[str(occurrence["page"])]
            entry = next((
                item for item in records.values()
                if page_name_to_fixture.get(_norm(item.get("page_name")), "")
                == fixture_page
                and _semantic_norm(item.get("region_name"))
                == _semantic_norm(truth.get("title"))
                and _semantic_norm(item.get("target"))
                == _semantic_norm(truth.get("entry"))
            ), None)
            if entry:
                entry_ids.append(str(entry["entry_id"]))
            matched_region = next((
                item
                for item in ledger_regions_by_fixture.get(fixture_page) or []
                if _semantic_norm(item.get("name"))
                == _semantic_norm(truth.get("title"))
            ), None)
            if matched_region:
                region_hits.append(fixture_page)
                region_ref = str(matched_region.get("region_ref") or "")
                if region_ref:
                    region_refs.append(region_ref)
        matched_entries[stable_id] = entry_ids
        matched_regions[stable_id] = region_hits
        matched_region_refs[stable_id] = region_refs
        expected_count = len(truth.get("occurrences") or [])
        region_group_ok[stable_id] = (
            len(region_refs) == expected_count
            and len(set(region_refs)) == 1
        )
        canonical = {_canonical_entry(entry_id, records) for entry_id in entry_ids}
        statuses = {(records.get(entry_id) or {}).get("status") for entry_id in entry_ids}
        group_ok[stable_id] = (
            len(entry_ids) == expected_count
            and len(canonical) == 1
            and statuses <= {"verified", "inferred"}
            and "verified" in statuses
        )
        destination_route = str(truth.get("destination") or "")
        destination = next(
            str(item["page_id"]) for item in scenario.get("pages") or []
            if str(item.get("route")) == destination_route
        )
        source_pages = {
            page_key_to_id[str(item["page"])]
            for item in truth.get("occurrences") or []
        }
        behavior_ok[stable_id] = any(
            _verified(attempts.get(int(pair["event"])) or {})
            and pair["before"].get("action_id") == truth.get("entry_id")
            and pair["before"].get("page") in source_pages
            and pair["after"].get("page") == destination
            for pair in pairs
        )
    canonical_groups = {
        _canonical_entry(entry_id, records)
        for values in matched_entries.values() for entry_id in values
    }
    explicit_region_groups = {
        refs[0] for refs in matched_region_refs.values() if refs
    }
    occurrence_count = sum(len(values) for values in matched_entries.values())
    region_occurrence_count = sum(len(values) for values in matched_regions.values())
    expected_pages = {str(item["page_id"]) for item in scenario.get("pages") or []}
    contract = scenario.get("contract") or {}
    checks = {
        "model_finished": trace.get("stop_reason") == "model_finished",
        "three_pages_have_distinct_identity": _identity_check(
            expected_pages, mapping),
        "seven_region_occurrences_registered": (
            region_occurrence_count
            == int(contract.get("expected_region_occurrence_count") or 0)
        ),
        "four_explicit_region_groups": (
            len(explicit_region_groups)
            == int(contract.get("expected_stable_region_count") or 0)
            and all(region_group_ok.values())
        ),
        "four_explicit_entry_equivalence_groups": (
            len(canonical_groups)
            == int(contract.get("expected_stable_region_count") or 0)
            and all(group_ok.values())
        ),
        "one_verified_action_per_stable_region": all(behavior_ok.values()),
        "seven_entry_occurrences_accounted_for": (
            occurrence_count
            == int(contract.get("expected_region_occurrence_count") or 0)
        ),
    }
    return {
        "checks": checks,
        "observed": {
            "entry_occurrences": occurrence_count,
            "region_occurrences": region_occurrence_count,
            "canonical_region_groups": len(canonical_groups),
            "explicit_region_groups": len(explicit_region_groups),
            "region_merge_representation": (
                "explicit_agent_region_ref_plus_task_local_entry_reuse"
            ),
            "region_groups": region_group_ok,
            "groups": group_ok,
            "verified_behaviors": behavior_ok,
            "fixture_to_internal_pages": {
                key: sorted(value) for key, value in mapping.items()
            },
        },
    }


def validate_run(
    fixture: str, oracle: Mapping[str, Any],
    edge_manifest: Mapping[str, Any], trace: Mapping[str, Any],
    graph: Mapping[str, Any], natural_map: Mapping[str, Any],
    regions: Mapping[str, Any], entries: Mapping[str, Any],
) -> Dict[str, Any]:
    scenario = _scenario(oracle, fixture)
    cases = _cases_for(edge_manifest, scenario)
    pairs = _audit_pairs(trace)
    attempts = _attempts_by_event(graph)
    if fixture == "scroll":
        body = _scroll_report(scenario, cases, trace, pairs, attempts, entries)
    elif fixture == "loop":
        body = _loop_report(scenario, cases, trace, pairs, attempts, entries)
    elif fixture == "back":
        body = _back_report(scenario, cases, trace, pairs, attempts, entries)
    else:
        body = _region_merge_report(
            scenario, cases, trace, pairs, attempts, entries,
            regions, natural_map,
        )
    checks = body["checks"]
    return {
        "schema": "gui_rewalk.quick_traversal_acceptance.v1",
        "fixture": fixture,
        "status": "certified" if checks and all(checks.values()) else "incomplete",
        **body,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", choices=sorted(FIXTURE_SCENARIO))
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--edge-cases", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    report = validate_run(
        args.fixture,
        _read(args.oracle),
        _read(args.edge_cases),
        _read(run_dir / "autonomous_trace.json"),
        _read(run_dir / "graph.json"),
        _read(run_dir / "autonomous_natural_map.json"),
        _read(run_dir / "autonomous_regions.json"),
        _read(run_dir / "autonomous_entries.json"),
    )
    output = args.output or run_dir / "quick_acceptance.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "certified" else 3


if __name__ == "__main__":
    raise SystemExit(main())
