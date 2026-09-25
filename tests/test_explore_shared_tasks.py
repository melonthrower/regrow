"""One exploration goal across reviewed local bindings, with local evidence."""
from copy import deepcopy
from dataclasses import replace

from gui_rewalk.src.core.explore.contracts import parse_turn
from gui_rewalk.src.core.explore.inventory import apply_page_report
from gui_rewalk.src.core.explore.models import ActionAttempt, HistoryItem, PageState, RegionOccurrence, Task
from gui_rewalk.src.core.explore.status import current_operation_binding
from gui_rewalk.src.core.explore.tasks import TaskScheduler, task_source_states

from .explore_fixtures import _known_screen, _seed_ledger, _turn


def _add_shared_binding(ledger, handling="explore"):
    ledger.states["s2"] = PageState("s2", "p1", "Other layout", "same control", "second.png")
    ledger.pages["p1"].state_ids.append("s2")
    ledger.current_state_id = "s2"
    ledger.occurrences["ro-shared"] = RegionOccurrence("ro-shared", "r1", "s2", "Shared controls", "same controls")
    ledger.states["s2"].region_occurrence_ids.append("ro-shared")
    ledger.regions["r1"].occurrence_ids.append("ro-shared")
    ledger.ensure_occurrence_variant("ro-shared")
    report = parse_turn(_turn(screen=_known_screen(), page_report={
        "regions": [{"region_ref": "r1", "name": "Shared controls", "summary": "same controls",
                     "elements": [{"element_ref": "", "name": "Start in this layout", "operations": [{
                         "operation_ref": "co1", "action": "click", "target": "Start", "handling": handling,
                         "reason": "same operation, current binding", "parameter_status": "none", "parameter_summary": "none"}]}],
                     "region_operations": []}], "survey_complete": True, "coverage_note": "visible controls inventoried"}),
        has_pending_action=False).page_report
    result = apply_page_report(ledger, state_id="s2", report=report)
    assert result.ok, result.issue
    return result.ledger


def test_new_state_reuses_task_and_exposes_current_binding():
    original = _seed_ledger()
    task_id = original.operation_task("o1").task_id
    ledger = _add_shared_binding(original)
    alias = next(o for o in ledger.operations.values() if o.operation_id != "o1")
    assert len([t for t in ledger.tasks.values() if t.kind == "explore_operation"]) == 1
    assert ledger.operation_task(alias.operation_id).task_id == task_id
    assert task_source_states(ledger, ledger.tasks[task_id]) == {"s1", "s2"}
    chosen = TaskScheduler().select_visible_operation(ledger, "co1", "use current visible binding")
    assert chosen.task_id == task_id
    assert current_operation_binding(ledger, chosen.operation_id).operation_id == alias.operation_id
    assert not ledger.attempts


def test_recorded_new_binding_does_not_complete_existing_unknown_goal():
    ledger = _add_shared_binding(_seed_ledger(), handling="record")
    task = ledger.operation_task("o1")
    alias = next(o for o in ledger.operations.values() if o.operation_id != "o1")
    assert ledger.operation_task(alias.operation_id) is task
    assert task.status == "pending"
    assert ledger.operations["o1"].status == "pending"


def test_available_binding_reuses_deferred_goal_without_resetting_attempts():
    original = _seed_ledger()
    original.operations["o1"].status = "deferred"
    task = original.operation_task("o1")
    task.status, task.attempt_count = "deferred", 2
    ledger = _add_shared_binding(original)
    chosen = TaskScheduler().choose(ledger)
    assert chosen.task_id == task.task_id
    assert chosen.attempt_count == 2
    assert current_operation_binding(ledger, chosen.operation_id).operation_id != "o1"


def test_old_duplicate_tasks_coalesce_without_changing_gui_evidence():
    ledger = _add_shared_binding(_seed_ledger())
    alias = next(o for o in ledger.operations.values() if o.operation_id != "o1")
    first = next(t for t in ledger.tasks.values() if t.operation_id == "o1")
    # Model identity can be established after both local tasks were created.
    ledger.tasks = {t.task_id: t for t in ledger.tasks.values() if t.kind != "explore_operation" or t.task_id == first.task_id}
    duplicate = Task("t-extra", "explore_operation", "active", "s2", alias.operation_id, attempt_count=1)
    first.attempt_count = 2
    ledger.tasks[duplicate.task_id] = duplicate
    ledger.current_task_id = duplicate.task_id
    ledger.attempts["a-old"] = ActionAttempt("a-old", first.task_id, "s1", "execute", {"kind": "click", "owner_ref": "el1", "operation_ref": "o1"}, "before.png", "after.png", "uncertain", "original outcome", "s1")
    ledger.history.append(HistoryItem(1, first.task_id, "execute", "click", "Start", {"owner_ref": "el1"}, "uncertain", "s1", "s1"))
    evidence = deepcopy(ledger.attempts["a-old"])
    TaskScheduler().choose(ledger)
    ordinary = [t for t in ledger.tasks.values() if t.kind == "explore_operation"]
    assert len(ordinary) == 1
    kept = ordinary[0]
    assert kept.task_id == duplicate.task_id
    assert kept.attempt_count == 3
    assert replace(ledger.attempts["a-old"], task_id=evidence.task_id) == evidence
    assert ledger.history[0].task_id == kept.task_id
    assert ledger.operation_task("o1") is ledger.operation_task(alias.operation_id)
    assert any(e["kind"] == "operation_tasks_coalesced" for e in ledger.events)


def test_success_closes_shared_goal_without_fabricating_sibling_result():
    ledger = _add_shared_binding(_seed_ledger())
    alias = next(o for o in ledger.operations.values() if o.operation_id != "o1")
    alias.status, alias.result = "verified", "observed in s2"
    TaskScheduler().choose(ledger)
    assert ledger.operation_task("o1").status == "done"
    assert ledger.operations["o1"].status == "recorded"
    assert ledger.operations["o1"].result == ""
    assert not ledger.attempts


def test_explicit_representative_members_keep_separate_trial_tasks():
    ledger = _add_shared_binding(_seed_ledger())
    alias = next(o for o in ledger.operations.values() if o.operation_id != "o1")
    identity = ledger.canonical_operations["co1"]
    identity.representative_operation_ids = ["o1", alias.operation_id]
    ledger.tasks["t-member"] = Task("t-member", "explore_operation", "pending", "s2", alias.operation_id)
    TaskScheduler().choose(ledger)
    assert ledger.operation_task("o1").task_id != ledger.operation_task(alias.operation_id).task_id
