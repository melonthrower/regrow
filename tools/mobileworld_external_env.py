"""Run the modular explorer against a MobileWorld emulator over forwarded ADB.

This explicit tool does not start, stop, reset, or snapshot an AVD.  The caller
owns the MobileWorld container lifecycle; this adapter only drives one supplied
ADB serial and leaves the container running for per-app graph inspection.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence


MOBILEWORLD_APP_PACKAGES = {
    "calendar": "org.fossify.calendar",
    "camera": "com.android.camera2",
    "chrome": "com.android.chrome",
    "clock": "com.google.android.deskclock",
    "contacts": "com.google.android.contacts",
    "docreader": "",
    "files": "com.google.android.documentsui",
    "gallery": "gallery.photomanager.picturegalleryapp.imagegallery",
    "mail": "com.gmailclone",
    "maps": "com.google.android.apps.maps",
    "mastodon": "org.joinmastodon.android.mastodon",
    "mattermost": "com.mattermost.rnbeta",
    "messages": "com.google.android.apps.messaging",
    "settings": "com.android.settings",
    "taodian": "com.testmall.app",
}


class ExternalADBController:
    def __init__(
        self,
        *,
        adb_path: str,
        serial: str,
        screen_size: Optional[tuple[int, int]] = None,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.adb_path = str(adb_path)
        self.serial = str(serial)
        self._runner = runner
        self.screen_size = screen_size or self._read_screen_size()

    def _run(
        self,
        args: Sequence[str],
        *,
        timeout: float = 30,
        binary: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        result = self._runner(
            [self.adb_path, "-s", self.serial, *map(str, args)],
            capture_output=True,
            timeout=timeout,
            text=not binary,
        )
        if check and result.returncode != 0:
            detail = result.stderr if isinstance(result.stderr, str) else ""
            raise RuntimeError(f"ADB command failed: {detail[:300]}")
        return result

    def _read_screen_size(self) -> tuple[int, int]:
        text = self.adb_shell("wm size")
        match = re.search(r"(\d+)x(\d+)", text)
        if match is None:
            raise RuntimeError("MobileWorld ADB did not report a screen size")
        return int(match.group(1)), int(match.group(2))

    def adb_shell(self, command: str, timeout: float = 20) -> str:
        result = self._run(
            ["shell", *str(command).split()], timeout=timeout, check=False)
        return str(result.stdout or "")

    def get_screenshot(self) -> bytes:
        result = self._run(
            ["exec-out", "screencap", "-p"], timeout=30, binary=True)
        return bytes(result.stdout or b"")

    def get_vm_screen_size(self) -> tuple[int, int]:
        return self.screen_size

    def current_activity(self) -> str:
        text = self.adb_shell("dumpsys activity activities", timeout=15)
        match = re.search(
            r"(?:mResumedActivity|topResumedActivity)[^\n]*?"
            r"([A-Za-z0-9_.]+/[A-Za-z0-9_.$]+)",
            text,
        )
        return match.group(1) if match is not None else ""

    def foreground_package(self) -> str:
        activity = self.current_activity()
        return activity.split("/", 1)[0] if "/" in activity else ""

    def launch_app_android(self, package: str, activity: str = "") -> bool:
        if activity:
            component = package + activity if activity.startswith(".") else activity
            result = self._run(
                ["shell", "am", "start", "-n", component], check=False)
        else:
            result = self._run([
                "shell", "monkey", "-p", package,
                "-c", "android.intent.category.LAUNCHER", "1",
            ], check=False)
        return result.returncode == 0

    def force_stop(self, package: str) -> None:
        self._run(["shell", "am", "force-stop", package], check=False)

    def clear_app_data(self, package: str) -> None:
        self._run(["shell", "pm", "clear", package], check=False)

    def press_home(self) -> None:
        self._run(["shell", "input", "keyevent", "KEYCODE_HOME"])

    def execute_gui_action(self, action: Mapping[str, Any]) -> None:
        kind = str(action.get("action_type") or "").strip().casefold()
        x = int(action.get("x") or self.screen_size[0] // 2)
        y = int(action.get("y") or self.screen_size[1] // 2)
        if kind == "click":
            self._run(["shell", "input", "tap", str(x), str(y)])
            return
        if kind == "input_text":
            self._run(["shell", "input", "tap", str(x), str(y)])
            value = str(action.get("text") or "").replace(" ", "%s")
            self._run(["shell", "input", "text", value])
            return
        if kind == "long_press":
            self._run([
                "shell", "input", "swipe", str(x), str(y), str(x), str(y),
                "800",
            ])
            return
        if kind == "scroll":
            direction = str(action.get("direction") or "").casefold()
            width, height = self.screen_size
            margin_y = max(80, height // 12)
            margin_x = max(40, width // 12)
            span_y = max(1, round(height * 0.35))
            span_x = max(1, round(width * 0.35))
            if direction == "down":
                end_x, end_y = x, max(margin_y, y - span_y)
            elif direction == "up":
                end_x, end_y = x, min(height - margin_y, y + span_y)
            elif direction == "right":
                end_x, end_y = max(margin_x, x - span_x), y
            elif direction == "left":
                end_x, end_y = min(width - margin_x, x + span_x), y
            else:
                raise ValueError(f"unsupported scroll direction: {direction}")
            self._run([
                "shell", "input", "swipe", str(x), str(y),
                str(end_x), str(end_y), "400",
            ])
            return
        if kind == "navigate_back":
            self._run(["shell", "input", "keyevent", "KEYCODE_BACK"])
            return
        if kind == "navigate_home":
            self.press_home()
            return
        if kind == "wait":
            return
        raise ValueError(f"unsupported MobileWorld action: {kind}")


class ExternalADBEnv:
    platform = "android"
    vm_platform = "android"

    def __init__(self, controller: ExternalADBController) -> None:
        self.controller = controller
        self.adb_path = controller.adb_path
        self.serial = controller.serial
        self.screen_size = controller.screen_size

    def _get_obs(self) -> dict[str, bytes]:
        screenshot = self.controller.get_screenshot()
        if not screenshot:
            raise RuntimeError("MobileWorld ADB returned an empty screenshot")
        return {"screenshot": screenshot}

    def step(
        self, action_json_dict: Mapping[str, Any], pause: float = 1.0
    ) -> dict[str, bytes]:
        self.controller.execute_gui_action(action_json_dict)
        if pause > 0:
            time.sleep(pause)
        return self._get_obs()

    def close(self) -> None:
        return


def _wait_foreground(
    controller: ExternalADBController, package: str, timeout: float = 20
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if controller.foreground_package() == package:
            return True
        time.sleep(1)
    return False


def run_one(args: argparse.Namespace) -> int:
    from gui_rewalk.src.config import config as gui_config
    from gui_rewalk.src.core.explore.api_config import (
        load_explore_api_config,
        local_explore_api_config_path,
    )
    from gui_rewalk.src.core.explore.runtime import run as run_exploration

    package = MOBILEWORLD_APP_PACKAGES[args.app]
    if not package:
        raise RuntimeError(
            f"{args.app} has no direct launcher package; resolve it from the "
            "live MobileWorld image before traversal")
    internal_name = "mobileworld_" + args.app
    gui_config.APP_PACKAGE_MAP[internal_name] = (package, "")

    if ":" in args.serial:
        subprocess.run(
            [args.adb_path, "connect", args.serial],
            capture_output=True, text=True, timeout=20, check=False)
    controller = ExternalADBController(
        adb_path=args.adb_path, serial=args.serial)
    installed = controller.adb_shell(f"pm path {package}")
    if "package:" not in installed:
        raise RuntimeError(f"MobileWorld package is not installed: {package}")
    controller.force_stop(package)
    if not controller.launch_app_android(package):
        raise RuntimeError(f"MobileWorld app failed to launch: {args.app}")
    if not _wait_foreground(controller, package):
        raise RuntimeError(
            f"MobileWorld app did not become foreground: {args.app}")
    env = ExternalADBEnv(controller)
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    api_config = load_explore_api_config(local_explore_api_config_path())

    def relaunch() -> dict[str, bytes]:
        controller.force_stop(package)
        controller.launch_app_android(package)
        _wait_foreground(controller, package)
        return env._get_obs()

    result = run_exploration(
        env=env,
        app_name=internal_name,
        output_root=str(output_root),
        initial_obs=env._get_obs(),
        model=api_config.model,
        transport_agent=None,
        max_actions=args.max_actions,
        backend="openai_api",
        relaunch_fn=relaunch,
        api_config=api_config,
    )
    summary = {
        "schema": "mobileworld_modular_run.v1",
        "app": args.app,
        "package": package,
        "serial": args.serial,
        "status": result.status,
        "stop_reason": result.stop_reason,
        "actions_used": result.actions_used,
        "model_turns": result.model_turns,
        "gaps": list(result.gaps),
    }
    (output_root / "mobileworld_run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result.status == "complete" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, choices=MOBILEWORLD_APP_PACKAGES)
    parser.add_argument("--serial", default="127.0.0.1:5709")
    parser.add_argument("--adb-path", default="adb")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--max-actions", type=int, default=220)
    return run_one(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
