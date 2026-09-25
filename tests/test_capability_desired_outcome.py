from __future__ import annotations

import json
from pathlib import Path

from gui_rewalk.src.core.scenario.capability_instruction_gen import (
    CapabilityInstructionGenerator,
)


class _Agent:
    def __init__(self) -> None:
        self.prompt = ""

    def predict_mm(self, prompt, _images):
        self.prompt = prompt
        return json.dumps(
            {
                "instructions": [
                    {
                        "type": "single",
                        "instruction": "Turn message notifications off.",
                        "capability_refs": [
                            "Settings::Set notifications"
                        ],
                        "params": {},
                        "desired_outcomes": {
                            "Settings::Set notifications": False
                        },
                        "runtime_slots": [],
                    }
                ]
            }
        ), None


def test_generator_preserves_per_ref_desired_outcome(tmp_path: Path) -> None:
    node = tmp_path / "settings"
    node.mkdir()
    (node / "page_capabilities.json").write_text(
        json.dumps(
            {
                "app_id": "mingle",
                "page_name": "Settings",
                "capabilities": [
                    {
                        "capability_id": "cap_notifications",
                        "name": "Set notifications",
                        "param": {"type": "none"},
                        "elements": ["toggle"],
                        "availability_status": "verified",
                    },
                    {
                        "capability_id": "cap_visible_only",
                        "name": "Visible but unverified control",
                        "param": {"type": "none"},
                        "elements": ["unverified"],
                        "status": "discovered",
                        "availability_status": "discovered",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    agent = _Agent()
    generator = CapabilityInstructionGenerator(
        str(tmp_path), agent, app_id="mingle"
    )

    instructions = generator.generate(n=1)

    assert "desired_outcomes" in agent.prompt
    assert "Visible but unverified control" in agent.prompt
    assert len(instructions) == 1
    ref = instructions[0].capability_refs[0]
    assert ref.desired_outcome is False
    assert ref.to_dict()["desired_outcome"] is False

class _InventingAgent:
    def predict_mm(self, _prompt, _images):
        return json.dumps({
            "instructions": [{
                "type": "single",
                "instruction": "Turn notifications off and enable an imaginary mode.",
                "capability_refs": [
                    "Settings::Set notifications",
                    "Settings::Imaginary mode",
                ],
                "params": {},
                "runtime_slots": [],
            }],
        }), None


def test_generator_rejects_instruction_when_any_ref_is_unknown(
    tmp_path: Path,
) -> None:
    node = tmp_path / "settings"
    node.mkdir()
    (node / "page_capabilities.json").write_text(json.dumps({
        "app_id": "mingle",
        "page_name": "Settings",
        "capabilities": [{
            "capability_id": "cap_notifications",
            "name": "Set notifications",
            "param": {"type": "none"},
            "availability_status": "verified",
        }],
    }), encoding="utf-8")
    generator = CapabilityInstructionGenerator(
        str(tmp_path), _InventingAgent(), app_id="mingle")

    assert generator.generate(n=1) == []
