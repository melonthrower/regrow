# Copyright (c) 2026
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""AndroidGUIGenEnv — mobile counterpart of ``DesktopGUIGenEnv``.

Presents the same surface the traversal engine relies on:

* ``env.controller``  → :class:`AndroidController`
* ``env._get_obs()``  → {"screenshot", "terminal"}
* ``env.reset()`` / ``env.close()``
* ``env.provider.save_state / revert_to_snapshot`` → AVD snapshots
* ``env.platform == "android"`` lets traversal pick mobile code paths

The Android emulator must be created beforehand (an AVD name is required);
this class starts it with gRPC enabled, waits for boot, and connects
android_world's controller on top.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

import gymnasium as gym

from gui_rewalk.env.android_controller import AndroidController

logger = logging.getLogger("desktopenv.android.env")

HEADLESS_IME_APK_PATH = (
    Path(__file__).resolve().parents[2]
    / "third_party"
    / "android_ime"
    / "appium_settings_v7.1.3"
    / "io.appium.settings-v7.1.3.apk"
)
HEADLESS_IME_SHA256 = (
    "16af5bb042573f300755ce09c84811ef9f2ffc585a3ed0b930a44c599df2fa32"
)
HEADLESS_IME_ID = "io.appium.settings/.UnicodeIME"


def _default_sdk_root() -> str:
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(var)
        if value and os.path.isdir(value):
            return value
    guess = os.path.join(
        os.path.expanduser("~"), "AppData", "Local", "Android", "Sdk"
    )
    if os.path.isdir(guess):
        return guess
    return os.path.join(os.path.expanduser("~"), "Android", "Sdk")


class AndroidVirtualDeviceProvider:
    """Snapshot/lifecycle provider backed by the emulator console.

    Mirrors the OSWorld provider interface (``save_state``,
    ``revert_to_snapshot``, ``stop_emulator``) used by the scenario pipeline
    so conditional-branch collection works on mobile too.
    """

    def __init__(self, adb_path: str, serial: str):
        self.adb_path = adb_path
        self.serial = serial

    def _emu(self, *args: str, timeout: float = 120) -> str:
        cmd = [self.adb_path, "-s", self.serial, "emu", *args]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return (result.stdout or "") + (result.stderr or "")

    def save_state(self, path_to_vm: str = "", snapshot_name: str = "init_state"):
        out = self._emu("avd", "snapshot", "save", snapshot_name)
        logger.info("AVD snapshot save '%s': %s", snapshot_name, out.strip()[:200])

    def revert_to_snapshot(self, path_to_vm: str = "", snapshot_name: str = "init_state"):
        out = self._emu("avd", "snapshot", "load", snapshot_name)
        logger.info("AVD snapshot load '%s': %s", snapshot_name, out.strip()[:200])
        return path_to_vm

    def delete_snapshot(self, path_to_vm: str = "", snapshot_name: str = ""):
        out = self._emu("avd", "snapshot", "delete", snapshot_name)
        logger.info("AVD snapshot delete '%s': %s", snapshot_name, out.strip()[:200])

    def list_snapshots(self) -> str:
        return self._emu("avd", "snapshot", "list")

    def start_emulator(self, *args, **kwargs):
        # Lifecycle is owned by AndroidGUIGenEnv._start_emulator
        pass

    def stop_emulator(self, path_to_vm: str = ""):
        try:
            out = self._emu("kill", timeout=30)
            logger.info("Emulator kill: %s", out.strip()[:200])
        except Exception as exc:
            logger.warning("Failed to stop emulator: %s", exc)

    def get_ip_address(self, path_to_vm: str = "") -> str:
        return self.serial


