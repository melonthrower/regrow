#!/usr/bin/env python3
"""Detect same-page splits in a desktop (VS Code) archive: two distinct
state-ids whose element-name sets are near-identical (jaccard>0.8) indicate
the coordinate-zone identity split one logical page into multiple nodes —
the same pathology we confirmed on Android. Read-only.
"""
import json
import os
import glob
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

B = "result_vscode_0611_fix/gen_data/Qwen/0/nodes"
nodes = {}
for ej in glob.glob(os.path.join(B, "*", "elements.json")):
    sid = os.path.basename(os.path.dirname(ej))
    els = json.load(open(ej, encoding="utf-8", errors="replace"))
    names = frozenset(
        (e.get("name") or "").strip() for e in els if (e.get("name") or "").strip()
    )
    nodes[sid] = names

print("vscode nodes:", len(nodes))
sids = list(nodes)
splits = 0
for i in range(len(sids)):
    for j in range(i + 1, len(sids)):
        a, b2 = nodes[sids[i]], nodes[sids[j]]
        if not a or not b2:
            continue
        inter = len(a & b2)
        uni = len(a | b2)
        if uni and inter / uni > 0.8 and a != b2:
            splits += 1
            if splits <= 8:
                print(f"  POSSIBLE SPLIT {sids[i][:8]} vs {sids[j][:8]}  "
                      f"jaccard={inter/uni:.2f}  sizes={len(a)},{len(b2)}")
print("possible same-page splits (jaccard>0.8, not identical):", splits)
