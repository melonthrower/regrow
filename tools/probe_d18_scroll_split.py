"""Scan local android result graphs for D18 "same page, different element
count" node pairs: high global_uid overlap (jaccard) but different state_id.

These are REAL scroll-split samples (better than a simulated subset) for
designing the skeleton-stable state_id fix. Read-only.

Run: python tools/probe_d18_scroll_split.py
"""
import json
import sys
from pathlib import Path
from itertools import combinations

ROOT = Path(__file__).resolve().parents[1]


def uids(node):
    return {e.get("global_uid", "") for e in node.get("elements", []) if e.get("global_uid")}


def names(node):
    return {e.get("name", "") for e in node.get("elements", [])}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def scan_graph(path):
    try:
        g = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []
    nodes = g.get("nodes", [])
    out = []
    for a, b in combinations(nodes, 2):
        if a["state_id"] == b["state_id"]:
            continue
        ua, ub = uids(a), uids(b)
        if len(ua) < 2 or len(ub) < 2:
            continue
        j = jaccard(ua, ub)
        if j >= 0.5 and len(ua) != len(ub):
            out.append((j, a, b, path))
    return out


def main():
    import sys
    # If a graph path (or run dir) is given, scan ONLY that — avoids mixing in
    # unrelated old archives under result_android*/ (which inflated counts when
    # the default glob ran). No arg => scan all android graphs (legacy mode).
    if len(sys.argv) > 1:
        arg = Path(sys.argv[1])
        if arg.is_file():
            graphs = [arg]
        else:
            graphs = list(arg.glob("**/graphs/*_graph.json")) or list(
                arg.glob("**/*_graph.json"))
        print(f"scanning {len(graphs)} graph(s) under {arg}\n")
    else:
        graphs = list(ROOT.glob("result_android*/gen_data/*/graphs/*_graph.json"))
        print(f"scanning {len(graphs)} android graphs (all archives)...\n")
    found = []
    for gp in graphs:
        found.extend(scan_graph(gp))
    found.sort(key=lambda x: -x[0])
    print(f"=== {len(found)} same-page-different-count pairs (jaccard>=0.5) ===\n")
    for j, a, b, path in found[:25]:
        ua, ub = uids(a), uids(b)
        print(f"jaccard={j:.3f}  {a['state_id'][:12]}({len(ua)}els) vs "
              f"{b['state_id'][:12]}({len(ub)}els)")
        print(f"   graph: {path.parent.parent.parent.parent.name}")
        shared = ua & ub
        only_a = sorted(names(a) - names(b))
        only_b = sorted(names(b) - names(a))
        print(f"   shared uids={len(shared)}  only_in_A_names={only_a[:6]}")
        print(f"   only_in_B_names={only_b[:6]}")
        print()


if __name__ == "__main__":
    main()