class AndroidGUIGenEnv(gym.Env):
    """Android environment with the DesktopGUIGenEnv interface."""

    platform = "android"

    def __init__(
        self,
        avd_name: str,
        console_port: int = 5554,
        grpc_port: int = 8554,
        sdk_root: str = "",
        snapshot_name: str = "init_state",
        boot_from_snapshot: bool = False,
        action_space: str = "gen_data",
        screen_size: Tuple[int, int] = (1080, 2400),
        headless: bool = False,
        boot_timeout: float = 300.0,
        allow_snapshot_writes: bool = False,
        **_: Any,
    ):
        self.avd_name = avd_name
        self.console_port = console_port
        self.grpc_port = grpc_port
        self.sdk_root = sdk_root or _default_sdk_root()
        self.adb_path = os.path.join(self.sdk_root, "platform-tools", "adb.exe")
        if not os.path.exists(self.adb_path):
            self.adb_path = os.path.join(self.sdk_root, "platform-tools", "adb")
        self.emulator_path = os.path.join(self.sdk_root, "emulator", "emulator.exe")
        if not os.path.exists(self.emulator_path):
            self.emulator_path = os.path.join(self.sdk_root, "emulator", "emulator")
        self.serial = f"emulator-{console_port}"
        self.snapshot_name = snapshot_name
        self.boot_from_snapshot = bool(boot_from_snapshot)
        self.allow_snapshot_writes = bool(allow_snapshot_writes)
        self.headless = headless
        self.require_terminal = False
        self.os_type = "Android"
        self.action_space = action_space
        self.screen_size = screen_size
        self.boot_timeout = boot_timeout
        self._emulator_proc: Optional[subprocess.Popen] = None
        self._aw_env = None

        self.provider = AndroidVirtualDeviceProvider(self.adb_path, self.serial)
        self.provider_name = "android"
        self.path_to_vm = avd_name  # interface parity with desktop env
        self.is_environment_used = False

        self.instruction = None
        self._traj_no: int = -1
        self._step_no: int = 0
        self.action_history: List[Dict[str, Any]] = []

        logger.info("Initializing Android environment (AVD=%s)...", avd_name)
        self._start_emulator()
        self._suppress_soft_keyboard()
        self._connect_controller()

    # ── Emulator lifecycle ───────────────────────────────────────────────

    def _adb(self, *args: str, timeout: float = 30) -> str:
        result = subprocess.run(
            [self.adb_path, "-s", self.serial, *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return (result.stdout or "") + (result.stderr or "")

    def _suppress_soft_keyboard(self) -> None:
        """Keep the hardware-keyboard traversal default after attach or reset."""
        self._adb("shell", "settings", "put", "secure",
                  "show_ime_with_hard_keyboard", "0", timeout=10)
        value = self._adb("shell", "settings", "get", "secure",
                          "show_ime_with_hard_keyboard", timeout=10).strip()
        if value != "0":
            raise RuntimeError(f"soft keyboard suppression not applied: {value!r}")
        logger.info("Verified show_ime_with_hard_keyboard=0 on %s", self.serial)

    def is_soft_keyboard_visible(self) -> Optional[bool]:
        """Read the current Android IME input-view state without changing it."""
        try:
            output = self._adb(
                "shell", "dumpsys", "input_method", timeout=10)
        except Exception:
            return None
        if f"mCurMethodId={HEADLESS_IME_ID}" in output:
            return False
        for field in (
                "mInputShown", "mInputViewShown", "mIsInputViewShown"):
            flags = re.findall(
                rf"\b{field}\s*=\s*(true|false)\b",
                output,
                flags=re.IGNORECASE,
            )
            if flags:
                return any(value.casefold() == "true" for value in flags)
        return None

    def has_active_text_input(self) -> Optional[bool]:
        """Return whether Android exposes one live served input connection."""
        try:
            output = self._adb(
                "shell", "dumpsys", "input_method", timeout=10)
        except Exception:
            return None
        match = re.search(
            r"^\s*mServedInputConnection=(.+)$",
            output,
            flags=re.MULTILINE,
        )
        if match is None:
            return None
        value = match.group(1).strip().casefold()
        if value == "null":
            return False
        return "finished=false" in value and "isactive()=true" in value

    def _configure_headless_input_method(self) -> None:
        """Install and select the pinned no-view IME in an owned overlay."""
        configured = str(os.environ.get(
            "GUI_REWALK_HEADLESS_IME_APK", "") or "").strip()
        apk_path = (
            Path(configured).expanduser()
            if configured else HEADLESS_IME_APK_PATH
        )
        if not apk_path.is_file():
            raise RuntimeError(f"headless IME APK is missing: {apk_path}")
        digest = hashlib.sha256(apk_path.read_bytes()).hexdigest()
        if digest != HEADLESS_IME_SHA256:
            raise RuntimeError(
                "headless IME APK digest mismatch: "
                f"expected {HEADLESS_IME_SHA256}, got {digest}")
        installed = subprocess.run(
            [
                self.adb_path, "-s", self.serial,
                "install", "-r", "-g", str(apk_path),
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if installed.returncode != 0:
            detail = (installed.stderr or installed.stdout or "").strip()
            raise RuntimeError(
                "headless IME install failed: " + detail[:300])
        for _attempt in range(10):
            self._adb(
                "shell", "ime", "enable", HEADLESS_IME_ID, timeout=10,
            )
            self._adb(
                "shell", "ime", "set", HEADLESS_IME_ID, timeout=10,
            )
            current = self._adb(
                "shell", "settings", "get", "secure",
                "default_input_method", timeout=10,
            ).strip()
            if current == HEADLESS_IME_ID:
                logger.info(
                    "Configured pinned headless IME in snapshot overlay: %s",
                    HEADLESS_IME_ID,
                )
                return
            time.sleep(0.5)
        raise RuntimeError(
            "headless IME did not become the default input method")

    def _device_online(self) -> bool:
        try:
            result = subprocess.run(
                [self.adb_path, "devices"],
                capture_output=True, text=True, timeout=15,
            )
            for line in result.stdout.splitlines():
                if line.startswith(self.serial) and "device" in line.split():
                    return True
        except Exception:
            pass
        return False

    def _serial_present(self) -> bool:
        try:
            result = subprocess.run(
                [self.adb_path, "devices"],
                capture_output=True, text=True, timeout=15,
            )
        except Exception as exc:
            raise RuntimeError(
                "cannot verify serial availability") from exc
        output = result.stdout or ""
        if result.returncode != 0 or "List of devices attached" not in output:
            raise RuntimeError("cannot verify serial availability")
        return any(
            line.split() and line.split()[0] == self.serial
            for line in output.splitlines()
        )

    def _restart_adb_server(
        self, *, wait_for_target: bool = False, timeout: float = 30.0
    ) -> bool:
        """Restart the host ADB daemon without touching host networking."""
        allow_restart = str(os.environ.get(
            "GUI_REWALK_ALLOW_ADB_RESTART", "1"
        )).strip().casefold() not in {"0", "false", "no"}
        if not allow_restart:
            logger.warning(
                "ADB restart disabled for shared host; target=%s", self.serial
            )
            return self._device_online() if wait_for_target else False
        logger.warning("Restarting ADB server for target %s", self.serial)
        try:
            subprocess.run(
                [self.adb_path, "kill-server"],
                capture_output=True, text=True, timeout=15,
            )
            started = subprocess.run(
                [self.adb_path, "start-server"],
                capture_output=True, text=True, timeout=20,
            )
            if started.returncode != 0:
                logger.warning(
                    "ADB server restart failed: %s",
                    ((started.stdout or "") + (started.stderr or "")).strip()[:300],
                )
                return False
        except Exception as exc:
            logger.warning("ADB server restart failed: %s", exc)
            return False

        if not wait_for_target:
            return True
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._device_online():
                return True
            time.sleep(1)
        logger.warning("ADB restarted but target %s did not reconnect", self.serial)
        return False

    def _recover_adb_transport(self) -> bool:
        """Perform one bounded controller recovery after a capture failure."""
        if not self._restart_adb_server(wait_for_target=True):
            return False
        try:
            if self._aw_env is not None:
                self._aw_env.close()
        except Exception:
            pass
        self._aw_env = None
        try:
            self._connect_controller()
            return True
        except Exception as exc:
            logger.warning("Failed to reconnect Android controller: %s", exc)
            return False

    def _boot_completed(self) -> bool:
        try:
            return self._adb(
                "shell", "getprop", "sys.boot_completed", timeout=10
            ).strip() == "1"
        except Exception:
            return False

    def _emulator_command(self) -> List[str]:
        cmd = [
            self.emulator_path,
            "-avd", self.avd_name,
            "-port", str(self.console_port),
            "-grpc", str(self.grpc_port),
            "-no-audio",
            # Default -read-only lets many emulator instances boot off the same
            # AVD with disposable overlays. A run-owned checkpoint explicitly
            # opts into one exclusive writable overlay so its whole-AVD state can
            # be paired with the exploration ledger.
            *([] if getattr(self, "allow_snapshot_writes", False) else ["-read-only"]),
            "-no-snapshot-save",
            "-no-boot-anim",
            # software GPU: headless servers have no display for host GPU.
            "-gpu", "swiftshader_indirect",
            # Keep snapshot/renderer compatibility with the seeded mobile AVD;
            # the leading '-' disables the Vulkan feature.
            "-feature", "-Vulkan",
        ]
        if self.boot_from_snapshot:
            cmd.extend(["-snapshot", self.snapshot_name])
        if self.headless:
            cmd.append("-no-window")
        return cmd

    def _validate_running_avd(self) -> None:
        output = self._adb("emu", "avd", "name", timeout=15)
        names = [line.strip() for line in output.splitlines()
                 if line.strip() and line.strip().upper() != "OK"]
        actual = names[0] if names else ""
        if actual != self.avd_name:
            raise RuntimeError(
                f"AVD mismatch on {self.serial}: expected {self.avd_name}, "
                f"got {actual or 'unknown'}")

    def _start_emulator(self):
        device_online = self._device_online()
        if device_online and self._boot_completed():
            self._validate_running_avd()
            if self.boot_from_snapshot:
                raise RuntimeError(
                    "named snapshot run requires an unused serial")
            logger.info("Emulator %s already running", self.serial)
            return
        if self.boot_from_snapshot and self._serial_present():
            raise RuntimeError(
                "named snapshot run requires an unused serial")
        if not device_online:
            # Rebuild only the local ADB control daemon. Never reset the host
            # network stack, DNS, adapter, or proxy.
            self._restart_adb_server()

        cmd = self._emulator_command()
        logger.info("Starting emulator: %s", " ".join(cmd))
        self._emulator_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + self.boot_timeout
        while time.time() < deadline:
            if self._device_online() and self._boot_completed():
                self._validate_running_avd()
                logger.info("Emulator booted (%s)", self.serial)
                time.sleep(5)
                return
            time.sleep(3)
        self._terminate_owned_emulator()
        raise RuntimeError(
            f"Emulator '{self.avd_name}' did not boot within {self.boot_timeout}s"
        )

    def _terminate_owned_emulator(self) -> None:
        process = getattr(self, "_emulator_proc", None)
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        except Exception as exc:
            logger.warning("Failed to stop owned emulator process: %s", exc)
        finally:
            self._emulator_proc = None

    def _connect_controller(self):
        # NOTE: 不用 env_launcher / get_controller（前者的 import 链经
        # task_evals 依赖未编译的 proto），直接
        # 构建 AndroidWorldController。
        from absl import logging as absl_logging
        from android_env import loader
        from android_env.components import config_classes
        from android_world.env import android_world_controller
        from android_world.env import interface

        config = config_classes.AndroidEnvConfig(
            task=config_classes.FilesystemTaskConfig(
                path=android_world_controller._write_default_task_proto()
            ),
            simulator=config_classes.EmulatorConfig(
                emulator_launcher=config_classes.EmulatorLauncherConfig(
                    emulator_console_port=self.console_port,
                    adb_port=self.console_port + 1,
                    grpc_port=self.grpc_port,
                ),
                adb_controller=config_classes.AdbControllerConfig(
                    adb_path=self.adb_path
                ),
            ),
        )
        previous_absl_verbosity = absl_logging.get_verbosity()
        absl_logging.set_verbosity(absl_logging.WARNING)
        try:
            env_instance = loader.load(config)
        finally:
            absl_logging.set_verbosity(previous_absl_verbosity)
        aw_controller = android_world_controller.AndroidWorldController(
            env_instance,
            install_a11y_forwarding_app=False,
        )
        self._android_env = env_instance
        self._aw_env = interface.AsyncAndroidEnv(aw_controller)
        self.controller = AndroidController(aw_controller)
        if getattr(self, "boot_from_snapshot", False):
            self._configure_headless_input_method()
            self.controller.active_text_input_check = self.has_active_text_input
        logger.info("AndroidController connected (grpc=%d)", self.grpc_port)

    def _wait_for_ready(self, timeout: int = 180):
        """Re-establish the controller after a snapshot load.

        Loading an AVD snapshot drops the adb and gRPC connections, so the
        android_world env must be rebuilt — mirrors the desktop
        ``_wait_for_ready`` contract used by the scenario pipeline.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._device_online() and self._boot_completed():
                break
            time.sleep(3)
        else:
            logger.warning("Device not ready after snapshot load")

        try:
            if self._aw_env is not None:
                self._aw_env.close()
        except Exception:
            pass
        # gRPC service needs a moment after snapshot restore
        time.sleep(5)
        self._connect_controller()

        deadline = time.time() + 60
        while time.time() < deadline:
            if self.controller.get_screenshot():
                logger.info("Android controller is ready")
                return
            time.sleep(3)
        logger.warning("Android controller not ready after snapshot load")

    # ── Snapshot API (desktop parity) ────────────────────────────────────

    def _save_state(self, snapshot_name: Optional[str] = None):
        self.provider.save_state(self.path_to_vm, snapshot_name or self.snapshot_name)

    def _revert_to_snapshot(self):
        self.provider.revert_to_snapshot(self.path_to_vm, self.snapshot_name)
        self._wait_for_ready()

    def _delete_snapshot(self, snapshot_name: str):
        self.provider.delete_snapshot(self.path_to_vm, snapshot_name)

    # ── Gym interface ────────────────────────────────────────────────────

    def reset(self, task_config: Optional[Dict[str, Any]] = None, seed=None,
              options=None) -> Dict[str, Any]:
        logger.info("Resetting Android environment...")
        self._traj_no += 1
        self._step_no = 0
        self.action_history.clear()

        if not (self._device_online() and self._boot_completed()):
            self._start_emulator()
            self._connect_controller()

        if self.is_environment_used:
            snapshots = self.provider.list_snapshots()
            if self.snapshot_name in snapshots:
                logger.info("Reverting to AVD snapshot '%s'", self.snapshot_name)
                self._revert_to_snapshot()
                self.is_environment_used = False
            else:
                logger.info(
                    "Snapshot '%s' not found; going home instead", self.snapshot_name
                )
                self.controller.press_home()
        else:
            self.controller.press_home()
        self._suppress_soft_keyboard()
        time.sleep(2)
        return self._get_obs()

    def _get_obs(self):
        screenshot = None
        try:
            screenshot = self.controller.get_screenshot()
        except Exception as e:
            logger.warning("Failed to fetch screenshot: %s", e)
        if screenshot is None:
            logger.warning("Screenshot unavailable; attempting one ADB recovery")
            if self._recover_adb_transport():
                try:
                    screenshot = self.controller.get_screenshot()
                except Exception as e:
                    logger.warning("Screenshot retry failed after ADB recovery: %s", e)
        return {
            "screenshot": screenshot,
            "terminal": None,
        }

    def step(self, action_json_dict, pause=2):
        self._step_no += 1
        self.is_environment_used = True

        action_type = action_json_dict["action_type"]
        if action_type == "WAIT":
            time.sleep(3)
        if self.action_space == "gen_data":
            self.controller.execute_gui_action(action_json_dict)
        action_error = str(
            getattr(self.controller, "last_action_error", "") or "")
        time.sleep(pause)
        observation = self._get_obs()
        if action_error:
            observation["action_error"] = action_error
        return observation

    def close(self):
        try:
            if self._aw_env is not None:
                self._aw_env.close()
        except Exception:
            pass
        # Ordinary runs keep a reused emulator for speed. Named-snapshot runs
        # own an isolated overlay and always release the process they started.
        if self.boot_from_snapshot:
            self._terminate_owned_emulator()
        elif os.environ.get("GUI_REWALK_KILL_EMULATOR") == "1":
            if self._emulator_proc is not None:
                self._terminate_owned_emulator()
            else:
                self.provider.stop_emulator()

    @property
    def vm_platform(self):
        return "Android"

    @property
    def vm_screen_size(self):
        return self.controller.get_vm_screen_size()
