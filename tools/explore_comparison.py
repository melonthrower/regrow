#!/usr/bin/env python3
"""Compare old exploration results with new VLM filter (display category).

For each explored state:
1. Reconstruct what happened: which elements were available, clicked, wasted (self-loop)
2. Re-run VLM with new prompt (containing "display" category) on saved screenshots
3. Compare old vs new classification
4. Generate annotated screenshots + aggregate report

Color convention on annotated screenshots:
  Green  = clicked → productive (led to different state)
  Red    = clicked → self-loop (wasted)
  Blue   = available but not clicked
  Gray   = new VLM classified as "display" (would be skipped)
  Orange = new VLM classified as "shallow"
"""

from __future__ import annotations

import argparse
import base64
import json
import io
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# ── Colors ──────────────────────────────────────────────────────────────────
COLOR_PRODUCTIVE = (40, 180, 40)       # green
COLOR_SELFLOOP   = (220, 40, 40)       # red
COLOR_AVAILABLE  = (60, 120, 220)      # blue
COLOR_DISPLAY    = (140, 140, 140)     # gray
COLOR_SHALLOW    = (240, 160, 30)      # orange
COLOR_DANGEROUS  = (180, 0, 180)       # purple

LEGEND = [
    ("Productive click", COLOR_PRODUCTIVE),
    ("Self-loop (wasted)", COLOR_SELFLOOP),
    ("Available (not clicked)", COLOR_AVAILABLE),
    ("VLM: display (skip)", COLOR_DISPLAY),
    ("VLM: shallow", COLOR_SHALLOW),
    ("VLM: dangerous", COLOR_DANGEROUS),
]

# ── VLM prompt (same as config/prompt.py, with "display") ──────────────────
VLM_PROMPT = """
You are an agent analyzing a {os_type} desktop app page.

You are given:
- A screenshot of the current page.
- A JSON list of framework-provided unseen candidates on this page.

Your goals:
1) Classify EVERY candidate into one of four categories: "navigation", "dangerous", "shallow", or "display".
2) For each candidate, provide the interaction method: CLICK / TYPE / SCROLL.
3) If action is TYPE, provide suggested input text.
4) Provide a short page summary and possible tasks achievable from this page.

CRITICAL classification rules:
- "dangerous": Power Off, Restart, Reboot, Log Out, Suspend, Hibernate, Delete Account,
  Format, Factory Reset, Change Resolution, any action that could shut down, restart,
  or irrevocably alter the OS. These elements must NEVER be clicked.
- "display": Static text labels, headings, descriptions, dates, version numbers, ratings,
  status indicators, or any read-only content that is NOT interactive. Clicking these
  has no effect — they are purely informational and must be skipped.
- "shallow": Toggle switches, on/off buttons, radio buttons, sliders, checkbox filters,
  dropdown value selectors, volume controls — anything that changes a setting value
  in-place without navigating to a new page or dialog.
- "navigation": Everything else — buttons, links, menu items, or list entries that open
  new pages, dialogs, sub-menus, or sections. These are the candidates we want to explore.

Respond in strict JSON:
```json
{{
   "llm_unseen_candidates": [
      {{
         "element_id": "candidate element id (can be empty if unsure)",
         "element_name": "human readable name",
         "bbox": {{"x": 0, "y": 0, "w": 0, "h": 0}},
         "action": "CLICK",
         "text": "",
         "category": "navigation",
         "likely_new_page_score": 0.92,
         "reason": "short reason"
      }}
   ],
   "page_summary": "short summary of current page",
   "possible_tasks": []
}}
```

Important:
- You MUST classify ALL framework candidates. Include dangerous, shallow, and display candidates.
- Always include `bbox` in pixel coordinates.

Framework unseen candidates JSON:
{framework_unseen_json}
"""


def _safe_parse_json(text: str) -> Optional[Dict]:
    if not isinstance(text, str):
        return None
    try:
        t = text.strip()
        if "```json" in t:
            t = t.split("```json", 1)[1]
        if "```" in t:
            t = t.split("```", 1)[0]
        parsed = json.loads(t.strip())
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, IndexError, ValueError):
        return None


