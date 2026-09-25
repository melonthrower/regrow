"""D12 — capability designer.

Reads a state graph + per-node llm_unseen_candidates summaries, builds an
LLM-friendly app-map (page summaries + enriched key-elements per page),
and calls Doubao once to produce:

    {
      "page_names": {"<state_id>": "<short page name>"},
      "capabilities": [
         {
           "id": "...", "name": "...", "description": "...",
           "involves_pages": ["<state_id>", ...],
           "key_elements": [
              {"page": "<state_id>", "element_id": "...", "function": "..."}
           ],
           "slots": [{"name": "...", "type": "...", "source": "..."}],
           "trajectory_skeleton": [
              {"page": "<state_id>", "element_id": "...", "executed": true}
           ]
         }
      ]
    }

Design notes (see design/design_decisions.md for the discussion that
led here):

- Uses ``vlm_actual_function`` as the primary semantic field; falls
  back through ``semantic_repair_label`` -> ``vlm_semantic_name`` ->
  ``name`` (D9 priority chain).
- Inferred edges are KEPT (not filtered): they're still semantic
  observations the VLM made from the src side, just unverified. The
  rollout layer is responsible for handling failed predictions.
- Each element is annotated with ``has_outgoing_edge`` /
  ``edge_executed`` / ``predicted_destination`` so the LLM can reason
  about which buttons cross pages and which mutate the current page.
- Page-level prompt input is built per-node and concatenated. Total
  prompt size is bounded; for >~25 nodes call with --batch.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# project path setup so we can import the existing Ark client
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except Exception:
    pass

DEFAULT_MODEL = os.environ.get("ARK_MODEL", "doubao-seed-1-8-251228")


# ---------------------------------------------------------------------------
# Graph loading and per-element semantic resolution
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_function(elem: Dict[str, Any]) -> str:
    """D9 priority chain: vlm_actual_function -> semantic_repair_label
    -> vlm_semantic_name -> name."""
    for k in ("vlm_actual_function", "semantic_repair_label",
              "vlm_semantic_name", "name"):
        v = elem.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""




def _is_inferred(action: Any) -> bool:
    if isinstance(action, dict):
        return action.get("type") == "inferred"
    if isinstance(action, list):
        return all(isinstance(a, dict) and a.get("type") == "inferred"
                   for a in action)
    return False


def _outgoing_index(graph: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """(src_state, element_id) -> list of outgoing links (executed + inferred)."""
    idx: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for L in graph.get("links", []):
        src = L.get("source")
        eid = L.get("element_id")
        if not src or not eid:
            continue
        idx[f"{src}::{eid}"].append(L)
    return idx


def _load_page_summary(node_dir: Path) -> Dict[str, Any]:
    """Pull page_summary / possible_tasks from per-node llm_unseen_candidates.json
    if available."""
    cand = node_dir / "llm_unseen_candidates.json"
    if not cand.exists():
        return {}
    try:
        data = _load_json(cand)
    except Exception:
        return {}
    return {
        "page_summary": data.get("page_summary") or "",
        "possible_tasks": data.get("possible_tasks") or [],
        "needs_scroll": data.get("needs_scroll") or False,
        "has_modal_dialog": data.get("has_modal_dialog") or False,
    }


def _node_short_id(state_id: str) -> str:
    return state_id[:8]


def _build_page_record(
    node: Dict[str, Any],
    out_index: Dict[str, List[Dict[str, Any]]],
    nodes_by_id: Dict[str, Dict[str, Any]],
    base_dir: Path,
) -> Dict[str, Any]:
    state_id = node["state_id"]
    node_dir = base_dir / "nodes" / state_id
    summary = _load_page_summary(node_dir)

    elements_out: List[Dict[str, Any]] = []
    for elem in node.get("elements", []) or []:
        eid = elem.get("id")
        if not eid:
            continue
        edges = out_index.get(f"{state_id}::{eid}", [])
        executed_edges = [e for e in edges if not _is_inferred(e.get("action"))]
        inferred_edges = [e for e in edges if _is_inferred(e.get("action"))]

        predicted_dst: List[str] = []
        for e in (executed_edges or inferred_edges):
            t = e.get("target")
            if t and t != state_id and _node_short_id(t) not in predicted_dst:
                predicted_dst.append(_node_short_id(t))

        category = elem.get("vlm_category") or ""
        interaction = elem.get("vlm_action") or "CLICK"
        current_value = elem.get("vlm_option_value") or elem.get("text") or ""

        elements_out.append({
            "element_id": eid,
            "tag": elem.get("tag") or "",
            "name": elem.get("name") or "",
            "function": _resolve_function(elem),
            "category": category,
            "interaction": interaction,
            "current_value": current_value,
            "has_outgoing_edge": bool(edges),
            "edge_executed": bool(executed_edges),
            "predicted_destination": predicted_dst,
        })

    return {
        "state_id": state_id,
        "short_id": _node_short_id(state_id),
        "page_summary": summary.get("page_summary", ""),
        "possible_tasks": summary.get("possible_tasks", []),
        "needs_scroll": summary.get("needs_scroll", False),
        "has_modal_dialog": summary.get("has_modal_dialog", False),
        "elements": elements_out,
    }


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a GUI capability designer. Given an app-map
(per-page summaries + interactive elements with their VLM-derived
functions and outgoing-edge predictions), design the set of meaningful
USER CAPABILITIES the app exposes.

A CAPABILITY is a goal a real user has when opening the app. Examples
(generic, not specific to any one app): "add a world clock for a city",
"set an alarm for HH:MM with a label", "convert N units from A to B".

Rules:
1. Anchor each capability to ONE OR A FEW pages — typically 1-3
   neighboring pages. NOT every capability ends at the root/home page.
2. Group elements by user intent, not by widget type. A capability
   should bundle the elements a user must touch in sequence to achieve
   the goal.
3. If a capability needs the user to choose / type / pick — declare
   it as a SLOT with name, type, and which element supplies it.
4. For each trajectory step, set "executed" based on the element's
   recorded edge status:
   - has_outgoing_edge=true AND edge_executed=true   -> "executed": true
   - has_outgoing_edge=true AND edge_executed=false  -> "executed": false  (inferred edge)
   - has_outgoing_edge=false                          -> "executed": false  (never tried)
   This signal tells the rollout layer which steps are predictions
   that may fail vs. observed transitions.
5. Avoid trivially-derivable navigation-only capabilities ("click
   World tab"). The atomic capability is the *complete* user task.
6. Give each page a short canonical name (2-4 words, lowercased
   with underscores) that captures its functional role.

Output STRICT JSON with this schema (no prose, no code fences):

{
  "page_names": {"<full_state_id>": "<short_name>"},
  "capabilities": [
    {
      "id": "<snake_case_id>",
      "name": "<human readable>",
      "description": "<1-sentence what the user accomplishes>",
      "involves_pages": ["<full_state_id>", ...],
      "slots": [
        {"name": "<slot>", "type": "<string|number|enum|...>",
         "source": {"page": "<state_id>", "element_id": "<id>"},
         "examples": ["<example1>", "<example2>"]}
      ],
      "key_elements": [
        {"page": "<state_id>", "element_id": "<id>",
         "function": "<short>", "role_in_capability": "<entry|select|confirm|...>"}
      ],
      "trajectory_skeleton": [
        {"page": "<state_id>", "element_id": "<id>",
         "action": "<click|hover|type|...>", "executed": true}
      ]
    }
  ]
}
"""


