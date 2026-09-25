#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run the production abnormal-detection prompt over the labeled abnormal-axis
frames (real captures + synthetic crash dialogs) and score sensitivity /
specificity per axis. Filenames encode the ground truth:

    <app>__<expected_status>__<expected_kind>__<tag>.png

Run on js1 (needs the Qwen key):
    cd /data/shenghonghui/GUI-ReWalk-mobile
    PYTHONPATH=.:OSWorld python tools/probe_abnormal_axis.py --frames /tmp/abn_frames
"""

import argparse
import glob
import io
import json
import os

import numpy as np
from PIL import Image

from tools.probe_crash_vlm import PROBE_PROMPT, parse_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="/tmp/abn_frames")
    ap.add_argument("--out", default="/tmp/abn_axis_result.json")
    ap.add_argument("--model", default="Qwen")
    ap.add_argument("--model_version", default="qwen3.7-plus")
    args = ap.parse_args()

    from gui_rewalk.env.gui_gen_agent import GUIGenAgent
    agent = GUIGenAgent(
        model=args.model, model_version=args.model_version,
        max_tokens=512, top_p=0.9, temperature=0.0,
        action_space="gen_data", observation_type="screenshot",
        enable_ocr=False, max_trajectory_length=0, max_retry=2,
        enable_thinking=False, use_ark=(args.model != "Qwen"))

    files = sorted(glob.glob(os.path.join(args.frames, "*.png")))
    print(f"[probe] {len(files)} labeled frames")
    rows = []
    for fp in files:
        base = os.path.basename(fp)[:-4]
        parts = base.split("__")
        if len(parts) < 4:
            print(f"[skip] bad label: {base}")
            continue
        app, exp_status, exp_kind, tag = parts[0], parts[1], parts[2], parts[3]
        # the app the agent THINKS it operates: for a killed/closed frame it is
        # still that app (we are mid-episode of operating it)
        target = {"gimp": "GNU image", "synthgimp": "GNU image",
                  "synthcalc": "calculator", "evince": "document viewer",
                  "desktop": "GNU image"}.get(app, app)
        try:
            img = np.array(Image.open(fp).convert("RGB"))
        except Exception as e:
            print(f"[skip] {fp}: {e}")
            continue
        resp = agent.predict_mm(PROBE_PROMPT.format(app=target), [img])
        raw = resp[0] if isinstance(resp, tuple) else resp
        parsed = parse_json(raw) or {}
        got_status = (parsed.get("status") or "").lower()
        got_kind = parsed.get("kind", "")
        ok = (got_status == exp_status)
        rows.append({
            "frame": base, "target_app": target,
            "expected_status": exp_status, "expected_kind": exp_kind,
            "got_status": got_status, "got_kind": got_kind,
            "correct": ok, "reason": parsed.get("reason", ""),
        })
        mark = "OK " if ok else "XX "
        print(f"{mark}[{base}] exp={exp_status}/{exp_kind} "
              f"got={got_status}/{got_kind} :: {parsed.get('reason','')[:70]}")

    n = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    # sensitivity: abnormal frames correctly flagged
    abn = [r for r in rows if r["expected_status"] == "abnormal"]
    abn_ok = sum(1 for r in abn if r["got_status"] == "abnormal")
    # specificity: normal frames NOT flagged
    nor = [r for r in rows if r["expected_status"] == "normal"]
    nor_ok = sum(1 for r in nor if r["got_status"] == "normal")
    print("\n==== ABNORMAL-AXIS SUMMARY ====")
    print(f"overall correct: {correct}/{n}")
    print(f"sensitivity (caught abnormal): {abn_ok}/{len(abn)}")
    print(f"specificity (passed normal)  : {nor_ok}/{len(nor)}")
    with io.open(args.out, "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "sensitivity": [abn_ok, len(abn)],
                   "specificity": [nor_ok, len(nor)]}, f,
                  ensure_ascii=False, indent=1)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