def _image_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img_rgb = img.convert("RGB")
    img_rgb.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _call_vlm(
    ark_client,
    model: str,
    prompt_text: str,
    image: Image.Image,
    temperature: float = 0.1,
) -> Tuple[str, int, int]:
    """Call Ark VLM and return (response_text, prompt_tokens, completion_tokens)."""
    b64 = _image_to_base64(image)
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ],
    }]

    for attempt in range(3):
        try:
            resp = ark_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
            )
            text = resp.choices[0].message.content if resp.choices else ""
            pt = getattr(resp.usage, "prompt_tokens", 0)
            ct = getattr(resp.usage, "completion_tokens", 0)
            return text, pt, ct
        except Exception as e:
            wait = 10 * (attempt + 1)
            print(f"  VLM call failed (attempt {attempt+1}): {e}, retry in {wait}s")
            time.sleep(wait)

    return "", 0, 0


def _map_vlm_to_elements(
    vlm_candidates: List[Dict],
    elements: List[Dict],
) -> Dict[str, str]:
    """Map VLM response back to element IDs. Returns {element_id: category}."""
    result: Dict[str, str] = {}

    elem_by_id = {e["id"]: e for e in elements}
    for vc in vlm_candidates:
        cat = (vc.get("category") or "navigation").lower()
        # Try matching by element_id first
        eid = vc.get("element_id", "")
        if eid and eid in elem_by_id:
            result[eid] = cat
            continue
        # Fall back to bbox overlap matching
        vbox = vc.get("bbox", {})
        vx, vy = vbox.get("x", 0), vbox.get("y", 0)
        vw, vh = vbox.get("w", 0), vbox.get("h", 0)
        if vw <= 0 or vh <= 0:
            continue
        best_iou, best_eid = 0, None
        for e in elements:
            ex, ey = e["screen_x"], e["screen_y"]
            ew, eh = e["width"], e["height"]
            ix = max(0, min(vx + vw, ex + ew) - max(vx, ex))
            iy = max(0, min(vy + vh, ey + eh) - max(vy, ey))
            inter = ix * iy
            union = vw * vh + ew * eh - inter
            iou = inter / union if union > 0 else 0
            if iou > best_iou:
                best_iou = iou
                best_eid = e["id"]
        if best_eid and best_iou > 0.3:
            result[best_eid] = cat

    return result


# ── Drawing ─────────────────────────────────────────────────────────────────

def _draw_annotated(
    image: Image.Image,
    groups: List[Tuple[List[Dict], Tuple[int, int, int], str]],
    output_path: str,
    title: str = "",
) -> None:
    """Draw color-coded bounding boxes on image."""
    canvas = image.convert("RGB").copy()
    draw = ImageDraw.Draw(canvas)

    try:
        font = ImageFont.truetype("arial.ttf", 13)
    except Exception:
        font = ImageFont.load_default()

    for items, color, prefix in groups:
        for idx, elem in enumerate(items):
            x = int(elem["screen_x"])
            y = int(elem["screen_y"])
            w = int(elem["width"])
            h = int(elem["height"])
            if w <= 0 or h <= 0:
                continue
            draw.rectangle([x, y, x + w, y + h], outline=color, width=2)
            name = elem.get("name") or elem.get("text") or elem.get("tag", "")
            label = f"{prefix}{idx}:{name[:20]}"
            # Background for readability
            text_bbox = draw.textbbox((x + 2, max(0, y - 15)), label, font=font)
            draw.rectangle(text_bbox, fill=(0, 0, 0, 180))
            draw.text((x + 2, max(0, y - 15)), label, fill=color, font=font)

    # Legend
    ly = 8
    for legend_text, legend_color in LEGEND:
        draw.rectangle([8, ly, 24, ly + 12], fill=legend_color)
        draw.text((28, ly - 1), legend_text, fill=(255, 255, 255), font=font)
        ly += 16

    if title:
        draw.text((8, ly + 4), title, fill=(255, 255, 0), font=font)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    canvas.save(output_path)


# ── Main logic ──────────────────────────────────────────────────────────────

