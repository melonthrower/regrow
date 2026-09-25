"""Deterministic audit for agent-caused trajectory failures.

The audit consumes compact per-step facts emitted by a collector.  It does not
infer success from the action name: callers provide expected action ids plus
before/after outcome, scroll, verification, and optional graph-distance facts.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence


def audit_agent_trajectory(
    steps: Sequence[Mapping[str, Any]],
    *,
    max_consecutive_scrolls: int = 4,
    scroll_progress_epsilon: float = 1.0,
) -> Dict[str, Any]:
    """Flag unexpected, ineffective, regressing, or outcome-inverting actions."""

    issues: list[Dict[str, Any]] = []
    consecutive_scrolls = 0
    consecutive_stalled_scrolls = 0

    def add(step: int, code: str, severity: str, detail: str) -> None:
        issues.append({
            "step": step,
            "code": code,
            "severity": severity,
            "detail": detail,
        })

    for index, raw in enumerate(steps):
        step_number = int(raw.get("step", index + 1) or index + 1)
        action = raw.get("action") if isinstance(raw.get("action"), Mapping) else {}
        action_type = str(action.get("type") or raw.get("action_type") or "").casefold()
        action_id = str(
            action.get("id") or action.get("action_id") or raw.get("action_id") or ""
        )
        expected = raw.get("expected_action_ids") or []
        if isinstance(expected, str):
            expected = [expected]
        expected_ids = {str(value) for value in expected if str(value)}
        if expected_ids and action_id not in expected_ids:
            add(
                step_number,
                "unexpected_action",
                "error",
                f"action {action_id!r} is not in the expected set {sorted(expected_ids)}",
            )

        effect = raw.get("effect") if isinstance(raw.get("effect"), Mapping) else {}
        if effect.get("had_effect") is False:
            add(step_number, "no_effect_action", "warning", "before/after evidence shows no effect")

        if "desired_outcome" in effect and "observed_outcome" in effect:
            desired = effect.get("desired_outcome")
            observed = effect.get("observed_outcome")
            if observed != desired:
                add(
                    step_number,
                    "wrong_outcome",
                    "error",
                    f"desired outcome {desired!r}, observed {observed!r}",
                )

        before_distance = effect.get("graph_distance_before")
        after_distance = effect.get("graph_distance_after")
        if (
            isinstance(before_distance, (int, float))
            and isinstance(after_distance, (int, float))
            and after_distance > before_distance
        ):
            add(
                step_number,
                "route_regression",
                "error",
                f"graph distance increased from {before_distance} to {after_distance}",
            )

        if raw.get("committed") is False:
            add(step_number, "uncommitted_action", "error", "action transaction was not committed")
        verification = raw.get("verification")
        if isinstance(verification, Mapping) and verification.get("complete") is False:
            add(
                step_number,
                "verification_failed",
                "error",
                str(verification.get("reason") or "step verification returned false"),
            )

        if action_type == "scroll":
            consecutive_scrolls += 1
            scroll_before = effect.get("scroll_before")
            scroll_after = effect.get("scroll_after")
            progressed = not (
                isinstance(scroll_before, (int, float))
                and isinstance(scroll_after, (int, float))
                and abs(scroll_after - scroll_before) <= scroll_progress_epsilon
            )
            if progressed:
                consecutive_stalled_scrolls = 0
            else:
                consecutive_stalled_scrolls += 1
                severity = "error" if consecutive_stalled_scrolls >= 2 else "warning"
                add(
                    step_number,
                    "repeated_scroll_no_progress",
                    severity,
                    f"scroll position stayed at {scroll_after!r}",
                )
            if consecutive_scrolls > max(1, int(max_consecutive_scrolls)):
                add(
                    step_number,
                    "excessive_consecutive_scroll",
                    "error",
                    f"more than {max_consecutive_scrolls} consecutive scroll actions",
                )
        else:
            consecutive_scrolls = 0
            consecutive_stalled_scrolls = 0

    errors = sum(issue["severity"] == "error" for issue in issues)
    warnings = sum(issue["severity"] == "warning" for issue in issues)
    score = max(0.0, 1.0 - 0.25 * errors - 0.08 * warnings)
    return {
        "agent_failure": errors > 0,
        "quality_score": round(score, 3),
        "num_steps": len(steps),
        "error_count": errors,
        "warning_count": warnings,
        "issues": issues,
    }


__all__ = ["audit_agent_trajectory"]
