"""Offline regression for the AndroidEnv loader log guard.

The test supplies fake ``absl.logging`` and AndroidEnv/AndroidWorld modules, so
it neither imports nor starts a real ``android_env`` runtime.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.env import android_gui_gen_env  # noqa: E402


class LoaderFailure(RuntimeError):
    """Distinct loader failure used to verify exception propagation."""


def _package(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []
    return module


def _fake_runtime(*, loader_error: Exception | None = None):
    events: list[tuple[str, int]] = []
    emitted_info: list[str] = []

    absl_package = _package("absl")
    absl_logging = types.ModuleType("absl.logging")
    absl_logging.INFO = 0
    absl_logging.WARNING = -1
    absl_logging.current_verbosity = absl_logging.INFO

    def get_verbosity():
        return absl_logging.current_verbosity

    def set_verbosity(verbosity):
        absl_logging.current_verbosity = verbosity
        events.append(("set", verbosity))

    def info(message):
        if absl_logging.current_verbosity >= absl_logging.INFO:
            emitted_info.append(message)

    absl_logging.get_verbosity = get_verbosity
    absl_logging.set_verbosity = set_verbosity
    absl_logging.info = info
    absl_package.logging = absl_logging

    android_env_package = _package("android_env")
    loader = types.ModuleType("android_env.loader")

    def load(config):
        del config
        events.append(("load", absl_logging.current_verbosity))
        absl_logging.info("third-party loader detail")
        if loader_error is not None:
            raise loader_error
        return object()

    loader.load = load
    android_env_package.loader = loader

    components_package = _package("android_env.components")
    config_classes = types.ModuleType("android_env.components.config_classes")

    class Config:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    config_classes.AndroidEnvConfig = Config
    config_classes.FilesystemTaskConfig = Config
    config_classes.EmulatorConfig = Config
    config_classes.EmulatorLauncherConfig = Config
    config_classes.AdbControllerConfig = Config
    components_package.config_classes = config_classes

    android_world_package = _package("android_world")
    world_env_package = _package("android_world.env")
    world_controller = types.ModuleType(
        "android_world.env.android_world_controller"
    )
    world_controller._write_default_task_proto = lambda: "fake-task.textproto"

    class FakeWorldController:
        def __init__(self, env_instance, *, install_a11y_forwarding_app):
            self.env_instance = env_instance
            self.install_a11y_forwarding_app = install_a11y_forwarding_app

    world_controller.AndroidWorldController = FakeWorldController

    interface = types.ModuleType("android_world.env.interface")

    class FakeAsyncAndroidEnv:
        def __init__(self, controller):
            self.controller = controller

    interface.AsyncAndroidEnv = FakeAsyncAndroidEnv
    world_env_package.android_world_controller = world_controller
    world_env_package.interface = interface
    android_world_package.env = world_env_package

    modules = {
        "absl": absl_package,
        "absl.logging": absl_logging,
        "android_env": android_env_package,
        "android_env.loader": loader,
        "android_env.components": components_package,
        "android_env.components.config_classes": config_classes,
        "android_world": android_world_package,
        "android_world.env": world_env_package,
        "android_world.env.android_world_controller": world_controller,
        "android_world.env.interface": interface,
    }
    return modules, absl_logging, events, emitted_info


def _env_stub():
    return SimpleNamespace(console_port=5554, grpc_port=8554, adb_path="adb")


class AndroidEnvLogGuardTest(unittest.TestCase):
    def test_loader_info_is_suppressed_and_verbosity_is_restored(self):
        modules, absl_logging, events, emitted_info = _fake_runtime()

        with mock.patch.dict(sys.modules, modules), mock.patch.object(
            android_gui_gen_env,
            "AndroidController",
            side_effect=lambda controller: ("wrapped", controller),
        ):
            env = _env_stub()
            android_gui_gen_env.AndroidGUIGenEnv._connect_controller(env)

        self.assertEqual(
            events,
            [
                ("set", absl_logging.WARNING),
                ("load", absl_logging.WARNING),
                ("set", absl_logging.INFO),
            ],
        )
        self.assertEqual(emitted_info, [])
        self.assertEqual(absl_logging.current_verbosity, absl_logging.INFO)
        self.assertIsNotNone(env._aw_env)
        self.assertEqual(env.controller[0], "wrapped")


class AndroidAdbRecoveryTest(unittest.TestCase):
    def _env(self):
        env = object.__new__(android_gui_gen_env.AndroidGUIGenEnv)
        env.adb_path = "adb"
        env.serial = "emulator-5554"
        env._aw_env = None
        return env

    def test_restart_adb_server_waits_for_target_without_touching_network(self):
        env = self._env()
        results = [
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=0, stdout="daemon started", stderr=""),
        ]
        with mock.patch.object(
            android_gui_gen_env.subprocess, "run", side_effect=results
        ) as run, mock.patch.object(
            env, "_device_online", side_effect=[False, True]
        ), mock.patch.object(android_gui_gen_env.time, "sleep"):
            self.assertTrue(env._restart_adb_server(wait_for_target=True))

        self.assertEqual(run.call_args_list[0].args[0], ["adb", "kill-server"])
        self.assertEqual(run.call_args_list[1].args[0], ["adb", "start-server"])
        self.assertEqual(run.call_count, 2)

    def test_shared_host_can_disable_adb_server_restart(self):
        env = self._env()
        with mock.patch.dict(
            android_gui_gen_env.os.environ,
            {"GUI_REWALK_ALLOW_ADB_RESTART": "0"},
        ), mock.patch.object(
            android_gui_gen_env.subprocess, "run"
        ) as run, mock.patch.object(
            env, "_device_online", return_value=False
        ):
            self.assertFalse(env._restart_adb_server(wait_for_target=True))

        run.assert_not_called()

    def test_get_obs_recovers_once_and_retries_current_screenshot(self):
        env = self._env()
        expected = object()
        env.controller = mock.Mock()
        env.controller.get_screenshot.side_effect = [
            RuntimeError("no buffer space"), expected,
        ]
        with mock.patch.object(
            env, "_recover_adb_transport", return_value=True
        ) as recover:
            observation = env._get_obs()

        self.assertIs(observation["screenshot"], expected)
        recover.assert_called_once_with()
        self.assertEqual(env.controller.get_screenshot.call_count, 2)

    def test_loader_exception_still_restores_verbosity(self):
        error = LoaderFailure("fake loader failure")
        modules, absl_logging, events, emitted_info = _fake_runtime(
            loader_error=error
        )

        with mock.patch.dict(sys.modules, modules):
            env = _env_stub()
            with self.assertRaisesRegex(LoaderFailure, "fake loader failure"):
                android_gui_gen_env.AndroidGUIGenEnv._connect_controller(env)

        self.assertEqual(
            events,
            [
                ("set", absl_logging.WARNING),
                ("load", absl_logging.WARNING),
                ("set", absl_logging.INFO),
            ],
        )
        self.assertEqual(emitted_info, [])
        self.assertEqual(absl_logging.current_verbosity, absl_logging.INFO)


if __name__ == "__main__":
    unittest.main()
