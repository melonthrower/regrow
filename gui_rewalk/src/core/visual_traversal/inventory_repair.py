"""Opt-in second-pass review for omissions in a saved semantic inventory."""

from __future__ import annotations

import io
import json
import re
from typing import Any, Dict, List

import numpy as np
from PIL import Image

from .prompts.grounding import ELEMENT_SEMANTICS_CONTRACT
from .visual_cache import predict_mm_role


def _json_object(response: Any) -> Dict[str, Any]:
    text = str(response or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    try:
        value = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
        except Exception:
            return {}
    return value if isinstance(value, dict) else {}


def build_inventory_repair_prompt(existing_elements: List[Dict[str, Any]]) -> str:
    existing = []
    for item in existing_elements:
        if not isinstance(item, dict):
            continue
        existing.append({
            "name": str(item.get("name") or ""),
            "action_label": str(item.get("action_label") or ""),
            "type": str(item.get("type") or item.get("el_type") or ""),
            "interactive": bool(item.get("interactive", False)),
            "category": str(item.get("category") or ""),
            "region": str(item.get("region") or ""),
            "selected": bool(item.get("selected", False)),
            "enabled": bool(item.get("enabled", True)),
        })
    return f"""
Review the complete GUI screenshot against the first-pass inventory below. The
inventory is a hypothesis, not ground truth. Return only visible interactive
controls that need to be ADDED because they are absent or represented only by a
secondary status/action string instead of the stable primary label of the
functional control.

First-pass inventory:
{json.dumps(existing, ensure_ascii=False, sort_keys=True)}

Use semantic identity, not exact string equality. Do not echo a control that is
already correctly represented under an equivalent stable name. In a compound
setting or control, prefer the persistent functional label over a changing value,
status, or prerequisite action; put the supporting visible text in
visual_evidence and name any replaced first-pass item in supersedes.

Require direct visual interaction evidence such as a bounded button/icon,
switch, checkbox, input, link treatment, menu item, or explicit control
affordance. A surrounding card, row, title, avatar label, or content item is not
a separate control merely because it groups a nested button. Include visibly
disabled controls with enabled=false and their blocked_reason. Do not infer
hidden or below-fold controls. Coordinates and geometry are forbidden.

Each candidate must have name, action_label, visual_evidence, type, interactive, category,
selected, group, back, enabled, requires_permission, blocked_reason, stateful,
state_key, state_value, effect_scope, reversible, risk, identity_anchor,
supersedes, and repair_reason. category must be one of
navigation/shallow/dangerous/display. Every returned candidate must have
interactive=true; otherwise omit it.

{ELEMENT_SEMANTICS_CONTRACT}

Return only one JSON object with candidates. Return {{"candidates": []}} when
the first-pass inventory already covers every visible interactive control.
""".strip()


class InventoryRepairExperiment:
    """Ask one VLM pass only for omissions in an existing inventory."""

    def __init__(self, agent, ledger=None):
        self.agent = agent
        self.ledger = ledger

    def review(self, screenshot_bytes: bytes,
               existing_elements: List[Dict[str, Any]], *,
               force_refresh: bool = False) -> Dict[str, Any]:
        image = Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")
        prompt = build_inventory_repair_prompt(existing_elements)
        response, *_ = predict_mm_role(
            self.agent, "semantic_inventory_repair", prompt,
            [np.asarray(image)], self.ledger, max_attempts=1,
            timeout_seconds=150, use_response_cache=not force_refresh)
        payload = _json_object(response)
        raw_candidates = payload.get("candidates")
        valid = isinstance(raw_candidates, list)
        candidates = []
        if valid:
            for item in raw_candidates:
                if (isinstance(item, dict)
                        and str(item.get("name") or "").strip()
                        and item.get("interactive") is True):
                    candidates.append(item)
        return {
            "status": "ok" if valid else "invalid_response",
            "existing_count": len(existing_elements),
            "candidates": candidates,
            "raw_response": str(response or ""),
        }


__all__ = ["InventoryRepairExperiment", "build_inventory_repair_prompt"]
