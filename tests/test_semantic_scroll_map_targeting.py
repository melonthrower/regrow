from __future__ import annotations

import io
import json
from types import SimpleNamespace

from PIL import Image

from gui_rewalk.src.core.visual_traversal import visual_cache
from gui_rewalk.src.core.visual_traversal.prompts.grounding import (
    SCROLL_MAP_TARGET_PROMPT,
    SEMANTIC_INVENTORY_PROMPT,
)
from gui_rewalk.src.core.visual_traversal.runtime.execution import (
    _semantic_scroll_map_target,
)
from gui_rewalk.src.core.visual_traversal.visual_perception import (
    VisualElement,
    VisualPerception,
)


def _png(color="white", size=(200, 120)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, "PNG")
    return stream.getvalue()


def _target():
    return VisualElement(
        3, "Add alarm", [0, 0, 0, 0], [0, 0], el_type="button",
        category="navigation", region="alarm_list", region_id="r7",
        geometry_status="semantic_only")


def _accepting_reviewer():
    return SimpleNamespace(review_target=lambda *_args: {
        "accepted": True, "reason": "marked point is on Add alarm"})


def test_inventory_contract_marks_scrollability_and_ignores_passive_feedback():
    prompt = " ".join(SEMANTIC_INVENTORY_PROMPT.split())
    scroll_prompt = " ".join(SCROLL_MAP_TARGET_PROMPT.split())
    assert '"surface_scrollable":true|false|null' in prompt
    assert '"scrollable":true|false|null' in prompt
    assert "For each area return a short name" in prompt
    assert '"passive_feedback_present":true|false' in prompt
    assert "temporary feedback with no operable control" in prompt
    assert "estimated_viewports" not in scroll_prompt
    assert "complete actionable bbox lies strictly inside" in scroll_prompt
    assert "Visible text alone does not prove" in scroll_prompt


def test_two_image_scroll_map_grounder_returns_live_geometry(monkeypatch):
    captured = {}

    def predict(_agent, role, prompt, images, *_args, **_kwargs):
        captured.update(role=role, prompt=prompt, images=images)
        return json.dumps({
            "status": "visible",
            "coordinate_space": "normalized_1000",
            "bbox_1000": [100, 200, 300, 400],
            "click_point_1000": [200, 300],
            "reason": "plus icon is visible in the current alarm block",
        }), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object())
    grounded = perception.ground_target_with_scroll_map(
        _png(size=(200, 120)), _png(size=(200, 480)), _target())

    assert captured["role"] == "scroll_map_target"
    assert len(captured["images"]) == 2
    assert grounded.center == [40, 36]
    assert grounded.bbox_xywh == [20, 24, 40, 24]
    assert perception.last_scroll_map_grounding["status"] == "visible"


