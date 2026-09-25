"""Unit test: ReviewDebugSink.record_candidate_breakdown — the DEBUG agent's
per-node "candidate drop breakdown" (spec A, 2026-07-06 grill Q1/Q2/Q3).

Every time the engine asks a node "what's still explorable" (_unvisited_candidates),
this records, NEUTRALLY, which elements were dropped and WHY (visited / generic /
shared-global-explored / group-collapsed / dangerous) and how many remain. This is
what makes the foldcheck6 early-stop legible: "root: 22 navigation dropped by
shared-global-dedup" instead of a silent frontier-empty.

Offline, no VM / no API key.  Usage:  python tests/test_candidate_breakdown.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, ".")

from gui_rewalk.src.core.visual_traversal.visual_agents import (  # noqa: E402
    ReviewDebugSink)

fails = 0


def check(desc, cond):
    global fails
    print("PASS" if cond else "FAIL", desc)
    if not cond:
        fails += 1


tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "_dbg.jsonl")
sink = ReviewDebugSink(path)

# The engine collects (name, reason) for each dropped element + the kept names.
dropped = [("Bluetooth", "shared_global_explored"),
           ("Sound", "shared_global_explored"),
           ("Displays", "shared_global_explored"),
           ("Back", "chrome_generic"),
           ("Delete Account", "dangerous"),
           ("Alarm 8:30", "group_collapsed")]
kept = ["Add VPN Connection", "Wired Settings"]

sink.record_candidate_breakdown("8003070f", kept=kept, dropped=dropped)
sink.close()

recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
check("one breakdown record written", len(recs) == 1)
r = recs[0]
check("kind is candidate_breakdown", r.get("kind") == "candidate_breakdown")
check("node id recorded", r.get("node") == "8003070f")
check("kept count recorded", r.get("n_kept") == 2)
check("dropped count recorded", r.get("n_dropped") == 6)

# reason histogram — the key signal (spec: "root: 22 dropped by shared-global-dedup")
by = r.get("by_reason") or {}
check("reason histogram: shared_global_explored=3", by.get("shared_global_explored") == 3)
check("reason histogram: dangerous=1", by.get("dangerous") == 1)
check("reason histogram: group_collapsed=1", by.get("group_collapsed") == 1)

# per-element detail preserved (so a human can see WHICH items)
det = r.get("dropped") or []
check("per-element name+reason preserved",
      any(d.get("name") == "Bluetooth" and d.get("reason") == "shared_global_explored"
          for d in det))
check("kept names preserved", r.get("kept") == kept)
check("record timestamped", "ts" in r)

# unicode names survive (Chinese sidebar items) — the log garbled these
sink2 = ReviewDebugSink(os.path.join(tmp, "u.jsonl"))
sink2.record_candidate_breakdown("x", kept=["网络"],
                                 dropped=[("蓝牙", "shared_global_explored")])
sink2.close()
u = json.loads(open(os.path.join(tmp, "u.jsonl"), encoding="utf-8").readline())
check("unicode preserved", u["kept"] == ["网络"]
      and u["dropped"][0]["name"] == "蓝牙")

# disabled sink (path=None) is a safe no-op
noop = ReviewDebugSink(None)
noop.record_candidate_breakdown("y", kept=[], dropped=[])
noop.close()
check("disabled sink no-op safe", True)

print("=" * 40)
if fails:
    print(f"{fails} FAILED"); sys.exit(1)
print("ALL PASS")
