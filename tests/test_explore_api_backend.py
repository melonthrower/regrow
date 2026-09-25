from pathlib import Path
import json
import sys
from types import SimpleNamespace

import pytest
import requests

from .explore_fixtures import _png

from gui_rewalk import run_visual_traversal as traversal_entry
from gui_rewalk.run_visual_traversal import parse_args
from gui_rewalk.src.core.explore.api_config import (
    ExploreAPIConfig,
    load_explore_api_config,
    local_explore_api_config_path,
)
from gui_rewalk.src.core.explore.agent import OpenAIAPIExplorerAgent
from gui_rewalk.src.core.explore.runtime import _build_explorer_agent


def _write_config(path: Path, *, api_key: str = "plain-local-key") -> None:
    path.write_text(
        "version: 1\n"
        "explore_api:\n"
        "  base_url: https://example.test/v1\n"
        f"  api_key: {api_key!r}\n"
        "  model: gpt-5.6-luna\n"
        "  reasoning_effort: medium\n"
        "  timeout_seconds: 300\n",
        encoding="utf-8",
    )


def test_load_explore_api_config_accepts_version_one_yaml(tmp_path):
    path = tmp_path / ".guiwalk.local.yaml"
    _write_config(path)

    config = load_explore_api_config(path)

    assert config == ExploreAPIConfig(
        base_url="https://example.test/v1",
        api_key="plain-local-key",
        model="gpt-5.6-luna",
        reasoning_effort="medium",
        timeout_seconds=300,
    )


def test_load_explore_api_config_rejects_empty_key_without_echoing_yaml(
    tmp_path,
):
    path = tmp_path / ".guiwalk.local.yaml"
    _write_config(path, api_key="")

    with pytest.raises(ValueError, match="api_key") as caught:
        load_explore_api_config(path)

    assert "https://example.test/v1" not in str(caught.value)


def test_load_explore_api_config_requires_https(tmp_path):
    path = tmp_path / ".guiwalk.local.yaml"
    _write_config(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "https://example.test/v1", "http://example.test/v1"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="HTTPS"):
        load_explore_api_config(path)


def test_local_explore_api_config_path_is_repository_root():
    expected = Path(__file__).resolve().parents[1] / ".guiwalk.local.yaml"

    assert local_explore_api_config_path() == expected


def test_modular_explore_cli_accepts_openai_api(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "run_visual_traversal.py",
        "--modular-explore",
        "--explore-backend", "openai_api",
    ])

    assert parse_args().explore_backend == "openai_api"


def test_openai_api_preflight_finishes_before_live_setup_on_invalid_config(
    tmp_path, monkeypatch,
):
    path = tmp_path / ".guiwalk.local.yaml"
    _write_config(path, api_key="")
    monkeypatch.setattr(sys, "argv", [
        "run_visual_traversal.py",
        "--modular-explore",
        "--explore-backend", "openai_api",
        "--no_live_monitor",
    ])
    monkeypatch.setattr(
        traversal_entry, "local_explore_api_config_path", lambda: path)
    calls = []
    monkeypatch.setattr(
        traversal_entry, "setup_live_monitor",
        lambda _args: calls.append("live_setup"),
    )
    monkeypatch.setattr(
        traversal_entry, "run_full", lambda _args: calls.append("run_full"))

    assert traversal_entry.main() == 2
    assert calls == []


def test_openai_api_preflight_passes_validated_config_to_run_full(
    tmp_path, monkeypatch,
):
    path = tmp_path / ".guiwalk.local.yaml"
    _write_config(path)
    monkeypatch.setattr(sys, "argv", [
        "run_visual_traversal.py",
        "--modular-explore",
        "--explore-backend", "openai_api",
        "--no_live_monitor",
    ])
    monkeypatch.setattr(
        traversal_entry, "local_explore_api_config_path", lambda: path)
    captured = []
    monkeypatch.setattr(traversal_entry, "setup_live_monitor", lambda _args: None)
    monkeypatch.setattr(
        traversal_entry, "run_full",
        lambda args: captured.append(args) or 17,
    )

    assert traversal_entry.main() == 17
    assert captured[0]._explore_api_config.model == "gpt-5.6-luna"
    assert captured[0]._explore_api_config.api_key == "plain-local-key"


def test_run_full_rejects_unvalidated_openai_config_before_agent_setup():
    args = SimpleNamespace(
        modular_explore=True,
        explore_backend="openai_api",
    )

    assert traversal_entry.run_full(args) == 2


def _main_turn_payload():
    return {
        "app_scope": "target_app",
        "strategy": "先完成当前页面清点。",
        "screen": {
            "identity": "new_page",
            "page_ref": "",
            "page_name": "Stopwatch",
            "page_summary": "秒表功能页面",
            "state_ref": "",
            "state_name": "初始状态",
            "state_summary": "秒表尚未启动",
        },
        "previous_action": None,
        "representative_probe": None,
        "page_report": {
            "regions": [{
                "region_ref": "",
                "name": "秒表显示",
                "summary": "显示当前计时结果",
                "memory": "秒表显示区尚未启动，当前没有计时结果。",
                "elements": [],
                "region_operations": [],
            }],
            "survey_complete": True,
            "coverage_note": "当前完整视图无需滚动。",
        },
        "action": None,
        "finish": False,
        "reason": "完整截图显示全部稳定功能区。",
    }


