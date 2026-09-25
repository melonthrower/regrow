"""Visualize name-lookup grounding: VLM contributes name only, a11y owns bbox.

For each Qwen-demo candidate we look its name up in the union of
  framework_unseen_candidates + framework_unseen_candidates_raw + vlm_discovered_elements
and replace its bbox with the a11y truth bbox if the name matches.

Output per node:
  green  solid    = name matched to an a11y element, drawn at a11y bbox
  orange dashed   = name not matched, drawn at VLM-reported bbox (still suspect)

Run:
  python tools/visualize_qwen_namelookup.py
       --filename llm_unseen_candidates_qwen_demo.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUN = REPO_ROOT / "result_logs_0427_v3" / "gen_data" / "Doubao" / "0"

COLOR_MATCH = (50, 200, 80)
COLOR_UNMATCH = (255, 140, 0)


def _font(size: int = 14) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_dashed_rect(draw, xy, color, width=3, dash=8):
    x0, y0, x1, y1 = xy
    for x in range(x0, x1, dash * 2):
        draw.line([(x, y0), (min(x + dash, x1), y0)], fill=color, width=width)
        draw.line([(x, y1), (min(x + dash, x1), y1)], fill=color, width=width)
    for y in range(y0, y1, dash * 2):
        draw.line([(x0, y), (x0, min(y + dash, y1))], fill=color, width=width)
        draw.line([(x1, y), (x1, min(y + dash, y1))], fill=color, width=width)


def build_truth(d: Dict[str, Any]) -> Dict[str, Tuple[int, int, int, int]]:
    truth: Dict[str, Tuple[int, int, int, int]] = {}
    for fw in d.get("framework_unseen_candidates_raw", []):
        nm = (fw.get("name") or "").strip().lower()
        if nm:
            bb = fw["bbox"]
            truth.setdefault(nm, (bb["x"], bb["y"], bb["w"], bb["h"]))
    for fw in d.get("framework_unseen_candidates", []):
        nm = (fw.get("name") or "").strip().lower()
        if nm:
            bb = fw["bbox"]
            truth.setdefault(nm, (bb["x"], bb["y"], bb["w"], bb["h"]))
    for v in d.get("vlm_discovered_elements", []) or []:
        nm = (v.get("name") or "").strip().lower()
        if nm:
            truth.setdefault(nm, (v["screen_x"], v["screen_y"], v.get("width", 0), v.get("height", 0)))
    return truth


def lookup(name: str, truth: Dict[str, Tuple[int, int, int, int]]) -> Optional[Tuple[int, int, int, int]]:
    n = (name or "").strip().lower()
    if not n:
        return None
    if n in truth:
        return truth[n]
    # fuzzy substring (longest match wins)
    best, best_len = None, 0
    for tn, bb in truth.items():
        if n in tn or tn in n:
            common_len = min(len(n), len(tn))
            if common_len > best_len:
                best, best_len = bb, common_len
    return best


def _annotate(img: Image.Image, items: List[Dict[str, Any]]) -> Image.Image:
    out = img.copy()
    draw = ImageDraw.Draw(out, "RGBA")
    font = _font(13)
    for it in items:
        x, y, w, h = it["bbox"]
        x0, y0 = int(x), int(y)
        x1, y1 = x0 + max(2, int(w)), y0 + max(2, int(h))
        if it["matched"]:
            draw.rectangle([x0, y0, x1, y1], outline=COLOR_MATCH, width=3)
            color = COLOR_MATCH
            tag = "[a11y]"
        else:
            _draw_dashed_rect(draw, (x0, y0, x1, y1), COLOR_UNMATCH, width=3)
            color = COLOR_UNMATCH
            tag = "[vlm bbox]"

        text = f"{tag} {it['name']}"
        if len(text) > 36:
            text = text[:35] + "…"
        try:
            tb = draw.textbbox((0, 0), text, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        except AttributeError:
            tw, th = font.getsize(text)
        ty = max(0, y0 - th - 2)
        draw.rectangle([x0, ty, x0 + tw + 4, ty + th + 2], fill=color + (220,))
        draw.text((x0 + 2, ty), text, fill=(255, 255, 255), font=font)
    return out


def render_node(
    screenshot: Path,
    src: Dict[str, Any],
    out_path: Path,
) -> Tuple[int, int]:
    truth = build_truth(src)

    items: List[Dict[str, Any]] = []
    for c in src.get("llm_unseen_candidates", []) or []:
        cat = (c.get("category") or "").lower()
        if cat in ("display", "dangerous"):
            continue  # follow same drop policy as compare/visualize scripts
        name = c.get("element_name", "")
        bb = c.get("bbox") or {"x": 0, "y": 0, "w": 0, "h": 0}
        truth_bb = lookup(name, truth)
        if truth_bb is not None:
            items.append({"name": name, "bbox": truth_bb, "matched": True})
        else:
            items.append({
                "name": name,
                "bbox": (bb.get("x", 0), bb.get("y", 0), bb.get("w", 0), bb.get("h", 0)),
                "matched": False,
            })

    matched = sum(1 for it in items if it["matched"])
    unmatched = len(items) - matched

    base = Image.open(screenshot).convert("RGB")
    annotated = _annotate(base, items)

    banner_h = 40
    bar = Image.new("RGB", (annotated.width, banner_h), (30, 30, 30))
    bd = ImageDraw.Draw(bar)
    bd.text(
        (10, 8),
        f"NAME-LOOKUP  —  total={len(items)}, a11y-grounded={matched}, unmatched(VLM bbox)={unmatched}",
        fill=(255, 255, 255),
        font=_font(20),
    )

    legend = Image.new("RGB", (annotated.width, 32), (30, 30, 30))
    ld = ImageDraw.Draw(legend)
    f = _font(14)
    ld.rectangle([10, 8, 30, 24], outline=COLOR_MATCH, width=3)
    ld.text((36, 9), "name matched -> a11y bbox", fill=(220, 220, 220), font=f)
    _draw_dashed_rect(ld, (320, 8, 340, 24), COLOR_UNMATCH, width=3, dash=4)
    ld.text((346, 9), "no a11y match -> VLM bbox (suspect)", fill=(220, 220, 220), font=f)

    final = Image.new(
        "RGB",
        (annotated.width, annotated.height + banner_h + legend.height),
        (30, 30, 30),
    )
    final.paste(bar, (0, 0))
    final.paste(annotated, (0, banner_h))
    final.paste(legend, (0, banner_h + annotated.height))
    final.save(out_path)
    return matched, unmatched


def main(run_dir: Path, filename: str) -> int:
    screenshots = run_dir / "screenshots"
    nodes_dir = run_dir / "nodes"

    suffix = "_namelookup"
    out_dir = run_dir.parent / f"vlm_first_diff{suffix}"
    out_dir.mkdir(exist_ok=True)

    total_matched = 0
    total_unmatched = 0
    rendered = 0
    for sub in sorted(nodes_dir.iterdir()):
        if not sub.is_dir():
            continue
        src_path = sub / filename
        shot = screenshots / f"{sub.name}.png"
        if not src_path.exists() or not shot.exists():
            continue
        src = json.load(open(src_path, encoding="utf-8"))
        out_path = out_dir / f"{sub.name}.png"
        m, u = render_node(shot, src, out_path)
        total_matched += m
        total_unmatched += u
        rate = m / max(1, m + u)
        print(f"  [{sub.name[:8]}]  matched={m:>2}  unmatched={u:>2}  ({100*rate:.0f}% grounded)  -> {out_path.name}")
        rendered += 1

    total = total_matched + total_unmatched
    print(f"\nrendered {rendered} screenshots -> {out_dir}")
    if total:
        print(f"aggregate name-grounding: {total_matched}/{total} = {100*total_matched/total:.1f}%")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", nargs="?", type=Path, default=DEFAULT_RUN)
    p.add_argument("--filename", default="llm_unseen_candidates_qwen_demo.json")
    args = p.parse_args()
    sys.exit(main(args.run_dir, args.filename))
