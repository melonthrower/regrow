"""Summarize a run's _review_debug.jsonl (the DEBUG-agent output).

Answers the foldcheck6 verification questions at a glance:
  - how many nodes registered (early-stop check: should be >> 8)
  - per-node grounding quality (wrong / missing counts from the reviewer)
  - the actual MISSING functional entries the reviewer named (the coverage gaps)
  - every retarget_rejected / fly-click event (should be ~0 now the guard is on)
  - frontier_empty event (why the run ended)

Usage:  python tools/analyze_review_debug.py <path/to/_review_debug.jsonl>
        (or a result_dir; it will glob for the file)
"""
import glob
import json
import sys

arg = sys.argv[1] if len(sys.argv) > 1 else "result_foldcheck6"
paths = ([arg] if arg.endswith(".jsonl")
         else glob.glob(f"{arg}/**/_review_debug.jsonl", recursive=True))
if not paths:
    print(f"no _review_debug.jsonl under {arg!r}"); sys.exit(1)
path = paths[0]
recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]

nodes = [r for r in recs if r.get("kind") == "node"]
events = [r for r in recs if r.get("kind") == "event"]
breakdowns = [r for r in recs if r.get("kind") == "candidate_breakdown"]
agents = [r for r in recs if r.get("kind") == "agent"]

print(f"file: {path}")
print(f"nodes registered: {len(nodes)}")
print(f"events: {len(events)}")
print("=" * 60)

flies = [e for e in events if e["type"] == "retarget_rejected"]
print(f"\n[MIS-CLICK GUARD]  retarget_rejected (fly-clicks blocked): {len(flies)}")
for e in flies:
    print(f"  node {e.get('node','?')[:8]}  '{e.get('elem')}'  "
          f"{e.get('frm')} -> {e.get('to')}  region={e.get('region')}")

# [spec C] semantic click-effect verdicts — the adjacent-row mis-click + dead-click
ce = [e for e in events if e["type"] == "click_effect"]
bad = [e for e in ce if e.get("verdict") == "transitioned_inconsistent"]
noop = [e for e in ce if e.get("verdict") == "no_change"]
print(f"\n[CLICK-EFFECT]  {len(ce)} judged | "
      f"{len(bad)} mis-click(点偏) | {len(noop)} no-effect(死点)")
for e in bad:
    print(f"  MIS-CLICK  node {e.get('node','?')[:8]}  '{e.get('elem')}' -> "
          f"{str(e.get('dst',''))[:8]}  {e.get('note','')}")

# [spec B] other action anomalies
for kind, label in [("quarantine_edge", "点错页(QUARANTINE)"),
                    ("off_app_click", "点击掉出app"),
                    ("backtrack_false_arrival", "回溯假到达"),
                    ("nondeterministic_edge", "非确定性边"),
                    ("repeated_scroll", "重复滚动")]:
    hits = [e for e in events if e["type"] == kind]
    if hits:
        print(f"\n[{label}]  {len(hits)}")
        for e in hits[:12]:
            print(f"  {({k: v for k, v in e.items() if k not in ('kind','type','ts')})}")

stop = [e for e in events if e["type"] == "frontier_empty"]
for e in stop:
    print(f"\n[END] frontier_empty at {e.get('n_nodes')} nodes / "
          f"{e.get('n_actions')} actions")

# [spec A] candidate drop-breakdown — the early-stop diagnoser. Take the LAST
# snapshot per node (most-exhausted state) and flag nodes that ended with 0 kept
# but many dropped by a single dedup reason (the foldcheck6 22-sidebar pattern).
if breakdowns:
    last = {}
    for b in breakdowns:
        last[b["node"]] = b  # later snapshot wins
    print("\n[CANDIDATE DROP-BREAKDOWN]  (last snapshot per node)")
    for nid, b in last.items():
        by = b.get("by_reason") or {}
        hot = ", ".join(f"{k}={v}" for k, v in sorted(by.items(),
                                                       key=lambda kv: -kv[1]))
        flag = "  <-- 0 kept, all dropped" if b.get("n_kept") == 0 and b.get("n_dropped") else ""
        print(f"  {nid[:8]}  kept={b.get('n_kept')}  dropped={b.get('n_dropped')}"
              f"  [{hot}]{flag}")

print("\n[PER-NODE GROUNDING QUALITY]")
tot_missing = 0
for n in nodes:
    r = n.get("review", {})
    w = r.get("wrong") or []
    m = r.get("missing") or []
    tot_missing += len(m)
    flag = "" if (not w and not m) else "  <-- issues"
    print(f"  {n['node'][:8]}  els={n['n_elements']:3d}  "
          f"wrong={len(w):2d}  missing={len(m):2d}{flag}")

print(f"\n[COVERAGE GAPS]  reviewer-named missing entries (total {tot_missing}):")
seen = set()
for n in nodes:
    for m in (n.get("review", {}).get("missing") or []):
        nm = (m.get("name") or "").strip()
        if nm and nm not in seen:
            seen.add(nm)
            print(f"  - {nm}   (node {n['node'][:8]})")

# [agent transcript] line up, per click STEP, what the explorer anticipated vs the
# actual click outcome (and any page-identity merge reason) — "预期 vs 实际".
if agents or [e for e in events if e.get("type") == "click_effect"]:
    ce_by_step = {e.get("step"): e for e in events if e.get("type") == "click_effect"}
    exp_by_step = {}
    pi_records = []
    for a in agents:
        if a.get("agent") == "explorer":
            exp_by_step[a.get("step")] = a
        elif a.get("agent") == "page_identity":
            pi_records.append(a)
    steps = sorted(s for s in set(list(ce_by_step) + list(exp_by_step)) if s is not None)
    print("\n[AGENT TRANSCRIPT]  每次点击: explorer 预期 -> 实际结果")
    for s in steps:
        ex = exp_by_step.get(s); ce = ce_by_step.get(s)
        chose = ex.get("verdict") if ex else "?"
        antic = (ex.get("reason") or "")[:60] if ex else ""
        actual = ce.get("verdict") if ce else "(no outcome)"
        dst = str(ce.get("dst", ""))[:8] if ce else ""
        flag = ""
        if ce and ce.get("verdict") == "transitioned_inconsistent":
            flag = "  <== 点偏(预期与实际不符)"
        elif ce and ce.get("verdict") == "no_change":
            flag = "  <== 无新节点"
        print(f"  step {s}: 点 '{chose}' 预期[{antic}] -> 实际 {actual} {dst}{flag}")
    if pi_records:
        print("\n[PAGE-IDENTITY 判词]  (合并/区分的理由)")
        for a in pi_records[:20]:
            print(f"  node {str(a.get('node',''))[:8]} step {a.get('step')}: "
                  f"{a.get('verdict')} — {(a.get('reason') or '')[:70]}")
