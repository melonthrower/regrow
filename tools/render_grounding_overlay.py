#!/usr/bin/env python3
"""把 VLM-grounding 的框叠加到节点截图上, 直观看检测/命名/分类效果.

用法: python tools/render_grounding_overlay.py <graph.json> [out.png] [node_id]
  默认挑元素最多的节点. 颜色: 红=dangerous 蓝=navigation 绿=shallow 黄=其他.
"""
import json, os, sys
from PIL import Image, ImageDraw, ImageFont

graph = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else "grounding_overlay.png"
want_id = sys.argv[3] if len(sys.argv) > 3 else None

d = json.load(open(graph))
nodes = d.get("nodes") or d.get("states") or []
nl = nodes if isinstance(nodes, list) else list(nodes.values())
if want_id:
    node = next(n for n in nl if str(n.get("state_id") or n.get("id")) == want_id)
else:
    node = max(nl, key=lambda n: len(n.get("elements") or n.get("actionable") or []))
els = node.get("elements") or node.get("actionable") or []

gdir = os.path.dirname(graph)
sid = str(node.get("state_id") or node.get("id"))
sp = node.get("screenshot_path") or ""
cands = [sp, os.path.join(gdir, sp),
         os.path.join(gdir, "node_artifacts", sid, "screenshot.png"),
         os.path.join(gdir, "node_artifacts", sid, "composite.png")]
img_path = next((p for p in cands if p and os.path.exists(p)), None)
if not img_path:
    print("no screenshot, tried:", cands); sys.exit(1)

im = Image.open(img_path).convert("RGB")
dr = ImageDraw.Draw(im)
W, H = im.size
def font(sz):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()
F = font(max(16, W // 55))
colors = {"dangerous": (230, 40, 40), "navigation": (40, 110, 230), "shallow": (30, 180, 90)}
for e in els:
    b = e.get("bbox_xywh") or e.get("bbox")
    if not b or len(b) < 4:
        continue
    x, y, w, h = b[:4]
    c = colors.get(e.get("category", ""), (210, 160, 0))
    dr.rectangle([x, y, x + w, y + h], outline=c, width=3)
    lbl = f"{e.get('id')}:{(e.get('name') or '')[:20]}"
    g = e.get("group")
    if g:
        lbl += f" [{g}]"
    tw = int(len(lbl) * (F.size * 0.6)) + 6
    ty = max(0, y - F.size - 6)
    dr.rectangle([x, ty, min(x + tw, W), ty + F.size + 5], fill=c)
    dr.text((x + 3, ty + 1), lbl, fill=(255, 255, 255), font=F)

im.save(out)
print(f"saved {out} size={im.size} app={node.get('app_name')} node={sid} els={len(els)}")
