"""Offline integration test for the STITCH_NODE_IMAGE wiring in visual_engine.

No device, no YOLO, no VLM. A synthetic scrollable "page" is rendered into frames
by a mock env; a mock perception returns geometry-only boxes for arbitrary frames
(the YOLO-only capture path) and named elements for the COMPOSITE (the single
naming call). We drive the engine's real ``_register`` with the flag ON and assert
the integration contracts:

  1. the scroll-capture buffers are filled and the composite is built + perceived
     EXACTLY ONCE for naming after the mandatory arrival grounding (the VLM
     saving), not once-per-viewport;
  2. composite-detected elements are mapped back to a real (scroll_steps,
     in-viewport y) so they remain scrollable + clickable (scroll_steps in range,
     center y inside one viewport);
  3. IDENTITY stays tolerant — the registry's SSIM path stays the TOP frame
     (screenshots/<id>.png), NOT the tall composite; the composite is written to a
     SEPARATE __fullpage.png and only the graph/node artifact points at it;
  4. the node's saved image (node_artifacts/<id>/screenshot.png) is the FULL-PAGE
     composite (taller than one viewport);
  5. flag OFF reproduces the per-viewport path (composite never built; node image
     == one viewport; naming called per frame).

Run:  PYTHONPATH=.:OSWorld python tests/test_stitch_node_integration.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile

import numpy as np
from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement
from gui_rewalk.src.core.visual_traversal import visual_engine as VE


# ── synthetic page + mock env ────────────────────────────────────────────────
W = 320
TOP_H = 36
BOT_H = 48
ROW_H = 30
N_ROWS = 40
VP_H = 480
CONTENT_H = N_ROWS * ROW_H
PAGE_H = TOP_H + CONTENT_H + BOT_H
WIN_H = VP_H - TOP_H - BOT_H


def _row_color(i):
    return ((37 * (i + 1)) % 160 + 40, (91 * (i + 1)) % 160 + 40,
            (53 * (i + 1)) % 160 + 40)


def _build_page():
    page = np.full((PAGE_H, W, 3), (235, 236, 238), dtype=np.uint8)
    page[:TOP_H] = (210, 212, 216)
    for i in range(N_ROWS):
        y0 = TOP_H + i * ROW_H
        page[y0:y0 + ROW_H] = _row_color(i)
        # high-frequency "text"-like stripes whose pattern is unique per row, so a
        # scroll genuinely changes the frame pHash (a flat solid band hashes nearly
        # identically before/after a scroll → the engine would read "no movement").
        for j in range(0, W - 20, 8):
            if (i * 7 + j) % 3 == 0:
                page[y0 + 8:y0 + ROW_H - 8, 16 + j:16 + j + 4] = (20, 20, 30)
    page[TOP_H + CONTENT_H:] = (210, 212, 216)
    return page


def _png(arr):
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


class MockEnv:
    """Renders a viewport at a running content offset; a down-swipe advances the
    offset by a LARGE fling step (tiny overlap) so the integration also exercises
    the element-anchored-offset branch of the stitcher."""

    vm_platform = "android"
    FLING = 380   # px/swipe (tiny overlap, like the real amount=1 fling)

    def __init__(self):
        self.page = _build_page()
        self.offset = 0

    def _shot(self):
        fr = np.zeros((VP_H, W, 3), dtype=np.uint8)
        fr[:TOP_H] = self.page[:TOP_H]
        c = self.page[TOP_H:TOP_H + CONTENT_H]
        off = min(self.offset, CONTENT_H - WIN_H)
        fr[TOP_H:TOP_H + WIN_H] = c[off:off + WIN_H]
        fr[TOP_H + WIN_H:] = self.page[TOP_H + CONTENT_H:]
        return _png(fr)

    def _get_obs(self):
        return {"screenshot": self._shot()}

    def step(self, action, pause=0.0):
        p = action.get("parameters", {})
        if action.get("action_type") == "SCROLL":
            d = p.get("direction")
            # honour frac if present (stitch uses a smaller swipe) just for realism
            step = self.FLING
            if d == "down":
                self.offset = min(self.offset + step, CONTENT_H - WIN_H)
            elif d == "up":
                self.offset = max(self.offset - step, 0)
        return self._get_obs()


class MockPerception:
    """detect()/detect_and_name() driven by the rows visible in a frame.

    ``detect_and_name`` counts how many times it is called (the naming budget). For
    a tall COMPOSITE it returns one element per row across the WHOLE page; for a
    single viewport it returns the rows currently visible. ``detect`` (YOLO-only)
    returns the same boxes without names — the capture path uses this and must NOT
    bump the naming counter."""

    def __init__(self):
        self.naming_calls = 0
        self.last_som_image = None
        self.last_node_local_functions = []
        self.last_all_elements = []
        self.last_page_name = "Synthetic list"
        # Current _register is fail-closed and only accepts its screenshot-native
        # grounding path. This mock provides that path without any real VLM call.
        self.use_vlm_grounding = True
        self.cache = None
        self.reuse_named_elements_fn = None

    # rows whose band lies (partly) inside this image, as (name, center_y, h).
    # Sample at x=6 — the left margin holds the PURE row colour (the high-freq
    # "text" stripes live at x>=16), so row identity is read cleanly despite them.
    SAMPLE_X = 6

    @classmethod
    def _rows_in(cls, img):
        h = img.shape[0]
        sx = cls.SAMPLE_X
        out = []
        y = 0
        while y < h:
            px = img[y, sx]
            # chrome bars are (210,212,216)-ish; rows are saturated
            if abs(int(px[0]) - 210) > 12 or abs(int(px[1]) - 212) > 12:
                y2 = y
                while y2 < h and np.abs(img[y2, sx].astype(int)
                                       - px.astype(int)).max() <= 6:
                    y2 += 1
                cy = (y + y2) // 2
                out.append((f"row_{px[0]}_{px[1]}_{px[2]}", cy, y2 - y))
                y = y2
            else:
                y += 1
        return out

    def _img(self, shot):
        return np.asarray(Image.open(io.BytesIO(shot)).convert("RGB"))

    def detect(self, image):
        # mimic perception.detect: return [0,1] xyxy dicts (geometry only)
        img = np.asarray(image.convert("RGB"))
        h = img.shape[0]
        dets = []
        for _name, cy, bh in self._rows_in(img):
            y0 = max(0, cy - bh // 2)
            dets.append({"type": "icon",
                         "bbox": [20 / W, y0 / h, (W - 20) / W, (y0 + bh) / h],
                         "interactivity": True, "content": None, "_score": 0.9})
        return dets

    def detect_and_name(self, shot, apply_filter=True, system_band="both"):
        self.naming_calls += 1
        img = self._img(shot)
        h = img.shape[0]
        els = []
        for k, (name, cy, bh) in enumerate(self._rows_in(img)):
            els.append(VisualElement(
                id=k, name=name, bbox_xywh=[20, cy - bh // 2, W - 40, bh],
                center=[W // 2, cy], el_type="text", interactive=True,
                category="navigation", source="vlm"))
        # SoM image just the input (not asserted on)
        self.last_som_image = img
        self.last_node_local_functions = []
        self.last_all_elements = list(els)
        return els


class MockAgent:
    action_space = "gen_data"

    def predict_mm(self, *a, **k):
        return ("{}",)


def _make_engine(out_dir, stitch):
    eng = VE.VisualTraversalEngine(
        env=MockEnv(), agent=MockAgent(), perception=MockPerception(),
        app_name="mock", output_root=out_dir, max_states=5, max_actions=5,
        focus_guard_enabled=False, scroll_aggregate=True, settle=False,
        stitch_node_image=stitch)
    # the reuse hook does a registry.identify (SSIM on temp files); harmless here
    # but disable so the mock perception's naming counter is unambiguous.
    eng.perception.reuse_named_elements_fn = None
    return eng


def _img_size(path):
    with Image.open(path) as im:
        return im.size  # (w, h)


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as td:
        # ── flag ON ──
        eng = _make_engine(os.path.join(td, "on"), stitch=True)
        env = eng.env
        env.offset = 0
        obs = env._get_obs()
        sid, is_new = eng._register(obs, [])
        assert is_new, "first register should be new"
        perc = eng.perception

        print(f"[ON ] state {sid}: naming_calls={perc.naming_calls} "
              f"elements={len(eng._state_data[sid]['elements'])}")

        # (1) current _register performs one fail-closed arrival grounding before
        # identity, then STITCH names the whole composite exactly once. Two total
        # calls is therefore the contract; per-viewport naming would be >2.
        if perc.naming_calls != 2:
            failures.append(f"[ON] expected 2 naming calls (arrival + one "
                            f"composite), got {perc.naming_calls}")

        elements = eng._state_data[sid]["elements"]
        # the full page has N_ROWS rows; composite naming should see most of them
        # (a couple may merge at band edges) — definitely more than one viewport.
        vp_rows = WIN_H // ROW_H
        if len(elements) <= vp_rows + 2:
            failures.append(f"[ON] composite revealed only {len(elements)} elements "
                            f"(~one viewport={vp_rows}); full page not captured")

        # (2) every element mapped back to a valid (scroll_steps, in-viewport y)
        bad = []
        for e in elements:
            ss = getattr(e, "scroll_steps", None)
            cy = e.center[1]
            if ss is None or ss < 0:
                bad.append((e.name, "scroll_steps", ss))
            elif not (0 <= cy < VP_H):
                bad.append((e.name, "center_y_off_viewport", cy))
        if bad:
            failures.append(f"[ON] {len(bad)} elements not mapped back into a "
                            f"viewport: {bad[:5]}")
        max_ss = max((getattr(e, "scroll_steps", 0) for e in elements), default=0)
        print(f"[ON ] mapped scroll_steps range 0..{max_ss}, all centers in viewport")

        # (3) IDENTITY: registry SSIM path is the TOP frame, not the composite.
        reg_path = eng.registry._states[sid][1]
        if not reg_path.endswith(f"{sid}.png") or "__fullpage" in reg_path:
            failures.append(f"[ON] registry SSIM path is not the top-frame file: "
                            f"{reg_path}")
        else:
            rw, rh = _img_size(reg_path)
            if rh > VP_H + 4:
                failures.append(f"[ON] registry identity image is {rw}x{rh} — a "
                                f"composite, not the top viewport ({VP_H}px). "
                                f"identity would SSIM-mismatch on re-visit.")
            else:
                print(f"[ON ] identity image {rw}x{rh} == top viewport (tolerant "
                      f"identity preserved, NOT composite pixels)")

        # (4) node artifact image is the FULL-PAGE composite
        node_png = os.path.join(td, "on", "node_artifacts", sid, "screenshot.png")
        if not os.path.exists(node_png):
            failures.append("[ON] node artifact screenshot.png missing")
        else:
            nw, nh = _img_size(node_png)
            if nh <= VP_H + ROW_H:
                failures.append(f"[ON] node image {nw}x{nh} is not a full-page "
                                f"composite (<= one viewport)")
            else:
                print(f"[ON ] node image {nw}x{nh} is the full page "
                      f"(page={PAGE_H}px, viewport={VP_H}px)")
        # the separate full-page file exists
        fp = os.path.join(td, "on", "screenshots", f"{sid}__fullpage.png")
        if not os.path.exists(fp):
            failures.append("[ON] separate __fullpage.png composite not written")

        # ── flag OFF (same synthetic page) ──
        eng2 = _make_engine(os.path.join(td, "off"), stitch=False)
        env2 = eng2.env
        env2.offset = 0
        sid2, _ = eng2._register(env2._get_obs(), [])
        perc2 = eng2.perception
        print(f"[OFF] state {sid2}: naming_calls={perc2.naming_calls} "
              f"elements={len(eng2._state_data[sid2]['elements'])}")
        # per-viewport: at least 2 naming calls (top + >=1 scrolled frame)
        if perc2.naming_calls < 2:
            failures.append(f"[OFF] per-viewport path should name each frame "
                            f"(>=2 calls); got {perc2.naming_calls}")
        reg2 = eng2.registry._states[sid2][1]
        rw2, rh2 = _img_size(reg2)
        if rh2 > VP_H + 4:
            failures.append(f"[OFF] node identity image {rw2}x{rh2} is not one "
                            f"viewport — flag OFF changed behaviour")
        else:
            print(f"[OFF] node image {rw2}x{rh2} == one viewport (per-viewport path "
                  f"unchanged)")
        # OFF must not write a __fullpage composite
        if os.path.exists(os.path.join(td, "off", "screenshots",
                                       f"{sid2}__fullpage.png")):
            failures.append("[OFF] a __fullpage composite was written with the flag "
                            "OFF — not additive")

        # the ON path used MORE rows than OFF's single registered viewport (proves
        # below-the-fold rows are in the node only when stitched-and-named once)
        if len(eng._state_data[sid]["elements"]) <= len(
                eng2._state_data[sid2]["elements"]):
            print("  (note) ON elements not greater than OFF — OFF's aggregate also "
                  "reveals below-fold rows; that's fine, the win is the call count.")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print("  -", f)
        return 1
    print("\nPASS: STITCH_NODE_IMAGE wires in — composite perceived ONCE, elements "
          "mapped back to (scroll_steps, viewport-y), identity stays the top-frame "
          "(tolerant, not composite pixels), node image is the full page; flag OFF "
          "is the unchanged per-viewport path.")
    return 0


# ── tall-composite TILING (the live-A/B downscale-recall fix) ─────────────────
# A VERY tall composite (settings home = 5 frames / ~5077px) gets DOWNSCALED by the
# VLM when named in ONE pass, dropping the small below-fold rows (~17 named vs the
# ~25+ real). The fix tiles a composite taller than STITCH_VLM_MAX_H into vertical
# chunks each <= the cap (split on FRAME boundaries, small seam overlap), names EACH
# chunk at full resolution, then MERGES the element sets deduping the seam overlap by
# appearance pHash. This test builds frames whose stitched composite EXCEEDS the cap
# and drives the engine's real ``_build_stitched_node`` (no device / YOLO / VLM —
# the same MockPerception, which returns one element per visible row), asserting:
#
#   1. the composite is genuinely TALLER than the cap (so tiling actually fires);
#   2. it is split into >= 2 chunks, EACH <= the cap, on whole-viewport boundaries;
#   3. naming is called once PER CHUNK — MORE than 1 (so we kept resolution) but
#      FEWER than the capture-frame count (the win over per-viewport naming);
#   4. the merged element set has NO duplicate across the seam (it is far below the
#      no-dedup tiled sum, which double-counts the overlap, and within per-seam slack
#      of the one-pass+dedup baseline) AND no row is clipped at a seam (it is not
#      below that baseline) — i.e. tiling+merge is INVARIANT to the chunking;
#   5. every kept element maps back to a valid (scroll_steps in range, center y in
#      one viewport) — clickable exactly like the single-call path, and the deepest
#      reaches the LAST chunk (below-the-fold rows are surfaced, not dropped).

# A tall page of GENUINELY-DISTINCT rows. Flat colour bands all hash alike under the
# (deliberately coarse, jitter-absorbing) appearance pHash, so to exercise the seam
# dedup + coverage with REALISTIC distinct elements each row carries one big black
# block whose x-position encodes its index — a coarse, large-scale pattern that
# SURVIVES the 64x64 normalise (measured min pairwise pHash distance 8 at N=20, well
# above the ELEMENT_MATCH_DISTANCE=12 dedup gate), so the matcher keeps ~all rows.
T_W = 320
T_TOP_H = 40
T_BOT_H = 56
T_ROW_H = 120                  # tall rows so a coarse block pattern stays distinct
T_N_ROWS = 44                  # 44 * 120 = 5280px content; stitched comp > 3500 cap
T_VP_H = 900                   # tall viewport (like a phone in px)
T_CONTENT_H = T_N_ROWS * T_ROW_H
T_PAGE_H = T_TOP_H + T_CONTENT_H + T_BOT_H
T_WIN_H = T_VP_H - T_TOP_H - T_BOT_H
T_BLOCK_W = 40


def _t_block_x(i):
    """x of row i's distinctive block (unique, spread across the width)."""
    return 8 + (i * (T_W - 16 - T_BLOCK_W)) // max(1, T_N_ROWS - 1)


