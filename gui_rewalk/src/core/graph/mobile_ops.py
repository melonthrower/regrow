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

"""Android-side app lifecycle operations for the traversal engine.

桌面端的 wmctrl / pkill / dconf / Activities-search 等操作在手机端的对应实现，
全部集中在这个模块，traversal.py 仅做一行委托：

    if _is_android(env):
        return mobile_ops.launch_app(env, app_name)

约定：``env`` 是 :class:`AndroidGUIGenEnv`，``env.controller`` 是
:class:`AndroidController`。
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from ...config.config import (
    ANDROID_CLEAR_DATA_APPS,
    get_android_activity,
    get_android_package,
)

logger = logging.getLogger("desktopenv.graph.mobile")

MOBILE_FIXTURE_APP_NAME = "mingle"
MOBILE_FIXTURE_PACKAGE = "com.guirewalk.mingle"
MOBILE_FIXTURE_APK = (
    Path(__file__).resolve().parents[4]
    / "synthetic_mobile_app"
    / "mingle-debug.apk"
)


def is_android_env(env) -> bool:
    return getattr(env, "platform", "") == "android"


# ── App lifecycle ──────────────────────────────────────────────────────────

def _install_mobile_fixture_app(env) -> bool:
    """Install/update the repository-owned Mingle APK once per AVD session."""
    if getattr(env, "_mingle_fixture_installed", False):
        return True
    if not MOBILE_FIXTURE_APK.is_file():
        logger.error(
            "Mingle fixture APK is missing: %s (run synthetic_mobile_app/build_apk.py)",
            MOBILE_FIXTURE_APK,
        )
        return False
    adb_path = str(getattr(env, "adb_path", "") or "")
    serial = str(getattr(env, "serial", "") or "")
    if not adb_path or not serial:
        logger.error("Mingle fixture install requires Android env adb_path and serial")
        return False
    try:
        result = subprocess.run(
            [adb_path, "-s", serial, "install", "-r", str(MOBILE_FIXTURE_APK)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:
        logger.error("Mingle fixture APK install failed: %s", exc)
        return False
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    if result.returncode != 0 or "success" not in output.lower():
        logger.error("Mingle fixture APK install failed: %s", output.strip()[:500])
        return False
    setattr(env, "_mingle_fixture_installed", True)
    logger.info("Installed Mingle fixture APK into %s", serial)
    return True

def launch_app(env, app_name: str) -> None:
    """am start / monkey 拉起应用（对应桌面端 Activities 搜索启动）。"""
    if app_name == MOBILE_FIXTURE_APP_NAME and not _install_mobile_fixture_app(env):
        return
    package = get_android_package(app_name)
    if not package:
        logger.warning("launch_app: '%s' not in APP_PACKAGE_MAP", app_name)
        return
    activity = get_android_activity(app_name)
    ok = env.controller.launch_app_android(package, activity)
    if ok:
        logger.debug("Launched Android app: %s (%s)", app_name, package)
    time.sleep(2.0)


def kill_app(env, app_name_or_package: str) -> None:
    """am force-stop（对应桌面端 pkill -f）。"""
    package = get_android_package(app_name_or_package) or app_name_or_package
    env.controller.force_stop(package)
    logger.debug("Force-stopped Android app: %s", package)


def clear_app_cache(env, app_name: str) -> None:
    """回溯前清应用状态（对应桌面端 dconf reset）。

    只有 ANDROID_CLEAR_DATA_APPS 白名单内的应用才执行 ``pm clear``；
    国内 App 清数据会丢登录态，默认只 force-stop（已由调用方完成）。
    """
    if app_name not in ANDROID_CLEAR_DATA_APPS:
        logger.debug("clear_app_cache: '%s' not whitelisted; skip pm clear", app_name)
        return
    package = get_android_package(app_name)
    if package:
        env.controller.clear_app_data(package)
        logger.debug("Cleared app data: %s", package)


def close_all_windows(env) -> None:
    """对应桌面端关闭多余窗口：手机端没有自由窗口，关掉最近任务即可。

    保守实现：no-op。系统弹窗（权限请求等）由探索循环的 foreign-app
    检测处理，误按 BACK 反而可能改变目标应用状态。
    """
    return


def _is_in_app_activity(current: str, package: str) -> bool:
    return bool(current and package and re.search(
        rf"(?:^|\s){re.escape(package)}/", current))


def _foreground_task_affinity(env) -> str:
    """Return the affinity of the task owning the resumed Android activity."""
    try:
        dump = env.controller.adb_shell(
            "dumpsys activity activities", timeout=10)
    except Exception:
        return ""
    resumed = re.search(
        r"(?:mResumedActivity|topResumedActivity)="
        r"[^\n]*\bt(?P<task>\d+)\}",
        str(dump or ""),
    )
    if resumed is None:
        return ""
    task_id = resumed.group("task")
    task = re.search(
        rf"^\s*\*?\s*Task\{{[^\n]*#{re.escape(task_id)}\b"
        r"[^\n]*\bA=\d+:(?P<affinity>[^\s\}}]+)",
        str(dump or ""),
        flags=re.MULTILINE,
    )
    return str(task.group("affinity") if task is not None else "")


def _is_foreground_app_flow(env, current: str, package: str) -> bool:
    """Accept the target activity or a delegated surface in its rooted task."""
    if _is_in_app_activity(current, package):
        return True
    affinity = _foreground_task_affinity(env)
    return affinity == package or affinity.startswith(f"{package}.")


def is_app_foreground(env, app_name: str) -> Optional[bool]:
    """Read Android foreground ownership without spending a vision call.

    ``None`` means the controller/dumpsys signal is unavailable. Visual
    traversal retries the system query once and then fails closed; it does not
    infer application ownership from the screenshot.
    """
    if not is_android_env(env):
        return None
    package = get_android_package(app_name)
    if not package:
        return None
    try:
        current = env.controller.current_activity()
    except Exception:
        return None
    if not current:
        return None
    return _is_foreground_app_flow(env, current, package)


def focus_app_window(env, app_name: str) -> bool:
    """对应桌面端 wmctrl -a：检查前台任务，不对则重新拉起。"""
    package = get_android_package(app_name)
    if not package:
        return False
    current = env.controller.current_activity()
    if _is_foreground_app_flow(env, current, package):
        return True
    logger.info(
        "Foreground activity '%s' is not '%s'; relaunching", current, package
    )
    activity = get_android_activity(app_name)
    env.controller.launch_app_android(package, activity)
    time.sleep(2.0)
    current = env.controller.current_activity()
    return _is_foreground_app_flow(env, current, package)


def maximize_app_window(env, app_name: str) -> None:
    """手机应用天然全屏；确保前台即可。"""
    focus_app_window(env, app_name)


def wait_for_app(env, app_name: str, timeout: float = 12.0) -> bool:
    """轮询前台 activity，确认目标应用或其内嵌子包已经出现。"""
    package = get_android_package(app_name)
    if not package:
        return False
    start = time.time()
    while time.time() - start < timeout:
        try:
            current = env.controller.current_activity()
        except Exception:
            current = ""
        if _is_foreground_app_flow(env, current, package):
            return True
        time.sleep(1.0)
    return False


def run_vm_command(env, command, timeout: float = 10) -> str:
    """对应桌面端 /execute 通道：转成 adb shell。"""
    if isinstance(command, (list, tuple)):
        command = " ".join(str(c) for c in command)
    return env.controller.adb_shell(str(command), timeout=timeout)
