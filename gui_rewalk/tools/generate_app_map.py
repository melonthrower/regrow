"""
Generate a structured app map from exploration results.

Reads the graph JSON + per-node VLM analysis artifacts, and outputs a
human-readable app_map.json that describes every page, its elements,
and where each element leads.

Two-phase process:
  1. Programmatic extraction: build raw map from graph + VLM artifacts
  2. LLM refinement: generate concise page names, clean descriptions,
     merge similar elements, fix cross-references

Usage:
    python gui_rewalk/tools/generate_app_map.py \
        --result_dir result_calculator_test/gen_data/Qwen \
        --task_id 0

    # Skip LLM refinement (raw output only):
    python gui_rewalk/tools/generate_app_map.py \
        --result_dir result_calculator_test/gen_data/Qwen \
        --task_id 0 --no_refine
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple


def _load_graph(graph_path: str) -> Dict:
    with open(graph_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_vlm(node_dir: str) -> Optional[Dict]:
    path = os.path.join(node_dir, "llm_unseen_candidates.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _short_page_name(page_summary: str, app_name: str) -> str:
    """Extract a short page name from VLM page_summary."""
    if not page_summary:
        return "Unknown Page"
    # Try to extract key descriptor from common patterns
    # "This is the native Ubuntu Calculator application in Basic mode, ..."
    # "This Preferences window enables users to ..."
    s = page_summary.strip()
    # Remove leading "This is the/a " or "This "
    s = re.sub(r"^This\s+is\s+(the|a|an)\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^This\s+", "", s, flags=re.IGNORECASE)
    # Take up to the first comma or period
    s = re.split(r"[,.]", s)[0].strip()
    # Remove app name prefix if redundant
    # Truncate to reasonable length
    if len(s) > 60:
        s = s[:60].rsplit(" ", 1)[0]
    return s if s else "Unknown Page"


def _build_edge_map(graph_data: Dict) -> Dict[str, List[Dict]]:
    """Build mapping: source_state_id -> [{element_id, element_label, target_state_id, semantic_description}]."""
    edge_map: Dict[str, List[Dict]] = defaultdict(list)
    for edge in graph_data.get("links", []):
        src = edge.get("source", "")
        dst = edge.get("target", "")
        if src == dst:
            continue  # Skip self-loops
        action = edge.get("action", {})
        if isinstance(action, dict) and action.get("type") == "inferred":
            continue  # Skip inferred edges
        edge_map[src].append({
            "element_id": edge.get("element_id", ""),
            "element_label": edge.get("element_label", ""),
            "target": dst,
            "semantic_description": edge.get("semantic_description", ""),
        })
    return dict(edge_map)


def _merge_similar_elements(elements: List[Dict]) -> List[Dict]:
    """Merge elements marked as similar_group into grouped entries."""
    merged = []
    similar_groups: Dict[str, List[Dict]] = defaultdict(list)

    for elem in elements:
        reason = elem.get("_reason", "")
        if "similar_group" in reason:
            # Extract group hint from reason
            # e.g. "similar_group: only one representative needed for number format radio buttons"
            group_hint = reason.split("similar_group:")[-1].strip() if ":" in reason else "similar"
            # Use first few words as group key
            group_key = " ".join(group_hint.split()[:6])
            similar_groups[group_key].append(elem)
        else:
            merged.append(elem)

    # Add grouped entries
    for group_key, members in similar_groups.items():
        names = [m["name"] for m in members]
        # Try to find a collective description
        if len(names) <= 3:
            collective_name = ", ".join(names)
        else:
            collective_name = f"{names[0]}, {names[1]} ... ({len(names)} items)"
        # Use the representative's action if available
        rep = members[0]
        entry = {
            "name": collective_name,
            "count": len(members),
        }
        if "destination" in rep:
            entry["destination"] = rep["destination"]
        elif "action" in rep:
            entry["action"] = rep["action"]
        merged.append(entry)

    return merged


def generate_app_map(result_dir: str, task_id: str) -> Dict:
    """Generate structured app map from exploration results."""
    graph_path = os.path.join(result_dir, "graphs", f"{task_id}_graph.json")
    nodes_dir = os.path.join(result_dir, task_id, "nodes")

    graph_data = _load_graph(graph_path)
    app_name = graph_data.get("app_name", "unknown")
    edge_map = _build_edge_map(graph_data)

    # First pass: build state_id -> page_name mapping
    page_names: Dict[str, str] = {}
    page_summaries: Dict[str, str] = {}
    vlm_cache: Dict[str, Dict] = {}

    for node in graph_data.get("nodes", []):
        state_id = node["state_id"]
        node_dir = os.path.join(nodes_dir, state_id)
        vlm = _load_vlm(node_dir)
        if vlm:
            vlm_cache[state_id] = vlm
            summary = vlm.get("page_summary", "")
            page_summaries[state_id] = summary
            page_names[state_id] = _short_page_name(summary, app_name)
        else:
            page_names[state_id] = f"Page {state_id[:8]}"
            page_summaries[state_id] = ""

    # Deduplicate page names (append index if collision)
    name_counts: Dict[str, int] = defaultdict(int)
    for sid, name in sorted(page_names.items()):
        name_counts[name] += 1
    seen: Dict[str, int] = defaultdict(int)
    for sid in list(page_names.keys()):
        name = page_names[sid]
        if name_counts[name] > 1:
            seen[name] += 1
            page_names[sid] = f"{name} ({seen[name]})"

    # Second pass: build element lists per page
    pages = []
    for node in graph_data.get("nodes", []):
        state_id = node["state_id"]
        vlm = vlm_cache.get(state_id)
        node_local_functions = node.get("node_local_functions", []) or []

        # Build element_id -> edge destination mapping
        elem_destinations: Dict[str, Tuple[str, str]] = {}
        for edge_info in edge_map.get(state_id, []):
            eid = edge_info["element_id"]
            target_id = edge_info["target"]
            target_name = page_names.get(target_id, f"Page {target_id[:8]}")
            desc = edge_info.get("semantic_description", "")
            elem_destinations[eid] = (target_name, desc)

        # Build element list from VLM analysis
        raw_elements = []
        raw_element_ids = set()
        if vlm:
            vlm_elements = vlm.get("llm_unseen_candidates_mapped", [])
            # Also build a set of element IDs that VLM analyzed
            vlm_elem_ids = {e.get("mapped_framework_id", e.get("element_id", "")) for e in vlm_elements}

            for ve in vlm_elements:
                fw_id = ve.get("mapped_framework_id", ve.get("element_id", ""))
                elem_name = ve.get("element_name", "")
                category = ve.get("category", "")
                reason = ve.get("reason", "")

                entry: Dict[str, Any] = {"name": elem_name, "_reason": reason}
                if fw_id:
                    raw_element_ids.add(fw_id)

                if fw_id in elem_destinations:
                    # This element has a known transition to another page
                    dest_name, desc = elem_destinations[fw_id]
                    entry["destination"] = dest_name
                    if desc and "inferred" not in desc:
                        entry["description"] = desc
                elif category == "navigation":
                    # VLM thinks it's navigation but we didn't explore it
                    entry["destination"] = f"(unexplored: {reason[:60]})"
                elif category == "shallow":
                    entry["action"] = reason if reason else elem_name
                elif category == "display" and "similar_group" not in reason:
                    entry["action"] = reason if reason else "display element"
                # display + similar_group will be handled by merge

                raw_elements.append(entry)

            for fn in node_local_functions:
                fw_id = fn.get("element_id", "") or fn.get("mapped_framework_id", "")
                if fw_id and fw_id in raw_element_ids:
                    continue
                name = fn.get("name", "")
                if not name:
                    continue
                raw_elements.append({
                    "name": name,
                    "action": fn.get("reason") or fn.get("action") or name,
                    "_reason": "node_local_function: shallow",
                })
                if fw_id:
                    raw_element_ids.add(fw_id)

            # Check for edges whose elements aren't in VLM analysis
            for edge_info in edge_map.get(state_id, []):
                eid = edge_info["element_id"]
                if eid not in vlm_elem_ids:
                    target_name = page_names.get(edge_info["target"], "")
                    label = edge_info["element_label"]
                    # Extract element name from label like "Click push-button: Preferences"
                    clean_label = re.sub(r"^Click\s+\S+:\s*", "", label)
                    raw_elements.append({
                        "name": clean_label or label,
                        "destination": target_name,
                        "_reason": "",
                    })
        else:
            # No VLM data - use graph node elements + edges
            for fn in node_local_functions:
                name = fn.get("name", "")
                if not name:
                    continue
                raw_elements.append({
                    "name": name,
                    "action": fn.get("reason") or fn.get("action") or name,
                    "_reason": "node_local_function: shallow",
                })
            for edge_info in edge_map.get(state_id, []):
                target_name = page_names.get(edge_info["target"], "")
                label = edge_info["element_label"]
                clean_label = re.sub(r"^Click\s+\S+:\s*", "", label)
                raw_elements.append({
                    "name": clean_label or label,
                    "destination": target_name,
                    "_reason": "",
                })

        # Merge similar groups
        elements = _merge_similar_elements(raw_elements)

        # Clean up internal fields
        for e in elements:
            e.pop("_reason", None)

        page_entry: Dict[str, Any] = {
            "page_name": page_names[state_id],
            "summary": page_summaries.get(state_id, ""),
        }

        if elements:
            page_entry["elements"] = elements

        possible_tasks = []
        if vlm:
            possible_tasks = vlm.get("possible_tasks", [])
        if possible_tasks:
            page_entry["possible_tasks"] = possible_tasks

        pages.append(page_entry)

    return {
        "app": app_name,
        "pages": pages,
    }


_REFINE_PROMPT = """\
You are given a raw "app map" extracted from a GUI exploration of the "{app_name}" application.
Your job is to refine it into a clean, concise app map that a scenario-generation AI can use.

