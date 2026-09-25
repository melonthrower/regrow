from __future__ import annotations

import json
from pathlib import Path

from gui_rewalk.env.local_html_gui_gen_env import LocalHTMLGUIGenEnv
from tools.validate_quick_traversal_run import validate_run


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "traversal_test_app"


def _truth():
    return (
        json.loads((FIXTURE / "oracle.json").read_text(encoding="utf-8")),
        json.loads((FIXTURE / "edge_cases.json").read_text(encoding="utf-8")),
    )


def _attempt(event, source, target, *, entry_id="", action_type="CLICK"):
    return {
        "source_page_id": source,
        "target_page_id": target,
        "attempts": [{
            "action_index": event,
            "action": {"action_type": action_type},
            "landing_verified": True,
            "committed": True,
            "evidence": {"entry_id": entry_id},
        }],
    }


def _audit(event, phase, page, *, label="", action_id="", y=0,
           regions=None, active_entry="", visits=None, control_id=""):
    return {
        "phase": phase,
        "event_index": event,
        "page": page,
        "action_label": label,
        "action_id": action_id,
        "control_id": control_id,
        "active_entry": active_entry,
        "visits": list(visits or []),
        "scroll": {"y": y, "max_y": 600, "top": y == 0, "bottom": y == 600},
        "scroll_regions": dict(regions or {}),
    }


def _entry(entry_id, page, region, target, status="verified", representative=""):
    return {
        "entry_id": entry_id,
        "page_name": page,
        "region_name": region,
        "target": target,
        "status": status,
        "representative_entry_id": representative,
    }


def _artifacts(trace, graph, *, entries, page_details=None, regions=None):
    return {
        "trace": trace,
        "graph": {"action_edges": graph},
        "natural_map": {"page_details": list(page_details or [])},
        "regions": {"pages": dict(regions or {})},
        "entries": {"entries": entries},
    }


def _validate(fixture, artifacts):
    oracle, cases = _truth()
    return validate_run(
        fixture, oracle, cases, artifacts["trace"], artifacts["graph"],
        artifacts["natural_map"], artifacts["regions"], artifacts["entries"],
    )


def test_quick_fixture_audit_reads_fixture_snapshot_and_scroll_containers():
    env = LocalHTMLGUIGenEnv(
        str(FIXTURE / "scroll.html"), screen_size=(1365, 900),
        start_hash="#/inbox",
    )
    try:
        env.reset()
        audit = env.autonomous_fixture_audit()
    finally:
        env.close()

    assert audit["page"] == "scroll.workspace"
    assert set(audit["scroll_regions"]) == {
        "scroll.today", "scroll.projects", "scroll.files",
    }
    assert audit["scroll"]["y"] == 0


def test_scroll_acceptance_requires_three_bound_entries_and_independent_scrolls():
    oracle, cases = _truth()
    scenario = oracle["scenarios"][0]
    selected = [item for item in cases["cases"] if item["file"] == "scroll.html"]
    region_state = {
        item["id"]: {"y": 0, "max_y": 100 * item["depth_rank"],
                     "top": True, "bottom": False}
        for item in scenario["regions"]
    }
    audit = [_audit(None, "initial", scenario["page_id"], regions=region_state)]
    graph = []
    entries = []
    event = 0
    for region, case in zip(scenario["regions"], selected):
        event += 1
        after_regions = {key: dict(value) for key, value in region_state.items()}
        after_regions[region["id"]].update(
            y=after_regions[region["id"]]["max_y"], top=False, bottom=True)
        audit.extend([
            _audit(event, "before", scenario["page_id"], regions=region_state),
            _audit(event, "after", scenario["page_id"], regions=after_regions),
        ])
        graph.append(_attempt(event, "p1", "p1", action_type="SCROLL"))
        region_state = after_regions
        event += 1
        entry_id = f"ae{event}"
        audit.extend([
            _audit(event, "before", scenario["page_id"], label=case["target"],
                   action_id=region["entry_id"], regions=region_state),
            _audit(event, "after", scenario["page_id"], regions=region_state,
                   active_entry=region["entry_id"]),
        ])
        graph.append(_attempt(event, "p1", "p1", entry_id=entry_id))
        entries.append(_entry(
            entry_id, "Wednesday plan", region["id"], case["target"]))
    audit.append(_audit(None, "final", scenario["page_id"], regions=region_state))
    artifacts = _artifacts(
        {"stop_reason": "model_finished", "fixture_audit": audit}, graph,
        entries=entries,
    )

    assert _validate("scroll", artifacts)["status"] == "certified"
    artifacts["entries"]["entries"][0]["status"] = "discovered"
    report = _validate("scroll", artifacts)
    assert report["checks"]["all_three_entries_verified"] is False


