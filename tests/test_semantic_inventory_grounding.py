from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from gui_rewalk.src.core.visual_traversal import visual_cache
from gui_rewalk.src.core.visual_traversal.agents.review import AnnotationReviewer
from gui_rewalk.src.core.visual_traversal.artifacts import ArtifactWriter
from gui_rewalk.src.core.visual_traversal.live_targeting import LiveTargeting
from gui_rewalk.src.core.visual_traversal.visual_perception import (
    ACTIVE_SURFACE_PAGE,
    VisualElement,
    VisualPerception,
)


def _frame(width=200, height=120):
    stream = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(stream, "PNG")
    return stream.getvalue()


def test_inventory_is_bbox_free_and_region_ids_are_local(monkeypatch):
    response = {
        "page": "Alarm", "surface_kind": "page",
        "passive_feedback_present": True, "blocks": [{
            "id": "untrusted-b0", "role": "primary_navigation",
            "scope": "target_app", "interaction": "direct",
            "page_identity": True, "bbox_1000": [0, 0, 1000, 1000],
            "elements": [
                {"name": "Alarm", "type": "tab", "category": "navigation",
                 "risk": "none", "interactive": True, "selected": True,
                 "enabled": True, "group": "Primary tabs",
                 "identity_anchor": True},
                {"name": "Clock", "type": "tab", "category": "navigation",
                 "interactive": True, "selected": False, "identity_anchor": True,
                 "group": "Primary tabs", "stateful": False, "risk": "none"},
                {"name": "Vibrate", "type": "switch", "category": "navigation",
                 "interactive": True, "selected": False, "identity_anchor": True,
                 "stateful": True, "state_key": "vibrate",
                 "state_value": "off", "effect_scope": "function_set",
                 "reversible": True, "risk": "none"},
            ]}]
    }
    monkeypatch.setattr(
        visual_cache, "predict_mm_role",
        lambda *args, **kwargs: (json.dumps(response), None, None))
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    elements = perception.semantic_inventory(_frame())
    assert perception.last_passive_feedback_present is True
    assert [item.name for item in elements] == ["Alarm", "Clock", "Vibrate"]
    assert all(item.bbox_xywh == [0, 0, 0, 0] for item in elements)
    assert all(item.center == [0, 0] for item in elements)
    assert all(item.geometry_status == "semantic_only" for item in elements)
    block = perception.last_semantic_blocks[0]
    assert block["local_id"] == "b0"
    assert block["bbox_1000"] == [0, 0, 1000, 1000]
    assert "region_id" not in block
    assert all(item.region_id == "b0" for item in elements)
    clock = elements[1]
    assert elements[0].selected is True
    assert elements[0].enabled is True
    assert [elements[0].group, clock.group] == [
        "primary tabs", "primary tabs"]
    assert clock.selected is False and clock.stateful is False
    assert clock.el_type == "target" and clock.category == "navigation"
    assert (clock.state_key, clock.state_value, clock.effect_scope,
            clock.reversible, clock.risk) == ("", "", "", None, "none")
    switch = elements[2]
    assert switch.stateful is True and switch.state_key == "vibrate"
    assert switch.state_value == "off"
    assert switch.effect_scope == "function_set"
    assert switch.reversible is True
    assert switch.is_safe_stateful_surface()


def test_live_inventory_excludes_explicit_auxiliary_blocks(monkeypatch):
    response = {
        "page": "Editor", "surface_kind": "page", "blocks": [{
            "role": "content", "scope": "target_app",
            "interaction": "direct",
            "bbox_1000": [0, 0, 1000, 500],
            "elements": [{
                "name": "Title", "category": "display", "risk": "none",
                "selected": False,
            }],
        }, {
            "role": "input_relay", "scope": "auxiliary",
            "interaction": "direct",
            "bbox_1000": [0, 500, 1000, 1000],
            "elements": [{
                "name": "Relayed input", "category": "shallow", "risk": "none",
                "selected": False,
            }],
        }],
    }
    monkeypatch.setattr(
        visual_cache, "predict_mm_role",
        lambda *args, **kwargs: (json.dumps(response), None, None))

    perception = VisualPerception(None, agent=object(), use_ocr=False)
    elements = perception.semantic_inventory(_frame())

    assert [element.name for element in elements] == ["Title"]
    assert [block["role"] for block in perception.last_semantic_blocks] == [
        "content"]


def test_live_inventory_excludes_explicit_background_blocks(monkeypatch):
    response = {
        "page": "Foreground actions", "surface_kind": "page", "blocks": [{
            "role": "foreground_actions", "scope": "target_app",
            "interaction": "direct",
            "bbox_1000": [500, 0, 1000, 300],
            "elements": [{
                "name": "Help", "category": "navigation", "risk": "none",
                "selected": False,
            }],
        }, {
            "role": "underlying_content", "scope": "target_app",
            "interaction": "background",
            "bbox_1000": [0, 0, 1000, 1000],
            "elements": [{
                "name": "Visible but blocked", "category": "navigation",
                "risk": "none", "selected": False,
            }],
        }],
    }
    monkeypatch.setattr(
        visual_cache, "predict_mm_role",
        lambda *args, **kwargs: (json.dumps(response), None, None))

    perception = VisualPerception(None, agent=object(), use_ocr=False)
    elements = perception.semantic_inventory(_frame())

    assert [element.name for element in elements] == ["Help"]
    assert [block["interaction"] for block in perception.last_semantic_blocks] == [
        "direct"]


def test_background_scrollability_does_not_trigger_foreground_scroll_review(
        monkeypatch):
    response = {
        "page": "Foreground choices",
        "surface_kind": "page",
        "surface_scrollable": True,
        "blocks": [{
            "role": "choices", "scope": "target_app",
            "interaction": "direct", "scrollable": False,
            "bbox_1000": [200, 300, 500, 500],
            "elements": [{
                "name": "First choice", "category": "shallow",
                "risk": "none", "selected": True,
            }, {
                "name": "Second choice", "category": "shallow",
                "risk": "none", "selected": False,
            }],
        }, {
            "role": "underlying_content", "scope": "target_app",
            "interaction": "background", "scrollable": True,
            "bbox_1000": [0, 0, 1000, 1000],
            "elements": [],
        }],
    }
    roles = []

    def predict(_agent, role, *_args, **_kwargs):
        roles.append(role)
        if role != "semantic_inventory":
            raise AssertionError("background motion must not trigger review")
        return json.dumps(response), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    elements = perception.semantic_inventory(_frame())

    assert roles == ["semantic_inventory"]
    assert [element.name for element in elements] == [
        "First choice", "Second choice"]
    assert [block["scrollable"]
            for block in perception.last_semantic_blocks] == [False]
    assert perception.last_surface_scrollable is False
    assert perception.last_scroll_viewport_review["status"] == "static"


def test_scroll_viewport_review_adds_parent_without_merging_function_blocks(
        monkeypatch):
    inventory = {
        "page": "Items",
        "surface_kind": "page",
        "surface_scrollable": True,
        "blocks": [
            {
                "role": "frame_actions", "scope": "target_app",
                "interaction": "direct", "scrollable": False,
                "bbox_1000": [0, 0, 1000, 100],
                "elements": [{
                    "name": "Menu", "category": "navigation", "risk": "none",
                    "selected": False,
                }],
            },
            {
                "role": "first_group", "scope": "target_app",
                "interaction": "direct", "scrollable": False,
                "bbox_1000": [0, 100, 1000, 500],
                "elements": [{
                    "name": "First item", "category": "navigation",
                    "risk": "none", "selected": False,
                }],
            },
            {
                "role": "second_group", "scope": "target_app",
                "interaction": "direct", "scrollable": False,
                "bbox_1000": [0, 500, 1000, 850],
                "elements": [{
                    "name": "Second item", "category": "navigation",
                    "risk": "none", "selected": False,
                }],
            },
            {
                "role": "floating_action", "scope": "target_app",
                "interaction": "direct", "scrollable": False,
                "bbox_1000": [400, 700, 600, 830],
                "elements": [{
                    "name": "Add", "category": "navigation", "risk": "none",
                    "selected": False,
                }],
            },
            {
                "role": "fixed_navigation", "scope": "target_app",
                "interaction": "direct", "scrollable": False,
                "bbox_1000": [0, 850, 1000, 1000],
                "elements": [{
                    "name": "Home", "category": "navigation", "risk": "none",
                    "selected": True,
                }],
            },
        ],
    }
    review = {
        "status": "ok",
        "viewports": [{
            "bbox_1000": [0, 100, 1000, 850],
            "reason": "two child groups move together",
        }],
    }
    roles = []

    def predict(_agent, role, *_args, **_kwargs):
        roles.append(role)
        payload = inventory if role == "semantic_inventory" else review
        return json.dumps(payload), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    elements = perception.semantic_inventory(_frame())

    assert roles == ["semantic_inventory", "scroll_viewport_review"]
    assert [block["role"] for block in perception.last_semantic_blocks] == [
        "frame_actions", "first_group", "second_group", "floating_action",
        "fixed_navigation", "scroll_viewport"]
    parent = perception.last_semantic_blocks[-1]
    assert parent["scrollable"] is True
    assert parent["bbox_1000"] == [0, 100, 1000, 850]
    assert parent["element_ids"] == []
    assert parent["element_names"] == []
    assert [element.region_id for element in elements] == [
        block["local_id"] for block in perception.last_semantic_blocks[:-1]]
    assert perception.last_scroll_viewport_review["status"] == "ok"


def test_uncertain_scroll_viewport_review_does_not_certify_static(monkeypatch):
    inventory = {
        "page": "Items",
        "surface_kind": "page",
        "surface_scrollable": True,
        "blocks": [{
            "role": "content", "scope": "target_app",
            "interaction": "direct", "scrollable": False,
            "bbox_1000": [0, 0, 1000, 1000],
            "elements": [{
                "name": "Item", "category": "navigation", "risk": "none",
                "selected": False,
            }],
        }],
    }

    def predict(_agent, role, *_args, **_kwargs):
        payload = inventory if role == "semantic_inventory" else {
            "status": "uncertain", "viewports": []}
        return json.dumps(payload), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    perception.semantic_inventory(_frame())

    assert perception.last_semantic_blocks[0]["scrollable"] is None
    assert perception.last_scroll_viewport_review["status"] == "uncertain"


def test_scroll_viewport_review_can_confirm_frontmost_surface_is_static(
        monkeypatch):
    inventory = {
        "page": "Actions",
        "surface_kind": "popup_menu",
        "surface_scrollable": True,
        "blocks": [{
            "role": "actions", "scope": "target_app",
            "interaction": "direct", "scrollable": False,
            "bbox_1000": [500, 100, 950, 400],
            "elements": [{
                "name": "Help", "category": "navigation", "risk": "none",
                "selected": False,
            }],
        }],
    }

    review_image = {}

    def predict(_agent, role, *_args, **_kwargs):
        if role == "scroll_viewport_review":
            review_image["pixels"] = _args[1][0]
        payload = inventory if role == "semantic_inventory" else {
            "status": "static", "viewports": []}
        return json.dumps(payload), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    perception.semantic_inventory(_frame())

    assert perception.last_semantic_blocks[0]["scrollable"] is False
    assert perception.last_surface_scrollable is False
    assert perception.last_scroll_viewport_review["status"] == "static"
    assert review_image["pixels"][10, 10].tolist() == [0, 0, 0]
    assert review_image["pixels"][20, 110].tolist() == [255, 255, 255]


