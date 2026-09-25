from __future__ import annotations

from types import SimpleNamespace

from gui_rewalk.src.core import app_lifecycle
from gui_rewalk.src.core.visual_traversal.visual_engine import (
    VisualTraversalEngine,
)
from gui_rewalk.src.core.visual_traversal.agents.focus import AppFocusGuard


SETTINGS_WINDOW = """\
WINDOW_ID=0x3400011
WM_CLASS(STRING) = "gnome-control-center", "Gnome-control-center"
_NET_WM_NAME(UTF8_STRING) = "Settings"
WM_NAME(STRING) = "Settings"
_NET_WM_PID(CARDINAL) = 2758
WM_TRANSIENT_FOR:  not found.
"""


def test_seed_file_reports_guest_creation_failure() -> None:
    result = {"output": "seed_fail\n"}
    env = SimpleNamespace(
        controller=SimpleNamespace(
            execute_python_command=lambda _command: result,
        ),
    )

    assert app_lifecycle._ensure_seed_file(
        env, "/home/user/Documents/budget.xlsx", "xlsx") is False

    result["output"] = "seed_ok\n"
    assert app_lifecycle._ensure_seed_file(
        env, "/home/user/Documents/budget.xlsx", "xlsx") is True


def test_desktop_window_owner_binds_launch_and_rejects_external_window(
    monkeypatch,
) -> None:
    active = {"output": SETTINGS_WINDOW}
    monkeypatch.setattr(
        app_lifecycle.mobile_ops, "is_android_env", lambda _env: False)
    monkeypatch.setattr(
        app_lifecycle, "_run_vm_command",
        lambda _env, _command, timeout=10: active["output"])

    owner = app_lifecycle.DesktopWindowOwner(object())
    assert owner.bind_active("setting") is True
    assert owner.is_foreground() is True

    active["output"] = """\
WINDOW_ID=0x4200001
WM_CLASS(STRING) = "firefox", "Firefox"
_NET_WM_NAME(UTF8_STRING) = "Mozilla Firefox"
_NET_WM_PID(CARDINAL) = 9001
WM_TRANSIENT_FOR:  not found.
"""
    assert owner.is_foreground() is False


def test_desktop_window_owner_accepts_owned_dialog(monkeypatch) -> None:
    active = {"output": SETTINGS_WINDOW}
    monkeypatch.setattr(
        app_lifecycle.mobile_ops, "is_android_env", lambda _env: False)
    monkeypatch.setattr(
        app_lifecycle, "_run_vm_command",
        lambda _env, _command, timeout=10: active["output"])

    owner = app_lifecycle.DesktopWindowOwner(object())
    assert owner.bind_active("setting") is True
    active["output"] = """\
WINDOW_ID=0x3400099
WM_CLASS(STRING) = "dialog", "Dialog"
_NET_WM_NAME(UTF8_STRING) = "Confirm"
_NET_WM_PID(CARDINAL) = 2758
WM_TRANSIENT_FOR(WINDOW): window id # 0x3400011
"""
    assert owner.is_foreground() is True


def test_desktop_window_owner_reactivates_bound_window(monkeypatch) -> None:
    active = {"output": SETTINGS_WINDOW}
    commands = []

    def run(_env, command, timeout=10):
        commands.append(command)
        return active["output"]

    monkeypatch.setattr(
        app_lifecycle.mobile_ops, "is_android_env", lambda _env: False)
    monkeypatch.setattr(app_lifecycle, "_run_vm_command", run)

    owner = app_lifecycle.DesktopWindowOwner(object())
    assert owner.bind_active("setting") is True

    assert owner.activate() is True
    assert ["wmctrl", "-ia", "0x3400011"] in commands


def test_surface_app_window_matches_wm_class_when_title_is_generic(
    monkeypatch,
) -> None:
    commands = []

    def run(_env, command, timeout=10):
        commands.append(command)
        if command == ["wmctrl", "-lx"]:
            return (
                "0x03e00003  0 org.gnome.Nautilus.Org.gnome.Nautilus "
                "user-virtual-machine Home\n"
            )
        if command == ["wmctrl", "-l"]:
            return "0x03e00003  0 user-virtual-machine Home\n"
        return ""

    monkeypatch.setattr(
        app_lifecycle.mobile_ops, "is_android_env", lambda _env: False)
    monkeypatch.setattr(app_lifecycle, "_run_vm_command", run)

    assert app_lifecycle._surface_app_window(object(), "files") is True
    assert ["wmctrl", "-ia", "0x03e00003"] in commands


