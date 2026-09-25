"""Offline checks for the traversal-backed M13 live adapter."""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui_rewalk.src.core.scenario.live_visual_collection import (  # noqa: E402
    EngineVisualAdapter,
)


@dataclass
class Element:
    id: int
    name: str
    uid: str = ""
    el_type: str = "button"
    region: str = "content"
    region_id: str = ""
    region_bbox: list = None
    bbox_xywh: list = None

    def __post_init__(self):
        if self.region_bbox is None:
            self.region_bbox = [0, 0, 300, 300]
        if self.bbox_xywh is None:
            self.bbox_xywh = [100, 100, 80, 20]


class Env:
    def __init__(self):
        self.obs = {"screenshot": b"frame", "node": "root"}
        self.actions = []

    def _get_obs(self):
        return self.obs

    def step(self, action, pause=0):
        self.actions.append(action)
        return self.obs


class Engine:
    def __init__(self):
        class _Perception:
            @staticmethod
            def detect_and_name(_screenshot):
                return [Element(99, "Live Unlock")]

        self.perception = _Perception()
        self._state_data = {
            "root": {"elements": [
                Element(1, "Open Details"),
                Element(2, "Title", el_type="input"),
                Element(3, "Drop Zone"),
            ]}
        }

    def _router_identify(self, obs):
        return obs.get("node")

    def _live_center_for(self, target, _obs):
        return [120 + target.id, 80 + target.id]

    def _settle(self, obs):
        return obs


def test_identify_resolves_page_then_exact_known_state(tmp_path):
    screenshot_paths = {}
    for state_id in ("s1", "s2"):
        path = tmp_path / f"{state_id}.png"
        path.write_bytes(f"known-{state_id}".encode())
        screenshot_paths[state_id] = str(path)

    class _Registry:
        @staticmethod
        def exact_frame_state_ids(_screenshot):
            return []

        @staticmethod
        def page_id_of(_state_id):
            return "p1"

        @staticmethod
        def known_path(state_id):
            return screenshot_paths[state_id]

    class _Resolver:
        @staticmethod
        def resolve(_screenshot):
            return SimpleNamespace(known=False, state_id="")

    class _PageJudge:
        last_selection_status = "selected"
        last_candidate_page_ids = ("p1",)

    class _Engine:
        registry = _Registry()
        identity_resolver = _Resolver()
        page_judge = _PageJudge()
        _state_data = {
            "s1": {
                "page_id": "p1", "page_name": "Stopwatch",
                "variant_id": "s1", "semantic_blocks": [],
                "elements": [Element(1, "Start", region_id="controls")],
            },
            "s2": {
                "page_id": "p1", "page_name": "Stopwatch",
                "variant_id": "s2", "semantic_blocks": [],
                "elements": [Element(2, "Pause", region_id="controls")],
            },
        }

    class _StateLocator:
        def __init__(self):
            self.call = None
            self.calls = 0

        def locate(self, screenshot, candidates, *, page_ref):
            self.calls += 1
            self.call = (screenshot, candidates, page_ref)
            return "s2"

    locator = _StateLocator()
    adapter = EngineVisualAdapter(
        Env(), _Engine(), "clock", pause=0, state_locator=locator)

    assert adapter.identify({"screenshot": b"live"}) == "s2"
    assert locator.call[0] == b"live"
    assert locator.call[2] == "p1"
    assert [row["state_ref"] for row in locator.call[1]] == ["s1", "s2"]
    assert locator.call[1][0]["regions"] == [{
        "name": "content", "operations": ["Start"]}]
    assert adapter.identify({"screenshot": b"live-again"}) == "s2"
    assert locator.calls == 1, "State identity is stable until a GUI action"
    adapter.execute({
        "actions": [{
            "action_type": "PRESS", "parameters": {"key": "enter"}}],
    })
    assert adapter.identify({"screenshot": b"after-action"}) == "s2"
    assert locator.calls == 2