def test_fixture_inventory_provider_bypasses_semantic_model(monkeypatch):
    monkeypatch.setattr(
        visual_cache, "predict_mm_role",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("semantic inventory model must be bypassed")))
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    perception.fixture_inventory_provider = lambda: {
        "page": "Chats", "surface_kind": "page", "blocks": [{
            "role": "top_app_bar", "fixture_oracle": True,
            "bbox_1000": [0, 0, 1000, 100],
            "scrollable": False, "elements": [{
                "name": "Recent chats", "type": "text",
                "category": "display", "interactive": False,
            }, {
                "name": "Search chats", "type": "button",
                "category": "navigation", "interactive": True,
                "enabled": True, "identity_anchor": True,
                "stateful": True, "state_key": "inbox.search",
                "state_value": "off", "effect_scope": "function_set",
                "reversible": True,
            }],
        }, {
            "role": "message_thread", "fixture_oracle": True,
            "bbox_1000": [0, 100, 1000, 900],
            "scrollable": True, "elements": [],
        }],
    }
    elements = perception.semantic_inventory(_frame())
    assert [element.name for element in elements] == [
        "Recent chats", "Search chats"]
    assert elements[0].interactive is False
    assert elements[0].category == "display"
    assert perception.last_page_name == "Chats"
    assert perception.last_semantic_blocks[0]["fixture_oracle"] is True
    assert perception.last_semantic_blocks[1]["scrollable"] is True
    assert perception.last_semantic_blocks[1]["element_ids"] == []
    assert elements[0].geometry_status == "semantic_only"
    assert (elements[1].category, elements[1].risk) == ("navigation", "none")
    assert elements[1].stateful is True
    assert elements[1].state_key == "inbox.search"
    assert elements[1].reversible is True


def test_live_semantic_inventory_missing_classification_fails_closed(monkeypatch):
    response = {
        "page": "Unknown dialog", "surface_kind": "dialog", "blocks": [{
            "role": "dialog", "scope": "target_app",
            "interaction": "direct",
            "elements": [{"name": "Unclassified action"}],
        }],
    }
    monkeypatch.setattr(
        visual_cache, "predict_mm_role",
        lambda *args, **kwargs: (json.dumps(response), None, None))

    element = VisualPerception(
        None, agent=object(), use_ocr=False).semantic_inventory(_frame())[0]

    assert (element.category, element.risk) == ("dangerous", "unknown")
    assert element.is_dangerous() is True


def test_live_description_contract_maps_fields_and_safety(monkeypatch):
    response = {
        "interface_summary": "Settings with the Network section selected",
        "surface_kind": "page",
        "surface_scrollable": False,
        "areas": [{
            "name": "Sidebar",
            "bbox_1000": [0, 0, 300, 1000],
            "scrollable": True,
            "context_labels": ["Settings categories"],
            "controls": [{
                "name": "Bluetooth",
                "purpose": "Open Bluetooth settings",
                "expected_immediate_effect": "Show Bluetooth controls",
                "visible_state": "unselected",
                "enabled": True,
                "selected": False,
                "evidence": "Bluetooth row in the category list",
                "execution_safety": "safe",
                "changes_available_controls": True,
            }, {
                "name": "Maximize",
                "purpose": "Maximize the application window",
                "expected_immediate_effect": "Change only the window layout",
                "visible_state": "available",
                "enabled": True,
                "selected": False,
                "evidence": "Window title-bar maximize icon",
                "execution_safety": "safe",
                "changes_available_controls": False,
                "state_axis": None,
                "state": None,
                "state_effect": None,
            }, {
                "name": "Airplane mode",
                "purpose": "Change connectivity outside this application",
                "expected_immediate_effect": "Disable wireless radios",
                "visible_state": "off",
                "enabled": True,
                "selected": False,
                "evidence": "Off switch",
                "execution_safety": "safe",
                "changes_available_controls": False,
                "state_axis": "network connectivity",
                "state": "off",
                "state_effect": "outside",
            }],
        }],
    }
    monkeypatch.setattr(
        visual_cache, "predict_mm_role",
        lambda *args, **kwargs: (json.dumps(response), None, None))

    perception = VisualPerception(None, agent=object(), use_ocr=False)
    elements = perception.semantic_inventory(_frame())

    assert perception.last_page_name == (
        "Settings with the Network section selected")
    assert perception.last_semantic_blocks[0]["role"] == "sidebar"
    assert perception.last_semantic_blocks[0]["context_labels"] == [
        "Settings categories"]
    bluetooth, maximize, airplane = elements
    assert (bluetooth.category, bluetooth.risk) == ("navigation", "none")
    assert bluetooth.purpose == "Open Bluetooth settings"
    assert bluetooth.expected_immediate_effect == "Show Bluetooth controls"
    assert bluetooth.visible_state == "unselected"
    assert bluetooth.semantic_evidence == (
        "Bluetooth row in the category list")
    assert bluetooth.execution_safety == "safe"
    assert bluetooth.changes_available_controls is True
    assert (maximize.category, maximize.risk) == ("shallow", "none")
    assert maximize.stateful is False
    assert (airplane.category, airplane.risk) == ("dangerous", "unknown")
    assert airplane.is_dangerous() is True


def test_live_result_contract_maps_to_execution_fields_and_validates_groups(
        monkeypatch):
    response = {
        "page": "Choices", "surface_kind": "page", "blocks": [{
            "role": "choices", "scope": "target_app",
            "interaction": "direct", "elements": [
                {"name": "Open other", "result": "opens"},
                {"name": "Current mode", "result": "opens",
                 "selected": True, "group": "mode"},
                {"name": "Other mode", "result": "opens",
                 "selected": False, "group": "mode"},
                {"name": "Current record", "result": "acts",
                 "selected": True, "group": "record"},
                {"name": "Other record", "result": "acts",
                 "selected": False, "group": "record"},
                {"name": "Status", "result": "read_only"},
                {"name": "External toggle", "result": "avoid",
                 "state": "on", "state_effect": "outside"},
            ],
        }],
    }
    def predict(_agent, role, *_args, **_kwargs):
        payload = (
            {"groups": [{
                "region_id": "b0", "group": "record", "keep": True,
                "reason": "same repeated record template",
            }]}
            if role == "semantic_group_review" else response
        )
        return json.dumps(payload), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)

    elements = VisualPerception(
        None, agent=object(), use_ocr=False).semantic_inventory(_frame())

    assert [(item.name, item.category, item.risk) for item in elements] == [
        ("Open other", "navigation", "none"),
        ("Current mode", "shallow", "none"),
        ("Other mode", "navigation", "none"),
        ("Current record", "shallow", "none"),
        ("Other record", "shallow", "none"),
        ("Status", "display", "none"),
        ("External toggle", "dangerous", "unknown"),
    ]
    assert [item.group for item in elements[1:5]] == [
        "", "", "record", "record"]
    toggle = elements[-1]
    assert toggle.stateful is True
    assert toggle.state_key == "external toggle"
    assert toggle.state_value == "on"
    assert toggle.effect_scope == "unknown"
    assert toggle.reversible is None


def test_description_contract_maps_shared_state_axis(monkeypatch):
    response = {
        "interface_summary": "Proxy mode chooser",
        "surface_kind": "dialog",
        "areas": [{
            "name": "Proxy mode",
            "controls": [{
                "name": "Automatic",
                "purpose": "Use automatic proxy configuration",
                "expected_immediate_effect": "Selects automatic proxy mode",
                "visible_state": "unselected",
                "enabled": True,
                "selected": False,
                "evidence": "Unselected radio option",
                "execution_safety": "safe",
                "changes_available_controls": True,
                "state_axis": "proxy mode",
                "state": "off",
                "state_effect": "controls",
            }, {
                "name": "Manual",
                "purpose": "Use manual proxy configuration",
                "expected_immediate_effect": "Keeps manual proxy fields enabled",
                "visible_state": "selected",
                "enabled": True,
                "selected": True,
                "evidence": "Selected radio option",
                "execution_safety": "safe",
                "changes_available_controls": True,
                "state_axis": "proxy mode",
                "state": "on",
                "state_effect": "controls",
            }],
        }],
    }
    monkeypatch.setattr(
        visual_cache, "predict_mm_role",
        lambda *args, **kwargs: (json.dumps(response), None, None))

    elements = VisualPerception(
        None, agent=object(), use_ocr=False).semantic_inventory(_frame())

    assert [element.state_key for element in elements] == [
        "proxy mode", "proxy mode"]
    assert [element.state_value for element in elements] == ["off", "on"]
    assert all(element.is_safe_stateful_surface() for element in elements)


def test_fixture_full_surface_inventory_preserves_oracle_geometry():
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    calls = []

    def provider(*, full_surface=False):
        calls.append(full_surface)
        return {
            "page": "Documents", "surface_kind": "page",
            "surface_scrollable": True,
            "blocks": [{
                "role": "content_list", "fixture_oracle": True,
                "scrollable": True, "elements": [{
                    "name": "Open Document 09", "interactive": True,
                    "bbox_xywh": [100, 1160, 200, 48],
                }],
            }],
        }

    perception.fixture_inventory_provider = provider
    elements = perception.semantic_inventory(_frame(), full_surface=True)

    assert calls == [True]
    assert elements[0].bbox_xywh == [100, 1160, 200, 48]
    assert elements[0].geometry_status == "fixture_full_surface"


def test_semantic_inventory_receives_navigation_context(monkeypatch):
    captured = {}
    response = {
        "page": "Screen saver", "surface_kind": "page", "blocks": [{
            "role": "content", "elements": [{
                "name": "12:30", "type": "text", "category": "display",
                "interactive": False,
            }],
        }],
    }

    def predict(_agent, _role, prompt, *_args, **_kwargs):
        captured["prompt"] = prompt
        return json.dumps(response), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    VisualPerception(None, agent=object(), use_ocr=False).semantic_inventory(
        _frame(), navigation_context=(
            "Previous page: Fullscreen Mode Instruction\n"
            "Action/control that opened the current frame: Got it\n"
            "The previous page itself was reached via Screen saver."))

    assert "NAVIGATION CONTEXT" in captured["prompt"]
    assert "Screen saver" in captured["prompt"]
    assert "do not discard a clear source/action chain" in captured["prompt"]


def test_semantic_target_reconciliation_is_text_only_and_one_to_one(monkeypatch):
    captured = {}

    def predict(_agent, role, prompt, images, *_args, **_kwargs):
        captured.update(role=role, prompt=prompt, images=images)
        return json.dumps({"mappings": [
            {"live_id": "10", "historical_id": "0", "reason": "same function"},
            {"live_id": "11", "historical_id": "0", "reason": "duplicate"},
            {"live_id": "12", "historical_id": "NEW", "reason": "new"},
            {"live_id": "13", "historical_id": "1", "reason": "same group"},
            {"live_id": "14", "historical_id": "2",
             "reason": "same target with optional group omitted earlier"},
        ]}), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    historical = [
        VisualElement(
            0, "Existing function", [0, 0, 0, 0], [0, 0],
            category="navigation"),
        VisualElement(
            1, "First alternative", [0, 0, 0, 0], [0, 0],
            category="shallow", group="alternatives"),
        VisualElement(
            2, "Minute input (00)", [0, 0, 0, 0], [0, 0],
            category="shallow"),
    ]
    live = [
        VisualElement(
            10, "First wording", [0, 0, 0, 0], [0, 0],
            category="navigation"),
        VisualElement(
            11, "Second wording", [0, 0, 0, 0], [0, 0],
            category="navigation"),
        VisualElement(
            12, "New function", [0, 0, 0, 0], [0, 0],
            category="navigation"),
        VisualElement(
            13, "Second alternative", [0, 0, 0, 0], [0, 0],
            category="shallow", group="alternatives"),
        VisualElement(
            14, "Minute input", [0, 0, 0, 0], [0, 0],
            category="shallow", group="time_input"),
    ]

    assert perception.reconcile_semantic_targets(historical, live) == {
        "10": "0", "13": "1", "14": "2"}
    assert captured["role"] == "semantic_target_reconciliation"
    assert captured["images"] == []
    assert "same GUI State" in captured["prompt"]
    assert "block membership is not target identity evidence" in captured["prompt"]
    assert "application-specific conventions" in captured["prompt"]


