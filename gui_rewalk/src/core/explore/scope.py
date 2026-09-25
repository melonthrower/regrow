"""System-owned target-app foreground check and non-graph recovery."""

from __future__ import annotations

from typing import Any, Callable, Optional

from .actions import is_android


class ScopeGuard:
    def __init__(
        self,
        *,
        env: Any,
        app_name: str,
        platform: str,
        desktop_window_owner: Any = None,
        relaunch_fn: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.env = env
        self.app_name = app_name
        self.platform = platform
        self.desktop_window_owner = desktop_window_owner
        self.relaunch_fn = relaunch_fn
        self.last_reason = ""

    def check(self) -> str:
        if is_android(self.platform):
            try:
                from gui_rewalk.src.config.config import get_android_package
                from gui_rewalk.src.core.graph.mobile_ops import is_app_foreground

                package = str(get_android_package(self.app_name) or "").strip()
                foreground_package = getattr(
                    getattr(self.env, "controller", None),
                    "foreground_package",
                    None,
                )
                current = str(
                    foreground_package() if callable(foreground_package) else ""
                ).strip()
                if package and current:
                    self.last_reason = f"Android 前景包：{current}"
                    return "target" if current == package else "external"
                value = is_app_foreground(self.env, self.app_name)
            except Exception as exc:
                self.last_reason = f"Android 前景查询失败：{exc}"
                return "unknown"
            self.last_reason = "Android 当前任务归属查询"
            return "target" if value is True else "external" if value is False else "unknown"
        if self.desktop_window_owner is None:
            self.last_reason = "当前环境没有独立窗口归属接口"
            return "target"
        try:
            value = self.desktop_window_owner.is_foreground()
        except Exception as exc:
            self.last_reason = f"桌面窗口归属查询失败：{exc}"
            return "unknown"
        self.last_reason = str(self.desktop_window_owner.last_reason or "")
        return "target" if value is True else "external" if value is False else "unknown"

    def recover(self) -> Any:
        """Return to the target app without creating traversal edges."""
        if is_android(self.platform):
            try:
                observation = self.env.step(
                    {"action_type": "navigate_back"}, pause=1.0) or {}
                if self.check() == "target":
                    return observation or self.env._get_obs()
            except Exception:
                pass
        if not is_android(self.platform) and self.desktop_window_owner is not None:
            try:
                if self.desktop_window_owner.activate():
                    return self.env._get_obs()
            except Exception:
                pass
        return self.restart_preserving_data()

    def restart_preserving_data(self) -> Any:
        """Force-stop and relaunch through the injected lifecycle callback."""
        if self.relaunch_fn is not None:
            return self.relaunch_fn()
        return self.env._get_obs()


__all__ = ["ScopeGuard"]
