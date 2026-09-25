"""Offline capability-record verifier (a11y-present nodes only).

NOT production code. A throwaway probe to answer one question:
can we already produce decent per-function capability records — in the
owner's 1-5 form (label + shape + params) — from a11y data ALONE,
without trusting vlm_option_value and without the VLM at all?

Method: for each state_type=='a11y' node, take interactive elements
(radio/toggle/checkbox/combo), dedup, group by `actionable_ancestor_name`
(the trustworthy label), and infer control shape from the group structure.

Shapes:
  toggle      : a single toggle/checkbox row            -> params [on, off]
  one_of_n    : a contiguous run of radios w/ distinct labels under one
                visual section -> params = the labels
  multi_group : several one_of_n groups under one feature heading
                (e.g. App Switching = workspace-scope group + monitor-scope group)
Grouping into sections uses y-gaps (radios <~120px apart belong together),
NOT keyword rules (see feedback_no_hardcoded_rules_for_app_boundary).
"""
import json
import sys
from collections import OrderedDict

GRAPH = "result_setting_qwen_0603_noopfix/gen_data/Qwen/graphs/0_graph.json"
INTERACTIVE = {"radio-button", "toggle-button", "check-box", "combo-box", "switch"}
NAV_NAMES = {"Primary Menu", "Search", "Settings"}
Y_GAP = 130  # px; rows farther apart than this start a new section


def load_nodes():
    d = json.load(open(GRAPH, encoding="utf-8"))
    return [n for n in d["nodes"] if n.get("state_type") == "a11y"]


def controls_of(node):
    """Deduped interactive controls with their trustworthy label + y."""
    seen = set()
    rows = []
    for e in node["elements"]:
        if e.get("tag") not in INTERACTIVE:
            continue
        label = (e.get("actionable_ancestor_name") or e.get("name") or "").strip()
        if not label or label in NAV_NAMES:
            continue
        key = (label, e.get("tag"))
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "label": label,
            "tag": e.get("tag"),
            "y": e.get("screen_y", 0),
            "eid": e.get("id"),
            "sel": e.get("actionable_ancestor_selected"),
        })
    rows.sort(key=lambda r: r["y"])
    return rows


def segment(rows):
    """Split rows into y-contiguous sections (no keyword rules)."""
    sections = []
    cur = []
    for r in rows:
        if cur and r["y"] - cur[-1]["y"] > Y_GAP:
            sections.append(cur)
            cur = []
        cur.append(r)
    if cur:
        sections.append(cur)
    return sections


def to_records(rows):
    """Turn segmented control rows into capability records."""
    records = []
    for sec in segment(rows):
        radios = [r for r in sec if r["tag"] == "radio-button"]
        toggles = [r for r in sec if r["tag"] in ("toggle-button", "check-box", "switch")]
        if toggles and not radios:
            for t in toggles:
                records.append({
                    "label": t["label"], "shape": "toggle",
                    "params": ["on", "off"],
                    "current": _cur(t["sel"]),
                    "eids": [t["eid"]],
                })
        elif len(radios) >= 2:
            records.append({
                "label": "<section>", "shape": "one_of_n",
                "params": [r["label"] for r in radios],
                "current": _selected_label(radios),
                "eids": [r["eid"] for r in radios],
            })
        elif len(radios) == 1:
            records.append({
                "label": radios[0]["label"], "shape": "toggle?",
                "params": [radios[0]["label"]], "current": _cur(radios[0]["sel"]),
                "eids": [radios[0]["eid"]],
            })
    return records


def _cur(sel):
    return "?" if sel is None or sel is False else "selected"


def _selected_label(radios):
    sel = [r["label"] for r in radios if r["sel"] is True]
    return sel[0] if sel else "?(none recorded)"


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    nodes = load_nodes()
    total_records = 0
    nodes_with = 0
    for n in nodes:
        if only and not n["state_id"].startswith(only):
            continue
        rows = controls_of(n)
        if not rows:
            continue
        recs = to_records(rows)
        if not recs:
            continue
        nodes_with += 1
        total_records += len(recs)
        pd = (n.get("page_description") or "")[:60]
        print(f"\n=== {n['state_id'][:12]} | {pd} ===")
        for r in recs:
            cur = f" current={r['current']}" if r["current"] != "?" else ""
            if r["shape"] == "one_of_n":
                print(f"  [one_of_n]{cur}")
                for p in r["params"]:
                    print(f"       - {p}")
            else:
                print(f"  [{r['shape']}] {r['label']} -> {r['params']}{cur}")
    print(f"\n---\n{nodes_with} a11y nodes produced records; "
          f"{total_records} capability records total.")


if __name__ == "__main__":
    main()