def test_block_role_does_not_override_top_level_surface(monkeypatch):
    response = {
        "page": "Clock", "surface_kind": "page", "surface_scrollable": False,
        "blocks": [{
            "role": "popup_menu", "scrollable": False,
            "scope": "target_app", "interaction": "direct",
            "elements": [
                {"name": "Screen saver", "type": "menu_item",
                 "category": "navigation", "interactive": True},
                {"name": "Settings", "type": "menu_item",
                 "category": "navigation", "interactive": True},
            ],
        }, {
            "role": "primary_navigation", "scrollable": False,
            "scope": "target_app", "interaction": "direct",
            "elements": [{"name": "Clock", "type": "tab",
                          "category": "navigation", "interactive": True,
                          "selected": True}],
        }],
    }
    prompts = []

    def predict(_agent, _role, prompt, *_args, **_kwargs):
        prompts.append(prompt)
        return json.dumps(response), None, None

    monkeypatch.setattr(
        visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)

    elements = perception.semantic_inventory(_frame())

    assert [element.name for element in elements] == [
        "Screen saver", "Settings", "Clock"]
    assert perception.last_surface_kind == ACTIVE_SURFACE_PAGE
    assert perception.last_is_modal is False
    assert [block["role"] for block in perception.last_semantic_blocks] == [
        "popup_menu", "primary_navigation"]
    assert all(element.surface_kind == ACTIVE_SURFACE_PAGE
               for element in elements)
    assert len(prompts) == 1


def test_compound_control_keeps_stable_name_and_live_action_alias(monkeypatch):
    response = {
        "page": "Settings", "surface_kind": "page", "blocks": [{
            "role": "content", "scope": "target_app",
            "interaction": "direct", "elements": [{
                "name": "Cloud sync", "action_label": "Sign in",
                "type": "button", "category": "navigation",
                "interactive": True, "enabled": False,
                "requires_permission": True,
                "blocked_reason": "application_login",
                "identity_anchor": True,
            }, {
                "name": "About Dayline", "action_label": "About Dayline",
                "type": "button", "category": "navigation",
                "interactive": True, "enabled": True,
            }, {
                "name": "Alex Lee", "action_label": "Personal workspace",
                "type": "text", "category": "display",
                "interactive": False,
            }],
        }],
    }
    monkeypatch.setattr(
        visual_cache, "predict_mm_role",
        lambda *args, **kwargs: (json.dumps(response), None, None))
    elements = VisualPerception(
        None, agent=object(), use_ocr=False).semantic_inventory(_frame())
    element = elements[0]
    assert element.name == "Cloud sync"
    assert element.action_label == ""
    assert element.enabled is False
    assert element.requires_permission is False
    assert element.blocked_reason == ""
    assert elements[1].action_label == ""
    assert elements[2].action_label == ""


def test_inventory_prompt_uses_factual_control_description_contract():
    from gui_rewalk.src.core.visual_traversal.prompts.block_inventory import (
        build_region_inventory_prompt,
    )
    from gui_rewalk.src.core.visual_traversal.prompts.grounding import (
        SEMANTIC_INVENTORY_PROMPT,
        VLM_GROUNDING_PROMPT,
        VLM_NAMING_PROMPT,
    )

    block_prompt = build_region_inventory_prompt({
        "interface_name": "Workspace", "region_id": "r0", "name": "Content",
    })
    marker = "Shared feature-entry classification"
    for prompt in (VLM_NAMING_PROMPT, VLM_GROUNDING_PROMPT):
        assert marker in prompt
        assert "previously unseen page, panel, dialog, menu, detail" in prompt
        assert "safety itself is uncertain, use dangerous" in prompt
    assert "function_entries" in block_prompt
    assert "entry_id" in block_prompt
    assert "target" in block_prompt
    for value in (
        '"category"', '"risk"', '"group"', '"priority"', '"navigation"',
        '"shallow"', '"bbox"', '"coordinates"',
    ):
        assert value not in block_prompt
    assert "改变数值或切换状态的控件不是功能入口" in block_prompt
    assert "已经是某项功能的具体操作界面" in block_prompt
    assert "返回空数组" in block_prompt
    assert marker not in SEMANTIC_INVENTORY_PROMPT
    assert "侧栏和 tab 一律留空" not in VLM_GROUNDING_PROMPT
    assert "同一重复交互模板的不同数据实例" in VLM_GROUNDING_PROMPT
    assert "purpose" in SEMANTIC_INVENTORY_PROMPT
    assert "expected_immediate_effect" in SEMANTIC_INVENTORY_PROMPT
    assert "visible_state" in SEMANTIC_INVENTORY_PROMPT
    assert '"execution_safety":"safe|do_not_execute|uncertain"' in (
        SEMANTIC_INVENTORY_PROMPT)
    assert '"changes_available_controls":true|false|null' in (
        SEMANTIC_INVENTORY_PROMPT)
    assert "Do not output opens, acts, shallow, navigation" in (
        SEMANTIC_INVENTORY_PROMPT)
    assert "Do not decide which" in SEMANTIC_INVENTORY_PROMPT
    assert "Derive the last two fields from expected_immediate_effect" in (
        SEMANTIC_INVENTORY_PROMPT)
    assert "mutate user content or configuration" in (
        SEMANTIC_INVENTORY_PROMPT)
    assert "different panel" in SEMANTIC_INVENTORY_PROMPT
    assert "dense repeated data view" in SEMANTIC_INVENTORY_PROMPT
    assert "only inventory compression" in SEMANTIC_INVENTORY_PROMPT
    assert "Shared placement, visual similarity" in SEMANTIC_INVENTORY_PROMPT
    assert "distinct purposes or immediate" in SEMANTIC_INVENTORY_PROMPT
    assert "same state_axis" in SEMANTIC_INVENTORY_PROMPT
    assert '"group"' not in SEMANTIC_INVENTORY_PROMPT
    assert '"result"' not in SEMANTIC_INVENTORY_PROMPT


def test_semantic_inventory_preserves_two_stage_danger_and_display(monkeypatch):
    responses = iter([{
        "page": "App info", "surface_kind": "page", "blocks": [{
            "role": "actions", "scope": "target_app",
            "interaction": "direct", "elements": [{
                "name": "Disable", "category": "navigation", "risk": "none",
            }],
        }],
    }, {
            "page": "Disable app confirmation", "surface_kind": "dialog",
            "blocks": [{"role": "dialog", "scope": "target_app",
                        "interaction": "direct", "elements": [{
            "name": "Disabling may affect other apps", "category": "display",
            "risk": "none",
        }, {
            "name": "Cancel", "category": "navigation", "risk": "none",
        }, {
            "name": "Disable app", "category": "dangerous",
            "risk": "destructive",
        }]}],
    }])
    monkeypatch.setattr(
        visual_cache, "predict_mm_role",
        lambda *args, **kwargs: (json.dumps(next(responses)), None, None))
    perception = VisualPerception(None, agent=object(), use_ocr=False)

    entry = perception.semantic_inventory(_frame())[0]
    dialog = perception.semantic_inventory(_frame())

    assert (entry.name, entry.category, entry.risk) == (
        "Disable", "navigation", "none")
    assert entry.is_dangerous() is False
    assert [(item.name, item.category, item.risk, item.interactive)
            for item in dialog] == [
        ("Disabling may affect other apps", "display", "none", False),
        ("Cancel", "navigation", "none", True),
        ("Disable app", "dangerous", "destructive", True),
    ]
    assert dialog[-1].is_dangerous() is True


def test_region_long_inventory_reuses_region_local_function_entry_contract(
        monkeypatch):
    captured = {}
    response = {
        "region_id": "r1",
        "function_entries": [
            {"entry_id": "e0", "target": "Open item"},
            {"entry_id": "e1", "target": "Feature gate"},
        ],
    }

    def predict(_agent, role, prompt, *_args, **_kwargs):
        captured.update(role=role, prompt=prompt)
        return json.dumps(response), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    elements = perception.inventory_scrollable_region(
        _frame(), {"role": "content", "element_names": []}, "r1")

    assert [(item.name, item.category, item.risk, item.interactive,
             item.action_label) for item in elements] == [
        ("Open item", "control", "none", True, "e0"),
        ("Feature gate", "control", "none", True, "e1"),
    ]
    assert captured["role"] == "semantic_region_inventory"
    assert "function_entries" in captured["prompt"]
    assert "已经是某项功能的具体操作界面" in captured["prompt"]
    assert "连续滚动视图" in captured["prompt"]
    assert "purpose" not in captured["prompt"]
    assert "expected_immediate_effect" not in captured["prompt"]


def test_region_long_inventory_sends_tall_map_as_one_multiview_call(monkeypatch):
    calls = []

    def predict(_agent, role, prompt, images, *_args, **_kwargs):
        calls.append((role, prompt, images))
        return json.dumps({
            "region_id": "r1", "function_entries": [],
        }), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    elements = perception.inventory_scrollable_region(
        _frame(width=200, height=700),
        {
            "role": "long_list",
            "element_names": ["First row"],
            "_viewport_height_px": 120,
        },
        "r1",
    )

    assert elements == []
    assert len(calls) == 1
    role, prompt, images = calls[0]
    assert role == "semantic_region_inventory"
    assert len(images) == 4
    assert all(image.shape[:2] == (240, 200) for image in images)
    assert "连续滚动视图" in prompt
    assert "function_entries" in prompt
    assert perception.last_region_long_inventory["view_sizes"] == [
        [200, 240], [200, 240], [200, 240], [200, 240],
    ]
    assert perception.last_region_long_inventory["batch_count"] == 1


def test_region_long_inventory_batches_extreme_map_and_deduplicates(monkeypatch):
    calls = []
    responses = [
        {"region_id": "r1", "function_entries": [
            {"entry_id": "e0", "target": "First"},
            {"entry_id": "e1", "target": "Overlap"},
        ]},
        {"region_id": "r1", "function_entries": [
            {"entry_id": "e0", "target": "Overlap"},
            {"entry_id": "e1", "target": "Last"},
        ]},
    ]

    def predict(_agent, role, prompt, images, *_args, **_kwargs):
        calls.append((role, prompt, images))
        return json.dumps(responses[len(calls) - 1]), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    elements = perception.inventory_scrollable_region(
        _frame(width=200, height=1600),
        {"role": "long_list", "_viewport_height_px": 120},
        "r1",
    )

    assert [element.name for element in elements] == [
        "First", "Overlap", "Last"]
    assert [element.group for element in elements] == ["", "", ""]
    assert [len(call[2]) for call in calls] == [4, 4]
    assert all(call[0] == "semantic_region_inventory" for call in calls)
    assert all("连续滚动视图" in call[1] for call in calls)
    assert all('"group"' not in call[1] for call in calls)
    assert perception.last_region_long_inventory["batch_count"] == 2


def test_region_long_inventory_fails_closed_when_one_batch_fails(monkeypatch):
    calls = 0

    def predict(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            return "not json", None, None
        return json.dumps({
            "region_id": "r1",
            "function_entries": [{
                "entry_id": "e0", "target": "Partial",
            }],
        }), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)

    assert perception.inventory_scrollable_region(
        _frame(width=200, height=1600),
        {"role": "long_list", "_viewport_height_px": 120},
        "r1",
    ) == []
    assert calls == 2
    assert perception.last_region_long_inventory == {
        "status": "invalid_response",
        "raw_response": "not json",
        "failed_batch": 2,
        "batch_count": 2,
    }


