"""Compare a11y-first vs VLM-first element selection on existing exploration data.

Uses result_logs_0427_v3 (Logs app, 25 nodes, 94 edges) where every node already has:
  - elements.json equivalent (graph node["elements"])  : a11y framework output
  - llm_unseen_candidates.json                          : full VLM result + matching info

For each node we re-derive the actionable set under two policies:

  (A) a11y-first  (current production pathway):
        actionable = framework_unseen_candidates  (a11y-filtered, then VLM keeps non-display/non-dangerous)
                   + vlm_discovered_elements      (VLM elements rescued via bbox-lookup fallback)
      → coords always come from a11y; VLM is only a filter / fallback discoverer.

  (B) VLM-first  (proposed):
        actionable = every llm_unseen_candidates_mapped entry whose category is not
                     'display' and not 'dangerous',
                     coords resolved via mapped_framework_id when match_mode != 'none',
                     otherwise via the same vlm_discovered_elements bbox-lookup result.
      → VLM picks the set; a11y is only a coordinate provider.

The script prints a per-node breakdown plus an aggregate summary so we can see exactly
which elements VLM-first would add or drop compared to current behaviour.

Run:
  python tools/compare_vlm_first.py [result_dir]
defaults to result_logs_0427_v3/gen_data/Doubao/0
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple


DEFAULT_RUN = Path(r"C:\Users\Admin\Desktop\GUI agent\mywork\result_logs_0427_v3\gen_data\Doubao\0")
DROP_CATEGORIES = {"display", "dangerous"}  # what we exclude from "would-click" set


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _bbox_iou(a: Dict[str, float], b: Dict[str, float]) -> float:
    ax1, ay1, aw, ah = a["x"], a["y"], a["w"], a["h"]
    bx1, by1, bw, bh = b["x"], b["y"], b["w"], b["h"]
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(1e-6, aw * ah)
    area_b = max(1e-6, bw * bh)
    return inter / (area_a + area_b - inter + 1e-6)




def _match_by_coord(a: List[Dict[str, Any]], b: List[Dict[str, Any]], tol: float = 25.0) -> Tuple[List[int], List[int], List[Tuple[int, int]]]:
    """Coord-proximity matching, robust to rename/relabel.

    Two elements are 'the same' if their centres are within `tol` pixels.
    Returns (only_a_indices, only_b_indices, matched_pairs).
    """
    used_b = set()
    matched: List[Tuple[int, int]] = []
    only_a: List[int] = []
    for i, ea in enumerate(a):
        best_j, best_d = -1, tol + 1
        for j, eb in enumerate(b):
            if j in used_b:
                continue
            d = ((ea["screen_x"] - eb["screen_x"]) ** 2 + (ea["screen_y"] - eb["screen_y"]) ** 2) ** 0.5
            if d < best_d:
                best_d, best_j = d, j
        if best_j >= 0:
            matched.append((i, best_j))
            used_b.add(best_j)
        else:
            only_a.append(i)
    only_b = [j for j in range(len(b)) if j not in used_b]
    return only_a, only_b, matched


def policy_a11y_first(node_meta: Dict[str, Any], llm_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Reproduce what BFS actually fed into actionable on this node.

    Steps:
      1. Take framework_unseen_candidates (already a11y-filtered).
      2. Drop those whose VLM mapped row is display/dangerous.
         (mapping is keyed by framework id when match_mode == 'id'.)
      3. Append vlm_discovered_elements (the bbox-lookup rescue path).
    """
    framework = llm_data.get("framework_unseen_candidates", [])
    mapped = llm_data.get("llm_unseen_candidates_mapped", [])
    vlm_discovered = llm_data.get("vlm_discovered_elements", []) or []

    cat_by_fwid: Dict[str, str] = {}
    for m in mapped:
        fwid = m.get("mapped_framework_id") or m.get("element_id")
        if fwid and m.get("match_mode") in ("id", "iou"):
            cat_by_fwid[fwid] = (m.get("category") or "").lower()

    out: List[Dict[str, Any]] = []
    for fw in framework:
        cat = cat_by_fwid.get(fw["id"], "")
        if cat in DROP_CATEGORIES:
            continue
        bb = fw["bbox"]
        out.append({
            "name": fw.get("name", ""),
            "tag": fw.get("tag", ""),
            "screen_x": bb["x"] + bb["w"] / 2,
            "screen_y": bb["y"] + bb["h"] / 2,
            "source": "framework",
            "category": cat or "(unfiltered)",
        })
    for v in vlm_discovered:
        out.append({
            "name": v.get("name", ""),
            "tag": v.get("tag", ""),
            "screen_x": v["screen_x"] + v.get("width", 0) / 2,
            "screen_y": v["screen_y"] + v.get("height", 0) / 2,
            "source": "vlm_discovered",
            "category": v.get("vlm_category", ""),
        })
    return out


