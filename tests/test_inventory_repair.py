from __future__ import annotations

import io
import json

import numpy as np
from PIL import Image

from gui_rewalk.src.core.visual_traversal.inventory_repair import (
    InventoryRepairExperiment,
    build_inventory_repair_prompt,
)
from gui_rewalk.src.core.visual_traversal.visual_cache import VLMCallLedger


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (160, 90), "white").save(out, "PNG")
    return out.getvalue()


class _Agent:
    model = "fake"
    model_version = "fake-v1"
    max_tokens = 100
    top_p = 0.9
    temperature = 0
    enable_thinking = False
    max_retry = 1

    def __init__(self):
        self.calls = []

    def predict_mm_with_policy(self, prompt, images, max_attempts,
                               timeout_seconds=None):
        self.calls.append((prompt, [image.shape for image in images]))
        return json.dumps({"candidates": [{
            "name": "More options", "visual_evidence": "ellipsis icon",
            "type": "icon_button", "interactive": True,
            "category": "navigation", "selected": False, "group": "",
            "back": False, "enabled": True, "requires_permission": False,
            "blocked_reason": "", "stateful": False, "state_key": "",
            "state_value": "unknown", "effect_scope": "unknown",
            "reversible": None, "risk": "none", "identity_anchor": True,
            "supersedes": "", "repair_reason": "missing icon control",
        }]}), 10, 5, 1


def test_inventory_repair_requests_only_missing_controls():
    agent = _Agent()
    ledger = VLMCallLedger()
    existing = [{"name": "Home", "el_type": "nav_item",
                 "interactive": True, "category": "navigation"}]
    result = InventoryRepairExperiment(agent, ledger).review(_png(), existing)

    assert result["status"] == "ok"
    assert [item["name"] for item in result["candidates"]] == ["More options"]
    prompt, shapes = agent.calls[0]
    assert shapes == [(90, 160, 3)]
    assert '"name": "Home"' in prompt
    assert "secondary status/action string" in prompt
    assert ledger.snapshot()["roles"]["semantic_inventory_repair"]["calls"] == 1


def test_repair_prompt_is_generic_and_rejects_container_inference():
    prompt = build_inventory_repair_prompt([])
    assert "surrounding card, row, title, avatar label" in prompt
    assert "persistent functional label" in prompt
    assert "action_label" in prompt
    assert "Cloud sync" not in prompt
