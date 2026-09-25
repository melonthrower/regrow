"""Offline contracts for the engine-independent current-frame target resolver."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.src.core.visual_traversal.live_targeting import (
    LiveTargeting,
    bbox_iou_xywh,
    is_explicit_noninteractive,
)
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement


def _frame(color: str = "white") -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (320, 200), color).save(stream, "PNG")
    return stream.getvalue()


def _norm(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _matches(target: str, candidate: str) -> bool:
    return bool(target and (target in candidate or candidate in target))


class _Env:
    def __init__(self, observation):
        self.observation = observation
        self.calls = 0

    def _get_obs(self):
        self.calls += 1
        if isinstance(self.observation, Exception):
            raise self.observation
        return dict(self.observation)


class _Perception:
    last_is_modal = False
    last_surface_kind = "page"
    last_window_xywh = None

    def __init__(self, elements):
        self.elements = elements
        self.calls = []

    def detect_and_name(self, _shot, force_refresh=False):
        self.calls.append(bool(force_refresh))
        return list(self.elements)


def _resolver(env, perception) -> LiveTargeting:
    return LiveTargeting(
        env=env,
        perception=perception,
        normalize_name=_norm,
        name_matches=_matches,
    )


def test_fresh_capture_updates_obs_and_region_filters() -> None:
    fresh_shot = _frame("green")
    outside = VisualElement(
        1, "Network", [220, 20, 80, 40], [260, 40],
        el_type="link", category="navigation")
    inside = VisualElement(
        2, "Network", [30, 60, 100, 40], [80, 80],
        el_type="link", category="navigation")
    stored = VisualElement(
        9, "Network", [20, 50, 100, 40], [70, 70],
        el_type="link", category="navigation")
    stored.region_bbox = [0, 0, 180, 180]
    env = _Env({"screenshot": fresh_shot, "terminal": "fresh"})
    resolver = _resolver(env, _Perception([outside, inside]))
    obs = {"screenshot": _frame("red"), "old": True}

    assert resolver.live_center_for(stored, obs) == inside.center
    assert env.calls == 1
    assert obs["screenshot"] == fresh_shot and obs["terminal"] == "fresh"
    assert resolver.last_observation is None


def test_capture_failure_and_noninteractive_are_diagnostic() -> None:
    stored = VisualElement(
        3, "Info", [10, 10, 40, 40], [30, 30],
        el_type="icon", category="navigation")
    resolver = _resolver(_Env(RuntimeError("capture down")), _Perception([]))
    assert resolver.live_center_for(stored, {"screenshot": _frame()}) is None
    assert resolver.last_observation["status"] == "surface_capture_failed"

    fresh = VisualElement(
        4, "Info", [10, 10, 40, 40], [30, 30],
        el_type="icon", interactive=False, category="display")
    resolver = _resolver(_Env({"screenshot": _frame()}), _Perception([fresh]))
    assert resolver.live_center_for(stored, {}) is None
    assert resolver.last_observation["status"] == "noninteractive"
    assert is_explicit_noninteractive(resolver.last_observation["fresh"])


def test_stateful_requires_same_state_key() -> None:
    stored = VisualElement(
        5, "Toggle", [10, 10, 80, 40], [50, 30],
        el_type="switch", category="navigation", stateful=True,
        state_key="wifi", state_value="off")
    wrong = VisualElement(
        6, "Toggle", [10, 10, 80, 40], [50, 30],
        el_type="switch", category="navigation", stateful=True,
        state_key="bluetooth", state_value="off")
    resolver = _resolver(_Env({"screenshot": _frame()}), _Perception([wrong]))
    assert resolver.live_center_for(stored, {}) is None
    assert bbox_iou_xywh(stored.bbox_xywh, wrong.bbox_xywh) == 1.0


def test_fixture_oracle_grounding_bypasses_model_and_reviewer() -> None:
    class OracleEnv(_Env):
        fixture_oracle_grounding = True

        def resolve_fixture_grounding(self, element):
            assert element.name == "Settings"
            return {
                "status": "matched", "method": "fixture_oracle_grounding",
                "action_id": "profile.settings", "center": [121, 404],
                "bbox_xywh": [20, 380, 202, 48],
            }

    class SemanticPerception:
        use_semantic_inventory = True

        def ground_target(self, *_args, **_kwargs):
            raise AssertionError("target grounding model must be bypassed")

    class Reviewer:
        def review_target(self, *_args, **_kwargs):
            raise AssertionError("target reviewer must be bypassed")

    env = OracleEnv({"screenshot": _frame()})
    resolver = LiveTargeting(
        env=env, perception=SemanticPerception(), reviewer=Reviewer(),
        normalize_name=_norm, name_matches=_matches)
    stored = VisualElement(
        8, "Settings", [0, 0, 0, 0], [0, 0], el_type="button",
        category="navigation", region="menu_list",
        geometry_status="semantic_only")

    assert resolver.live_center_for(stored, {}) == [121, 404]
    assert env.calls == 1
    assert resolver.last_observation["method"] == "fixture_oracle_grounding"
    assert resolver.last_observation["diagnostic"]["action_id"] == "profile.settings"


def main() -> int:
    test_fresh_capture_updates_obs_and_region_filters()
    test_capture_failure_and_noninteractive_are_diagnostic()
    test_stateful_requires_same_state_key()
    test_fixture_oracle_grounding_bypasses_model_and_reviewer()
    print("PASS live targeting fresh-capture/region/noninteractive/state-key guards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
