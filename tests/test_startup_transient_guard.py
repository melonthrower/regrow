"""Offline startup and Page-identity interruption recovery contracts."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.src.core.visual_traversal.runtime.bootstrap import (  # noqa: E402
    bootstrap_traversal,
)
from gui_rewalk.src.core.visual_traversal.visual_engine import (  # noqa: E402
    VisualTraversalEngine,
)
from gui_rewalk.src.core.visual_traversal.visual_perception import (  # noqa: E402
    VisualElement,
)


def _element(name: str, *, interactive: bool) -> VisualElement:
    return VisualElement(
        id=0, name=name, bbox_xywh=[0, 0, 20, 20], center=[10, 10],
        el_type="button" if interactive else "image",
        interactive=interactive,
        category="navigation" if interactive else "display",
    )


class _Perception:
    use_semantic_inventory = True

    def __init__(self) -> None:
        self._cur_frame_bytes = None
        self.last_all_elements = []
        self.last_is_interruption = False
        self.calls = []

    def semantic_inventory(self, shot, *, force_refresh=False):
        self.calls.append((shot, force_refresh))
        self._cur_frame_bytes = shot
        if shot == b"splash":
            self.last_is_interruption = True
            self.last_all_elements = [_element("App logo", interactive=False)]
        else:
            self.last_is_interruption = False
            self.last_all_elements = [_element("More options", interactive=True)]
        return list(self.last_all_elements)


class _Dismisser:
    def decide(self, _shot, _elements):
        return {"action": "done", "button": None, "reason": "nothing safe to click"}


class _Review:
    def record_agent(self, *_args, **_kwargs):
        return None


class _Env:
    def __init__(self):
        self.captures = 0

    def _get_obs(self):
        self.captures += 1
        return {"screenshot": b"main"}


def test_passive_splash_waits_and_forces_fresh_inventory() -> None:
    engine = object.__new__(VisualTraversalEngine)
    engine.perception = _Perception()
    engine.interruption = _Dismisser()
    engine.review_debug = _Review()
    engine.env = _Env()
    engine._dismiss_enabled = True
    engine._settle_enabled = False
    engine._action_count = 0

    with patch("time.sleep", return_value=None):
        obs = engine._dismiss_interruptions(
            {"screenshot": b"splash"}, force_first=True)

    assert obs["screenshot"] == b"main"
    assert engine.env.captures == 1
    assert engine.perception.calls == [(b"splash", False), (b"main", True)]
    assert engine._startup_surface_unresolved is False


def test_page_identity_interruption_bypasses_region_lazy_skip(
        monkeypatch) -> None:
    class _ClickDismisser:
        def decide(self, shot, elements):
            if shot == b"popup":
                return {
                    "action": "click", "button": elements[0],
                    "reason": "close external foreground notification",
                }
            return {"action": "done", "button": None, "reason": "clean"}

    class _PopupPerception(_Perception):
        def semantic_inventory(self, shot, *, force_refresh=False):
            self.calls.append((shot, force_refresh))
            self._cur_frame_bytes = shot
            self.last_is_interruption = False
            self.last_all_elements = [
                _element("Close notification", interactive=True)]
            return list(self.last_all_elements)

    class _ClickEnv(_Env):
        def step(self, _action, pause=0):
            return {"screenshot": b"clean"}

    engine = object.__new__(VisualTraversalEngine)
    engine.perception = _PopupPerception()
    engine.interruption = _ClickDismisser()
    engine.review_debug = _Review()
    engine.env = _ClickEnv()
    engine._dismiss_enabled = True
    engine._settle_enabled = False
    engine._action_count = 0
    engine._live_center_for = lambda _button, _obs: [10, 10]
    monkeypatch.setenv("GUIWALK_REGION_LAZY_INVENTORY", "1")

    obs = engine._dismiss_interruptions(
        {"screenshot": b"popup"}, page_identity_flagged=True)

    assert obs["screenshot"] == b"clean"
    assert engine.perception.calls == [(b"popup", False), (b"clean", False)]
    assert engine._startup_surface_unresolved is False


def test_page_identity_interruption_rechecks_stacked_popups(
        monkeypatch) -> None:
    class _StackedPerception(_Perception):
        def semantic_inventory(self, shot, *, force_refresh=False):
            self.calls.append((shot, force_refresh))
            self._cur_frame_bytes = shot
            self.last_is_interruption = False
            self.last_all_elements = [
                _element("Close foreground", interactive=True)]
            return list(self.last_all_elements)

    class _StackedDismisser:
        def decide(self, shot, elements):
            if shot in {b"popup-1", b"popup-2"}:
                return {
                    "action": "click", "button": elements[0],
                    "reason": "close current foreground interruption",
                }
            return {"action": "done", "button": None, "reason": "clean"}

    class _StackedEnv(_Env):
        def __init__(self):
            super().__init__()
            self.frames = iter([b"popup-2", b"clean"])

        def step(self, _action, pause=0):
            return {"screenshot": next(self.frames)}

    engine = object.__new__(VisualTraversalEngine)
    engine.perception = _StackedPerception()
    engine.interruption = _StackedDismisser()
    engine.review_debug = _Review()
    engine.env = _StackedEnv()
    engine._dismiss_enabled = True
    engine._settle_enabled = False
    engine._action_count = 0
    engine._live_center_for = lambda _button, _obs: [10, 10]
    monkeypatch.setenv("GUIWALK_REGION_LAZY_INVENTORY", "1")

    obs = engine._dismiss_interruptions(
        {"screenshot": b"popup-1"}, page_identity_flagged=True)

    assert obs["screenshot"] == b"clean"
    assert [shot for shot, _force in engine.perception.calls] == [
        b"popup-1", b"popup-2", b"clean"]
    assert engine._startup_surface_unresolved is False


class _Graph:
    class _Nx:
        @staticmethod
        def number_of_nodes():
            return 0

    graph = _Nx()

    def __init__(self):
        self.stop_reason = "incomplete"
        self.saved = 0

    def save(self, _path):
        self.saved += 1


class _Ledger:
    def __init__(self):
        self.saved = 0

    def save(self):
        self.saved += 1


class _Debug:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


class _Host:
    app_name = "clock"
    _settle_enabled = False
    _preserve_initial_surface = False
    _action_count = 0
    graph_save_path = "memory://graph.json"

    def __init__(self):
        self.graph = _Graph()
        self.vlm_ledger = _Ledger()
        self.review_debug = _Debug()
        self.registered = 0

    def _ensure_on_app(self, obs):
        return obs, False, True

    def _refresh_window_crop(self):
        return None

    def _dismiss_interruptions(self, obs, force_first=False):
        assert force_first is True
        self._startup_surface_unresolved = True
        return obs

    def _register(self, _obs, _path):
        self.registered += 1
        return "bad", True


def test_unresolved_startup_interruption_is_not_registered() -> None:
    host = _Host()
    outcome = bootstrap_traversal(host, {"screenshot": b"splash"})

    assert outcome.terminal is host.graph
    assert host.graph.stop_reason == "startup_interruption_unresolved"
    assert host.registered == 0
    assert host.graph.saved == 1
    assert host.vlm_ledger.saved == 1
    assert host.review_debug.closed == 1


def test_resume_with_existing_nodes_defers_interruption_to_page_identity() -> None:
    class _ResumeHost(_Host):
        def __init__(self):
            super().__init__()
            self.graph.graph = type(
                "_ExistingGraph", (), {"number_of_nodes": lambda _self: 1})()
            self._state_data = {
                "known": {"path": [], "replay_hints": []},
            }

        def _dismiss_interruptions(self, *_args, **_kwargs):
            raise AssertionError(
                "resume must let Page Identity handle interruptions")

        def _register_landed(self, _obs):
            return "known", [], [], False

    host = _ResumeHost()

    outcome = bootstrap_traversal(host, {"screenshot": b"current"})

    assert outcome.terminal is None
    assert outcome.state_id == "known"