def _format_app_map(pages: List[Dict[str, Any]]) -> str:
    """Render pages into a compact YAML-ish text the LLM can read."""
    lines: List[str] = []
    for p in pages:
        lines.append(f"# page state_id={p['state_id']}  (short={p['short_id']})")
        lines.append(f"  page_summary: {p['page_summary']}")
        if p["possible_tasks"]:
            lines.append("  possible_tasks:")
            for t in p["possible_tasks"]:
                lines.append(f"    - {t}")
        if p["has_modal_dialog"]:
            lines.append("  has_modal_dialog: true")
        if p["needs_scroll"]:
            lines.append("  needs_scroll: true")
        lines.append("  elements:")
        for e in p["elements"]:
            line = (f"    - id={e['element_id']} tag={e['tag']} "
                    f"name=\"{e['name']}\" "
                    f"category={e['category'] or '-'} "
                    f"interaction={e['interaction']}")
            if e["current_value"]:
                line += f" value=\"{e['current_value']}\""
            if e["has_outgoing_edge"]:
                tag = "executed" if e["edge_executed"] else "inferred"
                dsts = ",".join(e["predicted_destination"]) or "?"
                line += f" -> {tag}->[{dsts}]"
            line += f"\n      function: {e['function']}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _ark_client():
    from volcenginesdkarkruntime import Ark
    return Ark(
        api_key=os.environ.get("API_KEY"),
        base_url=os.environ.get("API_BASE_URL"),
    )


