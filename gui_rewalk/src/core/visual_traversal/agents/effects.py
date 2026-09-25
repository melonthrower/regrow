"""Visual-traversal agent role implementation."""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import numpy as np

from .common import _img_arr, _norm_fn, _parse_json
from ..prompts.navigation import STATEFUL_RISK_PROMPT
logger = logging.getLogger(__name__)

class StatefulRiskGuard:
    """Independent full-screen semantic gate before a function-set mutation.

    Grounding is optimized for element discovery and can still understate risk
    (observed live: Network/Wired was labelled risk=none).  This second VLM role
    sees the action in page context and fails closed; it runs only for a proposed
    safe stateful probe, never for ordinary navigation or the required inverse.
    """

    def __init__(self, agent, ledger=None):
        self.agent = agent
        self.ledger = ledger

    def assess(self, screenshot_bytes: bytes, element: Any) -> Dict[str, Any]:
        denied = {"allow": False, "risk": "unknown", "reason": "risk guard unavailable"}
        if self.agent is None or not screenshot_bytes:
            return denied
        description = {
            "name": getattr(element, "name", ""),
            "purpose": getattr(element, "purpose", ""),
            "expected_immediate_effect": getattr(
                element, "expected_immediate_effect", ""),
            "visible_state": getattr(element, "visible_state", ""),
            "state_key": getattr(element, "state_key", ""),
            "state_value": getattr(element, "state_value", ""),
            "effect_scope": getattr(element, "effect_scope", ""),
            "upstream_risk": getattr(element, "risk", ""),
        }
        prompt = STATEFUL_RISK_PROMPT.replace(
            "{element}", json.dumps(description, ensure_ascii=False))
        try:
            from ..visual_cache import predict_mm_role
            resp, *_ = predict_mm_role(
                self.agent, "stateful_risk_guard", prompt,
                [_img_arr(screenshot_bytes)], self.ledger)
        except Exception as exc:
            logger.warning("stateful risk guard failed: %s", exc)
            return denied
        parsed = _parse_json(resp)
        if not isinstance(parsed, dict):
            return denied
        risk = str(parsed.get("risk") or "unknown").strip().lower()
        if risk not in {
                "none", "connectivity", "destructive", "authentication",
                "permission", "unknown"}:
            risk = "unknown"
        # allow=True is accepted only with an explicit risk=none pair; the string
        # "false" must never become truthy through Python's generic bool().
        allow_raw = parsed.get("allow")
        allow_claim = (allow_raw is True) or (
            isinstance(allow_raw, str)
            and allow_raw.strip().lower() in {"true", "yes", "1"})
        allow = allow_claim and risk == "none"
        return {
            "allow": allow,
            "risk": risk,
            "reason": str(parsed.get("reason") or "")[:160] or
                      ("explicitly safe" if allow else "risk not cleared"),
        }