def test_map_relation_rechecks_after_each_scroll_segment():
    current = {"screenshot": _png("white")}
    after = {"screenshot": _png("gray")}

    class Perception:
        use_semantic_inventory = True

        def __init__(self):
            self.calls = 0
            self.last_scroll_map_grounding = {}

        def ground_target_with_scroll_map(self, shot, region_map, stored,
                                          force_refresh=False):
            assert region_map == b"long-map"
            self.calls += 1
            if self.calls == 1:
                self.last_scroll_map_grounding = {
                    "status": "below", "scroll_anchor_px": [100, 60],
                    "reason": "target below",
                }
                return None
            assert shot == after["screenshot"]
            self.last_scroll_map_grounding = {
                "status": "visible", "reason": "target now visible",
            }
            return VisualElement(
                stored.id, stored.name, [140, 80, 30, 20], [155, 90],
                el_type="button", category="navigation",
                region=stored.region, region_id=stored.region_id)

    class Env:
        def __init__(self):
            self.actions = []

        def step(self, action, pause=0):
            self.actions.append(action)
            return dict(after)

    class Writer:
        def __init__(self):
            self.attempts = []

        def load_region_image(self, state_id, region_id):
            assert (state_id, region_id) == ("s1", "r7")
            return b"long-map"

        def save_target_grounding_attempt(self, **kwargs):
            self.attempts.append(kwargs)

    perception = Perception()
    env = Env()
    host = SimpleNamespace(
        perception=perception, env=env, writer=Writer(),
        reviewer=_accepting_reviewer(),
        _state_data={"s1": {"semantic_blocks": [{
            "region_id": "r7", "scrollable": True,
            "viewport_bbox_1000": [0, 200, 1000, 700],
        }]}},
        graph=SimpleNamespace(scroll_ledger={"scope": {
            "region_id": "r7", "classification": "scrollable",
            "complete": True, "state_ids": ["s1"],
        }}),
        _frame_phash=lambda _shot: 0,
        _settle_enabled=False,
        _ensure_on_app=lambda obs: (obs, False, True),
        _last_live_rebind_observation=None,
    )

    result = _semantic_scroll_map_target(host, "s1", _target(), current)

    assert result["status"] == "matched"
    assert result["center"] == [155, 90]
    assert perception.calls == 2
    assert len(env.actions) == 1
    assert all(action["parameters"]["x"] == 100 for action in env.actions)
    assert env.actions[0]["parameters"]["frac"] == 0.21
    assert [row["outcome"] for row in host.writer.attempts] == [
        "offscreen", "accepted"]
    assert host.writer.attempts[-1]["reviewer"]["status"] == \
        "target_review_accepted"
    assert host.writer.attempts[-1]["diagnostic"]["local_validation"][
        "status"] == "locator_schema_validated"


def test_scroll_map_retries_once_after_reviewer_rejection():
    current = {"screenshot": _png("white")}

    class Perception:
        def __init__(self):
            self.calls = []
            self.last_scroll_map_grounding = {}

        def ground_target_with_scroll_map(
            self, shot, region_map, stored, force_refresh=False,
            correction_hint="",
        ):
            self.calls.append((force_refresh, correction_hint))
            self.last_scroll_map_grounding = {
                "status": "visible",
                "reason": "target is visible",
            }
            x = 40 if not force_refresh else 80
            return VisualElement(
                stored.id, stored.name, [x - 10, 30, 20, 20], [x, 40],
                el_type="button", category="navigation",
                region=stored.region, region_id=stored.region_id)

    verdicts = iter([
        {"accepted": False, "reason": "marked point is on the wrong row"},
        {"accepted": True, "reason": "corrected point is on Add alarm"},
    ])
    attempts = []
    perception = Perception()
    host = SimpleNamespace(
        perception=perception,
        env=SimpleNamespace(),
        writer=SimpleNamespace(
            load_region_image=lambda *_args: b"long-map",
            save_target_grounding_attempt=lambda **kwargs: attempts.append(
                kwargs)),
        reviewer=SimpleNamespace(
            review_target=lambda *_args: next(verdicts)),
        _state_data={"s1": {"semantic_blocks": []}},
        graph=SimpleNamespace(scroll_ledger={"scope": {
            "region_id": "r7", "classification": "scrollable",
            "complete": True, "state_ids": ["s1"],
        }}),
        _settle_enabled=False,
        _ensure_on_app=lambda obs: (obs, False, True),
        _last_live_rebind_observation=None,
    )

    result = _semantic_scroll_map_target(
        host, "s1", _target(), current)

    assert result["status"] == "matched"
    assert result["center"] == [80, 40]
    assert perception.calls == [
        (False, ""),
        (True, "marked point is on the wrong row"),
    ]
    assert [row["outcome"] for row in attempts] == [
        "review_rejected", "accepted"]
    assert attempts[-1]["reviewer"]["status"] == "target_review_accepted"


