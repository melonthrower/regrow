"""Unit test: ReviewDebugSink.save_click_shots — save before/after PNGs for an
anomalous click (no_change / transitioned_inconsistent) so the verdict carries
VISUAL PROOF (2026-07-06: 死点/点偏要能亲眼看到点击那刻屏幕是什么).

Offline, no VM.  Usage:  python tests/test_click_shots.py
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, ".")
from PIL import Image  # noqa: E402

from gui_rewalk.src.core.visual_traversal.visual_agents import (  # noqa: E402
    ReviewDebugSink)

fails = 0


def check(desc, cond):
    global fails
    print("PASS" if cond else "FAIL", desc)
    if not cond:
        fails += 1


def png(color):
    b = io.BytesIO(); Image.new("RGB", (6, 6), color).save(b, format="PNG")
    return b.getvalue()


tmp = tempfile.mkdtemp()
sink = ReviewDebugSink(os.path.join(tmp, "_review_debug.jsonl"))
B = png((1, 2, 3)); A = png((9, 9, 9))

# 1. enabled sink saves both PNGs and returns their paths
r = sink.save_click_shots("8003070f_Sound_3", B, A)
check("returns before/after paths", isinstance(r, dict) and "before" in r and "after" in r)
check("before file exists + valid PNG",
      os.path.exists(r["before"]) and Image.open(r["before"]).size == (6, 6))
check("after file exists + valid PNG",
      os.path.exists(r["after"]) and Image.open(r["after"]).size == (6, 6))
check("shots live next to the jsonl (_click_shots/)",
      "_click_shots" in r["before"])

# 2. tag with spaces / slashes is sanitized into a safe filename
r2 = sink.save_click_shots("home_Add VPN/Connection_1", B, A)
check("unsafe tag sanitized (no space/slash in filename)",
      r2 is not None and " " not in os.path.basename(r2["before"])
      and "/" not in os.path.basename(r2["before"]))

# 3. missing bytes -> None, no crash
check("missing after -> None", sink.save_click_shots("x", B, None) is None)
check("missing before -> None", sink.save_click_shots("x", None, A) is None)

sink.close()

# 4. disabled sink -> None, no dir created
noop = ReviewDebugSink(None)
check("disabled sink -> None", noop.save_click_shots("x", B, A) is None)
noop.close()

print("=" * 40)
if fails:
    print(f"{fails} FAILED"); sys.exit(1)
print("ALL PASS")
