from gui_rewalk.src.core.scenario.agent_trajectory_audit import (
    audit_agent_trajectory,
)


def test_clean_trace_has_no_agent_failure():
    report = audit_agent_trajectory([{
        "step": 1,
        "action": {"type": "click", "id": "settings.daily_tips"},
        "expected_action_ids": ["settings.daily_tips"],
        "effect": {
            "had_effect": True,
            "desired_outcome": True,
            "observed_outcome": True,
            "graph_distance_before": 0,
            "graph_distance_after": 0,
        },
        "committed": True,
        "verification": {"complete": True},
    }])
    assert report["agent_failure"] is False
    assert report["quality_score"] == 1.0
    assert report["issues"] == []


def test_wrong_action_and_inverse_toggle_are_errors():
    report = audit_agent_trajectory([{
        "step": 4,
        "action": {"type": "click", "id": "settings.daily_tips"},
        "expected_action_ids": ["settings.about_fixture"],
        "effect": {
            "had_effect": True,
            "desired_outcome": True,
            "observed_outcome": False,
        },
        "committed": True,
    }])
    assert report["agent_failure"] is True
    assert {issue["code"] for issue in report["issues"]} == {
        "unexpected_action", "wrong_outcome",
    }


def test_repeated_stalled_scroll_becomes_agent_failure():
    steps = [{
        "step": index,
        "action": {"type": "scroll", "id": "page.scroll"},
        "effect": {"scroll_before": 900, "scroll_after": 900},
        "committed": True,
    } for index in range(1, 4)]
    report = audit_agent_trajectory(steps)
    issues = [issue for issue in report["issues"]
              if issue["code"] == "repeated_scroll_no_progress"]
    assert report["agent_failure"] is True
    assert [issue["severity"] for issue in issues] == ["warning", "error", "error"]


def test_route_regression_uncommitted_and_failed_verification_are_errors():
    report = audit_agent_trajectory([{
        "step": 2,
        "action": {"type": "click", "id": "wrong.branch"},
        "effect": {"graph_distance_before": 1, "graph_distance_after": 3},
        "committed": False,
        "verification": {"complete": False, "reason": "target state absent"},
    }])
    assert report["agent_failure"] is True
    assert {issue["code"] for issue in report["issues"]} == {
        "route_regression", "uncommitted_action", "verification_failed",
    }
