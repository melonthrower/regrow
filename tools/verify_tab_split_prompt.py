"""Verify the PageIdentityJudge prompt change on ALREADY-TRAVERSED node frames
(2026-07-06 用户: 标签换功能面=拆节点, 滚动续接同面=不拆). Uses the REAL VLM on
saved screenshots — offline, no VM. Runs concurrently with a live traversal fine.

Cases (ground truth):
  1. Identity-tab frame  vs  IPv4-tab frame   -> MUST be different (each tab = a
     distinct functional surface; this is the fix — was wrongly 'same' before).
  2. Network home (run A) vs Network home (run B) -> MUST be same (no over-split).
  3. Network home        vs  Wired dialog frame -> MUST be different (new overlay).

Usage:  python tools/verify_tab_split_prompt.py
"""
import os
import sys

sys.path.insert(0, ".")

from gui_rewalk.env.gui_gen_agent import GUIGenAgent  # noqa: E402
from gui_rewalk.src.core.visual_traversal.visual_agents import (  # noqa: E402
    PageIdentityJudge)

FC8 = "result_foldcheck8/20260706/setting"
FC9 = "result_foldcheck9/20260706/setting"

IDENTITY_TAB = f"{FC8}/_click_shots/8823670c_IPv4_4_before.png"   # Identity tab
IPV4_TAB = f"{FC8}/_click_shots/8823670c_IPv4_4_after.png"        # IPv4 tab
HOME_A = f"{FC8}/node_artifacts/8003070f0e7f7e7e/screenshot.png"  # Network home
HOME_B = f"{FC9}/node_artifacts/8003070f0e7f7e7e/screenshot.png"  # Network home
WIRED_DIALOG = f"{FC8}/node_artifacts/8823670c1b7f5c73/screenshot.png"  # dialog


def load(p):
    with open(p, "rb") as f:
        return f.read()


def main():
    agent = GUIGenAgent(model="Qwen", model_version="qwen3.7-plus", use_ark=False,
                        max_tokens=1500, temperature=0.1)
    judge = PageIdentityJudge(agent)  # no cache -> always calls the VLM

    cases = [
        ("Identity-tab vs IPv4-tab  (标签换功能面)", IDENTITY_TAB, IPV4_TAB, False),
        ("Network home vs Network home (两轮同页)", HOME_A, HOME_B, True),
        ("Network home vs Wired dialog (新浮层)", HOME_A, WIRED_DIALOG, False),
    ]
    fails = 0
    for desc, a, b, want_same in cases:
        if not (os.path.exists(a) and os.path.exists(b)):
            print("SKIP", desc, "(frame missing)"); continue
        got = judge.same_page(load(a), load(b))
        reason = getattr(judge, "last_reason", "")
        ok = (got == want_same)
        print(("PASS" if ok else "FAIL"),
              f"{desc}: same={got} (want {want_same})")
        print("      理由:", reason[:90])
        if not ok:
            fails += 1
    print("=" * 50)
    print("ALL PASS" if fails == 0 else f"{fails} FAILED")
    sys.exit(0 if fails == 0 else 1)


if __name__ == "__main__":
    main()