def _call_llm(system: str, user: str, model: str,
              temperature: float = 0.3) -> str:
    client = _ark_client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def _strip_code_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        # remove first fence line
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("graph", type=Path,
                    help="Path to 0_graph.json")
    ap.add_argument("-o", "--output", type=Path,
                    help="Output JSON path (default: <app>_capabilities.json next to graph)")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"LLM model (default: {DEFAULT_MODEL})")
    ap.add_argument("--dump-prompt", type=Path,
                    help="If set, write the assembled prompt to this path "
                         "(for offline review or batching)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Build prompt + dump but skip LLM call")
    args = ap.parse_args()

    graph = _load_json(args.graph)
    nodes_by_id = {n["state_id"]: n for n in graph.get("nodes", [])
                   if n.get("state_id")}
    out_index = _outgoing_index(graph)

    # The per-node files (nodes/<state_id>/) live under
    # gen_data/<model>/<seed>/. Graph file is at
    # gen_data/<model>/graphs/<idx>_graph.json. We need base_dir = the
    # <seed> dir; auto-detect by searching siblings of graphs/ for a
    # 'nodes' folder.
    seed_root_candidate = args.graph.parent.parent  # gen_data/<model>/
    base_dir = None
    if seed_root_candidate.exists():
        for child in seed_root_candidate.iterdir():
            if (child / "nodes").is_dir():
                base_dir = child
                break
    if base_dir is None:
        base_dir = seed_root_candidate

    pages = [
        _build_page_record(n, out_index, nodes_by_id, base_dir)
        for n in graph.get("nodes", [])
        if n.get("state_id")
    ]
    app_map_text = _format_app_map(pages)

    user_prompt = (
        f"App: {graph.get('app_name', 'unknown')}\n"
        f"Total pages: {len(pages)}\n\n"
        f"App map:\n\n{app_map_text}\n\n"
        f"Now design the capabilities."
    )

    if args.dump_prompt:
        args.dump_prompt.write_text(
            f"=== SYSTEM ===\n{SYSTEM_PROMPT}\n\n=== USER ===\n{user_prompt}",
            encoding="utf-8",
        )
        print(f"prompt dumped: {args.dump_prompt}  "
              f"(system+user chars={len(SYSTEM_PROMPT)+len(user_prompt)})")

    if args.dry_run:
        print("dry-run: skipping LLM call")
        return

    print(f"calling {args.model} ... "
          f"(prompt chars={len(SYSTEM_PROMPT)+len(user_prompt)}, "
          f"pages={len(pages)})")
    raw = _call_llm(SYSTEM_PROMPT, user_prompt, args.model)
    cleaned = _strip_code_fence(raw)

    parsed: Optional[Dict[str, Any]]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"WARNING: response is not valid JSON ({e}); writing raw")
        parsed = None

    out_path = args.output or (
        args.graph.parent / f"{graph.get('app_name', 'app')}_capabilities.json"
    )
    payload: Dict[str, Any] = {
        "app_name": graph.get("app_name"),
        "graph_path": str(args.graph),
        "model": args.model,
        "pages_count": len(pages),
        "raw_response": raw,
    }
    if parsed is not None:
        payload["page_names"] = parsed.get("page_names", {})
        payload["capabilities"] = parsed.get("capabilities", [])
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"written: {out_path}")
    if parsed:
        print(f"  capabilities: {len(payload.get('capabilities', []))}")
        for c in payload.get("capabilities", []):
            print(f"    - {c.get('id')}: {c.get('name')}")


if __name__ == "__main__":
    main()
