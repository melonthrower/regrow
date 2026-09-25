"""Attach to the currently open VM modal and run the REAL visual traversal.

The script never resets, relaunches, or closes the VM.  Open the target modal by
hand first, then run this file.  It enables the same live-status console and the
engine's structured review/debug sink, records every unique perception frame, and
checks that modal tabs are covered before the dialog is dismissed.

Example (GNOME Settings wired-profile dialog)::

    C:\\Users\\Admin\\miniconda3\\envs\\guiwalk\\python.exe \
      tests/test_live_modal_traversal.py \
      --expect-tab Identity --expect-tab IPv4 --expect-tab IPv6 \
      --expect-tab Security --max_actions 6
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set


REPO_ROOT = Path(__file__).resolve().parents[1]
for dependency_root in (REPO_ROOT, REPO_ROOT / "OSWorld"):
    if str(dependency_root) not in sys.path:
        sys.path.insert(0, str(dependency_root))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("visual_traversal.entry")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="附着当前 VM 模态框，运行真实 VisualTraversalEngine 小预算遍历")
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
    p.add_argument("--ocr_engine", default="easyocr",
                   choices=["easyocr", "paddleocr"])
    p.add_argument("--ocr_lang", default="en,ch_sim")
    p.add_argument("--no_ocr", action="store_true")
    p.add_argument("--no_vlm_grounding", dest="vlm_grounding",
                   action="store_false", default=True)
    p.add_argument("--max_states", type=int, default=8)
    p.add_argument("--max_actions", type=int, default=6)
    p.add_argument("--expect-tab", action="append", default=[],
                   help="Expected modal tab label; repeat for every tab")
    p.add_argument("--preflight-only", action="store_true",
                   help="Only verify modal/regions; do not click")
    p.add_argument("--no_live_monitor", dest="live_monitor",
                   action="store_false", default=True)
    p.add_argument("--output_root", default="_scratch")
    p.add_argument("--max_trace_frames", type=int, default=40)
    return p.parse_args()


def _norm(value: str) -> str:
    return " ".join(re.findall(r"[0-9a-z一-鿿]+", (value or "").lower()))


def _matches(label: str, expected: str) -> bool:
    a, b = _norm(label), _norm(expected)
    return bool(a and b and (a in b or b in a))


def setup_live_monitor(log_path: Path, enabled: bool) -> None:
    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(fh)
    logger.info("live log -> %s", log_path)
    if not enabled:
        return
    monitor = REPO_ROOT / "tools" / "live_status.py"
    if not monitor.exists():
        logger.warning("[失败] 实时监视器不存在: %s", monitor)
        return
    kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    try:
        subprocess.Popen([sys.executable, str(monitor), str(log_path)], **kwargs)
        logger.info("live monitor window opened (tools/live_status.py)")
    except Exception as exc:
        logger.warning("[失败] 实时监视器启动失败: %s", exc)


def build(args: argparse.Namespace, out_dir: Path):
    from gui_rewalk.env.desktop_gui_gen_env import DesktopGUIGenEnv
    from gui_rewalk.env.gui_gen_agent import GUIGenAgent
    from gui_rewalk.env.utils import get_yolo_model
    from gui_rewalk.src.core.visual_traversal import visual_filter
    from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualPerception

    visual_filter.SYSTEM_UI_BAND_ENABLED = False
    agent = GUIGenAgent(
        model=args.model, model_version=args.model_version,
        max_tokens=args.max_tokens, temperature=args.temperature,
        enable_thinking=args.enable_thinking)
    yolo = get_yolo_model(args.ocr_model_path)
    perception = VisualPerception(
        yolo, agent=agent, caption_mp=None, use_ocr=not args.no_ocr,
        ocr_engine=args.ocr_engine,
        ocr_languages=[x for x in args.ocr_lang.split(",") if x])
    perception.use_vlm_grounding = args.vlm_grounding

    # Constructor attaches to the running VM.  Deliberately do not call reset().
    env = DesktopGUIGenEnv(
        provider_name=args.vm_provider, path_to_vm=args.path_to_vm,
        action_space=agent.action_space, screen_size=(1920, 1080),
        headless=False, os_type="Ubuntu")
    engine = VisualTraversalEngine(
        env=env, agent=agent, perception=perception, app_name=args.app_name,
        output_root=str(out_dir), max_states=args.max_states,
        max_actions=args.max_actions, region_dedup=True,
        stitch_node_image=False, focus_guard_enabled=True,
        preserve_initial_surface=True)
    return perception, env, engine


def install_perception_trace(perception, out_dir: Path,
                             max_frames: int) -> List[Dict[str, Any]]:
    """Wrap the real perception call and persist its modal decision per frame."""
    frames_dir = out_dir / "trace_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / "modal_trace.jsonl"
    trace: List[Dict[str, Any]] = []
    seen_hashes: Set[str] = set()
    original = perception.detect_and_name

    def traced(screenshot: bytes, *args, **kwargs):
        elements = original(screenshot, *args, **kwargs)
        digest = hashlib.md5(screenshot).hexdigest()
        record = {
            "seq": len(trace), "frame_md5": digest,
            "is_modal": bool(getattr(perception, "last_is_modal", False)),
            "modal_bbox": getattr(perception, "last_window_xywh", None),
            "page": getattr(perception, "last_page_name", None),
            "elements": [e.to_dict() for e in elements],
        }
        trace.append(record)
        with trace_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        if digest not in seen_hashes and len(seen_hashes) < max_frames:
            seen_hashes.add(digest)
            (frames_dir / f"frame_{record['seq']:03d}_{digest[:8]}.png").write_bytes(
                screenshot)
        logger.info("[模态] 感知 #%d modal=%s page=%s bbox=%s elements=%d",
                    record["seq"], record["is_modal"], record["page"],
                    record["modal_bbox"], len(elements))
        return elements

    perception.detect_and_name = traced
    return trace


def tab_members(engine, shot: bytes, elements) -> tuple[List[dict], List[Any]]:
    from gui_rewalk.src.core.visual_traversal.region_registry import (
        assign_elements_to_regions)

    regions = engine._segment_regions_cached(shot)
    regions = engine._stabilize_region_observations(regions, elements)
    mapping = assign_elements_to_regions(elements, regions)
    members = []
    for idx, region in enumerate(regions):
        if region.get("role") == "tab_bar":
            members.extend(mapping.get(idx, []))
    return regions, members


def read_debug_records(path: Path) -> List[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def edge_labels(graph) -> List[str]:
    labels = []
    for _src, _dst, data in graph.graph.edges(data=True):
        label = str(data.get("element_label") or
                    data.get("semantic_description") or "").strip()
        if label:
            labels.append(label)
    return labels


def covered_tabs(expected: Iterable[str], selected: Iterable[str],
                 labels: Iterable[str]) -> Set[str]:
    evidence = list(selected) + list(labels)
    return {tab for tab in expected
            if any(_matches(item, tab) for item in evidence)}


def run(args: argparse.Namespace, out_dir: Path) -> int:
    perception = env = engine = None
    try:
        perception, env, engine = build(args, out_dir)
        trace = install_perception_trace(
            perception, out_dir, args.max_trace_frames)
        logger.info("[取帧] 附着正在运行的 VM；不 reset、不重启应用")
        obs = env._get_obs()
        shot = obs.get("screenshot")
        if not shot:
            logger.error("[失败] 抓不到当前 VM 截图")
            return 2
        (out_dir / "preflight.png").write_bytes(shot)
        elements = perception.detect_and_name(shot)
        is_modal = bool(getattr(perception, "last_is_modal", False))
        regions, tabs = tab_members(engine, shot, elements)
        tab_names = [e.name for e in tabs if (e.name or "").strip()]
        selected = [e.name for e in tabs if getattr(e, "selected", False)]
        expected = list(args.expect_tab) or list(dict.fromkeys(tab_names))
        (out_dir / "preflight.json").write_text(json.dumps({
            "is_modal": is_modal,
            "modal_bbox": getattr(perception, "last_window_xywh", None),
            "regions": regions,
            "tabs": [e.to_dict() for e in tabs],
            "expected_tabs": expected,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("[前检] modal=%s regions=%s tabs=%s selected=%s expected=%s",
                    is_modal, [r.get("role") for r in regions], tab_names,
                    selected, expected)
        if not is_modal:
            logger.error("[失败] 当前画面未识别为应用内模态框；保持 VM 原样")
            return 1
        if args.preflight_only:
            missing_preflight = [
                tab for tab in expected
                if not any(_matches(name, tab) for name in tab_names)
            ]
            ok = not missing_preflight
            if missing_preflight:
                logger.error("[失败] 前检缺少预期页签: %s", missing_preflight)
            logger.info("[通过] 前检完成；未执行点击，产物=%s", out_dir)
            return 0 if ok else 1

        logger.info("[遍历] 启动真实 VisualTraversalEngine：max_states=%d "
                    "max_actions=%d", args.max_states, args.max_actions)
        graph = engine.run(obs)
        labels = edge_labels(graph)
        debug = read_debug_records(out_dir / "_review_debug.jsonl")
        effects = [r for r in debug
                   if r.get("kind") == "event" and r.get("type") == "click_effect"]
        no_effect = [r for r in effects if r.get("verdict") == "no_effect"]
        inconsistent = [r for r in effects
                        if r.get("verdict") == "transitioned_inconsistent"]
        covered = covered_tabs(expected, selected, labels)
        missing = [tab for tab in expected if tab not in covered]
        tab_regions = [r for r in engine.region_registry._regions.values()
                       if r.role == "tab_bar" and r.confirmed]
        modal_closed = any(not row.get("is_modal", False) for row in trace[1:])
        premature_close = modal_closed and bool(missing)

        report = {
            "passed": bool(is_modal and not missing and not premature_close
                           and not no_effect and not inconsistent),
            "initial_modal": is_modal,
            "initial_tabs": tab_names,
            "initial_selected_tabs": selected,
            "expected_tabs": expected,
            "covered_tabs": sorted(covered),
            "missing_tabs": missing,
            "edge_labels": labels,
            "confirmed_tab_regions": [
                {"id": r.id, "names": sorted(r.names),
                 "clicked": sorted(r.clicked), "observations": r.observations}
                for r in tab_regions],
            "modal_closed_during_run": modal_closed,
            "premature_close": premature_close,
            "no_effect_clicks": no_effect,
            "inconsistent_clicks": inconsistent,
            "states": graph.graph.number_of_nodes(),
            "edges": graph.graph.number_of_edges(),
            "stop_reason": getattr(graph, "stop_reason", None),
        }
        (out_dir / "modal_test_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("[证据] edges=%s", labels)
        logger.info("[汇总] covered=%s missing=%s tab_regions=%d "
                    "no_effect=%d inconsistent=%d modal_closed=%s",
                    sorted(covered), missing, len(tab_regions), len(no_effect),
                    len(inconsistent), modal_closed)
        if report["passed"]:
            logger.info("[通过] 模态框真实遍历通过；报告=%s", out_dir / "modal_test_report.json")
            return 0
        logger.error("[失败] 模态框真实遍历未通过；报告=%s", out_dir / "modal_test_report.json")
        return 1
    except Exception as exc:
        logger.exception("[失败] 模态框真实遍历测试异常: %s", exc)
        return 3
    finally:
        # Deliberately do not env.reset()/env.close(): preserve the user's VM.
        logger.info("[汇总] 测试结束；VM 保持当前状态，未 reset/close")


def main() -> int:
    args = parse_args()
    # These environment flags are read at module-import/engine-construction time.
    os.environ["GUIWALK_REVIEW_DEBUG"] = "1"
    os.environ["GUIWALK_REGION_MATCH_DEBUG"] = "1"
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_root) / f"modal_traversal_{stamp}_{os.getpid()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_live_monitor(out_dir / "live.log", args.live_monitor)
    logger.info("[证据] 输出目录: %s", out_dir)
    return run(args, out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
