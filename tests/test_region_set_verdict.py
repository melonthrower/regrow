"""Unit test: region_set_verdict — page identity by REGION-ID SET (2026-07-06 用户:
页面身份=它含的区块 id 集合, 相等=同页). Pure, offline.

A page's identity = the set of "role:rid" its regions map to (RegionRegistry gives
each region a stable rid shared across nodes). Equal sets = same page. Sets that
differ in a DISCRIMINATING region (content/title) = different. Differ by exactly
one region = ambiguous (grounding noise; fall to the VLM).

Usage:  python tests/test_region_set_verdict.py
"""
import sys

sys.path.insert(0, ".")

from gui_rewalk.src.core.visual_traversal.visual_state import (  # noqa: E402
    region_set_verdict)

fails = 0


def check(desc, cond):
    global fails
    print("PASS" if cond else "FAIL", desc)
    if not cond:
        fails += 1


# identical region sets -> same page
check("identical region sets -> same",
      region_set_verdict({"nav_sidebar:r3", "content:r4"},
                         {"nav_sidebar:r3", "content:r4"}) == "same")

# shared sidebar but DIFFERENT content rid -> different (the Privacy-subpage fix)
check("shared sidebar, different content -> different",
      region_set_verdict({"nav_sidebar:r9", "content:r11", "titlebar:r10"},
                         {"nav_sidebar:r9", "content:r13", "titlebar:r12"}) == "different")

# totally different pages -> different
check("disjoint regions -> different",
      region_set_verdict({"nav_sidebar:r1", "content:r7"},
                         {"nav_sidebar:r22", "content:r24", "titlebar:r23"}) == "different")

# same page, one extra region present on one visit (grounding jitter) -> ambiguous
check("differ by exactly one region -> ambiguous",
      region_set_verdict({"nav_sidebar:r3", "content:r4"},
                         {"nav_sidebar:r3", "content:r4", "titlebar:r6"}) == "ambiguous")

# empty on one side (nothing segmented) -> ambiguous (can't decide)
check("empty region set -> ambiguous",
      region_set_verdict(set(), {"nav_sidebar:r3"}) == "ambiguous")

# subset that differs only in a NON-discriminating way still needs care:
# share sidebar + share content, differ only by title present/absent -> ambiguous
check("same nav+content, title jitter -> ambiguous",
      region_set_verdict({"nav_sidebar:r3", "content:r4", "titlebar:r6"},
                         {"nav_sidebar:r3", "content:r4"}) == "ambiguous")

print("=" * 40)
if fails:
    print(f"{fails} FAILED"); sys.exit(1)
print("ALL PASS")