def test_graph_edge_region_ref_matches_the_stored_region_id():
    env = Env()
    engine = Engine()
    target = engine._state_data["root"]["elements"][0]
    target.region = "Top Navigation Bar"
    target.region_id = "r1"
    adapter = EngineVisualAdapter(env, engine, "clock", pause=0)

    grounded = adapter.ground({
        "kind": "graph_edge",
        "source_node": "root",
        "edge": {
            "element_label": "Open Details",
            "region": "r1",
            "action": {"action_type": "CLICK"},
        },
    }, env.obs)

    assert grounded["element_name"] == "Open Details"
    assert grounded["actions"][0]["parameters"]["x"] == 121


def test_semantic_only_targets_use_targeted_grounding_without_global_mode():
    env = Env()
    engine = Engine()
    target = engine._state_data["root"]["elements"][0]
    target.geometry_status = "semantic_only"
    engine.perception.use_semantic_inventory = False
    observed_modes = []

    def live_center(_target, _obs):
        observed_modes.append(engine.perception.use_semantic_inventory)
        return [121, 81]

    engine._live_center_for = live_center
    adapter = EngineVisualAdapter(env, engine, "clock", pause=0)

    grounded = adapter.ground({
        "kind": "graph_edge", "source_node": "root",
        "edge": {
            "element_label": "Open Details",
            "action": {"action_type": "CLICK"},
        },
    }, env.obs)

    assert grounded is not None
    assert observed_modes == [True]
    assert engine.perception.use_semantic_inventory is False


def test_workflow_click_uses_only_valid_current_frame_normalized_geometry():
    stream = io.BytesIO()
    Image.new("RGB", (1000, 500), "white").save(stream, format="PNG")
    observation = {"screenshot": stream.getvalue(), "node": "root"}
    adapter = EngineVisualAdapter(Env(), Engine(), "clock", pause=0)
    decision = {"next_click": {
        "target": "Stopwatch",
        "bbox_1000": [400, 100, 600, 300],
        "click_point_1000": [500, 200],
    }}

    grounded = adapter.ground_workflow_click(
        "Stopwatch", decision, observation)

    assert grounded["actions"] == [{
        "action_type": "CLICK",
        "parameters": {"x": 500, "y": 100, "button": "left"},
    }]
    assert grounded["grounding_source"] == "workflow_agent_current_frame"
    assert adapter.ground_workflow_click(
        "Alarms", decision, observation) is None
    outside = {"next_click": {
        "target": "Stopwatch",
        "bbox_1000": [400, 100, 600, 300],
        "click_point_1000": [900, 200],
    }}
    assert adapter.ground_workflow_click(
        "Stopwatch", outside, observation) is None


class DynamicEnv:
    def __init__(self):
        self.obs = {"screenshot": b"root-frame", "node": "root"}
        self.actions = []
        self.capture_count = 0
        self.focused = False

    def _get_obs(self):
        self.capture_count += 1
        return self.obs

    def step(self, action, pause=0):
        self.actions.append(action)
        action_type = action.get("action_type")
        if self.obs["node"] == "root" and action_type == "CLICK":
            self.obs = {"screenshot": b"form-frame", "node": "form"}
        elif self.obs["node"] == "form" and action_type == "CLICK" and not self.focused:
            self.focused = True
        elif self.obs["node"] == "form" and action_type == "CLICK" and self.focused:
            self.obs = {"screenshot": b"detail-frame", "node": "detail"}
        return self.obs


class DynamicEngine:
    def __init__(self):
        class _Perception:
            @staticmethod
            def detect_and_name(screenshot):
                if screenshot == b"root-frame":
                    return [Element(10, "Create alarm", region_id="toolbar")]
                if screenshot == b"form-frame":
                    return [
                        Element(
                            20, "Alarm name", el_type="input", region="form",
                            region_id="new-alarm-detail"),
                        Element(
                            21, "Save", region="action_bar",
                            region_id="new-alarm-detail"),
                    ]
                return [Element(30, "Alarm details")]

        self.perception = _Perception()
        self._state_data = {
            "root": {"elements": []},
            "form": {
                "elements": [],
                "region_transition": {
                    "source_state_id": "root",
                    "result_binding": {
                        "status": "bound",
                        "attempt_id": "clock:1",
                        "region_ids": ["new-alarm-detail"],
                    },
                },
            },
            "detail": {"elements": []},
        }

    def _router_identify(self, obs):
        return obs.get("node")

    def _live_center_for(self, target, _obs):
        return [10 + target.id, 20 + target.id]

    def _settle(self, obs):
        return obs


