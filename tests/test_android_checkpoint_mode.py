"""Android run checkpoints need one writable overlay, not the shared read-only mode."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import gui_rewalk.env.android_gui_gen_env as android_env
from gui_rewalk.env.android_gui_gen_env import AndroidGUIGenEnv


def test_run_checkpoint_mode_omits_read_only_emulator_flag() -> None:
    env = object.__new__(AndroidGUIGenEnv)
    env.emulator_path = "emulator"
    env.avd_name = "guitraverse_mobile_seed"
    env.console_port = 5612
    env.grpc_port = 8612
    env.boot_from_snapshot = True
    env.snapshot_name = "guitraverse_mobile_clean_base_v1"
    env.headless = True
    env.allow_snapshot_writes = True

    command = env._emulator_command()

    assert "-read-only" not in command
    assert command[-1] == "-no-window"


def test_headless_ime_uses_the_device_accepted_enable_set_form(
    tmp_path, monkeypatch,
) -> None:
    apk = tmp_path / "ime.apk"
    apk.write_bytes(b"ime")
    monkeypatch.setattr(android_env, "HEADLESS_IME_APK_PATH", apk)
    monkeypatch.setattr(
        android_env, "HEADLESS_IME_SHA256", hashlib.sha256(b"ime").hexdigest())
    monkeypatch.setattr(
        android_env.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    env = object.__new__(AndroidGUIGenEnv)
    env.adb_path = "adb"
    env.serial = "emulator-5612"
    calls = []

    def adb(*args, **_kwargs):
        calls.append(args)
        if args[:3] == ("shell", "settings", "get"):
            return android_env.HEADLESS_IME_ID
        return ""

    env._adb = adb
    env._configure_headless_input_method()

    assert ("shell", "ime", "enable", android_env.HEADLESS_IME_ID) in calls
    assert ("shell", "ime", "set", android_env.HEADLESS_IME_ID) in calls


def test_default_keyboard_policy_is_verified_after_attach_and_reset(monkeypatch):
    calls = []
    monkeypatch.setattr(AndroidGUIGenEnv, '_start_emulator', lambda self: None)
    monkeypatch.setattr(AndroidGUIGenEnv, '_connect_controller', lambda self: None)
    def adb(self, *args, **kwargs):
        calls.append(args)
        return '0\n' if args[:3] == ('shell', 'settings', 'get') else ''
    monkeypatch.setattr(AndroidGUIGenEnv, '_adb', adb)
    env = AndroidGUIGenEnv(avd_name="guitraverse_mobile_seed")
    put = ('shell', 'settings', 'put', 'secure', 'show_ime_with_hard_keyboard', '0')
    get = ('shell', 'settings', 'get', 'secure', 'show_ime_with_hard_keyboard')
    assert calls == [put, get]
    env._device_online = lambda: True
    env._boot_completed = lambda: True
    env.controller = SimpleNamespace(press_home=lambda: None)
    env._get_obs = lambda: {}
    monkeypatch.setattr(android_env.time, 'sleep', lambda _: None)
    env.reset()
    assert calls == [put, get, put, get]


def test_keyboard_policy_does_not_silently_accept_failed_setting(monkeypatch):
    import pytest
    env = object.__new__(AndroidGUIGenEnv)
    env._adb = lambda *args, **kwargs: '1\n'
    with pytest.raises(RuntimeError, match='keyboard'):
        env._suppress_soft_keyboard()
