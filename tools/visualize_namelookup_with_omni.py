"""Name-lookup grounding with an OmniParser fallback.

Extends `visualize_qwen_namelookup.py` (62% baseline) with a second
fallback layer: when a Qwen-demo candidate's name doesn't match anything
in the a11y truth set, try IoU-matching its VLM-reported bbox to one of
the OmniParser-detected icons. This recovers GTK header-bar icons
(Search / Filter / Menu) that have a11y `name=""` and were therefore
invisible to the name lookup.

For each candidate we draw one of:
    green  solid    = a11y name matched, drawn at a11y bbox  (best)
    cyan   solid    = OmniParser IoU matched, drawn at OmniParser bbox + caption shown
    orange dashed   = no match, drawn at VLM bbox (still suspect)

Inputs per node:
    nodes/<sid>/<--filename>            (Qwen demo candidates, default llm_unseen_candidates_qwen_demo.json)
    nodes/<sid>/omniparser_icons.json   (from run_omniparser_poc.py)

Output:
    <run>/../vlm_first_diff_namelookup_omni/<sid>.png

Run:
    python tools/visualize_namelookup_with_omni.py
    python tools/visualize_namelookup_with_omni.py --iou-threshold 0.3
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

COLOR_A11Y = (50, 200, 80)      # green
COLOR_OMNI = (60, 200, 230)     # cyan
COLOR_UNMATCH = (255, 140, 0)   # orange


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


def _bbox_iou(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ax1, ay1 = ax0 + aw, ay0 + ah
    bx1, by1 = bx0 + bw, by0 + bh
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def build_a11y_truth(d: Dict[str, Any]) -> Dict[str, Tuple[int, int, int, int]]:
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


def name_lookup(name: str, truth: Dict[str, Tuple[int, int, int, int]]) -> Optional[Tuple[int, int, int, int]]:
    n = (name or "").strip().lower()
    if not n:
        return None
    if n in truth:
        return truth[n]
    best, best_len = None, 0
    for tn, bb in truth.items():
        if n in tn or tn in n:
            common_len = min(len(n), len(tn))
            if common_len > best_len:
                best, best_len = bb, common_len
    return best


def omni_iou_lookup(
    vlm_bbox: Tuple[int, int, int, int],
    icons: List[Dict[str, Any]],
    iou_threshold: float,
) -> Optional[Dict[str, Any]]:
    if vlm_bbox[2] <= 0 or vlm_bbox[3] <= 0:
        return None
    best, best_iou = None, iou_threshold
    for ic in icons:
        bb = ic.get("bbox") or [0, 0, 0, 0]
        if len(bb) < 4 or bb[2] <= 0 or bb[3] <= 0:
            continue
        iou = _bbox_iou(vlm_bbox, tuple(bb))
        if iou > best_iou:
            best, best_iou = ic, iou
    if best is None:
        return None
    return {**best, "_iou": best_iou}


def _annotate(img: Image.Image, items: List[Dict[str, Any]]) -> Image.Image:
    out = img.copy()
    draw = ImageDraw.Draw(out, "RGBA")
    font = _font(13)
    for it in items:
        x, y, w, h = it["bbox"]
        x0, y0 = int(x), int(y)
        x1, y1 = x0 + max(2, int(w)), y0 + max(2, int(h))
        kind = it["kind"]
        if kind == "a11y":
            color = COLOR_A11Y
            tag = "[a11y]"
            dashed = False
        elif kind == "omni":
            color = COLOR_OMNI
            cap = it.get("caption") or "?"
            tag = f"[omni:{cap}]"
            dashed = False
        else:
            color = COLOR_UNMATCH
            tag = "[vlm bbox]"
            dashed = True

        if dashed:
            _draw_dashed_rect(draw, (x0, y0, x1, y1), color, width=3)
        else:
            draw.rectangle([x0, y0, x1, y1], outline=color, width=3)

        text = f"{tag} {it['name']}"
        if len(text) > 42:
            text = text[:41] + "…"
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
    icons: List[Dict[str, Any]],
    out_path: Path,
    iou_threshold: float,
) -> Tuple[int, int, int]:
    truth = build_a11y_truth(src)
    items: List[Dict[str, Any]] = []
    for c in src.get("llm_unseen_candidates", []) or []:
        cat = (c.get("category") or "").lower()
        if cat in ("display", "dangerous"):
            continue
        name = c.get("element_name", "")
        bb = c.get("bbox") or {"x": 0, "y": 0, "w": 0, "h": 0}
        vlm_bbox = (bb.get("x", 0), bb.get("y", 0), bb.get("w", 0), bb.get("h", 0))

        truth_bb = name_lookup(name, truth)
        if truth_bb is not None:
            items.append({"name": name, "bbox": truth_bb, "kind": "a11y"})
            continue

        omni = omni_iou_lookup(vlm_bbox, icons, iou_threshold)
        if omni is not None:
            ob = omni["bbox"]
            items.append({
                "name": name,
                "bbox": (ob[0], ob[1], ob[2], ob[3]),
                "kind": "omni",
                "caption": omni.get("caption", ""),
                "iou": omni.get("_iou", 0.0),
            })
            continue

        items.append({"name": name, "bbox": vlm_bbox, "kind": "unmatch"})

    matched_a = sum(1 for it in items if it["kind"] == "a11y")
    matched_o = sum(1 for it in items if it["kind"] == "omni")
    unmatched = sum(1 for it in items if it["kind"] == "unmatch")

    base = Image.open(screenshot).convert("RGB")
    annotated = _annotate(base, items)

    banner_h = 40
    bar = Image.new("RGB", (annotated.width, banner_h), (30, 30, 30))
    bd = ImageDraw.Draw(bar)
    bd.text(
        (10, 8),
        f"NAME-LOOKUP + OMNI  —  total={len(items)}, a11y={matched_a}, "
        f"omni={matched_o}, unmatched={unmatched}",
        fill=(255, 255, 255),
        font=_font(20),
    )

    legend = Image.new("RGB", (annotated.width, 32), (30, 30, 30))
    ld = ImageDraw.Draw(legend)
    f = _font(13)
    ld.rectangle([10, 8, 30, 24], outline=COLOR_A11Y, width=3)
    ld.text((36, 9), "a11y name match", fill=(220, 220, 220), font=f)
    ld.rectangle([220, 8, 240, 24], outline=COLOR_OMNI, width=3)
    ld.text((246, 9), "OmniParser IoU match (+caption)", fill=(220, 220, 220), font=f)
    _draw_dashed_rect(ld, (510, 8, 530, 24), COLOR_UNMATCH, width=3, dash=4)
    ld.text((536, 9), "no match -> VLM bbox (suspect)", fill=(220, 220, 220), font=f)

    final = Image.new(
        "RGB",
        (annotated.width, annotated.height + banner_h + legend.height),
        (30, 30, 30),
    )
    final.paste(bar, (0, 0))
    final.paste(annotated, (0, banner_h))
    final.paste(legend, (0, banner_h + annotated.height))
    final.save(out_path)
    return matched_a, matched_o, unmatched


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", nargs="?", type=Path, default=DEFAULT_RUN)
    p.add_argument("--filename", default="llm_unseen_candidates_qwen_demo.json",
                   help="Per-node Qwen candidates file (relative to nodes/<sid>/)")
    p.add_argument("--icons-filename", default="omniparser_icons.json")
    p.add_argument("--iou-threshold", type=float, default=0.3)
    p.add_argument("--out-suffix", default="namelookup_omni")
    args = p.parse_args(argv)

    screenshots = args.run_dir / "screenshots"
    nodes_dir = args.run_dir / "nodes"
    out_dir = args.run_dir.parent / f"vlm_first_diff_{args.out_suffix}"
    out_dir.mkdir(exist_ok=True)

    total_a, total_o, total_u = 0, 0, 0
    rendered = 0
    for sub in sorted(nodes_dir.iterdir()):
        if not sub.is_dir():
            continue
        src_path = sub / args.filename
        icons_path = sub / args.icons_filename
        shot = screenshots / f"{sub.name}.png"
        if not src_path.exists() or not shot.exists():
            continue
        src = json.load(open(src_path, encoding="utf-8"))
        icons: List[Dict[str, Any]] = []
        if icons_path.exists():
            try:
                icons = json.load(open(icons_path, encoding="utf-8")).get("icons", []) or []
            except Exception:
                icons = []

        out_path = out_dir / f"{sub.name}.png"
        ma, mo, mu = render_node(shot, src, icons, out_path, args.iou_threshold)
        total_a += ma
        total_o += mo
        total_u += mu
        n = ma + mo + mu
        rate = (ma + mo) / max(1, n)
        print(
            f"  [{sub.name[:8]}]  total={n:>2}  a11y={ma:>2}  omni={mo:>2}  "
            f"unmatched={mu:>2}  ({100 * rate:.0f}% grounded)  -> {out_path.name}"
        )
        rendered += 1

    total = total_a + total_o + total_u
    print(f"\nrendered {rendered} screenshots -> {out_dir}")
    if total:
        print(
            f"aggregate grounding: a11y={total_a}/{total} = {100 * total_a / total:.1f}%, "
            f"+omni={total_o}/{total} = +{100 * total_o / total:.1f}pp, "
            f"final={total_a + total_o}/{total} = {100 * (total_a + total_o) / total:.1f}%"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
