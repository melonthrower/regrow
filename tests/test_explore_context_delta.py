"""Context reductions must preserve binding and pending evidence."""
from copy import deepcopy

from gui_rewalk.src.core.explore.status import build_agent_context, current_page_record, recent_actions
from gui_rewalk.src.core.explore.models import ActionAttempt, PageState, Region, RegionOccurrence
from .explore_fixtures import _ledger_with_current_canonical_binding, _seed_ledger


def _context(ledger, *, pending="", correction=None):
    return build_agent_context(ledger, None, "target", app_name="example", platform="desktop",
        pending_attempt_id=pending, correction="", rejection_count=0, rejection_limit=4,
        pending_report_correction=correction)


def test_correction_includes_only_explicitly_mentioned_element_bindings():
    ledger, _ = _ledger_with_current_canonical_binding()
    card = {"pending_attempt_ref": "a-missing", "received": "Cannot bind candidate to el2; do not invent refs."}
    before = deepcopy(card)
    context = _context(ledger, pending="a-missing", correction=card)
    refs = context["合同纠正卡"]["已登记引用"]
    assert [item["element_ref"] for item in refs] == ["el2"]
    assert refs[0]["variant_ref"] == ledger.elements["el2"].variant_id
    assert refs[0]["source_state_refs"] == ["s2"]
    assert refs[0]["operations"][0]["operation_ref"] == "co1"
    assert "不证明当前可见" in context["合同纠正卡"]["引用说明"]
    assert context["当前页面已登记内容"] == {}
    assert card == before


def test_correction_does_not_match_an_element_id_prefix():
    ledger, _ = _ledger_with_current_canonical_binding()
    card = {"pending_attempt_ref": "a-missing", "received": "Invalid el20 and co2"}
    context = _context(ledger, pending="a-missing", correction=card)
    assert "已登记引用" not in context["合同纠正卡"]


def test_compact_context_keeps_operations_and_unique_text():
    ledger = _seed_ledger()
    ledger.regions["r1"].memory = "Previously observed behavior and its limitation."
    full = current_page_record(ledger)
    context = _context(ledger)
    region = context["当前页面已登记内容"]["regions"][0]
    assert "memory" not in region
    assert context["探索焦点"]["region_memories"][0]["memory"] == ledger.regions["r1"].memory
    assert region["summary"] == full["regions"][0]["summary"]
    assert region["elements"] == full["regions"][0]["elements"]
    assert region["region_operations"] == full["regions"][0]["region_operations"]
    assert current_page_record(ledger) == full


def test_state_candidates_keep_content_identity_without_old_click_targets():
    ledger = _seed_ledger()
    ledger.states["s1"].summary = "Shared navigation with a document editor."
    ledger.states["s2"] = PageState(
        "s2", "p1", "Other content", "Shared navigation with file search.", "search.png")
    before = ledger.clone()
    states = {s["state_ref"]: s for s in _context(ledger)["已知页面图"]["states"]}
    assert states["s1"]["state_summary"] == ledger.states["s1"].summary
    assert states["s2"]["state_summary"] == ledger.states["s2"].summary
    assert "elements" not in states["s2"]
    assert "operations" not in states["s2"]
    assert ledger.states == before.states


def test_pending_and_recent_receipts_preserve_the_executed_point_for_correction():
    ledger = _seed_ledger()
    task = ledger.operation_task("o1")
    action = {"kind": "click", "owner_ref": "el1", "operation_ref": "o1",
              "target": "Visible control", "point_1000": [275.0, 625.0]}
    ledger.attempts["a1"] = ActionAttempt(
        "a1", task.task_id, "s1", "execute", action, "before.png",
        after_ref="after.png", outcome="no_effect", target_state_id="s1")
    before = deepcopy(action)
    pending = _context(ledger, pending="a1")["待结算动作详情"]
    recent = recent_actions(ledger, task_id=task.task_id)[0]
    assert pending["point_1000"] == before["point_1000"]
    assert recent["point_1000"] == before["point_1000"]
    assert recent["kind"] == "click"
    pending["point_1000"][0] = 999
    assert action == before


def test_pending_can_identify_any_known_return_surface_without_old_controls():
    ledger = _seed_ledger()
    ledger.states["s-other"] = PageState(
        "s-other", "p1", "Other result", "Different content", "old.png", ["ro-other"])
    ledger.regions["r-other"] = Region("r-other", "Result list", "Independent content")
    ledger.occurrences["ro-other"] = RegionOccurrence(
        "ro-other", "r-other", "s-other", "Result list", "Independent content")
    ledger.attempts["a1"] = ActionAttempt(
        "a1", "", "s1", "route", {"kind": "back"}, "before.png")
    states = {s["state_ref"]: s for s in _context(ledger, pending="a1")["已知页面图"]["states"]}
    assert states["s-other"]["known_regions"] == [
        {"region_ref": "r-other", "name": "Result list"}]
    assert "elements" not in states["s-other"]
