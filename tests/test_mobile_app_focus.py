from __future__ import annotations

from types import SimpleNamespace

from gui_rewalk.src.core.graph import mobile_ops


class _Controller:
    def __init__(self, current: str, dump: str = "") -> None:
        self.current = current
        self.dump = dump
        self.dump_calls = 0

    def current_activity(self) -> str:
        return self.current

    def adb_shell(self, _command: str, timeout: int = 10) -> str:
        assert timeout == 10
        self.dump_calls += 1
        return self.dump


def _env(current: str, dump: str = ""):
    return SimpleNamespace(
        platform="android",
        controller=_Controller(current, dump),
    )


def _task_dump(task_id: int, affinity: str, current: str) -> str:
    return (
        f"  * Task{{abc #{task_id} type=standard "
        f"A=1000:{affinity} U=0 visible=true}}\n"
        f"    topResumedActivity=ActivityRecord{{def u0 {current} "
        f"t{task_id}}}\n"
    )


def test_foreground_exact_package_needs_no_task_dump(monkeypatch) -> None:
    monkeypatch.setattr(
        mobile_ops, "get_android_package",
        lambda _app: "com.example.clock",
    )
    env = _env("com.example.clock/.MainActivity")

    assert mobile_ops.is_app_foreground(env, "clock") is True
    assert env.controller.dump_calls == 0


def test_delegated_activity_in_target_rooted_task_is_on_app(monkeypatch) -> None:
    package = "com.example.clock"
    delegated = "com.android.permissioncontroller/.ManagePermissionsActivity"
    monkeypatch.setattr(
        mobile_ops, "get_android_package", lambda _app: package)
    env = _env(
        delegated,
        _task_dump(42, f"{package}.root", delegated),
    )

    assert mobile_ops.is_app_foreground(env, "clock") is True
    assert env.controller.dump_calls == 1


def test_activity_in_another_rooted_task_is_off_app(monkeypatch) -> None:
    monkeypatch.setattr(
        mobile_ops, "get_android_package",
        lambda _app: "com.example.clock",
    )
    external = "com.android.chrome/.Main"
    env = _env(external, _task_dump(7, "com.android.chrome", external))

    assert mobile_ops.is_app_foreground(env, "clock") is False
