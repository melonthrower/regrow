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

"""AndroidController — drop-in replacement for ``PythonController`` backed by
android_world's AndroidWorldController.

Implements the same observation/action surface the traversal engine relies
on:

* ``get_screenshot()``        → PNG bytes
* ``execute_gui_action(dict)``→ executes a desktop-format action dict
* ``execute_python_command``  → maps to ``adb shell`` (best effort)
* ``start_recording``/``end_recording`` → no-ops

plus Android-specific app lifecycle helpers used by the traversal platform
branches (``launch_app_android``, ``force_stop``, ``clear_app_data``,
``press_back``, ``press_home``, ``current_activity``).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("desktopenv.android.controller")

ANDROID_KEYCODES: Dict[str, str] = {
    "enter": "KEYCODE_ENTER",
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "tab": "KEYCODE_TAB",
    "delete": "KEYCODE_DEL",
    "backspace": "KEYCODE_DEL",
    "escape": "KEYCODE_BACK",
    "esc": "KEYCODE_BACK",
    "space": "KEYCODE_SPACE",
    "up": "KEYCODE_DPAD_UP",
    "down": "KEYCODE_DPAD_DOWN",
    "left": "KEYCODE_DPAD_LEFT",
    "right": "KEYCODE_DPAD_RIGHT",
    "pageup": "KEYCODE_PAGE_UP",
    "pagedown": "KEYCODE_PAGE_DOWN",
    "menu": "KEYCODE_MENU",
    "power": "KEYCODE_POWER",
    "volumeup": "KEYCODE_VOLUME_UP",
    "volumedown": "KEYCODE_VOLUME_DOWN",
}


class AndroidController:
    """Controller exposing the PythonController interface over android_world."""

    def __init__(
        self,
        aw_controller,
    ):
        """Wrap an AndroidWorld controller with screenshot and action methods."""
        self._ctrl = aw_controller
        # Desktop code occasionally checks this attribute; keep a marker so
        # any accidental desktop-only HTTP path fails loudly and clearly.
        self.http_server = "android://no-http-server"
        try:
            self.screen_size: Tuple[int, int] = tuple(
                self._ctrl.logical_screen_size
            )
        except Exception:
            self.screen_size = (1080, 2400)

        # Strip developer debug overlays that pollute every captured frame.
        # `pointer_location` paints the touch-coordinate banner across the top
        # of the screen ("P:0/1 dX:0.0 ... Size:1.0"); `show_touches` draws a
        # ring at each tap. Both end up baked into the training screenshots.
        # Disable them once at startup (best-effort; ignore if adb refuses).
        self._disable_debug_overlays()

    def _disable_debug_overlays(self) -> None:
        """Turn off pointer-location / show-touches debug overlays."""
        for key in ("pointer_location", "show_touches"):
            try:
                self.adb_shell(f"settings put system {key} 0")
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning("failed to disable %s overlay: %s", key, exc)

    # ── Observation ─────────────────────────────────────────────────────

    def get_screenshot(self) -> Optional[bytes]:
        """Return the current screen as PNG bytes (adb screencap)."""
        from android_world.env import adb_utils

        for attempt in range(3):
            try:
                # exec-out 而非 shell：Windows adb shell 会做 CRLF 换行
                # 转换，破坏 PNG 二进制流。
                response = adb_utils.issue_generic_request(
                    ["exec-out", "screencap", "-p"], self._ctrl.env
                )
                raw = response.generic.output
                if raw and raw[:8] == b"\x89PNG\r\n\x1a\n":
                    return bytes(raw)
                logger.warning(
                    "screencap attempt %d returned non-PNG (%d bytes)",
                    attempt + 1, len(raw or b""),
                )
            except Exception as exc:
                logger.warning("screencap attempt %d failed: %s", attempt + 1, exc)
            time.sleep(1.0)
        logger.error("Failed to get Android screenshot")
        return None

    def get_terminal_output(self) -> Optional[str]:
        return None

    # ── Action execution ────────────────────────────────────────────────

    def execute_gui_action(self, action_json_dict: dict):
        """Execute a desktop-format action dict on the Android device."""
        from android_world.env import adb_utils

        self.last_action_error = ""
        action_type = action_json_dict.get("action_type")
        if action_type in ("WAIT", "FAIL", "FINISHED", "DONE", "wait"):
            return
        params = action_json_dict.get("parameters") or {
            k: v for k, v in action_json_dict.items() if k != "action_type"
        }

        # Accept AndroidWorld JSONAction names directly.  The traversal graph
        # stores the native action; this adapter only translates execution to
        # the pre-existing desktop-shaped primitives below.
        native_aliases = {
            "click": "CLICK",
            "double_tap": "DOUBLE_CLICK",
            "input_text": "TYPE",
            "keyboard_enter": "PRESS",
            "long_press": "LONG_PRESS",
            "navigate_back": "BACK",
            "navigate_home": "HOME",
            "open_app": "OPEN_APP",
            "scroll": "SCROLL",
            "swipe": "SWIPE",
        }
        native_type = str(action_type or "").strip().casefold()
        if native_type in native_aliases:
            action_type = native_aliases[native_type]
            if native_type == "keyboard_enter":
                params = {**params, "key": "enter"}

        env = self._ctrl.env

        if action_type in ("CLICK", "MOVE_TO"):
            # MOVE_TO has no Android equivalent; treat a bare MOVE_TO as no-op
            if action_type == "MOVE_TO":
                return
            x, y = int(params["x"]), int(params["y"])
            num_clicks = int(params.get("num_clicks", 1))
            if num_clicks >= 2:
                adb_utils.double_tap(x, y, env)
            else:
                adb_utils.tap_screen(x, y, env)

        elif action_type == "DOUBLE_CLICK":
            adb_utils.double_tap(int(params["x"]), int(params["y"]), env)

        elif action_type in ("RIGHT_CLICK", "RIGHT_SINGLE", "LONG_PRESS"):
            # Mobile long-press is the analogue of a desktop right-click
            adb_utils.long_press(int(params["x"]), int(params["y"]), env)

        elif action_type == "TYPE":
            text = params.get("text", "")
            if text:
                if (native_type == "input_text"
                        and any(ord(char) > 127 for char in text)):
                    self.last_action_error = (
                        "input_text_unsupported_non_ascii")
                    logger.error(
                        "Android input_text rejected before delivery: "
                        "non-ASCII text is unsupported")
                    return
                focus_check = getattr(
                    self, "active_text_input_check", None)
                strict_focus_check = bool(
                    native_type == "input_text" and callable(focus_check))
                focused = None
                if strict_focus_check:
                    try:
                        focused = focus_check()
                    except Exception:
                        focused = None
                    if focused is None:
                        self.last_action_error = (
                            "input_text_focus_state_unavailable")
                        logger.error(
                            "Android input_text rejected: focused input state "
                            "is unavailable")
                        return
                if (native_type == "input_text"
                        and params.get("x") is not None
                        and params.get("y") is not None
                        and focused is not True):
                    adb_utils.tap_screen(
                        int(params["x"]), int(params["y"]), env)
                    time.sleep(1.0)
                    if strict_focus_check:
                        try:
                            focused = focus_check()
                        except Exception:
                            focused = None
                        if focused is not True:
                            self.last_action_error = (
                                "input_text_target_not_focused")
                            logger.error(
                                "Android input_text rejected: target tap did "
                                "not create an active text input connection")
                            return
                if native_type == "input_text" and params.get("clear_text"):
                    adb_utils.issue_generic_request([
                        "shell", "input", "keycombination", "113", "29",
                        "&&", "input", "keyevent", "67",
                    ], env)
                    time.sleep(1.0)
                adb_utils.type_text(text, env)

        elif action_type == "PRESS":
            key = str(params.get("key", "")).lower()
            keycode = ANDROID_KEYCODES.get(key)
            if keycode:
                adb_utils.press_keyboard_generic(keycode, env)
            elif len(key) == 1:
                adb_utils.type_text(key, env)
            else:
                logger.warning("PRESS key '%s' has no Android keycode", key)

        elif action_type == "HOTKEY":
            keys = [str(k).lower() for k in params.get("keys", [])]
            # No modifier-combo support over adb input; map common combos
            if keys in (["alt", "f4"], ["ctrl", "w"]):
                adb_utils.press_back_button(env)
            else:
                for key in keys:
                    keycode = ANDROID_KEYCODES.get(key)
                    if keycode:
                        adb_utils.press_keyboard_generic(keycode, env)

        elif action_type == "SCROLL":
            self._scroll(params)

        elif action_type == "SWIPE":
            # AndroidWorld SWIPE direction is the finger direction (the inverse
            # of its SCROLL/content direction).
            w, h = self.screen_size
            mx, my = max(1, w // 12), max(1, h // 12)
            cx, cy = w // 2, h // 2
            direction = str(params.get("direction") or "").casefold()
            endpoints = {
                "down": ((cx, my), (cx, h - my)),
                "up": ((cx, h - my), (cx, my)),
                "right": ((mx, cy), (w - mx, cy)),
                "left": ((w - mx, cy), (mx, cy)),
            }
            if direction not in endpoints:
                raise ValueError(f"Invalid AndroidWorld swipe direction: {direction}")
            (x1, y1), (x2, y2) = endpoints[direction]
            cmd = adb_utils.generate_swipe_command(
                x1, y1, x2, y2, duration_ms=500)
            adb_utils.issue_generic_request(cmd, env)

        elif action_type == "DRAG":
            # Pixel-grounded drag with absolute endpoints (sliders/handles).
            # Swipe start->end as a slow press-drag; clamp on-screen so an edge
            # coord (volume slider often near the screen edge) doesn't drop the
            # gesture the way an off-screen scroll start did.
            w, h = self.screen_size
            x1 = max(1, min(w - 1, int(params["x1"])))
            y1 = max(1, min(h - 1, int(params["y1"])))
            x2 = max(1, min(w - 1, int(params["x2"])))
            y2 = max(1, min(h - 1, int(params["y2"])))
            cmd = adb_utils.generate_swipe_command(x1, y1, x2, y2, duration_ms=800)
            adb_utils.issue_generic_request(cmd, env)

        elif action_type == "DRAG_TO":
            x, y = int(params["x"]), int(params["y"])
            sx = int(params.get("start_x", self.screen_size[0] // 2))
            sy = int(params.get("start_y", self.screen_size[1] // 2))
            cmd = adb_utils.generate_swipe_command(sx, sy, x, y, duration_ms=800)
            adb_utils.issue_generic_request(cmd, env)

        elif action_type == "BACK":
            adb_utils.press_back_button(env)

        elif action_type == "HOME":
            adb_utils.press_home_button(env)

        elif action_type == "OPEN_APP":
            app_name = str(params.get("app_name") or "").strip()
            if not app_name:
                raise ValueError("AndroidWorld open_app requires app_name")
            adb_utils.launch_app(app_name, env)

        elif action_type in ("MOUSE_DOWN", "MOUSE_UP", "KEY_DOWN", "KEY_UP"):
            logger.debug("Ignoring desktop-only action on Android: %s", action_type)

        else:
            raise Exception(f"Unknown action type: {action_type}")

    # Desktop code paths call execute_action in a few places; same semantics.
    execute_action = execute_gui_action

    def _scroll(self, params: Dict[str, Any]):
        """Map a scroll request to a touch swipe.

        Two parameter conventions are accepted:

        * Desktop wheel deltas ``dy`` / ``dx`` (positive dy = wheel up =
          content moves up = a downward finger swipe).
        * Semantic ``direction`` ("up"/"down"/"left"/"right") + ``amount``
          (number of swipe pages, default 1), used by ``scroll_discovery``.
          ``direction="down"`` reveals content further down the page (finger
          swipes upward). Explicit x/y is the touch start, not the swipe center.
        """
        from android_world.env import adb_utils

        w, h = self.screen_size
        cx = int(params.get("x", w // 2))
        cy = int(params.get("y", h // 2))
        dy = int(params.get("dy", 0))
        dx = int(params.get("dx", 0))
        span_y = h // 3
        span_x = w // 3

        # Keep swipe endpoints inside the screen. A swipe whose start lands
        # off-screen (e.g. cy + span//2 > h, which happens whenever the VLM
        # anchors the scroll low to "find content below") is silently dropped
        # by Android → the scroll is a no-op. Clamp both ends into a safe band.
        my, mx = h // 12, w // 12
        def _cy(v: float) -> int:
            return max(my, min(h - my, int(v)))
        def _cx(v: float) -> int:
            return max(mx, min(w - mx, int(v)))

        direction = str(params.get("direction", "") or "").strip().lower()
        amount = int(params.get("amount", 1) or 1)
        # Optional small / slow swipe (full-page stitching): ``frac`` (0..1) shrinks
        # the gesture span to that fraction of the screen (default = 2/3, the big
        # fling), and ``slow`` lengthens the gesture so it scrolls with little
        # momentum (content advances ≈ the gesture distance, lots of overlap).
        # Unanchored requests retain the previous centered gesture.
        try:
            frac = params.get("frac", None)
            frac = float(frac) if frac is not None else None
        except (TypeError, ValueError):
            frac = None
        slow = bool(params.get("slow", False))
        dur = 750 if slow else 400
        span_frac = frac if (frac is not None and 0.0 < frac <= 1.0) else (2.0 / 3.0)
        if not dy and not dx and direction:
            # Translate semantic direction → finger swipe endpoints.
            # To reveal lower content ("down"), the finger swipes UP.
            span = round(h * span_frac)
            anchored = "x" in params and "y" in params
            origin = (max(1, min(w - 1, cx)), max(1, min(h - 1, cy)))
            if direction in ("down", "up"):
                sign = -1 if direction == "down" else 1
                start = origin if anchored else (cx, _cy(cy - sign * span // 2))
                end = ((start[0], max(1, min(h - 1, start[1] + sign * span)))
                       if anchored else (cx, _cy(cy + sign * span // 2)))
            elif direction in ("left", "right"):
                spanx = round(w * span_frac)
                sign = -1 if direction == "right" else 1
                start = origin if anchored else (_cx(cx - sign * spanx // 2), cy)
                end = ((max(1, min(w - 1, start[0] + sign * spanx)), start[1])
                       if anchored else (_cx(cx + sign * spanx // 2), cy))
            else:
                return
            for _ in range(max(1, amount)):
                cmd = adb_utils.generate_swipe_command(
                    start[0], start[1], end[0], end[1], duration_ms=dur
                )
                adb_utils.issue_generic_request(cmd, self._ctrl.env)
            return

        if dy:
            sign = 1 if dy > 0 else -1
            start = (cx, _cy(cy - sign * span_y // 2))
            end = (cx, _cy(cy + sign * span_y // 2))
        elif dx:
            sign = 1 if dx > 0 else -1
            start = (_cx(cx - sign * span_x // 2), cy)
            end = (_cx(cx + sign * span_x // 2), cy)
        else:
            return
        cmd = adb_utils.generate_swipe_command(
            start[0], start[1], end[0], end[1], duration_ms=400
        )
        adb_utils.issue_generic_request(cmd, self._ctrl.env)

    # ── Shell-ish escape hatch ──────────────────────────────────────────

    def adb_shell(self, command: str, timeout: float = 20) -> str:
        """Run an ``adb shell`` command and return stdout."""
        from android_world.env import adb_utils

        try:
            response = adb_utils.issue_generic_request(
                ["shell"] + command.split(), self._ctrl.env, timeout_sec=timeout
            )
            return (response.generic.output or b"").decode("utf-8", "replace")
        except Exception as exc:
            logger.warning("adb shell '%s' failed: %s", command, exc)
            return ""

    def execute_python_command(self, command: str):
        """Desktop API compatibility. Python execution inside the device is
        not supported; callers must use platform branches instead."""
        logger.warning(
            "execute_python_command is a no-op on Android (command=%r)",
            command[:120],
        )
        return {"status": "unsupported", "output": "", "error": ""}

    # ── App lifecycle (used by traversal platform branches) ─────────────

    def is_package_installed(self, package: str) -> bool:
        """True iff ``package`` is installed on the device."""
        if not package:
            return False
        out = self.adb_shell(f"pm list packages {package}")
        # `pm list packages` substring-matches; require an exact package: line.
        return any(line.strip() == f"package:{package}"
                   for line in out.splitlines())

    def _resolved_launch_activity(self, package: str) -> str:
        """Resolve the package's launchable component (``pkg/.Activity``) via
        ``cmd package resolve-activity``. Returns '' if none — i.e. the package
        has no launcher entry (a system/intent-only component like AOSP
        DocumentsUI), which is exactly the silent-failure case that left
        files=0/messaging empty: ``monkey -c LAUNCHER`` matched nothing and we
        stayed on the home screen."""
        # Try LAUNCHER first (the normal home-screen entry), then fall back to a
        # plain MAIN resolve. Some AOSP/Google packages (DocumentsUI "Files",
        # certain Messaging builds) expose a MAIN activity but no LAUNCHER
        # category, so a LAUNCHER-only resolve returns nothing and we wrongly gave
        # up — this MAIN fallback recovers those (files/messaging).
        for category in ("-c android.intent.category.LAUNCHER", ""):
            out = self.adb_shell(
                f"cmd package resolve-activity --brief {category} {package}".strip())
            for line in out.splitlines():
                line = line.strip()
                if line.startswith(f"{package}/"):
                    return line
        return ""

    def launch_app_android(self, package: str, activity: str = "") -> bool:
        """Launch ``package`` and VERIFY it reached the foreground.

        Returns True only if the target package is actually foregrounded
        afterwards. Previously a bare ``monkey -c LAUNCHER`` was fired and we
        always returned True even when nothing launched (no launcher activity →
        we silently sat on the home screen → the visual focus-guard then aborted
        with 0 nodes; the files/messaging=0 bug). Now: try the explicit activity,
        else monkey, and if neither foregrounds the package, resolve the real
        launchable component and start it; report the true outcome."""
        from android_world.env import adb_utils
        import time as _time

        def _foregrounded() -> bool:
            try:
                return package in (self.current_activity() or "")
            except Exception:
                return False

        try:
            if activity:
                full = activity if "/" in activity else f"{package}/{activity}"
                adb_utils.start_activity(full, [], self._ctrl.env)
            else:
                # monkey trick launches the default launcher activity
                self.adb_shell(
                    f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
                )
            _time.sleep(2.0)
            if _foregrounded():
                return True
            # Primary path did not foreground the package. If it isn't even
            # installed, fail fast (caller -> "not installed/launchable").
            if not self.is_package_installed(package):
                logger.warning("launch: package %s is not installed", package)
                return False
            # Installed but monkey/activity didn't bring it forward — resolve the
            # real launchable activity and start it explicitly.
            comp = self._resolved_launch_activity(package)
            if comp:
                logger.info("launch: retrying %s via resolved component %s",
                            package, comp)
                adb_utils.start_activity(comp, [], self._ctrl.env)
                _time.sleep(2.0)
                if _foregrounded():
                    return True
            logger.warning("launch: %s installed but could not be foregrounded "
                           "(no launchable activity?)", package)
            return False
        except Exception as exc:
            logger.warning("Failed to launch %s: %s", package, exc)
            return False

    def force_stop(self, package: str) -> None:
        self.adb_shell(f"am force-stop {package}")

    def clear_app_data(self, package: str) -> None:
        from android_world.env import adb_utils

        try:
            adb_utils.clear_app_data(package, self._ctrl.env)
        except Exception as exc:
            logger.warning("clear_app_data(%s) failed: %s", package, exc)

    def press_back(self) -> None:
        from android_world.env import adb_utils

        adb_utils.press_back_button(self._ctrl.env)

    def press_home(self) -> None:
        from android_world.env import adb_utils

        adb_utils.press_home_button(self._ctrl.env)

    def current_activity(self) -> str:
        from android_world.env import adb_utils

        try:
            activity, _ = adb_utils.get_current_activity(self._ctrl.env)
            return activity or ""
        except Exception:
            return ""

    def foreground_package(self) -> str:
        """Return the package owning the foreground activity, if dumpsys knows it."""
        activity = self.current_activity().strip()
        if not activity:
            return ""
        component = activity.split()[-1]
        return component.split("/", 1)[0] if "/" in component else component

    # ── Recording & misc PythonController API compatibility ─────────────

    def start_recording(self):
        logger.debug("start_recording: no-op on Android")

    def end_recording(self, dest: str):
        logger.debug("end_recording: no-op on Android")

    def get_vm_platform(self):
        return "Android"

    def get_vm_screen_size(self):
        return {"width": self.screen_size[0], "height": self.screen_size[1]}
