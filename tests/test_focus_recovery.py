"""Offline regression for bounded recovery from an unobservable screen."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

from gui_rewalk.src.core.visual_traversal.visual_engine import (
    VisualTraversalEngine,
)


class _Environment:
    def __init__(self) -> None:
        self.steps: list[Dict[str, Any]] = []

    def step(
        self, action: Dict[str, Any], pause: float = 0.0,
    ) -> Dict[str, Any]:
        del pause
        self.steps.append(action)
        return {"screenshot": b"restored"}


def test_missing_screenshot_uses_back_recovery_before_failing() -> None:
    engine = object.__new__(VisualTraversalEngine)
    engine.app_name = "offline-app"
    engine.focus_guard = object()
    engine.relaunch_fn = lambda: (_ for _ in ()).throw(
        AssertionError("BACK recovery should avoid relaunch"))
    engine._is_touch = True
    engine._settle_enabled = False
    engine._relaunch_attempts = 0
    engine._action_count = 0
    engine._is_target_app_foreground = lambda _shot: True
    engine.review_debug = SimpleNamespace(
        record_event=lambda *_args, **_kwargs: None)
    engine.env = _Environment()

    obs, relaunched, on_app = VisualTraversalEngine._ensure_on_app(
        engine, {"screenshot": None})

    assert obs == {"screenshot": b"restored"}
    assert relaunched is False
    assert on_app is True
    assert engine._last_off_app_recovered_by_back is True
    assert engine._last_off_app_kind == "screenshot_unavailable"
    assert engine._terminal_off_app_outcome(
        engine._last_off_app_kind) == "unobservable_surface"
    assert engine.env.steps == [{"action_type": "navigate_back"}]
