"""A bad inventory cannot erase an independently verified known-state action."""
import pytest

from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.contracts import ElementReport, OperationReport, PageReport, RegionReport
from gui_rewalk.src.core.explore.inventory import apply_page_report
from .explore_fixtures import _Agent, _Env, _known_screen, _png, _seed_ledger, _turn


def _receipt(owner="el1"):
    return {"attempt_ref": "a1", "element_actions": [
        {"element_ref": owner, "action": "click", "completed": True}],
        "region_actions": [], "function_info": [], "parameter_info": None,
        "representative_same_kind": None, "reason": "The known surface changed as observed.",
        "region_effects": [{"region_ref": "r1", "report_index": None,
                            "change": "updated", "cause": "action"}]}


def _bad_inventory():
    return {"regions": [{"region_ref": "r1", "name": "Known component", "summary": "Known component",
        "elements": [{"element_ref": "el404", "name": "Unresolved candidate", "operations": []}],
        "region_operations": []}], "survey_complete": True, "coverage_note": "Candidate report."}


@pytest.mark.parametrize("redundant_index", [False, True])
def test_known_action_settles_once_while_bad_inventory_remains_a_gap(tmp_path, redundant_index):
    execute = _turn(screen=_known_screen(), action={"kind": "click", "owner_ref": "el1",
        "target": "开始按钮", "point_1000": [500, 500]})
    observe = _turn(screen=_known_screen(), previous=_receipt(), page_report=_bad_inventory(),
        action={"kind": "click", "owner_ref": "el404", "target": "Unresolved", "point_1000": [500, 500]})
    if redundant_index:
        observe["previous_action"]["region_effects"][0]["report_index"] = 0
    agent = _Agent([(execute, False), (observe, True)])
    env = _Env(_png("white"), _png("black"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
        output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.ledger = _seed_ledger()
    result = runtime.run(env._get_obs())
    assert len(env.actions) == 1
    assert runtime.pending_attempt_id == ""
    assert runtime.ledger.attempts["a1"].outcome == "success"
    assert runtime.ledger.operations["o1"].status == "verified"
    assert "el404" not in runtime.ledger.elements
    assert result.status == "partial"
    assert any("inventory" in gap for gap in result.gaps)
    assert sum(e["kind"] == "action_settled" for e in runtime.ledger.events) == 1
    assert any(e["kind"] == "inventory_report_deferred" for e in runtime.ledger.events)
    assert not any(e["kind"] == "report_correction_resolved" for e in runtime.ledger.events)


@pytest.mark.parametrize("issue", ["wrong_owner", "new_region_effect", "new_state", "conflicting_index", "new_region"])
def test_inventory_separation_does_not_release_unsafe_settlement(tmp_path, issue):
    execute = _turn(screen=_known_screen(), action={"kind": "click", "owner_ref": "el1",
        "target": "开始按钮", "point_1000": [500, 500]})
    receipt = _receipt("el404" if issue == "wrong_owner" else "el1")
    if issue == "new_region_effect":
        receipt["region_effects"] = [{"region_ref": "", "report_index": 0, "change": "appeared", "cause": "action"}]
    screen = _known_screen()
    inventory = _bad_inventory()
    if issue == "new_region":
        inventory["regions"][0]["region_ref"] = ""
    if issue == "conflicting_index":
        receipt["region_effects"][0]["report_index"] = 0
        inventory["regions"][0]["region_ref"] = "r404"
    if issue == "new_state":
        screen = {**screen, "identity": "new_state", "state_ref": "", "state_name": "Unknown result"}
        inventory["regions"][0]["region_ref"] = "r404"
    observe = _turn(screen=screen, previous=receipt, page_report=inventory)
    agent = _Agent([(execute, False), (observe, True)])
    env = _Env(_png("white"), _png("black"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
        output_root=str(tmp_path), agent=agent, max_actions=1)
    runtime.ledger = _seed_ledger()
    runtime.max_turns = 2
    runtime.run(env._get_obs())
    assert len(env.actions) == 1
    assert runtime.ledger.attempts["a1"].outcome == "pending"
    assert runtime.pending_attempt_id == "a1"
    assert not any(e["kind"] == "inventory_report_deferred" for e in runtime.ledger.events)


@pytest.mark.parametrize("repair", [False, True])
def test_deferred_inventory_allows_next_bound_action_and_requires_repair_to_clear_gap(tmp_path, repair):
    ledger = _seed_ledger()
    added = PageReport(regions=(RegionReport(region_ref="r1", name="Known component",
        summary="Two independent controls", elements=(ElementReport("Second control", operations=(
            OperationReport("click", "Second control", "explore", "A different function",
                            parameter_status="none", parameter_summary="No parameters"),)),),
        region_operations=()),), survey_complete=True, coverage_note="Both controls visible")
    ledger = apply_page_report(ledger, state_id="s1", report=added).ledger
    execute = _turn(screen=_known_screen(), action={"kind": "click", "owner_ref": "el1",
        "target": "开始按钮", "point_1000": [500, 500]})
    observe = _turn(screen=_known_screen(), previous=_receipt(), page_report=_bad_inventory())
    turns = [(execute, False), (observe, True)]
    if repair:
        valid = _bad_inventory()
        valid["regions"][0]["elements"] = []
        turns.append((_turn(screen=_known_screen(), page_report=valid), False))
    turns.append((_turn(screen=_known_screen(), action={"kind": "click", "owner_ref": "el2",
        "target": "Second control", "point_1000": [250, 250]}), False))
    receipt = _receipt("el2")
    receipt["attempt_ref"] = "a2"
    turns.append((_turn(screen=_known_screen(), previous=receipt), True))

    class Env(_Env):
        def step(self, action, pause=0):
            self.actions.append(action)
            self.observation = {"screenshot": _png("black" if len(self.actions) == 1 else "blue")}
            return self.observation

    agent = _Agent(turns)
    env = Env(_png("white"), _png("black"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
        output_root=str(tmp_path), agent=agent, max_actions=2)
    runtime.ledger = ledger
    result = runtime.run(env._get_obs())
    assert len(env.actions) == 2 and not agent.turns
    assert [item.outcome for item in runtime.ledger.attempts.values()] == ["success", "success"]
    assert runtime.ledger.attempts["a2"].action["owner_ref"] == "el2"
    assert any("inventory" in gap for gap in result.gaps) is not repair
    assert any(e["kind"] == "inventory_report_resolved" for e in runtime.ledger.events) is repair
    if repair:
        assert not any(e["kind"] == "redundant_page_report_without_progress_rejected"
                       for e in runtime.ledger.events)
