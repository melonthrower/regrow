"""Focused contracts for safe autonomous-model retry feedback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gui_rewalk.src.core.visual_traversal.runtime.autonomous_prompt import (
    _invalid_turn_correction,
    _model_retry_correction,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_qwen import (
    QwenAutonomousAgent,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_protocol import (
    available_tool_catalog,
)


class _Transport:
    def __init__(self, responses=(), *, error: Exception | None = None) -> None:
        self.responses = list(responses)
        self.error = error
        self.prompts = []

    def predict_mm_with_policy(self, prompt, images, **_kwargs):
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0), 1, 1, 1

    @staticmethod
    def parse_json(raw):
        return json.loads(raw)


def _valid_page_turn() -> str:
    return json.dumps({
        "screen": {"name": "Home", "identity": "new"},
        "reason": "The visible surface is the new Home Page.",
        "action": None,
    })


def test_qwen_retry_preserves_specific_safe_contract_feedback(tmp_path) -> None:
    first = json.dumps({
        "screen": {
            "name": "Home",
            "identity": "new",
            "frame_id": "secret-frame-id",
        },
        "reason": "The visible surface is the new Home Page.",
        "action": None,
    })
    transport = _Transport([first, _valid_page_turn()])
    agent = QwenAutonomousAgent("qwen-fixture", str(tmp_path), transport)
    catalog = available_tool_catalog(pending_identity=False)

    turn = agent.decide(
        b"screenshot",
        [],
        app_name="fixture",
        platform="local_html",
        exploration_map={"task": {"phase": "identify_page"}},
        tool_catalog=catalog,
    )

    assert turn is not None
    assert len(transport.prompts) == 2
    retry_prompt = transport.prompts[1]
    assert "page stage screen has unsupported fields" in retry_prompt
    assert "只修正这个字段或当前阶段要求" in retry_prompt
    assert "secret-frame-id" not in retry_prompt
    assert "重新检查本轮必填内容" not in retry_prompt
    debug = [
        json.loads(line)
        for line in Path(tmp_path, "_autonomous_debug.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert debug[0]["error_kind"] == "contract"


def test_qwen_backend_detail_is_debug_only_and_classified(tmp_path) -> None:
    transport = _Transport(
        error=RuntimeError(
            "transport endpoint=https://private.invalid/x "
            "frame_hash=secret backend detail"))
    agent = QwenAutonomousAgent("qwen-fixture", str(tmp_path), transport)
    catalog = available_tool_catalog(pending_identity=False)

    result = agent.decide(
        b"screenshot",
        [],
        app_name="fixture",
        platform="local_html",
        tool_catalog=catalog,
    )

    assert result is None
    assert len(transport.prompts) == 2
    assert "private.invalid" not in transport.prompts[1]
    assert "frame_hash" not in transport.prompts[1]
    assert "重新检查本轮必填内容" in transport.prompts[1]
    assert "private.invalid" not in agent.last_error
    debug = [
        json.loads(line)
        for line in Path(tmp_path, "_autonomous_debug.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert all(item["error_kind"] == "backend" for item in debug)
    assert "private.invalid" in debug[0]["error"]


@pytest.mark.parametrize(("bad_response", "expected_feedback", "secret"), [
    (
        "not-json secret-envelope-1",
        "response must contain one valid JSON object",
        "secret-envelope-1",
    ),
    (
        '["secret-envelope-2"]',
        "response must be a JSON object",
        "secret-envelope-2",
    ),
    ("null", "response must be a JSON object", ""),
])
def test_qwen_invalid_json_receives_specific_envelope_feedback(
    tmp_path,
    bad_response,
    expected_feedback,
    secret,
) -> None:
    transport = _Transport([bad_response, _valid_page_turn()])
    agent = QwenAutonomousAgent("qwen-fixture", str(tmp_path), transport)

    turn = agent.decide(
        b"screenshot",
        [],
        app_name="fixture",
        platform="local_html",
        exploration_map={"task": {"phase": "identify_page"}},
        tool_catalog=available_tool_catalog(pending_identity=False),
    )

    assert turn is not None
    assert expected_feedback in transport.prompts[1]
    if secret:
        assert secret not in transport.prompts[1]
    debug = [
        json.loads(line)
        for line in Path(tmp_path, "_autonomous_debug.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert debug[0]["error_kind"] == "contract"
    assert debug[0]["raw_response"] == bad_response


def test_invalid_turn_correction_uses_safe_model_error() -> None:
    safe_error = _model_retry_correction(
        "action.tool_arguments must be an object",
        contract_error=True,
    )
    correction = _invalid_turn_correction(
        model_error=safe_error,
        model_error_kind="contract",
    )

    assert "action.tool_arguments" in correction
    assert "factual reason" in correction
    assert "重新查看截图" not in correction
    assert _model_retry_correction(
        "previous_action.business_effect requires outcome=changed",
        contract_error=True,
    ) != _model_retry_correction("backend endpoint secret")


def test_qwen_contract_feedback_survives_outer_projection(tmp_path) -> None:
    invalid = json.dumps({
        "screen": {
            "name": "Home",
            "identity": "new",
            "frame_id": "secret-frame-value",
        },
        "reason": "The visible surface is the new Home Page.",
        "action": None,
    })
    agent = QwenAutonomousAgent(
        "qwen-fixture",
        str(tmp_path),
        _Transport([invalid, invalid]),
    )

    turn = agent.decide(
        b"screenshot",
        [],
        app_name="fixture",
        platform="local_html",
        exploration_map={"task": {"phase": "identify_page"}},
        tool_catalog=available_tool_catalog(pending_identity=False),
    )
    correction = _invalid_turn_correction(
        model_error=agent.last_error,
        model_error_kind=agent.last_error_kind,
    )

    assert turn is None
    assert agent.last_error_kind == "contract"
    assert "page stage screen has unsupported fields" in correction
    assert "secret-frame-value" not in correction


def test_backend_cannot_spoof_safe_contract_feedback_prefix() -> None:
    backend_error = "上一份回复违反了当前响应合同：secret backend detail"

    correction = _invalid_turn_correction(
        model_error=backend_error,
        model_error_kind="backend",
    )

    assert "secret backend detail" not in correction
    assert "Return one valid turn" in correction
