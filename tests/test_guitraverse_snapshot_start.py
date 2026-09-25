from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

from gui_rewalk import run_visual_traversal
from gui_rewalk.env import android_gui_gen_env
from gui_rewalk.env.android_gui_gen_env import AndroidGUIGenEnv


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "ops" / "run_guitraverse_seeded_mobile.ps1"


def _env(*, snapshot_name="init_state", boot_from_snapshot=False):
    env = object.__new__(AndroidGUIGenEnv)
    env.emulator_path = "emulator"
    env.avd_name = "guitraverse_mobile_seed"
    env.console_port = 5612
    env.grpc_port = 8612
    env.snapshot_name = snapshot_name
    env.boot_from_snapshot = boot_from_snapshot
    env.headless = True
    return env


def test_default_android_emulator_command_does_not_force_snapshot_load():
    command = _env()._emulator_command()

    assert command[:3] == ["emulator", "-avd", "guitraverse_mobile_seed"]
    assert "-read-only" in command
    assert "-no-snapshot-save" in command
    assert "-snapshot" not in command


def test_explicit_android_snapshot_is_loaded_into_read_only_overlay():
    command = _env(
        snapshot_name="guitraverse_mobile_seed_v1",
        boot_from_snapshot=True,
    )._emulator_command()

    assert "-read-only" in command
    assert "-no-snapshot-save" in command
    feature_index = command.index("-feature")
    assert command[feature_index + 1] == "-Vulkan"
    index = command.index("-snapshot")
    assert command[index + 1] == "guitraverse_mobile_seed_v1"


def test_android_keyboard_visibility_uses_actual_input_view_flags():
    env = _env()
    env._adb = lambda *_args, **_kwargs: (
        "mShowRequested=true mInputShown=true mInputViewShown=true")

    assert env.is_soft_keyboard_visible() is True

    env._adb = lambda *_args, **_kwargs: (
        "mShowRequested=true mInputShown=false mIsInputViewShown=true")
    assert env.is_soft_keyboard_visible() is False

    env._adb = lambda *_args, **_kwargs: "no supported input-view flag"
    assert env.is_soft_keyboard_visible() is None

    env._adb = lambda *_args, **_kwargs: (
        f"mCurMethodId={android_gui_gen_env.HEADLESS_IME_ID}\n"
        "mInputShown=true mIsInputViewShown=false")
    assert env.is_soft_keyboard_visible() is False


def test_android_active_text_input_uses_served_connection_state():
    env = _env()
    env._adb = lambda *_args, **_kwargs: (
        "mServedView=android.widget.EditText{abc .F......}\n"
        "mServedInputConnection=RemoteInputConnectionImpl{"
        "finished=false mParentInputMethodManager.isActive()=true}")

    assert env.has_active_text_input() is True

    env._adb = lambda *_args, **_kwargs: "mServedInputConnection=null"
    assert env.has_active_text_input() is False

    env._adb = lambda *_args, **_kwargs: "no served connection field"
    assert env.has_active_text_input() is None


def test_pinned_headless_ime_asset_matches_release_digest():
    path = android_gui_gen_env.HEADLESS_IME_APK_PATH

    assert path.is_file()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        android_gui_gen_env.HEADLESS_IME_SHA256)


def test_named_snapshot_configures_pinned_headless_ime(
    tmp_path, monkeypatch,
):
    env = _env(
        snapshot_name="guitraverse_mobile_seed_v2",
        boot_from_snapshot=True,
    )
    env.adb_path = "adb"
    env.serial = "emulator-5612"
    apk = tmp_path / "headless-ime.apk"
    apk.write_bytes(b"pinned headless ime")
    monkeypatch.setattr(android_gui_gen_env, "HEADLESS_IME_APK_PATH", apk)
    monkeypatch.setattr(
        android_gui_gen_env,
        "HEADLESS_IME_SHA256",
        hashlib.sha256(apk.read_bytes()).hexdigest(),
    )
    shell_calls = []
    selected = {"attempts": 0}

    def adb(*args, **_kwargs):
        shell_calls.append(args)
        if args[:4] == ("shell", "ime", "set", "--user"):
            selected["attempts"] += 1
        if args == (
                "shell", "settings", "get", "secure",
                "default_input_method"):
            return (
                android_gui_gen_env.HEADLESS_IME_ID
                if selected["attempts"] >= 2 else "old.ime/.Old")
        return ""

    env._adb = adb
    installs = []
    monkeypatch.setattr(
        android_gui_gen_env.subprocess,
        "run",
        lambda command, **kwargs: (
            installs.append((command, kwargs))
            or subprocess.CompletedProcess(command, 0, "Success\n", "")
        ),
    )
    monkeypatch.setattr(android_gui_gen_env.time, "sleep", lambda _seconds: None)

    env._configure_headless_input_method()

    assert installs[0][0] == [
        "adb", "-s", "emulator-5612", "install", "-r", "-g", str(apk)]
    assert selected["attempts"] == 2
    assert shell_calls[-1] == (
        "shell", "settings", "get", "secure", "default_input_method")


