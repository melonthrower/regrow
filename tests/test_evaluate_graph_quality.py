"""Offline checks for the graph quality evaluator."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.evaluate_graph_quality import evaluate, main


def test_report_flags_visual_and_landing_problems() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        image = root / "desktop.png"
        Image.new("RGB", (1920, 1080), "white").save(image)
        graph = root / "graph.json"
        graph.write_text(json.dumps({
            "app_name": "setting", "stop_reason": "frontier_empty",
            "nodes": [
                {"state_id": "root", "action_path_from_root": [],
                 "page_name": "Settings", "screenshot_path": str(image),
                 "elements": [{"id": 1, "name": "Displays", "category": "navigation",
                               "el_type": "link", "visited": True, "region": "sidebar"}]},
                {"state_id": "target", "action_path_from_root": [{"action_type": "CLICK"}],
                 "page_name": "Desktop", "screenshot_path": str(image), "elements": []},
            ],
            "edges": [{"source": "root", "target": "target", "element_id": "1",
                       "element_label": "Displays", "region": "sidebar",
                       "landing_verified": True, "effect_verdict": "transitioned_consistent",
                       "target_page_name": "Displays"}],
        }), encoding="utf-8")
        report = evaluate(graph, root)
        codes = {item["code"] for item in report["findings"]}
        assert {"suspicious_screen_text", "duplicate_visual_evidence",
                "landing_page_name_mismatch"} <= codes
        assert report["summary"]["screenshots"] == 2


def test_invalid_graph_fails_cleanly() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        graph = Path(temporary) / "bad.json"
        graph.write_text("{invalid", encoding="utf-8")
        report = evaluate(graph)
        assert report["status"] == "error"
        assert report["findings"][0]["code"] == "invalid_json"


def main_test() -> int:
    test_report_flags_visual_and_landing_problems()
    test_invalid_graph_fails_cleanly()
    print("PASS graph quality evaluator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_test())
