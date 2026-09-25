"""LIVE feasibility eval for visual_stitch: stitched-vs-per-viewport perception.

Launches the settings app on an Android emulator, scroll-captures the home page
frames (top->bottom, mirroring visual_engine._scroll_aggregate's swipe+pHash-
settle loop), stitches them with visual_stitch.stitch_frames, then runs the SAME
perception (YOLO+VLM detect_and_name) on:
  (1) the tall STITCHED composite, and
  (2) each per-viewport frame (union of detections),
and reports element counts + names so we can judge whether perceiving the tall
image ONCE is as complete/accurate as per-viewport (the tall-image downscale /
small-text concern).

Writes everything to --out_dir for human inspection (stitched.png, each frame,
the two SoM images, the two element json lists).

Run on the server (ONE free emulator, NEVER 5554/56/58/60):
  PYTHONPATH=.:OSWorld python tools/live_stitch_eval.py \
      --console_port 5584 --grpc_port 8584 --out_dir /tmp/stitch_eval
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

import numpy as np
from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("live_stitch_eval")

# pHash settle threshold (matches visual_engine.VIEW_STABLE_DISTANCE).
VIEW_STABLE = 4
MAX_SCROLL = 8
PATIENCE = 2


def _phash(shot_bytes):
    import imagehash, io
    return imagehash.phash(Image.open(io.BytesIO(shot_bytes)).convert("RGB"))


def capture_scroll_frames(env):
    """Swipe down from the page top, collecting one settled frame per step until
    the viewport stops changing for PATIENCE swipes or MAX_SCROLL is hit.
    Mirrors visual_engine._scroll_aggregate's frame capture (not its element
    dedup — we keep the raw frames for stitching)."""
    frames = []
    obs = env._get_obs()
    shot = obs.get("screenshot")
    if not shot:
        raise RuntimeError("no initial screenshot")
    frames.append(shot)
    prev = _phash(shot)
    stale = 0
    steps = 0
    while steps < MAX_SCROLL and stale < PATIENCE:
        obs = env.step({"action_type": "SCROLL",
                        "parameters": {"direction": "down", "amount": 1}}, pause=2.0)
        steps += 1
        shot = obs.get("screenshot")
        if not shot:
            break
        v = _phash(shot)
        if (v - prev) <= VIEW_STABLE:
            stale += 1
            prev = v
            continue
        stale = 0
        prev = v
        frames.append(shot)
    log.info("captured %d frames over %d swipes", len(frames), steps)
    # restore to top so we leave the device clean
    for _ in range(steps + 2):
        obs = env.step({"action_type": "SCROLL",
                        "parameters": {"direction": "up", "amount": 1}}, pause=1.0)
        s = obs.get("screenshot")
        if s and (_phash(s) - _phash(frames[0])) <= VIEW_STABLE:
            break
    return frames


def perceive(perception, shot_bytes, label, out_dir):
    """detect_and_name on one image; save SoM + return element dicts."""
    t0 = time.time()
    els = perception.detect_and_name(shot_bytes)
    dt = time.time() - t0
    if perception.last_som_image is not None:
        Image.fromarray(perception.last_som_image).save(
            os.path.join(out_dir, f"som_{label}.png"))
    out = [e.to_dict() for e in els]
    with open(os.path.join(out_dir, f"elements_{label}.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    names = [e.name for e in els if (e.name or "").strip()]
    log.info("[%s] %d elements (%.1fs), %d named: %s", label, len(els), dt,
             len(names), names[:25])
    return els, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--console_port", type=int, required=True)
    ap.add_argument("--grpc_port", type=int, required=True)
    ap.add_argument("--avd_name", default="")
    ap.add_argument("--app_name", default="android_settings")
    ap.add_argument("--model", default="Qwen")
    ap.add_argument("--model_version", default="qwen3.7-plus")
    ap.add_argument("--ocr_model_path",
                    default="OmniParser/weights/icon_detect/model.pt")
    ap.add_argument("--out_dir", default="/tmp/stitch_eval")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    from gui_rewalk.env.gui_gen_agent import GUIGenAgent
    from gui_rewalk.env.android_gui_gen_env import AndroidGUIGenEnv
    from gui_rewalk.env.utils import get_yolo_model
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualPerception
    from gui_rewalk.src.core.visual_traversal import visual_stitch as vs
    from gui_rewalk.src.config.config import ANDROID_DEFAULT_AVD
    from gui_rewalk.src.core.app_lifecycle import startup_reset_app

    agent = GUIGenAgent(model=args.model, model_version=args.model_version,
                        max_tokens=1500, temperature=0.5, use_ark=False)
    agent.reset(log)
    env = AndroidGUIGenEnv(
        avd_name=args.avd_name or ANDROID_DEFAULT_AVD,
        console_port=args.console_port, grpc_port=args.grpc_port,
        action_space=agent.action_space, headless=True)
    yolo = get_yolo_model(args.ocr_model_path)
    perception = VisualPerception(yolo, agent=agent, use_ocr=True,
                                  ocr_languages=["en"])

    env.reset()
    log.info("startup-reset app '%s' ...", args.app_name)
    startup_reset_app(env, args.app_name)
    time.sleep(2)

    # 1) capture scroll frames of the home page
    frames = capture_scroll_frames(env)
    for i, fr in enumerate(frames):
        with open(os.path.join(args.out_dir, f"frame_{i:02d}.png"), "wb") as f:
            f.write(fr)

    # 2) stitch
    res = vs.stitch_frames(frames, debug=True)
    if res is None:
        log.error("stitch returned None")
        return 1
    stitched_png = vs.encode_png(res.image)
    with open(os.path.join(args.out_dir, "stitched.png"), "wb") as f:
        f.write(stitched_png)
    fh, fw = (Image.open(__import__("io").BytesIO(frames[0])).convert("RGB")).size[::-1]
    log.info("STITCH: %d frames -> composite %dx%d (frame %dx%d), "
             "sticky_top=%d sticky_bot=%d",
             len(frames), res.image.shape[1], res.image.shape[0], fw, fh,
             res.sticky_top_h, res.sticky_bot_h)

    # 3) perceive stitched
    log.info("=== perceiving STITCHED composite ===")
    st_els, _ = perceive(perception, stitched_png, "stitched", args.out_dir)

    # 4) perceive each viewport, union the names
    log.info("=== perceiving PER-VIEWPORT frames ===")
    pv_total = 0
    pv_names = set()
    pv_counts = []
    for i, fr in enumerate(frames):
        els, _ = perceive(perception, fr, f"frame{i:02d}", args.out_dir)
        pv_total += len(els)
        pv_counts.append(len(els))
        for e in els:
            n = (e.name or "").strip().lower()
            if n:
                pv_names.add(n)

    st_names = {(e.name or "").strip().lower() for e in st_els if (e.name or "").strip()}

    # 5) compare
    summary = {
        "n_frames": len(frames),
        "composite_h": int(res.image.shape[0]),
        "frame_h": int(fh),
        "sticky_top_h": int(res.sticky_top_h),
        "sticky_bot_h": int(res.sticky_bot_h),
        "stitched_n_elements": len(st_els),
        "stitched_n_named": len(st_names),
        "perviewport_total_elements_with_dup": pv_total,
        "perviewport_per_frame_counts": pv_counts,
        "perviewport_unique_named": len(pv_names),
        "names_only_in_perviewport": sorted(pv_names - st_names)[:40],
        "names_only_in_stitched": sorted(st_names - pv_names)[:40],
        "names_in_both": len(st_names & pv_names),
        "vlm_naming_calls_stitched": 1,
        "vlm_naming_calls_perviewport": len(frames),
    }
    with open(os.path.join(args.out_dir, "comparison.json"), "w",
              encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    log.info("=== COMPARISON ===\n%s",
             json.dumps(summary, ensure_ascii=False, indent=2))
    try:
        env.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
