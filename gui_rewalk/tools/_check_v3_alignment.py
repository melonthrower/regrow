"""Check if v3 stored elements align with v3 stored screenshot."""
import json, os
from PIL import Image, ImageDraw

nodes_dir = "result_libre_calc_0412_v3/gen_data/Qwen/0/nodes"
root_id = "ea243525d1f6e8df"

# Load screenshot
img = Image.open(os.path.join(nodes_dir, root_id, "screenshot.png"))
draw = ImageDraw.Draw(img)

# Load elements
with open(os.path.join(nodes_dir, root_id, "elements.json"), encoding="utf-8") as f:
    elems = json.load(f)

# Draw boxes + crosshairs for named non-table-cell elements
count = 0
for e in elems:
    tag = e.get("tag", "")
    if tag == "table-cell":
        continue
    name = e.get("name", "")
    if not name:
        continue
    sx = e.get("screen_x", 0)
    sy = e.get("screen_y", 0)
    w = e.get("width", 0)
    h = e.get("height", 0)
    if w <= 0 or h <= 0:
        continue
    # Red box
    draw.rectangle([sx, sy, sx + w, sy + h], outline="red", width=1)
    # Green crosshair at center
    cx, cy = sx + w // 2, sy + h // 2
    draw.line([(cx - 5, cy), (cx + 5, cy)], fill="lime", width=2)
    draw.line([(cx, cy - 5), (cx, cy + 5)], fill="lime", width=2)
    count += 1

print(f"Drew {count} elements")

# Save full overlay
img.save("gui_rewalk/tools/_v3_alignment_full.png")

# Save zoomed toolbar crop
crop = img.crop((50, 40, 700, 180))
crop = crop.resize((crop.width * 3, crop.height * 3), Image.NEAREST)
crop.save("gui_rewalk/tools/_v3_alignment_toolbar.png")

# Save zoomed formatting toolbar
crop2 = img.crop((300, 85, 600, 170))
crop2 = crop2.resize((crop2.width * 4, crop2.height * 4), Image.NEAREST)
crop2.save("gui_rewalk/tools/_v3_alignment_bold.png")

print("Saved alignment images")
