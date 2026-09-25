"""Native benchmark action contracts shared by prompts and validators."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple


ANDROID_ACTIONS: Mapping[str, Mapping[str, Any]] = {
    "click": {"targeted": True},
    "double_tap": {"targeted": True},
    "long_press": {"targeted": True},
    "input_text": {"targeted": True, "required": {"text": str}},
    "keyboard_enter": {},
    "navigate_back": {},
    "navigate_home": {},
    "open_app": {"required": {"app_name": str}},
    "scroll": {"required": {"direction": str}},
    "swipe": {"required": {"direction": str}},
    "wait": {},
}

OSWORLD_ACTIONS: Mapping[str, Mapping[str, Any]] = {
    "MOVE_TO": {"targeted": True},
    "CLICK": {"targeted": True},
    "MOUSE_DOWN": {},
    "MOUSE_UP": {},
    "RIGHT_CLICK": {"targeted": True},
    "DOUBLE_CLICK": {"targeted": True},
    "DRAG_TO": {"required": {"x": (int, float), "y": (int, float)}},
    "SCROLL": {"required": {"dx": int, "dy": int}},
    "TYPING": {"required": {"text": str}},
    "PRESS": {"required": {"key": str}},
    "KEY_DOWN": {"required": {"key": str}},
    "KEY_UP": {"required": {"key": str}},
    "HOTKEY": {"required": {"keys": list}},
    "WAIT": {},
}

ANDROID_DIRECTIONS = {"left", "right", "up", "down"}
MOUSE_BUTTONS = {"left", "right", "middle"}


def is_android(platform: str) -> bool:
    return str(platform or "").strip().casefold() in {
        "android", "androidworld",
    }


def action_contract(platform: str) -> Mapping[str, Mapping[str, Any]]:
    return ANDROID_ACTIONS if is_android(platform) else OSWORLD_ACTIONS


def action_is_targeted(platform: str, action_type: str) -> bool:
    key = (str(action_type or "").casefold()
           if is_android(platform) else str(action_type or "").upper())
    return bool(action_contract(platform).get(key, {}).get("targeted"))


def _parameters(action: Mapping[str, Any], *, mobile: bool) -> Mapping[str, Any]:
    if mobile:
        return action
    value = action.get("parameters")
    return value if isinstance(value, dict) else {}


def normalize_native_action(
    action: Mapping[str, Any], *, platform: str,
) -> Tuple[Dict[str, Any] | None, str]:
    """Validate one native AndroidWorld or OSWorld action dictionary."""
    if not isinstance(action, Mapping):
        return None, "action must be an object"
    mobile = is_android(platform)
    raw_type = str(action.get("action_type") or "").strip()
    action_type = raw_type.casefold() if mobile else raw_type.upper()
    contract = action_contract(platform)
    spec = contract.get(action_type)
    if spec is None:
        return None, "invalid platform action"
    normalized = dict(action)
    normalized["action_type"] = action_type
    params = _parameters(normalized, mobile=mobile)
    for name, expected in dict(spec.get("required") or {}).items():
        value = params.get(name)
        if value is None or not isinstance(value, expected):
            return None, f"missing or invalid parameter: {name}"
    if mobile and action_type in {"scroll", "swipe"}:
        if str(params.get("direction") or "").casefold() not in ANDROID_DIRECTIONS:
            return None, "invalid direction"
        normalized["direction"] = str(params["direction"]).casefold()
    if not mobile:
        parameters = dict(params)
        button = parameters.get("button")
        if button is not None and str(button).casefold() not in MOUSE_BUTTONS:
            return None, "invalid mouse button"
        if action_type == "CLICK" and parameters.get("num_clicks") is not None:
            if parameters["num_clicks"] not in {1, 2, 3}:
                return None, "invalid num_clicks"
        if action_type == "HOTKEY" and not all(
                isinstance(key, str) and key for key in parameters.get("keys", [])):
            return None, "invalid hotkey keys"
        normalized["parameters"] = parameters
    return normalized, ""


def action_prompt_lines(platform: str) -> list[str]:
    """Return schema-only benchmark action documentation for the VLM."""
    if is_android(platform):
        return [
            "AndroidWorld JSONAction schema (exact lowercase action_type):",
            "- click, double_tap, long_press: choice_id is required; coordinates are added after live grounding.",
            "- input_text: choice_id and string text are required.",
            "- keyboard_enter, navigate_back, navigate_home, wait: no parameters.",
            "- open_app: string app_name is required.",
            "- scroll, swipe: direction is required and must be left, right, up, or down.",
            "Use AndroidWorld fields at the top level of action; do not add a parameters object.",
        ]
    return [
        "OSWorld computer_13 schema (exact uppercase action_type; arguments are in action.parameters):",
        "- MOVE_TO: choice_id is required; x and y are added after live grounding.",
        "- CLICK: choice_id is required; optional button=left|right|middle and num_clicks=1|2|3.",
        "- RIGHT_CLICK, DOUBLE_CLICK: choice_id is required; x and y are added after live grounding.",
        "- MOUSE_DOWN, MOUSE_UP: optional button=left|right|middle.",
        "- DRAG_TO: numeric x and y are required.",
        "- SCROLL: integer dx and dy are required.",
        "- TYPING: string text is required.",
        "- PRESS, KEY_DOWN, KEY_UP: string key is required.",
        "- HOTKEY: string-array keys is required.",
        "- WAIT: no parameters.",
    ]


__all__ = [
    "ANDROID_ACTIONS", "OSWORLD_ACTIONS", "action_contract",
    "action_is_targeted", "action_prompt_lines", "is_android",
    "normalize_native_action",
]
