#!/usr/bin/env python3
"""Offline probe: test whether a STRUCTURAL identity (container resource-id
chain + index-within-container + name) is stable across scroll, unlike the
current screen-coordinate `zone`-based global_uid.

Reads real a11y.xml from overnight run's three root states and compares the
structural signature of rows that DID drift uid under the coordinate scheme
(Network, Apps). No source code is touched. Pure read-only verification.
"""
from __future__ import annotations

import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path("result_android_overnight_20260615/gen_data/Qwen/0/nodes")
ROOTS = ["4ea30233325a74c0", "a8a82dd728a11cc6", "aa5854c695f678c3"]

ST = "https://accessibility.ubuntu.example.org/ns/state"
COMP = "https://accessibility.ubuntu.example.org/ns/component"


def _is_clickable(node) -> bool:
    """A row is interactive if sensitive (clickable) per converter mapping."""
    return node.get(f"{{{ST}}}sensitive", "false") == "true"


def _resid(node) -> str:
    return node.get("resource-id", "") or ""


def _short_resid(rid: str) -> str:
    # com.android.settings:id/settings_homepage_container -> settings_homepage_container
    return rid.split("/")[-1] if "/" in rid else rid


def structural_sig(path_stack, node) -> str:
    """Container resource-id chain (nearest scrollable/list/container ancestors)
    + index-within-nearest-named-container + element name.

    Crucially: NO screen coordinates. Stable across any scroll direction.
    """
    name = node.get("name", "") or ""
    # nearest ancestor that has a resource-id = the container the row lives in
    container_chain = [
        _short_resid(_resid(p)) for p in path_stack if _resid(p)
    ]
    # keep last 2 container ids (immediate + grandparent) for disambiguation
    container_sig = ">".join(container_chain[-2:])
    raw = f"{container_sig}|{name}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8], container_sig


def walk(root):
    """Yield (clickable_node, structural_signature, container_sig, name)."""
    results = []

    def rec(node, stack):
        if _is_clickable(node):
            sig, csig = structural_sig(stack, node)
            results.append((sig, csig, node.get("name", "") or ""))
        for child in list(node):
            rec(child, stack + [node])

    rec(root, [])
    return results


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    per_root = {}
    for sid in ROOTS:
        xml_path = BASE / sid / "a11y.xml"
        if not xml_path.exists():
            print(f"MISSING {xml_path}")
            continue
        root = ET.fromstring(xml_path.read_text(encoding="utf-8", errors="replace"))
        rows = walk(root)
        per_root[sid] = rows
        print(f"=== {sid[:8]}  clickable rows: {len(rows)} ===")
        for sig, csig, name in rows:
            print(f"   sig={sig}  container={csig[:45]:45s}  name={name[:30]}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
