"""Platform-neutral action validation and primitive conversion."""

from __future__ import annotations

from dataclasses import asdict
from io import BytesIO
from typing import Any, Dict, Optional, Sequence

from PIL import Image

from .contracts import ActionRequest


def is_android(platform: str) -> bool:
    return str(platform or "").casefold() in {"android", "androidworld"}


def _pixel_point(screenshot: bytes, point: Sequence[float]) -> tuple[int, int]:
    with Image.open(BytesIO(screenshot)) as image:
        width, height = image.size
    return (
        round(float(point[0]) * max(0, width - 1) / 1000.0),
        round(float(point[1]) * max(0, height - 1) / 1000.0),
    )


def validate_for_platform(action: ActionRequest, *, platform: str) -> str:
    mobile = is_android(platform)
    if mobile and action.kind in {"hover", "right_click", "double_click"}:
        return (f"action.kind={action.kind}：当前 Android 执行器不支持该动作；"
                "请根据截图选择支持的 click/long_press/scroll/back 等动作，不能直接套用桌面交互。")
    if not mobile and action.kind == "long_press":
        return "桌面端 long_press 应改用 right_click 或普通 click"
    if action.purpose == "execute" and not action.operation_ref:
        return (f"action.owner_ref={action.owner_ref!r} 未解析出执行绑定；"
                "请复制当前实际控件或区块的 owner_ref；新控件先补清单，不要手填内部 purpose/operation_ref。")
    return ""


def to_primitive(
    action: ActionRequest,
    *,
    screenshot: bytes,
    platform: str,
) -> Optional[Dict[str, Any]]:
    mobile = is_android(platform)
    point = (
        _pixel_point(screenshot, action.point_1000)
        if action.point_1000 is not None else None
    )
    if action.kind == "wait":
        return None
    if action.kind == "back":
        return ({"action_type": "navigate_back"} if mobile else
                {"action_type": "PRESS", "parameters": {"key": "esc"}})
    if action.kind == "scroll" and point is not None:
        if mobile:
            with Image.open(BytesIO(screenshot)) as image:
                axis = image.height if action.direction in {"up", "down"} else image.width
            return {
                "action_type": "scroll", "direction": action.direction,
                "x": point[0], "y": point[1],
                "frac": min(1.0, float(action.amount) / max(1, axis)),
            }
        wheel = max(1, round(action.amount / 125))
        dx, dy = {
            "up": (0, wheel), "down": (0, -wheel),
            "left": (-wheel, 0), "right": (wheel, 0),
        }[action.direction]
        return {
            "action_type": "SCROLL",
            "parameters": {"x": point[0], "y": point[1], "dx": dx, "dy": dy},
        }
    if point is None:
        raise ValueError(f"action.point_1000: {action.kind} requires a point；请填写最新整屏 0..1000 尺度的 [x,y]。")
    x, y = point
    if action.kind == "click":
        return ({"action_type": "click", "x": x, "y": y} if mobile else {
            "action_type": "CLICK",
            "parameters": {"x": x, "y": y, "button": "left"},
        })
    if action.kind in {"double_click", "right_click"}:
        return {
            "action_type": "DOUBLE_CLICK" if action.kind == "double_click"
            else "RIGHT_CLICK",
            "parameters": {"x": x, "y": y},
        }
    if action.kind == "long_press":
        return {"action_type": "long_press", "x": x, "y": y}
    if action.kind == "hover":
        return {
            "action_type": "HOVER",
            "parameters": {"x": x, "y": y, "dwell_ms": 700},
        }
    if action.kind == "input_text":
        return ({
            "action_type": "input_text", "x": x, "y": y,
            "text": action.text, "clear_text": True,
        } if mobile else {
            "action_type": "TYPING",
            "parameters": {"x": x, "y": y, "text": action.text},
        })
    raise ValueError(f"unsupported action kind: {action.kind}")


def action_dict(action: ActionRequest) -> Dict[str, Any]:
    value = asdict(action)
    if not value.get("owner_ref"):
        value.pop("owner_ref", None)
    if value.get("point_1000") is not None:
        value["point_1000"] = list(value["point_1000"])
    return value


__all__ = [
    "execute_action", "action_dict", "is_android", "to_primitive", "validate_for_platform",
]


def execute_action(env, action, *, screenshot, platform, pause=2.0, executed_actions=None):
    """Execute the same semantic input/action sequence for explore and collect."""
    import time
    primitive = to_primitive(action, screenshot=screenshot, platform=platform)
    if primitive is None:
        time.sleep(pause)
        return env._get_obs() or {}
    steps = [primitive]
    if action.kind == "input_text" and not is_android(platform):
        parameters = primitive["parameters"]
        steps = [
            {"action_type": "CLICK", "parameters": {
                "x": parameters["x"], "y": parameters["y"], "button": "left"}},
            {"action_type": "HOTKEY", "parameters": {"keys": ["ctrl", "a"]}},
            ({"action_type": "TYPING", "parameters": {"text": action.text}} if action.text
             else {"action_type": "PRESS", "parameters": {"key": "backspace"}}),
        ]
    observation = {}
    for index, step in enumerate(steps):
        observation = env.step(step, pause=pause if index == len(steps) - 1 else 0) or {}
        if executed_actions is not None:
            executed_actions.append(step)
        if observation.get("action_error"):
            break
    return observation
