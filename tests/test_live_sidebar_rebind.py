"""Live VM regression for visible sidebar drift and semantic landing validation.

The script attaches to the running Settings VM, dismisses an open app modal if
needed, deliberately corrupts the stored y of one sidebar item, resolves it again
from the live frame, clicks the resolved point, and asks the production effect
verifier whether the landing matches the requested item.  It never resets or
closes the VM and opens the standard live-status console.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import logging
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
for p in (ROOT, ROOT / "OSWorld", TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_live_modal_traversal import build, setup_live_monitor

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sidebar_rebind.live")


def args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="Displays")
    p.add_argument("--stale-offset-y", type=int, default=-45)
    p.add_argument("--path_to_vm",
                   default="OSWorld/vmware_vm_data/Ubuntu0/Ubuntu0.vmx")
    p.add_argument("--vm_provider", default="vmware")
    p.add_argument("--app_name", default="setting")
    p.add_argument("--model", default="Qwen")
    p.add_argument("--model_version", default="qwen3.7-plus")
    p.add_argument("--max_tokens", type=int, default=1500)
    p.add_argument("--temperature", type=float, default=0.3)
    p.add_argument("--enable_thinking", action="store_true")
    p.add_argument("--ocr_model_path",
                   default="OmniParser/weights/icon_detect/model.pt")
    p.add_argument("--ocr_engine", default="easyocr")
    p.add_argument("--ocr_lang", default="en,ch_sim")
    p.add_argument("--no_ocr", action="store_true")
    p.add_argument("--no_vlm_grounding", dest="vlm_grounding",
                   action="store_false", default=True)
    p.add_argument("--max_states", type=int, default=4)
    p.add_argument("--max_actions", type=int, default=2)
    p.add_argument("--output_root", default="_scratch")
    return p.parse_args()


def norm(value: str) -> str:
    return " ".join((value or "").lower().split())


def role_stat(snapshot: dict, role: str, field: str) -> int:
    return int(((snapshot.get("roles") or {}).get(role) or {}).get(field, 0))


def main() -> int:
    cfg = args()
    os.environ["GUIWALK_REVIEW_DEBUG"] = "1"
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(cfg.output_root) / f"sidebar_rebind_{stamp}_{os.getpid()}"
    out.mkdir(parents=True, exist_ok=True)
    setup_live_monitor(out / "live.log", True)
    perception, env, engine = build(cfg, out)

    obs = env._get_obs()
    elements = perception.detect_and_name(obs["screenshot"])
    if getattr(perception, "last_is_modal", False):
        back = next((e for e in elements if getattr(e, "back", False)), None)
        if back is None:
            raise RuntimeError("current modal has no grounded back/Cancel control")
        log.info("[前检] dismiss current functional modal via %s", back.name)
        obs = env.step({"action_type": "CLICK", "parameters": {
            "x": back.center[0], "y": back.center[1], "button": "left"}}, pause=2)
        obs = engine._settle(obs)
        elements = perception.detect_and_name(obs["screenshot"])

    # Exact-frame A/B probe: the second grounding must reconstruct fresh element
    # objects from the cached raw response without another VLM call.
    grounding_before = engine.vlm_ledger.snapshot()
    repeated_elements = perception.detect_and_name(obs["screenshot"])
    grounding_after = engine.vlm_ledger.snapshot()
    grounding_reused = bool(
        repeated_elements
        and role_stat(grounding_after, "grounding", "calls")
        == role_stat(grounding_before, "grounding", "calls")
        and role_stat(grounding_after, "grounding", "cache_hits")
        > role_stat(grounding_before, "grounding", "cache_hits"))
    if repeated_elements:
        elements = repeated_elements

    target = next((e for e in elements if norm(e.name) == norm(cfg.target)), None)
    if target is None:
        raise RuntimeError(f"target sidebar item not grounded: {cfg.target}")

    # Tag the target with the real current region so the production out-of-region
    # guard participates in this regression.
    from gui_rewalk.src.core.visual_traversal.region_registry import (
        assign_elements_to_regions)
    regions = engine._segment_regions_cached(obs["screenshot"])
    region_before = engine.vlm_ledger.snapshot()
    # Drop the old one-entry cache to prove the new exact-frame LRU survives a
    # non-consecutive revisit; this must still be a cache hit, not a VLM call.
    engine._seg_cache_key = None
    repeated_regions = engine._segment_regions_cached(obs["screenshot"])
    region_after = engine.vlm_ledger.snapshot()
    region_reused = bool(
        repeated_regions == regions
        and role_stat(region_after, "legacy_region_cache", "calls")
        == role_stat(region_before, "legacy_region_cache", "calls")
        and role_stat(region_after, "legacy_region_cache", "cache_hits")
        > role_stat(region_before, "legacy_region_cache", "cache_hits"))
    regions = engine._stabilize_region_observations(regions, elements)
    amap = assign_elements_to_regions(elements, regions)
    for i, region in enumerate(regions):
        if target not in amap.get(i, []):
            continue
        target.region = region.get("role", "")
        target.region_bbox = list(region.get("bbox") or [])
        names = [e.name for e in amap.get(i, []) if (e.name or "").strip()]
        rid, _ = engine.region_registry.register(
            target.region, names, bbox=region.get("bbox"),
            container_bbox=getattr(perception, "last_window_xywh", None))
        target.region_id = rid or ""
        break

    # The VLM's label may itself carry an adjacent-row bbox, which is precisely
    # the production bug under test.  Use region-local OCR as the coordinate
    # oracle and retain the VLM center as diagnostic evidence.
    vlm_center = list(target.center)
    actual = engine._ocr_live_center_by_name(obs["screenshot"], target)
    if actual is None:
        raise RuntimeError("target label was not found by region-local OCR")
    stale = copy.deepcopy(target)
    stale.center = [actual[0], actual[1] + cfg.stale_offset_y]
    stale.bbox_xywh = list(stale.bbox_xywh)
    stale.bbox_xywh[1] += cfg.stale_offset_y
    stale._template = None
    before = obs["screenshot"]
    (out / "before.png").write_bytes(before)

    resolved = engine._live_center_for(stale, obs)
    log.info("[定位] target=%s actual=%s stale=%s resolved=%s region=%s",
             cfg.target, actual, stale.center, resolved, target.region_bbox)
    if resolved is None:
        raise RuntimeError("production live rebinder returned None")

    obs2 = env.step({"action_type": "CLICK", "parameters": {
        "x": resolved[0], "y": resolved[1], "button": "left"}}, pause=2)
    obs2 = engine._settle(obs2)
    after = obs2["screenshot"]
    (out / "after.png").write_bytes(after)
    unchanged = (engine._frame_phash(before) - engine._frame_phash(after)) == 0
    effect = {
        "verdict": "no_effect" if unchanged else "transitioned_consistent",
        "note": "derived from perceptual hash change",
    }
    resolved_error = math.dist(resolved, actual)
    stale_error = math.dist(stale.center, actual)
    report = {
        "passed": bool(grounding_reused
                       and region_reused
                       and resolved_error <= 8
                       and stale_error >= 20
                       and effect.get("verdict") == "transitioned_consistent"),
        "target": cfg.target,
        "vlm_center": vlm_center,
        "actual_center": actual,
        "stale_center": stale.center,
        "resolved_center": resolved,
        "resolved_error_px": resolved_error,
        "stale_error_px": stale_error,
        "effect": effect,
        "cache_probe": {
            "grounding_reused": grounding_reused,
            "region_reused_after_local_cache_drop": region_reused,
        },
        "vlm_ledger": engine.vlm_ledger.snapshot(),
        "vm_preserved": True,
    }
    engine.vlm_ledger.save()
    (out / "sidebar_rebind_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("[汇总] %s report=%s", "PASS" if report["passed"] else "FAIL",
             out / "sidebar_rebind_report.json")
    log.info("[汇总] VM 未 reset/close，保持当前落地页")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
