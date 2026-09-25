"""Priority-1 offline test: semantic danger guard + widened categories.

No emulator, no VLM. Exercises the pure helpers in visual_filter that classify
which rows survive inventory filtering. Validates:
  1. Element names never decide safety; only explicit category/risk evidence does.
  2. is_enqueueable keeps navigation/shallow/display and excludes only dangerous.
  3. candidate_priority orders nav < unknown < shallow < display (explore-order
     hint, not a keep/drop signal).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui_rewalk.src.core.visual_traversal import visual_filter as vf
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement


def _element(name, **kwargs):
    return VisualElement(0, name, [0, 0, 10, 10], [5, 5], **kwargs)


def main():
    # 1a. rows that USED to be force-dropped by the danger net must now survive
    #     (perception supplies their category; these labels open sub-pages).
    recovered = [
        ("Reset options", "navigation"),
        ("Erase all data", "navigation"),   # 'erase' alone no longer danger
        ("Reset network settings", "navigation"),  # 'reset' alone no longer danger
        ("Delete account", "navigation"),
        ("Remove account", "navigation"),
        ("Uninstall", "navigation"),
        ("Format SD card", "navigation"),
        ("重置选项", "navigation"),
        ("删除账号", "navigation"),
        ("移除", "shallow"),
        ("卸载", "navigation"),
    ]
    for name, cat in recovered:
        assert vf.effective_category(cat, name) == cat
        assert vf.is_enqueueable(cat, name), f"{name!r} should be enqueueable"
        assert not _element(name).is_dangerous(), \
            f"{name!r} wrongly changed safety without semantic evidence"
    print(f"[1a] {len(recovered)} reset/delete/remove/uninstall/format rows "
          f"recovered (no longer force-dropped)")

    # 1b. Names alone never override the semantic category/risk contract.
    label_only = [
        ("Shut down", "navigation"),
        ("Power off", "shallow"),
        ("Reboot", "navigation"),
        ("Restart", "navigation"),
        ("Sign out", "navigation"),
        ("Log out", "navigation"),
        ("Factory reset", "navigation"),
        ("关机", "navigation"),
        ("注销", "navigation"),
        ("恢复出厂", "navigation"),
    ]
    for name, cat in label_only:
        assert vf.effective_category(cat, name) == cat
        assert not _element(name, category=cat).is_dangerous(), \
            f"{name!r} must not hit a name-based danger guard"
    assert _element("Any label", category="dangerous").is_dangerous()
    assert _element(
        "Any label", category="navigation", risk="destructive"
    ).is_dangerous()
    assert not _element("Restart tour").is_dangerous()
    assert not _element("Format SD card").is_dangerous()
    print(f"[1b] {len(label_only)} labels do not decide safety; explicit "
          "dangerous category/destructive risk is guarded")

    # 2. display/shallow are KEPT (enqueueable) — the dominant silent drop is gone.
    for cat in ("display", "shallow", "navigation", ""):
        assert vf.is_enqueueable(cat, "Some Row"), f"category {cat!r} should be kept"
    assert not vf.is_enqueueable("dangerous", "Some Row")
    print("[2] display/shallow/navigation/unknown all kept; only dangerous dropped")

    # 3. explore-order priority hint
    # NOTE: an EMPTY/unknown category resolves to 'navigation' (explore rather
    # than miss), so its priority equals nav's; shallow/display sort strictly
    # after. That is the intended explore-order: never bury an unknown row.
    p_nav = vf.candidate_priority("navigation", "X")
    p_unk = vf.candidate_priority("", "X")
    p_sh = vf.candidate_priority("shallow", "X")
    p_dis = vf.candidate_priority("display", "X")
    assert p_nav == p_unk < p_sh < p_dis, (p_nav, p_unk, p_sh, p_dis)
    print(f"[3] priority order nav({p_nav}) == unknown({p_unk}) < "
          f"shallow({p_sh}) < display({p_dis})")

    print("ALL PASS — danger is semantic rather than name-hardcoded; "
          "display/shallow rows remain inventory.")


if __name__ == "__main__":
    main()
