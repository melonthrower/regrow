"""Render OmniParser bbox + caption overlays on each screenshot.

Reads nodes/<sid>/omniparser_icons.json (produced by run_omniparser_poc.py)
and writes <run_dir>/../omniparser_overlay/<sid>.png.

Sanity checks to look for:
  - Top-bar icons (Search / Filter / Menu in Logs) get framed.
  - Sidebar items (label-style rows) are NOT framed (would create false
    positives that the IoU step downstream might mismatch).

Run:
  python tools/visualize_omniparser_icons.py
  python tools/visualize_omniparser_icons.py --run <path>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUN = REPO_ROOT / "result_logs_0427_v3" / "gen_data" / "Doubao" / "0"
ICONS_FILENAME = "omniparser_icons.json"

COLOR_BOX = (50, 200, 80)
COLOR_TEXT_BG = (30, 30, 30)


def _font(size: int = 13) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _annotate(img: Image.Image, icons: List[Dict[str, Any]]) -> Image.Image:
    out = img.copy()
    draw = ImageDraw.Draw(out, "RGBA")
    font = _font(12)
    for it in icons:
        x, y, w, h = it["bbox"]
        x0, y0 = int(x), int(y)
        x1, y1 = x0 + max(2, int(w)), y0 + max(2, int(h))
        draw.rectangle([x0, y0, x1, y1], outline=COLOR_BOX, width=2)

        cap = (it.get("caption") or "<no caption>").strip()
        score = it.get("score", 0.0)
        text = f"{cap}  {score:.2f}"
        if len(text) > 36:
            text = text[:35] + "…"
        try:
            tb = draw.textbbox((0, 0), text, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        except AttributeError:
            tw, th = font.getsize(text)
        ty = max(0, y0 - th - 2)
        draw.rectangle([x0, ty, x0 + tw + 4, ty + th + 2], fill=COLOR_BOX + (220,))
        draw.text((x0 + 2, ty), text, fill=(255, 255, 255), font=font)
    return out


def _banner(width: int, sid: str, n: int) -> Image.Image:
    h = 40
    bar = Image.new("RGB", (width, h), COLOR_TEXT_BG)
    d = ImageDraw.Draw(bar)
    d.text((10, 10), f"[{sid[:8]}] OmniParser icons={n}", fill=(255, 255, 255), font=_font(20))
    return bar


def render_node(screenshot: Path, icons_path: Path, out_path: Path) -> Tuple[int, int, int]:
    data = json.load(open(icons_path, encoding="utf-8"))
    icons = data.get("icons", []) or []
    base = Image.open(screenshot).convert("RGB")
    annotated = _annotate(base, icons)

    bar = _banner(annotated.width, data.get("state_id", icons_path.parent.name), len(icons))
    final = Image.new("RGB", (annotated.width, annotated.height + bar.height), (0, 0, 0))
    final.paste(bar, (0, 0))
    final.paste(annotated, (0, bar.height))
    final.save(out_path)
    return base.width, base.height, len(icons)


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", nargs="?", type=Path, default=DEFAULT_RUN)
    p.add_argument("--icons-filename", default=ICONS_FILENAME)
    args = p.parse_args(argv)

    nodes_dir = args.run_dir / "nodes"
    shots_dir = args.run_dir / "screenshots"
    out_dir = args.run_dir.parent / "omniparser_overlay"
    out_dir.mkdir(exist_ok=True)

    rendered = 0
    total_icons = 0
    for sub in sorted(nodes_dir.iterdir()):
        if not sub.is_dir():
            continue
        icons = sub / args.icons_filename
        shot = shots_dir / f"{sub.name}.png"
        if not icons.exists() or not shot.exists():
            continue
        out_path = out_dir / f"{sub.name}.png"
        try:
            _, _, n = render_node(shot, icons, out_path)
        except Exception as e:
            print(f"  [{sub.name[:8]}] render failed: {e}")
            continue
        rendered += 1
        total_icons += n
        print(f"  [{sub.name[:8]}] icons={n:>3}  -> {out_path.name}")

    print(f"\nrendered {rendered} overlays -> {out_dir}")
    if rendered:
        print(f"average icons/node: {total_icons / rendered:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