def _test_dynamic_multiscreen_recipe() -> None:
    env = DynamicEnv()
    adapter = EngineVisualAdapter(env, DynamicEngine(), "clock", pause=0)
    try:
        adapter.ground({
            "kind": "capability",
            "capability_ref": {
                "node_id": "root",
                "name": "Unbound",
                "execution_recipe": [
                    {"action_type": "TYPE", "parameters": {"text": "{{missing}}"}},
                ],
            },
        }, env.obs)
    except ValueError as exc:
        assert "missing parameter" in str(exc)
    else:
        raise AssertionError("an unresolved recipe parameter must fail grounding")
    grounded = adapter.ground({
        "kind": "capability",
        "capability_ref": {
            "app_id": "clock",
            "node_id": "root",
            "capability_id": "create_alarm",
            "name": "Create alarm",
            "params": {"alarm_name": "Morning"},
            "execution_recipe": [
                {
                    "action_type": "CLICK",
                    "selector": {"element_label": "Create alarm"},
                    "parameters": {"x": 999, "y": 999},
                },
                {
                    "action_type": "CLICK",
                    "selector": {
                        "element_label": "Alarm name",
                        "element_type": "input",
                        "region": "form",
                    },
                },
                {"action_type": "HOTKEY", "parameters": {"keys": ["ctrl", "a"]}},
                {"action_type": "TYPE", "parameters": {"text": "{{alarm_name}}"}},
                {
                    "action_type": "CLICK",
                    "selector": {"element_label": "Save", "region": "action_bar"},
                },
            ],
        },
    }, env.obs)
    assert grounded["grounding_source"] == "capability_dynamic_visual_recipe"
    assert grounded["dynamic_recipe"][0]["parameters"] == {}, \
        "persisted recipe coordinates must be removed before execution"
    result = adapter.execute(grounded)
    assert result["node"] == "detail"
    assert env.capture_count >= 5, "every recipe step must recapture the live frame"
    assert [action["action_type"] for action in env.actions] == [
        "CLICK", "CLICK", "HOTKEY", "TYPE", "CLICK",
    ]
    assert env.actions[0]["parameters"]["x"] == 20
    assert env.actions[1]["parameters"]["x"] == 30
    assert env.actions[-1]["parameters"]["x"] == 31
    assert env.actions[3]["parameters"]["text"] == "Morning"
    assert grounded["gui_action_count"] == 5
    assert grounded["_executed_gui_actions"] == 5
    assert grounded["primitive_actions"] == env.actions
    assert [item["source_node_id"] for item in grounded["recipe_groundings"]] == [
        "root", "form", "form", "form", "form",
    ]

    failed_env = DynamicEnv()
    failed = EngineVisualAdapter(failed_env, DynamicEngine(), "clock", pause=0)
    failed_grounding = failed.ground({
        "kind": "capability",
        "capability_ref": {
            "node_id": "root",
            "name": "Fail closed",
            "execution_recipe": [
                {"action_type": "CLICK", "selector": {"element_label": "Create alarm"}},
                {"action_type": "CLICK", "selector": {"element_label": "Missing control"}},
                {"action_type": "TYPE", "parameters": {"text": "must not run"}},
            ],
        },
    }, failed_env.obs)
    try:
        failed.execute(failed_grounding)
    except RuntimeError as exc:
        assert "step 1 failed" in str(exc)
    else:
        raise AssertionError("an ungroundable recipe step must fail closed")
    assert len(failed_env.actions) == 1
    assert failed_grounding["_executed_gui_actions"] == 1
    assert failed_grounding["failed_recipe_index"] == 1


