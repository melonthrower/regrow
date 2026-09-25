"""Full-page screenshot STITCHING for a scrollable page (a11y-free).

Takes the ORDERED frames captured by ``visual_engine._scroll_aggregate`` (top→
bottom swipes) and reconstructs ONE tall composite image = the page's canonical
"state image". Two problems are solved purely with cv2 / numpy:

  (a) OVERLAP between consecutive frames. A down-swipe moves the content up by an
      UNKNOWN, non-deterministic amount (fling momentum), and the frames overlap.
      We recover the exact per-frame vertical shift by template-matching a strip
      from the bottom of the SCROLLING band of frame N into frame N+1 (1-D search
      over y), then append only the genuinely-new content below the overlap. No
      row is duplicated and no gap is left.

  (b) STICKY bars. A sticky top app-bar and/or a sticky bottom nav repeat in
      every frame and do NOT move with the content. If we blindly concatenated
      the new band we would either re-paste the sticky bottom bar N times or, when
      measuring the shift, mistake the unchanging sticky region for "no scroll".
      We detect the sticky bands by finding, from the top and from the bottom, the
      maximal run of rows that are (near-)identical between two well-separated
      frames — those rows never move, hence they are chrome. The shift is then
      measured ONLY on the middle SCROLLING band, the sticky top bar is kept once
      (from the first frame), the scrolling content is stitched, and the sticky
      bottom bar is kept once (from the last frame).

The function also returns a y-MAP: composite-y -> (frame_index, in-frame y) for
every stitched row, so a detected element's composite-y can be turned back into
"which swipe + where in that viewport" — exactly the ``scroll_steps`` mechanism
the engine already uses to scroll a below-the-fold element into view before
clicking it (see ``visual_engine._scroll_locate``).

This module is STANDALONE: it imports nothing from the live engine and the engine
imports nothing from it. It is a prototype for evaluating the stitched-image-as-
node-representation idea; wiring it in is a separate, deliberate step.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ── tunables ────────────────────────────────────────────────────────────────
# A row of frame N and the corresponding row of frame N+1 count as "the same"
# (used for sticky-bar detection) if their mean absolute per-pixel difference is
# below this (0..255). Small but non-zero to absorb JPEG/scaling noise and a
# blinking caret / clock second.
STICKY_ROW_MAD = 6.0
# Fraction of a row's pixels allowed to differ a LOT (e.g. a moving caret inside
# an otherwise static search bar) before the row is declared "moving". Combined
# with the MAD gate so a single animated pixel run doesn't break a sticky band.
STICKY_ROW_OUTLIER_FRAC = 0.04
# Hard ceiling on how tall a detected sticky band may be, as a fraction of frame
# height — a sticky bar is chrome, never half the screen. Guards against a page
# that genuinely didn't scroll (two identical frames) being read as "all sticky".
STICKY_MAX_FRAC = 0.30
# Template-match score (TM_CCOEFF_NORMED) below which the measured overlap shift
# is not trusted (caller falls back to "assume the whole new band is new").
SHIFT_MATCH_MIN = 0.55
# Height of the probe strip taken from the bottom of frame N's scrolling band,
# as a fraction of the scrolling-band height, to locate in frame N+1.
PROBE_STRIP_FRAC = 0.22
# Min probe-strip height in px (a too-thin strip matches everywhere).
PROBE_STRIP_MIN_PX = 24
# Below this measured shift (px) two consecutive frames are treated as the same
# view (no real scroll happened — bottom reached / non-scrollable).
MIN_SHIFT_PX = 6
# When BOTH a pixel shift (score >= SHIFT_MATCH_MIN) and an element-anchored offset
# are available, the pixel value is kept only if the two AGREE within this many px
# (box-jitter slack). A larger disagreement means the high pixel score is a
# false-confident wrong match (tiny-overlap fling latching onto a repeated region),
# so the element offset — measured from matched real controls — is taken instead.
ELEMENT_PIXEL_AGREE_PX = 24


# ── data carrier ────────────────────────────────────────────────────────────
@dataclass
class StitchResult:
    """Output of :func:`stitch_frames`.

    Attributes
    ----------
    image : np.ndarray
        The composite full-page image (RGB, HxWx3, uint8).
    y_map : np.ndarray
        Shape (H, 2), int32. ``y_map[Y] == (frame_index, in_frame_y)`` — the
        frame and in-that-frame row that composite row ``Y`` was painted from.
        This is the inverse of the scroll: it tells the engine WHICH swipe-step
        (frame_index) brings a composite-y element back on screen and at what
        in-viewport y it then sits. Sticky-top rows map to frame 0; sticky-bottom
        rows map to the last frame.
    sticky_top_h : int
        Height (px) of the detected sticky top app-bar (0 if none).
    sticky_bot_h : int
        Height (px) of the detected sticky bottom nav bar (0 if none).
    frame_h : int
        Height (px) of one input viewport frame (all frames assumed equal size).
    frame_top_in_composite : List[int]
        ``frame_top_in_composite[i]`` = the composite-y at which frame ``i``'s
        TOP edge sits (i.e. where this viewport begins in the full page). Lets the
        forward map composite-y -> scroll-step be computed without scanning y_map.
    system_top_h / system_bot_h : int
        Fixed platform-system bands supplied by the caller. These are subsets of
        ``sticky_top_h`` / ``sticky_bot_h``: the latter may additionally include
        a real app toolbar or bottom navigation surface. Keeping them separate
        lets tiled perception reject Android status/gesture UI by row provenance
        without suppressing app chrome.
    """

    image: np.ndarray
    y_map: np.ndarray
    sticky_top_h: int = 0
    sticky_bot_h: int = 0
    frame_h: int = 0
    frame_top_in_composite: List[int] = field(default_factory=list)
    system_top_h: int = 0
    system_bot_h: int = 0

    # ── element ⇄ composite helpers (mirror scroll_steps) ───────────────────
    def composite_y_to_scroll(self, comp_y: int) -> Tuple[int, int]:
        """Composite-y -> (frame_index a.k.a. scroll_steps, in-viewport y).

        The engine scrolls a below-the-fold element into view by swiping down
        ``scroll_steps`` times; this returns the frame (= swipe depth) on which
        ``comp_y`` is visible and the y it occupies there, so a composite-detected
        element can be scrolled in and clicked exactly like a per-viewport one."""
        comp_y = int(max(0, min(self.image.shape[0] - 1, comp_y)))
        fi, in_y = self.y_map[comp_y]
        return int(fi), int(in_y)

# [2026-07-07 用户 删除] scroll_to_composite_y(拼接图坐标逆变换)已删,零调用。


# ── image helpers ───────────────────────────────────────────────────────────
def _to_rgb(shot) -> Optional[np.ndarray]:
    """PNG bytes / path / PIL / ndarray -> RGB uint8 HxWx3."""
    if isinstance(shot, np.ndarray):
        if shot.ndim == 2:
            return np.stack([shot] * 3, axis=-1).astype(np.uint8)
        return shot[:, :, :3].astype(np.uint8)
    from PIL import Image
    if isinstance(shot, (bytes, bytearray)):
        return np.asarray(Image.open(io.BytesIO(bytes(shot))).convert("RGB"))
    if isinstance(shot, str):
        return np.asarray(Image.open(shot).convert("RGB"))
    if isinstance(shot, Image.Image):
        return np.asarray(shot.convert("RGB"))
    return None


def _row_diff(a: np.ndarray, b: np.ndarray) -> Tuple[float, float]:
    """(mean-abs-diff, fraction-of-strongly-differing-pixels) between two equal-
    shape row blocks. Used to decide whether a row 'moved' between frames."""
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    mad = float(d.mean())
    # a pixel "strongly differs" if any channel moved > 24 levels
    strong = (d.max(axis=-1) > 24)
    frac = float(strong.mean())
    return mad, frac


def _rows_equal(a: np.ndarray, b: np.ndarray) -> bool:
    mad, frac = _row_diff(a, b)
    return mad <= STICKY_ROW_MAD and frac <= STICKY_ROW_OUTLIER_FRAC


# ── sticky-band detection ───────────────────────────────────────────────────
def detect_sticky_bands(
    frames: List[np.ndarray],
    min_top_h: int = 0,
    min_bot_h: int = 0,
) -> Tuple[int, int]:
    """Return (sticky_top_h, sticky_bot_h) in px.

    A sticky band is a maximal run of rows that stay (near-)identical across
    frames that are KNOWN to have scrolled relative to each other. We compare the
    first frame against the LAST frame (maximally separated → the content band is
    guaranteed different, so any rows that are still identical are genuinely
    pinned chrome, not coincidentally-similar content). The runs are measured from
    the top edge downward (sticky top bar) and from the bottom edge upward (sticky
    bottom nav), then clamped to ``STICKY_MAX_FRAC`` of the frame height so a
    non-scrolling page can't be read as all-chrome.

    ``min_top_h`` / ``min_bot_h`` are deterministic platform bands that must be
    treated as sticky even when their pixels change between frames (Android's
    clock, signal indicators, or navigation-hint animation). Detection continues
    immediately inside those bands, so an adjacent *app* toolbar can still extend
    the inferred sticky range. This avoids one dynamic system row collapsing the
    inferred band to zero and pasting the gesture bar at every composite seam.
    """
    if len(frames) < 2:
        return 0, 0
    a = frames[0]
    b = frames[-1]
    h = min(a.shape[0], b.shape[0])
    cap = int(h * STICKY_MAX_FRAC)

    top = min(cap, max(0, int(min_top_h)))
    while top < cap and _rows_equal(a[top:top + 1], b[top:top + 1]):
        top += 1

    bot = min(cap, max(0, int(min_bot_h)))
    while bot < cap and _rows_equal(a[h - 1 - bot:h - bot], b[h - 1 - bot:h - bot]):
        bot += 1

    return top, bot


# ── overlap / shift estimation ──────────────────────────────────────────────
def estimate_shift(prev: np.ndarray, cur: np.ndarray,
                   top: int, bot: int) -> Tuple[int, float]:
    """Vertical pixels the CONTENT moved up from ``prev`` to ``cur``.

    Restricting the search to the scrolling band ``[top, H-bot)`` (the sticky bars
    excluded), take a probe strip near the BOTTOM of ``prev``'s scrolling band and
    1-D template-match it down ``cur``'s scrolling band. The y at which it matches,
    minus where it sat in ``prev``, is the shift. Returns (shift_px, score). A
    score below ``SHIFT_MATCH_MIN`` means the match is unreliable.
    """
    import cv2

    H = min(prev.shape[0], cur.shape[0])
    band_lo = top
    band_hi = H - bot
    band_h = band_hi - band_lo
    if band_h <= PROBE_STRIP_MIN_PX:
        return 0, 0.0

    strip_h = max(PROBE_STRIP_MIN_PX, int(band_h * PROBE_STRIP_FRAC))
    strip_h = min(strip_h, band_h - 2)
    # take the strip from the bottom of prev's scrolling band (most likely to have
    # scrolled up into cur's visible area)
    strip_y0 = band_hi - strip_h
    strip = prev[strip_y0:band_hi, :, :]
    scene = cur[band_lo:band_hi, :, :]
    if strip.shape[0] >= scene.shape[0] or strip.shape[1] < 1:
        return 0, 0.0

    s_gray = cv2.cvtColor(scene, cv2.COLOR_RGB2GRAY)
    t_gray = cv2.cvtColor(strip, cv2.COLOR_RGB2GRAY)
    try:
        res = cv2.matchTemplate(s_gray, t_gray, cv2.TM_CCOEFF_NORMED)
        _mn, score, _ml, maxloc = cv2.minMaxLoc(res)
    except Exception as e:
        logger.debug("estimate_shift matchTemplate failed: %s", e)
        return 0, 0.0

    # maxloc[1] is the y (within the scene band) where prev's bottom strip now
    # sits in cur. prev's strip used to sit at (strip_y0 - band_lo) within the
    # band; the content moved up by the difference.
    matched_band_y = maxloc[1]
    prev_band_y = strip_y0 - band_lo
    shift = prev_band_y - matched_band_y
    return int(shift), float(score)


# ── main stitch ─────────────────────────────────────────────────────────────
def stitch_frames(frames_in: List, debug: bool = False,
                  element_offsets: Optional[List[Optional[float]]] = None,
                  system_top_h: int = 0,
                  system_bot_h: int = 0,
                  ) -> Optional[StitchResult]:
    """Stitch ORDERED top→bottom scroll frames into one full-page composite.

    Parameters
    ----------
    frames_in : list of (PNG bytes | path | PIL.Image | ndarray)
        Viewport screenshots in scroll order (index 0 = page top). All must be the
        same WxH (the device viewport); mismatched frames are skipped.
    debug : bool
        Log per-frame shift / sticky decisions.
    element_offsets : optional list, parallel to ``frames_in``
        ``element_offsets[i]`` = the content shift (px the content moved UP) from
        frame ``i-1`` to frame ``i``, as measured by the caller from the
        y-positions of the SAME element matched across the two frames (the engine's
        ``ElementMatcher`` already matches each element across the scroll). It is a
        ROBUST shift in the two regimes where the pixel template-match fails: a
        flat, low-texture list (a near-uniform strip matches everywhere → weak
        score) AND the production large fling (only ~1 row of overlap → the matcher
        latches onto a repeated region and returns a confidently-WRONG shift with a
        HIGH score). When a plausible element offset is present it is PREFERRED over
        the pixel shift unless the pixel match is strong AND agrees with it (within
        ``ELEMENT_PIXEL_AGREE_PX``), in which case the px-exact pixel value is kept.
        ``None`` / a non-positive / an implausibly large value for an entry means
        "no usable element offset" → fall back to the pixel-only behaviour.
        ``element_offsets[0]`` is ignored (frame 0 is the seed, no predecessor).
    system_top_h / system_bot_h : int
        Fixed system-UI bands in input-frame pixels. Use these for touch/Android
        screenshots where the platform status and gesture bars are known geometry
        but are not pixel-stable. They are kept once at the composite exterior and
        excluded from every appended content block. Defaults preserve the generic
        pixel-only sticky detection used by existing callers.

    Returns
    -------
    StitchResult or None
        None only when there are zero decodable frames.

    Algorithm
    ---------
    1. Detect the sticky top / bottom bands once (first-vs-last frame).
    2. Seed the canvas with frame 0 in full (sticky top + its content + sticky
       bottom). Record its y-map.
    3. For each subsequent frame, measure the content shift vs the previous frame
       over the scrolling band only. When the pixel match is unreliable and an
       element-anchored offset is supplied, use that instead. Append the bottom
       ``shift`` px of this frame's SCROLLING band (the genuinely-new content)
       below the canvas's current content tail, and extend the y-map to point at
       this frame's rows. A sub-threshold shift with no element offset means no
       new content (bottom reached) → skip.
    4. Re-attach the sticky bottom bar once at the very end (taken from the last
       frame), and patch the y-map of those rows to the last frame.
    """
    # Decode frames but REMEMBER which originals survived, so element_offsets
    # (indexed against frames_in) can be re-aligned to the decoded list — a dropped
    # oddball frame must not silently shift every subsequent offset by one.
    frames: List[np.ndarray] = []
    kept_idx: List[int] = []
    for src_i, f in enumerate(frames_in):
        img = _to_rgb(f)
        if img is not None and img.ndim == 3 and img.shape[0] > 1:
            frames.append(img)
            kept_idx.append(src_i)
    if not frames:
        return None

    # enforce a common width/height (use the first frame's); drop oddballs, keeping
    # kept_idx in lock-step so element_offsets can be re-aligned to the survivors.
    H0, W0 = frames[0].shape[:2]
    _kept = [(j, f) for j, f in zip(kept_idx, frames)
             if f.shape[0] == H0 and f.shape[1] == W0]
    if not _kept:
        return None
    kept_idx = [j for j, _ in _kept]
    frames = [f for _, f in _kept]

    # Keep caller-provided platform bands sane and disjoint. They are deliberately
    # bounded by the same chrome ceiling as inferred sticky bars: a platform band
    # can never consume half a viewport. Zero keeps the historical generic path.
    chrome_cap = int(H0 * STICKY_MAX_FRAC)
    system_top_h = min(chrome_cap, max(0, int(system_top_h or 0)))
    system_bot_h = min(chrome_cap, max(0, int(system_bot_h or 0)))
    if system_top_h + system_bot_h >= H0:
        system_top_h = system_bot_h = 0

    # Re-align the caller's per-original-frame offsets onto the surviving frames.
    # elem_off[i] is the content-shift from surviving-frame i-1 -> i (i>=1).
    elem_off: List[Optional[float]] = [None] * len(frames)
    if element_offsets:
        for i, src_i in enumerate(kept_idx):
            if 0 <= src_i < len(element_offsets):
                v = element_offsets[src_i]
                try:
                    elem_off[i] = float(v) if v is not None else None
                except (TypeError, ValueError):
                    elem_off[i] = None

    if len(frames) == 1:
        # nothing to stitch — the page fit in one viewport
        ymap = np.empty((H0, 2), dtype=np.int32)
        ymap[:, 0] = 0
        ymap[:, 1] = np.arange(H0, dtype=np.int32)
        return StitchResult(image=frames[0].copy(), y_map=ymap,
                            sticky_top_h=0, sticky_bot_h=0, frame_h=H0,
                            frame_top_in_composite=[0],
                            system_top_h=system_top_h,
                            system_bot_h=system_bot_h)

    sticky_top_h, sticky_bot_h = detect_sticky_bands(
        frames, min_top_h=system_top_h, min_bot_h=system_bot_h)
    if debug:
        logger.info("stitch: sticky_top=%dpx sticky_bot=%dpx over %d frames",
                    sticky_top_h, sticky_bot_h, len(frames))

    content_lo = sticky_top_h
    content_hi = H0 - sticky_bot_h  # exclusive

    # ── seed canvas with frame 0 (full frame) ──
    canvas_rows: List[np.ndarray] = [frames[0].copy()]
    map_frame: List[np.ndarray] = [np.full(H0, 0, dtype=np.int32)]
    map_y: List[np.ndarray] = [np.arange(H0, dtype=np.int32)]
    # composite-y of each frame's top edge; frame 0 sits at 0
    frame_top: List[int] = [0]
    # running composite height
    cur_h = H0
    # the composite-y at which the sticky-bottom bar currently begins (we trim it
    # off before appending new content, then re-add at the very end)
    # We keep the seed's sticky-bottom in place and insert new content ABOVE it.

    # We will build the body WITHOUT the trailing sticky bottom, then add it once.
    # Re-seed cleanly: body = frame0[: content_hi]  (sticky top + content),
    # we'll append each frame's new content, and finally the sticky bottom.
    body = frames[0][:content_hi].copy()
    body_map_frame = np.full(content_hi, 0, dtype=np.int32)
    body_map_y = np.arange(content_hi, dtype=np.int32)
    frame_top = [0]
    # the composite-y of the bottom edge of the last-appended content
    body_h = content_hi

    # the max content a single frame's scrolling band can contribute (used to
    # sanity-bound an element-anchored offset against a bogus huge value).
    max_band_shift = content_hi - content_lo

    prev = frames[0]
    for i in range(1, len(frames)):
        cur = frames[i]
        shift, score = estimate_shift(prev, cur, sticky_top_h, sticky_bot_h)
        used = "pixel"

        # ELEMENT-ANCHORED OFFSET: the pixel template-match is unreliable on a real
        # scroll in TWO ways the prototype hit — (1) a flat, low-texture list
        # (settings rows on a plain background) gives the strip nothing distinctive,
        # so the score is weak; and (2) the production large fling advances ~2/3 of
        # the viewport per swipe, leaving only ~1 row of overlap — the prev-frame
        # bottom strip has scrolled OFF, so the matcher latches onto a repeated-ish
        # region and returns a confidently-WRONG shift (high score, wrong value).
        # The caller, however, matched the SAME UI control across the two frames
        # (ElementMatcher) and measured how far it moved; that delta IS the content
        # shift and is robust in BOTH failure modes. So when a plausible element
        # offset exists (positive, within one scrolling band) we PREFER it — except
        # when the pixel match is strong AND agrees with it (then either is fine and
        # the px-exact pixel value is kept). It is only ignored when absent or
        # implausible (a mis-matched anchor), in which case we fall back to pixels.
        eo = elem_off[i] if i < len(elem_off) else None
        eo_i = None
        if eo is not None:
            cand = int(round(eo))
            if MIN_SHIFT_PX <= cand <= max_band_shift:
                eo_i = cand
        if eo_i is not None:
            pixel_trustworthy = (score >= SHIFT_MATCH_MIN
                                 and abs(eo_i - shift) <= ELEMENT_PIXEL_AGREE_PX)
            if not pixel_trustworthy:
                shift, used = eo_i, "element"

        if debug:
            logger.info("stitch: frame %d shift=%dpx score=%.3f (%s%s)",
                        i, shift, score, used,
                        "" if eo is None else f", elem_off={eo:.1f}")

        if shift < MIN_SHIFT_PX or (used == "pixel" and score < SHIFT_MATCH_MIN):
            # no reliable new content (bottom reached / jitter) and no usable
            # element offset — skip this frame
            prev = cur
            continue

        # The new content is the bottom ``shift`` px of cur's scrolling band.
        new_lo = content_hi - shift
        new_lo = max(content_lo, new_lo)
        new_block = cur[new_lo:content_hi, :, :]
        nb_h = new_block.shape[0]
        if nb_h <= 0:
            prev = cur
            continue

        # this frame's TOP edge lands at: (composite-y of new_block top) - new_lo
        # composite-y of new_block top == body_h (we append directly below body)
        ft = body_h - new_lo
        frame_top.append(ft)

        body = np.vstack([body, new_block])
        body_map_frame = np.concatenate(
            [body_map_frame, np.full(nb_h, i, dtype=np.int32)])
        body_map_y = np.concatenate(
            [body_map_y, np.arange(new_lo, content_hi, dtype=np.int32)])
        body_h += nb_h
        prev = cur

    # ── re-attach the sticky bottom bar ONCE (from the last frame) ──
    if sticky_bot_h > 0:
        last = frames[-1]
        bot_block = last[content_hi:H0, :, :]
        body = np.vstack([body, bot_block])
        body_map_frame = np.concatenate(
            [body_map_frame, np.full(sticky_bot_h, len(frames) - 1, dtype=np.int32)])
        body_map_y = np.concatenate(
            [body_map_y, np.arange(content_hi, H0, dtype=np.int32)])
        body_h += sticky_bot_h

    y_map = np.stack([body_map_frame, body_map_y], axis=-1).astype(np.int32)
    assert y_map.shape[0] == body.shape[0], (y_map.shape, body.shape)

    return StitchResult(
        image=body, y_map=y_map,
        sticky_top_h=sticky_top_h, sticky_bot_h=sticky_bot_h,
        frame_h=H0, frame_top_in_composite=frame_top,
        system_top_h=system_top_h, system_bot_h=system_bot_h,
    )


def encode_png(img: np.ndarray) -> bytes:
    """Encode an RGB ndarray to PNG bytes (for handing to perception/writers)."""
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(img.astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


# [REGION-SCROLL CHANGE 13] Region-crop vertical stitcher (validated in
# _scratch/_stitch_sidebar_probe.py): tall-template matchTemplate + SAD pixel-refine
# + flat-row (inter-item gap, bg-colour-agnostic) seam snap. For desktop region
# scroll: cheap crops while scrolling, stitch, then ONE VLM grounding on the composite.
def stitch_region_crops(crops, template_frac: float = 0.6, min_score: float = 0.55,
                        shifts=None):
    """Stitch ordered top->bottom REGION crops (same width, overlapping) into one tall
    composite. ``crops`` = list of numpy RGB arrays. Returns composite RGB (or
    ``crops[0]`` when <2). Weak/duplicate crops (no confident overlap) are dropped.

    ``shifts`` (optional, parallel to ``crops``): ``shifts[i]`` = px the content moved
    UP from crop i-1 to crop i, as ALREADY measured by the caller (the engine's
    cross-correlation scroll gate). When a valid positive shift is supplied for a frame
    we append its bottom ``shift`` rows DIRECTLY — no matchTemplate re-derivation. This
    is the robust path on sparse/low-texture forms (settings rows on plain bg), where
    re-running matchTemplate here scores below ``min_score`` and the frame gets dropped,
    collapsing the composite to a single viewport. ``shifts[i] <= 0`` means "no new
    content" (bottom reached / non-scroll step) → skip. A missing/None entry falls back
    to the matchTemplate path for that frame."""
    import numpy as np
    import cv2
    if not crops:
        return None
    canvas = np.asarray(crops[0]).copy()
    for idx in range(1, len(crops)):
        B = np.asarray(crops[idx])
        if B.ndim != 3 or B.shape[1] != canvas.shape[1]:
            continue
        h = B.shape[0]
        # ── known-shift fast path: append exactly the new rows, no re-matching ──
        if shifts is not None and idx < len(shifts) and shifts[idx] is not None:
            sh = int(shifts[idx])
            if sh <= 1:
                continue                      # no real scroll this step → no new content
            sh = min(sh, h)                   # clamp: a step can't reveal more than one crop
            canvas = np.vstack([canvas, B[h - sh:]])
            continue
        # ── fallback: derive overlap by matchTemplate (original behaviour) ──
        tail = canvas[-h:] if canvas.shape[0] >= h else canvas
        gA = cv2.cvtColor(tail, cv2.COLOR_RGB2GRAY)
        gB = cv2.cvtColor(B, cv2.COLOR_RGB2GRAY)
        th = max(8, int(h * template_frac))
        if gA.shape[0] < th:
            continue
        res = cv2.matchTemplate(gA, gB[:th], cv2.TM_CCOEFF_NORMED)
        _, maxv, _, loc = cv2.minMaxLoc(res)
        y = loc[1]
        if maxv < min_score or (tail.shape[0] - y) <= 0 or (tail.shape[0] - y) > h:
            continue
        # SAD pixel-refine ±3
        Hh = gA.shape[0]; best_y, best = y, 1e18
        for yy in range(max(0, y - 3), min(Hh - 1, y + 3) + 1):
            n = min(Hh - yy, gB.shape[0])
            if n < 8:
                continue
            c = float(np.abs(gA[yy:yy + n].astype(np.int16) - gB[:n].astype(np.int16)).mean())
            if c < best:
                best, best_y = c, yy
        y = best_y
        oh = tail.shape[0] - y
        # seam snap to flattest (lowest horizontal-variance) row = an inter-item gap
        win = min(oh, 44)
        cut = int(np.argmin(B[:win].reshape(win, -1).std(axis=1))) if win > 1 else 0
        canvas[-(oh - cut):] = B[cut:oh]
        canvas = np.vstack([canvas, B[oh:]])
    return canvas

# Runtime adapter -----------------------------------------------------------
# The algorithms above are standalone. This explicit context is the only
# bridge needed by the engine-facing stitched-node orchestration below.
from typing import Any, Callable

from .. import visual_relocate as _reloc
from ..visual_perception import VisualElement
from ..visual_state import ElementMatcher, assign_element_uids

STITCH_VLM_MAX_H = 3500
STITCH_TILE_OVERLAP_PX = 140


@dataclass
class StitchContext:
    perception: Any
    is_touch: bool
    screen_wh: Callable[[dict], Tuple[int, int]]
    frames: List[bytes]
    offsets: List[Optional[float]]
    vlm_max_height: int = STITCH_VLM_MAX_H
    tile_overlap_px: int = STITCH_TILE_OVERLAP_PX


class StitchRuntime:
    """Stitched-node orchestration with declared, engine-free dependencies."""

    def __init__(self, context: StitchContext) -> None:
        self.context = context
        self.perception = context.perception
        self._is_touch = context.is_touch
        self._last_scroll_frames = context.frames
        self._last_scroll_offsets = context.offsets
        self.STITCH_VLM_MAX_H = int(context.vlm_max_height)
        self.STITCH_TILE_OVERLAP_PX = int(context.tile_overlap_px)

    def _screen_wh(self, obs: dict) -> Tuple[int, int]:
        return self.context.screen_wh(obs)

    def _build_stitched_node(
        self, top_shot: bytes
    ) -> Optional[Tuple[List[VisualElement], bytes, Any]]:
        """Stitch the captured scroll frames into a full-page composite, perceive
        it (ONE VLM naming call when short; TILED into a few chunk calls when very
        tall — see below), and map every composite element back to its (scroll_step,
        in-viewport y) so it stays scroll-into-view + clickable.

        Returns ``(elements, composite_png, som_image)`` or ``None`` to fall back to
        the per-viewport path (no/too-few frames, decode/stitch/perception failure).
        Identity is NOT touched here — the node was already registered from
        ``top_shot``'s pHash/chrome-band; this only builds the node's IMAGE + element
        set.

        TALL-COMPOSITE TILING (the live-A/B regression fix). A VERY tall composite
        (settings home = 5 frames / ~5077px) gets DOWNSCALED by the VLM when named in
        one pass, dropping the small below-fold rows (~17 named vs the ~25+ real
        rows; composites <= ~3500px have recall EQUAL to per-viewport). So when the
        composite exceeds ``STITCH_VLM_MAX_H`` we TILE it into vertical chunks each
        <= the cap — split on FRAME boundaries so a chunk is a clean set of whole
        viewports, with a small ``STITCH_TILE_OVERLAP_PX`` overlap so a row on a seam
        is whole in at least one chunk — name EACH chunk at full resolution (no
        downscale loss), then MERGE the element sets, deduping the overlap-region
        duplicates by appearance pHash (the same ElementMatcher ``_scroll_aggregate``
        uses). A 5-frame page → ~3 chunk calls (vs 5+ per-viewport), names stay clean,
        and recall matches per-viewport. A composite <= the cap stays a SINGLE call.
        """
        frames = list(self._last_scroll_frames)
        offsets = list(self._last_scroll_offsets)
        # consume the buffer regardless of outcome
        self._last_scroll_frames = []
        self._last_scroll_offsets = []
        if len(frames) < 2:
            return None  # page fit in one viewport — per-viewport path is fine
        try:
            from . import stitch as _vs
            # Android status/gesture bars are fixed platform geometry but their
            # pixels are not fixed (clock, signal, battery, gesture animation).
            # Seed the stitcher's sticky lower bounds from the same conservative
            # bands used by perception; inferred sticky detection may extend them
            # over an adjacent app toolbar, but can never shrink below system UI.
            system_top_h = system_bot_h = 0
            if getattr(self, "_is_touch", True):
                from .. import visual_filter as _vf
                if getattr(_vf, "SYSTEM_UI_BAND_ENABLED", True):
                    _w, frame_h = self._screen_wh({"screenshot": frames[0]})
                    system_top_h = int(
                        frame_h * float(_vf.STATUS_BAR_FRAC) + 0.999)
                    system_bot_h = int(
                        frame_h * float(_vf.NAV_BAR_FRAC) + 0.999)
            res = _vs.stitch_frames(
                frames,
                element_offsets=offsets,
                system_top_h=system_top_h,
                system_bot_h=system_bot_h,
            )
            if res is None:
                return None
            composite_png = _vs.encode_png(res.image)
        except Exception as e:
            logger.warning("stitch: composite build failed (%s); per-viewport "
                           "fallback", e)
            return None

        comp_h = res.image.shape[0]
        comp_w = res.image.shape[1]
        cap = int(getattr(self, "STITCH_VLM_MAX_H", STITCH_VLM_MAX_H))
        semantic = bool(getattr(
            self.perception, "use_semantic_inventory", False))
        try:
            if semantic:
                # Semantic traversal already has an inventory VLM and a
                # single-target grounding VLM. Reuse those unchanged on one
                # complete visual surface instead of inventing a second
                # per-viewport target-correspondence prompt. The inventory is
                # produced once, so overlapping viewport rows cannot be
                # registered twice. Grounding supplies composite geometry only
                # so the framework can recover each target's scroll depth.
                if comp_h > cap:
                    logger.warning(
                        "semantic stitch: composite %dpx exceeds grounded "
                        "single-image cap %dpx; refusing partial inventory",
                        comp_h, cap)
                    return None
                try:
                    elements = self.perception.semantic_inventory(
                        composite_png, full_surface=True)
                except TypeError:
                    # Test shims and older perception adapters may not expose
                    # the fixture-only keyword. Their normal image contract is
                    # unchanged.
                    elements = self.perception.semantic_inventory(composite_png)
                if not elements:
                    logger.warning(
                        "semantic stitch: full-surface inventory unavailable")
                    return None
                for element in elements:
                    if getattr(element, "geometry_status", "") == "fixture_full_surface":
                        continue
                    grounded = self.perception.ground_target(
                        composite_png, element, force_refresh=False)
                    if grounded is None:
                        logger.warning(
                            "semantic stitch: target grounding unavailable for %r",
                            getattr(element, "name", ""))
                        return None
                    element.bbox_xywh = list(grounded.bbox_xywh)
                    element.center = list(grounded.center)
                    element.geometry_status = "full_surface_target"
                som_image = None
                n_calls = 1 + len(elements)
            elif comp_h <= cap:
                # SHORT composite: one naming call, recall already equals per-viewport.
                elements = self.perception.detect_and_name(composite_png)
                elements = [
                    e for e in elements
                    if not self._is_stitched_system_ui_element(res, e)
                ]
                som_image = self.perception.last_som_image
                n_calls = 1
            else:
                # TALL composite: tile into <= cap chunks on frame boundaries, name
                # each, merge+dedup the seam overlap. composite element coords are
                # already in the FULL-PAGE space here (each chunk element is lifted
                # back to composite-y inside _perceive_tiled), so the mapping below
                # is identical to the single-call path.
                elements, som_image, n_calls = self._perceive_tiled(
                    res, composite_png, cap)
        except Exception as e:
            logger.warning("stitch: composite perception failed (%s); per-viewport "
                           "fallback", e)
            return None
        if not elements and comp_h > cap:
            # tiling produced nothing usable — don't register an empty node; let the
            # per-viewport path re-perceive instead.
            logger.warning("stitch: tiled perception yielded 0 elements; "
                           "per-viewport fallback")
            return None

        # Assign visual uids from the COMPOSITE now, while each element's bbox still
        # points at its true appearance on the full page. (Doing it later on the TOP
        # frame would hash the wrong pixels for below-the-fold elements, since their
        # viewport-y on the top frame shows different content.) The appearance-pHash
        # uid is identical whether cropped from the composite or the live viewport —
        # it is the same control's pixels — so it stays comparable to the
        # per-viewport path and stable across visits.
        try:
            assign_element_uids(composite_png, elements)
        except Exception as e:
            logger.debug("stitch: composite uid assignment failed (%s)", e)

        # Map each composite element's center back to a real (scroll_step, viewport
        # center) so the existing scroll_steps click path works unchanged, and crop
        # its relocation template from the frame that actually shows it.
        self._map_composite_elements_back(elements, res, frames, comp_h)
        logger.info("stitch: composite %dx%d from %d frames -> %d named elements "
                    "(%d naming VLM call%s for the whole page)",
                    comp_w, comp_h, len(frames), len(elements), n_calls,
                    "" if n_calls == 1 else "s")
        return elements, composite_png, som_image

    def _map_composite_elements_back(
        self, elements: List[VisualElement], res: Any,
        frames: List[bytes], comp_h: int,
    ) -> None:
        """Map each COMPOSITE-space element back to a real (scroll_step, in-viewport
        center) + viewport bbox + relocation template, in place.

        Shared by the single-call and the tiled paths — both hand elements whose
        ``center``/``bbox_xywh`` live in FULL-PAGE composite coordinates, so the
        y-map round-trip is identical regardless of how many VLM calls produced
        them."""
        for e in elements:
            if getattr(e, "geometry_status", "") == "fixture_full_surface":
                # Fixture-oracle full-surface geometry is expressed in document
                # coordinates.  It is not evidence for a production click, but
                # it can map an off-screen control to the bottom frame captured
                # by the real sweep.  Runtime grounding will still relocate the
                # control on that live frame before execution.
                original_y = int(e.center[1])
                frame_idx = 0 if original_y < int(res.frame_h) else len(frames) - 1
                e.scroll_steps = int(max(0, frame_idx))
                e.center = [int(e.center[0]), int(max(
                    0, min(int(res.frame_h) - 1, e.center[1])))]
                bx, by, bw, bh = e.bbox_xywh
                e.bbox_xywh = [int(bx), int(max(
                    0, min(int(res.frame_h) - max(1, int(bh)), by))),
                    int(bw), int(bh)]
                continue
            cy = int(max(0, min(comp_h - 1, e.center[1])))
            frame_idx, in_y = res.composite_y_to_scroll(cy)
            frame_idx = int(max(0, min(len(frames) - 1, frame_idx)))
            # frame_idx is the capture-frame index; capture frame 0 = the settled
            # TOP frame (scroll_steps 0), frame k = after k small swipes. The click
            # path swipes `scroll_steps` times from the top, then re-perceives /
            # template-relocates — so scroll_steps == frame_idx.
            e.scroll_steps = frame_idx
            # x stays as-is (no horizontal scroll); y becomes the in-viewport y so
            # the stored center matches what the live scrolled frame shows.
            e.center = [int(e.center[0]), int(in_y)]
            # crop the template from the frame that shows this element, at its
            # in-viewport bbox (x unchanged, y shifted to the viewport).
            bx, by, bw, bh = e.bbox_xywh
            vp_bbox = [int(bx), int(in_y - bh // 2), int(bw), int(bh)]
            try:
                e._template = _reloc.save_template(frames[frame_idx], vp_bbox)
            except Exception:
                e._template = None
            # keep the composite bbox y in viewport space too, so downstream
            # geometry (uid occurrence ordering) reflects the live frame.
            e.bbox_xywh = vp_bbox

    def _composite_chunk_bounds(
        self, res: Any, comp_h: int, cap: int,
    ) -> List[Tuple[int, int]]:
        """Vertical [y0, y1) chunk spans covering the whole composite, each <= ``cap``
        px, split on FRAME BOUNDARIES (``frame_top_in_composite``) so every chunk is a
        clean set of whole viewports, with a ``STITCH_TILE_OVERLAP_PX`` overlap before
        each non-first chunk so a row on a seam is whole in at least one chunk.

        Greedy: walk the frame-top boundaries and start a new chunk whenever adding
        the next frame would exceed the cap; a single frame taller than the cap (rare)
        becomes its own chunk (clamped). Always covers [0, comp_h)."""
        overlap = int(getattr(self, "STITCH_TILE_OVERLAP_PX", STITCH_TILE_OVERLAP_PX))
        # frame-top composite-y boundaries, plus the composite bottom as the final
        # boundary; de-duplicated + sorted + in-range so a clamped/duplicate frame_top
        # can't make a zero/negative span.
        tops = sorted({int(t) for t in (getattr(res, "frame_top_in_composite", None)
                                        or [0]) if 0 <= int(t) < comp_h})
        if not tops or tops[0] != 0:
            tops = [0] + tops
        boundaries = tops + [comp_h]

        chunks: List[Tuple[int, int]] = []
        seg_start = 0  # composite-y where the current chunk's content begins
        i = 1
        while i < len(boundaries):
            nxt = boundaries[i]
            if nxt - seg_start > cap and boundaries[i - 1] > seg_start:
                # adding this frame overflows the cap — close the chunk at the prior
                # boundary (a whole-viewport split).
                end = boundaries[i - 1]
                y0 = max(0, seg_start - overlap) if chunks else seg_start
                chunks.append((y0, end))
                seg_start = end
                continue  # re-test this same frame against the fresh chunk
            i += 1
        # close the final chunk (covers down to the composite bottom)
        y0 = max(0, seg_start - overlap) if chunks else seg_start
        if comp_h > seg_start:
            chunks.append((y0, comp_h))
        if not chunks:  # degenerate guard — one chunk covering everything
            chunks = [(0, comp_h)]
        return chunks

    @staticmethod
    def _is_stitched_system_ui_element(res: Any, elem: VisualElement) -> bool:
        """Reject an element whose composite row came from a source-frame system
        band.

        Tile-relative top/bottom percentages are insufficient here: an Android
        gesture pill accidentally pasted at an interior seam is neither the first
        tile's top nor the last tile's bottom. ``StitchResult.y_map`` preserves the
        source-frame row for every composite row, so this test remains correct for
        exterior bars, overlapping chunks, and any defensive residual seam copy.
        Only fixed *system* bands are checked; inferred sticky app chrome remains a
        legitimate element surface.
        """
        top_h = max(0, int(getattr(res, "system_top_h", 0) or 0))
        bot_h = max(0, int(getattr(res, "system_bot_h", 0) or 0))
        frame_h = max(0, int(getattr(res, "frame_h", 0) or 0))
        if frame_h <= 0 or (top_h <= 0 and bot_h <= 0):
            return False
        try:
            comp_h = int(res.image.shape[0])
            comp_y = int(max(0, min(comp_h - 1, elem.center[1])))
            _frame_idx, in_y = res.composite_y_to_scroll(comp_y)
            in_y = int(in_y)
        except Exception:
            return False
        return ((top_h > 0 and in_y < top_h)
                or (bot_h > 0 and in_y >= frame_h - bot_h))

    def _perceive_tiled(
        self, res: Any, composite_png: bytes, cap: int,
    ) -> Tuple[List[VisualElement], Any, int]:
        """Name a too-tall composite by TILING it into <= ``cap`` chunks (split on
        frame boundaries, small seam overlap), naming each chunk at full resolution,
        and MERGING the element sets with appearance-pHash dedup of the seam overlap.

        Returns ``(elements_in_composite_coords, som_image, n_naming_calls)``. Every
        returned element's ``center``/``bbox_xywh`` is lifted back into FULL-PAGE
        composite coordinates (chunk-local y + chunk y0), so the caller maps them with
        the SAME y-map round-trip as the single-call path. ``som_image`` is the first
        chunk's SoM image (the node's top, the most useful single annotated view)."""
        from . import stitch as _vs

        comp_img = res.image
        comp_h = comp_img.shape[0]
        bounds = self._composite_chunk_bounds(res, comp_h, cap)

        merged: List[VisualElement] = []
        matcher = ElementMatcher()  # appearance-pHash dedup across the seams
        som_image = None
        n_calls = 0
        for ci, (y0, y1) in enumerate(bounds):
            chunk_arr = comp_img[y0:y1, :, :]
            try:
                chunk_png = _vs.encode_png(chunk_arr)
            except Exception as e:
                logger.debug("stitch tile: chunk %d encode failed (%s); skipping",
                             ci, e)
                continue
            # [SCROLL-MAP CHANGE 18/B1] the status/nav bars exist ONCE in the
            # composite (stitch de-dups sticky bands): only the first chunk's top
            # and the last chunk's bottom are system UI — a middle chunk's top/
            # bottom bands are REAL rows and must not be band-filtered away.
            if len(bounds) == 1:
                _sb = "both"
            elif ci == 0:
                _sb = "top"
            elif ci == len(bounds) - 1:
                _sb = "bottom"
            else:
                _sb = "none"
            try:
                chunk_els = self.perception.detect_and_name(chunk_png, system_band=_sb)
            except Exception as e:
                logger.debug("stitch tile: chunk %d perception failed (%s); skipping",
                             ci, e)
                continue
            n_calls += 1
            if som_image is None:
                som_image = self.perception.last_som_image
            for e in chunk_els:
                # lift chunk-local coords -> full-page composite coords
                e.center = [int(e.center[0]), int(e.center[1] + y0)]
                bx, by, bw, bh = e.bbox_xywh
                e.bbox_xywh = [int(bx), int(by + y0), int(bw), int(bh)]
                # Defense in depth: use source-row provenance rather than tile
                # position. A system bar from any frame is rejected even if it
                # somehow survived at an interior composite seam, where the old
                # middle-tile ``system_band=none`` policy could expose it.
                if self._is_stitched_system_ui_element(res, e):
                    continue
                # dedup the seam: an element in the overlap region appears in BOTH
                # this chunk and the previous one. Match its appearance (cropped from
                # the COMPOSITE — same pixels in both chunks) against everything kept
                # so far; keep only genuinely-new controls.
                try:
                    _uid, is_new = matcher.match_or_add(composite_png, e.bbox_xywh)
                except Exception:
                    is_new = True  # on hash failure, don't drop a real element
                if is_new:
                    merged.append(e)
        logger.info("stitch tile: composite %dpx > cap %dpx -> %d chunk(s) "
                    "%s, %d naming call(s) -> %d merged elements (seam dups deduped)",
                    comp_h, cap, len(bounds), [list(b) for b in bounds],
                    n_calls, len(merged))
        return merged, som_image, n_calls
