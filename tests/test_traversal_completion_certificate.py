"""Offline contracts for the fail-closed traversal completion certificate."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui_rewalk.src.core.graph.traversal_completion import (  # noqa: E402
    CERTIFICATE_SCHEMA,
    _element_id,
    _semantic_element_match,
    evaluate_traversal_completion,
)


def test_numeric_zero_is_a_valid_control_identity() -> None:
    assert _element_id({"id": 0, "name": "More options"}) == "0"
    assert _semantic_element_match(
        {"element_id": "0", "element_label": "More options"},
        {"id": 0, "name": "More options"})
    assert _semantic_element_match(
        {"element_id": 0, "element_label": "Back", "region": "top_app_bar"},
        {"id": 0, "name": "Back", "region_id": "r1",
         "region": "top_app_bar"})


def _node(
    state_id: str,
    page_id: str,
    variant_id: str,
    elements: list[dict],
    visible_capabilities: list[str],
    path: list[dict],
) -> dict:
    return {
        "state_id": state_id,
        "state_type": "visual",
        "page_id": page_id,
        "variant_id": variant_id,
        "page_identity_version": "semantic_page_variant_v1",
        "page_name": page_id,
        "variant_signature": "{}",
        "observed_facts": {},
        "elements": elements,
        "visible_capabilities": visible_capabilities,
        "action_path_from_root": path,
        "unreachable": False,
    }


def _attempt(
    index: int,
    source: str,
    target: str,
    *,
    evidence: dict | None = None,
) -> dict:
    return {
        "attempt_id": f"demo:{index}",
        "event_id": f"demo:{index}",
        "action_index": index,
        "source": source,
        "target": target,
        "outcome": "transitioned_consistent",
        "committed": True,
        "landing_verified": True,
        "evidence": dict(evidence or {}),
    }


def _edge(
    edge_id: str,
    source: str,
    target: str,
    source_page: str,
    source_variant: str,
    target_page: str,
    target_variant: str,
    element_id: str,
    element_label: str,
    attempt: dict,
) -> dict:
    return {
        "action_edge_id": edge_id,
        "source": source,
        "target": target,
        "source_page_id": source_page,
        "source_variant_id": source_variant,
        "target_page_id": target_page,
        "target_variant_id": target_variant,
        "action": {
            "action_type": "CLICK",
            "selector": {"element_label": element_label},
        },
        "element_id": element_id,
        "element_label": element_label,
        "region": "content",
        "attempts": [attempt],
        "attempt_count": 1,
        "routing_verified": True,
    }


def _scroll(state_id: str) -> dict:
    return {
        "scope_id": f"state:{state_id}:page",
        "state_ids": [state_id],
        "classification": "static",
        "termination": "static",
        "bottom_reached": False,
        "top_restored": True,
        "complete": True,
        "steps": 0,
        "max_steps": 16,
    }


def _happy_graph() -> dict:
    selected = {
        "id": "network", "name": "Network", "category": "navigation",
        "el_type": "link", "interactive": True, "selected": True,
        "visited": True, "region_id": "settings-sidebar",
        "exploration_status": "semantic_only",
        "exploration_reason": "Explorer confirmed no additional interface.",
    }
    open_bluetooth = {
        "id": "bluetooth", "name": "Bluetooth", "category": "navigation",
        "el_type": "link", "interactive": True, "visited": True,
        "region_id": "settings-sidebar", "group": "settings-section",
    }
    terminal_control = {
        "id": "app-a", "name": "Application A", "category": "navigation",
        "el_type": "link", "interactive": True, "visited": True,
        "abnormal_reason": "external_app",
    }
    group_alias = {
        "id": "app-b", "name": "Application B", "category": "navigation",
        "el_type": "link", "interactive": True, "visited": True,
        "group": "settings-section",
    }
    back = {
        "id": "back", "name": "Back", "category": "navigation",
        "el_type": "button", "interactive": True, "back": True,
    }
    toggle_off = {
        "id": "toggle", "name": "Bluetooth switch", "category": "navigation",
        "el_type": "toggle", "interactive": True, "visited": True,
        "stateful": True, "state_key": "bluetooth", "state_value": "off",
        "effect_scope": "function_set", "reversible": True,
    }
    toggle_on = {**toggle_off, "state_value": "on"}
    search = {
        "id": "search", "name": "Search devices", "category": "shallow",
        "el_type": "input", "interactive": True, "visited": True,
    }

    nodes = [
        _node(
            "network", "page_network", "variant_network",
            [selected, open_bluetooth, terminal_control, group_alias],
            ["cap_open_bluetooth"], [],
        ),
        _node(
            "bt_off", "page_bluetooth", "variant_off",
            [back, toggle_off, search],
            ["cap_toggle_bluetooth", "cap_search_devices"],
            [{"action_edge_id": "ae_open"}],
        ),
        _node(
            "bt_on", "page_bluetooth", "variant_on",
            [back, toggle_on], ["cap_toggle_bluetooth"],
            [{"action_edge_id": "ae_open"}, {"action_edge_id": "ae_probe"}],
        ),
    ]

    probe_evidence = {
        "stateful": True, "mutation_id": "mutation-bluetooth",
        "purpose": "probe", "state_key": "bluetooth",
        "before_value": "off", "after_value": "on",
    }
    restore_evidence = {
        "stateful": True, "mutation_id": "mutation-bluetooth",
        "purpose": "restore", "state_key": "bluetooth",
        "before_value": "on", "after_value": "off",
    }
    action_edges = [
        _edge(
            "ae_open", "network", "bt_off",
            "page_network", "variant_network",
            "page_bluetooth", "variant_off",
            "bluetooth", "Bluetooth",
            _attempt(1, "network", "bt_off"),
        ),
        _edge(
            "ae_probe", "bt_off", "bt_on",
            "page_bluetooth", "variant_off",
            "page_bluetooth", "variant_on",
            "toggle", "Bluetooth switch",
            _attempt(2, "bt_off", "bt_on", evidence=probe_evidence),
        ),
        _edge(
            "ae_restore", "bt_on", "bt_off",
            "page_bluetooth", "variant_on",
            "page_bluetooth", "variant_off",
            "toggle", "Bluetooth switch",
            _attempt(3, "bt_on", "bt_off", evidence=restore_evidence),
        ),
    ]
    pages = {
        "page_network": {
            "page_id": "page_network",
            "semantic_name": "Network",
            "capability_ids": ["cap_open_bluetooth"],
            "variants": {
                "variant_network": {
                    "variant_id": "variant_network",
                    "state_ids": ["network"],
                    "visible_capabilities": ["cap_open_bluetooth"],
                },
            },
        },
        "page_bluetooth": {
            "page_id": "page_bluetooth",
            "semantic_name": "Bluetooth",
            "capability_ids": ["cap_toggle_bluetooth", "cap_search_devices"],
            "variants": {
                "variant_off": {
                    "variant_id": "variant_off",
                    "state_ids": ["bt_off"],
                    "visible_capabilities": [
                        "cap_toggle_bluetooth", "cap_search_devices"],
                },
                "variant_on": {
                    "variant_id": "variant_on",
                    "state_ids": ["bt_on"],
                    "visible_capabilities": ["cap_toggle_bluetooth"],
                },
            },
        },
    }
    for page in pages.values():
        for variant in page["variants"].values():
            variant.setdefault("variant_signature", "{}")
            variant.setdefault("observed_facts", {})
    capabilities = {
        "cap_open_bluetooth": {
            "capability_id": "cap_open_bluetooth",
            "page_id": "page_network",
            "status": "verified",
            "availability_status": "verified",
            "entry_variants": ["variant_network"],
            "evidence_variants": ["variant_network"],
            "available_when": {"variant_ids": ["variant_network"]},
            "source_elements": [{
                "state_id": "network", "variant_id": "variant_network",
                "element_id": "bluetooth", "element_label": "Bluetooth",
            }],
            "action_edge_ids": ["ae_open"],
            "target_pages": ["page_bluetooth"],
            "target_variants": ["variant_off"],
            "effects": [{
                "kind": "navigation", "target_page_id": "page_bluetooth",
                "target_variant_id": "variant_off",
            }],
            "success_predicate": "live page is Bluetooth@off",
        },
        "cap_toggle_bluetooth": {
            "capability_id": "cap_toggle_bluetooth",
            "page_id": "page_bluetooth",
            "status": "verified",
            "availability_status": "verified",
            "entry_variants": ["variant_off", "variant_on"],
            "evidence_variants": ["variant_off", "variant_on"],
            "available_when": {
                "variant_ids": ["variant_off", "variant_on"]},
            "source_elements": [
                {
                    "state_id": "bt_off", "variant_id": "variant_off",
                    "element_id": "toggle", "element_label": "Bluetooth switch",
                },
                {
                    "state_id": "bt_on", "variant_id": "variant_on",
                    "element_id": "toggle", "element_label": "Bluetooth switch",
                },
            ],
            "action_edge_ids": ["ae_probe", "ae_restore"],
            "target_pages": ["page_bluetooth"],
            "target_variants": ["variant_off", "variant_on"],
            "effects": [{"kind": "observable_change", "state_key": "bluetooth"}],
            "success_predicate": "structured bluetooth state changes",
        },
        "cap_search_devices": {
            "capability_id": "cap_search_devices",
            "page_id": "page_bluetooth",
            "status": "discovered",
            "availability_status": "discovered",
            "entry_variants": ["variant_off"],
            "evidence_variants": ["variant_off"],
            "available_when": {"variant_ids": ["variant_off"]},
            "source_elements": [{
                "state_id": "bt_off", "variant_id": "variant_off",
                "element_id": "search", "element_label": "Search devices",
            }],
            "action_edge_ids": [],
            "target_pages": [],
            "target_variants": [],
            "effects": [],
            "success_predicate": "",
        },
    }
    topology = [
        {
            "source": "network", "target": "bt_off",
            "action_edge_ids": ["ae_open"], "routing_verified": True,
        },
        {
            "source": "bt_off", "target": "bt_on",
            "action_edge_ids": ["ae_probe"], "routing_verified": True,
        },
        {
            "source": "bt_on", "target": "bt_off",
            "action_edge_ids": ["ae_restore"], "routing_verified": True,
        },
    ]
    return {
        "graph_schema_version": 3,
        "app_name": "settings",
        "stop_reason": "frontier_empty",
        "nodes": nodes,
        "edges": topology,
        "pages": pages,
        "capabilities": capabilities,
        "action_edges": action_edges,
        "scroll_ledger": [_scroll("network"), _scroll("bt_off"), _scroll("bt_on")],
        "abnormal_buttons": [],
    }


def _assert_failed(report: dict, check_id: str, code: str | None = None) -> None:
    assert report["status"] == "incomplete"
    check = report["checks"][check_id]
    assert check["passed"] is False, (check_id, check)
    if code is not None:
        assert code in {item["code"] for item in check["issues"]}, check


def test_happy_path_certifies_all_evidence_classes_and_is_pure() -> None:
    graph = _happy_graph()
    before = json.dumps(graph, ensure_ascii=False, sort_keys=True)
    report = evaluate_traversal_completion(graph)
    after = json.dumps(graph, ensure_ascii=False, sort_keys=True)
    assert report["schema"] == CERTIFICATE_SCHEMA
    assert report["status"] == "certified", report["checks"]
    assert all(item["passed"] for item in report["checks"].values())
    outcomes = {item["outcome"] for item in report["control_outcomes"]}
    assert {
        "verified_attempt", "inventory_capability", "semantic_only", "back",
        "abnormal", "group_alias",
    } <= outcomes
    assert len(report["graph_evidence_digest"]["sha256"]) == 64
    assert before == after, "completion evaluation must not mutate graph data"

    # The persisted StateGraph uses a dict in memory and a list on disk.
    dict_ledger = copy.deepcopy(graph)
    dict_ledger["scroll_ledger"] = {
        item["scope_id"]: item for item in dict_ledger["scroll_ledger"]}
    assert evaluate_traversal_completion(dict_ledger)["status"] == "certified"


def test_schema_and_missing_materials_fail_closed() -> None:
    graph = _happy_graph()
    graph["graph_schema_version"] = 2
    graph.pop("action_edges")
    graph["transition_events"] = []
    report = evaluate_traversal_completion(graph)
    _assert_failed(report, "schema_materials", "unsupported_graph_schema")
    assert "legacy_transition_events_present" in {
        item["code"] for item in report["checks"]["schema_materials"]["issues"]}
    assert evaluate_traversal_completion(None)["status"] == "incomplete"


def test_frontier_scroll_and_controls_each_fail_closed() -> None:
    graph = _happy_graph()
    graph["stop_reason"] = "max_actions"
    _assert_failed(
        evaluate_traversal_completion(graph),
        "frontier_exhaustion", "frontier_not_exhausted")

    graph = _happy_graph()
    graph["scroll_ledger"][1].update({
        "classification": "scrollable",
        "termination": "hard_cap",
        "bottom_reached": False,
        "top_restored": False,
        "complete": False,
    })
    _assert_failed(
        evaluate_traversal_completion(graph),
        "scroll_exhaustion", "scroll_scope_aborted")

    graph = _happy_graph()
    graph["nodes"][0]["elements"].append({
        "id": "orphan", "name": "Orphan page", "category": "navigation",
        "el_type": "link", "interactive": True, "visited": True,
    })
    report = evaluate_traversal_completion(graph)
    _assert_failed(report, "control_coverage", "control_without_outcome")
    orphan = next(item for item in report["control_outcomes"]
                  if item["element_id"] == "orphan")
    assert orphan["outcome"] == "unresolved"
    assert "visited is not execution evidence" in orphan["evidence"]["reason"]


def test_one_completed_stable_region_scroll_scope_covers_all_mapped_variants():
    graph = _happy_graph()
    for node in graph["nodes"]:
        node["semantic_blocks"] = [{
            "region_id": "shared-region",
            "role": "shared content",
            "scrollable": True,
        }]
    graph["scroll_ledger"] = [{
        "scope_id": "region:shared-region",
        "state_ids": ["network"],
        "region_id": "shared-region",
        "classification": "static",
        "termination": "static",
        "bottom_reached": True,
        "top_restored": True,
        "complete": True,
    }]

    report = evaluate_traversal_completion(graph)

    assert report["checks"]["scroll_exhaustion"]["passed"] is True
    assert report["checks"]["scroll_exhaustion"]["evidence"][
        "required_regions"] == 1
    assert report["checks"]["scroll_exhaustion"]["evidence"][
        "covered_regions"] == 1


def test_static_regions_do_not_force_old_states_through_a_scroll_audit():
    graph = _happy_graph()
    for index, node in enumerate(graph["nodes"]):
        node["semantic_blocks"] = [{
            "region_id": f"static-region-{index}",
            "role": "visible controls",
            "scrollable": False,
        }]
    graph["scroll_ledger"] = []

    report = evaluate_traversal_completion(graph)

    assert report["checks"]["scroll_exhaustion"]["passed"] is True
    assert report["checks"]["scroll_exhaustion"]["evidence"][
        "required_regions"] == 0


def test_region_lazy_node_cannot_certify_with_unobserved_region() -> None:
    graph = _happy_graph()
    graph["nodes"][0]["perception_mode"] = "region_lazy"
    graph["nodes"][0]["region_observation"] = {
        "network:r0": {"status": "complete", "attempts": 1},
        "network:r1": {"status": "pending", "attempts": 0},
    }

    report = evaluate_traversal_completion(graph)

    _assert_failed(
        report, "control_coverage", "region_inventory_incomplete")


def test_navigation_group_alias_requires_verified_representative() -> None:
    for terminal_reason in ("external_app", "no_effect"):
        graph = _happy_graph()
        elements = graph["nodes"][0]["elements"]
        verified = next(item for item in elements if item["id"] == "bluetooth")
        terminal = next(item for item in elements if item["id"] == "app-a")
        alias = next(item for item in elements if item["id"] == "app-b")
        verified.pop("group")
        terminal["group"] = "installed-app"
        terminal["abnormal_reason"] = terminal_reason
        alias["group"] = "installed-app"

        report = evaluate_traversal_completion(graph)
        _assert_failed(report, "control_coverage", "control_without_outcome")
        outcomes = {
            item["element_id"]: item for item in report["control_outcomes"]
            if item["state_id"] == "network"
        }
        assert outcomes["app-a"]["outcome"] == "abnormal"
        assert outcomes["app-a"]["evidence"]["reason"] == terminal_reason
        assert outcomes["app-b"]["outcome"] == "unresolved"
        assert outcomes["app-b"]["resolved"] is False

    graph = _happy_graph()
    verified = next(
        item for item in graph["nodes"][0]["elements"]
        if item["id"] == "bluetooth"
    )
    verified["category"] = "shallow"
    report = evaluate_traversal_completion(graph)
    _assert_failed(report, "control_coverage", "control_without_outcome")
    alias = next(
        item for item in report["control_outcomes"]
        if item["state_id"] == "network" and item["element_id"] == "app-b"
    )
    assert alias["outcome"] == "unresolved"

    graph = _happy_graph()
    peer_verified = next(
        item for item in graph["nodes"][0]["elements"]
        if item["id"] == "bluetooth"
    )
    peer_alias = next(
        item for item in graph["nodes"][0]["elements"]
        if item["id"] == "app-b"
    )
    peer_verified.update({
        "group": "bottom_nav", "region": "primary_navigation"})
    peer_alias.update({
        "group": "bottom_nav", "region": "primary_navigation"})
    report = evaluate_traversal_completion(graph)
    _assert_failed(report, "control_coverage", "control_without_outcome")
    peer_alias_outcome = next(
        item for item in report["control_outcomes"]
        if item["state_id"] == "network" and item["element_id"] == "app-b"
    )
    assert peer_alias_outcome["outcome"] == "unresolved"
    assert peer_alias_outcome["resolved"] is False


def test_same_page_blocked_landing_is_observed_but_not_routable() -> None:
    graph = _happy_graph()
    blocked_back = {
        "id": "blocked-back", "name": "Back", "category": "navigation",
        "el_type": "button", "interactive": True, "back": True,
    }
    graph["nodes"].append(_node(
        "bt_blocked", "page_bluetooth", "variant_blocked",
        [blocked_back], [], [{"action_edge_id": "ae_blocked"}],
    ))
    graph["pages"]["page_bluetooth"]["variants"]["variant_blocked"] = {
        "variant_id": "variant_blocked",
        "variant_signature": "{}",
        "observed_facts": {},
        "state_ids": ["bt_blocked"],
        "visible_capabilities": [],
    }
    blocked_attempt = _attempt(4, "bt_off", "bt_blocked")
    blocked_attempt.update({
        "outcome": "blocked",
        "committed": False,
        "landing_verified": True,
        "evidence": {
            "terminal_landing": True,
            "terminal_reason": "blocked",
        },
    })
    blocked_edge = _edge(
        "ae_blocked", "bt_off", "bt_blocked",
        "page_bluetooth", "variant_off",
        "page_bluetooth", "variant_blocked",
        "toggle", "Bluetooth switch", blocked_attempt,
    )
    blocked_edge["routing_verified"] = False
    graph["action_edges"].append(blocked_edge)
    graph["scroll_ledger"].append(_scroll("bt_blocked"))

    report = evaluate_traversal_completion(graph)
    assert report["status"] == "certified", report["checks"]
    routing = report["checks"]["routing_reachability"]["evidence"]
    assert 4 in routing["terminal_landing_action_indices"]
    assert "ae_blocked" not in routing["verified_action_edge_ids"]

    # A generic inconsistent/non-routing target remains an orphan.  The explicit
    # terminal marker is mandatory and cannot be inferred from visited state.
    broken = copy.deepcopy(graph)
    broken["action_edges"][-1]["attempts"][0]["evidence"].pop(
        "terminal_landing")
    _assert_failed(
        evaluate_traversal_completion(broken),
        "routing_reachability", "routing_unreachable_nodes")


def test_open_mutation_page_variant_and_routing_each_fail_closed() -> None:
    graph = _happy_graph()
    restore = graph["action_edges"][2]["attempts"][0]
    restore["committed"] = False
    restore["landing_verified"] = False
    graph["action_edges"][2]["routing_verified"] = False
    _assert_failed(
        evaluate_traversal_completion(graph),
        "state_restoration", "stateful_mutation_open")

    graph = _happy_graph()
    probe = graph["action_edges"][1]["attempts"][0]
    probe.update({
        "outcome": "app_crash", "committed": False,
        "landing_verified": False,
    })
    probe["evidence"].update({
        "after_value": "unknown", "mutation_status": "unknown",
    })
    graph["action_edges"][1]["routing_verified"] = False
    graph["edges"][1]["routing_verified"] = False
    _assert_failed(
        evaluate_traversal_completion(graph),
        "state_restoration", "stateful_mutation_outcome_unknown")

    graph = _happy_graph()
    graph["pages"]["page_bluetooth"]["variants"]["variant_on"][
        "state_ids"] = []
    _assert_failed(
        evaluate_traversal_completion(graph),
        "page_variant_consistency", "variant_without_state")

    graph = _happy_graph()
    probe = graph["action_edges"][1]["attempts"][0]
    probe["committed"] = False
    probe["landing_verified"] = False
    probe["outcome"] = "no_effect"
    graph["action_edges"][1]["routing_verified"] = False
    graph["edges"][1]["routing_verified"] = False
    _assert_failed(
        evaluate_traversal_completion(graph),
        "routing_reachability", "routing_unreachable_nodes")


def test_grouped_baseline_return_uses_the_frozen_restore_value() -> None:
    graph = _happy_graph()
    probe = graph["action_edges"][1]["attempts"][0]["evidence"]
    probe.update({
        "before_value": "off",
        "after_value": "unknown",
        "restore_before_value": "on",
    })
    restore = graph["action_edges"][2]["attempts"][0]["evidence"]
    restore.update({
        "before_value": "unknown",
        "after_value": "on",
        "restore_before_value": "on",
        "restoration_kind": "verified_baseline_return",
    })

    report = evaluate_traversal_completion(graph)

    assert report["checks"]["state_restoration"]["status"] == "passed"


def test_capability_references_effect_and_predicate_fail_closed() -> None:
    graph = _happy_graph()
    cap = graph["capabilities"]["cap_open_bluetooth"]
    cap["action_edge_ids"] = ["unknown-edge"]
    cap["effects"] = []
    cap["success_predicate"] = ""
    report = evaluate_traversal_completion(graph)
    _assert_failed(
        report, "capability_integrity", "capability_action_edge_missing")
    codes = {item["code"]
             for item in report["checks"]["capability_integrity"]["issues"]}
    assert {
        "verified_capability_without_verified_edge",
        "verified_capability_without_effect",
        "verified_capability_without_predicate",
    } <= codes

    graph = _happy_graph()
    graph["nodes"][0]["visible_capabilities"].append("unknown-capability")
    _assert_failed(
        evaluate_traversal_completion(graph),
        "capability_integrity", "unknown_capability_reference")


def test_capability_source_id_cannot_silently_point_to_another_label() -> None:
    graph = _happy_graph()
    source = graph["capabilities"]["cap_open_bluetooth"]["source_elements"][0]
    source["element_id"] = "network"
    source["element_label"] = "Bluetooth"

    report = evaluate_traversal_completion(graph)
    _assert_failed(
        report, "capability_integrity", "capability_source_element_missing")


def test_retry_errors_are_not_terminal_and_drag_needs_explicit_unsupported() -> None:
    graph = _happy_graph()
    orphan = {
        "id": "retry", "name": "Retry target", "category": "navigation",
        "el_type": "link", "interactive": True, "visited": True,
        "abnormal_reason": "target_rebind_failed",
    }
    graph["nodes"][0]["elements"].append(orphan)
    graph["abnormal_buttons"].append({
        "state_id": "network", "element_id": "retry",
        "element_name": "Retry target", "reason": "target_rebind_failed",
    })
    report = evaluate_traversal_completion(graph)
    _assert_failed(report, "control_coverage", "control_without_outcome")
    retry = next(item for item in report["control_outcomes"]
                 if item["element_id"] == "retry")
    assert retry["outcome"] == "unresolved"
    assert retry["evidence"]["rejected_abnormal_reason"] == \
        "target_rebind_failed"

    graph["abnormal_buttons"][0]["evidence"] = {
        "kind": "bounded_local_failure",
        "attempts_used": 2,
        "failure_kind": "visible_target_not_confirmed",
    }
    assert evaluate_traversal_completion(graph)["status"] == "certified"

    graph = _happy_graph()
    graph["nodes"][0]["elements"].append({
        "id": "historical", "name": "Historical target",
        "category": "navigation", "el_type": "link",
        "interactive": True, "visited": True,
        "abnormal_reason": "route_unavailable",
    })
    graph["abnormal_buttons"].append({
        "state_id": "network", "element_id": "historical",
        "element_name": "Historical target", "reason": "route_unavailable",
        "evidence": {
            "kind": "route_unavailable",
            "attempts_used": 2,
            "failure_kind": "identity_mismatch",
            "landed_state_id": "bt_off",
        },
    })
    assert evaluate_traversal_completion(graph)["status"] == "certified"

    graph = _happy_graph()
    graph["nodes"][1]["elements"].append({
        "id": "volume", "name": "Volume", "category": "shallow",
        "el_type": "slider", "interactive": True, "visited": True,
    })
    graph["nodes"][1]["visible_capabilities"].append("cap_volume")
    graph["pages"]["page_bluetooth"]["capability_ids"].append("cap_volume")
    graph["pages"]["page_bluetooth"]["variants"]["variant_off"][
        "visible_capabilities"].append("cap_volume")
    graph["capabilities"]["cap_volume"] = {
        "capability_id": "cap_volume", "page_id": "page_bluetooth",
        "status": "discovered", "availability_status": "discovered",
        "entry_variants": ["variant_off"],
        "evidence_variants": ["variant_off"],
        "available_when": {"variant_ids": ["variant_off"]},
        "source_elements": [{
            "state_id": "bt_off", "variant_id": "variant_off",
            "element_id": "volume", "element_label": "Volume",
            "element_type": "slider",
        }],
        "execution_recipe": [], "action_edge_ids": [],
    }
    report = evaluate_traversal_completion(graph)
    _assert_failed(
        report, "capability_integrity", "unsupported_drag_contract_missing")
    graph["capabilities"]["cap_volume"].update({
        "availability_status": "unsupported",
        "execution_support": "unsupported",
        "unsupported_reason": (
            "semantic drag destination is not observable from one control"),
    })
    assert evaluate_traversal_completion(graph)["status"] == "certified"


def test_stateful_no_effect_requires_fresh_post_action_proof() -> None:
    graph = _happy_graph()
    probe = graph["action_edges"][1]["attempts"][0]
    probe.update({
        "outcome": "no_effect", "committed": False,
        "landing_verified": False,
    })
    graph["action_edges"][1]["routing_verified"] = False
    graph["edges"][1]["routing_verified"] = False
    graph["nodes"][0]["elements"][1].update({
        "abnormal_reason": "stateful_no_effect", "visited": True})
    graph["abnormal_buttons"].append({
        "state_id": "bt_off", "element_id": "toggle",
        "element_name": "Bluetooth switch",
        "reason": "stateful_no_effect",
    })

    report = evaluate_traversal_completion(graph)
    control = next(item for item in report["control_outcomes"]
                   if item["state_id"] == "bt_off"
                   and item["element_id"] == "toggle")
    assert control["outcome"] == "unresolved"

    probe["evidence"].update({
        "fresh_post_action_observation": True,
        "post_action_phash_distance": 0,
    })
    report = evaluate_traversal_completion(graph)
    control = next(item for item in report["control_outcomes"]
                   if item["state_id"] == "bt_off"
                   and item["element_id"] == "toggle")
    assert control["outcome"] == "abnormal"


def test_data_only_stateful_control_accepts_verified_local_change() -> None:
    graph = _happy_graph()
    off_node = next(node for node in graph["nodes"]
                    if node["state_id"] == "bt_off")
    toggle = next(element for element in off_node["elements"]
                  if element["id"] == "toggle")
    toggle["effect_scope"] = "data_only"
    probe = graph["action_edges"][1]["attempts"][0]
    probe["evidence"] = {
        "fresh_post_action_observation": True,
        "post_action_phash_distance": 2,
    }

    report = evaluate_traversal_completion(graph)
    control = next(item for item in report["control_outcomes"]
                   if item["state_id"] == "bt_off"
                   and item["element_id"] == "toggle")
    assert control["outcome"] == "verified_attempt"
    assert control["resolved"] is True

    toggle["effect_scope"] = "function_set"
    report = evaluate_traversal_completion(graph)
    control = next(item for item in report["control_outcomes"]
                   if item["state_id"] == "bt_off"
                   and item["element_id"] == "toggle")
    assert control["outcome"] == "unresolved"


def test_explorer_semantic_and_verified_coverage_are_terminal_evidence() -> None:
    graph = _happy_graph()
    graph["nodes"][0]["elements"].extend([
        {
            "id": "help", "name": "Help", "category": "shallow",
            "el_type": "button", "interactive": True,
            "exploration_status": "semantic_only", "visited": True,
        },
        {
            "id": "network-copy", "name": "Network copy",
            "category": "navigation", "el_type": "link",
            "interactive": True, "exploration_status": "covered",
            "covered_by": "bluetooth", "visited": True,
        },
    ])

    report = evaluate_traversal_completion(graph)
    outcomes = {
        item["element_id"]: item for item in report["control_outcomes"]
    }
    assert outcomes["help"]["outcome"] == "semantic_only"
    assert outcomes["network-copy"]["outcome"] == "explorer_covered"


def test_selected_flag_alone_is_not_completion_evidence() -> None:
    graph = _happy_graph()
    selected = graph["nodes"][0]["elements"][0]
    selected.pop("exploration_status")
    selected.pop("exploration_reason")

    report = evaluate_traversal_completion(graph)

    control = next(item for item in report["control_outcomes"]
                   if item["state_id"] == "network"
                   and item["element_id"] == "network")
    assert control["outcome"] == "unresolved"
    assert report["status"] == "incomplete"


def test_cross_state_covered_control_requires_verified_shared_region_source() -> None:
    graph = _happy_graph()
    graph["nodes"][1]["elements"].append({
        "id": "home-copy", "name": "Home", "category": "navigation",
        "el_type": "link", "interactive": True,
        "region_id": "settings-sidebar", "exploration_status": "covered",
        "covered_by": "bluetooth", "covered_by_state": "network",
        "exploration_reason": "Explorer mapped the verified shared result.",
        "visited": True,
    })

    report = evaluate_traversal_completion(graph)

    control = next(item for item in report["control_outcomes"]
                   if item["element_id"] == "home-copy")
    assert control["outcome"] == "explorer_covered"
    assert control["evidence"]["scope"] == "shared_region"
    assert control["evidence"]["representative_state_id"] == "network"

    graph["nodes"][1]["elements"][-1]["region_id"] = "different-region"
    report = evaluate_traversal_completion(graph)
    control = next(item for item in report["control_outcomes"]
                   if item["element_id"] == "home-copy")
    assert control["outcome"] == "unresolved"


def test_covered_control_requires_verified_representative_on_same_state() -> None:
    graph = _happy_graph()
    graph["nodes"][0]["elements"].append({
        "id": "network-copy", "name": "Network copy",
        "category": "navigation", "el_type": "link", "interactive": True,
        "exploration_status": "covered", "covered_by": "missing",
        "visited": True,
    })

    report = evaluate_traversal_completion(graph)
    control = next(
        item for item in report["control_outcomes"]
        if item["element_id"] == "network-copy")
    assert control["resolved"] is False
    assert control["evidence"]["reason"] == (
        "covered representative lacks a verified action")


def test_shared_region_attempt_does_not_verify_an_unexecuted_peer_control() -> None:
    graph = _happy_graph()
    graph["nodes"][1]["elements"].append({
        "id": "bluetooth-peer", "name": "Bluetooth",
        "category": "navigation", "el_type": "link",
        "interactive": True, "region_id": "settings-sidebar",
    })

    report = evaluate_traversal_completion(graph)

    peer = next(
        item for item in report["control_outcomes"]
        if item["state_id"] == "bt_off"
        and item["element_id"] == "bluetooth-peer")
    assert peer["outcome"] == "unresolved"
    assert peer["resolved"] is False


def test_cli_writer_persists_current_certificate_atomically() -> None:
    from gui_rewalk.run_visual_traversal import write_completion_certificate

    with tempfile.TemporaryDirectory() as temporary:
        certificate = write_completion_certificate(_happy_graph(), temporary)
        destination = Path(temporary) / "completion.json"
        assert destination.exists()
        assert not (Path(temporary) / "completion.json.tmp").exists()
        persisted = json.loads(destination.read_text(encoding="utf-8"))
        assert persisted == certificate
        assert persisted["status"] == "certified"


def main() -> int:
    test_happy_path_certifies_all_evidence_classes_and_is_pure()
    test_schema_and_missing_materials_fail_closed()
    test_frontier_scroll_and_controls_each_fail_closed()
    test_navigation_group_alias_requires_verified_representative()
    test_same_page_blocked_landing_is_observed_but_not_routable()
    test_open_mutation_page_variant_and_routing_each_fail_closed()
    test_capability_references_effect_and_predicate_fail_closed()
    test_retry_errors_are_not_terminal_and_drag_needs_explicit_unsupported()
    test_cli_writer_persists_current_certificate_atomically()
    print("PASS traversal completion certificate: happy path + fail-closed gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
