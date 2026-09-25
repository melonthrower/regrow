"""Offline --help and configuration checks for the M13 entry point."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.run_visual_collection import (  # noqa: E402
    _build_collection_model_agent,
    _load_collection_perception_models,
    build_parser,
    execute_prepared,
    main,
    prepare_collection,
)
from gui_rewalk.src.core.graph.state_graph import StateGraph  # noqa: E402


def _fixture(root: Path) -> tuple[Path, Path, Path]:
    graph_path = root / "graph.json"
    graph = StateGraph("settings")
    graph.graph.add_node(
        "n1",
        state_type="visual",
        page_id="p1",
        page_name="Bluetooth",
        screenshot_path="C:/remote/run/screenshots/frame_00001.png",
    )
    graph.save(str(graph_path))

    node_dir = root / "nodes"
    screenshot = node_dir / "screenshots" / "frame_00001.png"
    screenshot.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), "white").save(screenshot)
    artifact = node_dir / "n1" / "page_capabilities.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps({
        "app_id": "settings",
        "node_id": "n1",
        "page_name": "Bluetooth",
        "capabilities": [{
            "capability_id": "toggle-bluetooth",
            "name": "Toggle Bluetooth",
            "target_node": "n1",
            "elements": ["7"],
            "param": {"type": "boolean", "slot": "enabled"},
            "success_predicate": "Bluetooth switch shows the requested state",
            "action_steps": 1,
        }],
    }), encoding="utf-8")

    instruction = root / "instruction.json"
    instruction.write_text(json.dumps({
        "instruction_id": "M13-CLI",
        "instruction": "Turn Bluetooth on",
        "apps_involved": ["settings"],
        "fixed_order": True,
        "capability_refs": [{
            "ref_id": "r1",
            "app_id": "settings",
            "capability_id": "toggle-bluetooth",
            "params": {"enabled": True},
            "desired_outcome": True,
        }],
    }), encoding="utf-8")
    return graph_path, node_dir, instruction


def main_test() -> int:
    entry = ROOT / "gui_rewalk" / "run_visual_collection.py"
    help_run = subprocess.run(
        [sys.executable, str(entry), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert help_run.returncode == 0, help_run.stderr
    assert "APP_ID=GRAPH_JSON" in help_run.stdout
    assert "--validate-only" in help_run.stdout
    assert "--model-backend" in help_run.stdout

    with tempfile.TemporaryDirectory() as temporary:
        graph_path, node_dir, instruction = _fixture(Path(temporary))
        argv = [
            "--instruction", str(instruction),
            "--graph", f"settings={graph_path}",
            "--node-dir", f"settings={node_dir}",
            "--launch-name", "settings=gnome-settings",
            "--validate-only",
        ]
        args = build_parser().parse_args(argv)
        assert args.model_backend == "qwen_api"
        luna_args = build_parser().parse_args([
            *argv,
            "--model-backend", "codex_cli",
            "--model-version", "gpt-5.6-luna",
        ])
        assert luna_args.model_backend == "codex_cli"
        assert luna_args.model_version == "gpt-5.6-luna"
        luna_args.output_root = str(Path(temporary) / "luna-output")
        luna_args.vlm_grounding = True
        assert _build_collection_model_agent(
            luna_args).__class__.__name__ == "CodexGUIGenAgent"
        assert _load_collection_perception_models(luna_args) == (None, None)
        prepared = prepare_collection(args)
        assert set(prepared.app_graphs) == {"settings"}
        assert prepared.launch_names["settings"] == "gnome-settings"
        assert prepared.capability_count == 1
        assert prepared.app_graphs["settings"].graph.nodes["n1"][
            "screenshot_path"] == str(
                (node_dir / "screenshots" / "frame_00001.png").resolve())
        assert prepared.app_graphs["settings"].graph.nodes["n1"][
            "visual_fingerprint"]["phash"]
        ref = prepared.instruction["capability_refs"][0]
        assert ref["node_id"] == "n1"
        assert ref["target_node"] == "n1"
        assert ref["elements"] == ["7"]
        assert ref["params"] == {"enabled": True}
        assert ref["desired_outcome"] is True
        assert ref["source_path"].endswith("page_capabilities.json")
        assert main(argv) == 0

        class _ExplodingExecutor:
            def execute(self, *_args, **_kwargs):
                raise RuntimeError("synthetic execution failure")

        class _Prerequisites:
            action_events = ()

            def __init__(self):
                self.cleaned = False

            def cleanup(self):
                self.cleaned = True
                return type("Cleanup", (), {"to_dict": lambda self: {
                    "status": "nothing_to_clean", "gui_action_count": 0,
                }})()

        class _Runtime:
            def __init__(self):
                self.executor = _ExplodingExecutor()
                self.prerequisite_agent = _Prerequisites()
                self.closed = False

            def close(self):
                self.closed = True

        fake_runtime = _Runtime()
        try:
            execute_prepared(
                args,
                prepared,
                runtime_factory=lambda _args, _prepared: fake_runtime,
            )
        except RuntimeError as exc:
            assert "synthetic" in str(exc)
        else:
            raise AssertionError("executor exception must propagate fail-closed")
        assert fake_runtime.prerequisite_agent.cleaned
        assert fake_runtime.closed

        class _SuccessfulExecutor:
            def execute(self, instruction, **_kwargs):
                return {
                    "instruction_id": instruction["instruction_id"],
                    "instruction": instruction["instruction"],
                    "success": True,
                    "scenario_success": True,
                    "final_status": "complete",
                    "trajectory": [],
                    "total_action_steps": 0,
                    "cleanup_action_steps": 2,
                    "cleanup": {
                        "status": "complete", "gui_action_count": 2,
                        "results": [{"status": "cleaned"}],
                    },
                }

        successful_runtime = _Runtime()
        successful_runtime.executor = _SuccessfulExecutor()
        successful_runtime.prerequisite_agent.cleanup = lambda: type(
            "Cleanup", (), {"to_dict": lambda self: {
                "status": "already_clean", "gui_action_count": 0,
            }})()
        args.output_root = str(Path(temporary) / "collections")
        args.uid = "offline"
        success_result = execute_prepared(
            args,
            prepared,
            runtime_factory=lambda _args, _prepared: successful_runtime,
        )
        assert success_result["success"] is True
        assert success_result["final_status"] == "complete"
        assert success_result["cleanup_report"]["status"] == "complete"
        assert success_result["cleanup_action_steps"] == 2
        assert success_result["total_episode_action_steps"] == 2
        assert Path(success_result["episode_dir"]).is_dir()
        assert successful_runtime.closed

        broken = json.loads(instruction.read_text(encoding="utf-8"))
        broken["capability_refs"][0]["capability_id"] = "missing"
        instruction.write_text(json.dumps(broken), encoding="utf-8")
        try:
            prepare_collection(args)
        except ValueError as exc:
            assert "does not resolve" in str(exc)
        else:
            raise AssertionError("unknown capability must fail closed")

        broken["capability_refs"][0]["capability_id"] = "toggle-bluetooth"
        instruction.write_text(json.dumps(broken), encoding="utf-8")
        capability_path = node_dir / "n1" / "page_capabilities.json"
        unverified = json.loads(capability_path.read_text(encoding="utf-8"))
        unverified["capabilities"][0].update({
            "status": "discovered",
            "availability_status": "discovered",
        })
        capability_path.write_text(
            json.dumps(unverified), encoding="utf-8")
        prepared = prepare_collection(args)
        assert prepared.instruction["capability_refs"][0][
            "availability_status"] == "discovered"

    print("PASS M13 CLI offline config")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_test())
