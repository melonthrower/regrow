"""System-owned foreground application check for visual traversal."""

from __future__ import annotations

from typing import Any, Optional

from ...graph.mobile_ops import is_app_foreground

class AppFocusGuard:
    """Tri-state app ownership from Android or desktop window metadata."""

    def __init__(
        self,
        env: Any,
        app_name: str,
        *,
        is_touch: bool,
        desktop_window_owner: Any = None,
    ):
        self.env = env
        self.app_name = app_name or "(目标应用)"
        self.is_touch = is_touch
        self.desktop_window_owner = desktop_window_owner
        self.last_kind = "unknown"
        self.last_reason = "system foreground ownership has not been checked"

    def on_app(
        self,
        _screenshot_bytes: bytes | None = None,
        context: Any = None,
    ) -> Optional[bool]:
        """Return True/False from system metadata, or None when unavailable."""
        del context
        if self.is_touch:
            verdict = is_app_foreground(self.env, self.app_name)
            self.last_reason = (
                "Android foreground activity/task"
                if verdict is not None
                else "Android foreground activity/task unavailable"
            )
        elif self.desktop_window_owner is not None:
            verdict = self.desktop_window_owner.is_foreground()
            self.last_reason = str(
                self.desktop_window_owner.last_reason
                or "desktop active window ownership unavailable")
        else:
            verdict = None
            self.last_reason = "desktop target window owner unavailable"
        self.last_kind = (
            "on_app" if verdict is True
            else "external_app" if verdict is False
            else "unknown"
        )
        return verdict
