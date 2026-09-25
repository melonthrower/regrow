"""One-off comparison: pure-YOLO detection vs YOLO+OCR (OmniParser-style).

Runs on a single screenshot, counts boxes from each path, and saves two
annotated PNGs so we can eyeball what OCR adds. Throwaway analysis script.
"""
import sys, os
sys.path.insert(0, ".")
import numpy as np
import torch
from PIL import Image, ImageDraw

from gui_rewalk.env.utils import (
    get_yolo_model, predict_yolo, remove_overlap_new,
    check_ocr_box, int_box_area,
)

IMG = sys.argv[1] if len(sys.argv) > 1 else \
    "result/gen_data/Doubao/0/nodes/018ee57712493a90/screenshot.png"
YOLO = "OmniParser/weights/icon_detect/model.pt"
OUT = "result_visual/compare"
os.makedirs(OUT, exist_ok=True)

img = Image.open(IMG).convert("RGB")
w, h = img.size
img_np = np.asarray(img)
print(f"image: {IMG}  size={w}x{h}")

# ---- 1) YOLO only (what visual_perception.detect does) ----
model = get_yolo_model(YOLO)
xyxy, conf, _ = predict_yolo(model=model, image=img, box_threshold=0.05,
                             imgsz=(h, w), scale_img=False, iou_threshold=0.1)
xyxy_ratio = (xyxy / torch.tensor([w, h, w, h], device=xyxy.device)).cpu().tolist()
yolo_elems = [{"type": "icon", "bbox": b, "interactivity": True, "content": None}
              for b in xyxy_ratio]
yolo_filtered = remove_overlap_new(boxes=list(yolo_elems), iou_threshold=0.7, ocr_bbox=None)
print(f"\n[YOLO only]  raw={len(xyxy_ratio)}  after_overlap={len(yolo_filtered)}")

# ---- 2) OCR boxes (the part my module currently does NOT use) ----
# check_ocr_box() references uninitialized globals (paddle_ocr/reader) in this
# repo — proof OCR was never actually wired. Call easyocr directly instead.
import easyocr
reader = easyocr.Reader(["en", "ch_sim"], gpu=torch.cuda.is_available())
raw = reader.readtext(img_np, text_threshold=0.5)
ocr_text = [r[1] for r in raw]
# easyocr returns 4-point polygons; convert to xyxy
ocr_bbox_raw = []
for r in raw:
    pts = r[0]
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    ocr_bbox_raw.append([min(xs), min(ys), max(xs), max(ys)])
print(f"[OCR only]   text_boxes={len(ocr_text)}")
print("  sample OCR text:", [t for t in ocr_text[:12]])

# ---- 3) YOLO + OCR combined (full OmniParser style) ----
ocr_bbox_ratio = (torch.tensor(ocr_bbox_raw) / torch.tensor([w, h, w, h])).tolist() \
    if ocr_bbox_raw else []
ocr_elems = [{"type": "text", "bbox": b, "interactivity": False, "content": t,
              "source": "box_ocr_content_ocr"}
             for b, t in zip(ocr_bbox_ratio, ocr_text) if int_box_area(b, w, h) > 0]
combined = remove_overlap_new(boxes=list(yolo_elems), iou_threshold=0.7, ocr_bbox=ocr_elems)
print(f"[YOLO+OCR]   combined_after_overlap={len(combined)}")

# ---- annotate ----
def draw(elems, color, fname):
    im = img.copy(); d = ImageDraw.Draw(im)
    for e in elems:
        x0, y0, x1, y1 = e["bbox"]
        d.rectangle([x0*w, y0*h, x1*w, y1*h], outline=color, width=2)
    im.save(os.path.join(OUT, fname)); print("  saved", fname)

draw(yolo_filtered, (255, 0, 0), "yolo_only.png")
draw(combined, (0, 160, 0), "yolo_plus_ocr.png")
print(f"\nSUMMARY: YOLO-only={len(yolo_filtered)}  vs  YOLO+OCR={len(combined)}  "
      f"(OCR added ~{len(combined)-len(yolo_filtered)} boxes)")