def test_named_snapshot_rejects_unpinned_headless_ime(
    tmp_path, monkeypatch,
):
    env = _env(
        snapshot_name="guitraverse_mobile_seed_v2",
        boot_from_snapshot=True,
    )
    apk = tmp_path / "headless-ime.apk"
    apk.write_bytes(b"unexpected artifact")
    monkeypatch.setattr(android_gui_gen_env, "HEADLESS_IME_APK_PATH", apk)
    monkeypatch.setattr(android_gui_gen_env, "HEADLESS_IME_SHA256", "0" * 64)

    with pytest.raises(RuntimeError, match="digest mismatch"):
        env._configure_headless_input_method()


def test_existing_serial_with_wrong_avd_fails_before_controller_attach():
    env = _env(
        snapshot_name="guitraverse_mobile_seed_v1",
        boot_from_snapshot=True,
    )
    env.serial = "emulator-5612"
    env._device_online = lambda: True
    env._boot_completed = lambda: True
    env._adb = lambda *_args, **_kwargs: "Small_Phone_seeded\nOK\n"

    with pytest.raises(RuntimeError, match="AVD mismatch"):
        env._start_emulator()


def test_named_snapshot_run_rejects_an_already_running_serial():
    env = _env(
        snapshot_name="guitraverse_mobile_seed_v2",
        boot_from_snapshot=True,
    )
    env.serial = "emulator-5612"
    env._device_online = lambda: True
    env._boot_completed = lambda: True
    env._adb = lambda *_args, **_kwargs: "guitraverse_mobile_seed\nOK\n"

    with pytest.raises(RuntimeError, match="unused serial"):
        env._start_emulator()


def test_named_snapshot_run_rejects_an_offline_serial(monkeypatch):
    env = _env(
        snapshot_name="guitraverse_mobile_seed_v2",
        boot_from_snapshot=True,
    )
    env.serial = "emulator-5612"
    env._device_online = lambda: False
    env._serial_present = lambda: True
    env._restart_adb_server = lambda **_kwargs: False
    monkeypatch.setattr(
        "gui_rewalk.env.android_gui_gen_env.subprocess.Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("occupied serial must fail before Popen")),
    )

    with pytest.raises(RuntimeError, match="unused serial"):
        env._start_emulator()


@pytest.mark.parametrize("probe", [
    subprocess.TimeoutExpired("adb devices", 15),
    subprocess.CompletedProcess(["adb", "devices"], 1, "", "failed"),
    subprocess.CompletedProcess(["adb", "devices"], 0, "", ""),
])
def test_named_snapshot_serial_probe_failure_is_fail_closed(
    monkeypatch, probe,
):
    env = _env(
        snapshot_name="guitraverse_mobile_seed_v2",
        boot_from_snapshot=True,
    )
    env.serial = "emulator-5612"
    env.adb_path = "adb"
    env._device_online = lambda: False
    if isinstance(probe, BaseException):
        monkeypatch.setattr(
            "gui_rewalk.env.android_gui_gen_env.subprocess.run",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(probe),
        )
    else:
        monkeypatch.setattr(
            "gui_rewalk.env.android_gui_gen_env.subprocess.run",
            lambda *_args, **_kwargs: probe,
        )
    monkeypatch.setattr(
        "gui_rewalk.env.android_gui_gen_env.subprocess.Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("failed ownership probe must not start Popen")),
    )

    with pytest.raises(RuntimeError, match="cannot verify serial availability"):
        env._start_emulator()


class _OwnedProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False
        self.waited = []

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout):
        self.waited.append(timeout)
        return 0