def test_fixture_region_long_inventory_reuses_full_surface_oracle(monkeypatch):
    monkeypatch.setattr(
        visual_cache, "predict_mm_role",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fixture long inventory must not call the model")))
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    calls = []

    def provider(*, full_surface=False):
        calls.append(full_surface)
        return {
            "page": "Chats", "surface_kind": "page",
            "surface_scrollable": True,
            "blocks": [{
                "role": "top_app_bar", "fixture_oracle": True,
                "bbox_1000": [0, 0, 1000, 100], "scrollable": False,
                "elements": [{
                    "name": "Search", "interactive": True,
                    "category": "navigation", "risk": "none",
                    "bbox_xywh": [360, 20, 36, 36],
                }],
            }, {
                "role": "conversation_list", "fixture_oracle": True,
                "bbox_1000": [0, 100, 1000, 900], "scrollable": True,
                "elements": [{
                    "name": "Open Alex", "interactive": True,
                    "category": "navigation", "risk": "none",
                    "bbox_xywh": [20, 1200, 360, 64],
                }],
            }],
        }

    perception.fixture_inventory_provider = provider
    perception.last_semantic_blocks = [{"role": "original"}]
    perception.last_page_name = "Original"
    elements = perception.inventory_scrollable_region(
        _frame(), {"role": "conversation_list"}, "r9")

    assert calls == [True]
    assert [element.name for element in elements] == ["Open Alex"]
    assert elements[0].region_id == "r9"
    assert elements[0].bbox_xywh == [20, 1200, 360, 64]
    assert elements[0].source == "fixture_full_surface_inventory"
    assert perception.last_semantic_blocks == [{"role": "original"}]
    assert perception.last_page_name == "Original"
    assert perception.last_region_long_inventory["method"] == (
        "fixture_oracle_full_surface")


def test_inventory_prompt_describes_frontmost_triggerable_controls():
    from gui_rewalk.src.core.visual_traversal.prompts.block_inventory import (
        PAGE_MAP_PROMPT,
    )
    from gui_rewalk.src.core.visual_traversal.prompts.grounding import (
        SEMANTIC_INVENTORY_PROMPT,
    )

    lowered = SEMANTIC_INVENTORY_PROMPT.casefold()
    normalized = " ".join(lowered.split())
    assert "frontmost" in lowered
    assert "frontmost interactive situation" in normalized
    assert "whose own action can be triggered by the user's next click" in normalized
    assert "use one interaction level" in normalized
    assert "when children trigger different results" in normalized
    assert "name a control by its stable function" in normalized
    assert "context_labels" in normalized
    assert '"areas"' in normalized
    assert '"controls"' in normalized
    assert '"group"' not in normalized

    page_map = " ".join(PAGE_MAP_PROMPT.casefold().split())
    assert "当前唯一的 active interaction surface" in page_map
    assert "inactive background 不允许出现在 regions 中" in page_map
    assert "region 是功能容器，不是单个操作目标" in page_map


def test_explorer_freely_selects_from_current_function_entries():
    from gui_rewalk.src.core.visual_traversal.prompts.exploration import (
        build_explorer_prompt,
    )

    prompt = build_explorer_prompt({
        "function_entries": [
            {"entry_id": "e0", "target": "Keyboard Shortcuts"},
            {"entry_id": "e1", "target": "Help"},
        ],
    }, platform="android")

    assert "自由选择任意一个入口" in prompt
    assert "选择列表中的第一个入口" not in prompt
    assert "框架会在你提出选择后独立完成" in prompt
    assert "selected_entry_id" in prompt
    assert "covered" not in prompt


def test_semantic_capabilities_reference_only_canonical_element_ids():
    from gui_rewalk.src.core.visual_traversal.capability_discovery import (
        discover_capabilities,
    )

    canonical = [
        VisualElement(
            7, "Browse documents", [0, 0, 0, 0], [0, 0],
            el_type="button", category="navigation", region="content",
            region_id="r1",
            geometry_status="semantic_only"),
        VisualElement(
            8, "View recent activity", [0, 0, 0, 0], [0, 0],
            el_type="link", category="navigation", region="content",
            region_id="r1",
            geometry_status="semantic_only"),
    ]
    capabilities = discover_capabilities(
        page_id="home", variant_id="default", state_id="home-state",
        elements=canonical)
    refs = {
        source["element_label"]: source["element_id"]
        for capability in capabilities
        for source in capability["source_elements"]
    }
    assert refs == {
        "Browse documents": "7",
        "View recent activity": "8",
    }
    assert {capability["semantic_key"] for capability in capabilities} == {
        "open browse documents", "open view recent activity",
    }


def test_single_target_grounding_converts_normalized_1000_to_pixels(monkeypatch):
    replies = iter([
        {"found": True, "coordinate_space": "normalized_1000",
         "bbox_1000": [19, 850, 177, 950],
         "click_point_1000": [98, 900], "reason": "Alarm tab"},
        {"found": True, "coordinate_space": "normalized_1000",
         "bbox_1000": [20, 800, 180, 940],
         "click_point_1000": [100, 880], "reason": "corrected"},
    ])
    prompts = []
    def predict(_agent, _role, prompt, *_args, **_kwargs):
        prompts.append(prompt)
        return json.dumps(next(replies)), None, None
    monkeypatch.setattr(
        visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    target = VisualElement(
        1, "Clock", [0, 0, 0, 0], [0, 0], el_type="tab",
        category="navigation", region="primary_navigation",
        region_id="semantic:primary_navigation:x", geometry_status="semantic_only",
        action_label="Open clock")
    grounded = perception.ground_target(_frame(720, 1280), target)
    assert grounded is not None
    assert grounded.bbox_xywh == [14, 1088, 113, 128]
    assert grounded.center == [71, 1152]
    assert grounded.geometry_status == "live_target"
    assert grounded.action_label == "Open clock"
    assert '"action_label": "Open clock"' in prompts[0]
    assert target.bbox_xywh == [0, 0, 0, 0]
    assert perception.last_target_grounding["bbox_1000"] == [19, 850, 177, 950]
    assert perception.last_target_grounding["bbox_px_xyxy"] == [14, 1088, 127, 1216]
    assert perception.ground_target(
        _frame(720, 1280), target, force_refresh=True,
        correction_hint="candidate was above the bottom navigation") is not None
    assert "candidate was above the bottom navigation" in prompts[1]


def test_single_target_grounding_uses_complete_frame_coordinates(monkeypatch):
    captured = {}

    def predict(_agent, _role, prompt, images, *_args, **_kwargs):
        captured.update(prompt=prompt, shape=images[0].shape)
        return json.dumps({
            "found": True,
            "coordinate_space": "normalized_1000",
            "bbox_1000": [100, 200, 300, 400],
            "click_point_1000": [200, 300],
            "reason": "target inside Region",
        }), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    perception.last_semantic_blocks = [{
        "region_id": "region:header",
        "element_names": ["Cancel", "Add"],
        "bbox_1000": [250, 250, 750, 750],
    }]
    target = VisualElement(
        1, "Cancel", [0, 0, 0, 0], [0, 0], el_type="button",
        category="control", region="Dialog Header",
        region_id="region:header", geometry_status="semantic_only")

    grounded = perception.ground_target(_frame(200, 120), target)

    assert grounded is not None
    assert captured["shape"] == (120, 200, 3)
    assert '"region_bbox_1000": [250, 250, 750, 750]' in captured["prompt"]
    assert "approximate visual search hint" in captured["prompt"]
    assert grounded.bbox_xywh == [20, 24, 40, 24]
    assert grounded.center == [40, 36]
    assert perception.last_target_grounding["grounding_crop_px_xyxy"] is None
    assert perception.last_target_grounding["bbox_px_xyxy"] == [
        20, 24, 60, 48,
    ]


def test_single_target_grounding_accepts_target_outside_approximate_region(
        monkeypatch):
    calls = []
    response = {
        "found": True,
        "coordinate_space": "normalized_1000",
        "bbox_1000": [100, 20, 300, 100],
        "click_point_1000": [200, 50],
        "reason": "matching target crosses the Region estimate",
    }

    def predict(_agent, _role, prompt, images, *_args, **_kwargs):
        calls.append((prompt, images[0].shape))
        return json.dumps(response), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    perception.last_semantic_blocks = [{
        "region_id": "region:header",
        "element_names": ["Cancel", "Add"],
        "bbox_1000": [250, 250, 750, 750],
    }]
    target = VisualElement(
        1, "Cancel", [0, 0, 0, 0], [0, 0], el_type="button",
        category="control", region="Dialog Header",
        region_id="region:header", geometry_status="semantic_only")

    grounded = perception.ground_target(_frame(200, 120), target)

    assert grounded is not None
    assert [shape for _prompt, shape in calls] == [(120, 200, 3)]
    assert "approximate visual search hint" in calls[0][0]
    assert grounded.center == [40, 6]


def test_single_target_grounding_correction_rechecks_complete_frame(monkeypatch):
    captured = {}

    def predict(_agent, _role, prompt, images, *_args, **_kwargs):
        captured.update(prompt=prompt, shape=images[0].shape)
        return json.dumps({
            "found": True,
            "coordinate_space": "normalized_1000",
            "bbox_1000": [500, 200, 600, 300],
            "click_point_1000": [550, 250],
            "reason": "corrected on the complete frame",
        }), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    perception.last_semantic_blocks = [{
        "region_id": "region:header",
        "element_names": ["Search", "Menu"],
        "bbox_1000": [250, 250, 750, 750],
    }]
    target = VisualElement(
        1, "Search", [0, 0, 0, 0], [0, 0], el_type="button",
        category="navigation", region="Header",
        region_id="region:header", geometry_status="semantic_only")

    grounded = perception.ground_target(
        _frame(200, 120), target, force_refresh=True,
        correction_hint="coordinate_out_of_range at x=1042")

    assert grounded is not None
    assert captured["shape"] == (120, 200, 3)
    assert '"region_bbox_1000": [250, 250, 750, 750]' in captured["prompt"]
    assert "coordinate_out_of_range at x=1042" in captured["prompt"]
    assert perception.last_target_grounding["grounding_crop_px_xyxy"] is None


@pytest.mark.parametrize("response, status", [
    ({"found": True, "bbox_px": [14, 1088, 127, 1216],
      "click_point_px": [71, 1152]}, "invalid_coordinate_space"),
    ({"found": True, "coordinate_space": "pixels",
      "bbox_1000": [19, 850, 177, 950], "click_point_1000": [98, 900]},
     "invalid_coordinate_space"),
    ({"found": True, "coordinate_space": "normalized_1000",
       "bbox_1000": [19, 850, 1001, 950], "click_point_1000": [98, 900]},
     "coordinate_out_of_range"),
])
def test_target_grounding_rejects_wrong_coordinate_contract(
        monkeypatch, response, status):
    monkeypatch.setattr(
        visual_cache, "predict_mm_role",
        lambda *args, **kwargs: (json.dumps(response), None, None))
    perception = VisualPerception(None, agent=object(), use_ocr=False)
    target = VisualElement(
        1, "Alarm", [0, 0, 0, 0], [0, 0], el_type="tab",
        category="navigation", region="primary_navigation",
        geometry_status="semantic_only")
    assert perception.ground_target(_frame(720, 1280), target) is None
    assert perception.last_target_grounding["status"] == status


class _SemanticPerception:
    use_semantic_inventory = True

    def __init__(self):
        self.calls = []
        self.last_target_grounding = {}

    def ground_target(self, shot, target, force_refresh=False, correction_hint=""):
        self.calls.append((force_refresh, correction_hint))
        self.last_target_grounding = {
            "status": "matched", "coordinate_space": "normalized_1000",
            "bbox_1000": [50, 167, 250, 333],
            "click_point_1000": [150, 250], "image_size": [200, 120],
            "bbox_px_xyxy": [10, 20, 50, 40],
            "click_point_px": [30, 30],
            "raw_response": "normalized grounding response",
        }
        return VisualElement(
            target.id, target.name, [10, 20, 40, 20], [30, 30],
            el_type=target.el_type, category=target.category,
            geometry_status="live_target")


class _CorrectingSemanticPerception(_SemanticPerception):
    def __init__(self, first_diagnostic):
        super().__init__()
        self.first_diagnostic = first_diagnostic

    def ground_target(self, shot, target, force_refresh=False, correction_hint=""):
        if not self.calls:
            self.calls.append((force_refresh, correction_hint))
            self.last_target_grounding = dict(self.first_diagnostic)
            return None
        return super().ground_target(
            shot, target, force_refresh=force_refresh,
            correction_hint=correction_hint)


class _Reviewer:
    def __init__(self, verdicts):
        self.verdicts = iter(verdicts)
        self.targets = []

    def review_target(self, shot, target, stored):
        self.targets.append((target, stored.name, stored.region))
        return next(self.verdicts)


def test_live_semantic_target_requires_reviewer_acceptance():
    perception = _SemanticPerception()
    reviewer = _Reviewer([{
        "accepted": True, "reason": "marked point is on Clock"}])

    env = SimpleNamespace(_get_obs=lambda: {"screenshot": _frame()})
    resolver = LiveTargeting(
        env=env, perception=perception, reviewer=reviewer,
        normalize_name=lambda value: value.casefold(),
        name_matches=lambda left, right: left == right)
    stored = VisualElement(
        2, "Clock", [0, 0, 0, 0], [0, 0], el_type="tab",
        category="navigation", region="primary_navigation",
        geometry_status="semantic_only")
    assert resolver.live_center_for(stored, {}) == [30, 30]
    assert perception.calls == [(False, "")]
    assert len(reviewer.targets) == 1
    assert stored.bbox_xywh == [0, 0, 0, 0]
    assert resolver.last_observation["status"] == "matched"
    assert resolver.last_observation["review"]["status"] == \
        "target_review_accepted"
    assert resolver.last_observation["diagnostic"]["local_validation"][
        "status"] == "locator_schema_validated"


@pytest.mark.parametrize("diagnostic", [
    {
        "status": "coordinate_out_of_range",
        "reason": "coordinate outside normalized_1000 range 0..1000",
        "bbox_1000": [1021, 188, 1064, 290],
        "click_point_1000": [1042, 239],
    },
    {
        "status": "invalid_coordinate_space",
        "reason": "coordinate_space must be normalized_1000",
    },
    {
        "status": "invalid_geometry",
        "reason": "click_point_1000 must be inside bbox_1000",
        "bbox_1000": [700, 100, 800, 200],
        "click_point_1000": [900, 150],
    },
    {
        "status": "target_not_found",
        "reason": "requested control was not confirmed",
    },
])
def test_live_semantic_target_feedback_retries_grounder_before_reviewer(
        diagnostic):
    perception = _CorrectingSemanticPerception(diagnostic)
    reviewer = _Reviewer([{
        "accepted": True, "reason": "corrected point is on Search"}])
    resolver = LiveTargeting(
        env=SimpleNamespace(_get_obs=lambda: {"screenshot": _frame()}),
        perception=perception, reviewer=reviewer,
        normalize_name=lambda value: value.casefold(),
        name_matches=lambda left, right: left == right)
    stored = VisualElement(
        2, "Search", [0, 0, 0, 0], [0, 0], el_type="button",
        category="navigation", region="header",
        geometry_status="semantic_only")

    assert resolver.live_center_for(stored, {}) == [30, 30]
    assert perception.calls[0] == (False, "")
    assert perception.calls[1][0] is True
    assert diagnostic["status"] in perception.calls[1][1]
    assert diagnostic["reason"] in perception.calls[1][1]
    assert len(reviewer.targets) == 1
    if diagnostic["status"] == "coordinate_out_of_range":
        assert "bbox_1000=[1021, 188, 1064, 290]" in perception.calls[1][1]
        assert "click_point_1000=[1042, 239]" in perception.calls[1][1]
        assert "within 0..1000" in perception.calls[1][1]


def test_live_semantic_target_retries_once_after_reviewer_rejection():
    perception = _SemanticPerception()
    reviewer = _Reviewer([
        {"accepted": False, "reason": "marked point is on Weather"},
        {"accepted": True, "reason": "corrected point is on Keyboard Shortcuts"},
    ])
    resolver = LiveTargeting(
        env=SimpleNamespace(_get_obs=lambda: {"screenshot": _frame()}),
        perception=perception, reviewer=reviewer,
        normalize_name=lambda value: value.casefold(),
        name_matches=lambda left, right: left == right)
    stored = VisualElement(
        2, "Keyboard Shortcuts", [0, 0, 0, 0], [0, 0],
        el_type="button", category="navigation", region="menu",
        geometry_status="semantic_only")

    assert resolver.live_center_for(stored, {}) == [30, 30]
    assert perception.calls == [
        (False, ""),
        (True, "marked point is on Weather"),
    ]
    assert len(reviewer.targets) == 2
    assert resolver.last_observation["review"]["status"] == \
        "target_review_accepted"


def test_live_semantic_target_stops_after_two_reviewer_rejections():
    perception = _SemanticPerception()
    reviewer = _Reviewer([
        {"accepted": False, "reason": "marked point is on Weather"},
        {"accepted": False, "reason": "marked point is still not on target"},
    ])
    resolver = LiveTargeting(
        env=SimpleNamespace(_get_obs=lambda: {"screenshot": _frame()}),
        perception=perception, reviewer=reviewer,
        normalize_name=lambda value: value.casefold(),
        name_matches=lambda left, right: left == right)
    stored = VisualElement(
        2, "Keyboard Shortcuts", [0, 0, 0, 0], [0, 0],
        el_type="button", category="navigation", region="menu",
        geometry_status="semantic_only")

    assert resolver.live_center_for(stored, {}) is None
    assert perception.calls == [
        (False, ""),
        (True, "marked point is on Weather"),
    ]
    assert resolver.last_observation["status"] == "target_review_rejected"


def test_live_semantic_target_fails_closed_when_reviewer_unavailable():
    perception = _SemanticPerception()
    resolver = LiveTargeting(
        env=SimpleNamespace(_get_obs=lambda: {"screenshot": _frame()}),
        perception=perception, reviewer=None,
        normalize_name=lambda value: value.casefold(),
        name_matches=lambda left, right: left == right)
    stored = VisualElement(
        2, "Clock", [0, 0, 0, 0], [0, 0], el_type="tab",
        category="navigation", region="primary_navigation",
        geometry_status="semantic_only")

    assert resolver.live_center_for(stored, {}) is None
    assert perception.calls == [(False, "")]
    assert resolver.last_observation["status"] == "review_unavailable"


def test_live_semantic_target_does_not_reject_approximate_region_mismatch():
    perception = _SemanticPerception()
    reviewer = _Reviewer([{
        "accepted": True, "reason": "marked point is on Add"}])
    resolver = LiveTargeting(
        env=SimpleNamespace(_get_obs=lambda: {"screenshot": _frame()}),
        perception=perception, reviewer=reviewer,
        normalize_name=lambda value: value.casefold(),
        name_matches=lambda left, right: left == right)
    stored = VisualElement(
        2, "Add", [0, 0, 0, 0], [0, 0], el_type="button",
        category="control", region="Dialog Header",
        geometry_status="semantic_only")
    stored.region_bbox = [0, 0, 20, 20]

    assert resolver.live_center_for(stored, {}) == [30, 30]
    assert stored.region_bbox == [0, 0, 20, 20]
    assert resolver.last_observation["status"] == "matched"
    assert len(reviewer.targets) == 1


def test_live_semantic_target_cannot_escape_active_surface():
    perception = _SemanticPerception()
    resolver = LiveTargeting(
        env=SimpleNamespace(_get_obs=lambda: {"screenshot": _frame()}),
        perception=perception, reviewer=None,
        normalize_name=lambda value: value.casefold(),
        name_matches=lambda left, right: left == right)
    stored = VisualElement(
        2, "Add", [0, 0, 0, 0], [0, 0], el_type="button",
        category="control", region="Dialog Header",
        geometry_status="semantic_only", surface_kind="dialog",
        surface_bbox_xywh=[0, 0, 20, 20])
    stored.region_bbox = [0, 0, 20, 35]

    assert resolver.live_center_for(stored, {}) is None
    assert perception.calls[0] == (False, "")
    assert perception.calls[1][0] is True
    assert "surface_mismatch" in perception.calls[1][1]
    assert "frontmost dialog surface" in perception.calls[1][1]
    assert stored.region_bbox == [0, 0, 20, 35]
    assert resolver.last_observation["status"] == "surface_mismatch"


def test_live_semantic_target_forwards_executed_no_effect_correction():
    perception = _SemanticPerception()
    reviewer = _Reviewer([{
        "accepted": True, "reason": "marked point is on Mode"}])
    resolver = LiveTargeting(
        env=SimpleNamespace(_get_obs=lambda: {"screenshot": _frame()}),
        perception=perception, reviewer=reviewer,
        normalize_name=lambda value: value.casefold(),
        name_matches=lambda left, right: left == right)
    stored = VisualElement(
        2, "Mode", [0, 0, 0, 0], [0, 0], el_type="target",
        category="shallow", region="choices",
        geometry_status="semantic_only")
    correction = (
        "The previous executed point had no effect; choose a different "
        "directly operable part.")

    assert resolver.live_center_for(
        stored, {}, correction_hint=correction) == [30, 30]
    assert perception.calls == [(False, correction)]


def test_live_semantic_target_does_not_reclassify_inventory_during_grounding():
    perception = _SemanticPerception()
    reviewer = _Reviewer([{
        "accepted": True, "reason": "marked point is on Cloud sync"}])

    resolver = LiveTargeting(
        env=SimpleNamespace(_get_obs=lambda: {"screenshot": _frame()}),
        perception=perception, reviewer=reviewer,
        normalize_name=lambda value: value.casefold(),
        name_matches=lambda left, right: left == right)
    stored = VisualElement(
        2, "Cloud sync", [0, 0, 0, 0], [0, 0], el_type="button",
        category="navigation", region="content", geometry_status="semantic_only",
        action_label="Sign in", enabled=True, requires_permission=False,
        blocked_reason="")
    assert resolver.live_center_for(stored, {}) == [30, 30]
    assert perception.calls == [(False, "")]
    assert len(reviewer.targets) == 1
    assert stored.enabled is True
    assert stored.requires_permission is False
    assert stored.blocked_reason == ""
    assert resolver.last_observation["status"] == "matched"


def test_semantic_grounding_attempt_artifacts_record_reviewer_acceptance(tmp_path):
    stored = VisualElement(
        2, "Clock", [0, 0, 0, 0], [0, 0], el_type="tab",
        category="navigation", region="primary_navigation",
        region_id="semantic:primary_navigation:clock",
        geometry_status="semantic_only")
    writer = ArtifactWriter(str(tmp_path / "run"))

    first = LiveTargeting(
        env=SimpleNamespace(_get_obs=lambda: {"screenshot": _frame()}),
        perception=_SemanticPerception(),
        reviewer=_Reviewer([{
            "accepted": True, "reason": "marked point is on Clock"}]),
        normalize_name=lambda value: value.casefold(),
        name_matches=lambda left, right: left == right,
        semantic_attempt_sink=writer.save_target_grounding_attempt)
    assert first.live_center_for(stored, {}) == [30, 30]

    retry = LiveTargeting(
        env=SimpleNamespace(_get_obs=lambda: {"screenshot": _frame()}),
        perception=_SemanticPerception(),
        reviewer=_Reviewer([{
            "accepted": True, "reason": "marked point is on Clock"}]),
        normalize_name=lambda value: value.casefold(),
        name_matches=lambda left, right: left == right,
        semantic_attempt_sink=writer.save_target_grounding_attempt)
    assert retry.live_center_for(stored, {}) == [30, 30]

    attempt_root = tmp_path / "run" / "target_grounding_attempts"
    attempts = sorted(path for path in attempt_root.iterdir() if path.is_dir())
    assert [path.name[:6] for path in attempts] == ["000001", "000002"]
    payloads = [json.loads((path / "result.json").read_text("utf-8"))
                for path in attempts]
    assert [payload["outcome"] for payload in payloads] == [
        "accepted", "accepted"]
    assert [payload["target_attempt"] for payload in payloads] == [1, 1]
    assert all(payload["reviewer"]["status"] == "target_review_accepted"
               for payload in payloads)
    for path, payload in zip(attempts, payloads):
        assert (path / "input.png").read_bytes() == _frame()
        assert (path / "overlay.png").is_file()
        assert payload["target"]["region_id"] == stored.region_id
        assert payload["diagnostic"]["bbox_1000"] == [50, 167, 250, 333]
        assert payload["diagnostic"]["bbox_px_xyxy"] == [10, 20, 50, 40]
        assert payload["diagnostic"]["image_size"] == [200, 120]
        assert payload["diagnostic"]["local_validation"]["status"] == \
            "locator_schema_validated"
        assert payload["grounded_geometry"]["click_point_px"] == [30, 30]
        overlay = Image.open(path / "overlay.png").convert("RGB")
        assert overlay.getpixel((10, 20))[0] > 200
        assert max(overlay.getpixel((30, 30))) < 40


def test_target_reviewer_uses_clean_click_centered_crop(monkeypatch):
    captured = {}

    def predict(_agent, _role, prompt, images, *_args, **_kwargs):
        captured["prompt"] = prompt
        captured["images"] = [
            Image.fromarray(image).convert("RGB") for image in images]
        return json.dumps({
            "accepted": True, "reason": "click point triggers target",
        }), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    stored = VisualElement(
        2, "Clock", [0, 0, 0, 0], [0, 0], el_type="tab",
        category="navigation", region="primary_navigation",
        action_label="Open clock")
    grounded = VisualElement(
        2, "Clock", [10, 20, 40, 20], [30, 30], el_type="tab",
        category="navigation", geometry_status="live_target")
    frame = Image.new("RGB", (200, 120), "white")
    frame.putpixel((30, 30), (12, 34, 56))
    stream = io.BytesIO()
    frame.save(stream, "PNG")
    review = AnnotationReviewer(object()).review_target(
        stream.getvalue(), grounded, stored)
    assert review["accepted"] is True
    assert len(captured["images"]) == 2
    original, click_crop = captured["images"]
    assert original.getpixel((10, 20)) == (255, 255, 255)
    assert original.getpixel((30, 30)) == (12, 34, 56)
    assert click_crop.size == (201, 201)
    assert click_crop.getpixel((100, 100)) == (12, 34, 56)
    assert click_crop.getpixel((80, 90)) == (255, 255, 255)
    assert click_crop.getpixel((0, 0)) == (127, 127, 127)
    prompt_text = " ".join(captured["prompt"].split())
    assert "IMAGE 1 is the untouched current complete GUI frame" in prompt_text
    assert "IMAGE 2 is a clean, unannotated crop" in prompt_text
    assert "exact center pixel" in prompt_text
    assert "contains no framework marks or overlays" in prompt_text
    assert "Open clock" not in prompt_text
    assert "Target category/type" not in prompt_text
    assert "Prior inventory availability" not in prompt_text


def test_target_reviewer_rejects_click_point_outside_frame(monkeypatch):
    monkeypatch.setattr(
        visual_cache, "predict_mm_role",
        lambda *_args, **_kwargs: pytest.fail("reviewer must not see invalid point"))
    stored = VisualElement(
        2, "Clock", [0, 0, 0, 0], [0, 0], el_type="tab",
        category="navigation")
    grounded = VisualElement(
        2, "Clock", [190, 110, 20, 20], [210, 130], el_type="tab",
        category="navigation", geometry_status="live_target")

    review = AnnotationReviewer(object()).review_target(_frame(), grounded, stored)

    assert review == {
        "accepted": False, "reason": "click_point_out_of_frame"}


def test_target_reviewer_ignores_out_of_contract_availability_fields(monkeypatch):
    def predict(*_args, **_kwargs):
        return json.dumps({
            "accepted": True, "enabled": True,
            "requires_permission": True,
            "blocked_reason": "authentication required to enable sync",
            "reason": "click point triggers target",
        }), None, None

    monkeypatch.setattr(visual_cache, "predict_mm_role", predict)
    stored = VisualElement(
        2, "Cloud sync", [0, 0, 0, 0], [0, 0], el_type="button",
        category="dangerous", region="content", action_label="Sign in")
    grounded = VisualElement(
        2, "Cloud sync", [10, 20, 40, 20], [30, 30], el_type="button",
        category="dangerous", geometry_status="live_target")
    review = AnnotationReviewer(object()).review_target(_frame(), grounded, stored)
    assert review["accepted"] is True
    assert set(review) == {"accepted", "reason", "raw_response"}


def test_attempt_artifact_failure_does_not_change_reviewed_click():
    def fail_sink(**_kwargs):
        raise OSError("disk unavailable")

    resolver = LiveTargeting(
        env=SimpleNamespace(_get_obs=lambda: {"screenshot": _frame()}),
        perception=_SemanticPerception(),
        reviewer=_Reviewer([{
            "accepted": True, "reason": "marked point is on Clock"}]),
        normalize_name=lambda value: value.casefold(),
        name_matches=lambda left, right: left == right,
        semantic_attempt_sink=fail_sink)
    stored = VisualElement(
        2, "Clock", [0, 0, 0, 0], [0, 0], el_type="tab",
        category="navigation", region="primary_navigation",
        geometry_status="semantic_only")
    assert resolver.live_center_for(stored, {}) == [30, 30]
    assert resolver.last_observation["status"] == "matched"


def test_registration_flag_dispatches_before_legacy_detection(monkeypatch):
    from gui_rewalk.src.core.visual_traversal.state import registration

    host = SimpleNamespace(
        perception=SimpleNamespace(
            use_semantic_inventory=True,
            semantic_inventory=lambda *_args, **_kwargs: [object()],
            last_page_name="Page", last_surface_kind="page",
            last_semantic_blocks=[]),
        _map_guided_inherited=None,
    )
    called = []
    monkeypatch.setattr(
        registration, "_register_semantic_observation",
        lambda self, obs, path, replay_hints=None, arrival_elements=None:
        called.append(True) or ("s", True))
    assert registration.register_observation(host, {"screenshot": b"x"}, []) == ("s", True)
    assert called == [True]


def test_semantic_scroll_retry_persists_long_inventory_on_stable_regions():
    from gui_rewalk.src.core.visual_traversal.state.registration import (
        retry_semantic_scroll_audit,
    )

    live = VisualElement(
        7, "Current action", [0, 0, 0, 0], [0, 0],
        category="navigation", region_id="b0")
    durable = VisualElement(
        3, "Durable action", [0, 0, 0, 0], [0, 0],
        category="navigation", region_id="r7")
    below_fold = VisualElement(
        8, "Below-fold action", [0, 0, 0, 0], [0, 0],
        category="navigation", region_id="r7")
    fixed = VisualElement(
        4, "Network summary", [0, 0, 0, 0], [0, 0],
        category="shallow", region_id="r8")
    original_blocks = [{
        "local_id": "b0", "bbox_1000": [0, 0, 1000, 1000],
        "scrollable": True, "element_ids": [7],
    }]
    calls = []
    saved_maps = []
    saved_observations = []
    saved_buttons = []
    capability_batches = []

    class NativeGraph(dict):
        @property
        def nodes(self):
            return self

    graph_nodes = NativeGraph({"state": {}})
    perception = SimpleNamespace(
        use_semantic_inventory=True,
        last_semantic_blocks=original_blocks,
    )
    host = SimpleNamespace(
        env=SimpleNamespace(step=lambda action, pause=0: {
            "screenshot": _frame()}),
        perception=perception,
        _scroll_aggregate_enabled=True,
        _last_live_observation_elements=[live],
        _state_data={"state": {
            "durable": "unchanged",
            "semantic_blocks": [{
                "region_id": "r7", "scrollable": True,
                "viewport_bbox_1000": [0, 0, 1000, 1000],
                "observation_status": "complete",
            }, {
                "region_id": "r8", "scrollable": False,
                "viewport_bbox_1000": [500, 0, 1000, 1000],
                "observation_status": "complete",
                "element_ids": [4],
                "element_names": ["Network summary"],
            }],
            "elements": [durable, fixed],
            "page_name": "Settings list",
            "page_id": "page",
            "variant_id": "variant",
        }},
        writer=SimpleNamespace(
            save_region_image=lambda state, region, payload:
            saved_maps.append((state, region, payload)),
            update_node_observation=lambda state, **kwargs:
            saved_observations.append((state, kwargs))),
        registry=SimpleNamespace(
            set_buttons=lambda state, elements:
            saved_buttons.append((state, list(elements))),
            record_page_variant=lambda *_args, **_kwargs: ("page", "variant"),
            variant_facts_of=lambda _state: {
                "functions": ["Durable action", "Below-fold action"]}),
        graph=SimpleNamespace(
            graph=graph_nodes,
            scroll_ledger={
                "region:r7": {
                    "region_id": "r7", "complete": False,
                },
                "region:r8": {
                    "region_id": "r8", "complete": True,
                },
            },
            register_capability_candidates=lambda state, capabilities:
            capability_batches.append((state, capabilities)) or [
                item["capability_id"] for item in capabilities]),
        region_registry=SimpleNamespace(
            record_mapped_elements=lambda *_args, **_kwargs: None),
        app_name="test_app",
        _scroll_node_local_functions=["prior"],
    )

    def scroll(obs, elements, state_id=""):
        calls.append((obs, elements, state_id))
        assert perception.last_semantic_blocks[0]["region_id"] == "r7"
        assert [element.name for element in elements] == ["Durable action"]
        assert set(host._semantic_scroll_seed_region_crops) == {"r7"}
        assert host._semantic_scroll_seed_region_bboxes == {
            "r7": [0, 0, 1000, 1000]}
        host._state_data[state_id]["_semantic_scroll_blocks"] = [{
            "region_id": "r7", "scrollable": True,
            "viewport_bbox_1000": [0, 0, 1000, 1000],
        }]
        host._state_data[state_id]["_semantic_scroll_region_crops"] = {
            "r7": b"temporary"}
        return [*elements, below_fold]

    host._scroll_aggregate = scroll
    obs = {"screenshot": _frame()}

    assert retry_semantic_scroll_audit(host, obs, "state") is True
    assert len(calls) == 1
    assert perception.last_semantic_blocks is original_blocks
    assert host._scroll_node_local_functions == ["prior"]
    assert host._state_data["state"]["durable"] == "unchanged"
    assert host._state_data["state"]["semantic_blocks"] == [{
        "region_id": "r7", "scrollable": True,
        "viewport_bbox_1000": [0, 0, 1000, 1000],
        "element_ids": [0, 1],
        "element_names": ["Durable action", "Below-fold action"],
        "observation_status": "complete",
    }, {
        "region_id": "r8", "scrollable": False,
        "viewport_bbox_1000": [500, 0, 1000, 1000],
        "observation_status": "complete",
        "element_ids": [2],
        "element_names": ["Network summary"],
    }]
    assert [element.name for element in host._state_data["state"]["elements"]] == [
        "Durable action", "Below-fold action", "Network summary"]
    assert [element.id for element in host._state_data["state"]["elements"]] == [
        0, 1, 2]
    assert "_semantic_scroll_blocks" not in host._state_data["state"]
    assert "_semantic_scroll_region_crops" not in host._state_data["state"]
    assert saved_maps == [("state", "r7", b"temporary")]
    assert [element.name for element in saved_buttons[0][1]] == [
        "Durable action", "Below-fold action", "Network summary"]
    assert saved_observations[0][0] == "state"
    assert len(saved_observations[0][1]["elements"]) == 3
    assert len(capability_batches) == 1
    assert [row["name"] for row in graph_nodes["state"]["elements"]] == [
        "Durable action", "Below-fold action", "Network summary"]
    assert not hasattr(host, "_semantic_scroll_seed_region_crops")
    assert not hasattr(host, "_semantic_scroll_force_top")


def test_known_state_reconciles_alias_without_growing_durable_targets():
    from gui_rewalk.src.core.visual_traversal.state.registration import (
        _reconcile_known_state_live_targets,
    )

    historical = [
        VisualElement(
            0, "Existing function", [0, 0, 0, 0], [0, 0],
            category="navigation", group="stable", region="content",
            region_id="r1"),
        VisualElement(
            1, "Old terminal value", [0, 0, 0, 0], [0, 0],
            category="shallow", region="content", region_id="r1"),
    ]
    historical[0].exploration_status = "complete"
    historical[1].exploration_status = "terminal"
    live = [
        VisualElement(
            0, "Equivalent wording", [0, 0, 0, 0], [0, 0],
            category="navigation", region_id="b0"),
        VisualElement(
            1, "Genuinely new function", [0, 0, 0, 0], [0, 0],
            category="shallow", region_id="b0"),
    ]

    class Perception:
        def reconcile_semantic_targets(self, old, current):
            assert [element.name for element in old] == ["Existing function"]
            assert [element.name for element in current] == [
                "Equivalent wording", "Genuinely new function"]
            return {"0": "0"}

    live_blocks = [{
        "scope": "target_app", "interaction": "direct",
        "element_ids": [0, 1],
    }]
    reconciled = _reconcile_known_state_live_targets(
        historical, live, live_blocks, Perception())

    assert reconciled == [{
        "live_name": "Equivalent wording",
        "historical_name": "Existing function",
        "historical_id": "0",
    }]
    assert live[0].name == "Existing function"
    assert live[0].group == "stable"
    assert live[1].name == "Genuinely new function"
    assert [element.name for element in historical] == [
        "Existing function", "Old terminal value"]


def test_known_state_reconciles_alias_across_changed_block_partition():
    from gui_rewalk.src.core.visual_traversal.state.registration import (
        _reconcile_known_state_live_targets,
    )

    historical = [
        VisualElement(
            0, "Create item", [0, 0, 0, 0], [0, 0],
            category="navigation", region_id="r1"),
        VisualElement(
            1, "Next section", [0, 0, 0, 0], [0, 0],
            category="navigation", region_id="r2"),
    ]
    historical[1].exploration_status = "covered"
    live = [
        VisualElement(
            7, "Add new item", [0, 0, 0, 0], [0, 0],
            category="navigation", region_id="b2"),
        VisualElement(
            8, "Next section", [0, 0, 0, 0], [0, 0],
            category="navigation", region_id="b3"),
    ]

    class Perception:
        def reconcile_semantic_targets(self, old, current):
            assert [element.name for element in old] == [
                "Create item", "Next section"]
            assert [element.name for element in current] == ["Add new item"]
            return {"7": "0"}

    reconciled = _reconcile_known_state_live_targets(
        historical,
        live,
        [
            {"scope": "target_app", "interaction": "direct",
             "element_ids": [7]},
            {"scope": "target_app", "interaction": "direct",
             "element_ids": [8]},
        ],
        Perception(),
    )

    assert reconciled == [{
        "live_name": "Add new item",
        "historical_name": "Create item",
        "historical_id": "0",
    }]
    assert live[0].name == "Create item"


def test_registration_refreshes_passive_feedback_before_identity(monkeypatch):
    from gui_rewalk.src.core.visual_traversal.state import registration

    calls = []

    class Perception:
        use_semantic_inventory = True
        last_page_name = "Alarm"
        last_surface_kind = "page"
        last_passive_feedback_present = False

        def semantic_inventory(self, shot, *, navigation_context="",
                               force_refresh=False):
            calls.append((shot, force_refresh))
            self.last_passive_feedback_present = shot == b"feedback"
            return [shot]

    captured = {}
    perception = Perception()
    host = SimpleNamespace(
        perception=perception,
        env=SimpleNamespace(
            _get_obs=lambda: {"screenshot": b"unobscured"}),
        _settle_enabled=False,
        _state_data={},
        _map_guided_inherited=None,
        review_debug=SimpleNamespace(record_event=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(registration.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(
        registration, "_try_map_guided",
        lambda *_args, **_kwargs: (None, None, None))
    monkeypatch.setattr(
        registration, "_register_semantic_observation",
        lambda self, obs, path, replay_hints=None, arrival_elements=None:
        captured.update(obs=obs, elements=arrival_elements) or ("s", True))

    assert registration.register_observation(
        host, {"screenshot": b"feedback"}, []) == ("s", True)
    assert calls == [(b"feedback", False), (b"unobscured", True)]
    assert captured["obs"]["screenshot"] == b"unobscured"
    assert captured["elements"] == [b"unobscured"]


def test_registration_ignores_persistent_passive_feedback_without_controls(
        monkeypatch):
    from gui_rewalk.src.core.visual_traversal.state import registration

    calls = []
    events = []

    class Perception:
        use_semantic_inventory = True
        last_page_name = "Home"
        last_surface_kind = "page"
        last_passive_feedback_present = False

        def semantic_inventory(self, shot, *, navigation_context="",
                               force_refresh=False):
            calls.append((shot, force_refresh))
            self.last_passive_feedback_present = True
            return [f"functional:{shot!r}"]

    frames = iter([
        {"screenshot": b"latest-1"},
        {"screenshot": b"latest-2"},
    ])
    captured = {}
    host = SimpleNamespace(
        perception=Perception(),
        env=SimpleNamespace(_get_obs=lambda: next(frames)),
        _settle_enabled=False,
        _state_data={},
        _map_guided_inherited=None,
        review_debug=SimpleNamespace(
            record_event=lambda *args, **kwargs: events.append(
                (args, kwargs))),
    )
    monkeypatch.setattr(registration.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(
        registration, "_try_map_guided",
        lambda *_args, **_kwargs: (None, None, None))
    monkeypatch.setattr(
        registration, "_register_semantic_observation",
        lambda self, obs, path, replay_hints=None, arrival_elements=None:
        captured.update(obs=obs, elements=arrival_elements) or ("s", True))

    assert registration.register_observation(
        host, {"screenshot": b"initial"}, []) == ("s", True)
    assert calls == [
        (b"initial", False),
        (b"latest-1", True),
        (b"latest-2", True),
    ]
    assert captured["obs"]["screenshot"] == b"latest-2"
    assert captured["elements"] == ["functional:b'latest-2'"]
    assert events[-1][0] == ("passive_feedback_ignored",)


def test_frame_identity_uses_semantic_regions_without_segmentation(tmp_path):
    from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine

    captured = {}
    frame_path = tmp_path / "frame.png"

    class Registry:
        def identify(self, shot, path, **kwargs):
            captured.update(kwargs)
            return "known"

    def write_frame(shot):
        frame_path.write_bytes(shot)
        return str(frame_path)

    host = SimpleNamespace(
        perception=SimpleNamespace(use_semantic_inventory=True),
        registry=Registry(), _judge_same_page=lambda *args: True,
        _screenshot_to_tmp=write_frame,
        _arrival_region_set=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("semantic identity must not segment geometry")),
    )
    element = VisualElement(
        0, "Clock", [0, 0, 0, 0], [0, 0], region="primary_navigation",
        region_id="semantic:primary_navigation:x", geometry_status="semantic_only")
    assert VisualTraversalEngine._frame_state_id(
        host, {"screenshot": _frame()}, [element]) == "known"
    assert captured["region_set"] == {"region:semantic:primary_navigation:x"}


def test_router_semantic_click_uses_durable_target_without_legacy_detection():
    from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine

    target = VisualElement(
        0, "More options", [0, 0, 0, 0], [0, 0], category="navigation",
        region="top_app_bar", region_id="r1", geometry_status="semantic_only")
    sent = []
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.perception = SimpleNamespace(
        use_semantic_inventory=True,
        detect_and_name=lambda _shot: (_ for _ in ()).throw(
            AssertionError("semantic Router click must not use detect_and_name")))
    engine._state_data = {"clock": {"elements": [target]}}
    engine._live_center_for = lambda element, obs: (
        [31, 42] if element is target else None)
    engine.env = SimpleNamespace(
        step=lambda action, pause: sent.append(action) or {"screenshot": _frame()})
    engine._settle_enabled = False
    engine._ensure_on_app = lambda obs: (obs, "", True)
    engine.review_debug = None

    result = engine._router_click_button(
        "clock", "More options", "r1", "top_app_bar",
        {"screenshot": _frame()})

    assert result.status == "action_dispatched"
    assert sent == [{"action_type": "CLICK", "parameters": {
        "x": 31, "y": 42, "button": "left"}}]


def test_live_merge_refreshes_factual_control_description():
    from gui_rewalk.src.core.visual_traversal.visual_engine import (
        VisualTraversalEngine,
    )

    stored = VisualElement(
        0, "Bluetooth", [0, 0, 0, 0], [0, 0],
        category="navigation", purpose="Open old settings",
        expected_immediate_effect="Show old controls",
        visible_state="unselected", semantic_evidence="old row",
        execution_safety="safe", changes_available_controls=True,
    )
    stored.visited = True
    fresh = VisualElement(
        9, "Bluetooth", [10, 20, 30, 40], [25, 40],
        category="navigation", purpose="Open Bluetooth settings",
        expected_immediate_effect="Show Bluetooth device controls",
        visible_state="selected", semantic_evidence="selected sidebar row",
        execution_safety="safe", changes_available_controls=True,
    )

    downgraded = VisualTraversalEngine._merge_topup_observation(stored, fresh)

    assert downgraded is False
    assert stored.visited is True
    assert stored.purpose == "Open Bluetooth settings"
    assert stored.expected_immediate_effect == "Show Bluetooth device controls"
    assert stored.visible_state == "selected"
    assert stored.semantic_evidence == "selected sidebar row"
    assert stored.execution_safety == "safe"
    assert stored.changes_available_controls is True


def test_router_semantic_identify_shortlists_all_pages_once():
    from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine

    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.perception = SimpleNamespace(
        use_semantic_inventory=True,
        semantic_inventory=lambda _shot: [],
        last_surface_kind="page", last_page_name="Alarm",
        detect_and_name=lambda _shot: (_ for _ in ()).throw(
            AssertionError("semantic identify must not use detect_and_name")))
    neighbors = ["source", *[f"neighbor-{index}" for index in range(6)]]
    engine._state_data = {
        **{sid: {"elements": [], "page_name": sid} for sid in neighbors},
        "actual": {"elements": [], "page_name": "Alarm",
                   "surface_kind": "popup_menu"},
        "remote": {"elements": [], "page_name": "Remote"},
    }
    engine.router = SimpleNamespace(
        expected_destinations=lambda _source, _label: list(neighbors))
    engine.registry = SimpleNamespace(known_path=lambda _sid: None)
    engine._node_descriptor = lambda sid: {
        "name": engine._state_data[sid]["page_name"]}
    seen = []
    def which_page(_shot, candidates, transition=None, current_observation=None):
        seen.append([item["sid"] for item in candidates])
        return "actual"
    engine.page_judge = SimpleNamespace(which_page=which_page)
    engine.review_debug = None
    engine._frame_state_id = lambda obs, elements=None: "fallback"

    assert engine._router_identify(
        {"screenshot": _frame()}, "source") == "actual"
    assert seen == [[*neighbors, "actual", "remote"]]


def test_router_env_error_is_dispatch_unknown():
    from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine

    target = VisualElement(
        0, "More options", [0, 0, 0, 0], [0, 0], category="navigation",
        region="top_app_bar", region_id="r1", geometry_status="semantic_only")
    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    engine.perception = SimpleNamespace(use_semantic_inventory=True)
    engine._state_data = {"clock": {"elements": [target]}}
    engine._live_center_for = lambda _element, _obs: [31, 42]
    engine.env = SimpleNamespace(
        step=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("delivery uncertain")))
    engine.review_debug = None
    obs = {"screenshot": _frame()}

    result = engine._router_click_button(
        "clock", "More options", "r1", "top_app_bar", obs)

    assert result.status == "dispatch_unknown"
    assert result.observation is obs
    assert result.reason == "env_error"


def test_router_semantic_touch_page_without_control_tries_system_back():
    from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine

    engine = VisualTraversalEngine.__new__(VisualTraversalEngine)
    perception = SimpleNamespace(
        use_semantic_inventory=True, last_surface_kind="page")
    perception.semantic_inventory = lambda _shot: [VisualElement(
        0, "Clock", [0, 0, 0, 0], [0, 0], interactive=False,
        region="top_app_bar", region_id="b0", geometry_status="semantic_only")]
    perception.detect_and_name = lambda _shot: (_ for _ in ()).throw(
        AssertionError("semantic Router Back must not use detect_and_name"))
    engine.perception = perception
    engine._is_touch = True
    calls = []
    next_obs = {"screenshot": _frame()}
    engine.env = SimpleNamespace(
        step=lambda action, **_kwargs: calls.append(action) or next_obs)
    engine._ensure_on_app = lambda value: (value, None, True)
    engine.review_debug = None
    obs = {"screenshot": _frame()}

    assert engine._router_back(obs) is next_obs
    assert calls == [{"action_type": "navigate_back"}]


@pytest.mark.parametrize("target_id, expected_path_key", [
    ("source", "source"),
    ("target", "new"),
])
def test_landing_commit_preserves_correct_cursor_for_same_and_new_state(
        target_id, expected_path_key):
    from gui_rewalk.src.core.visual_traversal.runtime.landing import (
        LandingCommitContext, commit_landing,
    )

    transitions = []
    host = SimpleNamespace(
        _commit_explored=lambda *_args: None,
        _state_data={"source": {"page_name": "Alarm"},
                     "target": {"page_name": "Clock"}},
        graph=SimpleNamespace(
            add_transition=lambda **kwargs: transitions.append(kwargs)),
        _persist_online_capabilities=lambda *_args: None,
        review_debug=SimpleNamespace(enabled=False),
        _maybe_save=lambda: None,
    )
    element = SimpleNamespace(
        id=1, name="Clock", region="primary_navigation")
    source_obs, new_obs = {"frame": "source"}, {"frame": "new"}
    source_path, source_hints = [{"source": 1}], [{"source_hint": 1}]
    new_path, new_hints = [{"new": 1}], [{"new_hint": 1}]
    committed = commit_landing(host, LandingCommitContext(
        source_id="source", target_id=target_id, element=element,
        is_seed=False, click_effect=None, verify_effect=False,
        ledger_action={"type": "CLICK"}, event_index=1,
        is_stateful=False, is_restore=False, mutation_id="",
        before_value="", after_value="", edge_label="Clock",
        source_path=source_path, source_hints=source_hints,
        source_observation=source_obs, new_path=new_path,
        new_hints=new_hints, observation=new_obs))
    if expected_path_key == "source":
        assert committed.state_id == "source"
        assert committed.path == source_path
        assert committed.replay_hints == source_hints
        assert committed.observation is new_obs
    else:
        assert committed.state_id == "target"
        assert committed.path == new_path
        assert committed.replay_hints == new_hints
        assert committed.observation is new_obs
    assert len(transitions) == 1


def test_landing_commit_marks_back_control_as_return_edge():
    from gui_rewalk.src.core.visual_traversal.runtime.landing import (
        LandingCommitContext, commit_landing,
    )

    transitions = []
    host = SimpleNamespace(
        _commit_explored=lambda *_args: None,
        _state_data={
            "detail": {"page_name": "Detail"},
            "parent": {"page_name": "Parent"},
        },
        graph=SimpleNamespace(
            add_transition=lambda **kwargs: transitions.append(kwargs)),
        _persist_online_capabilities=lambda *_args: None,
        review_debug=SimpleNamespace(enabled=False),
        _maybe_save=lambda: None,
    )
    back = SimpleNamespace(
        id=0, name="Close", region="dialog_actions", back=True)
    commit_landing(host, LandingCommitContext(
        source_id="detail", target_id="parent", element=back,
        is_seed=False, click_effect=None, verify_effect=False,
        ledger_action={"action_type": "CLICK"}, event_index=1,
        is_stateful=False, is_restore=False, mutation_id="",
        before_value="", after_value="", edge_label="Close",
        source_path=[], source_hints=[], source_observation={},
        new_path=[], new_hints=[], observation={}))

    assert transitions[0]["effect_kind"] == "return_via_control"


def test_landing_commit_keeps_pre_click_state_snapshot_after_live_merge():
    from gui_rewalk.src.core.visual_traversal.runtime.landing import (
        LandingCommitContext, commit_landing,
    )

    host = SimpleNamespace(
        _commit_explored=lambda *_args: None,
        _state_data={"source": {"page_name": "Settings"}},
        graph=SimpleNamespace(add_transition=lambda **_kwargs: None),
        _persist_online_capabilities=lambda *_args: None,
        review_debug=SimpleNamespace(enabled=False),
        _maybe_save=lambda: None,
        _frame_phash=lambda shot: "baseline-hash",
        _stateful_inflight=object(), _active_state_mutation=None,
        _stateful_probe_count=0, _stateful_probe_sources=set(),
    )
    # Registration already refreshed the canonical object to the live value.
    element = SimpleNamespace(
        id=1, name="Daily digest", region="settings_list",
        state_key="settings.daily_tips", state_value="on")
    committed = commit_landing(host, LandingCommitContext(
        source_id="source", target_id="source", element=element,
        is_seed=False,
        click_effect={"verdict": "transitioned_consistent", "note": "off->on"},
        verify_effect=True, ledger_action={"type": "CLICK"}, event_index=1,
        is_stateful=True, is_restore=False, mutation_id="m1",
        before_value="off", after_value="on", edge_label="Daily digest",
        source_path=[], source_hints=[],
        source_observation={"frame": "before", "screenshot": b"before"},
        new_path=[], new_hints=[], observation={"frame": "after"},
        baseline_candidates=["daily digest|settings_list|switch|"]))
    assert committed.observation == {"frame": "after"}
    assert host._active_state_mutation["before_value"] == "off"
    assert host._active_state_mutation["after_value"] == "on"
    assert host._active_state_mutation["baseline_candidates"] == [
        "daily digest|settings_list|switch|"]
    assert host._active_state_mutation["baseline_frame_phash"] == \
        "baseline-hash"
    assert ("source", "settings.daily_tips", "off") in host._stateful_probe_sources


def test_perception_only_semantic_writes_bbox_free_artifacts(tmp_path, monkeypatch):
    import gui_rewalk.run_visual_traversal as entry

    image_path = tmp_path / "shot.png"
    image_path.write_bytes(_frame())
    monkeypatch.setattr(
        "gui_rewalk.env.gui_gen_agent.GUIGenAgent", lambda **kwargs: object())

    def inventory(self, shot):
        self.last_page_name = "Alarm"
        self.last_surface_kind = "page"
        self.last_semantic_inventory_response = '{"interface_summary":"Alarm"}'
        self.last_semantic_blocks = [{"region_id": "semantic:content:x",
                                      "role": "content", "element_ids": [0]}]
        return [VisualElement(
            0, "Add alarm", [0, 0, 0, 0], [0, 0], category="navigation",
            region="content", region_id="semantic:content:x",
            geometry_status="semantic_only")]

    monkeypatch.setattr(VisualPerception, "semantic_inventory", inventory)
    args = SimpleNamespace(
        image=str(image_path), model="x", model_version="x", max_tokens=10,
        temperature=0, enable_thinking=False,
        semantic_inventory=True, vlm_grounding=True, caption_weights="",
        ocr_model_path="unused", box_threshold=.1, iou_threshold=.5,
        no_ocr=True, ocr_engine="easyocr", ocr_lang="en",
        result_dir=str(tmp_path / "out"), target_element="")
    assert entry.run_perception_only(args) == 0
    assert (tmp_path / "out" / "semantic_inventory.json").is_file()
    assert (tmp_path / "out" / "semantic_inventory_raw.txt").read_text(
        "utf-8") == '{"interface_summary":"Alarm"}'
    assert not (tmp_path / "out" / "som_labeled.png").exists()
    elements = json.loads((tmp_path / "out" / "elements.json").read_text("utf-8"))
    assert elements[0]["geometry_status"] == "semantic_only"


def test_perception_only_retries_rejected_target_with_correction(tmp_path, monkeypatch):
    import gui_rewalk.run_visual_traversal as entry
    from gui_rewalk.src.core.visual_traversal.agents.review import AnnotationReviewer

    image_path = tmp_path / "shot.png"
    image_path.write_bytes(_frame())
    monkeypatch.setattr(
        "gui_rewalk.env.gui_gen_agent.GUIGenAgent", lambda **kwargs: object())

    def inventory(self, shot):
        self.last_page_name, self.last_surface_kind = "Alarm", "page"
        self.last_semantic_blocks = [{"region_id": "semantic:content:x",
                                      "role": "content", "element_ids": [0]}]
        return [VisualElement(
            0, "Add alarm", [0, 0, 0, 0], [0, 0], category="navigation",
            region="content", region_id="semantic:content:x",
            geometry_status="semantic_only")]

    calls = []
    def ground(self, shot, target, force_refresh=False, correction_hint=""):
        calls.append((force_refresh, correction_hint))
        center = [30, 30] if not force_refresh else [80, 80]
        self.last_target_grounding = {
            "status": "matched", "correction_hint": correction_hint,
            "click_point_px": center}
        return VisualElement(
            target.id, target.name, [center[0] - 10, center[1] - 10, 20, 20], center,
            category=target.category, geometry_status="live_target")

    verdicts = iter([
        {"accepted": False, "reason": "box is on neighbor"},
        {"accepted": True, "reason": "correct target"},
    ])
    monkeypatch.setattr(VisualPerception, "semantic_inventory", inventory)
    monkeypatch.setattr(VisualPerception, "ground_target", ground)
    monkeypatch.setattr(
        AnnotationReviewer, "review_target",
        lambda self, shot, candidate, stored: next(verdicts))
    args = SimpleNamespace(
        image=str(image_path), model="x", model_version="x", max_tokens=10,
        temperature=0, enable_thinking=False,
        semantic_inventory=True, vlm_grounding=False, caption_weights="",
        ocr_model_path="unused", box_threshold=.1, iou_threshold=.5,
        no_ocr=True, ocr_engine="easyocr", ocr_lang="en",
        result_dir=str(tmp_path / "out"), target_element="Add alarm")
    assert entry.run_perception_only(args) == 0
    evidence = json.loads(
        (tmp_path / "out" / "target_grounding.json").read_text("utf-8"))
    assert calls == [(False, ""), (True, "box is on neighbor")]
    assert len(evidence["attempts"]) == 2
    assert evidence["review"]["accepted"] is True
    assert evidence["grounded"]["center"] == [80, 80]
    assert (tmp_path / "out" / "target_overlay.png").is_file()
