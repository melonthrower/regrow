"""Batch capability extractor over the whole graph (a11y nodes).

For every state_type=='a11y' node that has interactive controls:
  1. a11y supplies the inventory (exact labels + ids), deterministic.
  2. VLM (qwen3.7-plus) groups labels into features, names them, classifies
     shape, and assigns params — judging from the screenshot, no geometric rules.

Also asks the VLM to flag controls that are NOT real settings (tab switchers,
test surfaces, navigation) and combo-boxes whose option set is not statically
available (params_incomplete).

Writes:
  - capability_records.json  (structured, machine-readable)
  - capability_records.txt   (human-readable feature+params listing)

Run:
  export PYTHONPATH='.;OSWorld'
  export DASHSCOPE_API_KEY='...'
  python.exe tools/extract_capabilities.py
"""
import json
import os
import sys

import numpy as np
from PIL import Image

GRAPH = "result_setting_qwen_0603_noopfix/gen_data/Qwen/graphs/0_graph.json"
NODE_DIR = "result_setting_qwen_0603_noopfix/gen_data/Qwen/0/nodes"
OUT_JSON = "result_setting_qwen_0603_noopfix/capability_records.json"
OUT_TXT = "result_setting_qwen_0603_noopfix/capability_records.txt"
INTERACTIVE = {"radio-button", "toggle-button", "check-box", "combo-box", "switch"}
NAV_NAMES = {"Primary Menu", "Search", "Settings"}

PROMPT = """You are extracting the CONFIGURABLE FEATURES of one settings page.

Inputs: (1) a screenshot, (2) interactive controls from the accessibility
tree. Each control has an id, a tag, and an exact label. The labels are
AUTHORITATIVE — reuse them verbatim, never invent or rephrase.

Your job: cluster the controls into features, name each feature, classify its
shape, and give its parameters. Judge grouping from the screenshot's visual
layout (headings, separators, spacing), not the list order.

Shapes:
- "toggle": one on/off control. params = ["on","off"].
- "one_of_n": mutually-exclusive options (radio group / sound scheme / a
  dropdown's choices); pick one. params = the member labels.
- "multi_dimension": ONE feature with several independent sub-groups; use
  sub_groups, each a one_of_n or toggle axis.

Special handling:
- If a control is a combo-box / dropdown whose options are NOT visible in the
  screenshot (only the current value shows), set "params_incomplete": true and
  put the current value (if any) in params.
- If a control is NOT a real setting (e.g. a tab/section switcher, a test
  surface, pure navigation), put it under "non_settings" with a short reason,
  not under features.

Controls (from a11y):
{controls}

Return ONLY JSON, no prose:
{{
  "features": [
    {{"feature": "<name>", "shape": "toggle|one_of_n|multi_dimension",
      "params": ["<verbatim label or on/off>", ...],
      "sub_groups": [{{"dimension": "<axis>", "shape": "...", "params": [...]}}],
      "params_incomplete": false,
      "member_ids": ["<id>", ...]}}
  ],
  "non_settings": [{{"label": "<label>", "reason": "<why>"}}]
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


def parse_json(resp):
    txt = resp.strip()
    if "```" in txt:
        txt = txt.split("```")[1]
        if txt.startswith("json"):
            txt = txt[4:]
        txt = txt.strip()
    return json.loads(txt)


def main():
    d = json.load(open(GRAPH, encoding="utf-8"))
    targets = []
    for n in d["nodes"]:
        if n.get("state_type") != "a11y":
            continue
        rows = controls_of(n)
        if rows:
            targets.append((n, rows))
    print(f"{len(targets)} a11y nodes with controls to process")

    from gui_rewalk.env.gui_gen_agent import GUIGenAgent
    agent = GUIGenAgent(model="Qwen", model_version="qwen3.7-plus",
                        observation_type="screenshot", action_space="gen_data",
                        max_tokens=2500, use_ark=False)

    records = []
    for i, (node, rows) in enumerate(targets, 1):
        sid = node["state_id"]
        listing = "\n".join(f'  - id={r["id"]} tag={r["tag"]} label="{r["label"]}"'
                            for r in rows)
        ss_path = os.path.join(NODE_DIR, sid, "screenshot.png")
        if not os.path.exists(ss_path):
            ss_path = node.get("screenshot_path", "")
        try:
            img = np.array(Image.open(ss_path).convert("RGB"))
        except Exception as e:
            print(f"[{i}/{len(targets)}] {sid[:10]} SKIP (no screenshot: {e})")
            continue
        resp, *_ = agent.predict_mm(PROMPT.format(controls=listing), [img])
        try:
            parsed = parse_json(resp)
        except Exception as e:
            print(f"[{i}/{len(targets)}] {sid[:10]} PARSE-FAIL: {e}")
            parsed = {"features": [], "non_settings": [], "_raw": resp[:500]}
        rec = {
            "state_id": sid,
            "page_description": node.get("page_description", ""),
            "control_count": len(rows),
            "features": parsed.get("features", []),
            "non_settings": parsed.get("non_settings", []),
        }
        if "_raw" in parsed:
            rec["_raw"] = parsed["_raw"]
        records.append(rec)
        nf = len(rec["features"])
        print(f"[{i}/{len(targets)}] {sid[:10]} -> {nf} features | "
              f"{node.get('page_description','')[:40]}")

    json.dump(records, open(OUT_JSON, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    with open(OUT_TXT, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(f"\n● {rec['state_id'][:10]} | {rec['page_description'][:55]}\n")
            for ft in rec["features"]:
                if ft.get("shape") == "multi_dimension":
                    f.write(f'    [multi] {ft.get("feature")}\n')
                    for sg in ft.get("sub_groups", []):
                        f.write(f'        <{sg.get("dimension")}> '
                                f'{sg.get("shape","")}: {sg.get("params")}\n')
                else:
                    inc = " (options incomplete)" if ft.get("params_incomplete") else ""
                    f.write(f'    [{ft.get("shape")}] {ft.get("feature")} '
                            f'-> {ft.get("params")}{inc}\n')
            for ns in rec.get("non_settings", []):
                f.write(f'    (skip: {ns.get("label")} — {ns.get("reason")})\n')
    print(f"\nWrote {OUT_JSON} and {OUT_TXT} ({len(records)} pages)")


if __name__ == "__main__":
    main()
