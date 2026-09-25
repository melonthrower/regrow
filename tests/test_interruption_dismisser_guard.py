"""Offline regressions for fail-closed interruption dismissal."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.src.core.visual_traversal.visual_agents import (  # noqa: E402
    InterruptionDismisser,
)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    return buf.getvalue()


def _button(name: str):
    return SimpleNamespace(name=name, category="navigation", center=(4, 4))


def _decide(payload, button=None):
    button = button or _button("candidate")
    response = payload if isinstance(payload, str) else json.dumps(payload)
    with mock.patch(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        return_value=(response, None),
    ):
        return InterruptionDismisser(object()).decide(_png(), [button])


def test_normal_page_cta_is_not_dismissed() -> None:
    result = _decide({
        "action": "click",
        "surface_is_temporary": False,
        "target_is_close_control": False,
        "button_id": 0,
        "reason": "normal empty-state Add CTA",
    }, _button("Add World Clock"))
    assert result["action"] == "done"
    assert result["button"] is None


def test_notification_body_is_not_dismissed() -> None:
    result = _decide({
        "action": "click",
        "surface_is_temporary": True,
        "target_is_close_control": False,
        "button_id": 0,
        "reason": "notification body, not its close affordance",
    }, _button("Software Updates Available"))
    assert result["action"] == "done"
    assert result["button"] is None


def test_explicit_temporary_overlay_close_control_is_allowed() -> None:
    close = _button("overlay close")
    result = _decide({
        "action": "click",
        "surface_is_temporary": True,
        "target_is_close_control": True,
        "button_id": 0,
        "reason": "explicit close control on a temporary overlay",
    }, close)
    assert result["action"] == "click"
    assert result["button"] is close


def test_old_invalid_and_exceptional_responses_are_noops() -> None:
    old = _decide({"action": "click", "button_id": 0, "reason": "old format"})
    assert old["action"] == "done" and old["button"] is None

    invalid = _decide("not json")
    assert invalid["action"] == "done" and invalid["button"] is None

    with mock.patch(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        side_effect=RuntimeError("transport failed"),
    ):
        failed = InterruptionDismisser(object()).decide(_png(), [_button("close")])
    assert failed["action"] == "done" and failed["button"] is None


if __name__ == "__main__":
    test_normal_page_cta_is_not_dismissed()
    test_notification_body_is_not_dismissed()
    test_explicit_temporary_overlay_close_control_is_allowed()
    test_old_invalid_and_exceptional_responses_are_noops()
    print("interruption dismisser guard: 4 tests passed")
