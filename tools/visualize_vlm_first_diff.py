"""Render side-by-side annotated screenshots: a11y-first (left) vs VLM-first (right).

For each node in the run, draws bboxes with this colour scheme:

    green  = element selected only under that policy (the "diff")
    blue   = element selected under both policies (common)
    dashed = (VLM-first panel only) coords come from VLM bbox itself, not a11y
             — i.e. the click position is less reliable

Output: <run_dir>/../vlm_first_diff/<state_id>.png

Run:
  python tools/visualize_vlm_first_diff.py [run_dir]
defaults to result_logs_0427_v3/gen_data/Doubao/0
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

# Reuse policy logic so both scripts stay in sync.
sys.path.insert(0, str(Path(__file__).parent))
from compare_vlm_first import (  # noqa: E402
    DEFAULT_RUN,
    DROP_CATEGORIES,
    _bbox_iou,
    _match_by_coord,
)


COLOR_COMMON = (60, 130, 255)   # blue  — present under both policies
COLOR_DIFF = (50, 200, 80)      # green — only under this panel's policy


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _font(size: int = 14) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def policy_a11y_first(llm: Dict[str, Any]) -> List[Dict[str, Any]]:
    """As in compare_vlm_first, but keep bbox so we can draw it."""
    framework = llm.get("framework_unseen_candidates", [])
    mapped = llm.get("llm_unseen_candidates_mapped", [])
    vlm_discovered = llm.get("vlm_discovered_elements", []) or []

    cat_by_fwid: Dict[str, str] = {}
    for m in mapped:
        fwid = m.get("mapped_framework_id") or m.get("element_id")
        if fwid and m.get("match_mode") in ("id", "iou"):
            cat_by_fwid[fwid] = (m.get("category") or "").lower()

    out: List[Dict[str, Any]] = []
    for fw in framework:
        cat = cat_by_fwid.get(fw["id"], "")
        if cat in DROP_CATEGORIES:
            continue
        bb = fw["bbox"]
        out.append({
            "name": fw.get("name", ""),
            "x": bb["x"], "y": bb["y"], "w": bb["w"], "h": bb["h"],
            "screen_x": bb["x"] + bb["w"] / 2,
            "screen_y": bb["y"] + bb["h"] / 2,
            "category": cat or "(unfiltered)",
            "coord_source": "a11y_match",
        })
    for v in vlm_discovered:
        out.append({
            "name": v.get("name", ""),
            "x": v["screen_x"], "y": v["screen_y"],
            "w": v.get("width", 0), "h": v.get("height", 0),
            "screen_x": v["screen_x"] + v.get("width", 0) / 2,
            "screen_y": v["screen_y"] + v.get("height", 0) / 2,
            "category": v.get("vlm_category", ""),
            "coord_source": "a11y_lookup",
        })
    return out


def policy_vlm_first(llm: Dict[str, Any]) -> List[Dict[str, Any]]:
    framework = llm.get("framework_unseen_candidates", [])
    by_id = {fw["id"]: fw for fw in framework}
    vlm_discovered = llm.get("vlm_discovered_elements", []) or []

    out: List[Dict[str, Any]] = []
    for m in llm.get("llm_unseen_candidates_mapped", []):
        cat = (m.get("category") or "").lower()
        if cat in DROP_CATEGORIES:
            continue

        name = m.get("element_name", "")
        bb = m.get("bbox") or {"x": 0, "y": 0, "w": 0, "h": 0}
        x, y, w, h = bb["x"], bb["y"], bb["w"], bb["h"]
        coord_source = "vlm_bbox"

        mode = m.get("match_mode")
        if mode in ("id", "iou"):
            fwid = m.get("mapped_framework_id")
            fw = by_id.get(fwid)
            if fw:
                fbb = fw["bbox"]
                x, y, w, h = fbb["x"], fbb["y"], fbb["w"], fbb["h"]
                coord_source = f"a11y_match({mode})"
        else:
            best_iou, best_v = 0.0, None
            for v in vlm_discovered:
                vb = {"x": v["screen_x"], "y": v["screen_y"], "w": v.get("width", 0), "h": v.get("height", 0)}
                iou = _bbox_iou(bb, vb)
                name_match = (v.get("vlm_element_name", "").strip().lower() == name.strip().lower())
                if (iou > best_iou and iou >= 0.3) or name_match:
                    best_iou, best_v = iou, v
                    if name_match:
                        break
            if best_v is not None:
                x = best_v["screen_x"]
                y = best_v["screen_y"]
                w = best_v.get("width", 0)
                h = best_v.get("height", 0)
                coord_source = "a11y_lookup"

        out.append({
            "name": name,
            "x": x, "y": y, "w": w, "h": h,
            "screen_x": x + w / 2,
            "screen_y": y + h / 2,
            "category": cat,
            "coord_source": coord_source,
            "score": m.get("likely_new_page_score", 0.0),
        })
    return out


def _draw_dashed_rect(draw: ImageDraw.ImageDraw, xy: Tuple[int, int, int, int],
                      color: Tuple[int, int, int], width: int = 3, dash: int = 8) -> None:
    x0, y0, x1, y1 = xy
    for x in range(x0, x1, dash * 2):
        draw.line([(x, y0), (min(x + dash, x1), y0)], fill=color, width=width)
        draw.line([(x, y1), (min(x + dash, x1), y1)], fill=color, width=width)
    for y in range(y0, y1, dash * 2):
        draw.line([(x0, y), (x0, min(y + dash, y1))], fill=color, width=width)
        draw.line([(x1, y), (x1, min(y + dash, y1))], fill=color, width=width)


def _annotate(base: Image.Image, elems: List[Dict[str, Any]],
              is_diff_idx: set, label: str, only_count: int, total: int) -> Image.Image:
    img = base.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    font = _font(13)
    title_font = _font(20)

    for i, e in enumerate(elems):
        x0, y0 = int(e["x"]), int(e["y"])
        x1, y1 = x0 + max(2, int(e["w"])), y0 + max(2, int(e["h"]))
        color = COLOR_DIFF if i in is_diff_idx else COLOR_COMMON
        dashed = e.get("coord_source") == "vlm_bbox"
        if dashed:
            _draw_dashed_rect(draw, (x0, y0, x1, y1), color, width=3)
        else:
            draw.rectangle([x0, y0, x1, y1], outline=color, width=3)

        text = (e["name"] or "<noname>")
        if len(text) > 28:
            text = text[:27] + "…"
        try:
            tb = draw.textbbox((0, 0), text, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        except AttributeError:
            tw, th = font.getsize(text)
        ty = max(0, y0 - th - 2)
        draw.rectangle([x0, ty, x0 + tw + 4, ty + th + 2], fill=color + (220,))
        draw.text((x0 + 2, ty), text, fill=(255, 255, 255), font=font)

    # banner
    banner_h = 40
    bar = Image.new("RGB", (img.width, banner_h), (30, 30, 30))
    bd = ImageDraw.Draw(bar)
    bd.text((10, 8), f"{label}  —  total={total}, unique-to-this-side={only_count}",
            fill=(255, 255, 255), font=title_font)
    out = Image.new("RGB", (img.width, img.height + banner_h), (30, 30, 30))
    out.paste(bar, (0, 0))
    out.paste(img, (0, banner_h))
    return out


def render_node(screenshot_path: Path, llm: Dict[str, Any], out_path: Path) -> Tuple[int, int, int]:
    base = Image.open(screenshot_path).convert("RGB")
    a = policy_a11y_first(llm)
    b = policy_vlm_first(llm)
    only_a_idx, only_b_idx, _ = _match_by_coord(a, b)

    left = _annotate(base, a, set(only_a_idx), "A11Y-FIRST  (current)", len(only_a_idx), len(a))
    right = _annotate(base, b, set(only_b_idx), "VLM-FIRST  (proposed)", len(only_b_idx), len(b))

    gap = 8
    combined = Image.new("RGB", (left.width + right.width + gap, left.height), (0, 0, 0))
    combined.paste(left, (0, 0))
    combined.paste(right, (left.width + gap, 0))

    legend = Image.new("RGB", (combined.width, 32), (30, 30, 30))
    ld = ImageDraw.Draw(legend)
    f = _font(14)
    ld.rectangle([10, 8, 30, 24], outline=COLOR_COMMON, width=3)
    ld.text((36, 9), "common (both policies)", fill=(220, 220, 220), font=f)
    ld.rectangle([260, 8, 280, 24], outline=COLOR_DIFF, width=3)
    ld.text((286, 9), "only on this side  (= the diff)", fill=(220, 220, 220), font=f)
    _draw_dashed_rect(ld, (560, 8, 580, 24), (200, 200, 200), width=3, dash=4)
    ld.text((586, 9), "dashed = coords from VLM bbox only (no a11y match)", fill=(220, 220, 220), font=f)

    final = Image.new("RGB", (combined.width, combined.height + legend.height), (0, 0, 0))
    final.paste(combined, (0, 0))
    final.paste(legend, (0, combined.height))
    final.save(out_path)
    return len(a), len(b), len(only_b_idx)


def main(run_dir: Path, filename: str = "llm_unseen_candidates.json") -> int:
    screenshots = run_dir / "screenshots"
    nodes_dir = run_dir / "nodes"

    suffix = ""
    stem = Path(filename).stem
    if stem != "llm_unseen_candidates":
        suffix = "_" + stem.replace("llm_unseen_candidates_", "")
    out_dir = run_dir.parent / f"vlm_first_diff{suffix}"
    out_dir.mkdir(exist_ok=True)

    rendered = 0
    for sub in sorted(nodes_dir.iterdir()):
        if not sub.is_dir():
            continue
        llm_path = sub / filename
        shot = screenshots / f"{sub.name}.png"
        if not llm_path.exists() or not shot.exists():
            continue
        llm = _load_json(llm_path)
        out_path = out_dir / f"{sub.name}.png"
        na, nb, diff = render_node(shot, llm, out_path)
        print(f"[{sub.name[:8]}]  a11y={na:>3}  vlm={nb:>3}  +{diff} unique  -> {out_path.name}")
        rendered += 1

    print(f"\nrendered {rendered} side-by-side comparisons -> {out_dir}")
    return 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", nargs="?", type=Path, default=DEFAULT_RUN)
    p.add_argument("--filename", default="llm_unseen_candidates.json")
    args = p.parse_args()
    sys.exit(main(args.run_dir, args.filename))
