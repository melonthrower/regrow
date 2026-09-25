from __future__ import annotations

import sys
from types import ModuleType
from types import SimpleNamespace


def test_android_controller_executes_androidworld_swipe(monkeypatch):
    from gui_rewalk.env.android_controller import AndroidController

    issued = []
    adb_utils = ModuleType("android_world.env.adb_utils")
    adb_utils.generate_swipe_command = (
        lambda x1, y1, x2, y2, duration_ms=0:
        [x1, y1, x2, y2, duration_ms])
    adb_utils.issue_generic_request = (
        lambda command, env: issued.append((command, env)))
    env_module = ModuleType("android_world.env")
    env_module.adb_utils = adb_utils
    world_module = ModuleType("android_world")
    world_module.env = env_module
    monkeypatch.setitem(sys.modules, "android_world", world_module)
    monkeypatch.setitem(sys.modules, "android_world.env", env_module)
    monkeypatch.setitem(sys.modules, "android_world.env.adb_utils", adb_utils)
    controller = AndroidController.__new__(AndroidController)
    controller._ctrl = SimpleNamespace(env="android-env")
    controller.screen_size = (720, 1280)

    controller.execute_gui_action({
        "action_type": "swipe", "direction": "down"})

    assert issued == [([360, 106, 360, 1174, 500], "android-env")]


def test_android_controller_focuses_input_text_target_before_typing(monkeypatch):
    from gui_rewalk.env import android_controller

    events = []
    adb_utils = ModuleType("android_world.env.adb_utils")
    adb_utils.tap_screen = (
        lambda x, y, env: events.append(("tap", x, y, env)))
    adb_utils.type_text = (
        lambda value, env: events.append(("type", value, env)))
    env_module = ModuleType("android_world.env")
    env_module.adb_utils = adb_utils
    world_module = ModuleType("android_world")
    world_module.env = env_module
    monkeypatch.setitem(sys.modules, "android_world", world_module)
    monkeypatch.setitem(sys.modules, "android_world.env", env_module)
    monkeypatch.setitem(sys.modules, "android_world.env.adb_utils", adb_utils)
    monkeypatch.setattr(android_controller.time, "sleep", lambda _seconds: None)
    controller = android_controller.AndroidController.__new__(
        android_controller.AndroidController)
    controller._ctrl = SimpleNamespace(env="android-env")
    controller.screen_size = (720, 1280)

    controller.execute_gui_action({
        "action_type": "input_text",
        "x": 120,
        "y": 240,
        "text": "Oslo",
    })

    assert events == [
        ("tap", 120, 240, "android-env"),
        ("type", "Oslo", "android-env"),
    ]


def test_android_controller_reuses_verified_focused_input_without_tap(
    monkeypatch,
):
    from gui_rewalk.env import android_controller

    events = []
    adb_utils = ModuleType("android_world.env.adb_utils")
    adb_utils.tap_screen = (
        lambda x, y, env: events.append(("tap", x, y, env)))
    adb_utils.type_text = (
        lambda value, env: events.append(("type", value, env)))
    env_module = ModuleType("android_world.env")
    env_module.adb_utils = adb_utils
    world_module = ModuleType("android_world")
    world_module.env = env_module
    monkeypatch.setitem(sys.modules, "android_world", world_module)
    monkeypatch.setitem(sys.modules, "android_world.env", env_module)
    monkeypatch.setitem(sys.modules, "android_world.env.adb_utils", adb_utils)
    monkeypatch.setattr(android_controller.time, "sleep", lambda _seconds: None)
    controller = android_controller.AndroidController.__new__(
        android_controller.AndroidController)
    controller._ctrl = SimpleNamespace(env="android-env")
    controller.screen_size = (720, 1280)
    controller.active_text_input_check = lambda: True

    controller.execute_gui_action({
        "action_type": "input_text",
        "x": 120,
        "y": 240,
        "text": "Oslo",
    })

    assert events == [("type", "Oslo", "android-env")]


