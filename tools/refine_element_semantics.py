"""D9 Step 1 (Lite) — element semantic backfill.

For each element that has outgoing edges, compose a backfilled
``vlm_actual_function_v2`` from the dst nodes' page_description /
visible_content_summary. Zero LLM cost — pure template aggregation.

Output: diff JSON listing old vs new for human review BEFORE writing
back into graph.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List


def _load_graph(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _node_index(graph: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {n["state_id"]: n for n in graph.get("nodes", []) if n.get("state_id")}


def _is_inferred(link: Dict[str, Any]) -> bool:
    """An edge is inferred if its action.type is 'inferred' (not fact-derived)."""
    action = link.get("action") or {}
    if isinstance(action, dict):
        return action.get("type") == "inferred"
    if isinstance(action, list):
        return all(
            isinstance(a, dict) and a.get("type") == "inferred"
            for a in action
        )
    return False


def _outgoing_index(
    graph: Dict[str, Any],
    skip_inferred: bool = True,
) -> Dict[str, List[Dict[str, Any]]]:
    """Map (src_state_id, element_id) -> list of fact-derived outgoing edges.

    Inferred edges are excluded by default: they were never executed, so
    using their dst as the src element's semantic source would propagate
    speculation, not observation.
    """
    idx: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for L in graph.get("links", []):
        src = L.get("source")
        eid = L.get("element_id")
        if not src or not eid:
            continue
        if skip_inferred and _is_inferred(L):
            continue
        idx[f"{src}::{eid}"].append(L)
    return idx


def _summarize_dst(dst_node: Dict[str, Any]) -> str:
    desc = (dst_node.get("page_description") or "").strip()
    summary = (dst_node.get("visible_content_summary") or "").strip()
    if desc and summary and summary not in desc:
        return f"{desc} ({summary})"
    return desc or summary or ""


def _compose_actual_function(
    edges: List[Dict[str, Any]],
    nodes: Dict[str, Dict[str, Any]],
) -> str:
    """Compose a backfilled actual_function from dst summaries."""
    seen: List[str] = []
    for L in edges:
        dst_id = L.get("target")
        if not dst_id or dst_id == L.get("source"):
            continue
        dst = nodes.get(dst_id)
        if not dst:
            continue
        summary = _summarize_dst(dst)
        if summary and summary not in seen:
            seen.append(summary)
    if not seen:
        return ""
    if len(seen) == 1:
        return f"Opens: {seen[0]}"
    bullets = " | ".join(seen[:3])
    return f"Opens one of: {bullets}"


def backfill(graph_path: Path) -> Dict[str, Any]:
    graph = _load_graph(graph_path)
    nodes = _node_index(graph)
    outgoing = _outgoing_index(graph)

    samples: List[Dict[str, Any]] = []
    counts = {"total_elements": 0, "with_outgoing": 0, "backfilled": 0,
              "skipped_no_dst_summary": 0}

    for src_state, src_node in nodes.items():
        for elem in src_node.get("elements", []):
            counts["total_elements"] += 1
            eid = elem.get("id")
            if not eid:
                continue
            edges = outgoing.get(f"{src_state}::{eid}", [])
            if not edges:
                continue
            counts["with_outgoing"] += 1
            new_fn = _compose_actual_function(edges, nodes)
            if not new_fn:
                counts["skipped_no_dst_summary"] += 1
                continue
            counts["backfilled"] += 1
            samples.append({
                "src_state": src_state[:8],
                "element_id": eid,
                "element_name": elem.get("name"),
                "element_tag": elem.get("tag"),
                "old_vlm_semantic_name": elem.get("vlm_semantic_name"),
                "old_vlm_actual_function": elem.get("vlm_actual_function"),
                "outgoing_edges": [
                    {
                        "label": L.get("element_label"),
                        "dst_state": (L.get("target") or "")[:8],
                        "dst_page": _summarize_dst(nodes.get(L.get("target", ""), {}))[:160],
                    }
                    for L in edges
                ],
                "new_vlm_actual_function_v2": new_fn,
            })

    return {
        "graph_path": str(graph_path),
        "counts": counts,
        "samples": samples,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("graphs", nargs="+", type=Path,
                    help="Paths to 0_graph.json files")
    ap.add_argument("-o", "--output", type=Path, default=Path("refined_labels_diff.json"))
    args = ap.parse_args()

    out: List[Dict[str, Any]] = []
    for gp in args.graphs:
        report = backfill(gp)
        out.append(report)
        c = report["counts"]
        print(f"{gp}")
        print(f"  total_elements={c['total_elements']}  with_outgoing={c['with_outgoing']}  "
              f"backfilled={c['backfilled']}  skipped={c['skipped_no_dst_summary']}")

    with args.output.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nDiff written to: {args.output}")


if __name__ == "__main__":
    main()