def test_boundary_clipped_visible_target_scrolls_before_clicking():
    current = {"screenshot": _png("white")}
    after = {"screenshot": _png("gray")}

    class Perception:
        def __init__(self):
            self.calls = 0
            self.last_scroll_map_grounding = {}

        def ground_target_with_scroll_map(self, shot, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                self.last_scroll_map_grounding = {
                    "status": "visible",
                    "bbox_1000": [0, 900, 1000, 1000],
                    "click_point_1000": [100, 970],
                    "image_size": [200, 120],
                    "reason": "only the label is exposed at the bottom edge",
                }
                return VisualElement(
                    3, "Add alarm", [0, 108, 200, 12], [20, 116],
                    el_type="button", category="navigation",
                    region="alarm_list", region_id="r7")
            assert shot == after["screenshot"]
            self.last_scroll_map_grounding = {
                "status": "visible",
                "bbox_1000": [100, 300, 900, 500],
                "click_point_1000": [200, 400],
                "image_size": [200, 120],
                "reason": "complete row is now inside the viewport",
            }
            return VisualElement(
                3, "Add alarm", [20, 36, 160, 24], [40, 48],
                el_type="button", category="navigation",
                region="alarm_list", region_id="r7")

    class Env:
        def __init__(self):
            self.actions = []

        def step(self, action, pause=0):
            self.actions.append(action)
            return dict(after)

    attempts = []
    host = SimpleNamespace(
        perception=Perception(),
        env=Env(),
        writer=SimpleNamespace(
            load_region_image=lambda *_args: b"long-map",
            save_target_grounding_attempt=lambda **kwargs: attempts.append(
                kwargs)),
        reviewer=_accepting_reviewer(),
        _state_data={"s1": {"semantic_blocks": [{
            "region_id": "r7", "scrollable": True,
            "viewport_bbox_1000": [0, 0, 1000, 1000],
        }]}},
        graph=SimpleNamespace(scroll_ledger={"scope": {
            "region_id": "r7", "classification": "scrollable",
            "complete": True, "state_ids": ["s1"],
        }}),
        _frame_phash=lambda _shot: 0,
        _settle_enabled=False,
        _ensure_on_app=lambda obs: (obs, False, True),
        _last_live_rebind_observation=None,
    )

    result = _semantic_scroll_map_target(
        host, "s1", _target(), current)

    assert result["status"] == "matched"
    assert result["center"] == [40, 48]
    assert len(host.env.actions) == 1
    assert host.env.actions[0]["parameters"]["x"] == 100
    assert host.env.actions[0]["parameters"]["y"] == 60
    assert attempts[0]["diagnostic"]["model_status"] == "visible"
    assert attempts[0]["diagnostic"]["status"] == "below"
    assert attempts[0]["diagnostic"]["geometry_reclassified"] == \
        "target_bbox_touches_viewport_boundary"


def test_map_relation_stops_when_scroll_does_not_move_viewport():
    current = {"screenshot": _png("white")}

    class Perception:
        last_scroll_map_grounding = {}

        def ground_target_with_scroll_map(self, *_args, **_kwargs):
            self.last_scroll_map_grounding = {
                "status": "below", "scroll_anchor_px": [100, 60],
                "reason": "target below",
            }
            return None

    host = SimpleNamespace(
        perception=Perception(),
        env=SimpleNamespace(step=lambda *_args, **_kwargs: dict(current)),
        writer=SimpleNamespace(
            load_region_image=lambda *_args: b"long-map",
            save_target_grounding_attempt=lambda **_kwargs: None),
        reviewer=None,
        _state_data={"s1": {"semantic_blocks": [{
            "region_id": "r7", "scrollable": True,
            "viewport_bbox_1000": [0, 0, 1000, 1000],
        }]}},
        graph=SimpleNamespace(scroll_ledger={"scope": {
            "region_id": "r7", "classification": "scrollable",
            "complete": True, "state_ids": ["s1"],
        }}),
        _settle_enabled=False,
        _ensure_on_app=lambda obs: (obs, False, True),
        _last_live_rebind_observation=None,
    )

    result = _semantic_scroll_map_target(host, "s1", _target(), current)

    assert result["status"] == "scroll_stalled"
    assert len(result["actions"]) == 1
    assert host._last_live_rebind_observation["status"] == "scroll_stalled"


def test_incomplete_scroll_ledger_cannot_treat_seed_crop_as_long_map():
    current = {"screenshot": _png("white")}

    class Perception:
        def ground_target_with_scroll_map(self, *_args, **_kwargs):
            raise AssertionError("incomplete audit must not use a Region crop")

    host = SimpleNamespace(
        perception=Perception(), env=SimpleNamespace(),
        writer=SimpleNamespace(load_region_image=lambda *_args: (
            _ for _ in ()).throw(
                AssertionError("incomplete audit must not load a Region map"))),
        graph=SimpleNamespace(scroll_ledger={"scope": {
            "region_id": "r7", "classification": "scrollable",
            "complete": False, "state_ids": ["s1"],
        }}),
        _state_data={"s1": {"semantic_blocks": [{
            "region_id": "r7", "scrollable": True,
            "viewport_bbox_1000": [0, 0, 1000, 1000],
        }]}},
    )

    assert _semantic_scroll_map_target(
        host, "s1", _target(), current) is None


def test_scroll_ledger_keeps_map_targeting_available_when_node_blocks_missing():
    current = {"screenshot": _png("white")}

    class Perception:
        last_scroll_map_grounding = {}

        def ground_target_with_scroll_map(self, *_args, **_kwargs):
            self.last_scroll_map_grounding = {
                "status": "visible", "reason": "visible in current viewport",
            }
            return VisualElement(
                3, "Add alarm", [20, 30, 40, 20], [40, 40],
                el_type="button", category="navigation",
                region="alarm_list", region_id="r7")

    host = SimpleNamespace(
        perception=Perception(),
        env=SimpleNamespace(),
        writer=SimpleNamespace(
            load_region_image=lambda *_args: b"long-map",
            save_target_grounding_attempt=lambda **_kwargs: None),
        reviewer=_accepting_reviewer(),
        region_registry=SimpleNamespace(_regions={}),
        graph=SimpleNamespace(scroll_ledger={"scope": {
            "region_id": "r7",
            "classification": "scrollable",
            "complete": True,
            "state_ids": ["s1"],
        }}),
        _state_data={"s1": {"semantic_blocks": []}},
        _settle_enabled=False,
        _ensure_on_app=lambda obs: (obs, False, True),
        _last_live_rebind_observation=None,
    )

    result = _semantic_scroll_map_target(host, "s1", _target(), current)

    assert result["status"] == "matched"
    assert result["center"] == [40, 40]


def test_router_click_uses_region_map_and_not_historical_scroll_depth():
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    target = _target()
    target.scroll_steps = 9

    class Perception:
        use_semantic_inventory = True
        last_scroll_map_grounding = {}

        def ground_target_with_scroll_map(self, shot, region_map, stored,
                                          force_refresh=False):
            assert shot == b"top"
            assert region_map == b"long-map"
            assert stored is target
            self.last_scroll_map_grounding = {"status": "visible"}
            return VisualElement(
                stored.id, stored.name, [40, 50, 20, 20], [50, 60],
                el_type="button", category="navigation",
                region=stored.region, region_id=stored.region_id)

    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.perception = Perception()
    engine._state_data = {"s1": {
        "elements": [target],
        "semantic_blocks": [{
            "region_id": "r7", "scrollable": True,
            "viewport_bbox_1000": [0, 0, 1000, 1000],
        }],
    }}
    engine.graph = SimpleNamespace(scroll_ledger={"scope": {
        "region_id": "r7", "classification": "scrollable",
        "complete": True, "state_ids": ["s1"],
    }})
    engine.writer = SimpleNamespace(
        load_region_image=lambda state_id, region_id: (
            b"long-map" if (state_id, region_id) == ("s1", "r7") else None))
    engine.reviewer = _accepting_reviewer()
    engine._router_diagnostic = lambda *_args, **_kwargs: None
    engine._live_center_for = lambda *_args: (_ for _ in ()).throw(
        AssertionError("Region-map grounding must own this target"))
    engine.env = SimpleNamespace(step=lambda action, pause=0: {
        "screenshot": b"clicked", "action": action})
    engine._settle_enabled = False
    engine._ensure_on_app = lambda obs: (obs, False, True)

    result = engine._router_click_button(
        "s1", target.name, target.region_id, target.region,
        {"screenshot": b"top"})

    assert result.status == "action_dispatched"
    assert result.observation["action"]["parameters"]["x"] == 50