def test_loop_acceptance_requires_ordered_cycle_scroll_and_identity_reuse():
    oracle, manifest = _truth()
    scenario = oracle["scenarios"][1]
    cases = [item for item in manifest["cases"] if item["file"] == "loop.html"]
    page_ids = scenario["page_chain"]
    internal = {
        page_id: f"p{index}" for index, page_id in enumerate(dict.fromkeys(page_ids), 1)
    }
    audit = [_audit(None, "initial", page_ids[0], visits=[page_ids[0]])]
    graph = []
    entries = []
    visits = [page_ids[0]]
    event = 0
    for index, case in enumerate(cases):
        source, target = page_ids[index], page_ids[index + 1]
        if index == 1:
            event += 1
            audit.extend([
                _audit(event, "before", source, y=0, visits=visits),
                _audit(event, "after", source, y=600, visits=visits),
            ])
            graph.append(_attempt(
                event, internal[source], internal[source], action_type="SCROLL"))
        event += 1
        entry_id = f"ae{event}"
        audit.extend([
            _audit(event, "before", source, label=case["target"],
                   action_id=(scenario["scroll_required_entry"] if index == 1
                              else f"loop.action.{index}"),
                   y=600 if index == 1 else 0, visits=visits),
            _audit(event, "after", target, visits=[*visits, target]),
        ])
        visits.append(target)
        graph.append(_attempt(
            event, internal[source], internal[target], entry_id=entry_id))
        entries.append(_entry(entry_id, case["source_page"], "content", case["target"]))
    audit.append(_audit(None, "final", page_ids[-1], visits=visits))
    artifacts = _artifacts(
        {"stop_reason": "model_finished", "fixture_audit": audit}, graph,
        entries=entries,
    )

    assert _validate("loop", artifacts)["status"] == "certified"
    artifacts["graph"]["action_edges"][-1]["target_page_id"] = "duplicate-root"
    report = _validate("loop", artifacts)
    assert report["checks"]["page_identity_reused_on_return"] is False


def test_back_acceptance_requires_each_direct_edge_return_and_scroll_restore():
    oracle, manifest = _truth()
    scenario = oracle["scenarios"][2]
    cases = [item for item in manifest["cases"] if item["file"] == "back.html"]
    title_pages = {item["title"]: item["page_id"] for item in scenario["pages"]}
    internal = {page: f"p{index}" for index, page in enumerate(title_pages.values(), 1)}
    audit = [_audit(None, "initial", next(iter(title_pages.values())))]
    graph = []
    entries = []
    event = 0
    for case in cases:
        source = title_pages[case["source_page"]]
        target = title_pages[case["expected_destination"]]
        event += 1
        entry_id = f"ae{event}"
        audit.extend([
            _audit(event, "before", source, label=case["target"],
                   action_id=case["id"], y=600),
            _audit(event, "after", target, y=0),
        ])
        graph.append(_attempt(
            event, internal[source], internal[target], entry_id=entry_id))
        entries.append(_entry(entry_id, case["source_page"], "entries", case["target"]))
        event += 1
        audit.extend([
            _audit(event, "before", target, label="← Back", control_id="back"),
            _audit(event, "after", source, y=600),
        ])
        graph.append(_attempt(event, internal[target], internal[source]))
    audit.append(_audit(None, "final", next(iter(title_pages.values()))))
    artifacts = _artifacts(
        {"stop_reason": "model_finished", "fixture_audit": audit}, graph,
        entries=entries,
    )

    assert _validate("back", artifacts)["status"] == "certified"
    # Break the first return position without changing the edge itself.
    first_return_after = next(
        row for row in audit
        if row.get("phase") == "after" and row.get("event_index") == 2)
    first_return_after["scroll"]["y"] = 0
    report = _validate("back", artifacts)
    assert report["checks"]["every_edge_returns_to_actual_source"] is True
    assert report["checks"]["source_scroll_position_restored"] is False


def test_region_merge_acceptance_requires_four_explicit_groups_across_seven_occurrences():
    oracle, _manifest = _truth()
    scenario = oracle["scenarios"][3]
    pages = {item["key"]: item for item in scenario["pages"]}
    internal = {key: f"p{key}" for key in pages}
    natural = {key: item["title"] for key, item in pages.items()}
    audit = [_audit(None, "initial", pages["A"]["page_id"])]
    graph = []
    entries = []
    region_pages = {item["title"].casefold(): {"regions": []} for item in pages.values()}
    event = 0
    for index, truth in enumerate(scenario["regions"], 1):
        representative = f"ae{index}.1"
        for occurrence_index, occurrence in enumerate(truth["occurrences"], 1):
            page_key = occurrence["page"]
            entry_id = f"ae{index}.{occurrence_index}"
            entries.append(_entry(
                entry_id, natural[page_key], truth["title"], truth["entry"],
                status="verified" if occurrence_index == 1 else "inferred",
                representative="" if occurrence_index == 1 else representative,
            ))
            region_pages[natural[page_key].casefold()]["regions"].append({
                "name": truth["title"], "coverage_complete": True,
                "region_ref": f"rg{index}",
            })
        first_page = truth["occurrences"][0]["page"]
        destination = next(
            item for item in scenario["pages"]
            if item["route"] == truth["destination"])
        event += 1
        audit.extend([
            _audit(event, "before", pages[first_page]["page_id"],
                   label=truth["entry"], action_id=truth["entry_id"]),
            _audit(event, "after", destination["page_id"]),
        ])
        graph.append(_attempt(
            event, internal[first_page], internal[destination["key"]],
            entry_id=representative,
        ))
    audit.append(_audit(None, "final", pages["C"]["page_id"]))
    page_details = [
        {"name": natural[key], "internal_page_id": internal[key]}
        for key in pages
    ]
    artifacts = _artifacts(
        {"stop_reason": "model_finished", "fixture_audit": audit}, graph,
        entries=entries, page_details=page_details, regions=region_pages,
    )

    assert _validate("region_merge", artifacts)["status"] == "certified"
    artifacts["regions"]["pages"][natural["B"].casefold()]["regions"][0][
        "region_ref"] = "rg-unmerged"
    region_report = _validate("region_merge", artifacts)
    assert region_report["checks"]["four_explicit_region_groups"] is False
    artifacts["regions"]["pages"][natural["B"].casefold()]["regions"][0][
        "region_ref"] = "rg1"
    artifacts["entries"]["entries"][1]["representative_entry_id"] = ""
    report = _validate("region_merge", artifacts)
    assert report["checks"]["four_explicit_entry_equivalence_groups"] is False
