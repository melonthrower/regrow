"""Unit test: classify_edge_consistency — the DEBUG agent's non-deterministic
edge detector (spec B, 2026-07-06 grill Q4).

Same (source node, button name) clicked twice should lead to the SAME destination.
If it lands somewhere different, that's a non-deterministic transition (a mis-click,
a flaky page, or a broken replay) — flag it. Pure function, offline.

Usage:  python tests/test_edge_consistency.py
"""
import sys

sys.path.insert(0, ".")

from gui_rewalk.src.core.visual_traversal.visual_agents import (  # noqa: E402
    classify_edge_consistency)

fails = 0


def check(desc, cond):
    global fails
    print("PASS" if cond else "FAIL", desc)
    if not cond:
        fails += 1


seen = {}

# 1. first sighting of an edge -> not anomalous, remembered
r = classify_edge_consistency(seen, "home", "Network", "net_page")
check("first edge is not anomalous", r is None)
check("edge remembered", seen.get(("home", "Network")) == "net_page")

# 2. same (src,name) -> same dst: consistent, not anomalous
r = classify_edge_consistency(seen, "home", "Network", "net_page")
check("repeat to same dst is consistent", r is None)

# 3. same (src,name) -> DIFFERENT dst: anomalous, returns the prior dst
r = classify_edge_consistency(seen, "home", "Network", "bluetooth_page")
check("same button, different dst -> anomalous", r == "net_page")

# 4. different button on same src -> independent, not anomalous
r = classify_edge_consistency(seen, "home", "Bluetooth", "bt_page")
check("different button is independent", r is None)

# 5. same button name on a DIFFERENT src -> independent (per-source keying)
r = classify_edge_consistency(seen, "settings2", "Network", "other_page")
check("same name different src is independent", r is None)

# 6. self-loop dst (no-op click) is not flagged as nondeterministic on first sight
r = classify_edge_consistency(seen, "pageX", "Toggle", "pageX")
check("self-loop first sight not anomalous", r is None)

print("=" * 40)
if fails:
    print(f"{fails} FAILED"); sys.exit(1)
print("ALL PASS")