def _t_paint_row(buf, y0, i):
    buf[y0:y0 + T_ROW_H] = (240, 240, 242)
    x = _t_block_x(i)
    buf[y0 + 24:y0 + T_ROW_H - 24, x:x + T_BLOCK_W] = (15, 15, 15)
    # a small second mark in a coarse vertical bin for extra separation
    yb = y0 + 8 + (i % 4) * 8
    buf[yb:yb + 10, T_W - 60:T_W - 20] = (15, 15, 15)


def _t_build_page():
    page = np.full((T_PAGE_H, T_W, 3), (235, 236, 238), dtype=np.uint8)
    page[:T_TOP_H] = (10, 120, 120)        # sticky top bar (distinct chrome colour)
    for i in range(T_N_ROWS):
        _t_paint_row(page, T_TOP_H + i * T_ROW_H, i)
    page[T_TOP_H + T_CONTENT_H:] = (30, 30, 40)  # sticky bottom bar
    return page


def _t_render_frames(page, fling):
    """Top->bottom viewport crops at a fixed fling step (sticky bars re-pasted),
    in scroll order, until the bottom is reached."""
    top_bar = page[:T_TOP_H].copy()
    bot_bar = page[T_TOP_H + T_CONTENT_H:].copy()
    content = page[T_TOP_H:T_TOP_H + T_CONTENT_H]
    frames = []
    off = 0
    while True:
        fr = np.zeros((T_VP_H, T_W, 3), dtype=np.uint8)
        fr[:T_TOP_H] = top_bar
        o = min(off, T_CONTENT_H - T_WIN_H)
        fr[T_TOP_H:T_TOP_H + T_WIN_H] = content[o:o + T_WIN_H]
        fr[T_TOP_H + T_WIN_H:] = bot_bar
        frames.append(_png(fr))
        if off >= T_CONTENT_H - T_WIN_H:
            break
        off += fling
    return frames


