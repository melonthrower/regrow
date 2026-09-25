"""Audit node-merge / identity quality on an ALREADY-BUILT visual graph.

The live identity is pixel-driven: pHash/SSIM picks the nearest candidates, then a
VLM compares two SCREENSHOTS. This offline audit asks the question that pixels
alone can't answer — for every node pair, is the pixel verdict backed by the
page's FUNCTION, or do they merely look alike?

It crosses two signals per node pair:
  * pHash distance of the node screenshots         (the PIXEL signal the engine uses)
  * Jaccard overlap of the node element-name sets  (the FUNCTION signal it does NOT use)

…and classifies the interesting pairs:

  FALSE-SPLIT suspect  function-near but kept as two nodes  -> identity SHOULD have
                       merged them (graph inflated; each extra node is one more
                       frontier target the backtracker can fail on). Includes the
                       D16/D18 "same page, scrolled/data differs -> pixels split"
                       case (function-near, pixel-FAR).
  PIXEL-FRAGILE sibling pixel-near but function-FAR -> genuinely distinct pages the
                       engine can only tell apart by FUNCTION, not pixels. These are
                       the "sibling page sharing app chrome" pairs that make
                       backtrack arrival land on the wrong page. They are the
                       evidence that the identity judge needs functional context.

Usage:
  python tools/audit_node_merge.py <run_dir_with_graph.json> [--px 14]
                                    [--jhigh 0.6] [--jlow 0.25] [--max-examples 12]
Reads node_artifacts/<id>/{screenshot.png,elements.json}. No emulator / network.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
from pathlib import Path

import imagehash
from PIL import Image

_ICON_SUFFIX = re.compile(r"\s*icon$")
_WS = re.compile(r"\s+")
_CLOCKISH = re.compile(r"^(\d{1,2}[:.]\d{2}|\d{1,3}%|am|pm)$")
# generic chrome that is on every page and carries no page-specific function
_CHROME = {"back", "返回", "close", "关闭", "more options", "cancel", "dismiss",
           "navigate up", "go back", "(无名)", ""}


def _shot(run_dir: Path, nid: str):
    for c in (run_dir / "node_artifacts" / nid / "screenshot.png",
              run_dir / "screenshots" / f"{nid}.png"):
        if c.exists():
            return c
    return None


def _elements(run_dir: Path, nid: str):
    p = run_dir / "node_artifacts" / nid / "elements.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _norm(name: str) -> str:
    nm = _WS.sub(" ", str(name or "").strip().lower())
    nm = _ICON_SUFFIX.sub("", nm)
    return nm


def fn_set(els) -> set:
    """The page's function descriptor: the set of distinct, page-specific element
    names (icons collapsed onto their label, generic chrome + status-bar clock
    dropped)."""
    out = set()
    for e in els:
        nm = _norm(e.get("name"))
        if nm in _CHROME or _CLOCKISH.match(nm):
            continue
        out.add(nm)
    return out


def page_title(els) -> str:
    """Best-effort page title: the top-most non-chrome, non-icon text in the title
    band; falls back to the longest such name on the page so the audit output stays
    readable even when the title sits below the band."""
    band, rest = [], []
    for e in els:
        nm = str(e.get("name") or "").strip()
        low = _norm(nm)
        if not nm or low in _CHROME or low.endswith("icon") or _CLOCKISH.match(low):
            continue
        c = e.get("center") or [0, 0]
        bb = e.get("bbox_xywh") or [0, 0, 0, 0]
        y, h = c[1], bb[3]
        if 80 < y < 480:
            band.append((y, -h, nm))
        rest.append(nm)
    if band:
        band.sort()
        return band[0][2]
    return max(rest, key=len) if rest else "(?)"


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--px", type=int, default=14, help="pHash<= => pixel-near")
    ap.add_argument("--jhigh", type=float, default=0.6, help="Jaccard>= => function-near")
    ap.add_argument("--jlow", type=float, default=0.25, help="Jaccard<= => function-far")
    ap.add_argument("--max-examples", type=int, default=12)
    args = ap.parse_args()

    gpath = args.path / "graph.json"
    if not gpath.exists():
        f = list(args.path.rglob("graph.json"))
        gpath = f[0] if f else gpath
    run_dir = gpath.parent
    data = json.loads(gpath.read_text(encoding="utf-8"))
    nodes = [n.get("id") for n in data.get("nodes", [])]
    app = data.get("app_name", run_dir.name)

    ph, fns, titles = {}, {}, {}
    for nid in nodes:
        sp = _shot(run_dir, nid)
        if not sp:
            continue
        try:
            with Image.open(sp) as im:
                ph[nid] = imagehash.phash(im.convert("RGB"))
        except Exception:
            continue
        els = _elements(run_dir, nid)
        fns[nid] = fn_set(els)
        titles[nid] = page_title(els)

    have = [n for n in nodes if n in ph]
    false_split, fragile, ambiguous = [], [], []
    for a, b in itertools.combinations(have, 2):
        d = ph[a] - ph[b]
        j = jaccard(fns[a], fns[b])
        # function-near pair that the graph kept as two nodes => merge was missed
        if j >= args.jhigh:
            false_split.append((j, d, a, b))
        # pixel-near but function-far => genuinely-distinct look-alike sibling
        elif d <= args.px and j <= args.jlow:
            fragile.append((d, j, a, b))
        elif d <= args.px:
            ambiguous.append((d, j, a, b))

    false_split.sort(reverse=True)
    fragile.sort()
    n_far_split = sum(1 for j, d, a, b in false_split if d > args.px)

    print(f"\n===== {app}  ({len(have)} nodes w/ artifacts, {len(nodes)} total) =====")
    print(f"FALSE-SPLIT suspects (function-near, kept as 2 nodes): {len(false_split)}"
          f"   [{n_far_split} of them pixel-FAR = D16/D18 scroll/data split]")
    print(f"PIXEL-FRAGILE siblings (pixel-near, function-far):     {len(fragile)}"
          f"   <- need FUNCTION context to stay distinct (backtrack-confusers)")
    print(f"ambiguous (pixel-near, mid Jaccard):                  {len(ambiguous)}")

    me = args.max_examples
    if false_split:
        print("  -- FALSE-SPLIT suspects (should likely be ONE node) --")
        for j, d, a, b in false_split[:me]:
            tag = "pixel-far" if d > args.px else "pixel-near"
            print(f"    J={j:.2f} pHash{d:>2} [{tag}]  {a[:8]} \"{titles[a][:24]}\""
                  f"  ==  {b[:8]} \"{titles[b][:24]}\"")
    if fragile:
        print("  -- PIXEL-FRAGILE siblings (look identical, different function) --")
        for d, j, a, b in fragile[:me]:
            print(f"    pHash{d:>2} J={j:.2f}  {a[:8]} \"{titles[a][:24]}\""
                  f"  VS  {b[:8]} \"{titles[b][:24]}\"")


if __name__ == "__main__":
    main()
