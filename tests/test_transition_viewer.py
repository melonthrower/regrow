import json

from PIL import Image

from tools.transition_viewer import (
    GroundingEvidence,
    Transition,
    TransitionViewerApp,
    _load_transitions_from_graph,
)


def test_graph_loader_preserves_parallel_action_edges(tmp_path):
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "edges": [
                    {
                        "source": "home",
                        "target": "docs",
                        "element_label": "Documents",
                    }
                ],
                "action_edges": [
                    {
                        "source": "home",
                        "target": "docs",
                        "element_id": "2",
                        "element_label": "Browse documents",
                        "action": {"action_type": "CLICK"},
                        "routing_verified": True,
                        "attempts": [
                            {
                                "action_index": 2,
                                "committed": True,
                                "landing_verified": True,
                            }
                        ],
                    },
                    {
                        "source": "home",
                        "target": "docs",
                        "element_id": "7",
                        "element_label": "Documents",
                        "action": {"action_type": "CLICK"},
                        "routing_verified": True,
                        "attempts": [
                            {
                                "action_index": 3,
                                "committed": True,
                                "landing_verified": True,
                            }
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    rows = _load_transitions_from_graph(graph_path)

    assert [(row.element_label, row.dst) for row in rows] == [
        ("Browse documents", "docs"),
        ("Documents", "docs"),
    ]


def test_element_rows_use_source_local_evidence_and_skip_non_gaps(tmp_path):
    state_dir = tmp_path / "home"
    state_dir.mkdir()
    (state_dir / "elements.json").write_text(
        json.dumps(
            [
                {"name": "Direct", "interactive": True, "category": "navigation"},
                {"name": "Grouped sibling", "interactive": True, "category": "navigation", "visited": True},
                {"name": "Cloud sync", "interactive": True, "category": "navigation", "enabled": False, "blocked_reason": "login_required"},
                {"name": "Home", "interactive": True, "category": "navigation", "selected": True},
                {"name": "Description", "interactive": True, "category": "display"},
                {"name": "Real gap", "interactive": True, "category": "navigation"},
            ]
        ),
        encoding="utf-8",
    )
    app = TransitionViewerApp.__new__(TransitionViewerApp)
    app.nodes_dir = tmp_path
    app.elements_cache = {}
    app.outgoing = {
        "home": [
            Transition(
                src="home",
                dst="docs",
                element_id="1",
                element_label="Direct",
                action={},
                action_index=1,
            )
        ]
    }

    rows = {row["name"]: row for row in app._element_rows("home")}

    assert rows["Direct"]["kind"] == "direct"
    assert rows["Grouped sibling"]["kind"] == "covered"
    assert rows["Cloud sync"]["kind"] == "skip"
    assert rows["Cloud sync"]["reason"] == "login_required"
    assert rows["Home"]["kind"] == "skip"
    assert rows["Description"]["kind"] == "skip"
    assert rows["Real gap"]["kind"] == "unexplored"


def test_grounding_evidence_recovers_region_lazy_element_box(tmp_path):
    state_dir = tmp_path / "home"
    state_dir.mkdir()
    (state_dir / "elements.json").write_text(
        json.dumps(
            [
                {
                    "id": 0,
                    "name": "Alarms",
                    "interactive": True,
                    "category": "navigation",
                    "bbox_xywh": [0, 0, 0, 0],
                    "center": [104, 52],
                    "region": "Mode Navigation",
                    "region_bbox": [10, 20, 200, 100],
                }
            ]
        ),
        encoding="utf-8",
    )
    app = TransitionViewerApp.__new__(TransitionViewerApp)
    app.nodes_dir = tmp_path
    app.elements_cache = {}
    app.outgoing = {}
    app.grounding_by_label = {
        "alarms": [
            GroundingEvidence(
                label="Alarms",
                bbox=(80, 30, 130, 72),
                click_point=(104, 52),
                state_id="",
                sequence=1,
            )
        ]
    }

    row = app._element_rows("home")[0]

    assert row["bbox"] == (80, 30, 130, 72)
    assert app._region_boxes("home", app._load_elements("home")) == {
        "Mode Navigation": (10, 20, 200, 100)
    }


def test_label_only_reverse_edge_is_visible_and_duplicates_are_counted(tmp_path):
    state_dir = tmp_path / "dialog"
    state_dir.mkdir()
    (state_dir / "elements.json").write_text("[]", encoding="utf-8")
    app = TransitionViewerApp.__new__(TransitionViewerApp)
    app.nodes_dir = tmp_path
    app.elements_cache = {}
    app.grounding_by_label = {
        "cancel": [
            GroundingEvidence(
                label="Cancel",
                bbox=(484, 174, 557, 205),
                click_point=(520, 190),
                state_id="dialog",
                sequence=1,
            )
        ]
    }
    app.outgoing = {
        "dialog": [
            Transition("dialog", "home", "", "Cancel", {}, 1),
            Transition("dialog", "home", "0", "Cancel", {}, 2),
        ]
    }

    rows = app._element_rows("dialog")

    assert len(rows) == 1
    assert rows[0]["kind"] == "direct"
    assert rows[0]["bbox"] == (484, 174, 557, 205)
    assert rows[0]["edge_count"] == 2
    assert "without a durable element" in rows[0]["reason"]


def test_grounding_loader_binds_exact_input_frame_to_state(tmp_path):
    nodes_dir = tmp_path / "node_artifacts"
    state_dir = nodes_dir / "dialog"
    state_dir.mkdir(parents=True)
    screenshot = state_dir / "screenshot.png"
    Image.new("RGB", (20, 20), (10, 20, 30)).save(screenshot)

    attempt_dir = tmp_path / "target_grounding_attempts" / "000001_cancel"
    attempt_dir.mkdir(parents=True)
    Image.open(screenshot).save(attempt_dir / "input.png")
    (attempt_dir / "result.json").write_text(
        json.dumps(
            {
                "sequence": 1,
                "outcome": "accepted",
                "target": {"name": "Cancel"},
                "grounded_geometry": {
                    "bbox_px_xywh": [4, 5, 6, 7],
                    "click_point_px": [7, 8],
                },
            }
        ),
        encoding="utf-8",
    )

    app = TransitionViewerApp.__new__(TransitionViewerApp)
    app.nodes_dir = nodes_dir
    app.node_index = {"dialog": {}}

    loaded = app._load_grounding_evidence()

    assert loaded["cancel"][0].state_id == "dialog"
    assert loaded["cancel"][0].bbox == (4, 5, 10, 12)