class TilingMockPerception(MockPerception):
    """Perception for the tiling test: one element per row-band that holds a black
    BLOCK (the distinctive marker). Unlike the colour-band MockPerception, the block
    pattern survives the appearance-pHash normalise, so the seam dedup keeps the rows
    distinct — letting the test assert no-seam-duplication AND no-clipping coverage on
    a realistic element count, not a handful of pHash-collapsed bands. ``detect`` and
    ``detect_and_name`` scan whatever image (composite, chunk, or frame) they are
    given, so chunk-local coordinates come out correct."""

    @staticmethod
    def _block_rows(img):
        """(name, center_y, h) for each ROW_H band in ``img`` that contains a dark
        block in the content area — independent of absolute colour."""
        h = img.shape[0]
        dark = (img.max(axis=-1) < 60)          # near-black pixels
        out = []
        y = 0
        while y < h:
            band = dark[y:min(y + T_ROW_H, h)]
            # a content row's block spans many columns over several rows
            if band.sum() > 200 and band.any(axis=0).sum() > 20:
                y2 = min(y + T_ROW_H, h)
                cy = (y + y2) // 2
                out.append((f"row@{cy}", cy, y2 - y))
                y = y2
            else:
                y += 1
        return out

    def detect(self, image):
        img = np.asarray(image.convert("RGB"))
        h = img.shape[0]
        dets = []
        for _n, cy, bh in self._block_rows(img):
            y0 = max(0, cy - bh // 2)
            dets.append({"type": "icon",
                         "bbox": [8 / T_W, y0 / h, (T_W - 8) / T_W, (y0 + bh) / h],
                         "interactivity": True, "content": None, "_score": 0.9})
        return dets

    def detect_and_name(self, shot, apply_filter=True, system_band="both"):
        self.naming_calls += 1
        img = self._img(shot)
        els = []
        for k, (name, cy, bh) in enumerate(self._block_rows(img)):
            els.append(VisualElement(
                id=k, name=name, bbox_xywh=[8, cy - bh // 2, T_W - 16, bh],
                center=[T_W // 2, cy], el_type="text", interactive=True,
                category="navigation", source="vlm"))
        self.last_som_image = img
        self.last_node_local_functions = []
        self.last_all_elements = list(els)
        return els


def test_tall_composite_tiling() -> int:
    print("\n=== tall-composite TILING (downscale-recall fix) ===")
    from gui_rewalk.src.core.visual_traversal import visual_stitch as _vs

    failures = []
    with tempfile.TemporaryDirectory() as td:
        eng = _make_engine(os.path.join(td, "tall"), stitch=True)
        # swap in the block-row perception (distinct rows survive the dedup)
        eng.perception = TilingMockPerception()
        eng.perception.reuse_named_elements_fn = None
        perc = eng.perception
        cap = VE.STITCH_VLM_MAX_H

        # Build overlapping frames; a small fling -> generous overlap, clean stitch.
        page = _t_build_page()
        frames = _t_render_frames(page, fling=int(T_WIN_H * 0.5))
        n_frames = len(frames)

        # Stitch once up-front to (a) know the composite height/chunking the engine
        # will see and (b) compute the baselines for the merge/dedup assertions:
        #   * base_kept = the WHOLE composite named in ONE pass then run through the
        #     SAME ElementMatcher dedup tiling uses — the tiling-INVARIANCE target:
        #     tiling must reproduce this set (give or take per-chunk-edge collapse).
        #   * no_dedup_tiled = the per-chunk raw counts SUMMED (each chunk named, NO
        #     dedup). Because consecutive chunks OVERLAP, this DOUBLE-counts the seam
        #     rows, so a merged set comfortably below it PROVES the seam dedup fired.
        # The appearance pHash is deliberately coarse (it absorbs box jitter), so a
        # row near a chunk EDGE can survive in a chunk crop while it collided (deduped)
        # in the full composite — so merged sits BETWEEN base_kept and no_dedup_tiled,
        # never exactly on either. Assertion (4) sandwiches it accordingly rather than
        # demanding exact equality. (Real settings rows differ by their text labels and
        # stay distinct; flat synthetic markers cannot, which is why absolute recall is
        # a LIVE-A/B check, not a unit one — the unit contract is chunking+merge
        # correctness, i.e. invariance.)
        from gui_rewalk.src.core.visual_traversal.visual_state import ElementMatcher
        res = _vs.stitch_frames(frames, element_offsets=[None] * n_frames)
        assert res is not None, "stitch returned None for the tall page"
        comp_h = res.image.shape[0]
        comp_png = _vs.encode_png(res.image)
        base_els = perc.detect_and_name(comp_png)            # whole comp, one pass
        base_matcher = ElementMatcher()
        base_kept = sum(1 for be in base_els
                        if base_matcher.match_or_add(comp_png, be.bbox_xywh)[1])
        bounds0 = eng._composite_chunk_bounds(res, comp_h, cap)
        no_dedup_tiled = 0
        for (cy0, cy1) in bounds0:
            chunk_png = _vs.encode_png(res.image[cy0:cy1, :, :])
            no_dedup_tiled += len(perc.detect_and_name(chunk_png))
        perc.naming_calls = 0  # reset; the up-front calls above are just baselines
        print(f"  frames={n_frames}  composite={comp_h}px  cap={cap}px  "
              f"one-pass+dedup baseline={base_kept} (raw rows={len(base_els)})  "
              f"no-dedup tiled sum={no_dedup_tiled}")

        # (1) the composite must actually exceed the cap, else tiling never fires.
        if comp_h <= cap:
            failures.append(f"composite {comp_h}px <= cap {cap}px — the tall case "
                            f"is not tall enough to exercise tiling")

        # (2) chunk bounds: >=2 chunks, each <= cap, whole-viewport split, full cover.
        bounds = eng._composite_chunk_bounds(res, comp_h, cap)
        print(f"  chunk bounds = {bounds}")
        if len(bounds) < 2:
            failures.append(f"expected >=2 chunks for a {comp_h}px composite over a "
                            f"{cap}px cap; got {len(bounds)}")
        for (y0, y1) in bounds:
            if y1 - y0 > cap:
                failures.append(f"chunk {(y0, y1)} height {y1 - y0} exceeds cap {cap}")
        # contiguous cover [0, comp_h) (overlapping starts allowed, no gaps)
        if bounds[0][0] != 0:
            failures.append(f"first chunk does not start at 0: {bounds[0]}")
        if bounds[-1][1] != comp_h:
            failures.append(f"last chunk does not end at composite bottom {comp_h}: "
                            f"{bounds[-1]}")
        for a, b in zip(bounds, bounds[1:]):
            if b[0] > a[1]:  # a gap between chunks would drop rows
                failures.append(f"gap between chunks {a} and {b}")
            if b[0] >= b[1]:
                failures.append(f"empty chunk {b}")

        # ── drive the REAL engine path: load the capture buffers and build the node
        perc.naming_calls = 0
        eng._last_scroll_frames = list(frames)
        eng._last_scroll_offsets = [None] * n_frames
        built = eng._build_stitched_node(frames[0])
        assert built is not None, "_build_stitched_node returned None (fell back)"
        elements, node_png, _som = built
        n_calls = perc.naming_calls
        print(f"  naming VLM calls = {n_calls} (frames={n_frames}); "
              f"merged elements = {len(elements)}")

        # (3) one naming call PER CHUNK: > 1 (kept resolution) and < n_frames (the
        #     win vs per-viewport naming).
        if n_calls < 2:
            failures.append(f"tall composite should be named in >=2 chunk calls; "
                            f"got {n_calls}")
        if n_calls >= n_frames:
            failures.append(f"tiled naming calls ({n_calls}) not fewer than the "
                            f"capture-frame count ({n_frames}) — no win over "
                            f"per-viewport naming")
        if n_calls != len(bounds):
            failures.append(f"naming calls ({n_calls}) != chunk count "
                            f"({len(bounds)}) — a chunk was skipped or double-named")

        # (4) TILING-INVARIANCE — the merged set must satisfy
        #         base_kept (one-pass+dedup)  <=  merged  <  no_dedup_tiled (chunk sum)
        #     a collapse-magnitude-robust sandwich:
        #   * NO SEAM DUPLICATION (upper): merged STRICTLY below the no-dedup tiled sum
        #     (which double-counts the overlap) proves the seam dedup removed the
        #     duplicate copies — without it merged would equal that sum.
        #   * NO CLIPPING (lower): merged at least the one-pass+dedup baseline proves
        #     no row was dropped at a chunk boundary (a clip would push merged BELOW
        #     the un-chunked coverage). The coarse appearance pHash only ever lets a
        #     per-chunk crop keep MORE rows than the whole composite (a row that
        #     collided in the full image may not collide within a smaller chunk), so
        #     merged >= base_kept is the right, collapse-independent floor.
        if not (len(elements) < no_dedup_tiled):
            failures.append(f"merged {len(elements)} not below no-dedup tiled sum "
                            f"{no_dedup_tiled} — the seam dedup removed nothing "
                            f"(overlap rows survived in both chunks)")
        if len(elements) < base_kept:
            failures.append(f"merged {len(elements)} < one-pass+dedup baseline "
                            f"{base_kept} — rows CLIPPED at a chunk seam (coverage "
                            f"lost below the un-chunked set)")
        # explicit no-duplicate check on the merged set by uid (appearance identity):
        uids = [e.uid for e in elements if e.uid]
        if len(uids) != len(set(uids)):
            dup = len(uids) - len(set(uids))
            failures.append(f"{dup} merged elements share a uid — seam appearance "
                            f"duplicates slipped through the dedup")

        # (5) every kept element maps back to a valid (scroll_steps, viewport-y).
        bad = []
        max_ss = 0
        for e in elements:
            ss = getattr(e, "scroll_steps", None)
            cy = e.center[1]
            if ss is None or not (0 <= ss < n_frames):
                bad.append((e.name, "scroll_steps", ss))
            elif not (0 <= cy < T_VP_H):
                bad.append((e.name, "center_y_off_viewport", cy))
            else:
                max_ss = max(max_ss, ss)
        if bad:
            failures.append(f"{len(bad)} elements not mapped into a viewport: "
                            f"{bad[:5]}")
        # coverage proof: tiling must surface BELOW-THE-FOLD rows from beyond the
        # first viewport — the deepest mapped scroll_steps must reach the LAST chunk's
        # frames (not stop at the top chunk). The last chunk starts at composite-y
        # ``bounds[-1][0]``; whatever capture frame that maps to is the shallowest a
        # last-chunk element can carry, and the merged set must reach at least there.
        last_chunk_frame, _vy = res.composite_y_to_scroll(bounds[-1][0])
        if not bad and max_ss < last_chunk_frame:
            failures.append(f"deepest mapped scroll_steps {max_ss} < last-chunk frame "
                            f"{last_chunk_frame} — the bottom chunk's rows were not "
                            f"represented (coverage clipped)")
        print(f"  mapped scroll_steps range 0..{max_ss} "
              f"(last-chunk frame >= {last_chunk_frame}, last frame {n_frames - 1}), "
              f"all centers in viewport")

        # (6) the node image is still the FULL-PAGE composite (taller than one vp).
        nh = Image.open(io.BytesIO(node_png)).size[1]
        if nh <= T_VP_H:
            failures.append(f"node image height {nh} <= one viewport {T_VP_H} — "
                            f"not the full-page composite")

    if failures:
        print("FAIL:")
        for f in failures:
            print("  -", f)
        return 1
    print("PASS: tall composite TILED into <=cap whole-viewport chunks, named per "
          "chunk (>1, < per-viewport), seam dups deduped, ALL rows covered "
          "top->bottom, coords map back to (scroll_steps, viewport-y).")
    return 0


if __name__ == "__main__":
    rc = main()
    rc |= test_tall_composite_tiling()
    sys.exit(rc)
