"""Backward-compatible executable CapabilityAtom artifact contract."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui_rewalk.src.core.scenario.capability_instruction_gen import (  # noqa: E402
    CapabilityRef,
    Instruction,
)
from gui_rewalk.src.core.scenario.capability_synthesizer import (  # noqa: E402
    Capability,
    PageCapabilities,
)


def main() -> int:
    atom = Capability(
        name="编辑闹钟铃声",
        region="content",
        elements=["e1"],
        requires=[{"kind": "resource", "fact": "exists(alarm_ref)"}],
        effects=[{"fact": "alarm.ringtone", "value": "{ringtone}"}],
        success_predicate="详情页中铃声字段显示目标值",
        observables=[{"name": "ringtone", "type": "text"}],
        cleanup=[{"capability": "delete_alarm", "owned_only": True}],
        execution_recipe=[
            {
                "action_type": "CLICK",
                "selector": {"element_label": "Ringtone", "region": "form"},
            },
            {
                "action_type": "CLICK",
                "selector": {"element_label": "{{ringtone}}", "region": "dialog"},
            },
        ],
        action_steps=2,
    )
    atom.bind_context("clock", "alarm-detail", "Alarm Detail")
    page = PageCapabilities(
        node_id="alarm-detail", app_id="clock", page_name="Alarm Detail",
        page_breakdown="Edit one alarm", capabilities=[atom])
    encoded = json.loads(json.dumps(page.to_dict(), ensure_ascii=False))
    decoded = PageCapabilities.from_dict(encoded)
    loaded = decoded.capabilities[0]
    assert loaded.app_id == "clock"
    assert loaded.capability_id == atom.capability_id
    assert loaded.entry_surfaces == ["alarm-detail"]
    assert loaded.requires[0]["kind"] == "resource"
    assert loaded.action_steps == 2
    assert loaded.execution_recipe == atom.execution_recipe
    assert "action_recipe" not in encoded["capabilities"][0]
    assert "actions" not in encoded["capabilities"][0]

    legacy = PageCapabilities.from_dict({
        "node_id": "legacy", "page_name": "Legacy", "page_breakdown": "",
        "capabilities": [{"name": "Toggle", "param": {"type": "boolean"}}],
    })
    assert legacy.capabilities[0].availability_status == "unknown"
    assert legacy.capabilities[0].entry_surfaces == ["legacy"]

    legacy_aliases = PageCapabilities.from_dict({
        "node_id": "legacy-recipes", "page_name": "Legacy recipes",
        "page_breakdown": "",
        "capabilities": [
            {
                "name": "Old action recipe",
                "action_recipe": [{"action_type": "PRESS", "key": "enter"}],
            },
            {
                "name": "Old actions",
                "actions": [{"action_type": "BACK"}],
            },
        ],
    })
    assert legacy_aliases.capabilities[0].execution_recipe[0]["action_type"] == "PRESS"
    assert legacy_aliases.capabilities[1].execution_recipe[0]["action_type"] == "BACK"
    assert legacy_aliases.capabilities[0].action_steps == 1

    ref = CapabilityRef(
        node_id="alarm-detail", target_node="alarm-detail", app_id="clock",
        capability_id=atom.capability_id, page_name="Alarm Detail",
        name=atom.name, param_type="enum", requires=atom.requires,
        effects=atom.effects, success_predicate=atom.success_predicate,
        observables=atom.observables, cleanup=atom.cleanup,
        execution_recipe=atom.execution_recipe, action_steps=2,
        params={"ringtone": "Birdsong"})
    instruction = Instruction(
        instruction_id="CAP001", type="single", instruction="修改闹钟铃声",
        capability_refs=[ref], apps_involved=["clock"], fixed_order=True)
    out = instruction.to_dict()
    assert out["fixed_order"] is True
    assert out["capability_refs"][0]["app_id"] == "clock"
    assert out["capability_refs"][0]["success_predicate"]
    assert out["capability_refs"][0]["execution_recipe"] == atom.execution_recipe
    assert out["capability_refs"][0]["params"] == {"ringtone": "Birdsong"}

    print("PASS executable CapabilityAtom schema + legacy compatibility")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
