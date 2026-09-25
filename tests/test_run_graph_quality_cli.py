"""Offline tests for the formal graph-quality CLI entry point."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.run_graph_quality import main  # noqa: E402


def _graph(root: Path, *, complete: bool = True) -> Path:
    screenshot = root / "page.png"
    Image.new("RGB", (640, 480), "white").save(screenshot)
    elements = [
        {
            "id": 1,
            "name": "Bluetooth",
            "category": "navigation",
            "el_type": "link",
            "interactive": True,
            "visited": complete,
            "region": "content",
        }
    ]
    path = root / "graph.json"
    path.write_text(
        json.dumps(
            {
                "app_name": "settings",
                "stop_reason": "frontier_empty" if complete else "max_actions",
                "action_counter": 0,
                "transition_events": [],
                "nodes": [
                    {
                        "state_id": "root",
                        "page_name": "Bluetooth",
                        "screenshot_path": str(screenshot),
                        "elements": elements,
                        "action_path_from_root": [],
                    }
                ],
                "edges": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


class _FakeAgent:
    instances: list["_FakeAgent"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.prompts: list[str] = []
        self.image_counts: list[int] = []
        self.__class__.instances.append(self)

    def predict_mm(self, prompt: str, images: list[Any]):
        self.prompts.append(prompt)
        self.image_counts.append(len(images))
        return (
            json.dumps(
                {
                    "correctness": "correct",
                    "coverage_status": "verified",
                    "confidence": 0.95,
                    "reasons": ["page and function agree"],
                    "evidence": ["Bluetooth control is visible"],
                }
            ),
            11,
            7,
            1,
        )

    @staticmethod
    def parse_json(response: str):
        return json.loads(response)


def test_rules_only_writes_report_and_keeps_source_unchanged() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        graph = _graph(root)
        before = graph.read_bytes()
        report_path = root / "audit" / "quality.json"
        code = main(["--graph-path", str(graph), "--json-out", str(report_path)])
        assert code == 0
        assert graph.read_bytes() == before
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["read_only"] is True
        assert report["evaluation"]["mode"] == "rules-only"
        assert report["evaluation"]["model"] is None
        assert "vlm_usage" not in report


def test_default_report_path_and_fail_on() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        graph = _graph(root, complete=False)
        code = main([str(graph), "--fail-on", "warning"])
        assert code == 1
        report_path = root / "graph.quality.json"
        assert report_path.is_file()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["status"] in {"warn", "error"}
        assert graph.is_file()


def test_vlm_mode_uses_injected_agent_and_environment_configuration() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        graph = _graph(root)
        report_path = root / "vlm-quality.json"
        env = {
            "QUALITY_TEST_KEY": "not-a-real-key",
            "GUIWALK_GRAPH_QUALITY_MODEL": "TestModel",
            "GUIWALK_GRAPH_QUALITY_MODEL_VERSION": "test-version",
        }
        _FakeAgent.instances.clear()
        code = main(
            [
                str(graph),
                "--json-out",
                str(report_path),
                "--use-vlm",
                "--dashscope-api-key-env",
                "QUALITY_TEST_KEY",
                "--temperature",
                "0.1",
            ],
            agent_factory=_FakeAgent,
            environ=env,
        )
        assert code == 0
        assert len(_FakeAgent.instances) == 1
        fake = _FakeAgent.instances[0]
        assert fake.kwargs["model"] == "TestModel"
        assert fake.kwargs["model_version"] == "test-version"
        assert "use_ark" not in fake.kwargs
        assert fake.kwargs["temperature"] == 0.1
        assert fake.image_counts == [1]
        assert "response_schema" in fake.prompts[0]
        assert "not-a-real-key" not in fake.prompts[0]

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["evaluation"]["mode"] == "rules+vlm"
        assert report["evaluation"]["model_version"] == "test-version"
        assert report["vlm_usage"] == {
            "calls": 1,
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "transport_attempts": 1,
        }
        assert report["nodes"][0]["vlm_evaluation"]["accepted"] is True
        assert "DASHSCOPE_API_KEY" not in os.environ or os.environ["DASHSCOPE_API_KEY"] != "not-a-real-key"


def test_invalid_json_fails_but_still_writes_report() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        graph = root / "graph.json"
        graph.write_text("{invalid", encoding="utf-8")
        report_path = root / "quality.json"
        code = main([str(graph), "--json-out", str(report_path)])
        assert code == 1
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["findings"][0]["code"] == "invalid_graph_json"
        assert graph.read_text(encoding="utf-8") == "{invalid"


def test_vlm_mode_refuses_to_construct_client_without_credentials() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        graph = _graph(Path(temporary))
        _FakeAgent.instances.clear()
        try:
            main(
                [
                    str(graph),
                    "--use-vlm",
                    "--model",
                    "TestModel",
                    "--model-version",
                    "test-version",
                ],
                agent_factory=_FakeAgent,
                environ={},
            )
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("CLI created a VLM client without credentials")
        assert _FakeAgent.instances == []


def test_source_graph_cannot_be_report_destination() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        graph = _graph(Path(temporary))
        try:
            main([str(graph), "--json-out", str(graph)])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("CLI allowed report to overwrite source graph")


def main_test() -> int:
    test_rules_only_writes_report_and_keeps_source_unchanged()
    test_default_report_path_and_fail_on()
    test_vlm_mode_uses_injected_agent_and_environment_configuration()
    test_invalid_json_fails_but_still_writes_report()
    test_vlm_mode_refuses_to_construct_client_without_credentials()
    test_source_graph_cannot_be_report_destination()
    print("PASS: graph quality CLI rules-only/VLM injection/fail-on/read-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_test())