def test_wait_for_app_uses_desktop_owner_before_visual_fallback(
    monkeypatch,
) -> None:
    class Owner:
        def __init__(self):
            self.binds = 0

        def bind_active(self, app_name, verified=False):
            self.binds += 1
            assert app_name == "setting"
            assert verified is False
            return True

    class Env:
        def _get_obs(self):
            raise AssertionError("screenshot/VLM fallback should not run")

    owner = Owner()
    monkeypatch.setattr(
        app_lifecycle.mobile_ops, "is_android_env", lambda _env: False)
    monkeypatch.setattr(
        app_lifecycle, "_surface_app_window", lambda _env, _app: True)

    assert app_lifecycle.wait_for_app(
        Env(),
        "setting",
        appear_check=lambda _shot: (_ for _ in ()).throw(
            AssertionError("visual focus judge should not run")),
        desktop_window_owner=owner,
    ) is True
    assert owner.binds == 1


def test_wait_for_app_retries_window_bind_before_visual_fallback(
    monkeypatch,
) -> None:
    class Owner:
        def __init__(self):
            self.binds = 0

        def bind_active(self, app_name, verified=False):
            self.binds += 1
            return self.binds == 2

    class Env:
        def _get_obs(self):
            raise AssertionError("screenshot/VLM fallback should not run")

    owner = Owner()
    monkeypatch.setattr(
        app_lifecycle.mobile_ops, "is_android_env", lambda _env: False)
    monkeypatch.setattr(
        app_lifecycle, "_surface_app_window", lambda _env, _app: True)
    monkeypatch.setattr(app_lifecycle.time, "sleep", lambda _seconds: None)

    assert app_lifecycle.wait_for_app(
        Env(),
        "setting",
        appear_check=lambda _shot: (_ for _ in ()).throw(
            AssertionError("visual focus judge should not run")),
        desktop_window_owner=owner,
    ) is True
    assert owner.binds == 2


def test_wait_for_app_retries_until_window_is_listed(
    monkeypatch,
) -> None:
    surfaces = iter((False, True))

    class Owner:
        def __init__(self):
            self.binds = 0

        def bind_active(self, app_name, verified=False):
            self.binds += 1
            return True

    class Env:
        def _get_obs(self):
            raise AssertionError("screenshot/VLM fallback should not run")

    owner = Owner()
    monkeypatch.setattr(
        app_lifecycle.mobile_ops, "is_android_env", lambda _env: False)
    monkeypatch.setattr(
        app_lifecycle, "_surface_app_window",
        lambda _env, _app: next(surfaces))
    monkeypatch.setattr(app_lifecycle.time, "sleep", lambda _seconds: None)

    assert app_lifecycle.wait_for_app(
        Env(),
        "setting",
        appear_check=lambda _shot: (_ for _ in ()).throw(
            AssertionError("visual focus judge should not run")),
        desktop_window_owner=owner,
    ) is True
    assert owner.binds == 1


def test_engine_uses_desktop_owner_and_returns_unknown_without_vlm() -> None:
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine._is_touch = False
    engine.app_name = "setting"
    engine.env = object()
    engine.desktop_window_owner = SimpleNamespace(
        last_reason="desktop active window belongs to target",
        is_foreground=lambda: True,
    )
    engine.focus_guard = AppFocusGuard(
        engine.env,
        engine.app_name,
        is_touch=False,
        desktop_window_owner=engine.desktop_window_owner,
    )

    assert engine._is_target_app_foreground(b"frame") is True
    assert engine.focus_guard.last_reason == (
        "desktop active window belongs to target")

    engine.desktop_window_owner = SimpleNamespace(
        last_reason="desktop active window unavailable",
        is_foreground=lambda: None,
    )
    engine.focus_guard.desktop_window_owner = engine.desktop_window_owner
    assert engine._is_target_app_foreground(b"frame") is None
    assert engine.focus_guard.last_kind == "unknown"


def test_focus_unknown_does_not_back_or_relaunch() -> None:
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.focus_guard = SimpleNamespace(
        last_kind="unknown",
        last_reason="desktop active window unavailable",
        on_app=lambda _shot: None,
    )
    engine.relaunch_fn = lambda: (_ for _ in ()).throw(
        AssertionError("focus_unknown must not relaunch"))
    engine._settle_enabled = False
    engine._action_count = 0
    engine.review_debug = SimpleNamespace(record_event=lambda *_a, **_k: None)
    engine.env = SimpleNamespace(
        step=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("focus_unknown must not mutate the GUI")))

    obs, relaunched, on_app = engine._ensure_on_app(
        {"screenshot": b"frame"})

    assert obs == {"screenshot": b"frame"}
    assert relaunched is False
    assert on_app is False
    assert engine._last_off_app_kind == "focus_unknown"


def test_window_crop_refresh_is_read_only(monkeypatch) -> None:
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine._is_touch = False
    engine.app_name = "setting"
    engine.env = object()
    engine.perception = SimpleNamespace(window_px_override=None)
    bbox = [140, 54, 1210, 773]

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_engine."
        "_get_app_window_bbox",
        lambda _env, _app_name: bbox,
    )

    engine._refresh_window_crop()

    assert engine.perception.window_px_override == bbox
