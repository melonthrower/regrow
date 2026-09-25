"""Unit test: ReviewDebugSink.record_agent — structured per-agent transcript
(spec: 2026-07-06 用户 "把每个 agent 的回复结构化记下来, 看点击前后各 agent 怎么说、
预期 vs 实际, 判断 agent 准不准").

Each VLM role (explorer / page_identity / dismisser / review / click_effect)
logs its PARSED verdict + reason, tagged with the node + the step,
so the analyzer can line up "explorer said click Wired expecting a detail page"
against "click_effect said no_change" and judge accuracy. Offline.

Usage:  python tests/test_agent_transcript.py
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
path = os.path.join(tmp, "_review_debug.jsonl")
sink = ReviewDebugSink(path)

# explorer anticipates the result of clicking Wired Settings
sink.record_agent("explorer", node="8003070f", step=5,
                  verdict="Wired Settings",
                  reason="进入 Wired 连接的详情/设置页面")
# page-identity merged a tab-switch — record ITS reasoning (why same)
sink.record_agent("page_identity", node="8823670c", step=6,
                  verdict="same", reason="B 只是 A 的 Wired 对话框切到 IPv4 标签")
# click-effect records the resulting transition observation
sink.record_agent("click_effect", node="8003070f", step=5, verdict="changed")
sink.close()

recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
check("three agent records written", len(recs) == 3)
check("all tagged kind=agent", all(r.get("kind") == "agent" for r in recs))

exp = [r for r in recs if r["agent"] == "explorer"][0]
check("explorer verdict = chosen element", exp["verdict"] == "Wired Settings")
check("explorer reason captured (the anticipation)",
      "详情" in exp["reason"] or "设置" in exp["reason"])
check("record carries node + step for line-up",
      exp.get("node") == "8003070f" and exp.get("step") == 5)
check("record timestamped", "ts" in exp)

pi = [r for r in recs if r["agent"] == "page_identity"][0]
check("page_identity verdict + reason captured (why merged)",
      pi["verdict"] == "same" and "IPv4" in pi["reason"])

# unicode reasons survive
sink2 = ReviewDebugSink(os.path.join(tmp, "u.jsonl"))
sink2.record_agent("explorer", node="x", step=1, verdict="蓝牙", reason="进入蓝牙设置页面")
sink2.close()
u = json.loads(open(os.path.join(tmp, "u.jsonl"), encoding="utf-8").readline())
check("unicode reason preserved", u["reason"] == "进入蓝牙设置页面")

# disabled sink = safe no-op
noop = ReviewDebugSink(None)
noop.record_agent("explorer", node="x", step=1, verdict="y")
noop.close()
check("disabled sink no-op safe", True)

print("=" * 40)
if fails:
    print(f"{fails} FAILED"); sys.exit(1)
print("ALL PASS")
