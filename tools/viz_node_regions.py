"""Visualize each node's REGION/BLOCK distribution (2026-07-06 用户: 左截图标区块框,
右列区块及内容, 看怎么区分节点). Pure — no VM/VLM.

For each node: LEFT = screenshot with a colored box + label per region (bbox =
union of the region's element boxes); RIGHT = per-region list of element names.
Stacks the chosen nodes into one PNG and opens it.

Usage:  python tools/viz_node_regions.py <run_dir> <nid1> <nid2> ...
"""
import glob
import json
import os
import sys

sys.path.insert(0, ".")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

RUN = sys.argv[1] if len(sys.argv) > 1 else "result_foldcheck7/20260706/setting"
WANT = sys.argv[2:] or ["8003097e", "80031a6c", "8003070f", "80031b2f"]

REGION_COLORS = {
    "nav_sidebar": (66, 133, 244), "content": (219, 68, 55),
    "titlebar": (244, 180, 0), "toolbar": (15, 157, 88),
    "tab_bar": (171, 71, 188), "form": (0, 172, 193), "": (120, 120, 120),
}


def font(sz):
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except Exception:
            pass
    return ImageFont.load_default()


def region_boxes(elements):
    """role -> (union bbox xyxy, [names])."""
    reg = {}
    for e in elements:
        r = e.get("region") or ""
        b = e.get("bbox_xywh")
        if not b:
            continue
        x, y, w, h = b
        x2, y2 = x + w, y + h
        nm = (e.get("name") or "").strip()
        if r not in reg:
            reg[r] = [[x, y, x2, y2], []]
        bb = reg[r][0]
        bb[0], bb[1] = min(bb[0], x), min(bb[1], y)
        bb[2], bb[3] = max(bb[2], x2), max(bb[3], y2)
        if nm:
            reg[r][1].append(nm)
    return reg


def panel(run, nid):
    d = glob.glob(os.path.join(run, "node_artifacts", nid + "*"))
    if not d:
        return None
    els = json.load(open(os.path.join(d[0], "elements.json"), encoding="utf-8"))
    shot = Image.open(os.path.join(d[0], "screenshot.png")).convert("RGB")
    reg = region_boxes(els)
    dr = ImageDraw.Draw(shot)
    for r, (bb, _names) in reg.items():
        col = REGION_COLORS.get(r, REGION_COLORS[""])
        dr.rectangle(bb, outline=col, width=4)
        dr.rectangle([bb[0], bb[1] - 22, bb[0] + 12 + 9 * len(r), bb[1]], fill=col)
        dr.text((bb[0] + 4, bb[1] - 20), r or "(none)", fill=(255, 255, 255), font=font(15))
    sc = 0.46
    shot = shot.resize((int(shot.width * sc), int(shot.height * sc)))

    tw, th = 640, shot.height
    txt = Image.new("RGB", (tw, th), (250, 250, 250))
    td = ImageDraw.Draw(txt)
    y = 8
    td.text((8, y), f"node {nid}", fill=(0, 0, 0), font=font(18)); y += 28
    for r, (bb, names) in reg.items():
        col = REGION_COLORS.get(r, REGION_COLORS[""])
        td.text((8, y), f"[{r or '(none)'}]  {len(names)} 项", fill=col, font=font(16))
        y += 22
        for nm in names[:10]:
            td.text((24, y), "· " + nm[:60], fill=(40, 40, 40), font=font(13)); y += 17
        if len(names) > 10:
            td.text((24, y), f"  … +{len(names)-10} 项", fill=(120, 120, 120), font=font(13)); y += 17
        y += 4
    row = Image.new("RGB", (shot.width + tw + 12, th), (255, 255, 255))
    row.paste(shot, (0, 0)); row.paste(txt, (shot.width + 12, 0))
    return row


rows = [p for p in (panel(RUN, n) for n in WANT) if p is not None]
if not rows:
    print("no nodes"); sys.exit(1)
W = max(r.width for r in rows); H = sum(r.height + 10 for r in rows)
out = Image.new("RGB", (W, H), (200, 200, 200))
y = 0
for r in rows:
    out.paste(r, (0, y)); y += r.height + 10
op = os.path.abspath("_scratch/node_regions.png")
out.save(op)
print("SAVED", op)
