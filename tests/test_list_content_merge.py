"""Offline regression for stable aggregation of a non-terminating list.

A fake list reveals new rows on every swipe. The real scroll aggregate must hit
its cap and keep a stable element count across visits with different fling
jitter. Page/Variant identity is tested by the current map-guided identity
contracts, not inferred here from list-row wording.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

W, H = 360, 720
TOP_BAND = int(H * 0.16)


def _png(arr):
    return cv2.imencode(".png", arr)[1].tobytes()


class _InfiniteListEnv:
    """Every down-swipe scrolls a never-ending list by a JITTERY amount, always
    revealing brand-new rows (the infinite agenda). Up-swipe restores."""
    vm_platform = "android"
    ROW_H = 90

    def __init__(self, deltas):
        self.offset = 0
        self.deltas = deltas
        self.i = 0

    def _render(self):
        img = np.full((H, W, 3), 250, np.uint8)
        img[0:TOP_BAND] = (200, 120, 30)  # stable top bar
        # rows depend on absolute offset so each scroll shows NEW content forever
        first_row = self.offset // self.ROW_H
        for k in range(0, H // self.ROW_H + 2):
            ry = k * self.ROW_H - (self.offset % self.ROW_H) + TOP_BAND
            if ry + self.ROW_H < 0 or ry > H:
                continue
            r = first_row + k
            rng = np.random.RandomState(r * 7 + 13)
            col = rng.randint(0, 256, 3).tolist()
            y0 = max(0, ry)
            y1 = min(H, ry + self.ROW_H - 6)
            if y1 > y0:
                img[y0:y1] = col
                img[y0:min(y1, y0 + 18), 20:W - 20] = (
                    rng.rand(min(18, y1 - y0), W - 40, 3) * 255).astype(np.uint8)
        return img

    def step(self, action, pause=0.0):
        if action.get("action_type") == "SCROLL":
            d = self.deltas[min(self.i, len(self.deltas) - 1)]
            self.i += 1
            direction = action["parameters"].get("direction", "down")
            if direction == "down":
                self.offset += d
            else:
                self.offset = max(0, self.offset - d)
        return {"screenshot": _png(self._render())}


def _bind_engine(env):
    """Borrow the real _scroll_aggregate (+ its helpers) on a minimal shim, the
    same trick test_scroll_locate uses, so we exercise the actual engine code."""
    from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine
    from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement

    class _Perc:
        """Perceive the rows currently on screen as VisualElements (no YOLO/VLM)."""
        def detect_and_name(self, shot):
            img = cv2.imdecode(np.frombuffer(shot, np.uint8), cv2.IMREAD_COLOR)
            els = []
            # one element per visible row band (below the top bar)
            for k, y in enumerate(range(TOP_BAND + 10, H - 30, _InfiniteListEnv.ROW_H)):
                els.append(VisualElement(
                    id=k, name=f"row@{y}", bbox_xywh=[20, y, W - 40, 40],
                    center=[W // 2, y + 20]))
            return els

    shim = object.__new__(VisualTraversalEngine)
    shim.env = env
    shim.perception = _Perc()
    shim.focus_guard = None
    shim._is_touch = True
    shim._stitch_node_image = False
    shim._last_scroll_frames = []
    shim._last_scroll_offsets = []
    return shim, _Perc()


def test_aggregate_damp():
    from gui_rewalk.src.core.visual_traversal.grounding.scroll import (
        MAX_BELOW_FOLD_ON_RUNAWAY, MAX_SCROLL_STEPS)

    counts = []
    below_counts = []
    for deltas in ([150, 170, 140, 160, 150, 150, 150, 150, 150, 150],
                   [90, 240, 110, 300, 120, 180, 150, 200, 130, 170]):
        env = _InfiniteListEnv(deltas)
        shim, perc = _bind_engine(env)
        env.offset = 0
        first = perc.detect_and_name(_png(env._render()))
        n_top = len(first)
        agg = shim._scroll_aggregate({"screenshot": _png(env._render())}, first)
        n_below = sum(1 for e in agg if getattr(e, "scroll_steps", 0) > 0)
        counts.append(len(agg))
        below_counts.append(n_below)
        print(f"[2] infinite list (jitter {deltas[:3]}...): aggregated {len(agg)} "
              f"rows ({n_top} top + {n_below} below-fold)")
        # the runaway below-fold contribution is capped at a fixed COUNT
        assert n_below <= MAX_BELOW_FOLD_ON_RUNAWAY, (
            f"runaway tail not trimmed: {n_below} below-fold > cap "
            f"{MAX_BELOW_FOLD_ON_RUNAWAY}")
        # and the untrimmed list would have been WAY larger (sanity: an infinite
        # list over MAX_SCROLL_STEPS swipes reveals far more than the cap).
        assert n_below == MAX_BELOW_FOLD_ON_RUNAWAY, (
            "infinite list should fill the below-fold cap exactly")

    assert counts[0] == counts[1], (
        f"non-terminating list element count not STABLE across visits with "
        f"different jitter: {counts[0]} vs {counts[1]} (this is exactly the "
        f"103 vs 114 Schedule fork; the fixed-count cap must make it reproduce)")
    print(f"[2] element set STABLE across visits despite jitter: "
          f"{counts[0]} == {counts[1]} (capped below-fold {below_counts[0]})")


def main():
    test_aggregate_damp()
    print("\nALL PASS — a non-terminating list is trimmed to a stable element "
          "set across visits with different scroll jitter.")


if __name__ == "__main__":
    main()
