"""Shared application lifecycle and desktop-window helpers.

This module is intentionally independent of the graph traversal engine.  The
visual traversal needs app launch/reset/window control without UI-tree parsing.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests

from ..config.config import (
    APP_BINARY_MAP,
    APP_CACHE_CLEAR_CMDS,
    APP_SEED_FILE,
    APP_WINDOW_NAME_MAP,
)
from .graph import mobile_ops


# Keep the historical logger name so moving these helpers does not change log
# routing or filtering in existing runners.
logger = logging.getLogger("desktopenv.graph.traversal")

APP_LAUNCH_TIMEOUT_S = 30.0
VISUAL_APPEAR_POLL_S = 3.0
VISUAL_LAUNCH_TIMEOUT_S = 45.0
HARD_RESET_SETTLE_S = 1.5
FIXTURE_APP_NAME = "dayline"
FIXTURE_APP_NAMES = frozenset({FIXTURE_APP_NAME, "rewalk fixture"})
FIXTURE_GUEST_DIR = "/tmp/gui_rewalk_fixture"

# Window titles to keep alive during _close_all_windows().
PROTECTED_WINDOW_TITLES = {"desktop", "panel", "dock", "nautilus-desktop"}


_APP_SEARCH_NAME: Dict[str, str] = {
    "dayline": "Dayline",
    "rewalk fixture": "ReWalk Fixture",
    "setting": "Settings",
    "Chrome": "Chrome",
    "LibreOffice writer": "LibreOffice Writer",
    "LibreOffice calc": "LibreOffice Calc",
    "GNU image": "GIMP",
    "calendar": "Calendar",
    "calculator": "Calculator",
    "terminal": "Terminal",
    "mines": "Mines",
    "text editor": "Text Editor",
    "system monitor": "System Monitor",
    "tweaks": "Tweaks",
    "clocks": "Clocks",
    "characters": "Characters",
    "font viewer": "Fonts",
    "disk usage": "Disk Usage",
    "document viewer": "Document Viewer",
    "image viewer": "Image Viewer",
    "logs": "Logs",
    "firefox": "Firefox",
    "thunderbird": "Thunderbird",
    "vlc": "VLC",
    "shotwell": "Shotwell",
    "rhythmbox": "Rhythmbox",
    "inkscape": "Inkscape",
    "transmission": "Transmission",
    "cheese": "Cheese",
    "scanner": "Document Scanner",
    "vs_code": "Visual Studio Code",
}


def _fixture_asset_path() -> Path:
    """Return the generated standalone fixture owned by this repository."""
    return Path(__file__).resolve().parents[3] / "synthetic_app" / "index.html"


def _install_embedded_fixture_app(env) -> bool:
    """Copy the deterministic HTML fixture into a desktop guest.

    The transfer uses the existing guest Python execution channel, requires no
    network service, and writes only below ``/tmp/gui_rewalk_fixture``.  The
    dedicated Chrome profile lives beside the asset so ``--clean_start`` can
    clear fixture state without touching a user's normal browser profile.
    """
    asset = _fixture_asset_path()
    try:
        payload = asset.read_bytes()
    except OSError as exc:
        logger.error("Fixture app asset is unavailable at %s: %s", asset, exc)
        return False
    encoded = base64.b64encode(payload).decode("ascii")
    script = (
        "import base64, os\n"
        f"root = {FIXTURE_GUEST_DIR!r}\n"
        "os.makedirs(root, exist_ok=True)\n"
        f"data = base64.b64decode({encoded!r})\n"
        "path = os.path.join(root, 'index.html')\n"
        "current = open(path, 'rb').read() if os.path.exists(path) else b''\n"
        "if current != data:\n"
        "    tmp = path + '.tmp'\n"
        "    open(tmp, 'wb').write(data)\n"
        "    os.replace(tmp, path)\n"
        "print('fixture_ready', len(data))\n"
    )
    try:
        result = env.controller.execute_python_command("exec(%r)" % script)
    except Exception as exc:
        logger.error("Fixture app guest install failed: %s", exc)
        return False
    if result is None:
        logger.error("Fixture app guest install returned no result")
        return False
    logger.info("Fixture app installed into guest at %s/index.html", FIXTURE_GUEST_DIR)
    return True


def _get_process_name(app_name: str) -> str:
    """Derive a process name for pkill from the app name."""
    binary = APP_BINARY_MAP.get(app_name, app_name.lower())
    return binary.split()[0].split("/")[-1]


def _window_focus_candidates(app_name: str) -> List[str]:
    """Return likely wmctrl title/class candidates for an app."""
    candidates: List[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in candidates:
            candidates.append(text)

    binary = APP_BINARY_MAP.get(app_name, "")
    if binary:
        binary_name = binary.split()[0].split("/")[-1]
        add(binary_name)
        add(binary_name.replace("-", " "))
    for alias in APP_WINDOW_NAME_MAP.get(app_name, []):
        add(alias)
    add(_APP_SEARCH_NAME.get(app_name, ""))
    add(app_name)
    return candidates


def _run_vm_command(env, command: List[str], timeout: float = 10) -> str:
    if mobile_ops.is_android_env(env):
        return mobile_ops.run_vm_command(env, command, timeout=timeout)
    payload = json.dumps({
        "command": command,
        "shell": False,
    })
    resp = requests.post(
        env.controller.http_server + "/execute",
        headers={"Content-Type": "application/json"},
        data=payload,
        timeout=timeout,
    )
    try:
        body = resp.json()
    except Exception:
        return ""
    return str(body.get("output", "") or "")


def _focus_app_window(env, app_name: str) -> bool:
    """Raise the target app window using wmctrl title/class aliases."""
    if mobile_ops.is_android_env(env):
        return mobile_ops.focus_app_window(env, app_name)
    return _surface_app_window(env, app_name)


def _maximize_app_window(env, app_name: str) -> None:
    """Best-effort maximize of the target window after launch/focus."""
    if mobile_ops.is_android_env(env):
        mobile_ops.maximize_app_window(env, app_name)
        return
    try:
        if not _focus_app_window(env, app_name):
            if _surface_app_window(env, app_name):
                logger.info("Maximized app window for '%s' (a11y-free surface)", app_name)
            else:
                logger.debug("Maximize skipped: could not focus '%s'", app_name)
            return
        _run_vm_command(
            env,
            ["wmctrl", "-r", ":ACTIVE:", "-b", "add,maximized_vert,maximized_horz"],
            timeout=10,
        )
        time.sleep(0.5)
        logger.info("Maximized app window for '%s'", app_name)
    except Exception as exc:
        logger.debug("Maximize failed for '%s': %s", app_name, exc)


def _surface_app_window(env, app_name: str) -> bool:
    """Force the target desktop window visible without consulting A11y."""
    if mobile_ops.is_android_env(env):
        return False
    try:
        listing = _run_vm_command(env, ["wmctrl", "-lx"], timeout=10)
    except Exception as exc:
        logger.debug("surface: wmctrl -lx failed for '%s': %s", app_name, exc)
        return False
    cands = [c.lower() for c in _window_focus_candidates(app_name) if c]
    for line in listing.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        wid, wm_class, title = parts[0], parts[2], parts[4]
        window_identity = f"{wm_class} {title}".lower()
        if not any(c in window_identity for c in cands):
            continue
        for args in (["-ir", wid, "-b", "remove,hidden"],
                     ["-ir", wid, "-b", "remove,shaded"],
                     ["-ir", wid, "-b", "add,maximized_vert,maximized_horz"],
                     ["-ia", wid]):
            try:
                _run_vm_command(env, ["wmctrl"] + args, timeout=10)
            except Exception:
                pass
        logger.debug("surface: raised '%s' window id=%s (%s)", app_name, wid, title)
        return True
    return False


def _get_app_window_bbox(env, app_name: str):
    """Return the target desktop window ``[x, y, w, h]`` from wmctrl."""
    if mobile_ops.is_android_env(env):
        return None
    try:
        listing = _run_vm_command(env, ["wmctrl", "-lG"], timeout=10)
    except Exception as exc:
        logger.debug("window-bbox: wmctrl -lG failed for '%s': %s", app_name, exc)
        return None
    cands = [c.lower() for c in _window_focus_candidates(app_name) if c]
    for line in (listing or "").splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        title = parts[7].lower()
        if not any(c in title for c in cands):
            continue
        try:
            x, y, w, h = int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
        except ValueError:
            continue
        if w > 0 and h > 0:
            logger.info("window-bbox '%s' = [x=%d y=%d w=%d h=%d] (wmctrl -lG)",
                        app_name, x, y, w, h)
            return [x, y, w, h]
    logger.debug("window-bbox: no matching window for '%s'", app_name)
    return None




@dataclass(frozen=True)
class DesktopWindowIdentity:
    window_id: int
    wm_classes: frozenset[str]
    title: str
    pid: Optional[int]
    transient_for: Optional[int]


def _parse_window_id(value: str) -> Optional[int]:
    try:
        return int(str(value or "").strip(), 16)
    except (TypeError, ValueError):
        return None


def _active_desktop_window(env) -> Optional[DesktopWindowIdentity]:
    """Read the active X11 window identity without consulting A11y or pixels."""
    if mobile_ops.is_android_env(env):
        return None
    script = (
        "wid=$(xprop -root _NET_ACTIVE_WINDOW 2>/dev/null | "
        "grep -o '0x[0-9a-fA-F]*' | head -n1); "
        "[ -n \"$wid\" ] && [ \"$wid\" != \"0x0\" ] || exit 0; "
        "printf 'WINDOW_ID=%s\\n' \"$wid\"; "
        "xprop -id \"$wid\" WM_CLASS _NET_WM_NAME WM_NAME _NET_WM_PID "
        "WM_TRANSIENT_FOR 2>/dev/null"
    )
    try:
        output = _run_vm_command(
            env, ["bash", "-lc", script], timeout=10)
    except Exception as exc:
        logger.debug("active desktop window query failed: %s", exc)
        return None
    window_match = re.search(
        r"^WINDOW_ID=(0x[0-9a-fA-F]+)$", output, re.MULTILINE)
    window_id = _parse_window_id(
        window_match.group(1) if window_match else "")
    if window_id is None:
        return None
    class_match = re.search(
        r'^WM_CLASS\([^)]*\)\s*=\s*(.+)$', output, re.MULTILINE)
    classes = frozenset(
        value.lower()
        for value in re.findall(r'"([^"]+)"',
                                class_match.group(1) if class_match else "")
        if value.strip()
    )
    title = ""
    for key in ("_NET_WM_NAME", "WM_NAME"):
        title_match = re.search(
            rf'^{key}\([^)]*\)\s*=\s*"([^"]*)"$',
            output, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()
            break
    pid_match = re.search(
        r"^_NET_WM_PID\([^)]*\)\s*=\s*(\d+)$", output, re.MULTILINE)
    transient_match = re.search(
        r"^WM_TRANSIENT_FOR\([^)]*\).*#\s*(0x[0-9a-fA-F]+)$",
        output, re.MULTILINE)
    return DesktopWindowIdentity(
        window_id=window_id,
        wm_classes=classes,
        title=title,
        pid=int(pid_match.group(1)) if pid_match else None,
        transient_for=_parse_window_id(
            transient_match.group(1) if transient_match else ""),
    )


def _identity_matches_app(
    identity: DesktopWindowIdentity, app_name: str,
) -> bool:
    """Use the existing launch registry only to verify the first window bind."""
    candidates = {
        value.lower() for value in _window_focus_candidates(app_name) if value}
    if not candidates:
        return False
    for wm_class in identity.wm_classes:
        if any(candidate == wm_class or candidate in wm_class
               or wm_class in candidate for candidate in candidates):
            return True
    title = identity.title.lower()
    return bool(title) and any(candidate in title for candidate in candidates)


class DesktopWindowOwner:
    """Run-local target-window ownership learned at application launch."""

    def __init__(self, env):
        self.env = env
        self.window_ids: Set[int] = set()
        self.pids: Set[int] = set()
        self.last_reason = ""

    def bind_active(self, app_name: str = "", *, verified: bool = False) -> bool:
        identity = _active_desktop_window(self.env)
        if identity is None:
            self.last_reason = "desktop active window unavailable"
            return False
        if (not verified and app_name
                and not _identity_matches_app(identity, app_name)):
            self.last_reason = "active window does not match launch identity"
            return False
        self.window_ids.add(identity.window_id)
        if identity.pid is not None:
            self.pids.add(identity.pid)
        self.last_reason = "desktop active window bound at launch"
        return True

    def is_foreground(self) -> Optional[bool]:
        if not self.window_ids:
            self.last_reason = "desktop target window is not bound"
            return None
        identity = _active_desktop_window(self.env)
        if identity is None:
            self.last_reason = "desktop active window unavailable"
            return None
        owned = (
            identity.window_id in self.window_ids
            or (identity.pid is not None and identity.pid in self.pids)
            or (identity.transient_for is not None
                and identity.transient_for in self.window_ids)
        )
        if owned:
            self.window_ids.add(identity.window_id)
            if identity.pid is not None:
                self.pids.add(identity.pid)
            self.last_reason = "desktop active window belongs to target"
            return True
        self.last_reason = "desktop active window belongs to another owner"
        return False

    def activate(self) -> bool:
        """Raise one run-bound target window without restarting the app."""
        if not self.window_ids:
            self.last_reason = "desktop target window is not bound"
            return False
        for window_id in sorted(self.window_ids):
            try:
                _run_vm_command(
                    self.env,
                    ["wmctrl", "-ia", hex(window_id)],
                    timeout=10,
                )
            except Exception:
                continue
            if self.is_foreground() is True:
                self.last_reason = "desktop target window reactivated"
                return True
        self.last_reason = "desktop target window reactivation failed"
        return False


def _close_all_windows(env) -> None:
    """Close every visible desktop window except desktop/panel/dock."""
    if mobile_ops.is_android_env(env):
        mobile_ops.close_all_windows(env)
        return
    try:
        list_payload = json.dumps({
            "command": ["wmctrl", "-l"],
            "shell": False,
        })
        resp = requests.post(
            env.controller.http_server + "/execute",
            headers={"Content-Type": "application/json"},
            data=list_payload,
            timeout=10,
        )
        output = resp.json().get("output", "")
        for line in output.strip().splitlines():
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            wid = parts[0]
            title = parts[3].lower()
            if any(p in title for p in PROTECTED_WINDOW_TITLES):
                continue
            close_payload = json.dumps({
                "command": ["wmctrl", "-ic", wid],
                "shell": False,
            })
            requests.post(
                env.controller.http_server + "/execute",
                headers={"Content-Type": "application/json"},
                data=close_payload,
                timeout=5,
            )
        time.sleep(0.5)
    except Exception as e:
        logger.warning("_close_all_windows failed: %s", e)


def _kill_app(env, process_name: str) -> None:
    """Kill an application via the guest execute endpoint."""
    if mobile_ops.is_android_env(env):
        mobile_ops.kill_app(env, process_name)
        return
    try:
        payload = json.dumps({
            "command": ["pkill", "-f", process_name],
            "shell": False,
        })
        requests.post(
            env.controller.http_server + "/execute",
            headers={"Content-Type": "application/json"},
            data=payload,
            timeout=10,
        )
        logger.debug("Killed process: %s", process_name)
    except Exception as e:
        logger.warning("Failed to kill %s: %s", process_name, e)


def _clear_app_cache(env, app_name: str) -> None:
    """Run the configured per-app cache/state clearing commands."""
    if mobile_ops.is_android_env(env):
        mobile_ops.clear_app_cache(env, app_name)
        return
    cmds = APP_CACHE_CLEAR_CMDS.get(app_name, [])
    for cmd in cmds:
        try:
            payload = json.dumps({
                "command": ["bash", "-c", cmd],
                "shell": False,
            })
            requests.post(
                env.controller.http_server + "/execute",
                headers={"Content-Type": "application/json"},
                data=payload,
                timeout=10,
            )
            logger.debug("Cache cleared: %s 鈫?%s", app_name, cmd)
        except Exception as e:
            logger.warning("Cache clear failed for %s (%s): %s", app_name, cmd, e)


def _ensure_seed_file(env, vm_path: str, kind: str) -> bool:
    """Best-effort creation of an idempotent sample file in the guest VM."""
    sample_text = (
        "GUI ReWalk sample document\\n\\n"
        "Line one of sample content.\\n"
        "Line two of sample content.\\n"
        "Line three of sample content.\\n"
    )
    script = (
        "import os\n"
        f"p = {vm_path!r}\n"
        "os.makedirs(os.path.dirname(p), exist_ok=True)\n"
        "ok = os.path.exists(p)\n"
        "if not ok:\n"
        f"    kind = {kind!r}\n"
        "    try:\n"
        "        if kind == 'txt':\n"
        f"            open(p, 'w').write({sample_text!r})\n"
        "            ok = True\n"
        "        else:\n"
        "            from PIL import Image, ImageDraw\n"
        "            img = Image.new('RGB', (1000, 760), 'white')\n"
        "            d = ImageDraw.Draw(img)\n"
        "            d.rectangle([40, 40, 960, 720], outline='black', width=4)\n"
        "            for i in range(6):\n"
        "                y = 120 + i * 90\n"
        "                d.line([90, y, 910, y], fill=(60, 60, 60), width=3)\n"
        "            d.text((110, 60), 'GUI ReWalk sample', fill='black')\n"
        "            img.save(p)\n"
        "            ok = True\n"
        "    except Exception as e:\n"
        "        print('seed_err', e)\n"
        "        ok = False\n"
        "print('seed_ok' if ok else 'seed_fail')\n"
    )
    try:
        result = env.controller.execute_python_command("exec(%r)" % script)
        output = (
            str(result.get("output") or "")
            if isinstance(result, dict) else str(result or "")
        )
        return any(line.strip() == "seed_ok" for line in output.splitlines())
    except Exception as e:
        logger.warning("Seed file %s (%s) failed: %s", vm_path, kind, e)
        return False


def launch_app(
    env, app_name: str, appear_check=None,
    desktop_window_owner: Optional[DesktopWindowOwner] = None,
) -> None:
    """Launch an application directly, with Activities search as fallback."""
    if mobile_ops.is_android_env(env):
        mobile_ops.launch_app(env, app_name)
        return
    if app_name in FIXTURE_APP_NAMES and not _install_embedded_fixture_app(env):
        return
    search_name = _APP_SEARCH_NAME.get(app_name, app_name)
    binary = APP_BINARY_MAP.get(app_name, "")
    launch_target = binary
    seed = APP_SEED_FILE.get(app_name)
    if binary and seed:
        if _ensure_seed_file(env, seed[0], seed[1]):
            launch_target = f"{binary} {seed[0]}"
            logger.info("Seeded '%s' with %s", app_name, seed[0])
    if binary:
        script = (
            "import shlex, subprocess, time\n"
            f"subprocess.Popen(shlex.split({launch_target!r}), "
            "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL, start_new_session=True)\n"
            "time.sleep(0.5)\n"
        )
        try:
            env.controller.execute_python_command("exec(%r)" % script)
            _direct_to = VISUAL_LAUNCH_TIMEOUT_S if appear_check is not None else 12
            wait_kwargs = {
                "timeout": _direct_to,
                "appear_check": appear_check,
            }
            if desktop_window_owner is not None:
                wait_kwargs["desktop_window_owner"] = desktop_window_owner
            if wait_for_app(env, app_name, **wait_kwargs):
                logger.debug("Launched app directly: %s (%s)", app_name, binary)
                return
            logger.warning(
                "Direct launch of %s did not surface a window in %ss; "
                "falling back to Activities search",
                app_name,
                _direct_to,
            )
        except Exception as e:
            logger.warning("Failed to launch %s directly: %s", app_name, e)

    try:
        ctrl = env.controller
        ctrl.execute_gui_action({
            "action_type": "PRESS",
            "parameters": {"key": "win"},
        })
        time.sleep(1.5)
        ctrl.execute_gui_action({
            "action_type": "TYPE",
            "parameters": {"text": search_name},
        })
        time.sleep(1.5)
        ctrl.execute_gui_action({
            "action_type": "PRESS",
            "parameters": {"key": "enter"},
        })
        logger.debug("Launched app via Activities search: %s (%s)",
                     app_name, search_name)
    except Exception as e:
        logger.warning("Failed to launch %s via Activities: %s", app_name, e)


def wait_for_app(
    env,
    app_name: str,
    timeout: float = APP_LAUNCH_TIMEOUT_S,
    appear_check=None,
    desktop_window_owner: Optional[DesktopWindowOwner] = None,
) -> bool:
    """Poll until the target app appears via Android or screenshot checks."""
    if mobile_ops.is_android_env(env):
        return mobile_ops.wait_for_app(env, app_name, timeout=timeout)
    start = time.time()
    while time.time() - start < timeout:
        try:
            surfaced = _surface_app_window(env, app_name)
            if desktop_window_owner is not None:
                if (surfaced
                        and desktop_window_owner.bind_active(app_name)):
                    return True
                time.sleep(VISUAL_APPEAR_POLL_S)
                continue
            if appear_check is None:
                if surfaced:
                    return True
            else:
                obs = env._get_obs()
                screenshot = obs.get("screenshot")
                if screenshot and appear_check(screenshot):
                    if desktop_window_owner is not None:
                        desktop_window_owner.bind_active(verified=True)
                    return True
        except Exception as exc:
            logger.debug("wait_for_app screenshot check error: %s", exc)
        time.sleep(VISUAL_APPEAR_POLL_S)
    return False


def restart_app_preserving_data(
    env, app_name: str, appear_check=None,
    desktop_window_owner: Optional[DesktopWindowOwner] = None,
) -> bool:
    """Restart at the app entry surface without clearing persistent resources.

    Traversal uses this after a crash/off-app handoff and for router hard-reset.
    Unlike :func:`startup_reset_app`, it must retain run-owned prerequisite
    fixtures (for example a disposable alarm) so dependent pages remain
    reachable and can later be cleaned explicitly.
    """

    process_name = _get_process_name(app_name)
    logger.info("Data-preserving restart: killing '%s' (if running)", app_name)
    _kill_app(env, process_name)
    time.sleep(HARD_RESET_SETTLE_S)
    lifecycle_kwargs = {"appear_check": appear_check}
    if desktop_window_owner is not None:
        lifecycle_kwargs["desktop_window_owner"] = desktop_window_owner
    launch_app(env, app_name, **lifecycle_kwargs)
    ready = wait_for_app(env, app_name, **lifecycle_kwargs)
    if ready:
        _maximize_app_window(env, app_name)
        logger.info("Data-preserving restart: '%s' is ready", app_name)
    else:
        logger.warning(
            "Data-preserving restart: '%s' did not appear within timeout",
            app_name)
    return ready


def startup_reset_app(
    env, app_name: str, appear_check=None,
    desktop_window_owner: Optional[DesktopWindowOwner] = None,
) -> bool:
    """Kill, clear, relaunch, wait for, and maximize an application."""
    process_name = _get_process_name(app_name)
    logger.info("Startup reset: killing '%s' (if running)", app_name)
    _kill_app(env, process_name)
    time.sleep(HARD_RESET_SETTLE_S)

    logger.info("Startup reset: closing extraneous windows")
    _close_all_windows(env)

    logger.info("Startup reset: clearing cached state for '%s'", app_name)
    _clear_app_cache(env, app_name)

    logger.info("Startup reset: launching '%s'", app_name)
    lifecycle_kwargs = {"appear_check": appear_check}
    if desktop_window_owner is not None:
        lifecycle_kwargs["desktop_window_owner"] = desktop_window_owner
    launch_app(env, app_name, **lifecycle_kwargs)

    ready = wait_for_app(env, app_name, **lifecycle_kwargs)
    if ready:
        _maximize_app_window(env, app_name)
        logger.info("Startup reset: '%s' is ready", app_name)
    else:
        logger.warning("Startup reset: '%s' did not appear within timeout", app_name)
    return ready
