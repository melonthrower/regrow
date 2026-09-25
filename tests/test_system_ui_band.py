"""Offline unit test for the system-UI band filter (status bar + nav bar).

No emulator / VLM / network. Verifies that the Android top status bar
(clock / battery / signal) and the bottom gesture nav bar are dropped from the
click set, while real app rows — including ones that scrolled near the top/bottom
edge — are kept. Mirrors the live failure the user reported: the status-bar clock
("2:13", OCR'd "2.13") was being CLICKED, producing useless self-loop edges.

Run:  python tests/test_system_ui_band.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gui_rewalk.src.core.visual_traversal.visual_filter import (  # noqa: E402
    in_system_ui_band, STATUS_BAR_FRAC, NAV_BAR_FRAC, SYSTEM_UI_BAND_ENABLED)
from gui_rewalk.src.core.visual_traversal import visual_filter as vf  # noqa: E402

W, H = 1080, 1920
top = STATUS_BAR_FRAC * H        # 76.8
bot = (1 - NAV_BAR_FRAC) * H     # 1881.6


def expect(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        expect.failed += 1
expect.failed = 0


print(f"band: top<{top:.0f}px  bottom>{bot:.0f}px  (screen {W}x{H})")

# ── status bar (top corners) → DROP ──────────────────────────────────────────
expect(in_system_ui_band([83, 33], (W, H)), "clock '2:13' top-left (83,33) dropped")
expect(in_system_ui_band([962, 33], (W, H)), "battery '100%' top-right (962,33) dropped")
expect(in_system_ui_band([540, 20], (W, H)), "status-bar centre (540,20) dropped")

# ── gesture nav pill (very bottom) → DROP ────────────────────────────────────
expect(in_system_ui_band([540, 1885], (W, H)), "gesture pill (540,1885) dropped")

# ── real app controls → KEEP ─────────────────────────────────────────────────
expect(not in_system_ui_band([95, 130], (W, H)), "back-arrow / toolbar (95,130) kept")
expect(not in_system_ui_band([300, 250], (W, H)), "search bar (300,250) kept")
expect(not in_system_ui_band([540, 858], (W, H)), "'Check for update' row (540,858) kept")
expect(not in_system_ui_band([540, 1820], (W, H)), "last row above nav bar (540,1820) kept")

# ── boundary: just below the status bar must be KEPT (no clipping the app bar) ─
expect(not in_system_ui_band([540, int(top) + 2], (W, H)),
       f"just below status band (y={int(top)+2}) kept")
expect(in_system_ui_band([540, int(top) - 2], (W, H)),
       f"just inside status band (y={int(top)-2}) dropped")

# ── kill-switch: disabling the flag drops nothing ────────────────────────────
vf.SYSTEM_UI_BAND_ENABLED = False
expect(not in_system_ui_band([83, 33], (W, H)), "flag OFF: clock no longer dropped")
vf.SYSTEM_UI_BAND_ENABLED = True

print(f"\n{'ALL PASS' if expect.failed == 0 else str(expect.failed) + ' FAILED'}")
sys.exit(1 if expect.failed else 0)
