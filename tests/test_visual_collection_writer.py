"""Offline contract checks for CollectionWriter.write_visual_episode."""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.src.core.scenario.collection_writer import CollectionWriter  # noqa: E402


def _png(colour: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 6), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        writer = CollectionWriter(
            temporary, "desktop", "20260711", "federated")
        result = {
            "instruction_id": "M13/path unsafe",
            "instruction": "enable a setting then create an alarm",
            "final_status": "complete",
            "scenario_success": True,
            "total_action_steps": 3,
            "num_action_events": 2,
            "app_switches": 1,
            "completed_refs": ["settings-toggle", "clock-create"],
            "failed_refs": [],
            "capability_refs": [{
                "ref_id": "settings-toggle", "app_id": "settings",
                "node_id": "n1",
            }],
            "ref_results": [{
                "ref_id": "settings-toggle", "committed": True,
                "verification": {"complete": True},
            }],
            "final_verification": {"complete": True, "reason": "visible"},
            "agent_audit": {
                "agent_failure": False,
                "quality_score": 1.0,
                "issues": [],
            },
            "graph_provenance": [{"graph_app_id": "settings"}],
            "trajectory": [
                {
                    "step": 0,
                    "kind": "graph_edge",
                    "app_id": "settings",
                    "action_steps": 1,
                    "action_spec": {"kind": "graph_edge", "raw": b"binary"},
                    "grounding": {"element_name": "Bluetooth"},
                    "observation_before": {"screenshot": _png((255, 0, 0))},
                    "observation_after": {"screenshot": _png((0, 255, 0))},
                    "context_node_id": "n0",
                    "arrived_node_id": "n1",
                    "committed": True,
                    "effect": {
                        "desired_outcome": False,
                        "observed_outcome": False,
                        "had_effect": True,
                    },
                    "graph_provenance": {
                        "kind": "graph_edge", "graph_app_id": "settings",
                    },
                },
                {
                    "step": 1,
                    "kind": "precondition",
                    "app_id": "clock",
                    "ref_id": "clock-create",
                    "requirement": {"kind": "resource", "fact": "alarm exists"},
                    "evidence": [{"code": "fixture_created"}],
                    "verification": {"complete": True},
                    "action_steps": 2,
                    "committed": True,
                },
            ],
        }
        episode = Path(writer.write_visual_episode(
            result,
            "uid/../../unsafe",
            instruction_meta={
                "apps_involved": ["settings", "clock"],
                "fixed_order": True,
                "runtime_slots": [],
                "params": {},
            },
        ))
        assert episode.parent == Path(writer.base) / "episodes"
        assert (episode / "screenshots" / "step000_before.png").is_file()
        assert (episode / "screenshots" / "step000_after.png").is_file()

        meta = json.loads((episode / "meta.json").read_text(encoding="utf-8"))
        assert meta["schema_version"] == "m13.visual_collection.v1"
        assert meta["total_action_steps"] == 3
        assert meta["apps_involved"] == ["settings", "clock"]
        assert meta["agent_audit"]["quality_score"] == 1.0
        payload = json.loads(
            (episode / "trajectory.json").read_text(encoding="utf-8"))
        assert payload["steps"][0]["frames"]["before"] == \
            "step000_before.png"
        assert payload["steps"][0]["action_spec"]["raw"] == \
            {"binary_bytes": 6}
        assert payload["steps"][0]["effect"]["desired_outcome"] is False
        assert payload["agent_audit"]["agent_failure"] is False
        assert "annotation" not in payload["steps"][0]
        assert "reverse_had_effect" not in payload["steps"][0]
        assert payload["steps"][1]["evidence"] == [{"code": "fixture_created"}]

        manifest = Path(writer.finalize())
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        assert manifest_data["num_episodes"] == 1
        assert manifest_data["episodes"][0]["total_action_steps"] == 3
    print("PASS M13 visual collection writer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
