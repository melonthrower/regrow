"""VLM grouping verifier (a11y supplies the inventory, VLM supplies grouping).

Answers: with a11y giving the exact control labels + the screenshot,
can the VLM correctly group controls into features and judge each
feature's shape (toggle / one_of_n / multi-dimension), WITHOUT any
geometric or keyword heuristics?

a11y is authoritative for: which controls exist + their exact label.
VLM is asked ONLY to: cluster those given labels into features, name
each feature, and classify its shape. The VLM must reuse the provided
labels verbatim (no inventing) — this avoids the vlm_option_value
mislabel problem.

Run:
  export PYTHONPATH='.;OSWorld'
  export DASHSCOPE_API_KEY='...'
  python.exe tools/probe_vlm_grouping.py 66844ead
"""
import json
import os
import sys

import numpy as np
from PIL import Image

GRAPH = "result_setting_qwen_0603_noopfix/gen_data/Qwen/graphs/0_graph.json"
NODE_DIR = "result_setting_qwen_0603_noopfix/gen_data/Qwen/0/nodes"
INTERACTIVE = {"radio-button", "toggle-button", "check-box", "combo-box", "switch"}
NAV_NAMES = {"Primary Menu", "Search", "Settings"}

PROMPT = """You are analyzing a settings page to extract its CONFIGURABLE FEATURES.

I give you (1) a screenshot of the page and (2) a list of interactive
controls detected via the accessibility tree. Each control has an id and an
exact label (the labels are AUTHORITATIVE — reuse them verbatim, never invent
or rephrase).

Your ONLY job: decide which controls belong to the SAME feature, name each
feature, and classify its shape. Use the VISUAL layout in the screenshot
(headings, separators, spacing, alignment) to judge grouping — not the order
of the list.

Shapes:
- "toggle": one on/off switch. params = ["on","off"].
- "one_of_n": a set of mutually-exclusive options (radio group); pick exactly
  one. params = the member labels.
- "multi_dimension": ONE feature that has SEVERAL independent one_of_n
  sub-groups (e.g. a feature configured along two separate axes). Use
  sub_groups, each its own one_of_n.

Controls (from a11y):
{controls}

Return ONLY JSON, no prose:
{{
  "features": [
    {{"feature": "<name>", "shape": "toggle|one_of_n|multi_dimension",
      "params": ["<verbatim label>", ...],          // for toggle/one_of_n
      "sub_groups": [                                  // for multi_dimension only
        {{"dimension": "<what this axis controls>",
          "params": ["<verbatim label>", ...]}}
      ],
      "member_ids": ["<id>", ...]}}
  ]
}}"""


def controls_of(node):
    seen, rows = set(), []
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
        rows.append({"id": e.get("id"), "label": label, "tag": e.get("tag"),
                     "y": e.get("screen_y", 0)})
    rows.sort(key=lambda r: r["y"])
    return rows


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else "66844ead"
    d = json.load(open(GRAPH, encoding="utf-8"))
    node = next(n for n in d["nodes"]
                if n["state_id"].startswith(prefix) and n.get("state_type") == "a11y")
    sid = node["state_id"]
    rows = controls_of(node)
    listing = "\n".join(f'  - id={r["id"]} tag={r["tag"]} label="{r["label"]}"'
                        for r in rows)
    print(f"Node {sid[:12]} | {len(rows)} controls fed to VLM\n{listing}\n")

    ss_path = os.path.join(NODE_DIR, sid, "screenshot.png")
    img = np.array(Image.open(ss_path).convert("RGB"))

    from gui_rewalk.env.gui_gen_agent import GUIGenAgent
    agent = GUIGenAgent(model="Qwen", model_version="qwen3.7-plus",
                        observation_type="screenshot", action_space="gen_data",
                        max_tokens=2000, use_ark=False)
    resp, *_ = agent.predict_mm(PROMPT.format(controls=listing), [img])

    print("=== RAW VLM RESPONSE ===")
    print(resp)
    txt = resp.strip()
    if "```" in txt:
        txt = txt.split("```")[1].lstrip("json").strip()
    try:
        data = json.loads(txt)
    except Exception as e:
        print(f"\n[could not parse JSON: {e}]")
        return
    print("\n=== PARSED FEATURES ===")
    for f in data.get("features", []):
        if f.get("shape") == "multi_dimension":
            print(f'  [multi_dimension] {f["feature"]}')
            for sg in f.get("sub_groups", []):
                print(f'      <{sg.get("dimension")}>: {sg.get("params")}')
        else:
            print(f'  [{f.get("shape")}] {f["feature"]} -> {f.get("params")}')


if __name__ == "__main__":
    main()
