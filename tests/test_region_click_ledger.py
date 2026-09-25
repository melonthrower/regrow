"""[2026-07-08 用户 三层框架第2层] Region-keyed click ledger closes the shared-
sidebar re-click timing hole: a button clicked on page A must be dropped from
page B's candidates the moment B's sidebar matches the SAME region — with NO
seen_on>1 warm-up (the hole the name-based global dedup left)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gui_rewalk.src.core.visual_traversal.region_registry import RegionRegistry

SIDEBAR = ["Network", "Bluetooth", "Sound", "Display", "Power"]


def test_click_on_A_dedups_on_B_without_warmup():
    reg = RegionRegistry()
    # Page A: sidebar registered (seen_on={A}=1 -> NOT yet "shared").
    rid_a, is_new_a = reg.register("nav_sidebar", SIDEBAR, node_id="A")
    assert is_new_a
    # shared_button_names() is EMPTY at this point (the old warm-up hole).
    assert reg.shared_button_names() == set(), "warm-up hole precondition"
    # Click Network on A -> region ledger.
    reg.mark_clicked(rid_a, "Network")
    # Page B: same sidebar (subset/reorder) -> matches back to the SAME region id.
    rid_b, is_new_b = reg.register("nav_sidebar", SIDEBAR, node_id="B")
    assert rid_b == rid_a and not is_new_b, "B must match A's region"
    # THE FIX: Network is already clicked in this region -> dropped on B.
    assert reg.is_clicked(rid_b, "Network"), "clicked-on-A must dedup on B"
    # A sibling not yet clicked still enqueues.
    assert not reg.is_clicked(rid_b, "Bluetooth")
    print("PASS: click on A dedups on B with no seen_on warm-up")


def test_norm_is_consistent():
    reg = RegionRegistry()
    rid, _ = reg.register("nav_sidebar", SIDEBAR, node_id="A")
    reg.mark_clicked(rid, "  NETWORK  ")   # whitespace + case
    assert reg.is_clicked(rid, "network")
    print("PASS: mark/is_clicked normalize consistently")


def test_unknown_region_is_noop():
    reg = RegionRegistry()
    reg.mark_clicked("rNONE", "Network")   # no such region -> silent
    assert not reg.is_clicked("rNONE", "Network")
    print("PASS: unknown region id is a safe no-op")


def test_provisional_state_unregister_repairs_shared_membership():
    reg = RegionRegistry()
    rid, _ = reg.register("nav_sidebar", SIDEBAR, node_id="source")
    same, is_new = reg.register(
        "nav_sidebar", SIDEBAR, node_id="provisional")
    assert same == rid and not is_new
    assert reg.shared_button_names(), "two state memberships make it shared"
    reg.unregister_state("provisional")
    assert reg.regions_of("provisional") == set()
    assert reg.regions_of("source") == {f"region:{rid}"}
    assert reg.shared_button_names() == set()
    reg.unregister_state("source")
    assert rid not in reg._regions
    print("PASS: provisional state unregister repairs region membership")


def test_observer_correction_replaces_region_action_name():
    reg = RegionRegistry()
    rid, _ = reg.register(
        "toolbar", ["Date picker", "New event"], node_id="calendar")

    reg.rename_action(rid, "Date picker", "Manage your calendars")

    assert "date picker" not in reg.buttons(rid)
    assert "manage your calendars" in reg.buttons(rid)


if __name__ == "__main__":
    test_click_on_A_dedups_on_B_without_warmup()
    test_norm_is_consistent()
    test_unknown_region_is_noop()
    test_provisional_state_unregister_repairs_shared_membership()
    test_observer_correction_replaces_region_action_name()
    print("ALL PASS")
