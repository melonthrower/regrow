"""A completed function may replace its source Region with a result surface."""

from types import SimpleNamespace
import json

import pytest

from gui_rewalk.src.core.scenario.function_collection_research import RegionGuidedCollector
from .explore_fixtures import _contextual_region_route_ledger, _png


@pytest.mark.parametrize("final_verified", [True, False])
def test_goal_completion_can_outlive_its_source_region(final_verified):
    ledger = _contextual_region_route_ledger()
    replies = [
        {"region_visible": True, "complete": False, "action": {
            "kind": "click", "owner_ref": "", "target": "Submit the visible form",
            "point_1000": [500, 500], "text": None, "direction": None, "amount": None}},
        {"region_visible": False, "complete": True, "action": None},
    ]
    final_calls = []

    class Agent:
        def _call(self, **kwargs):
            if kwargs["role"] == "region_collection_final":
                final_calls.append(kwargs)
                return {"complete": final_verified, "reason": "Check the actual result evidence"}
            reply = replies.pop(0) if replies else {"region_visible": False, "complete": False, "action": None}
            return {"app_scope": "target_app", "visible_region_refs": ["r-nav"],
                    "previous_action_outcome": "success", "condition_value": None,
                    "reason": "The form disappeared and the requested result is visible", **reply}

    class Env:
        frame = _png("white")

        def _get_obs(self):
            return {"screenshot": self.frame}

        def step(self, _action, pause=0):
            self.frame = _png("blue")
            return self._get_obs()

    instruction = {"instruction": "Submit the form and preserve the result", "before": [
        {"region_ref": "r-world-dialog", "goal": "Submit the completed form"}],
        "condition": None, "if_true": [], "if_false": [], "after": []}
    result = RegionGuidedCollector(ledger, Agent(), Env(),
        SimpleNamespace(check=lambda: "target", app_name="fixture"), max_turns=3).execute(instruction)

    assert len(final_calls) == 1
    assert _png("white") in final_calls[0]["screenshots"]
    assert final_calls[0]["screenshots"][-1] == _png("blue")
    assert result["success"] is final_verified
    assert result["ref_results"][0]["complete"] is True
    assert len(result["trajectory"]) == 1
    assert result["trajectory"][0]["committed"] is True


def test_pending_navigation_requires_an_explicit_outcome():
    ledger = _contextual_region_route_ledger()
    enums = []

    class Agent:
        def _call(self, **kwargs):
            enums.append(list(kwargs["response_schema"]["properties"]["previous_action_outcome"]["enum"]))
            return {"app_scope": "target_app", "visible_region_refs": [], "region_visible": False,
                    "complete": False, "condition_value": None, "previous_action_outcome": "none",
                    "reason": "No result supplied", "action": {
                        "kind": "click", "owner_ref": "", "target": "Navigation", "point_1000": [500, 500]}}

    class Env:
        def _get_obs(self):
            return {"screenshot": _png("blue")}

        def step(self, _action, pause=0):
            return self._get_obs()

    instruction = {"instruction": "Reach and use the form", "before": [
        {"region_ref": "r-world-dialog", "goal": "Use the form"}],
        "condition": None, "if_true": [], "if_false": [], "after": []}
    result = RegionGuidedCollector(ledger, Agent(), Env(),
        SimpleNamespace(check=lambda: "target", app_name="fixture"), max_turns=3).execute(instruction)

    assert enums == [["none"], ["success", "no_effect", "uncertain"]]
    assert result["success"] is False
    assert len(result["trajectory"]) == 1
    assert any("GUI action outcome" in error for error in result["errors"])


def test_completed_branch_survives_the_recent_action_window():
    ledger = _contextual_region_route_ledger()
    prepare = {"region_ref": "r-nav", "goal": "Show the control"}
    selected = {"region_ref": "r-nav", "goal": "Turn the control off"}
    after = {"region_ref": "r-world-dialog", "goal": "Set the date"}
    followup_contexts = []

    class Agent:
        branch_clicked = False

        def _call(self, **kwargs):
            if kwargs["role"] == "region_collection_final":
                return {"complete": True, "reason": "Result verified"}
            context = json.loads(kwargs["user_prompt"])
            reply = {"app_scope": "target_app", "region_visible": True,
                     "visible_region_refs": ["r-nav"], "complete": True,
                     "condition_value": None, "previous_action_outcome": "success",
                     "reason": "Observed current result", "action": None}
            target = None
            if context["condition_check"]:
                reply["condition_value"] = True
            elif context["current_goal"] == selected and not self.branch_clicked:
                self.branch_clicked = True
                target = "Turn off"
            elif context["current_goal"] == after:
                followup_contexts.append(context)
                if len(followup_contexts) <= 3:
                    target = "Date step"
            if target:
                reply.update(complete=False, action={"kind": "click", "owner_ref": "",
                    "target": target, "point_1000": [500, 500]})
            return reply

    class Env:
        def _get_obs(self):
            return {"screenshot": _png("blue")}

        def step(self, _action, pause=0):
            return self._get_obs()

    task = {"instruction": "Reverse the control, then set the date", "before": [prepare],
            "condition": {"region_ref": "r-nav", "goal": "Is the control on?"},
            "if_true": [selected], "if_false": [{"region_ref": "r-nav", "goal": "Turn it on"}],
            "after": [after]}
    result = RegionGuidedCollector(ledger, Agent(), Env(),
        SimpleNamespace(check=lambda: "target", app_name="fixture"), max_turns=10).execute(task)

    assert result["success"] is True
    last = followup_contexts[-1]
    assert len(last["recent_actions"]) == 3
    assert all(x["action"]["target"] == "Date step" for x in last["recent_actions"])
    assert last.get("completed_goals") == [prepare, selected]
    assert last["branch_taken"] is True
