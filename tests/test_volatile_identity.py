"""Volatile-text identity filter (2026-07-14 用户).

Pure offline test — no VLM, no images, no key. Asserts that dynamic display
values (time/date/number) are dropped from the page-identity signature so the
SAME page revisited at a different time keeps ONE id (Clock 主页 no longer
splits), while stable sparse-page status text still distinguishes distinct
pages (Settings Bluetooth vs Privacy still SPLIT).

Run: python tests/test_volatile_identity.py   (or via pytest)
"""
import sys

sys.path.insert(0, ".")

from gui_rewalk.src.core.visual_traversal.state.identity import (  # noqa: E402
    _is_volatile_text, signature_names, observed_variant_facts)
from gui_rewalk.src.core.visual_traversal.state.regions import (  # noqa: E402
    _button_set_id)
from gui_rewalk.src.core.visual_traversal.state.matching import (  # noqa: E402
    normalize_button_names)


class E:
    """Minimal VisualElement stand-in for the getattr-based readers."""
    def __init__(self, name, category="", selected=False, group=""):
        self.name = name
        self.category = category
        self.selected = selected
        self.group = group
        self.stateful = False
        self.effect_scope = ""
        self.state_key = ""
        self.state_value = ""
        self.enabled = None
        self.requires_permission = False
        self.blocked_reason = ""


def sig_id(elements):
    """The derived state id for a frame's identity signature (empty-region path)."""
    return _button_set_id(signature_names(elements))


def test_volatile_predicate():
    """The predicate itself: drop values-that-change, keep real content."""
    volatile = ["10:08", "10:09", "下午 3:00", "9:41 AM", "2026-07-14",
                "7月14日", "85%", "42", "<PRIVATE_HOST>", "周一", "Mon", "May 14"]
    stable = ["Bluetooth Turned Off", "No Thunderbolt support", "Add alarm",
              "5 alarms", "时钟", "Wi-Fi", "May contain ads", "IPv6"]
    bad_v = [t for t in volatile if not _is_volatile_text(t)]
    bad_s = [t for t in stable if _is_volatile_text(t)]
    assert not bad_v, "these should be volatile but survived: %s" % bad_v
    assert not bad_s, "these are real content but got dropped: %s" % bad_s
    print("[1] volatile predicate OK — dropped %d, kept %d" % (len(volatile), len(stable)))


def test_clock_home_stable_across_time():
    """Clock 主页两次访问, 只有时间/日期变 -> 必须同一身份 id (不分裂)."""
    nav = lambda n, sel=False: E(n, category="navigation", selected=sel)
    # skeleton shared by both visits: title + more/add + bottom nav (时钟 selected)
    skeleton = [E("时钟", category="display"), E("more options", category="navigation"),
                E("add", category="navigation"), nav("闹钟"), nav("时钟", sel=True),
                nav("定时器"), nav("秒表"), nav("就寝时间")]
    frame_a = skeleton + [E("10:08", category="display"), E("周一 7月14日", category="display")]
    frame_b = skeleton + [E("10:09", category="display"), E("周二 7月15日", category="display")]
    id_a, id_b = sig_id(frame_a), sig_id(frame_b)
    assert id_a == id_b, (
        "Clock home split on time change!\n  A sig=%s\n  B sig=%s"
        % (sorted(normalize_button_names(signature_names(frame_a))),
           sorted(normalize_button_names(signature_names(frame_b)))))
    print("[2] Clock home OK — same id %s across time change" % id_a[:10])


def test_settings_sparse_pages_still_split():
    """稀疏页靠稳定状态文字区分 -> Bluetooth vs Privacy 必须不同 id (不误合并)."""
    bt = [E("Bluetooth", category="display"), E("Bluetooth Turned Off", category="display")]
    pv = [E("Privacy", category="display"), E("No Thunderbolt support", category="display")]
    id_bt, id_pv = sig_id(bt), sig_id(pv)
    assert id_bt != id_pv, "sparse pages wrongly merged (status text lost)!"
    print("[3] Settings sparse OK — Bluetooth %s != Privacy %s" % (id_bt[:8], id_pv[:8]))


def test_variant_facts_drop_volatile():
    """Second line of defense: even if VLM mis-tags a dynamic value as a
    non-display function, the volatile filter keeps it out of variant facts."""
    els = [E("Add alarm", category="navigation"), E("10:08", category="button")]
    facts = observed_variant_facts(els)
    assert "10:08" not in facts["functions"], "volatile leaked into variant facts"
    assert "add alarm" in facts["functions"], "real function dropped"
    print("[4] variant facts OK — functions=%s" % facts["functions"])


if __name__ == "__main__" or "pytest" not in sys.modules:
    if __name__ == "__main__":
        test_volatile_predicate()
        test_clock_home_stable_across_time()
        test_settings_sparse_pages_still_split()
        test_variant_facts_drop_volatile()
        print("\nRESULT: PASS — Clock stays one node, Settings still splits")
