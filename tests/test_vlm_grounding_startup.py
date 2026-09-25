"""Offline startup contract for the semantic-only inventory entry point."""

from __future__ import annotations

import sys

import pytest

from gui_rewalk import run_visual_traversal


def test_retired_inventory_entrypoints_are_absent() -> None:
    assert not hasattr(run_visual_traversal, "_build_perception")
    assert not hasattr(run_visual_traversal, "_select_inventory_mode")


def test_help_exposes_semantic_inventory_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["run_visual_traversal.py", "--help"])
    with pytest.raises(SystemExit) as exc:
        run_visual_traversal.parse_args()
    assert exc.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "only traversal inventory mode" in help_text
    assert "--vlm_grounding" not in help_text
    assert "--legacy_yolo_inventory" not in help_text
    assert "--ocr_model_path" not in help_text


@pytest.mark.parametrize(
    "flag", ["--vlm_grounding", "--legacy_yolo_inventory", "--ocr_model_path"])
def test_retired_inventory_flags_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
) -> None:
    monkeypatch.setattr(sys, "argv", ["run_visual_traversal.py", flag])
    with pytest.raises(SystemExit) as exc:
        run_visual_traversal.parse_args()
    assert exc.value.code == 2
