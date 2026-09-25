"""Scenario-instruction probe (one page): capability records -> effect ->
human-scenario instructions.

Step 1 (deterministic): a11y inventory of the page's controls.
Step 2 (VLM): group into features + shape + params (as verified) AND for each
feature produce an `effect` (what the user concretely achieves) plus scenario
instructions in two styles, with concrete parameter values. Single-function
and one cross-function instruction.

Run:
  export PYTHONPATH='.;OSWorld'
  export DASHSCOPE_API_KEY='...'
  python.exe tools/probe_scenario_instructions.py 66844ead
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

PROMPT = """You are documenting the CONFIGURABLE FEATURES of one settings page,
and writing human-scenario instructions a real user might ask.

Inputs: (1) screenshot, (2) interactive controls from the accessibility tree,
each with id/tag/exact label. Labels are AUTHORITATIVE — reuse verbatim.

PART A — features. Cluster controls into features (judge from the screenshot
layout). For each feature give:
- "feature": name
- "shape": "toggle" (on/off) | "one_of_n" (pick one) | "multi_dimension"
- "params": the option labels (or ["on","off"])
- "effect": in plain user terms, what turning this on / picking each value lets
  the user actually DO or experience. Be concrete and observable.
- "member_ids": the control ids

PART B — instructions. Write instructions in the exact TONE of real GUI-agent
benchmarks (OSWorld). Real examples of the target tone:
  - "I am currently working on a ubuntu system but I do not want the
     notifications to bother me. Can you help me to switch to 'Do not disturb
     mode'?"
  - "My glasses are broken, and I'm having trouble seeing small things clearly.
     Could you help me enlarge the text on my screen so it's easier to read?"
  - "I want to have my computer automatically locked after I leaved. Can you
     help me?"
  - "The volume of my system is too small. Can you help me turn up to the max
     volume?"

Tone rules (STRICT):
- A real user states a CONCRETE desired OUTCOME or situation, then a soft
  request. They do NOT ask the agent which control to use.
- FORBIDDEN phrasings (these leak the agent's-eye view — never produce them):
  "需要开启哪个选项", "应该怎么在设置里调", "该选哪一项", "在哪里设置",
  "which option", "how do I set", "where is the setting". The user does not
  know or care about the control; they describe the goal.
- It is FINE to name the desired end-state ("把窗口拖到边缘能自动分屏",
  "固定成 4 个工作区"). It is NOT fine to ask where/which control achieves it.
- Prefer a first-person situation or motivation when natural ("我经常...",
  "我有两个显示器...", "工作区老是自动变来变去，看着乱").
- Always include the CONCRETE parameter value when relevant ("固定成 4 个",
  not "固定数量").

Two styles each, EACH in BOTH English and Chinese (4 strings per feature):
- "question": situation + soft request, e.g.
  EN: "I keep losing my workspaces when I close windows. Can you make it so I
       always have a fixed set of them?"
  ZH: "我一关窗口工作区就自动没了，能帮我固定住吗？"
- "imperative": a direct task by outcome, e.g.
  EN: "Set a fixed number of 4 workspaces so they stop disappearing."
  ZH: "工作区老是自动增减，帮我固定成 4 个吧。"
The English and Chinese must express the SAME scenario and the SAME concrete
value, in each language's natural phrasing (NOT a word-for-word translation).

Provide one instruction per feature (single-function), PLUS 1-2 cross-function
instructions that combine 2+ features toward ONE concrete goal (still concrete,
still with values, still in this tone, still bilingual).

Controls:
{controls}

Return ONLY JSON:
{{
  "features": [
    {{"feature": "...", "shape": "...", "params": [...], "effect": "...",
      "member_ids": [...],
      "instructions": {{
        "question": {{"en": "...", "zh": "..."}},
        "imperative": {{"en": "...", "zh": "..."}}}}}}
  ],
  "cross_function_instructions": [
    {{"goal": "<concrete goal>", "features_used": ["...","..."],
      "question": {{"en": "...", "zh": "..."}},
      "imperative": {{"en": "...", "zh": "..."}}}}
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


def parse_json(resp):
    txt = resp.strip()
    if "```" in txt:
        txt = txt.split("```")[1]
        if txt.startswith("json"):
            txt = txt[4:]
        txt = txt.strip()
    return json.loads(txt)


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else "66844ead"
    d = json.load(open(GRAPH, encoding="utf-8"))
    node = next(n for n in d["nodes"]
                if n["state_id"].startswith(prefix) and n.get("state_type") == "a11y")
    rows = controls_of(node)
    listing = "\n".join(f'  - id={r["id"]} tag={r["tag"]} label="{r["label"]}"'
                        for r in rows)
    ss = os.path.join(NODE_DIR, node["state_id"], "screenshot.png")
    img = np.array(Image.open(ss).convert("RGB"))

    from gui_rewalk.env.gui_gen_agent import GUIGenAgent
    agent = GUIGenAgent(model="Qwen", model_version="qwen3.7-plus",
                        observation_type="screenshot", action_space="gen_data",
                        max_tokens=3500, use_ark=False)
    resp, *_ = agent.predict_mm(PROMPT.format(controls=listing), [img])
    try:
        data = parse_json(resp)
    except Exception as e:
        print("PARSE FAIL:", e)
        print(resp[:1200])
        return

    print(f"PAGE {node['state_id'][:10]} | {node.get('page_description','')[:50]}\n")
    print("=" * 64)
    for ft in data.get("features", []):
        print(f'\n■ {ft.get("feature")}  [{ft.get("shape")}]')
        print(f'   params : {ft.get("params")}')
        print(f'   effect : {ft.get("effect")}')
        ins = ft.get("instructions", {})
        print(f'   Q: {ins.get("question")}')
        print(f'   I: {ins.get("imperative")}')
    print("\n" + "=" * 64)
    print("CROSS-FUNCTION:")
    for cf in data.get("cross_function_instructions", []):
        print(f'\n● goal: {cf.get("goal")}  (uses: {cf.get("features_used")})')
        print(f'   Q: {cf.get("question")}')
        print(f'   I: {cf.get("imperative")}')


if __name__ == "__main__":
    main()
