"""Compare window position between v3 stored screenshot and live screenshot."""
import os
from PIL import Image

# v3 stored screenshot
v3_path = "result_libre_calc_0412_v3/gen_data/Qwen/0/nodes/ea243525d1f6e8df/screenshot.png"
img_v3 = Image.open(v3_path)

# Live screenshot
live_path = "gui_rewalk/tools/_live_screenshot.png"
img_live = Image.open(live_path)

# Crop title bar area from both (y=0 to y=45, full width)
crop_v3 = img_v3.crop((0, 0, 800, 45))
crop_live = img_live.crop((0, 0, 800, 45))

# Stack vertically for comparison
combined = Image.new("RGB", (800, 100))
combined.paste(crop_v3, (0, 0))
combined.paste(crop_live, (0, 50))

from PIL import ImageDraw
draw = ImageDraw.Draw(combined)
draw.text((5, 0), "V3 stored", fill="yellow")
draw.text((5, 50), "LIVE now", fill="yellow")
draw.line([(0, 45), (800, 45)], fill="red", width=2)

combined = combined.resize((combined.width * 3, combined.height * 3), Image.NEAREST)
combined.save("gui_rewalk/tools/_titlebar_compare.png")

# Also compare the menu bar area (y=40 to y=70)
crop_v3_menu = img_v3.crop((50, 40, 700, 70))
crop_live_menu = img_live.crop((50, 40, 700, 70))

combined2 = Image.new("RGB", (650, 70))
combined2.paste(crop_v3_menu, (0, 0))
combined2.paste(crop_live_menu, (0, 35))
draw2 = ImageDraw.Draw(combined2)
draw2.text((5, 0), "V3", fill="yellow")
draw2.text((5, 35), "LIVE", fill="yellow")
draw2.line([(0, 30), (650, 30)], fill="red", width=1)
combined2 = combined2.resize((combined2.width * 3, combined2.height * 3), Image.NEAREST)
combined2.save("gui_rewalk/tools/_menu_compare.png")

# And the full toolbar area (y=25 to y=155)
crop_v3_tb = img_v3.crop((50, 25, 700, 155))
crop_live_tb = img_live.crop((50, 25, 700, 155))

combined3 = Image.new("RGB", (650, 270))
combined3.paste(crop_v3_tb, (0, 0))
combined3.paste(crop_live_tb, (0, 135))
draw3 = ImageDraw.Draw(combined3)
draw3.text((5, 0), "V3 stored", fill="yellow")
draw3.text((5, 135), "LIVE now", fill="yellow")
draw3.line([(0, 130), (650, 130)], fill="red", width=2)
combined3 = combined3.resize((combined3.width * 2, combined3.height * 2), Image.NEAREST)
combined3.save("gui_rewalk/tools/_toolbar_compare.png")

print("Saved comparison images")
print(f"V3 image size: {img_v3.size}")
print(f"Live image size: {img_live.size}")
