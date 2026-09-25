"""Acceptance contracts for post-run autonomous fixture coverage."""

from __future__ import annotations

from tools.validate_autonomous_fixture import validate


def _oracle():
    return {
        "pages": [
            {"id": "a", "controls": [
                {"id": "a.nav_b", "label": "B"},
                {"id": "a.open", "label": "Menu"},
            ], "scroll": {
                "classification": "scrollable", "must_restore_top": True}},
            {"id": "b", "controls": [
                {"id": "b.nav_c", "label": "C"}],
             "scroll": {"classification": "static"}},
            {"id": "c", "controls": [
                {"id": "c.nav_a", "label": "A"},
                {"id": "c.nav_b", "label": "B"}],
             "scroll": {"classification": "static"}},
        ],
        "surfaces": [{"id": "a.sheet", "controls": [
            {"id": "sheet.close", "label": "Close"}]}],
        "transitions": [
            {"id": "a.nav_b", "source_page": "a", "action_label": "B",
             "target_page": "b", "effect": "peer_navigation", "required": True},
            {"id": "c.nav_b", "source_page": "c", "action_label": "B",
             "target_page": "b", "effect": "peer_navigation", "required": True},
            {"id": "b.nav_c", "source_page": "b", "action_label": "C",
             "target_page": "c", "effect": "forward", "required": True},
            {"id": "c.nav_a", "source_page": "c", "action_label": "A",
             "target_page": "a", "effect": "return", "required": True},
            {"id": "a.open", "source_page": "a", "action_label": "Menu",
             "target_page": "a", "target_surface": "a.sheet",
             "effect": "open_sheet", "required": True},
            {"id": "sheet.close", "source_page": "a",
             "source_surface": "a.sheet", "action_label": "Close",
             "target_page": "a", "effect": "dismiss_overlay", "required": True},
        ],
    }


def _record(phase, page, *, event=None, surface="", action_id="",
            top=True, bottom=False):
    return {
        "phase": phase, "event_index": event, "page": page,
        "surface": surface, "state": {"toggle": False},
        "action_id": action_id, "action_label": "",
        "action_disabled": False,
        "scroll": {"y": 0 if top else 100, "max_y": 100,
                   "top": top, "bottom": bottom},
    }


def _trace():
    rows = [_record("initial", "a")]
    pairs = [
        (_record("before", "a", event=1, action_id="a.nav_b"),
         _record("after", "b", event=1)),
        (_record("before", "b", event=2, action_id="b.nav_c"),
         _record("after", "c", event=2)),
        (_record("before", "c", event=3, action_id="c.nav_a"),
         _record("after", "a", event=3)),
        (_record("before", "a", event=4),
         _record("after", "a", event=4, top=False, bottom=True)),
        (_record("before", "a", event=5, top=False, bottom=True),
         _record("after", "a", event=5, top=True)),
        (_record("before", "a", event=6, action_id="a.open"),
         _record("after", "a", event=6, surface="a.sheet")),
        (_record("before", "a", event=7, surface="a.sheet",
                 action_id="sheet.close"),
         _record("after", "a", event=7)),
    ]
    for before, after in pairs:
        rows.extend([before, after])
    rows.append(_record("final", "a"))
    return {"stop_reason": "model_finished", "fixture_audit": rows}


def test_certifies_distinct_coverage_without_repeating_shared_navigation():
    report = validate(_oracle(), _trace())

    assert report["status"] == "certified"
    assert report["observed"]["pages"] == ["a", "b", "c"]
    assert report["observed"]["transition_units"] == 5
    assert report["unproductive_repeats"] == []


def test_reports_missing_truth_and_repeated_no_effect():
    trace = _trace()
    trace["stop_reason"] = "max_actions"
    trace["fixture_audit"] = [
        row for row in trace["fixture_audit"]
        if row.get("surface") != "a.sheet" and row.get("event_index") not in {4, 5}
    ]
    trace["fixture_audit"].extend([
        _record("before", "a", event=8, action_id="a.open"),
        _record("after", "a", event=8),
        _record("before", "a", event=9, action_id="a.open"),
        _record("after", "a", event=9),
    ])

    report = validate(_oracle(), trace)

    assert report["status"] == "incomplete"
    assert report["checks"]["model_finished"] is False
    assert report["checks"]["scroll_bottom"] is False
    assert report["checks"]["no_unproductive_repeats"] is False