def test_dynamic_recipe_targets_the_region_created_by_an_earlier_step():
    env = DynamicEnv()
    adapter = EngineVisualAdapter(env, DynamicEngine(), "clock", pause=0)
    grounded = adapter.ground({
        "kind": "capability",
        "capability_ref": {
            "node_id": "root",
            "execution_recipe": [
                {
                    "action_type": "CLICK",
                    "selector": {"element_label": "Create alarm"},
                    "bind_result": "new_alarm",
                },
                {
                    "action_type": "CLICK",
                    "selector": {
                        "element_label": "Alarm name",
                        "region_ref": "new_alarm",
                    },
                },
            ],
        },
    }, env.obs)

    adapter.execute(grounded)

    assert grounded["recipe_groundings"][0]["result_binding"][
        "region_ids"] == ["new-alarm-detail"]
    assert grounded["recipe_groundings"][1]["semantic_step"]["selector"][
        "region_ids"] == ["new-alarm-detail"]
    assert [action["action_type"] for action in env.actions] == [
        "CLICK", "CLICK"]


def test_selector_bound_input_refocuses_fresh_element_before_typing():
    env = Env()
    engine = Engine()
    query = engine._state_data["root"]["elements"][1]
    query.uid = "autonomous-element:city-query"
    query.region_id = "rg-city-search"
    adapter = EngineVisualAdapter(env, engine, "clock", pause=0)

    grounded = adapter.ground({
        "action_type": "TYPING",
        "parameters": {"x": 999, "y": 999, "text": "Oslo"},
        "selector": {
            "element_id": "autonomous-element:city-query",
            "region_ids": ["rg-city-search"],
        },
    }, env.obs)

    assert grounded["actions"] == [
        {
            "action_type": "CLICK",
            "parameters": {"x": 122, "y": 82, "button": "left"},
        },
        {"action_type": "TYPE", "parameters": {"text": "Oslo"}},
    ]
    assert grounded["gui_action_count"] == 2
    assert grounded["element_id"] == "autonomous-element:city-query"
    assert grounded["grounding_source"] == "type_input_live_relocation"

    android_alias = adapter.ground({
        "action_type": "input_text",
        "text": "Paris",
        "selector": {
            "element_id": "autonomous-element:city-query",
            "region_ids": ["rg-city-search"],
        },
    }, env.obs)
    assert android_alias["actions"][1] == {
        "action_type": "TYPE", "parameters": {"text": "Paris"}}

    assert adapter.ground({
        "action_type": "TYPE",
        "text": "must not type",
        "selector": {"element_label": "Open Details"},
    }, env.obs) is None


