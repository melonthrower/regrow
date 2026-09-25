"""A Region-grounded scroll starts where the model actually pointed."""
import sys
import types
from io import BytesIO

import pytest
from PIL import Image

from gui_rewalk.env.android_controller import AndroidController
from gui_rewalk.src.core.explore.actions import to_primitive
from gui_rewalk.src.core.explore.contracts import ActionRequest


def _controller(monkeypatch):
    commands = []
    adb = types.ModuleType("android_world.env.adb_utils")
    adb.generate_swipe_command = lambda *args, **kwargs: (args, kwargs)
    adb.issue_generic_request = lambda command, env: commands.append(command)
    package = types.ModuleType("android_world.env")
    package.adb_utils = adb
    monkeypatch.setitem(sys.modules, "android_world.env", package)
    monkeypatch.setitem(sys.modules, "android_world.env.adb_utils", adb)
    controller = object.__new__(AndroidController)
    controller.screen_size = (900, 1600)
    controller._ctrl = types.SimpleNamespace(env=object())
    return controller, commands


@pytest.mark.parametrize("direction,end", [
    ("down", (360, 720)), ("up", (360, 1520)),
    ("left", (585, 1120)), ("right", (135, 1120)),
])
def test_explicit_scroll_origin_stays_inside_the_selected_region(monkeypatch, direction, end):
    controller, commands = _controller(monkeypatch)
    controller._scroll({"x": 360, "y": 1120, "direction": direction, "frac": .25})
    assert len(commands) == 1
    assert commands[0][0] == (360, 1120, *end)


def test_unanchored_scroll_retains_its_existing_centered_default(monkeypatch):
    controller, commands = _controller(monkeypatch)
    controller._scroll({"direction": "down", "frac": .25})
    assert commands[0][0] == (450, 1000, 450, 600)


def test_scroll_near_screen_edge_does_not_reverse_direction(monkeypatch):
    controller, commands = _controller(monkeypatch)
    controller._scroll({"x": 20, "y": 30, "direction": "down", "frac": .25})
    assert commands[0][0] == (20, 30, 20, 1)


def test_framework_mobile_scroll_distance_is_not_a_number_of_swipes(monkeypatch):
    stream = BytesIO()
    Image.new("RGB", (900, 1600)).save(stream, format="PNG")
    action = ActionRequest(kind="scroll", purpose="survey", target="List", text="",
                           owner_ref="r-list", operation_ref="o-scroll",
                           point_1000=[400, 700], direction="down", amount=400)
    primitive = to_primitive(action, screenshot=stream.getvalue(), platform="android")
    assert primitive["frac"] == .25
    assert primitive.get("amount", 1) == 1
    controller, commands = _controller(monkeypatch)
    controller.execute_gui_action(primitive)
    assert len(commands) == 1
    assert commands[0][0] == (360, 1119, 360, 719)