class _FakeResponse:
    def __init__(self, body, *, status_code=200, error=None):
        self._body = body
        self.status_code = status_code
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return self._body


def test_openai_api_agent_sends_image_strict_schema_and_records_usage(
    tmp_path, monkeypatch,
):
    captured = {}
    response_body = {
        "model": "gpt-5.6-luna-2026-08-01",
        "output": [{
            "type": "message",
            "content": [{
                "type": "output_text",
                "text": json.dumps(_main_turn_payload(), ensure_ascii=False),
            }],
        }],
        "usage": {
            "input_tokens": 120,
            "input_tokens_details": {"cached_tokens": 80},
            "output_tokens": 30,
            "output_tokens_details": {"reasoning_tokens": 12},
            "total_tokens": 150,
        },
    }

    def _post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return _FakeResponse(response_body)

    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.agent.requests.post", _post)
    screenshot = _png("navy")
    agent = OpenAIAPIExplorerAgent(
        base_url="https://example.test/v1",
        api_key="plain-local-key",
        model="gpt-5.6-luna",
        reasoning_effort="medium",
        timeout=300,
        output_root=str(tmp_path),
    )

    turn = agent.decide(
        context={"target_app": "clock"},
        screenshots=[screenshot],
        has_pending_action=False,
    )

    assert turn.screen.page_name == "Stopwatch"
    assert captured["url"] == "https://example.test/v1/responses"
    assert captured["timeout"] == 300
    assert captured["headers"]["Authorization"] == "Bearer plain-local-key"
    payload = captured["json"]
    assert payload["model"] == "gpt-5.6-luna"
    assert payload["reasoning"] == {"effort": "medium"}
    assert payload["store"] is False
    assert payload["input"][0]["content"][0]["type"] == "input_text"
    assert payload["input"][0]["content"][1]["type"] == "input_image"
    assert payload["input"][0]["content"][1]["image_url"].startswith(
        "data:image/png;base64,")
    response_format = payload["text"]["format"]
    assert response_format["type"] == "json_schema"
    assert response_format["name"] == "modular_main_agent"
    assert response_format["strict"] is True
    strict_previous = response_format["schema"]["properties"][
        "previous_action"]["anyOf"][0]
    assert strict_previous["required"] == [
        "attempt_ref", "element_actions", "region_actions",
        "function_info", "parameter_info", "representative_same_kind", "region_effects", "reason",
    ]
    assert "task_result" not in strict_previous["properties"]

    debug_text = (tmp_path / "_modular_debug.jsonl").read_text(
        encoding="utf-8")
    assert "plain-local-key" not in debug_text
    debug = json.loads(debug_text.splitlines()[-1])
    assert debug["backend"] == "openai_api"
    assert debug["model"] == "gpt-5.6-luna"
    assert debug["effective_model"] == "gpt-5.6-luna-2026-08-01"
    assert debug["prompt_tokens"] == 120
    assert debug["completion_tokens"] == 30
    assert debug["prompt_tokens_details"] == {"cached_tokens": 80}


def test_openai_api_agent_redacts_key_from_http_errors(tmp_path, monkeypatch):
    def _post(_url, **_kwargs):
        return _FakeResponse(
            {}, status_code=401,
            error=requests.HTTPError(
                "Bearer plain-local-key was rejected"),
        )

    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.agent.requests.post", _post)
    agent = OpenAIAPIExplorerAgent(
        base_url="https://example.test/v1",
        api_key="plain-local-key",
        model="gpt-5.6-luna",
        reasoning_effort="medium",
        timeout=300,
        output_root=str(tmp_path),
    )

    with pytest.raises(RuntimeError, match="HTTP 401") as caught:
        agent.invoke_specialist(
            tool_name="probe",
            prompt="probe",
            screenshots=[],
            response_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            system_prompt="Return the value.",
        )

    assert "plain-local-key" not in str(caught.value)


def test_openai_api_agent_retries_one_connection_error(tmp_path, monkeypatch):
    calls = []
    response_body = {
        "model": "gpt-5.6-luna",
        "output": [{
            "type": "message",
            "content": [{
                "type": "output_text",
                "text": json.dumps(_main_turn_payload(), ensure_ascii=False),
            }],
        }],
        "usage": {"input_tokens": 20, "output_tokens": 5},
    }

    def _post(_url, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise requests.ConnectionError("temporary disconnect")
        return _FakeResponse(response_body)

    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.agent.requests.post", _post)
    agent = OpenAIAPIExplorerAgent(
        base_url="https://example.test/v1",
        api_key="plain-local-key",
        model="gpt-5.6-luna",
        reasoning_effort="medium",
        output_root=str(tmp_path),
    )

    turn = agent.decide(
        context={"target_app": "clock"},
        screenshots=[_png("navy")],
        has_pending_action=False,
    )

    assert turn.screen.page_name == "Stopwatch"
    assert len(calls) == 2


def test_modular_runtime_builds_openai_api_agent_from_validated_config(tmp_path):
    config = ExploreAPIConfig(
        base_url="https://example.test/v1",
        api_key="plain-local-key",
        model="gpt-5.6-luna",
        reasoning_effort="medium",
        timeout_seconds=300,
    )

    agent = _build_explorer_agent(
        backend="openai_api",
        transport_agent=None,
        model="ignored-cli-default",
        output_root=str(tmp_path),
        api_config=config,
    )

    assert isinstance(agent, OpenAIAPIExplorerAgent)
    assert agent.model == "gpt-5.6-luna"
