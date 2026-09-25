"""Verify REGION-SET page identity on already-traversed nodes (2026-07-06 用户:
页面身份=它含的区块id集合; 区块用 RegionRegistry 跨节点分配稳定 rid). Pure.

For each node: group its elements by region role -> (role, name-set); feed every
region into a real RegionRegistry to get a stable rid; the node's identity = the
SET of rids it contains. Then: are all distinct nodes' rid-sets distinct? Does the
false-merge pair (8003097e Thunderbolt vs 80031a6c File History) now differ?

Usage:  python tools/verify_region_set_identity.py [run_dir]
"""
import glob
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from gui_rewalk.src.core.visual_traversal.region_registry import RegionRegistry  # noqa: E402

RUN = sys.argv[1] if len(sys.argv) > 1 else "result_foldcheck7/20260706/setting"


def node_regions(elements):
    """role -> set(names) for this node."""
    reg = defaultdict(set)
    for e in elements:
        r = e.get("region") or "(none)"
        g = (e.get("group") or "").strip().lower()
        nm = ("grp:" + g) if g else (e.get("name") or "").strip()
        if nm:
            reg[r].add(nm)
    return reg


nodes = {}
for p in sorted(glob.glob(os.path.join(RUN, "node_artifacts", "*", "elements.json"))):
    nid = os.path.basename(os.path.dirname(p))[:8]
    nodes[nid] = node_regions(json.load(open(p, encoding="utf-8")))

reg = RegionRegistry()
node_ridset = {}
for nid, regions in nodes.items():
    rids = set()
    for role, names in regions.items():
        rid, _new = reg.register(role, names, node_id=nid)
        rids.add(f"{role}:{rid}")
    node_ridset[nid] = rids

print(f"run: {RUN}  nodes: {len(nodes)}")
print("每节点的 region 集合(role:rid):")
for nid, rids in node_ridset.items():
    print(f"  {nid}: {sorted(rids)}")

# collisions: two DIFFERENT nodes with the SAME region-set = would false-merge
print("\n=== 判定: 不同节点的 region 集合应各不相同 ===")
ids = list(node_ridset)
collide = 0
for i in range(len(ids)):
    for j in range(i + 1, len(ids)):
        a, b = node_ridset[ids[i]], node_ridset[ids[j]]
        same = (a == b)
        if same:
            collide += 1
            print(f"  {ids[i]} vs {ids[j]}: 集合相同 <== 假合并!")
if not collide:
    print("  所有节点 region 集合两两不同 ✓")

# spotlight the old false-merge pair
A, B = "8003097e", "80031a6c"
if A in node_ridset and B in node_ridset:
    shared = node_ridset[A] & node_ridset[B]
    onlyA = node_ridset[A] - node_ridset[B]
    onlyB = node_ridset[B] - node_ridset[A]
    print(f"\n[原假合并对] {A} vs {B}:")
    print(f"  共享区块: {sorted(shared)}")
    print(f"  仅 {A}: {sorted(onlyA)}")
    print(f"  仅 {B}: {sorted(onlyB)}")
    print(f"  → {'相同(仍假合并)' if node_ridset[A]==node_ridset[B] else '不同(假合并消除 ✓)'}")

print("=" * 55)
print("假合并 =", collide, "(必须为 0)")
sys.exit(1 if collide else 0)
