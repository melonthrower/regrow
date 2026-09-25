"""Annotate detected+named buttons onto existing node screenshots.

Runs the full visual perception (YOLO + OCR + VLM naming) on one or more
screenshots and draws box + id + name, colour-coded by name source:
  green  = vlm     (VLM unified naming)
  blue   = ocr     (OCR text fallback)
  orange = caption (Florence-2 fallback)
  red    = yolo    (no name — couldn't identify)

No VM needed. Usage:
  python tools/annotate_buttons_on_nodes.py <img1.png> [img2.png ...]
  python tools/annotate_buttons_on_nodes.py --run result/gen_data/Doubao/0 --limit 4
Outputs result_visual/annotated/<name>_named.png and a combined report line.
"""
import sys, os, argparse, json
sys.path.insert(0, ".")
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from gui_rewalk.env.utils import get_yolo_model
from gui_rewalk.env.gui_gen_agent import GUIGenAgent
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualPerception

SRC_COLORS = {"vlm": (40, 180, 40), "ocr": (40, 120, 240),
              "caption": (240, 150, 30), "yolo": (230, 40, 40)}
OUT = "result_visual/annotated"


def load_font(size):
    for fp in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            continue
    return ImageFont.load_default()


def annotate(img_path, perception, font):
    from gui_rewalk.src.core.visual_traversal.visual_filter import (
        center_in_window, effective_category)
    with open(img_path, "rb") as f:
        shot = f.read()
    # keep everything so we can SHOW what the filter would drop
    els = perception.detect_and_name(shot, apply_filter=False)
    win = perception.last_window_xywh
    is_modal = getattr(perception, "last_is_modal", False)
    img = Image.open(img_path).convert("RGB")
    W, H = img.size
    d = ImageDraw.Draw(img)
    # draw the active surface (modal bbox if modal, else main window) in yellow
    if win:
        wx, wy, ww, wh = win
        d.rectangle([wx, wy, wx + ww, wy + wh], outline=(255, 220, 0), width=4)
    # colour by the four-category decision: green=navigation(click), red=dangerous,
    # orange=shallow(record), purple=display, grey=outside-window
    CAT_COLORS = {"navigation": (40, 180, 40), "dangerous": (230, 40, 40),
                  "shallow": (240, 150, 30), "display": (170, 80, 200)}
    counts = {"navigation": 0, "dangerous": 0, "shallow": 0, "display": 0, "outside": 0}
    for e in els:
        x, y, w, h = e.bbox_xywh
        cat = effective_category(e.category, e.name)
        if not center_in_window(e.center, win, (W, H)):
            col = (130, 130, 130); counts["outside"] += 1
        else:
            col = CAT_COLORS.get(cat, (180, 180, 180)); counts[cat] = counts.get(cat, 0) + 1
        d.rectangle([x, y, x + w, y + h], outline=col, width=2)
        label = f"{e.id}:{e.name}" if e.name else f"{e.id}:?"
        ly = max(0, y - 14)
        try:
            tw = int(d.textlength(label, font=font))
        except Exception:
            tw = 8 * len(label)
        d.rectangle([x, ly, x + tw + 4, ly + 14], fill=col)
        d.text((x + 2, ly), label, fill=(255, 255, 255), font=font)
    os.makedirs(OUT, exist_ok=True)
    base = os.path.basename(os.path.dirname(img_path)) or os.path.splitext(os.path.basename(img_path))[0]
    out_path = os.path.join(OUT, f"{base}_named.png")
    img.save(out_path)
    kept = counts["navigation"]
    print(f"  {base}: {len(els)} boxes | click~{kept} navigation "
          f"(skip {counts['dangerous']} dangerous, {counts['shallow']} shallow, "
          f"{counts['display']} display, {counts['outside']} outside) "
          f"modal={is_modal} -> {out_path}")
    return out_path, els


def main():
    p = argparse.ArgumentParser()
    p.add_argument("images", nargs="*")
    p.add_argument("--run", default="")
    p.add_argument("--limit", type=int, default=4)
    p.add_argument("--ocr_engine", default="easyocr")
    p.add_argument("--no_ocr", action="store_true")
    p.add_argument("--ocr_model_path", default="OmniParser/weights/icon_detect/model.pt")
    args = p.parse_args()

    imgs = list(args.images)
    if args.run:
        nodes = os.path.join(args.run, "nodes")
        found = sorted(os.path.join(nodes, d, "screenshot.png")
                       for d in os.listdir(nodes)
                       if os.path.exists(os.path.join(nodes, d, "screenshot.png")))
        imgs += found[: args.limit]
    if not imgs:
        print("no images given"); return 2

    agent = GUIGenAgent(model="Doubao", model_version="doubao-seed-1-8-251228",
                        max_tokens=1500, temperature=0.5, use_ark=True)
    yolo = get_yolo_model(args.ocr_model_path)
    perception = VisualPerception(yolo, agent=agent, use_ocr=not args.no_ocr,
                                  ocr_engine=args.ocr_engine)
    font = load_font(13)
    print(f"annotating {len(imgs)} screenshot(s), ocr={'off' if args.no_ocr else args.ocr_engine}")
    for ip in imgs:
        try:
            annotate(ip, perception, font)
        except Exception as e:
            print(f"  FAILED {ip}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
