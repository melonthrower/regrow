"""Analyze the final element list for multi-box / duplicate-box issues.

Loads elements.json (from run_visual_traversal --perception-only) and reports:
  * exact duplicate centers
  * high-IoU pairs (likely the same control boxed twice)
  * nested boxes (one fully inside another)
Throwaway analysis script.
"""
import sys, json
from itertools import combinations

path = sys.argv[1] if len(sys.argv) > 1 else "result_visual/perception_ocr/elements.json"
els = json.load(open(path, encoding="utf-8"))
print(f"total elements: {len(els)}")


def xyxy(e):
    x, y, w, h = e["bbox_xywh"]
    return x, y, x + w, y + h


def iou(a, b):
    ax0, ay0, ax1, ay1 = xyxy(a); bx0, by0, bx1, by1 = xyxy(b)
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    aarea = (ax1 - ax0) * (ay1 - ay0); barea = (bx1 - bx0) * (by1 - by0)
    return inter / (aarea + barea - inter + 1e-6), inter, aarea, barea


# exact duplicate centers
seen = {}
dup_centers = []
for e in els:
    c = tuple(e["center"])
    if c in seen:
        dup_centers.append((seen[c], e))
    else:
        seen[c] = e
print(f"\nexact duplicate centers: {len(dup_centers)}")
for a, b in dup_centers[:10]:
    print(f"  '{a['name']}' & '{b['name']}' @ {a['center']}")

# high IoU pairs + nested
high_iou, nested = [], []
for a, b in combinations(els, 2):
    v, inter, aarea, barea = iou(a, b)
    if v > 0.5:
        high_iou.append((a, b, v))
    elif inter > 0 and (inter / min(aarea, barea) > 0.85):
        nested.append((a, b, inter / min(aarea, barea)))

print(f"\nhigh-IoU (>0.5) pairs (same control boxed twice?): {len(high_iou)}")
for a, b, v in sorted(high_iou, key=lambda t: -t[2])[:12]:
    print(f"  IoU={v:.2f}  '{a['name']}'({a['source']}) <> '{b['name']}'({b['source']})")

print(f"\nnested boxes (>85% inside another): {len(nested)}")
for a, b, r in sorted(nested, key=lambda t: -t[2])[:12]:
    print(f"  {r:.0%}  '{a['name']}'({a['source']}) in/has '{b['name']}'({b['source']})")

# source breakdown
from collections import Counter
print("\nsource breakdown:", dict(Counter(e["source"] for e in els)))
print("empty-name count:", sum(1 for e in els if not e["name"].strip()))
