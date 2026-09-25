"""Offline regression for the read-only GraphQualityAgent."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.src.core.graph.graph_quality_agent import (  # noqa: E402
    COVERAGE_STATUSES,
    VLM_REQUEST_SCHEMA,
    GraphQualityAgent,
)


class _LowConfidenceJudge:
    def __init__(self) -> None:
        self.requests: list[Mapping[str, Any]] = []

    def __call__(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.requests.append(copy.deepcopy(request))
        if request["task"] == "judge_node_semantics_and_function_coverage":
            return {
                "correctness": "correct",
                "coverage_status": "unsupported",
                "confidence": 0.25,
                "reasons": ["not enough visible evidence"],
                "evidence": [],
            }
        return {
            "correctness": "correct",
            "coverage_status": "unknown",
            "confidence": 0.25,
            "reasons": ["weak edge judgement"],
            "evidence": [],
        }


def _image(path: Path, *, variant: bool = False) -> None:
    image = Image.new("RGB", (640, 480), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 70, 560, 430), outline="black", width=3)
    draw.text((120, 100), "Settings", fill="black")
    if variant:
        draw.rectangle((500, 390, 510, 400), fill="gray")
    image.save(path)


def _fixture(root: Path) -> Path:
    first = root / "first.png"
    second = root / "second.png"
    _image(first)
    _image(second)  # byte-identical evidence -> duplicate node clue
    graph = {
        "directed": True,
        "multigraph": False,
        "app_name": "settings",
        "stop_reason": "frontier_empty",
        "action_counter": 5,
        "nodes": [
            {
                "id": "modal",
                "state_id": "modal",
                "page_name": "Users",
                "screenshot_path": str(first),
                "is_modal": True,
                "modal_bbox": [100, 100, 500, 420],
                "elements": [
                    {
                        "id": 1,
                        "name": "Unlock to Add Users and Change Settings",
                        "category": "display",
                        "interactive": False,
                        "visited": True,
                        "center": [250, 140],
                        "region": "dialog",
                    },
                    {
                        "id": 2,
                        "name": "Add User",
                        "category": "navigation",
                        "el_type": "button",
                        "interactive": True,
                        "visited": True,
                        "enabled": False,
                        "center": [250, 200],
                        "bbox_xywh": [200, 180, 100, 40],
                        "region": "form_body",
                        "region_bbox": [100, 100, 500, 420],
                    },
                    {
                        "id": 3,
                        "name": "Network Proxy",
                        "category": "navigation",
                        "el_type": "link",
                        "interactive": True,
                        "visited": True,
                        "center": [40, 40],
                        "bbox_xywh": [10, 20, 80, 40],
                        "region": "background_sidebar",
                        "region_bbox": [10, 10, 90, 90],
                    },
                ],
            },
            {
                "id": "target",
                "state_id": "target",
                "page_name": "Bluetooth",
                "screenshot_path": str(second),
                "merged_page_names": ["Bluetooth", "Calendar"],
                "elements": [
                    {
                        "id": 9,
                        "name": "Bluetooth",
                        "category": "navigation",
                        "el_type": "link",
                        "interactive": True,
                        "visited": False,
                        "center": [200, 200],
                        "region": "content",
                    }
                ],
            },
        ],
        "edges": [
            {
                "source": "modal",
                "target": "target",
                "action_index": 1,
                "element_id": "2",
                "element_label": "Add User",
                "effect_verdict": "transitioned_consistent",
                "landing_verified": True,
                "target_page_name": "Users",
                "resolved_center": [700, 200],
                "region_bbox": [100, 100, 500, 420],
            },
            {
                "source": "modal",
                "target": "target",
                "action_index": 5,
                "element_id": "3",
                "element_label": "Network Proxy",
                "effect_verdict": "transitioned_consistent",
                "landing_verified": True,
                "target_page_name": "Calendar",
                "resolved_center": [40, 40],
                "region_bbox": [10, 10, 90, 90],
            },
        ],
        "transition_events": [
            {
                "action_index": 1,
                "source": "modal",
                "target": "target",
                "outcome": "transitioned_consistent",
                "committed_edge": True,
            },
            {"action_index": 3, "source": "modal", "outcome": "no_effect"},
            {"action_index": 3, "source": "modal", "outcome": "no_effect"},
            {
                "action_index": 5,
                "source": "modal",
                "target": "target",
                "outcome": "transitioned_consistent",
                "committed_edge": True,
            },
        ],
    }
    path = root / "graph.json"
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_rules_vlm_contract_and_read_only_report() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        graph_path = _fixture(root)
        before = graph_path.read_bytes()
        judge = _LowConfidenceJudge()
        agent = GraphQualityAgent(judge, min_vlm_confidence=0.7, workspace=root)
        report = agent.evaluate(graph_path)

        assert graph_path.read_bytes() == before
        assert report["read_only"] is True
        assert report["status"] == "error"
        assert 0 <= report["score"] < 100
        assert 0 < report["confidence"] <= 1
        assert set(report["summary"]["coverage_statuses"]) == set(COVERAGE_STATUSES)

        codes = {item["code"] for item in report["findings"]}
        assert report["completion_certificate"]["status"] == "incomplete"
        assert {
            "traversal_completion_incomplete",
            "duplicate_visual_nodes",
            "duplicate_node_visual",
            "overmerge_page_identity_conflict",
            "possible_overmerge",
            "node_exploration_incomplete",
            "permission_recorded_as_success",
            "modal_background_leakage",
            "retarget_outside_region",
            "landing_page_name_mismatch",
            "action_ledger_count_mismatch",
            "action_event_index_gaps",
            "duplicate_action_event_indexes",
            "digraph_pair_overwrite_risk",
        } <= codes

        assert report["ledger"]["history_status"] == "incomplete"
        assert report["ledger"]["missing_event_indexes"] == [2, 4]
        assert report["ledger"]["duplicate_event_indexes"] == [3]

        # The node was unknown/incomplete before semantic review.  A weak VLM
        # cannot claim absence and promote it to unsupported.
        target = next(item for item in report["nodes"] if item["node_id"] == "target")
        assert target["coverage_status"] == "unknown"
        assert target["vlm_evaluation"]["coverage_status"] == "unknown"
        assert target["vlm_evaluation"]["accepted"] is False
        assert target["evidence"]["screenshot"]["sha256"]
        assert target["evidence"]["elements"]["items"][0]["name"] == "Bluetooth"

        assert judge.requests
        for request in judge.requests:
            assert request["schema_version"] == VLM_REQUEST_SCHEMA
            assert request["policy"]["do_not_modify_graph"] is True
            assert isinstance(request["evidence"], dict)
            assert isinstance(request["response_schema"], dict)

        output = root / "quality" / "report.json"
        agent.write_report(report, output)
        persisted = json.loads(output.read_text(encoding="utf-8"))
        assert persisted["schema_version"] == report["schema_version"]
        assert graph_path.read_bytes() == before


def test_complete_ledger_and_high_confidence_semantic_override() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        screenshot = root / "page.png"
        _image(screenshot, variant=True)
        graph = {
            "app_name": "clock",
            "action_counter": 0,
            "transition_events": [],
            "nodes": [
                {
                    "state_id": "empty",
                    "page_name": "Alarm List",
                    "screenshot_path": str(screenshot),
                    "elements": [
                        {
                            "id": 1,
                            "name": "Create alarm",
                            "category": "navigation",
                            "el_type": "button",
                            "visited": True,
                            "interactive": True,
                        }
                    ],
                }
            ],
            "edges": [],
        }
        original = copy.deepcopy(graph)

        def judge(request: Mapping[str, Any]) -> Mapping[str, Any]:
            assert request["task"] == "judge_node_semantics_and_function_coverage"
            return {
                "correctness": "correct",
                "coverage_status": "conditional",
                "confidence": 0.95,
                "reasons": ["alarm detail requires an alarm resource"],
                "evidence": ["Create alarm is visible"],
            }

        report = GraphQualityAgent(judge, workspace=root).evaluate_data(graph)
        assert graph == original
        assert report["ledger"]["history_status"] == "complete"
        assert report["nodes"][0]["coverage_status"] == "conditional"
        assert report["nodes"][0]["vlm_evaluation"]["accepted"] is True


def test_missing_ledger_exposes_digraph_history_loss() -> None:
    graph = {
        "action_counter": 4,
        "nodes": [
            {"state_id": "a", "page_name": "A", "elements": []},
            {"state_id": "b", "page_name": "B", "elements": []},
        ],
        "edges": [
            {"source": "a", "target": "b", "action_index": 4, "landing_verified": True}
        ],
    }
    report = GraphQualityAgent().evaluate_data(graph)
    codes = {item["code"] for item in report["findings"]}
    assert {"missing_action_event_ledger", "possible_digraph_overwrite"} <= codes
    assert report["ledger"]["edge_index_gaps"] == [1, 2, 3]


def test_unlock_edge_must_clear_permission_gate() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        screenshot = root / "locked.png"
        _image(screenshot)
        graph = {
            "action_counter": 1,
            "transition_events": [
                {
                    "action_index": 1,
                    "source": "locked",
                    "target": "locked",
                    "outcome": "transitioned_consistent",
                    "committed_edge": True,
                }
            ],
            "nodes": [
                {
                    "state_id": "locked",
                    "page_name": "Printers",
                    "screenshot_path": str(screenshot),
                    "elements": [
                        {
                            "id": 1,
                            "name": "Unlock",
                            "category": "navigation",
                            "el_type": "button",
                            "interactive": True,
                            "visited": True,
                            "enabled": True,
                            "requires_permission": True,
                            "blocked_reason": "system_settings_unlock",
                            "region": "content",
                        },
                        {
                            "id": 2,
                            "name": "Unlock to Add Printers and Change Settings",
                            "category": "display",
                            "interactive": False,
                            "visited": True,
                        },
                    ],
                }
            ],
            "edges": [
                {
                    "source": "locked",
                    "target": "locked",
                    "action_index": 1,
                    "element_id": "1",
                    "element_label": "Unlock",
                    "effect_verdict": "transitioned_consistent",
                    "landing_verified": True,
                    "target_page_name": "Printers",
                }
            ],
        }
        report = GraphQualityAgent(workspace=root).evaluate_data(graph)
        codes = {item["code"] for item in report["findings"]}
        assert "permission_gate_not_cleared" in codes
        assert "permission_recorded_as_success" in codes
        assert report["edges"][0]["correctness"] == "incorrect"


def test_legacy_permission_context_is_warning_not_false_error() -> None:
    graph = {
        "nodes": [
            {
                "state_id": "printers",
                "page_name": "Printers",
                "elements": [
                    {
                        "id": 1,
                        "name": "Unlock to Add Printers and Change Settings",
                        "category": "display",
                        "interactive": False,
                        "visited": True,
                    },
                    {
                        "id": 2,
                        "name": "Additional Printer Settings",
                        "category": "navigation",
                        "el_type": "button",
                        "interactive": True,
                        "visited": True,
                        "region": "content",
                    },
                ],
            },
            {"state_id": "details", "page_name": "Printer details", "elements": []},
        ],
        "edges": [
            {
                "source": "printers",
                "target": "details",
                "element_id": "2",
                "element_label": "Additional Printer Settings",
                "effect_verdict": "transitioned_consistent",
                "landing_verified": True,
            }
        ],
    }
    report = GraphQualityAgent().evaluate_data(graph)
    codes = {item["code"] for item in report["findings"]}
    assert "possible_permission_gated_success" in codes
    assert "permission_recorded_as_success" not in codes


def test_selected_blocked_and_terminal_controls_are_not_pending_coverage() -> None:
    graph = {
        "nodes": [{
            "state_id": "settings",
            "page_name": "Users",
            "elements": [
                {
                    "id": 1, "name": "Users", "category": "navigation",
                    "el_type": "link", "selected": True, "visited": False,
                },
                {
                    "id": 2, "name": "Add User", "category": "navigation",
                    "el_type": "button", "enabled": False, "visited": False,
                },
                {
                    "id": 3, "name": "Open companion", "category": "navigation",
                    "el_type": "button", "visited": False,
                    "abnormal_reason": "external_app",
                },
            ],
        }],
        "edges": [],
    }
    report = GraphQualityAgent().evaluate_data(graph)
    codes = {item["code"] for item in report["findings"]}
    assert "node_exploration_incomplete" not in codes
    assert report["nodes"][0]["evidence"]["elements"]["pending_navigation"] == 0
    assert report["nodes"][0]["coverage_status"] == "blocked"


def test_visited_flags_must_agree_with_action_outcomes() -> None:
    graph = {
        "nodes": [
            {
                "state_id": "source",
                "page_name": "Source",
                "elements": [
                    {
                        "id": 1, "name": "Orphan function",
                        "category": "navigation", "el_type": "button",
                        "visited": True,
                    },
                    {
                        "id": 2, "name": "Recorded function",
                        "category": "navigation", "el_type": "button",
                        "visited": False,
                    },
                ],
            },
            {"state_id": "target", "page_name": "Target", "elements": []},
        ],
        "edges": [{
            "source": "source", "target": "target",
            "element_id": "2", "element_label": "Recorded function",
            "landing_verified": True,
        }],
    }
    report = GraphQualityAgent().evaluate_data(graph)
    codes = {item["code"] for item in report["findings"]}
    assert "visited_control_without_outcome" in codes
    assert "outcome_control_marked_unvisited" in codes


def test_shared_region_outcomes_and_selected_peer_count_once_globally() -> None:
    graph = {
        "nodes": [
            {
                "state_id": "network",
                "page_name": "Network",
                "elements": [
                    {
                        "id": 1, "name": "Network", "category": "navigation",
                        "el_type": "link", "region_id": "sidebar", "selected": True,
                    },
                    {
                        "id": 2, "name": "Bluetooth", "category": "navigation",
                        "el_type": "link", "region_id": "sidebar", "visited": True,
                    },
                    {
                        "id": 3, "name": "Background", "category": "navigation",
                        "el_type": "link", "region_id": "sidebar", "visited": False,
                    },
                    {
                        "id": 4, "name": "Privacy", "category": "navigation",
                        "el_type": "link", "region_id": "sidebar", "visited": False,
                    },
                ],
            },
            {
                "state_id": "bluetooth",
                "page_name": "Bluetooth",
                "elements": [
                    {
                        "id": 1, "name": "Network", "category": "navigation",
                        "el_type": "link", "region_id": "sidebar", "visited": True,
                    },
                    {
                        "id": 2, "name": "Bluetooth", "category": "navigation",
                        "el_type": "link", "region_id": "sidebar", "selected": True,
                    },
                    {
                        "id": 3, "name": "Background", "category": "navigation",
                        "el_type": "link", "region_id": "sidebar", "visited": True,
                    },
                    {
                        "id": 4, "name": "Privacy", "category": "navigation",
                        "el_type": "link", "region_id": "sidebar", "visited": False,
                    },
                ],
            },
            {
                "state_id": "background",
                "page_name": "Background",
                "elements": [],
            },
        ],
        "edges": [
            {
                "source": "network", "target": "bluetooth", "element_id": "2",
                "element_label": "Bluetooth", "landing_verified": True,
            },
            {
                "source": "bluetooth", "target": "background", "element_id": "3",
                "element_label": "Background", "landing_verified": True,
            },
        ],
    }
    report = GraphQualityAgent().evaluate_data(graph)
    by_node = {item["node_id"]: item for item in report["nodes"]}
    assert by_node["network"]["evidence"]["elements"]["pending_navigation"] == 1
    assert by_node["bluetooth"]["evidence"]["elements"]["pending_navigation"] == 0
    consistency_codes = {
        item["code"] for item in report["findings"]
        if item["code"] in {
            "visited_control_without_outcome", "outcome_control_marked_unvisited"
        }
    }
    assert not consistency_codes


def test_homogeneous_group_aliases_are_explained_by_pending_representative() -> None:
    graph = {
        "nodes": [{
            "state_id": "background",
            "page_name": "Background",
            "elements": [
                {
                    "id": 1, "name": "Wallpaper A", "category": "navigation",
                    "el_type": "link", "group": "wallpaper", "visited": False,
                },
                {
                    "id": 2, "name": "Wallpaper B", "category": "navigation",
                    "el_type": "link", "group": "wallpaper", "visited": True,
                },
            ],
        }],
        "edges": [],
    }
    report = GraphQualityAgent().evaluate_data(graph)
    findings = report["findings"]
    assert any(item["code"] == "node_exploration_incomplete" for item in findings)
    assert not any(
        item["code"] == "visited_control_without_outcome" for item in findings
    )

    graph["nodes"][0]["elements"][0]["visited"] = True
    report = GraphQualityAgent().evaluate_data(graph)
    assert any(
        item["code"] == "visited_control_without_outcome"
        for item in report["findings"]
    )


def test_stateful_probe_requires_committed_inverse() -> None:
    graph = {
        "nodes": [
            {"state_id": "off", "page_name": "Bluetooth", "elements": [{
                "id": 1, "name": "Bluetooth master switch",
                "category": "navigation", "el_type": "toggle", "visited": True,
                "stateful": True, "state_key": "bluetooth", "state_value": "off",
                "effect_scope": "function_set", "reversible": True, "risk": "none",
            }]},
            {"state_id": "on", "page_name": "Bluetooth", "elements": [{
                "id": 1, "name": "Bluetooth master switch",
                "category": "navigation", "el_type": "toggle", "visited": False,
                "stateful": True, "state_key": "bluetooth", "state_value": "on",
                "effect_scope": "function_set", "reversible": True, "risk": "none",
            }]},
        ],
        "edges": [{
            "source": "off", "target": "on", "element_id": "1",
            "element_label": "Set bluetooth on",
            "transition_kind": "stateful_surface", "landing_verified": True,
        }],
        "transition_events": [{
            "action_index": 1, "source": "off", "target": "on",
            "element_id": "1", "element_label": "Set bluetooth on",
            "outcome": "transitioned_consistent", "committed": True,
            "evidence": {
                "stateful": True, "mutation_id": "m1", "purpose": "probe",
                "state_key": "bluetooth", "before_value": "off", "after_value": "on",
            },
        }],
    }
    report = GraphQualityAgent().evaluate_data(graph)
    codes = {item["code"] for item in report["findings"]}
    assert "stateful_mutation_unrestored" in codes
    assert "edge_element_label_mismatch" not in codes

    graph["transition_events"].append({
        "action_index": 2, "source": "on", "target": "off",
        "element_id": "1", "element_label": "Set bluetooth off",
        "outcome": "transitioned_consistent", "committed": True,
        "evidence": {
            "stateful": True, "mutation_id": "m1", "purpose": "restore",
            "state_key": "bluetooth", "before_value": "on", "after_value": "off",
        },
    })
    report = GraphQualityAgent().evaluate_data(graph)
    assert not any(
        item["code"] == "stateful_mutation_unrestored"
        for item in report["findings"]
    )


def main() -> int:
    test_rules_vlm_contract_and_read_only_report()
    test_complete_ledger_and_high_confidence_semantic_override()
    test_missing_ledger_exposes_digraph_history_loss()
    test_unlock_edge_must_clear_permission_gate()
    test_legacy_permission_context_is_warning_not_false_error()
    test_selected_blocked_and_terminal_controls_are_not_pending_coverage()
    test_visited_flags_must_agree_with_action_outcomes()
    test_shared_region_outcomes_and_selected_peer_count_once_globally()
    test_homogeneous_group_aliases_are_explained_by_pending_representative()
    test_stateful_probe_requires_committed_inverse()
    print("PASS: read-only graph quality rules + structured VLM judge + action ledger audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