Rules:
1. **page_name**: Generate a SHORT, unique, descriptive name for each page (2-5 words).
   Examples: "Basic Calculator", "Main Menu", "Preferences", "Advanced Mode".
   Do NOT include the app name in the page name unless needed for clarity.
2. **summary**: Keep it to 1 sentence describing what the page is for.
3. **elements**: For each element:
   - "name": Keep the element name concise (the VLM name is usually good).
   - "destination": If the element navigates to another page, use the NEW page_name you assigned.
     If it says "(unexplored: ...)", keep it but shorten the description.
   - "action": If the element performs a page-internal action, describe it in ≤10 words.
     Remove phrases like "no new page opened", "within the current view", etc.
   - If elements are grouped (have "count"), give the group a clear collective name.
4. **possible_tasks**: Keep the most distinct 3-5 tasks per page. Remove duplicates.
5. **Cross-references**: Make sure all "destination" values exactly match a page_name in the output.
6. Output valid JSON only. Same schema as the input.

Raw app map:
{raw_map_json}
"""


def _refine_with_llm(raw_map: Dict, api_key: str, base_url: str, model: str) -> Dict:
    """Use LLM to refine the raw app map into clean output."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)

    prompt = _REFINE_PROMPT.format(
        app_name=raw_map.get("app", "unknown"),
        raw_map_json=json.dumps(raw_map, ensure_ascii=False, indent=2),
    )

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4096,
    )

    text = response.choices[0].message.content.strip()
    # Extract JSON from response (may be wrapped in ```json ... ```)
    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    # Try to find JSON object
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]

    refined = json.loads(text)
    return refined


