"""Generate geometry-free legacy replies accepted by the current Qwen parser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def element(
    name: str,
    element_type: str,
    *,
    interactive: bool = False,
    category: str = "display",
    selected: bool = False,
    group: str = "",
    back: bool = False,
    enabled: bool = True,
    requires_permission: bool = False,
    blocked_reason: str = "",
    stateful: bool = False,
    state_key: str = "",
    state_value: str = "unknown",
    effect_scope: str = "unknown",
    reversible: bool | None = None,
    risk: str = "unknown",
    identity_anchor: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "type": element_type,
        "interactive": interactive,
        "category": category,
        "selected": selected,
        "group": group,
        "back": back,
        "enabled": enabled,
        "requires_permission": requires_permission,
        "blocked_reason": blocked_reason,
        "stateful": stateful,
        "state_key": state_key,
        "state_value": state_value,
        "effect_scope": effect_scope,
        "reversible": reversible,
        "risk": risk,
        "identity_anchor": identity_anchor,
    }


def block(role: str, note: str, scrollable: bool, *elements: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": role,
        "scope": "target_app",
        "interaction": "direct",
        "note": note,
        "scrollable": scrollable,
        "elements": list(elements),
    }


def inventory(
    page: str,
    surface_kind: str,
    surface_scrollable: bool,
    *blocks: dict[str, Any],
) -> dict[str, Any]:
    return {
        "page": page,
        "surface_kind": surface_kind,
        "surface_scrollable": surface_scrollable,
        "is_system_dialog": False,
        "is_interruption": False,
        "blocks": list(blocks),
    }


def app_bar(title: str, *, more: bool = True, back_label: str = "") -> dict[str, Any]:
    rows = [element(title, "text")]
    if back_label:
        rows.insert(0, element(
            back_label, "button", interactive=True, category="navigation", back=True
        ))
    if more:
        rows.append(element("More options", "button", interactive=True, category="navigation"))
    return block("top_app_bar", "Application title and navigation actions", False, *rows)


def primary_navigation(selected: str) -> dict[str, Any]:
    rows = [
        element(
            label,
            "tab",
            interactive=True,
            category="navigation",
            selected=label == selected,
            group="bottom_nav",
            stateful=False,
            state_key="",
            state_value="unknown",
            effect_scope="unknown",
            reversible=None,
            risk="unknown",
        )
        for label in ("Home", "Documents", "Activity", "Settings")
    ]
    return block("primary_navigation", "Shared desktop sidebar", False, *rows)


def build_responses() -> dict[str, dict[str, Any]]:
    responses: dict[str, dict[str, Any]] = {}
    responses["home.default"] = inventory(
        "Home", "page", False,
        app_bar("Home"),
        block(
            "hero", "Welcome summary and primary entry", False,
            element("Good morning, Alex", "heading"),
            element("Browse documents", "button", interactive=True, category="navigation"),
        ),
        block(
            "content", "Quick navigation checks", False,
            element("View recent activity", "button", interactive=True, category="navigation"),
            element("Open settings", "button", interactive=True, category="navigation"),
        ),
        primary_navigation("Home"),
    )
    responses["home.menu_open"] = inventory(
        "Home", "popup_menu", False,
        block(
            "popup_menu", "Active quick menu; background excluded", False,
            element("Workspace menu", "heading"),
            element("About Dayline", "menu_item", interactive=True, category="navigation"),
            element("Close menu", "button", interactive=True, category="navigation", back=True),
        ),
    )

    def record_row(number: int) -> dict[str, Any]:
        value = f"{number:02d}"
        return element(
            f"Open Document {value}",
            "button",
            interactive=True,
            category="navigation",
            group="record_item",
        )

    responses["library.top"] = inventory(
        "Documents", "page", True,
        app_bar("Documents"),
        block(
            "summary", "Visible list summary", False,
            element("All documents", "text"),
        ),
        block(
            "content_list", "Visible top records only", True,
            *(record_row(number) for number in range(1, 6)),
        ),
        primary_navigation("Documents"),
    )
    responses["library.bottom"] = inventory(
        "Documents", "page", True,
        app_bar("Documents"),
        block(
            "content_list", "Visible bottom records only", True,
            *(record_row(number) for number in range(6, 10)),
        ),
        primary_navigation("Documents"),
    )

    for reviewed in (False, True):
        label = "Mark unreviewed" if reviewed else "Mark reviewed"
        responses[f"record_detail.{'reviewed' if reviewed else 'unreviewed'}"] = inventory(
            "Document details", "page", False,
            app_bar("Document details", more=False, back_label="Back to documents"),
            block(
                "summary", "Record identity and data-only instance values", False,
                element("Document details", "heading"),
                element("Owner", "text", identity_anchor=False),
                element("Updated", "text"),
            ),
            block(
                "actions", "Reversible review status", False,
                element(
                    label,
                    "switch",
                    interactive=True,
                    category="shallow",
                    stateful=True,
                    state_key="reviewed",
                    state_value="on" if reviewed else "off",
                    effect_scope="data_only",
                    reversible=True,
                    risk="none",
                ),
            ),
        )

    def activity_events(start: int, end: int) -> list[dict[str, Any]]:
        names = ("Document updated", "Comment resolved", "Document shared", "Review completed")
        return [
            element(names[(number - 1) % 4], "text", identity_anchor=number == 1)
            for number in range(start, end + 1)
        ]

    responses["activity.top"] = inventory(
        "Recent activity", "page", True,
        app_bar("Recent activity"),
        block("timeline", "Visible top activity events", True, *activity_events(1, 6)),
        primary_navigation("Activity"),
    )
    responses["activity.bottom"] = inventory(
        "Recent activity", "page", True,
        app_bar("Recent activity"),
        block("timeline", "Visible bottom activity events", True, *activity_events(10, 14)),
        block(
            "actions", "Below-fold report entry", False,
            element("View weekly summary", "button", interactive=True, category="navigation"),
        ),
        primary_navigation("Activity"),
    )

    responses["coverage_report.default"] = inventory(
        "Weekly summary", "page", False,
        app_bar("Weekly summary", more=False, back_label="Back to activity"),
        block(
            "summary", "Weekly activity metrics", False,
            element("Documents updated", "text"),
            element("Reviews completed", "text"),
        ),
        block(
            "content", "Weekly highlights", False,
            element("Launch plan is ready", "text"),
            element("Customer themes consolidated", "text"),
            element("Three reviews completed", "text"),
            element("Decision log refreshed", "text"),
        ),
        block(
            "actions", "Completion entry", False,
            element("Archive weekly summary", "button", interactive=True, category="navigation"),
        ),
    )
    responses["coverage_report.confirm_open"] = inventory(
        "Weekly summary", "dialog", False,
        block(
            "dialog", "Active completion confirmation; background excluded", False,
            element("Archive this summary?", "heading"),
            element("Cancel", "button", interactive=True, category="navigation", back=True),
            element("Archive summary", "button", interactive=True, category="navigation"),
        ),
    )

    for enabled in (False, True):
        responses[f"settings.tips_{'on' if enabled else 'off'}"] = inventory(
            "Settings", "page", False,
            app_bar("Settings"),
            block(
                "settings_list", "Workspace preferences", False,
                element(
                    "Daily digest",
                    "switch",
                    interactive=True,
                    category="shallow",
                    stateful=True,
                    state_key="daily_tips",
                    state_value="on" if enabled else "off",
                    effect_scope="data_only",
                    reversible=True,
                    risk="none",
                ),
                element(
                    "Cloud sync",
                    "button",
                    interactive=True,
                    category="navigation",
                    enabled=False,
                    requires_permission=True,
                    blocked_reason="login_required",
                ),
            ),
            block(
                "actions", "Application information entry", False,
                element("About Dayline", "button", interactive=True, category="navigation"),
            ),
            primary_navigation("Settings"),
        )

    responses["about.top"] = inventory(
        "About Dayline", "page", True,
        app_bar("About Dayline", more=False, back_label="Back"),
        block(
            "content", "Visible top product sections", True,
            element("Dayline 1.0", "heading"),
            element("Designed for focus", "heading"),
            element("Documents", "heading"),
        ),
    )
    responses["about.bottom"] = inventory(
        "About Dayline", "page", True,
        app_bar("About Dayline", more=False, back_label="Back"),
        block(
            "content", "Visible bottom product sections", True,
            element("Keyboard help", "heading"),
            element("Product notes", "heading"),
        ),
        block(
            "actions", "Stable bottom action", False,
            element("Back to home", "button", interactive=True, category="navigation", back=True),
        ),
    )
    responses["done.default"] = inventory(
        "Summary archived", "page", False,
        block(
            "completion", "Archived weekly summary", False,
            element("Summary archived", "heading"),
            element("Your workspace is ready for a fresh week", "text"),
        ),
        block(
            "actions", "Return action", False,
            element("Back to home", "button", interactive=True, category="navigation", back=True),
        ),
    )
    return responses


def write_responses(path: Path | None = None) -> Path:
    output = path or ROOT / "qwen_responses.json"
    output.write_text(
        json.dumps(build_responses(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


if __name__ == "__main__":
    print(f"built {write_responses()}")
