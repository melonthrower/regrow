"""Generate geometry-free legacy replies accepted by the current Qwen parser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def _element(
    name: str,
    element_type: str,
    *,
    interactive: bool = False,
    category: str = "display",
    enabled: bool = True,
    blocked_reason: str = "",
    stateful: bool = False,
    state_key: str = "",
    state_value: str = "unknown",
    effect_scope: str = "unknown",
    back: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "type": element_type,
        "interactive": interactive,
        "category": category,
        "selected": False,
        "group": "",
        "back": back,
        "enabled": enabled,
        "requires_permission": blocked_reason.endswith("permission")
        or "permission" in blocked_reason,
        "blocked_reason": blocked_reason,
        "stateful": stateful,
        "state_key": state_key,
        "state_value": state_value,
        "effect_scope": effect_scope if stateful else "unknown",
        "reversible": True if stateful else None,
        "risk": "none" if stateful else "unknown",
        "identity_anchor": True,
    }


def _category(control: dict[str, Any]) -> str:
    value = control.get("category")
    if value == "dangerous":
        return "dangerous"
    if value in {"stateful", "input"}:
        return "shallow"
    return "navigation"


def _page_response(
    oracle: dict[str, Any],
    page_id: str,
    key: str,
    visible_control_ids: set[str] | None = None,
    state_values: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    page = next(row for row in oracle["pages"] if row["id"] == page_id)
    blocks = []
    for block in page["blocks"]:
        elements = []
        if block["role"] == "top_app_bar":
            elements.append(_element(page["title"], "heading"))
        for control in page["controls"]:
            if control["block"] != block["id"]:
                continue
            if visible_control_ids is not None and control["id"] not in visible_control_ids:
                continue
            stateful = control.get("category") == "stateful"
            elements.append(_element(
                control["label"],
                control["type"],
                interactive=True,
                category=_category(control),
                enabled=control.get("enabled", True),
                blocked_reason=control.get("blocked_reason", ""),
                stateful=stateful,
                state_key=control["id"].split(".")[-1] if stateful else "",
                state_value=(state_values or {}).get(control["id"], "unknown"),
                effect_scope=control.get("effect_scope", "unknown"),
                back=control["id"].endswith(".back"),
            ))
        if elements:
            blocks.append({
                "role": block["role"],
                "scope": "target_app",
                "interaction": "direct",
                "note": f"Visible {block['role'].replace('_', ' ')}",
                "scrollable": block.get("scrollable", False),
                "elements": elements,
            })
    return key, {
        "page": page["title"],
        "surface_kind": "page",
        "surface_scrollable": page["scroll"]["classification"] == "scrollable",
        "is_system_dialog": False,
        "is_interruption": False,
        "blocks": blocks,
    }


def _surface_response(
    oracle: dict[str, Any], surface_id: str, key: str
) -> tuple[str, dict[str, Any]]:
    surface = next(row for row in oracle["surfaces"] if row["id"] == surface_id)
    host = next(row for row in oracle["pages"] if row["id"] == surface["host_pages"][0])
    elements = [_element(surface["anchors"][0], "heading")]
    for control in surface["controls"]:
        elements.append(_element(
            control["label"],
            control["type"],
            interactive=True,
            category=_category(control),
            enabled=control.get("enabled", True),
            blocked_reason=control.get("blocked_reason", ""),
            back=control["id"].endswith(".close") or control["id"] == "clear.cancel",
        ))
    return key, {
        "page": host["title"],
        "surface_kind": surface["kind"],
        "surface_scrollable": False,
        "is_system_dialog": False,
        "is_interruption": False,
        "blocks": [{
            "role": surface["kind"],
            "scope": "target_app",
            "interaction": "direct",
            "note": "Active surface only; background excluded",
            "scrollable": False,
            "elements": elements,
        }],
    }


def build_responses() -> dict[str, dict[str, Any]]:
    oracle = json.loads((ROOT / "oracle.json").read_text(encoding="utf-8"))
    rows = [
        _page_response(oracle, "inbox", "inbox.top", {
            "inbox.search", "inbox.new_chat", "inbox.open_weekend",
            "inbox.open_alex", "inbox.nav_contacts", "inbox.nav_explore",
            "inbox.nav_profile",
        }),
        _page_response(oracle, "inbox", "inbox.bottom", {
            "inbox.nav_contacts", "inbox.nav_explore", "inbox.nav_profile",
        }),
        _page_response(oracle, "conversation", "conversation.top", {
            "conversation.back", "conversation.call", "conversation.info",
        }),
        _page_response(oracle, "conversation", "conversation.bottom", {
            "conversation.attach", "conversation.message", "conversation.send",
        }),
        _page_response(oracle, "contacts", "contacts.top", {
            "contacts.add", "contacts.new_friends", "contacts.open_alex",
            "contacts.nav_inbox", "contacts.nav_explore", "contacts.nav_profile",
        }),
        _page_response(oracle, "contacts", "contacts.bottom", {
            "contacts.nav_inbox", "contacts.nav_explore", "contacts.nav_profile",
        }),
        _page_response(oracle, "contact_profile", "contact_profile.favorite_off", None, {
            "contact.favorite": "off",
        }),
        _page_response(oracle, "contact_profile", "contact_profile.favorite_on", None, {
            "contact.favorite": "on",
        }),
        _page_response(oracle, "explore", "explore.default"),
        _page_response(oracle, "profile", "profile.default"),
        _page_response(oracle, "settings", "settings.notifications_on", None, {
            "settings.notifications_toggle": "on",
        }),
        _page_response(oracle, "settings", "settings.notifications_off", None, {
            "settings.notifications_toggle": "off",
        }),
        _page_response(oracle, "chat_info", "chat_info.mute_off", None, {
            "chat_info.mute": "off",
        }),
        _page_response(oracle, "chat_info", "chat_info.mute_on", None, {
            "chat_info.mute": "on",
        }),
        _surface_response(oracle, "inbox.new_chat_sheet", "inbox.menu_open"),
        _surface_response(oracle, "conversation.attach_sheet", "conversation.attach_open"),
        _surface_response(oracle, "chat_info.clear_dialog", "chat_info.clear_open"),
    ]
    return dict(rows)


def write_responses(path: Path | None = None) -> Path:
    output = path or ROOT / "qwen_responses.json"
    output.write_text(
        json.dumps(build_responses(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


if __name__ == "__main__":
    print(f"built {write_responses()}")
