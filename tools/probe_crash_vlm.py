#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Probe: would a VLM "app-abnormal" self-report mis-judge normal screens?

Before wiring a VLM-based crash/abnormal signal into the collection pipeline,
we need to know its false-positive rate: how often does it cry "abnormal" on a
screen where the target app is actually running fine?  A noisy signal would
throw away good trajectories.

This script replays the PROPOSED production prompt over already-collected step
frames and tabulates verdicts.  The test set is the 20 completed desktop
episodes (which happen to include known wrong-app cases: GIMP->Calc,
inkscape->VLC, Writer->Calc, shotwell->VLC) — so it measures BOTH:
  * false positives  : correct-app frames flagged "abnormal"  (the risk)
  * true  positives  : wrong-app / crashed frames caught       (the value)

Layout consumed (matches the trajectory viewer):
    <root>/<OS>/<date>/<APP>/episodes/<EP>/trajectory.json + step*.png

Run on js1 (has the Qwen/DashScope key):
    cd /data/shenghonghui/GUI-ReWalk-mobile
    PYTHONPATH=.:OSWorld python tools/probe_crash_vlm.py \
        --episodes_root /tmp/crash_probe --out /tmp/crash_probe_result.json
"""

import argparse
import glob
import io
import json
import os
import re
import sys

import numpy as np
from PIL import Image

# ── The proposed production prompt ──────────────────────────────────────────
# This mirrors exactly what we would inject as a self-report instruction.  The
# agent is told which app it is supposed to be operating, sees one screenshot,
# and must classify the screen.  ABNORMAL is deliberately scoped to the failure
# modes the heuristic (_looks_like_crash) misses: crash/error dialogs, the bare
# desktop, or a DIFFERENT app in the foreground.
PROBE_PROMPT = """You are an agent operating the desktop application: "{app}".

Look at the current screenshot and decide the application's state.

Output STRICT JSON, nothing else:
{{"status": "normal" | "abnormal", "kind": "<short tag>", "reason": "<one short sentence>"}}

Use status="abnormal" ONLY when the target application "{app}" is clearly not in
a usable foreground state, i.e. one of:
  - the app crashed or closed (a crash / error / "stopped responding" dialog is shown)
  - the screen is the bare desktop / file manager / login with the app gone
  - a DIFFERENT application is in the foreground instead of "{app}"
For "kind" use one of: crash_dialog, desktop_blank, wrong_app, other.

Use status="normal" for ANY ordinary in-app screen of "{app}", including dialogs,
menus, settings pages, empty documents, loading states, and large view changes.
A big visual transition inside the app is still normal.
"""


def app_from_path(traj_path: str) -> str:
    # .../<APP>/episodes/<EP>/trajectory.json  ->  human-readable app name
    parts = traj_path.replace("\\", "/").split("/")
    try:
        app_dir = parts[parts.index("episodes") - 1]
    except ValueError:
        app_dir = parts[-3]
    return app_dir.replace("_", " ")


def parse_json(text: str):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        return json.loads(text)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes_root", required=True,
                    help="dir holding <OS>/<date>/<APP>/episodes/<EP>/...")
    ap.add_argument("--out", default="/tmp/crash_probe_result.json")
    ap.add_argument("--model", default="Qwen")
    ap.add_argument("--model_version", default="qwen3.7-plus")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap number of frames (0 = all)")
    args = ap.parse_args()

    from gui_rewalk.env.gui_gen_agent import GUIGenAgent
    agent = GUIGenAgent(
        model=args.model, model_version=args.model_version,
        max_tokens=512, top_p=0.9, temperature=0.0,
        action_space="gen_data", observation_type="screenshot",
        enable_ocr=False, max_trajectory_length=0, max_retry=2,
        enable_thinking=False, use_ark=(args.model != "Qwen"))

    trajs = sorted(glob.glob(os.path.join(
        args.episodes_root, "*", "*", "*", "episodes", "*", "trajectory.json")))
    if not trajs:
        # fall back: any trajectory.json under root
        trajs = sorted(glob.glob(os.path.join(
            args.episodes_root, "**", "trajectory.json"), recursive=True))
    print(f"[probe] {len(trajs)} episodes under {args.episodes_root}")

    rows = []
    n_frames = 0
    for tp in trajs:
        app = app_from_path(tp)
        ep_dir = os.path.dirname(tp)
        try:
            traj = json.load(io.open(tp, encoding="utf-8"))
        except Exception as e:
            print(f"[skip] {tp}: {e}")
            continue
        steps = traj.get("steps", []) if isinstance(traj, dict) else traj
        for st in steps:
            frame = st.get("frame", "")
            if not frame:
                continue
            fpath = os.path.join(ep_dir, frame)
            if not os.path.exists(fpath):
                # frames usually live in a screenshots/ subdir; `frame` is bare
                alt = os.path.join(ep_dir, "screenshots", frame)
                if os.path.exists(alt):
                    fpath = alt
                else:
                    continue
            if args.limit and n_frames >= args.limit:
                break
            try:
                img = np.array(Image.open(fpath).convert("RGB"))
            except Exception as e:
                print(f"[skip frame] {fpath}: {e}")
                continue
            prompt = PROBE_PROMPT.format(app=app)
            resp = agent.predict_mm(prompt, [img])
            raw = resp[0] if isinstance(resp, tuple) else resp
            parsed = parse_json(raw) or {}
            status = (parsed.get("status") or "").lower()
            row = {
                "app": app,
                "episode": os.path.basename(ep_dir),
                "frame": frame,
                "step": st.get("step"),
                "status": status,
                "kind": parsed.get("kind", ""),
                "reason": parsed.get("reason", ""),
                "raw": raw if not parsed else "",
            }
            rows.append(row)
            n_frames += 1
            flag = "!!" if status == "abnormal" else "  "
            print(f"{flag} [{app}/{row['episode']}/{frame}] -> {status} "
                  f"({row['kind']}) {row['reason'][:70]}")
        if args.limit and n_frames >= args.limit:
            break

    # ── aggregate ──
    by_app = {}
    for r in rows:
        d = by_app.setdefault(r["app"], {"n": 0, "abnormal": 0, "kinds": {}})
        d["n"] += 1
        if r["status"] == "abnormal":
            d["abnormal"] += 1
            d["kinds"][r["kind"]] = d["kinds"].get(r["kind"], 0) + 1

    total = len(rows)
    abn = sum(1 for r in rows if r["status"] == "abnormal")
    summary = {
        "total_frames": total,
        "abnormal_flagged": abn,
        "abnormal_rate": round(abn / total, 3) if total else 0,
        "by_app": by_app,
    }
    out = {"summary": summary, "rows": rows}
    with io.open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("\n==== SUMMARY ====")
    print(f"frames={total}  abnormal_flagged={abn}  rate={summary['abnormal_rate']}")
    for app, d in sorted(by_app.items()):
        print(f"  {app:24s} {d['abnormal']:>3}/{d['n']:<3} abnormal  {d['kinds']}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
