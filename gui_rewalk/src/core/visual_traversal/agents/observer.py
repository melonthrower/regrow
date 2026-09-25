"""Read-only VLM observation roles."""

from __future__ import annotations

import logging
from typing import Any, Dict

from .common import _img_arr, _parse_json
from ..prompts.observation import (
    build_coverage_observer_prompt,
    build_transition_observer_prompt,
)

logger = logging.getLogger(__name__)

_TRANSITION_RELATIONS = {
    "related", "unrelated", "no_relevant_change", "uncertain",
}
_TRANSITION_MAX_ATTEMPTS = 3


class ObserverAgent:
    """Describe and judge observed GUI state without proposing actions."""

    def __init__(self, agent, ledger=None):
        self.agent = agent
        self.ledger = ledger
        self.last_raw_response = ""

    def observe_transition(
            self, before_shot: bytes, after_shot: bytes,
            context: Dict[str, Any]) -> Dict[str, str]:
        self.last_raw_response = ""
        original_target = " ".join(str(
            context.get("target") or context.get("activated_control") or ""
        ).split())[:160]
        if self.agent is None or not before_shot or not after_shot:
            return {
                "target": original_target,
                "relation_to_target": "uncertain",
                "observed_outcome": "",
            }
        from ..visual_cache import predict_mm_role
        prompt = build_transition_observer_prompt(context)
        images = [_img_arr(before_shot), _img_arr(after_shot)]
        last_result = {
            "target": original_target,
            "relation_to_target": "uncertain",
            "observed_outcome": "",
        }
        for attempt in range(1, _TRANSITION_MAX_ATTEMPTS + 1):
            try:
                response, *_ = predict_mm_role(
                    self.agent,
                    "observer_transition",
                    prompt,
                    images,
                    self.ledger,
                    max_attempts=1,
                    use_response_cache=(attempt == 1),
                )
            except Exception as exc:
                logger.warning(
                    "transition observation attempt %d/%d failed: %s",
                    attempt, _TRANSITION_MAX_ATTEMPTS, exc)
                continue
            self.last_raw_response = str(response or "")
            parsed = _parse_json(response)
            if not isinstance(parsed, dict):
                last_result = {
                    "target": original_target,
                    "relation_to_target": "uncertain",
                    "observed_outcome": "",
                }
                continue
            target = " ".join(str(parsed.get("target") or "").split())[:160]
            relation = str(
                parsed.get("relation_to_target") or "").strip().lower()
            observed = " ".join(
                str(parsed.get("observed_outcome") or "").split())[:240]
            if (not target or relation not in _TRANSITION_RELATIONS
                    or not observed):
                last_result = {
                    "target": original_target,
                    "relation_to_target": "uncertain",
                    "observed_outcome": observed,
                }
                continue
            last_result = {
                "target": target,
                "relation_to_target": relation,
                "observed_outcome": observed,
            }
            if relation != "uncertain":
                return last_result
        return last_result

    def compare_coverage(
            self, screenshot: bytes, context: Dict[str, Any]) -> Dict[str, str]:
        """Verify one semantic coverage claim against an actual result."""
        if self.agent is None or not screenshot:
            return {
                "verdict": "uncertain",
                "reason": "coverage observer unavailable",
            }
        try:
            from ..visual_cache import predict_mm_role
            response, *_ = predict_mm_role(
                self.agent,
                "observer_coverage",
                build_coverage_observer_prompt(context),
                [_img_arr(screenshot)],
                self.ledger,
                max_attempts=1,
                use_response_cache=True,
            )
        except Exception as exc:
            logger.warning("coverage observation failed: %s", exc)
            return {
                "verdict": "uncertain",
                "reason": "coverage observer request failed",
            }
        parsed = _parse_json(response)
        if not isinstance(parsed, dict):
            return {
                "verdict": "uncertain",
                "reason": "coverage observer returned invalid JSON",
            }
        verdict = str(parsed.get("verdict") or "").strip().lower()
        reason = " ".join(str(parsed.get("reason") or "").split())[:240]
        if verdict not in {
                "same_result", "different_result", "uncertain"} or not reason:
            return {
                "verdict": "uncertain",
                "reason": "coverage observer returned an invalid verdict",
            }
        return {"verdict": verdict, "reason": reason}


__all__ = ["ObserverAgent"]