def main() -> int:
    env, engine = Env(), Engine()
    adapter = EngineVisualAdapter(env, engine, "demo", pause=0)

    edge = adapter.ground({
        "kind": "graph_edge", "source_node": "root",
        "edge": {
            "element_id": "1", "element_label": "Open Details",
            "region": "full_screen",
            "action": {"action_type": "CLICK",
                       "parameters": {"x": 999, "y": 999}},
        },
    }, env.obs)
    assert edge["actions"][0]["parameters"]["x"] == 121
    assert edge["actions"][0]["parameters"]["y"] == 81
    adapter.execute(edge)
    assert env.actions[-1]["parameters"]["x"] == 121

    capability = adapter.ground({
        "kind": "capability", "params": {"title": "GUIWalk Test"},
        "capability_ref": {
            "node_id": "root", "name": "Set title", "elements": ["2"],
            "param_type": "string", "slot": "title", "value": "GUIWalk Test",
        },
    }, env.obs)
    assert capability["gui_action_count"] == 2
    assert capability["actions"][1] == {
        "action_type": "TYPE", "parameters": {"text": "GUIWalk Test"}}

    prerequisite_click = adapter.ground({
        "action": "click", "element_id": "1",
        "element_label": "Open Details", "x": 999, "y": 999,
    }, env.obs)
    assert prerequisite_click["actions"][0]["parameters"]["x"] == 121
    assert prerequisite_click["grounding_source"] == \
        "prerequisite_live_element_relocation"

    live_elements = adapter.grounded_elements(env.obs)
    assert live_elements[0]["id"] == 99
    live_click = adapter.ground({
        "action": "click", "element_id": "99", "element_label": "Live Unlock",
    }, env.obs)
    assert live_click["actions"][0]["parameters"]["x"] == 219

    prerequisite_type = adapter.ground({
        "action_type": "TYPE", "text": "fixture",
    }, env.obs)
    assert prerequisite_type["actions"] == [{
        "action_type": "TYPE", "parameters": {"text": "fixture"}}]
    prerequisite_press = adapter.ground({
        "action_type": "PRESS", "parameters": {"key": "enter"},
    }, env.obs)
    assert prerequisite_press["actions"] == [{
        "action_type": "PRESS", "parameters": {"key": "enter"}}]
    prerequisite_hotkey = adapter.ground({
        "action_type": "HOTKEY", "parameters": {"keys": ["ctrl", "a"]},
    }, env.obs)
    assert prerequisite_hotkey["actions"] == [{
        "action_type": "HOTKEY", "parameters": {"keys": ["ctrl", "a"]}}]
    long_press = adapter.ground({
        "action_type": "LONG_PRESS", "selector": {"element_label": "Live Unlock"},
    }, env.obs)
    assert long_press["actions"][0]["action_type"] == "LONG_PRESS"
    prerequisite_back = adapter.ground({"action": "back"}, env.obs)
    assert prerequisite_back["actions"] == [{
        "action_type": "HOTKEY", "parameters": {"keys": ["alt", "left"]}}]
    prerequisite_scroll = adapter.ground({
        "action": "scroll", "direction": "down", "amount": 2,
        "x": 999, "y": 999,
    }, env.obs)
    assert prerequisite_scroll["actions"] == [{
        "action_type": "SCROLL", "parameters": {"dy": -2}}]
    assert adapter.ground({
        "action_type": "CLICK", "parameters": {"x": 999, "y": 999},
    }, env.obs) is None, "coordinate-only prerequisite clicks must fail closed"
    assert adapter.ground({"action": "run shell command"}, env.obs) is None
    drag = adapter.ground({
        "action_type": "DRAG",
        "source_selector": {"element_label": "Open Details"},
        "target_selector": {"element_label": "Drop Zone"},
        "parameters": {"x1": 999, "y1": 999, "x2": 0, "y2": 0},
    }, env.obs)
    assert drag["actions"] == [{
        "action_type": "DRAG",
        "parameters": {"x1": 121, "y1": 81, "x2": 123, "y2": 83},
    }]
    assert drag["grounding_source"] == "semantic_drag_live_relocation"
    engine._state_data["root"]["elements"].append(Element(
        9, "System Volume", el_type="slider",
        bbox_xywh=[100, 200, 400, 20]))
    slider = adapter.ground({
        "action_type": "SET_SLIDER",
        "selector": {
            "element_label": "System Volume", "element_type": "slider",
        },
        "parameters": {"level": "一半"},
    }, env.obs)
    assert slider["actions"] == [{
        "action_type": "CLICK", "parameters": {"x": 300, "y": 210},
    }]
    assert slider["slider_fraction"] == 0.5
    assert slider["grounding_source"] == "semantic_slider_live_track"
    assert adapter.ground({
        "kind": "graph_edge", "source_node": "root",
        "edge": {
            "transition_kind": "prerequisite_setup",
            "action_steps": 2,
            "action": {
                "action_type": "SEQUENCE",
                "parameters": {"actions": [
                    {"action_type": "CLICK", "parameters": {"x": 1, "y": 1}},
                ]},
            },
        },
    }, env.obs) is None, "runtime-owned setup sequences must be replanned"

    engine._state_data["root"]["elements"][0].region_bbox = [0, 0, 10, 10]
    assert adapter.ground({
        "kind": "graph_edge", "source_node": "root",
        "edge": {"element_id": "1", "element_label": "Open Details"},
    }, env.obs) is None, "relocation outside the source region must fail closed"

    _test_dynamic_multiscreen_recipe()

    print("PASS traversal-backed live collection adapter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
