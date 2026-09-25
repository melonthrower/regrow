#!/usr/bin/env python3
"""Aggregate Round3 N=3 repeated collection (260628r3a/b/c). Stats per CAP across 3 runs."""
import json, os, statistics
from collections import defaultdict, Counter

BASE = os.path.join(os.path.dirname(__file__), "..", "collections", "OS")
RUNS = ["260628r3a", "260628r3b", "260628r3c"]

# load manifests
manifests = {}
defects = {}
for r in RUNS:
    with open(os.path.join(BASE, r, "setting", "manifest.json"), encoding="utf-8") as f:
        manifests[r] = json.load(f)
    dp = os.path.join(BASE, r, "setting", "graph_fidelity_defects.json")
    defects[r] = json.load(open(dp, encoding="utf-8")) if os.path.exists(dp) else None

# per-CAP across runs
caps = defaultdict(lambda: {"status": [], "cause": [], "excluded": [], "steps": []})
for r in RUNS:
    for ep in manifests[r]["episodes"]:
        cid = ep["instruction_id"]
        caps[cid]["status"].append(ep["final_status"])
        caps[cid]["cause"].append(ep.get("impossible_cause", "") or "-")
        caps[cid]["excluded"].append(ep.get("excluded_from_agent_stats", False))
        caps[cid]["steps"].append(ep["num_steps"])

print("="*100)
print("ROUND3 N=3 AGGREGATE  (runs: 260628r3a / r3b / r3c)")
print("="*100)

# per-run headline
print("\n--- Per-run headline ---")
for r in RUNS:
    m = manifests[r]
    raw = m["num_complete"] / m["num_episodes"]
    print(f"{r}: complete={m['num_complete']}/10  raw={raw:.2%}  "
          f"excl_rate(true)={m['agent_success_rate_excl_nonagent']}  "
          f"num_excluded={m['num_excluded_from_agent_stats']}  cause_dist={m['impossible_cause_distribution']}")

# per-CAP table
print("\n--- Per-CAP across 3 runs ---")
print(f"{'CAP':<7}{'status(a/b/c)':<30}{'cause(a/b/c)':<60}{'steps':<12}{'flip?'}")
flips = []
for cid in sorted(caps):
    c = caps[cid]
    st = "/".join(c["status"])
    cz = "/".join(c["cause"])
    sp = "/".join(map(str, c["steps"]))
    flipped = len(set(c["status"])) > 1
    if flipped: flips.append(cid)
    print(f"{cid:<7}{st:<30}{cz:<60}{sp:<12}{'YES' if flipped else ''}")

# aggregate rates
print("\n--- Aggregate rates (30 episodes total) ---")
total = sum(len(c["status"]) for c in caps.values())
n_complete = sum(s == "complete" for c in caps.values() for s in c["status"])
n_excluded = sum(c["excluded"][i] for c in caps.values() for i in range(len(c["excluded"])))
# true agent rate = complete / (total - excluded)
denom = total - n_excluded
print(f"raw success rate          = {n_complete}/{total} = {n_complete/total:.2%}")
print(f"excluded (non-agent)      = {n_excluded}")
print(f"true agent rate (excl)    = {n_complete}/{denom} = {n_complete/denom:.2%}")
mean_excl = statistics.mean(manifests[r]['agent_success_rate_excl_nonagent'] for r in RUNS)
print(f"mean per-run true rate    = {mean_excl:.2%}")

# per-CAP success fraction & consistency
print("\n--- Per-CAP success fraction (consistency) ---")
for cid in sorted(caps):
    c = caps[cid]
    sc = sum(s == "complete" for s in c["status"])
    print(f"{cid}: {sc}/3 complete  status={c['status']}")
print(f"\nUnstable (flipped between runs): {flips if flips else 'NONE'}")

# cause-tag distribution across all 30
print("\n--- Cause-tag distribution (all 30 episodes) ---")
allcause = Counter()
for c in caps.values():
    for i, st in enumerate(c["status"]):
        if st != "complete":
            allcause[c["cause"][i]] += 1
for k, v in allcause.most_common():
    print(f"  {k}: {v}")

# defects
print("\n--- graph_fidelity_defects.json per run ---")
for r in RUNS:
    d = defects[r]
    if d:
        print(f"{r}: graph_mismatch={d['summary']['num_graph_mismatch']} "
              f"state_dependent={d['summary']['num_state_dependent']}")
    else:
        print(f"{r}: (no defects file)")

# CAP003/004 focus
print("\n--- CAP003 / CAP004 cause focus ---")
for cid in ["CAP003", "CAP004"]:
    print(f"{cid}: status={caps[cid]['status']} cause={caps[cid]['cause']}")
