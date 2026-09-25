#!/usr/bin/env python3
"""Probe v2: validate the final structural-identity formula on ALL Android
nodes, focusing on the same-name disambiguation risk.

Signature under test:
    sig = sha256(container_resid_chain[-2:] | name | index_within_container)

Checks:
1. Scroll stability: same logical row keeps sig across the 8/21-element roots.
2. Same-name collision: across ALL nodes, does any sig map to two rows that
   are genuinely different (different container/position)? And do genuinely
   same rows correctly share a sig?
Read-only. Touches no source.
"""
from __future__ import annotations

import glob
import hashlib
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

BASE = Path("result_android_overnight_20260615/gen_data/Qwen/0/nodes")
ST = "https://accessibility.ubuntu.example.org/ns/state"


def _resid(node) -> str:
    return node.get("resource-id", "") or ""


def _short(rid: str) -> str:
    return rid.split("/")[-1] if "/" in rid else rid


def _clickable(node) -> bool:
    return node.get(f"{{{ST}}}sensitive", "false") == "true"


def collect(xml_path: Path):
    root = ET.fromstring(xml_path.read_text(encoding="utf-8", errors="replace"))
    rows = []
    # index counter per container-signature, in document order
    idx_counter = defaultdict(int)

    def rec(node, stack):
        if _clickable(node):
            name = node.get("name", "") or ""
            chain = [_short(_resid(p)) for p in stack if _resid(p)]
            csig = ">".join(chain[-2:])
            i = idx_counter[csig]
            idx_counter[csig] += 1
            plain = hashlib.sha256(f"{csig}|{name}".encode()).hexdigest()[:8]
            indexed = hashlib.sha256(f"{csig}|{name}|i{i}".encode()).hexdigest()[:8]
            rows.append({"name": name, "csig": csig, "idx": i,
                         "plain": plain, "indexed": indexed})
        for ch in list(node):
            rec(ch, stack + [node])

    rec(root, [])
    return rows


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    all_nodes = sorted(glob.glob(str(BASE / "*" / "a11y.xml")))
    print(f"nodes: {len(all_nodes)}")

    # collision test on PLAIN sig (no index) within each node
    same_name_same_container = 0
    examples = []
    for xp in all_nodes:
        rows = collect(Path(xp))
        seen = defaultdict(list)
        for r in rows:
            seen[(r["csig"], r["name"])].append(r)
        for (csig, name), group in seen.items():
            if len(group) > 1 and name:
                same_name_same_container += 1
                if len(examples) < 10:
                    examples.append((Path(xp).parent.name[:8], name[:20], csig[:30], len(group)))

    print(f"\n=== same-name same-container groups (would collide w/o index): {same_name_same_container} ===")
    for nid, name, csig, n in examples:
        print(f"   {nid}  name={name:20s}  container={csig:30s}  count={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
