"""Unit test: classify_scroll_waste — the DEBUG agent's repeated-scroll detector
(spec B, 2026-07-06 grill Q4).

The over-scroll bug (a non-scrolling region scrolled to the cap re-detecting the
same controls) was fixed with stale-patience; hitting the scroll CAP with ZERO new
names now signals a regression / a region that should not have scrolled. Legit long
pages that hit the cap WHILE finding new content are not flagged. Pure, offline.

Usage:  python tests/test_scroll_waste.py
"""
import sys
import numpy as np

sys.path.insert(0, ".")

from gui_rewalk.src.core.visual_traversal.visual_agents import (  # noqa: E402
    classify_scroll_waste)
from gui_rewalk.src.core.visual_traversal.grounding.scroll import (  # noqa: E402
    _region_scroll_moved,
)

fails = 0


def check(desc, cond):
    global fails
    print("PASS" if cond else "FAIL", desc)
    if not cond:
        fails += 1


MAX = 12

# 1. hit the cap with NO new content -> the over-scroll pattern
check("hit max, 0 new -> flagged",
      classify_scroll_waste(steps=MAX, n_new=0, max_steps=MAX) == "hit_max_no_new")

# 2. hit the cap but found new rows -> legit long page, not flagged
check("hit max, new content -> not flagged",
      classify_scroll_waste(steps=MAX, n_new=5, max_steps=MAX) is None)

# 3. converged early (patience) below the cap -> normal, not flagged
check("converged below cap -> not flagged",
      classify_scroll_waste(steps=3, n_new=0, max_steps=MAX) is None)

# 4. exactly one below cap with no new -> not flagged (only the cap is the signal)
check("one below cap -> not flagged",
      classify_scroll_waste(steps=MAX - 1, n_new=0, max_steps=MAX) is None)

# 5. no scroll at all -> not flagged
check("zero steps -> not flagged",
      classify_scroll_waste(steps=0, n_new=0, max_steps=MAX) is None)

# 6. A cursor-sized change on a mostly blank Settings panel must not let an
# ambiguous high-score template match fabricate scrolling.
blank = np.full((200, 300, 3), 245, dtype=np.uint8)
cursor_only = blank.copy()
cursor_only[10:20, 10:20] = 0
check("cursor-sized blank-panel change -> not moved",
      not _region_scroll_moved(
          blank, cursor_only, 120, 0.99, min_shift=6, min_score=0.55))

# 7. A genuine content band moving changes enough pixels; shift and score still
# remain mandatory independent gates.
real_scroll = blank.copy()
real_scroll[80:120, :] = 80
check("real region change + shift + score -> moved",
      _region_scroll_moved(
          blank, real_scroll, 40, 0.90, min_shift=6, min_score=0.55))
check("real change but weak correlation -> not moved",
      not _region_scroll_moved(
          blank, real_scroll, 40, 0.20, min_shift=6, min_score=0.55))

print("=" * 40)
if fails:
    print(f"{fails} FAILED"); sys.exit(1)
print("ALL PASS")
