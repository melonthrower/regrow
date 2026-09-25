from __future__ import annotations

import json
from types import SimpleNamespace

from gui_rewalk.run_visual_traversal import (
    write_autonomous_completion_report,
)


def test_autonomous_completion_report_fails_closed_with_runtime_gaps(
    tmp_path,
) -> None:
    graph = SimpleNamespace(
        stop_reason="max_actions",
        autonomous_completion_gaps=["Home: Region Main is incomplete"],
    )

    report = write_autonomous_completion_report(graph, str(tmp_path))

    assert report["status"] == "incomplete"
    assert report["traversal_status"] == "partial"
    assert report["bundle_status"] == "not_compiled"
    assert report["checks"]["framework_finished"]["passed"] is False
    assert report["checks"]["completion_gaps_empty"] == {
        "passed": False,
        "details": ["Home: Region Main is incomplete"],
    }
    persisted = json.loads(
        (tmp_path / "autonomous_completion.json").read_text(
            encoding="utf-8"))
    assert persisted == report


def test_autonomous_completion_report_accepts_closed_framework_finish(
    tmp_path,
) -> None:
    graph = SimpleNamespace(
        stop_reason="framework_complete",
        autonomous_completion_gaps=[],
        autonomous_collection_bundle={
            "annotated_graph_path": "annotated_graph.json",
            "capability_graph_path": "capability_graph.json",
            "capabilities": 2,
        },
    )

    report = write_autonomous_completion_report(graph, str(tmp_path))

    assert report["status"] == "ledger_closed"
    assert report["traversal_status"] == "complete"
    assert report["bundle_status"] == "compiled"
    assert all(
        check["passed"] is True
        for check in report["checks"].values()
    )
    assert report["collection_bundle"] == {
        "annotated_graph_path": "annotated_graph.json",
        "capability_graph_path": "capability_graph.json",
        "capabilities": 2,
    }


def test_partial_traversal_still_reports_a_compiled_bundle(tmp_path) -> None:
    graph = SimpleNamespace(
        stop_reason="max_actions",
        autonomous_completion_gaps=["Alarm: one Entry remains open"],
        autonomous_collection_bundle={
            "annotated_graph_path": "annotated_graph.json",
            "capability_graph_path": "capability_graph.json",
            "capabilities": 1,
        },
        autonomous_bundle_status="compiled",
    )

    report = write_autonomous_completion_report(graph, str(tmp_path))

    assert report["status"] == "incomplete"
    assert report["traversal_status"] == "partial"
    assert report["bundle_status"] == "compiled"
    assert report["checks"]["bundle_compiled"]["passed"] is True