def main():
    parser = argparse.ArgumentParser(description="Generate app map from exploration results")
    parser.add_argument("--result_dir", required=True, help="Path to result dir (e.g. result_xxx/gen_data/Qwen)")
    parser.add_argument("--task_id", default="0", help="Task ID (default: 0)")
    parser.add_argument("--output", default=None, help="Output path (default: result_dir/app_map.json)")
    parser.add_argument("--no_refine", action="store_true", help="Skip LLM refinement")
    parser.add_argument("--model", default="qwen3.7-plus", help="Qwen model for refinement")
    args = parser.parse_args()

    # Load API config from environment
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    raw_map = generate_app_map(args.result_dir, args.task_id)

    # Save raw map
    raw_output = os.path.join(args.result_dir, "app_map_raw.json")
    with open(raw_output, "w", encoding="utf-8") as f:
        json.dump(raw_map, f, ensure_ascii=False, indent=2)
    print(f"Raw app map saved to: {raw_output}")

    # LLM refinement
    if not args.no_refine and api_key and base_url:
        print("Refining with LLM...")
        try:
            app_map = _refine_with_llm(raw_map, api_key, base_url, args.model)
            print("LLM refinement successful.")
        except Exception as e:
            print(f"LLM refinement failed ({e}), using raw map.")
            app_map = raw_map
    else:
        if not args.no_refine:
            print("No DASHSCOPE_API_KEY set, skipping LLM refinement.")
        app_map = raw_map

    output_path = args.output or os.path.join(args.result_dir, "app_map.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(app_map, f, ensure_ascii=False, indent=2)

    print(f"App map saved to: {output_path}")
    print(f"  App: {app_map.get('app', '?')}")
    print(f"  Pages: {len(app_map.get('pages', []))}")
    for p in app_map.get("pages", []):
        n_elem = len(p.get("elements", []))
        print(f"    - {p.get('page_name', '?')} ({n_elem} elements)")


if __name__ == "__main__":
    main()
