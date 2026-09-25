"""Offline tests for GraphQuality annotated screenshot evidence export."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.run_graph_quality import main  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_screenshot(path: Path, color: str, label: str) -> None:
    image = Image.new("RGB", (360, 260), color)
    draw = ImageDraw.Draw(image)
    draw.rectangle([20, 30, 100, 70], outline="black", width=2)
    draw.text((24, 42), label, fill="black")
    image.save(path)


def _quality_graph(root: Path) -> tuple[Path, Path, Path]:
    source_shot = root / "source.png"
    target_shot = root / "target.png"
    _write_screenshot(source_shot, "lightblue", "Bluetooth")
    _write_screenshot(target_shot, "lightgreen", "Bluetooth details")
    graph_path = root / "graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "graph_schema_version": 2,
                "app_name": "settings",
                "stop_reason": "frontier_empty",
                "action_counter": 1,
                "transition_events": [
                    {
                        "action_index": 1,
                        "source": "source",
                        "target": "target",
                        "outcome": "transitioned_consistent",
                        "committed": True,
                    }
                ],
                "nodes": [
                    {
                        "state_id": "source",
                        "page_name": "Settings",
                        "screenshot_path": str(source_shot),
                        "elements": [
                            {
                                "id": "bluetooth",
                                "name": "Bluetooth",
                                "category": "navigation",
                                "el_type": "link",
                                "interactive": True,
                                "visited": False,
                                "region": "content",
                                "bbox_xywh": [20, 30, 80, 40],
                                "center": [60, 50],
                                "region_bbox": [10, 10, 150, 120],
                            },
                            {
                                "id": "sound",
                                "name": "Sound",
                                "category": "navigation",
                                "el_type": "link",
                                "interactive": True,
                                "visited": False,
                                "region": "content",
                                "bbox_xywh": [20, 90, 80, 40],
                                "center": [60, 110],
                                "region_bbox": [10, 10, 150, 140],
                            }
                        ],
                        "action_path_from_root": [],
                    },
                    {
                        "state_id": "target",
                        "page_name": "Bluetooth",
                        "screenshot_path": str(target_shot),
                        "elements": [
                            {
                                "id": "toggle",
                                "name": "Bluetooth enabled",
                                "category": "control",
                                "el_type": "switch",
                                "interactive": True,
                                "visited": True,
                                "bbox_xywh": [200, 40, 100, 40],
                                "center": [250, 60],
                            }
                        ],
                        "action_path_from_root": [1],
                    },
                ],
                "edges": [
                    {
                        "source": "source",
                        "target": "target",
                        "action_index": 1,
                        "action_indices": [1],
                        "element_id": "bluetooth",
                        "element_label": "Bluetooth",
                        "semantic_description": "Open Bluetooth settings",
                        "target_page_name": "Bluetooth",
                        "effect_verdict": "transitioned_consistent",
                        "landing_verified": True,
                        "resolved_center": [300, 200],
                        "region_bbox": [10, 10, 150, 120],
                        "action": {
                            "action_type": "CLICK",
                            "parameters": {"x": 300, "y": 200, "button": "left"},
                        },
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return graph_path, source_shot, target_shot


def test_cli_exports_node_and_edge_annotations_without_mutating_sources() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        graph, source_shot, target_shot = _quality_graph(root)
        source_hashes = {
            path: _sha256(path) for path in (graph, source_shot, target_shot)
        }
        annotated = root / "evidence"
        report = root / "quality.json"
        code = main(
            [
                str(graph),
                "--json-out",
                str(report),
                "--annotated-dir",
                str(annotated),
            ]
        )
        assert code == 0
        assert all(_sha256(path) == digest for path, digest in source_hashes.items())

        manifest_path = annotated / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["source_graph_sha256"] == source_hashes[graph]
        assert manifest["generated_count"] >= 2
        entries = {item["code"]: item for item in manifest["findings"]}

        incomplete = entries["node_exploration_incomplete"]
        assert incomplete["status"] == "generated"
        assert any(item["kind"] == "unexplored_element" for item in incomplete["highlights"])

        bad_edge = entries["retarget_outside_region"]
        assert bad_edge["status"] == "generated"
        assert bad_edge["edge"]["source"] == "source"
        assert bad_edge["edge"]["target"] == "target"
        assert {item["kind"] for item in bad_edge["highlights"]} >= {
            "source_element_bbox",
            "region_bbox",
            "resolved_point",
        }
        edge_image_path = (annotated / bad_edge["image"]).resolve()
        edge_image_path.relative_to(annotated.resolve())
        with Image.open(edge_image_path) as edge_image:
            assert edge_image.width == 360 * 2 + 6
            assert edge_image.height > 260
            edge_image.verify()

        for entry in manifest["findings"]:
            if entry["status"] != "generated":
                continue
            image_path = (annotated / entry["image"]).resolve()
            image_path.relative_to(annotated.resolve())
            assert image_path.name == entry["image"]
            with Image.open(image_path) as image:
                image.verify()


def test_missing_screenshot_is_skipped_and_cli_does_not_crash() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        graph = root / "graph.json"
        graph.write_text(
            json.dumps(
                {
                    "app_name": "settings",
                    "action_counter": 0,
                    "transition_events": [],
                    "nodes": [
                        {
                            "state_id": "missing",
                            "page_name": "Missing evidence",
                            "screenshot_path": "not-present.png",
                            "elements": [],
                        }
                    ],
                    "edges": [],
                }
            ),
            encoding="utf-8",
        )
        before = _sha256(graph)
        annotated = root / "annotations"
        assert main([str(graph), "--annotated-dir", str(annotated)]) == 0
        assert _sha256(graph) == before
        manifest = json.loads((annotated / "manifest.json").read_text(encoding="utf-8"))
        missing = next(
            item for item in manifest["findings"] if item["code"] == "missing_screenshot"
        )
        assert missing["status"] == "skipped"
        assert missing["image"] is None
        assert missing["skip_reason"] == "referenced_screenshot_missing_or_unreadable"


def main_test() -> int:
    test_cli_exports_node_and_edge_annotations_without_mutating_sources()
    test_missing_screenshot_is_skipped_and_cli_does_not_crash()
    print("PASS: graph-quality annotated PNG/manifest export is read-only and resilient")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_test())
