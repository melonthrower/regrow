"""Offline contract for observation-time capability discovery."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui_rewalk.src.core.visual_traversal.capability_discovery import (  # noqa: E402
    discover_capabilities,
    merge_capability_records,
    observed_facts,
)
from gui_rewalk.src.core.graph.state_graph import StateGraph  # noqa: E402
from gui_rewalk.src.core.visual_traversal.artifacts import ArtifactWriter  # noqa: E402
from gui_rewalk.src.core.scenario.capability_synthesizer import PageCapabilities  # noqa: E402


def main() -> int:
    has_alarm = [
        {"id": 1, "name": "Add alarm", "category": "navigation",
         "el_type": "button", "interactive": True, "region": "toolbar"},
        {"id": 2, "name": "07:00", "category": "navigation",
         "el_type": "link", "interactive": True, "group": "alarm_item",
         "region": "content"},
        {"id": 3, "name": "Alarm enabled", "category": "shallow",
         "el_type": "toggle", "interactive": True, "stateful": True,
         "state_key": "alarm enabled", "state_value": "on",
         "effect_scope": "data_only"},
    ]
    facts = observed_facts(has_alarm)
    assert facts["present_groups"] == ["alarm item"]
    candidates = discover_capabilities(
        page_id="page_alarm", variant_id="variant_has_alarm",
        state_id="state_has_alarm", elements=has_alarm,
    )
    assert candidates and all(item["status"] == "discovered" for item in candidates)
    assert all("screenshot" not in str(item).lower() for item in candidates)
    assert all("bbox" not in str(item).lower() for item in candidates)
    open_item = next(item for item in candidates if item["input_slots"])
    assert open_item["input_slots"][0]["group"] == "alarm_item"
    assert open_item["available_when"]["variant_ids"] == ["variant_has_alarm"]

    empty = discover_capabilities(
        page_id="page_alarm", variant_id="variant_empty",
        state_id="state_empty", elements=[has_alarm[0]],
        extra_functions=[{
            "id": 99, "name": "Delete alarm", "category": "dangerous",
            "el_type": "button", "interactive": True,
            "region": "action_bar",
        }],
    )
    add_has = next(item for item in candidates if item["name"] == "open add alarm")
    add_empty = next(item for item in empty if item["name"] == "open add alarm")
    merged = merge_capability_records(add_has, add_empty)
    assert set(merged["evidence_variants"]) == {
        "variant_has_alarm", "variant_empty"
    }
    assert set(merged["available_when"]["variant_ids"]) == {
        "variant_has_alarm", "variant_empty"
    }
    assert set(merged["available_when"]["facts_by_variant"]) == {
        "variant_has_alarm", "variant_empty"
    }
    delete = next(item for item in empty if item["name"] == "use delete alarm")
    assert delete["status"] == "discovered"
    assert delete["risk_level"] == "high"

    multilingual = discover_capabilities(
        page_id="page_i18n", variant_id="default", state_id="i18n",
        elements=[
            {"id": 1, "name": "アラームを追加", "category": "navigation"},
            {"id": 2, "name": "알람 추가", "category": "navigation"},
            {"id": 3, "name": "Añadir alarma", "category": "navigation"},
            {"id": 4, "name": "Добавить будильник", "category": "navigation"},
        ],
    )
    assert len(multilingual) == 4, (
        "Unicode labels must not disappear during semantic normalization")

    blocked = discover_capabilities(
        page_id="page_permissions", variant_id="blocked", state_id="blocked",
        elements=[{
            "id": 20, "name": "Open camera", "category": "navigation",
            "enabled": False, "requires_permission": True,
            "blocked_reason": "camera permission", "region": "content",
        }],
    )[0]
    available = discover_capabilities(
        page_id="page_permissions", variant_id="allowed", state_id="allowed",
        elements=[{
            "id": 21, "name": "Open camera", "category": "navigation",
            "enabled": True, "requires_permission": False, "region": "content",
        }],
    )[0]
    variant_merge = merge_capability_records(blocked, available)
    assert variant_merge["availability_status"] == "conditional"
    assert variant_merge["requires"] == [], (
        "one blocked variant must not create a false global prerequisite")
    assert variant_merge["available_when"]["availability_by_variant"] == {
        "blocked": "blocked", "allowed": "discovered",
    }
    assert variant_merge["available_when"]["requires_by_variant"]["blocked"]
    assert variant_merge["available_when"]["requires_by_variant"]["allowed"] == []

    typed_controls = [
        {"id": 10, "name": "Alarm name", "category": "input",
         "el_type": "text_field", "interactive": True, "region": "form"},
        {"id": 11, "name": "Repeat", "category": "shallow",
         "el_type": "dropdown", "interactive": True, "region": "form"},
        {"id": 12, "name": "Sound", "category": "shallow",
         "el_type": "combobox", "interactive": True, "region": "form"},
        {"id": 13, "name": "Volume", "category": "shallow",
         "el_type": "slider", "interactive": True, "region": "form"},
        {"id": 14, "name": "Reorder alarm", "category": "shallow",
         "el_type": "drag_handle", "interactive": True, "region": "content"},
        {"id": 15, "name": "Save", "category": "navigation",
         "el_type": "button", "interactive": True, "region": "action_bar"},
    ]
    typed = discover_capabilities(
        page_id="page_alarm_edit", variant_id="variant_edit",
        state_id="state_edit", elements=typed_controls,
    )
    by_label = {
        item["source_elements"][0]["element_label"]: item for item in typed
    }

    text_capability = by_label["Alarm name"]
    assert text_capability["execution_recipe"] == [{
        "action_type": "TYPE",
        "selector": {
            "element_label": "Alarm name",
            "element_type": "text_field",
            "region": "form",
        },
        "parameters": {"text": "{{text}}"},
    }]
    assert text_capability["input_slots"] == [{
        "name": "text", "type": "string", "source": "runtime_parameter",
    }]

    for label in ("Repeat", "Sound"):
        dropdown = by_label[label]
        first_step = dropdown["execution_recipe"][0]
        assert first_step["action_type"] == "CLICK"
        assert first_step["runtime_options"] == {
            "required": True,
            "slot": "option",
            "source": "discover_at_runtime",
        }
        assert dropdown["input_slots"] == [{
            "name": "option", "type": "enum",
            "source": "discover_at_runtime",
        }]

    volume = by_label["Volume"]
    assert volume["param"]["values"] == ["最小", "一半", "最大"]
    assert volume["input_slots"] == [{
        "name": "level", "type": "enum",
        "source": "fixed_semantic_anchors",
        "values": ["最小", "一半", "最大"],
    }]
    assert volume["execution_recipe"] == [{
        "action_type": "SET_SLIDER",
        "selector": {
            "element_label": "Volume", "element_type": "slider",
            "region": "form",
        },
        "parameters": {"level": "{{level}}"},
    }]
    assert volume["availability_status"] == "discovered"
    assert volume["execution_support"] == "rebindable"

    unresolved_drag = by_label["Reorder alarm"]
    assert unresolved_drag["status"] == "discovered"
    assert unresolved_drag["execution_recipe"] == []
    assert unresolved_drag["availability_status"] == "unsupported"
    assert unresolved_drag["execution_support"] == "unsupported"

    save = by_label["Save"]
    assert save["execution_recipe"] == [{
        "action_type": "CLICK",
        "selector": {
            "element_label": "Save",
            "element_type": "button",
            "region": "action_bar",
        },
    }]
    serialized = str(typed).lower()
    assert "screenshot" not in serialized
    assert "bbox" not in serialized
    assert "center" not in serialized
    assert "x1" not in serialized and "x2" not in serialized

    graph = StateGraph("clock")
    graph.add_state(
        "state_has_alarm", has_alarm, "has.png", "clock",
        page_name="Alarm", page_id="page_alarm",
        variant_id="variant_has_alarm", observed_facts=facts,
        visible_capabilities=[item["capability_id"] for item in candidates],
    )
    graph.add_state(
        "state_detail", [], "detail.png", "clock",
        page_name="Alarm detail", page_id="page_alarm_detail",
        variant_id="variant_detail",
    )
    graph.register_capability_candidates("state_has_alarm", candidates)
    assert graph.capabilities[open_item["capability_id"]]["status"] == "discovered"
    effects_before_landing = copy.deepcopy(
        graph.capabilities[open_item["capability_id"]].get("effects"))
    predicate_before_landing = graph.capabilities[open_item["capability_id"]].get(
        "success_predicate")
    graph.add_transition(
        "state_has_alarm", "state_detail",
        {"action_type": "CLICK", "parameters": {"x": 10, "y": 20}},
        element_id="2", element_label="07:00", region="content",
        effect_verdict="transitioned_consistent", landing_verified=True,
        target_page_name="Alarm detail",
    )
    verified = graph.capabilities[open_item["capability_id"]]
    assert verified["status"] == "discovered"
    assert verified["target_pages"] == ["page_alarm_detail"]
    assert verified["action_edge_ids"]
    assert verified["entry_execution_evidence"][0]["landing_verified"] is True
    assert verified.get("effects") == effects_before_landing
    assert verified.get("success_predicate") == predicate_before_landing
    assert graph.pages["page_alarm"]["capability_ids"]
    assert graph.coverage_view()["capabilities"]["verified"] == 0
    assert "page_alarm" in graph.capability_view()["pages"]
    assert graph.routing_view().has_edge("state_has_alarm", "state_detail")

    permission_graph = StateGraph("permissions")
    permission_graph.add_state(
        "blocked", [], "blocked.png", "permissions",
        page_id="page_permissions", variant_id="blocked")
    permission_graph.add_state(
        "allowed", [], "allowed.png", "permissions",
        page_id="page_permissions", variant_id="allowed")
    permission_graph.register_capability_candidates("blocked", [blocked])
    permission_graph.register_capability_candidates("allowed", [available])
    registered = permission_graph.capabilities[blocked["capability_id"]]
    assert registered["availability_status"] == "conditional"
    assert registered["requires"] == []
    with tempfile.TemporaryDirectory() as temporary:
        writer = ArtifactWriter(temporary)
        writer.save_node(
            state_id="state_topup", screenshot_bytes=b"canonical",
            elements=[{"id": 0, "name": "First"}],
            visual_fingerprint={"phash": "0" * 16},
            page_name="Alarm", app_id="clock", page_id="page_alarm",
            variant_id="variant_empty", visible_capabilities=[],
        )
        writer.update_node_observation(
            "state_topup",
            elements=[{"id": 0, "name": "First"},
                      {"id": 1, "name": "Later top-up"}],
            page_name="Alarm", page_id="page_alarm",
            variant_id="variant_has_alarm", variant_signature="full",
            observed_facts={"alarm_exists": True},
            visible_capabilities=[verified["capability_id"]],
        )
        topup_root = Path(temporary) / "node_artifacts" / "state_topup"
        topup_elements = json.loads(
            (topup_root / "elements.json").read_text(encoding="utf-8"))
        topup_meta = json.loads(
            (topup_root / "state_meta.json").read_text(encoding="utf-8"))
        index = json.loads(
            (Path(temporary) / "node_artifacts" / "node_index.json")
            .read_text(encoding="utf-8"))
        assert [item["name"] for item in topup_elements] == [
            "First", "Later top-up"]
        assert topup_meta["elements_count"] == 2
        assert topup_meta["variant_id"] == "variant_has_alarm"
        assert index[0]["elements_count"] == 2
        assert (topup_root / "screenshot.png").read_bytes() == b"canonical"

        path = writer.save_capabilities(
            "state_has_alarm", app_id="clock", page_name="Alarm",
            page_id="page_alarm", variant_id="variant_has_alarm",
            capabilities=[verified],
        )
        sidecar = json.loads(Path(path).read_text(encoding="utf-8"))
        assert sidecar["schema_version"] == "capability.discovery.v1"
        assert sidecar["capabilities"][0]["status"] == "discovered"
        assert "screenshot" not in json.dumps(sidecar).casefold()
        compatible = PageCapabilities.from_dict(sidecar)
        assert compatible.capabilities[0].availability_status == "discovered"
        assert compatible.capabilities[0].execution_recipe

    print("PASS online capability discovery: discovered, portable, variant-aware")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