def test_boot_timeout_terminates_the_owned_emulator(monkeypatch):
    env = _env(
        snapshot_name="guitraverse_mobile_seed_v2",
        boot_from_snapshot=True,
    )
    env.serial = "emulator-5612"
    env.adb_path = "adb"
    env.boot_timeout = 0
    env._device_online = lambda: False
    env._restart_adb_server = lambda **_kwargs: False
    process = _OwnedProcess()
    monkeypatch.setattr(
        "gui_rewalk.env.android_gui_gen_env.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["adb", "devices"], 0, "List of devices attached\n", ""),
    )
    monkeypatch.setattr(
        "gui_rewalk.env.android_gui_gen_env.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )

    with pytest.raises(RuntimeError, match="did not boot"):
        env._start_emulator()

    assert process.terminated is True
    assert process.waited == [10]
    assert env._emulator_proc is None


def test_named_snapshot_close_terminates_the_owned_emulator(monkeypatch):
    env = _env(
        snapshot_name="guitraverse_mobile_seed_v2",
        boot_from_snapshot=True,
    )
    env._aw_env = None
    env.provider = type("Provider", (), {"stop_emulator": lambda self: None})()
    process = _OwnedProcess()
    env._emulator_proc = process
    monkeypatch.delenv("GUI_REWALK_KILL_EMULATOR", raising=False)

    env.close()

    assert process.terminated is True
    assert process.waited == [10]
    assert env._emulator_proc is None


def test_named_snapshot_close_is_idempotent_and_never_kills_by_serial(
    monkeypatch,
):
    env = _env(
        snapshot_name="guitraverse_mobile_seed_v2",
        boot_from_snapshot=True,
    )
    env._aw_env = None
    calls = []
    env.provider = type("Provider", (), {
        "stop_emulator": lambda self: calls.append("serial-kill"),
    })()
    env._emulator_proc = _OwnedProcess()
    monkeypatch.delenv("GUI_REWALK_KILL_EMULATOR", raising=False)

    env.close()
    env.close()

    assert calls == []


def test_owned_process_uses_kill_only_after_terminate_timeout():
    class _StubbornProcess(_OwnedProcess):
        def wait(self, timeout):
            self.waited.append(timeout)
            if not self.killed:
                raise subprocess.TimeoutExpired("emulator", timeout)
            return 0

    env = _env(
        snapshot_name="guitraverse_mobile_seed_v2",
        boot_from_snapshot=True,
    )
    process = _StubbornProcess()
    env._emulator_proc = process

    env._terminate_owned_emulator()

    assert process.terminated is True
    assert process.killed is True
    assert process.waited == [10, 5]
    assert env._emulator_proc is None


def test_ordinary_close_keeps_emulator_unless_explicitly_requested(monkeypatch):
    env = _env(boot_from_snapshot=False)
    env._aw_env = None
    env.provider = type("Provider", (), {"stop_emulator": lambda self: None})()
    process = _OwnedProcess()
    env._emulator_proc = process
    monkeypatch.delenv("GUI_REWALK_KILL_EMULATOR", raising=False)

    env.close()
    assert process.terminated is False

    monkeypatch.setenv("GUI_REWALK_KILL_EMULATOR", "1")
    env.close()
    assert process.terminated is True


def test_android_env_step_forwards_controller_action_error(monkeypatch):
    env = object.__new__(AndroidGUIGenEnv)
    env.action_space = "gen_data"
    env.is_environment_used = False
    env._step_no = 0

    class _Controller:
        last_action_error = ""

        def execute_gui_action(self, _action):
            self.last_action_error = "input_text_unsupported_non_ascii"

    env.controller = _Controller()
    env._get_obs = lambda: {"screenshot": b"after", "terminal": None}
    monkeypatch.setattr(
        "gui_rewalk.env.android_gui_gen_env.time.sleep", lambda _seconds: None)

    observation = env.step({"action_type": "input_text", "text": "闹钟"})

    assert observation["action_error"] == "input_text_unsupported_non_ascii"


def test_traversal_cli_accepts_explicit_android_snapshot(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "run_visual_traversal.py",
        "--vm_provider", "android",
        "--android_snapshot_name", "guitraverse_mobile_seed_v1",
    ])

    args = run_visual_traversal.parse_args()

    assert args.android_snapshot_name == "guitraverse_mobile_seed_v1"


def test_traversal_cli_keeps_empty_snapshot_as_existing_default(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_visual_traversal.py"])

    args = run_visual_traversal.parse_args()

    assert args.android_snapshot_name == ""


def test_invalid_android_snapshot_name_is_rejected_before_emulator_start(
    monkeypatch,
):
    monkeypatch.setattr(sys, "argv", [
        "run_visual_traversal.py",
        "--vm_provider", "android",
        "--android_snapshot_name", "../default boot",
    ])

    with pytest.raises(SystemExit) as exc:
        run_visual_traversal.parse_args()

    assert exc.value.code == 2


def test_seeded_runner_plan_is_read_only_and_never_requests_clean_start():
    result = subprocess.run([
        "powershell.exe", "-NoProfile", "-File", str(RUNNER),
        "-PlanOnly",
        "-AppName", "android_clock",
        "-SnapshotName", "guitraverse_mobile_seed_v1",
        "-ConsolePort", "5612",
        "-GrpcPort", "8612",
    ], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    arguments = payload["arguments"]
    assert arguments[0].endswith("gui_rewalk\\run_visual_traversal.py")
    assert arguments[arguments.index("--avd_name") + 1] == (
        "guitraverse_mobile_seed")
    assert arguments[arguments.index("--android_snapshot_name") + 1] == (
        "guitraverse_mobile_seed_v1")
    assert "--modular-explore" in arguments
    assert "--clean_start" not in arguments


def test_seeded_runner_requires_an_explicit_clean_base_snapshot():
    result = subprocess.run([
        "powershell.exe", "-NoProfile", "-File", str(RUNNER),
        "-PlanOnly",
        "-AppName", "simple_calendar_pro",
    ], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    arguments = payload["arguments"]
    assert payload["snapshot_name"] == ""
    assert arguments[arguments.index("--android_snapshot_name") + 1] == (
        "")
    assert arguments[arguments.index("--seed_manifest") + 1].endswith(
        "data\\dev_seed\\guitraverse_explore_seed_v2.yaml")


def test_seeded_runner_refuses_to_start_without_an_explicit_snapshot():
    result = subprocess.run([
        "powershell.exe", "-NoProfile", "-File", str(RUNNER),
        "-AppName", "broccoli",
    ], capture_output=True, text=True, timeout=30)

    assert result.returncode != 0
    assert "SnapshotName must name an explicitly created clean base" in result.stderr
