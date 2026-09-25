from __future__ import annotations

import json
from pathlib import Path


def test_region_collector_selects_branch_live_and_accepts_unmapped_screen(tmp_path):
    from types import SimpleNamespace
    from gui_rewalk.src.core.scenario.function_collection_research import RegionGuidedCollector
    from .explore_fixtures import _contextual_region_route_ledger, _png
    ledger = _contextual_region_route_ledger()
    responses = [
        dict(region_visible=True, complete=False, condition_value=False, action=None),
        dict(region_visible=False, complete=False, condition_value=None,
             action={"kind": "click", "target": "visible task control", "owner_ref": "",
                     "point_1000": [300, 300], "text": None, "direction": None, "amount": None}),
        dict(region_visible=True, complete=True, condition_value=None, action=None),
        dict(region_visible=True, complete=True, condition_value=None, action=None),
        {"complete": True, "reason": "selected branch and common goal are visible in saved evidence"},
    ]
    class Agent:
        def _call(self, **kwargs):
            item = responses.pop(0)
            return {"visible_region_refs": ["r-nav"], "previous_action_outcome": "success",
                    "app_scope": "target_app", "reason": "fresh screen evidence", **item}
    class Env:
        def _get_obs(self): return {"screenshot": _png("blue")}
        def step(self, action, pause=0): return self._get_obs()
    task = {"instruction": "if A then B else C, then D", "before": [],
            "condition": {"region_ref": "r-nav", "goal": "A?"},
            "if_true": [{"region_ref": "r-nav", "goal": "B"}],
            "if_false": [{"region_ref": "r-world-dialog", "goal": "C"}],
            "after": [{"region_ref": "r-nav", "goal": "D"}]}
    scope = SimpleNamespace(check=lambda: "target", app_name="fixture")
    result = RegionGuidedCollector(ledger, Agent(), Env(), scope, max_turns=8).execute(task)
    assert result["success"], result["errors"]
    assert result["branch_taken"] is False
    assert [x["goal"] for x in result["ref_results"]] == ["C", "D"]
    assert len(result["trajectory"]) == 1
    assert result["trajectory"][0]["arrived_node_id"] is None
    assert result["trajectory"][0]["committed"]
    assert not responses
    from gui_rewalk.src.core.scenario.collection_writer import CollectionWriter
    writer = CollectionWriter(str(tmp_path), "desktop", "20260906", "fixture")
    episode = Path(writer.write_visual_episode(result, "branch", instruction_meta=task))
    saved = json.loads((episode / "trajectory.json").read_text(encoding="utf-8"))
    assert saved["branch_taken"] is False
    assert (episode / "screenshots" / saved["meta"]["final_frame"]).is_file()
    assert (episode / "screenshots" / saved["branch_decisions"][0]["frame"]).is_file()
    assert (episode / "screenshots" / saved["ref_results"][0]["frame"]).is_file()


def test_discovered_functions_can_generate_tasks_without_any_attempt():
    from .explore_fixtures import _seed_ledger
    from gui_rewalk.src.core.scenario.function_collection_research import design_region_instruction
    ledger = _seed_ledger()
    class Agent:
        def _call(self, **kwargs):
            inventory = json.loads(kwargs["user_prompt"])["regions"]
            assert inventory[0]["operations"][0]["observed_results"] == []
            return {"instruction": "Use the discovered function", "before": [
                {"region_ref": inventory[0]["region_ref"], "goal": "Use the visible function"}],
                "condition": None, "if_true": [], "if_false": [], "after": []}
    assert not ledger.attempts
    assert design_region_instruction(ledger, Agent())["before"][0]["region_ref"] == "r1"