def load_graph(graph_path: str) -> Dict:
    with open(graph_path, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_state(
    state_id: str,
    node: Dict,
    edges: List[Dict],
    node_dir: str,
    screenshot_dir: str,
) -> Dict[str, Any]:
    """Offline analysis of a single state (no VLM call)."""
    actual_edges = [e for e in edges
                    if e["source"] == state_id and e.get("type", "actual") == "actual"]
    self_loops = [e for e in actual_edges if e["target"] == state_id]
    productive = [e for e in actual_edges if e["target"] != state_id]

    # Element IDs that were clicked
    clicked_ids = {e["element_id"] for e in actual_edges}
    selfloop_ids = {e["element_id"] for e in self_loops}
    productive_ids = {e["element_id"] for e in productive}

    elements = node.get("elements", [])
    elem_by_id = {e["id"]: e for e in elements}

    # Load old VLM report if available
    old_vlm_path = os.path.join(node_dir, state_id, "llm_unseen_candidates.json")
    old_vlm = {}
    old_vlm_categories = {}
    if os.path.exists(old_vlm_path):
        with open(old_vlm_path, "r", encoding="utf-8") as f:
            old_vlm = json.load(f)
        for m in old_vlm.get("llm_unseen_candidates_mapped", []):
            cat = (m.get("category") or "navigation").lower()
            fw_id = m.get("mapped_framework_id", "")
            if fw_id:
                old_vlm_categories[fw_id] = cat

    # Classify elements
    productive_elems = [elem_by_id[eid] for eid in productive_ids if eid in elem_by_id]
    selfloop_elems = [elem_by_id[eid] for eid in selfloop_ids if eid in elem_by_id]
    available_elems = [e for e in elements
                       if e["id"] not in clicked_ids]

    return {
        "state_id": state_id,
        "app_name": node.get("app_name", ""),
        "total_elements": len(elements),
        "actual_clicks": len(actual_edges),
        "productive_clicks": len(productive),
        "selfloop_clicks": len(self_loops),
        "productive_elems": productive_elems,
        "selfloop_elems": selfloop_elems,
        "available_elems": available_elems,
        "all_elements": elements,
        "old_vlm_categories": old_vlm_categories,
        "old_vlm_report": old_vlm,
        "selfloop_labels": [e["element_label"] for e in self_loops],
    }


def run_vlm_on_state(
    ark_client,
    model: str,
    screenshot_path: str,
    elements: List[Dict],
    os_type: str = "ubuntu",
) -> Dict[str, str]:
    """Re-run VLM with new prompt. Returns {element_id: category}."""
    if not os.path.exists(screenshot_path):
        print(f"  Screenshot not found: {screenshot_path}")
        return {}

    img = Image.open(screenshot_path).convert("RGB")

    # Build framework candidates in the same format used by traversal.py
    framework_candidates = []
    for e in elements:
        framework_candidates.append({
            "id": e["id"],
            "global_uid": e.get("global_uid", ""),
            "name": e.get("name") or e.get("text") or e.get("tag", ""),
            "tag": e.get("tag", ""),
            "role": e.get("role", ""),
            "is_input_field": bool(e.get("is_input_field", False)),
            "bbox": {
                "x": e.get("screen_x", 0),
                "y": e.get("screen_y", 0),
                "w": e.get("width", 0),
                "h": e.get("height", 0),
            },
        })

    prompt = VLM_PROMPT.format(
        os_type=os_type,
        framework_unseen_json=json.dumps(framework_candidates, ensure_ascii=False, indent=2),
    )

    raw_response, pt, ct = _call_vlm(ark_client, model, prompt, img)
    parsed = _safe_parse_json(raw_response)

    if not parsed:
        print(f"  VLM parse failed, raw len={len(raw_response)}")
        return {}

    vlm_candidates = parsed.get("llm_unseen_candidates", [])
    mapping = _map_vlm_to_elements(vlm_candidates, elements)
    print(f"  VLM: {pt} prompt + {ct} completion tokens, mapped {len(mapping)}/{len(elements)} elements")
    return mapping


def generate_state_report(
    analysis: Dict,
    new_vlm_categories: Dict[str, str],
    screenshot_path: str,
    output_dir: str,
) -> Dict[str, Any]:
    """Generate annotated screenshot and report for one state."""
    sid = analysis["state_id"]

    # Split available elements by new VLM category
    display_elems = []
    shallow_elems = []
    dangerous_elems = []
    nav_elems = []

    for e in analysis["available_elems"]:
        cat = new_vlm_categories.get(e["id"], "navigation")
        if cat == "display":
            display_elems.append(e)
        elif cat == "shallow":
            shallow_elems.append(e)
        elif cat == "dangerous":
            dangerous_elems.append(e)
        else:
            nav_elems.append(e)

    # Also check: among self-loop clicks, would VLM have prevented them?
    prevented_selfloops = []
    kept_selfloops = []
    for e in analysis["selfloop_elems"]:
        cat = new_vlm_categories.get(e["id"], "navigation")
        if cat in ("display", "dangerous"):
            prevented_selfloops.append(e)
        else:
            kept_selfloops.append(e)

    # Draw annotated screenshot
    if os.path.exists(screenshot_path):
        img = Image.open(screenshot_path).convert("RGB")
        groups = [
            (analysis["productive_elems"], COLOR_PRODUCTIVE, "P"),
            (analysis["selfloop_elems"], COLOR_SELFLOOP, "X"),
            (nav_elems, COLOR_AVAILABLE, "N"),
            (display_elems, COLOR_DISPLAY, "D"),
            (shallow_elems, COLOR_SHALLOW, "S"),
            (dangerous_elems, COLOR_DANGEROUS, "!"),
        ]
        title = (
            f"{sid[:8]} | {analysis['productive_clicks']} productive, "
            f"{analysis['selfloop_clicks']} self-loop, "
            f"{len(display_elems)} display, {len(nav_elems)} nav"
        )
        out_img = os.path.join(output_dir, f"{sid[:12]}_comparison.png")
        _draw_annotated(img, groups, out_img, title)
    else:
        out_img = ""

    report = {
        "state_id": sid,
        "app_name": analysis["app_name"],
        "total_elements": analysis["total_elements"],
        "productive_clicks": analysis["productive_clicks"],
        "selfloop_clicks": analysis["selfloop_clicks"],
        "selfloop_labels": analysis["selfloop_labels"],
        "new_vlm_display": len(display_elems),
        "new_vlm_shallow": len(shallow_elems),
        "new_vlm_dangerous": len(dangerous_elems),
        "new_vlm_navigation": len(nav_elems),
        "prevented_selfloops": len(prevented_selfloops),
        "prevented_selfloop_names": [
            e.get("name") or e.get("text") or e.get("tag", "")
            for e in prevented_selfloops
        ],
        "annotated_image": out_img,
    }
    return report


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Compare exploration results with new VLM filter")
    parser.add_argument("--graph", default="result/gen_data/Doubao/graphs/0_graph.json")
    parser.add_argument("--node-dir", default="result/gen_data/Doubao/0/nodes")
    parser.add_argument("--screenshot-dir", default="result/gen_data/Doubao/0/screenshots")
    parser.add_argument("--output-dir", default="logs/explore_comparison")
    parser.add_argument("--model", default="doubao-seed-1-8-251228")
    parser.add_argument("--use-vlm", action="store_true", help="Re-run VLM with new prompt")
    parser.add_argument("--max-vlm-states", type=int, default=10,
                        help="Max states to run VLM on (most interesting first)")
    parser.add_argument("--only-selfloop", action="store_true",
                        help="Only analyze states that have self-loop clicks")
    parser.add_argument("--state-id", default=None,
                        help="Analyze a specific state only")
    args = parser.parse_args()

    # Load .env for API keys
    load_dotenv()
    api_key = os.getenv("API_KEY", "")
    api_base = os.getenv("API_BASE_URL", "")

    # Load graph
    print("Loading graph...")
    g = load_graph(args.graph)
    nodes = {n["id"]: n for n in g["nodes"]}
    links = g["links"]
    print(f"  {len(nodes)} nodes, {len(links)} links")

    # Phase 1: Offline analysis of all states
    print("\n=== Phase 1: Offline Analysis ===")
    analyses: Dict[str, Dict] = {}
    for sid, node in nodes.items():
        analysis = analyze_state(sid, node, links, args.node_dir, args.screenshot_dir)
        analyses[sid] = analysis

    # Filter to interesting states
    if args.state_id:
        interesting = {args.state_id: analyses[args.state_id]} if args.state_id in analyses else {}
    elif args.only_selfloop:
        interesting = {sid: a for sid, a in analyses.items() if a["selfloop_clicks"] > 0}
    else:
        # States with actual clicks
        interesting = {sid: a for sid, a in analyses.items() if a["actual_clicks"] > 0}

    # Sort by selfloop count desc, then by total clicks desc
    sorted_states = sorted(
        interesting.keys(),
        key=lambda s: (interesting[s]["selfloop_clicks"], interesting[s]["actual_clicks"]),
        reverse=True,
    )

    # Print offline summary
    total_productive = sum(a["productive_clicks"] for a in analyses.values())
    total_selfloop = sum(a["selfloop_clicks"] for a in analyses.values())
    total_actual = total_productive + total_selfloop
    print(f"\nOverall: {total_actual} actual clicks = {total_productive} productive + {total_selfloop} self-loop")
    print(f"States with clicks: {len(interesting)}, with self-loops: {sum(1 for a in analyses.values() if a['selfloop_clicks'] > 0)}")

    if total_selfloop > 0:
        print(f"\nSelf-loop details:")
        for sid in sorted_states:
            a = interesting[sid]
            if a["selfloop_clicks"] > 0:
                print(f"  {sid[:8]} ({a['app_name'][:20]}) self-loops={a['selfloop_clicks']}: {a['selfloop_labels']}")

    # Phase 2: VLM re-classification (optional)
    vlm_results: Dict[str, Dict[str, str]] = {}  # {state_id: {elem_id: category}}

    if args.use_vlm:
        if not api_key or not api_base:
            print("\nERROR: --use-vlm requires API_KEY and API_BASE_URL in .env")
            return 1

        from volcenginesdkarkruntime import Ark

        ark_client = Ark(api_key=api_key, base_url=api_base)
        vlm_states = sorted_states[:args.max_vlm_states]
        print(f"\n=== Phase 2: VLM Re-classification ({len(vlm_states)} states) ===")

        for i, sid in enumerate(vlm_states):
            a = interesting[sid]
            screenshot_path = os.path.join(args.screenshot_dir, f"{sid}.png")
            print(f"\n[{i+1}/{len(vlm_states)}] State {sid[:8]} ({a['app_name']}) "
                  f"- {a['total_elements']} elements, {a['selfloop_clicks']} self-loops")

            new_cats = run_vlm_on_state(
                ark_client, args.model, screenshot_path,
                a["all_elements"],
            )
            vlm_results[sid] = new_cats

            # Quick comparison with old VLM
            old_cats = a["old_vlm_categories"]
            if old_cats:
                old_display = sum(1 for v in old_cats.values() if v == "display")
                new_display = sum(1 for v in new_cats.values() if v == "display")
                print(f"  Old VLM display: {old_display}, New VLM display: {new_display}")

    # Phase 3: Generate reports
    os.makedirs(args.output_dir, exist_ok=True)
    print(f"\n=== Phase 3: Generating Reports → {args.output_dir} ===")

    state_reports = []
    for sid in sorted_states:
        a = interesting[sid]
        new_cats = vlm_results.get(sid, {})
        screenshot_path = os.path.join(args.screenshot_dir, f"{sid}.png")

        report = generate_state_report(a, new_cats, screenshot_path, args.output_dir)
        state_reports.append(report)

    # Aggregate
    total_prevented = sum(r["prevented_selfloops"] for r in state_reports)
    aggregate = {
        "total_states_analyzed": len(interesting),
        "total_actual_clicks": total_actual,
        "total_productive": total_productive,
        "total_selfloop": total_selfloop,
        "vlm_states_analyzed": len(vlm_results),
        "total_prevented_selfloops": total_prevented,
        "selfloop_prevention_rate": (
            f"{total_prevented}/{total_selfloop} = "
            f"{total_prevented/total_selfloop*100:.1f}%"
            if total_selfloop > 0 else "N/A"
        ),
        "per_state": state_reports,
    }

    report_path = os.path.join(args.output_dir, "comparison_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(aggregate, f, ensure_ascii=False, indent=2)

    # Print summary
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"States analyzed:         {len(interesting)}")
    print(f"Total actual clicks:     {total_actual}")
    print(f"  Productive:            {total_productive} ({total_productive/total_actual*100:.1f}%)" if total_actual else "")
    print(f"  Self-loop (wasted):    {total_selfloop} ({total_selfloop/total_actual*100:.1f}%)" if total_actual else "")

    if vlm_results:
        # VLM category distribution
        all_new_cats = {}
        for cats in vlm_results.values():
            for cat in cats.values():
                all_new_cats[cat] = all_new_cats.get(cat, 0) + 1
        print(f"\nNew VLM classification across {len(vlm_results)} states:")
        for cat, cnt in sorted(all_new_cats.items(), key=lambda x: -x[1]):
            print(f"  {cat:15s}: {cnt}")
        print(f"\nSelf-loops that would be prevented: {aggregate['selfloop_prevention_rate']}")

    print(f"\nReport: {report_path}")
    print(f"Images: {args.output_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
