"""Unit test: ReviewDebugSink — turns the (log-only) AnnotationReviewer into a
DEBUG agent by persisting its per-node verdict + engine mis-click/retarget events
as structured JSONL (2026-07-06, 用户: 把检测异常的 agent 输出记录下来当 debug).

Offline, no VM / no API key.  Usage:  python tests/test_review_debug_sink.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, ".")

from gui_rewalk.src.core.visual_traversal.visual_agents import (  # noqa: E402
    ReviewDebugSink)
from gui_rewalk.src.core.visual_traversal.visual_perception import (  # noqa: E402
    VisualElement)

fails = 0


def check(desc, cond):
    global fails
    print("PASS" if cond else "FAIL", desc)
    if not cond:
        fails += 1


def mk(i, name, center, region="nav_sidebar", scroll=0):
    e = VisualElement(id=i, name=name, bbox_xywh=[center[0] - 30, center[1] - 12, 60, 24],
                      center=list(center))
    e.region = region
    e.scroll_steps = scroll
    return e


tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "_review_debug.jsonl")
sink = ReviewDebugSink(path)

els = [mk(0, "Network", [187, 96]), mk(1, "Color", [187, 761], scroll=2)]
review = {"wrong": [22, 27], "missing": [{"name": "Wired + button"}],
          "duplicate": [], "ok": False}

# 1. record a node review -> one JSONL line with node + elements + verdict
sink.record_node("8003070f", els, review)
# 2. record a mis-click event (the foldcheck5 Color fly)
sink.record_event("retarget_rejected", node="8003070f", elem="Color",
                  frm=[187, 761], to=[1123, 48], region=[0, 90, 375, 780])
sink.close()

lines = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
check("two records written", len(lines) == 2)

node_rec = [r for r in lines if r.get("kind") == "node"][0]
check("node id recorded", node_rec["node"] == "8003070f")
check("element names+coords captured",
      [e["name"] for e in node_rec["elements"]] == ["Network", "Color"]
      and node_rec["elements"][1]["scroll_steps"] == 2)
check("review verdict captured (wrong ids)", node_rec["review"]["wrong"] == [22, 27])
check("review missing names captured",
      node_rec["review"]["missing"][0]["name"] == "Wired + button")
check("node record timestamped", "ts" in node_rec)

ev = [r for r in lines if r.get("kind") == "event"][0]
check("event kind recorded", ev["type"] == "retarget_rejected")
check("event fly coords captured", ev["frm"] == [187, 761] and ev["to"] == [1123, 48])

# 3. unicode (Chinese missing names) survives round-trip (log had mojibake)
sink2 = ReviewDebugSink(os.path.join(tmp, "u.jsonl"))
sink2.record_node("x", [mk(0, "VPN 添加按钮", [1, 1])],
                  {"wrong": [], "missing": [{"name": "网络代理设置"}],
                   "duplicate": [], "ok": False})
sink2.close()
u = json.loads(open(os.path.join(tmp, "u.jsonl"), encoding="utf-8").readline())
check("unicode preserved (no mojibake)",
      u["elements"][0]["name"] == "VPN 添加按钮"
      and u["review"]["missing"][0]["name"] == "网络代理设置")

# 4. disabled sink (path=None) is a no-op, never raises
noop = ReviewDebugSink(None)
noop.record_node("y", els, review)
noop.record_event("x", a=1)
noop.close()
check("disabled sink is safe no-op", True)

print("=" * 40)
if fails:
    print(f"{fails} FAILED"); sys.exit(1)
print("ALL PASS")