def test_android_controller_does_not_type_when_tap_misses_input(monkeypatch):
    from gui_rewalk.env import android_controller

    events = []
    focus_states = iter([False, False])
    adb_utils = ModuleType("android_world.env.adb_utils")
    adb_utils.tap_screen = (
        lambda x, y, env: events.append(("tap", x, y, env)))
    adb_utils.type_text = (
        lambda value, env: events.append(("type", value, env)))
    env_module = ModuleType("android_world.env")
    env_module.adb_utils = adb_utils
    world_module = ModuleType("android_world")
    world_module.env = env_module
    monkeypatch.setitem(sys.modules, "android_world", world_module)
    monkeypatch.setitem(sys.modules, "android_world.env", env_module)
    monkeypatch.setitem(sys.modules, "android_world.env.adb_utils", adb_utils)
    monkeypatch.setattr(android_controller.time, "sleep", lambda _seconds: None)
    controller = android_controller.AndroidController.__new__(
        android_controller.AndroidController)
    controller._ctrl = SimpleNamespace(env="android-env")
    controller.screen_size = (720, 1280)
    controller.active_text_input_check = lambda: next(focus_states)

    controller.execute_gui_action({
        "action_type": "input_text",
        "x": 120,
        "y": 240,
        "text": "Oslo",
    })

    assert events == [("tap", 120, 240, "android-env")]
    assert controller.last_action_error == "input_text_target_not_focused"


def test_android_controller_clears_existing_text_before_replacement(monkeypatch):
    from gui_rewalk.env import android_controller

    events = []
    adb_utils = ModuleType("android_world.env.adb_utils")
    adb_utils.tap_screen = (
        lambda x, y, env: events.append(("tap", x, y, env)))
    adb_utils.issue_generic_request = (
        lambda command, env: events.append(("clear", command, env)))
    adb_utils.type_text = (
        lambda value, env: events.append(("type", value, env)))
    env_module = ModuleType("android_world.env")
    env_module.adb_utils = adb_utils
    world_module = ModuleType("android_world")
    world_module.env = env_module
    monkeypatch.setitem(sys.modules, "android_world", world_module)
    monkeypatch.setitem(sys.modules, "android_world.env", env_module)
    monkeypatch.setitem(sys.modules, "android_world.env.adb_utils", adb_utils)
    monkeypatch.setattr(android_controller.time, "sleep", lambda _seconds: None)
    controller = android_controller.AndroidController.__new__(
        android_controller.AndroidController)
    controller._ctrl = SimpleNamespace(env="android-env")
    controller.screen_size = (720, 1280)

    controller.execute_gui_action({
        "action_type": "input_text",
        "x": 120,
        "y": 240,
        "text": "Oslo",
        "clear_text": True,
    })

    assert events == [
        ("tap", 120, 240, "android-env"),
        ("clear", [
            "shell", "input", "keycombination", "113", "29", "&&",
            "input", "keyevent", "67",
        ], "android-env"),
        ("type", "Oslo", "android-env"),
    ]


def test_android_controller_rejects_non_ascii_before_partial_typing(monkeypatch):
    from gui_rewalk.env import android_controller

    events = []
    adb_utils = ModuleType("android_world.env.adb_utils")
    adb_utils.tap_screen = (
        lambda x, y, env: events.append(("tap", x, y, env)))
    adb_utils.issue_generic_request = (
        lambda command, env: events.append(("clear", command, env)))
    adb_utils.type_text = (
        lambda value, env: events.append(("type", value, env)))
    env_module = ModuleType("android_world.env")
    env_module.adb_utils = adb_utils
    world_module = ModuleType("android_world")
    world_module.env = env_module
    monkeypatch.setitem(sys.modules, "android_world", world_module)
    monkeypatch.setitem(sys.modules, "android_world.env", env_module)
    monkeypatch.setitem(sys.modules, "android_world.env.adb_utils", adb_utils)
    monkeypatch.setattr(android_controller.time, "sleep", lambda _seconds: None)
    controller = android_controller.AndroidController.__new__(
        android_controller.AndroidController)
    controller._ctrl = SimpleNamespace(env="android-env")
    controller.screen_size = (720, 1280)

    controller.execute_gui_action({
        "action_type": "input_text",
        "x": 120,
        "y": 240,
        "text": "8:30 AM 闹钟标签文本",
        "clear_text": True,
    })

    assert events == []
    assert controller.last_action_error == "input_text_unsupported_non_ascii"


def test_desktop_controller_accepts_osworld_native_aliases(monkeypatch):
    from gui_rewalk.env import osworld_reload

    commands = []
    controller = osworld_reload.PythonController.__new__(
        osworld_reload.PythonController)
    controller.execute_python_command = commands.append
    monkeypatch.setattr(osworld_reload.time, "sleep", lambda _seconds: None)

    controller.execute_gui_action({
        "action_type": "TYPING",
        "parameters": {"x": 12, "y": 34, "text": "hello"},
    })
    controller.execute_gui_action({
        "action_type": "SCROLL", "parameters": {"dx": 2, "dy": -3}})

    assert commands[:2] == [
        "pyautogui.click(x=12, y=34)",
        "pyautogui.typewrite('hello')",
    ]
    assert any("hscroll(2)" in command for command in commands)
    assert any("vscroll(-3)" in command for command in commands)