def policy_vlm_first(node_meta: Dict[str, Any], llm_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """VLM result is the spine. Resolve coords via match info, then bbox-lookup, else VLM bbox.

    Steps:
      1. For every llm_unseen_candidates_mapped row whose category not in display/dangerous:
         - if match_mode in (id, iou), use the mapped framework element's centre;
         - else if vlm_discovered_elements has a bbox-overlap match, use a11y centre from there;
         - else fall back to the VLM-reported bbox centre directly (lower confidence).
    """
    framework = llm_data.get("framework_unseen_candidates", [])
    by_id = {fw["id"]: fw for fw in framework}
    vlm_discovered = llm_data.get("vlm_discovered_elements", []) or []

    out: List[Dict[str, Any]] = []
    for m in llm_data.get("llm_unseen_candidates_mapped", []):
        cat = (m.get("category") or "").lower()
        if cat in DROP_CATEGORIES:
            continue

        name = m.get("element_name", "")
        bb = m.get("bbox") or {"x": 0, "y": 0, "w": 0, "h": 0}
        sx = bb["x"] + bb["w"] / 2
        sy = bb["y"] + bb["h"] / 2
        coord_source = "vlm_bbox"

        mode = m.get("match_mode")
        if mode in ("id", "iou"):
            fwid = m.get("mapped_framework_id")
            fw = by_id.get(fwid)
            if fw:
                fbb = fw["bbox"]
                sx = fbb["x"] + fbb["w"] / 2
                sy = fbb["y"] + fbb["h"] / 2
                coord_source = f"a11y_match({mode})"
        else:
            best_iou, best_v = 0.0, None
            for v in vlm_discovered:
                vb = {"x": v["screen_x"], "y": v["screen_y"], "w": v.get("width", 0), "h": v.get("height", 0)}
                iou = _bbox_iou(bb, vb)
                name_match = (v.get("vlm_element_name", "").strip().lower() == name.strip().lower())
                if (iou > best_iou and iou >= 0.3) or name_match:
                    best_iou, best_v = iou, v
                    if name_match:
                        break
            if best_v is not None:
                sx = best_v["screen_x"] + best_v.get("width", 0) / 2
                sy = best_v["screen_y"] + best_v.get("height", 0) / 2
                coord_source = "a11y_lookup"

        out.append({
            "name": name,
            "tag": m.get("element_id", "")[:8] or "(vlm)",
            "screen_x": sx,
            "screen_y": sy,
            "source": "vlm_first",
            "category": cat,
            "coord_source": coord_source,
            "score": m.get("likely_new_page_score", 0.0),
        })
    return out


def diff_sets(a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """Return (only_in_a, only_in_b, n_common). Uses coord-proximity matching."""
    only_a_idx, only_b_idx, matched = _match_by_coord(a, b)
    return [a[i] for i in only_a_idx], [b[j] for j in only_b_idx], len(matched)


def main(run_dir: Path, filename: str = "llm_unseen_candidates.json") -> int:
    graph_path = run_dir / "../graphs/0_graph.json"
    if not graph_path.exists():
        graph_path = run_dir.parent / "graphs" / "0_graph.json"
    graph = _load_json(graph_path)
    nodes_by_id = {n["state_id"]: n for n in graph["nodes"]}

    nodes_dir = run_dir / "nodes"
    rows: List[Dict[str, Any]] = []
    coord_source_counts: Counter[str] = Counter()
    cat_added_counts: Counter[str] = Counter()

    for sid, node in nodes_by_id.items():
        node_dir = nodes_dir / sid
        llm_path = node_dir / filename
        if not llm_path.exists():
            continue
        llm = _load_json(llm_path)

        a = policy_a11y_first(node, llm)
        b = policy_vlm_first(node, llm)
        only_a, only_b, both = diff_sets(a, b)

        for elem in b:
            coord_source_counts[elem.get("coord_source", "?")] += 1
        for elem in only_b:
            cat_added_counts[elem.get("category", "?")] += 1

        rows.append({
            "sid": sid[:8],
            "n_framework_total": len(llm.get("framework_unseen_candidates", [])),
            "n_vlm_total": len(llm.get("llm_unseen_candidates", [])),
            "n_a11y_first": len(a),
            "n_vlm_first": len(b),
            "delta": len(b) - len(a),
            "only_a11y": only_a,
            "only_vlm": only_b,
            "both": both,
        })

    # ------- print report -------
    print(f"\nRun: {run_dir}")
    print(f"Filename: {filename}")
    print(f"App: {graph.get('app_name', '?')}, nodes: {len(rows)}\n")

    header = f"{'state':<10} {'fw':>4} {'vlm':>4} {'a11y1st':>8} {'vlm1st':>7} {'Δ':>4} {'common':>7}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(f"{r['sid']:<10} {r['n_framework_total']:>4} {r['n_vlm_total']:>4} "
              f"{r['n_a11y_first']:>8} {r['n_vlm_first']:>7} {r['delta']:>+4} {r['both']:>7}")

    total_a = sum(r["n_a11y_first"] for r in rows)
    total_b = sum(r["n_vlm_first"] for r in rows)
    total_only_a = sum(len(r["only_a11y"]) for r in rows)
    total_only_b = sum(len(r["only_vlm"]) for r in rows)

    print("\n--- aggregate ---")
    print(f"actionable (a11y-first):  {total_a}")
    print(f"actionable (vlm-first):   {total_b}")
    print(f"only-in-a11y-first:       {total_only_a}")
    print(f"only-in-vlm-first:        {total_only_b}  (newly explored under VLM-first)")
    print(f"Δ per node (avg):         {(total_b - total_a) / max(1, len(rows)):+.2f}")

    print("\n--- vlm-first coordinate sources ---")
    for src, n in coord_source_counts.most_common():
        print(f"  {src:<20} {n}")

    print("\n--- categories of elements added by vlm-first ---")
    for c, n in cat_added_counts.most_common():
        print(f"  {c:<20} {n}")

    print("\n--- nodes with biggest divergence ---")
    rows.sort(key=lambda r: -abs(r["delta"]))
    for r in rows[:5]:
        print(f"\n[{r['sid']}] a11y-first={r['n_a11y_first']}, vlm-first={r['n_vlm_first']}, common={r['both']}, Δ={r['delta']:+d}")
        if r["only_vlm"]:
            adds = [f"{e['name']!r}({e.get('category','?')})" for e in r["only_vlm"][:6]]
            print(f"  + only in vlm-first: {adds}")
        if r["only_a11y"]:
            drops = [f"{e['name']!r}({e.get('source','?')})" for e in r["only_a11y"][:6]]
            print(f"  - only in a11y-first: {drops}")

    return 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", nargs="?", type=Path, default=DEFAULT_RUN)
    p.add_argument("--filename", default="llm_unseen_candidates.json",
                   help="JSON filename inside each nodes/<sid>/ directory")
    args = p.parse_args()
    sys.exit(main(args.run_dir, args.filename))
