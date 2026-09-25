"""Below-fold map, OCR anchoring, and closed-loop location runtime."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import visual_relocate as _reloc
from ..visual_perception import VisualElement
from .scroll import DEFAULT_PAUSE, DESKTOP_WHEEL_CLICKS, _scroll_action

logger = logging.getLogger(__name__)


SCROLL_MAP_ENABLED = os.environ.get("GUIWALK_SCROLL_MAP", "0") == "1"
SCROLL_MAP_WHEEL_STEP = 3
SCROLL_MAP_MAX_FRAMES = 24
SCROLL_MAP_SERVO_BUDGET = 18
SCROLL_MAP_STRIP_SCORE = 0.75
SCROLL_MAP_STRIPS_AGREE = 3

_NAME_TOK = re.compile(r"[0-9a-z一-鿿]+")


def _norm_name(value: str) -> str:
    """Lowercase, keep alphanumeric and CJK tokens, and collapse whitespace."""
    return " ".join(_NAME_TOK.findall((value or "").lower()))


def _name_match(target: str, got: str) -> bool:
    """Return whether OCR/live text plausibly identifies the target label."""
    if not target or not got:
        return False
    if target in got:
        return True
    target_tokens = set(_NAME_TOK.findall(target))
    got_tokens = set(_NAME_TOK.findall(got))
    return bool(target_tokens) and (
        len(target_tokens & got_tokens) / len(target_tokens)
    ) >= 0.6


@dataclass
class LocateContext:
    """Explicit engine boundary for below-fold localization."""

    env: Any
    perception: Any
    region_maps: Dict[str, Any]
    map_seg_cache: Dict[Any, Any]
    map_anims_off: bool
    last_live_rebind_observation: Any
    segment_regions: Callable[..., Any]
    screen_wh: Callable[..., Any]
    ensure_on_app: Callable[..., Any]
    best_live_rebind_match: Callable[..., Any]
    is_explicit_noninteractive: Callable[..., Any]


class LocateRuntime:
    """Own map/OCR localization state while the engine remains orchestration-only."""

    def __init__(self, context: LocateContext):
        self.context = context
        self.env = context.env
        self.perception = context.perception
        self._region_maps = context.region_maps
        self._map_seg_cache = context.map_seg_cache
        self._map_anims_off = context.map_anims_off
        self._last_live_rebind_observation = (
            context.last_live_rebind_observation
        )

    def _segment_regions(self, *args, **kwargs):
        return self.context.segment_regions(*args, **kwargs)

    def _screen_wh(self, *args, **kwargs):
        return self.context.screen_wh(*args, **kwargs)

    def _ensure_on_app(self, *args, **kwargs):
        return self.context.ensure_on_app(*args, **kwargs)

    def _best_live_rebind_match(self, *args, **kwargs):
        return self.context.best_live_rebind_match(*args, **kwargs)

    def _is_explicit_noninteractive(self, *args, **kwargs):
        return self.context.is_explicit_noninteractive(*args, **kwargs)

    def _map_frame(self):
        """Current full frame as (RGB ndarray, png bytes); (None, None) on failure."""
        import io as _io
        import numpy as _np
        from PIL import Image as _Image
        try:
            shot = self.env._get_obs().get("screenshot")
            if not shot:
                return None, None
            return _np.asarray(_Image.open(_io.BytesIO(shot)).convert("RGB")), shot
        except Exception:
            return None, None

    def _map_segments_cached(self, obs, win_key):
        """VLM region segmentation (CHANGE 8, modal-aware) as the map path's
        FIRST geometry source, cached per window geometry so the whole run pays
        ~one call — heuristics (element bbox, 0.30 width) become fallbacks only.
        Empty results are cached too (a failing VLM must not re-bill per goto)."""
        cache = getattr(self, "_map_seg_cache", None)
        if cache is None:
            cache = self._map_seg_cache = {}
        if win_key in cache:
            return cache[win_key]
        segs = []
        try:
            shot = obs.get("screenshot") if isinstance(obs, dict) else None
            if shot:
                # segment the WINDOW CROP, not the full screen: the full-screen
                # input made the VLM emit the Ubuntu DOCK as a nav_sidebar and
                # let it confidently "segment" bare wallpaper after an app crash
                # (no refusal). With the crop, a dead/absent window yields a
                # degenerate crop and NO regions — refusal for free. Boxes are
                # translated back to screen coords.
                import io as _io
                from PIL import Image as _Image
                wx, wy, ww, wh = win_key
                im = _Image.open(_io.BytesIO(shot)).convert("RGB")
                crop = im.crop((wx, wy, min(im.width, wx + ww),
                                min(im.height, wy + wh)))
                if crop.width >= 200 and crop.height >= 150:
                    buf = _io.BytesIO(); crop.save(buf, "PNG")
                    segs = self._segment_regions(buf.getvalue()) or []
                    for r in segs:
                        b = r.get("bbox")
                        if isinstance(b, (list, tuple)) and len(b) == 4:
                            r["bbox"] = [int(b[0]) + wx, int(b[1]) + wy,
                                         int(b[2]) + wx, int(b[3]) + wy]
        except Exception as ex:
            logger.debug("scroll-map: segmentation failed (%s)", ex)
            segs = []
        # keep only usable scroll panels; thin bars (titlebar/statusbar) are not
        # regions a below-fold element can live in
        segs = [r for r in segs
                if (r["bbox"][2] - r["bbox"][0]) >= 80
                and (r["bbox"][3] - r["bbox"][1]) >= 120]
        cache[win_key] = segs
        if segs:
            logger.info("scroll-map: VLM segmentation cached (%d region(s): %s)",
                        len(segs), [r.get("role") for r in segs])
        return segs

    def _map_region_candidates(self, elem, obs, node_elements=None):
        """ORDERED candidate (rect, side, source) list for the panel the element
        lives in: (1) VLM region segmentation (cached, modal-aware), (2) the
        node's element-cluster bbox, (3) width-fraction fallback. The goto tries
        candidates until the target RESOLVES on the built map — segmentation
        output varies run-to-run (one run's bbox built a map the target never
        resolved on), so a bad source must cost ONE retry, not the whole goto.
        The 0.45 split only assigns the SIDE, never the geometry."""
        try:
            sw, sh = self._screen_wh(obs)
        except Exception:
            sw, sh = 1920, 1080
        win = getattr(self.perception, "last_window_xywh", None) or [0, 0, sw, sh]
        wx, wy, ww, wh = [int(v) for v in win]
        split_x = wx + int(0.45 * ww)
        y0, y1 = wy + int(0.08 * wh), wy + wh - 4   # skip the headerbar band
        side = "sidebar" if int(elem.center[0]) < split_x else "content"
        cands = []
        # (1) VLM segmentation FIRST (user architecture: node-region-button,
        # semantics over priors). The seg decides the COLUMNS only — its x0/x1
        # carry the real signal (where panels split); the y-extent comes from
        # the standard window band, because a scroll panel spans the window
        # vertically and trusting the seg's y once clipped the last row (About)
        # in half at the map bottom. Earlier "seg variance" evidence was mostly
        # contaminated by app-crash frames (it was segmenting wallpaper); with
        # the window-crop input (see _map_segments_cached) a dead window yields
        # no regions at all. Sanity: role agrees with the split side; a sidebar
        # is never wider than the split.
        best = None
        for r in self._map_segments_cached(obs, (wx, wy, ww, wh)) or []:
            bx0, by0, bx1, by1 = [int(v) for v in r["bbox"]]
            if bx0 <= int(elem.center[0]) <= bx1 and by0 <= int(elem.center[1]) <= by1:
                area = max(1, (bx1 - bx0) * (by1 - by0))
                if best is None or area < best[0]:
                    best = (area, r)
        if best is not None:
            r = best[1]
            rx0 = max(wx + 2, int(r["bbox"][0]))
            rx1 = min(wx + ww - 4, int(r["bbox"][2]))
            role = str(r.get("role", "") or "").lower()
            seg_side = ("sidebar" if ("side" in role or "nav" in role)
                        else (role or side))
            side_ok = (seg_side == side) or (side == "content")
            width_ok = (side != "sidebar") or (rx1 - rx0 <= int(0.45 * ww))
            if rx1 - rx0 >= 80 and side_ok and width_ok:
                cands.append(([rx0, y0, rx1, y1], seg_side, "vlm-seg"))
        # (2) node element-cluster bbox
        els = [e for e in (node_elements or [])
               if (e.center[0] < split_x) == (side == "sidebar")]
        if len(els) >= 3:
            try:
                x0 = max(wx + 2, min(e.bbox_xywh[0] for e in els) - 8)
                x1 = min(wx + ww - 4,
                         max(e.bbox_xywh[0] + e.bbox_xywh[2] for e in els) + 24)
                if x1 - x0 >= 80:
                    cands.append(([int(x0), y0, int(x1), y1], side, "elements"))
            except Exception:
                pass
        # (3) width-fraction last-resort
        if side == "sidebar":
            cands.append(([wx + 2, y0, wx + int(0.30 * ww), y1], side, "fraction"))
        else:
            cands.append(([wx + int(0.34 * ww), y0, wx + ww - 4, y1], side, "fraction"))
        out, seen = [], set()
        for rc, sc, src in cands:
            k = tuple(rc)
            if k not in seen:
                seen.add(k)
                out.append((rc, sc, src))
        return out

    # [2026-07-07 用户 删除] _map_region_rect / _map_replay_resolver(SCROLL_MAP 死代码,
    # 零调用)已删。

    def _map_park(self, rect):
        """Park the cursor over the LABEL COLUMN of the region — never its center:
        the center of a settings content pane is often a SLIDER, which eats wheel
        events to adjust its value (live demo: the pane simply never scrolled)."""
        x = min(rect[0] + 60, (rect[0] + rect[2]) // 2)
        y = (rect[1] + rect[3]) // 2
        try:
            self.env.step({"action_type": "MOVE_TO",
                           "parameters": {"x": int(x), "y": int(y)}}, pause=0.15)
        except Exception:
            pass
        return int(x), int(y)

    def _map_wheel(self, park_xy, direction, amount):
        try:
            self.env.step({"action_type": "SCROLL",
                           "parameters": {"x": park_xy[0], "y": park_xy[1],
                                          "direction": direction,
                                          "amount": int(amount)}}, pause=0.25)
        except Exception as ex:
            logger.debug("scroll-map wheel failed (%s)", ex)

    def _map_settle_crop(self, rect, timeout=2.5, interval=0.18, outage_grace=12.0):
        """Region crop AFTER motion stops: poll until two consecutive crops are
        pixel-identical (with animations off this converges in 1-2 polls).

        A frame OUTAGE (guest server segfault+restart mid-capture returns no
        screenshot for ~10s) must not burn the settle budget and truncate a map
        build — it is waited out up to ``outage_grace`` and the settle clock is
        restarted on recovery."""
        import numpy as _np
        import time as _time
        last = None
        t0 = _time.time()
        none_t0 = None
        while True:
            fr, _shot = self._map_frame()
            if fr is None:
                none_t0 = none_t0 or _time.time()
                if _time.time() - none_t0 > outage_grace:
                    return last
                _time.sleep(0.8)
                continue
            if none_t0 is not None:
                none_t0 = None
                t0 = _time.time()   # fresh settle budget after the outage
            cur = fr[rect[1]:rect[3], rect[0]:rect[2]]
            if (last is not None and cur.shape == last.shape
                    and _np.array_equal(cur, last)):
                return cur
            last = cur
            if _time.time() - t0 > timeout:
                return cur
            _time.sleep(interval)

    def _map_disable_animations(self):
        """One-shot: GTK smooth-scroll animation is the main displacement-
        nondeterminism source (wheel events coalesce mid-animation; with it off
        the validated probe measured a constant 179px per 3-click step)."""
        if getattr(self, "_map_anims_off", False):
            return
        self._map_anims_off = True
        try:
            self.env.controller.execute_python_command(
                "import subprocess; subprocess.run(['gsettings','set',"
                "'org.gnome.desktop.interface','enable-animations','false'],"
                " check=False)")
            logger.info("scroll-map: gnome animations disabled")
        except Exception as ex:
            logger.debug("scroll-map: animations-off failed (%s)", ex)

    def _map_to_top(self, rect, park_xy=None):
        """Absorbing-state top: wheel up until the region stops changing. No step
        counting — the top is the only offset reproducible by construction."""
        import numpy as _np
        park_xy = park_xy or self._map_park(rect)
        cur = self._map_settle_crop(rect)
        for _ in range(12):
            self._map_wheel(park_xy, "up", DESKTOP_WHEEL_CLICKS)
            nxt = self._map_settle_crop(rect)
            if (cur is not None and nxt is not None and nxt.shape == cur.shape
                    and _np.array_equal(nxt, cur)):
                return nxt
            cur = nxt
        return cur

    def _map_build(self, rect, park_xy=None):
        """Build the region's tall MAP: top -> absorbing bottom in SMALL wheel
        steps (generous overlap), pixel-exact stitch. Leaves the panel at top.
        Returns ndarray or None."""
        import numpy as _np
        from . import stitch as _vs
        self._map_disable_animations()
        park_xy = park_xy or self._map_park(rect)
        top = self._map_to_top(rect, park_xy)
        if top is None:
            return None
        crops = [top]
        for _ in range(SCROLL_MAP_MAX_FRAMES):
            self._map_wheel(park_xy, "down", SCROLL_MAP_WHEEL_STEP)
            nxt = self._map_settle_crop(rect)
            if nxt is None:
                break
            if nxt.shape == crops[-1].shape and _np.array_equal(nxt, crops[-1]):
                break  # absorbing bottom
            crops.append(nxt)
        try:
            comp = _vs.stitch_region_crops(crops)
        except Exception as ex:
            logger.debug("scroll-map stitch failed (%s)", ex)
            comp = None
        self._map_to_top(rect, park_xy)
        if comp is not None:
            logger.info("scroll-map: built map %dx%d from %d frame(s)",
                        comp.shape[1], comp.shape[0], len(crops))
        return comp

    def _map_name_index(self, map_img):
        """OCR the map ONCE -> (merged_rows, word_boxes), each [(x, y, text)].
        Same-row boxes are MERGED (multi-word labels come back split and then
        match nothing), but word boxes are kept too: a single button inside a
        multi-button row must be clicked at the BUTTON's x, not the row mean."""
        try:
            reader = self.perception._get_ocr_reader()
            res = reader.readtext(map_img, text_threshold=0.4)
        except Exception as ex:
            logger.debug("scroll-map OCR failed (%s)", ex)
            return [], []
        words = []
        for box, txt, _c in res:
            xs = [p[0] for p in box]; ys = [p[1] for p in box]
            words.append((float(sum(xs)) / 4.0, float(sum(ys)) / 4.0, txt or ""))
        words.sort(key=lambda w: w[1])
        lines: List[List[Any]] = []
        for x, y, txt in words:
            if lines and abs(y - lines[-1][0]) <= 12:
                lines[-1][1].append((x, txt))
                lines[-1][0] = (lines[-1][0] + y) / 2.0
            else:
                lines.append([y, [(x, txt)]])
        merged = []
        for y, parts in lines:
            parts.sort(key=lambda p: p[0])
            merged.append((sum(p[0] for p in parts) / len(parts), y,
                           " ".join(p[1] for p in parts)))
        return merged, words

    def _map_resolve_name(self, index, name):
        """(x, y) of ``name`` on the map. Word-box exact first (button-level x),
        then merged-line exact/containment, then CONSTRAINED fuzzy: same first two
        chars + ratio>=0.8 — easyocr stably misreads t->l ('Nelwork'), while the
        prefix guard keeps 'sound' from ever matching 'background'/'ground'."""
        import difflib as _difflib
        merged, words = index
        tn = _norm_name(name or "")
        if not tn:
            return None
        for x, y, txt in words:
            if _norm_name(txt) == tn:
                return [int(x), int(y)]
        for x, y, txt in merged:
            mn = _norm_name(txt)
            if mn and (mn == tn or (len(tn) >= 4 and tn in mn)):
                return [int(x), int(y)]
        best = None
        for x, y, txt in list(merged) + list(words):
            mn = _norm_name(txt)
            if not mn or len(tn) < 4 or mn[:2] != tn[:2]:
                continue
            r = _difflib.SequenceMatcher(None, tn, mn).ratio()
            if r >= 0.8 and (best is None or r > best[0]):
                best = (r, x, y)
        if best is not None:
            return [int(best[1]), int(best[2])]
        return None

    def _map_localize(self, live_crop, map_img):
        """Viewport offset of ``live_crop`` inside ``map_img`` (strip-median
        matchTemplate), or None. STRICT acceptance: >=SCROLL_MAP_STRIPS_AGREE
        strips scoring >=SCROLL_MAP_STRIP_SCORE and agreeing within ±3px — a 0.6
        threshold once matched bare WALLPAPER after an app crash; a confidence
        collapse must be DETECTED, not turned into a hallucinated offset."""
        import cv2 as _cv2
        if live_crop is None or map_img is None:
            return None
        try:
            gl = _cv2.cvtColor(live_crop, _cv2.COLOR_RGB2GRAY)
            gc = _cv2.cvtColor(map_img, _cv2.COLOR_RGB2GRAY)
        except Exception:
            return None
        if gl.shape[1] != gc.shape[1] or gc.shape[0] < gl.shape[0]:
            return None  # window moved/resized or degenerate map
        H = gl.shape[0]
        offs = []
        for f in (0.08, 0.28, 0.5, 0.72, 0.9):
            y = min(max(0, int(f * H)), max(0, H - 38))
            strip = gl[y:y + 36]
            if strip.shape[0] < 8:
                continue
            try:
                res = _cv2.matchTemplate(gc, strip, _cv2.TM_CCOEFF_NORMED)
            except Exception:
                continue
            _mn, mv, _mnl, mxl = _cv2.minMaxLoc(res)
            if mv >= SCROLL_MAP_STRIP_SCORE:
                offs.append(mxl[1] - y)
        if len(offs) < SCROLL_MAP_STRIPS_AGREE:
            return None
        offs.sort()
        med = offs[len(offs) // 2]
        agree = sum(1 for o in offs if abs(o - med) <= 3)
        return int(med) if agree >= SCROLL_MAP_STRIPS_AGREE else None

    def _map_goto(self, elem, obs, node_elements=None):
        """One goto attempt + ONE app-recovery retry.

        GNOME's About panel sporadically crashes the whole app (observed live,
        repeatedly): wheel events then land on the bare wallpaper, every build
        comes back a single frame tall and nothing resolves. When the first
        attempt fails, ask the focus guard — if it had to RELAUNCH the app, the
        maps/segmentation built during the dead window are garbage: clear them
        and retry once from the fresh app root. If the app was fine all along
        (a genuine resolve failure) no retry is spent."""
        center, down = self._map_goto_once(elem, obs, node_elements)
        if center is not None:
            return center, down
        try:
            cur = self.env._get_obs()
            cur, relaunched, on_app = self._ensure_on_app(cur)
        except Exception as ex:
            logger.debug("scroll-map: app-recovery check failed (%s)", ex)
            return None, down
        if relaunched and on_app:
            logger.info("scroll-map: app was gone — relaunched; retrying the goto "
                        "on fresh maps")
            try:
                self._region_maps.clear()
            except Exception:
                pass
            self._map_seg_cache = {}
            return self._map_goto_once(elem, cur, node_elements)
        return None, down

    def _map_goto_once(self, elem, obs, node_elements=None):
        """Map-based goto for a below-the-fold desktop element. Resolve the target
        BY NAME on the region map (appearance template as fallback), scroll to the
        absorbing top, then measure->step->measure until the target is in view;
        gate the click with row-OCR at the expected spot. Returns
        ``(screen_center | None, down_swipes)`` — None = fail-closed, never a
        stale-center click. A stale/unusable map (page changed, first visit after
        a crash, mis-click landed elsewhere) is REBUILT once and the name
        re-resolved on the fresh map — the auto-rebuild the live demo validated.
        """
        maps = getattr(self, "_region_maps", None)
        if maps is None:
            maps = self._region_maps = {}

        def resolve(cmp_img):
            pt = self._map_resolve_name(self._map_name_index(cmp_img),
                                        getattr(elem, "name", "") or "")
            if pt is None and getattr(elem, "_template", None) is not None:
                import cv2 as _cv2
                try:
                    g = _cv2.cvtColor(cmp_img, _cv2.COLOR_RGB2GRAY)
                    t = elem._template
                    if getattr(t, "ndim", 2) == 3:
                        t = _cv2.cvtColor(t, _cv2.COLOR_RGB2GRAY)
                    r = _cv2.matchTemplate(g, t, _cv2.TM_CCOEFF_NORMED)
                    _a, mv, _b, ml = _cv2.minMaxLoc(r)
                    if mv >= 0.8:
                        pt = [int(ml[0] + t.shape[1] // 2),
                              int(ml[1] + t.shape[0] // 2)]
                except Exception:
                    pt = None
            return pt

        # candidate-chain: try each geometry source until the target RESOLVES
        # on the built map (VLM seg variance / a bad bbox costs one retry only)
        comp = rect = side = target = park_xy = None
        rebuilt = False
        for rect_c, side_c, src in self._map_region_candidates(elem, obs,
                                                               node_elements):
            if rect_c[2] - rect_c[0] < 60 or rect_c[3] - rect_c[1] < 60:
                continue
            park_c = self._map_park(rect_c)
            entry = maps.get(side_c)
            comp_c = (entry.get("comp")
                      if isinstance(entry, dict) and entry.get("rect") == list(rect_c)
                      else None)
            built = False
            if comp_c is None:
                comp_c = self._map_build(rect_c, park_c)
                maps[side_c] = {"rect": list(rect_c), "comp": comp_c}
                built = True
            # degenerate-build guard: a below-fold target needs a map taller than
            # the viewport — a truncated capture (frame outage mid-build) must
            # not silently eat the retry.
            if (comp_c is not None and getattr(elem, "scroll_steps", 0) > 0
                    and comp_c.shape[0] < (rect_c[3] - rect_c[1]) + 40):
                logger.info("scroll-map: %s map looks truncated (%dpx) — rebuilding",
                            side_c, comp_c.shape[0])
                comp_c = self._map_build(rect_c, park_c)
                maps[side_c] = {"rect": list(rect_c), "comp": comp_c}
                built = True
            if comp_c is None:
                continue
            t = resolve(comp_c)
            if t is None and not built:   # cached map may be stale — rebuild once
                comp_c = self._map_build(rect_c, park_c)
                maps[side_c] = {"rect": list(rect_c), "comp": comp_c}
                built = True
                t = None if comp_c is None else resolve(comp_c)
            if t is not None:
                comp, rect, side, target, park_xy = comp_c, rect_c, side_c, t, park_c
                rebuilt = built
                break
            logger.info("scroll-map: '%s' not on the %s map from %s — trying the "
                        "next geometry source", elem.name, side_c, src)
        if target is None:
            logger.warning("scroll-map: '%s' not resolvable on any region map — "
                           "fail-closed", elem.name)
            return None, 0
        xg, yg = target

        self._map_to_top(rect, park_xy)
        H = rect[3] - rect[1]
        M = 28
        prev_yv = None
        down = 0
        for _ in range(SCROLL_MAP_SERVO_BUDGET):
            live = self._map_settle_crop(rect)
            yv = self._map_localize(live, comp)
            if yv is None:
                # one cheap re-settle retry before the expensive rebuild path — a
                # single mid-repaint frame must not burn the rebuild budget
                live = self._map_settle_crop(rect)
                yv = self._map_localize(live, comp)
            if yv is None:
                if not rebuilt:
                    comp = self._map_build(rect, park_xy)   # stale map -> rebuild once
                    maps[side] = {"rect": list(rect), "comp": comp}
                    rebuilt = True
                    target = None if comp is None else resolve(comp)
                    if target is None:
                        return None, down
                    xg, yg = target
                    self._map_to_top(rect, park_xy)
                    prev_yv = None
                    continue
                logger.warning("scroll-map: localize failed on %s — fail-closed", side)
                return None, down
            rel = yg - yv
            stuck = prev_yv is not None and yv == prev_yv
            prev_yv = yv
            lo, hi = (4, H - 6) if stuck else (M, H - M)
            if lo <= rel <= hi:
                # row-OCR gate at the expected spot. Raw pixels are NOT the gate:
                # the selection highlight recolors the whole row between map time
                # and click time; text survives highlight.
                _fr, shot = self._map_frame()
                sx, sy = rect[0] + int(xg), rect[1] + int(rel)
                got = self._ocr_text_at(shot, (sx, sy), (34, 200)) if shot else ""
                visible_label = getattr(elem, "action_label", "") or elem.name or ""
                if not _name_match(_norm_name(visible_label), got):
                    logger.warning("scroll-map: row-OCR gate failed for '%s' "
                                   "(read '%s') — fail-closed", elem.name, got[:40])
                    return None, down
                return [sx, sy], down
            if stuck:
                logger.warning("scroll-map: '%s' unreachable (pinned yv=%d rel=%d)",
                               elem.name, yv, rel)
                return None, down
            if rel > hi:
                self._map_wheel(park_xy, "down", SCROLL_MAP_WHEEL_STEP)
                down += 1
            else:
                self._map_wheel(park_xy, "up", SCROLL_MAP_WHEEL_STEP)
                down = max(0, down - 1)
        return None, down

    def _ocr_text_at(self, shot_bytes, center, tmpl_shape):
        """OCR a small crop around ``center`` (sized to the template + padding).
        Returns lowercased joined text ('' on any failure). Reuses the perception
        OCR reader (lazy; works even when use_ocr=False)."""
        try:
            import io as _io
            import numpy as _np
            from PIL import Image as _Image
            im = _Image.open(_io.BytesIO(shot_bytes)).convert("RGB")
            W, H = im.size
            th, tw = (int(tmpl_shape[0]), int(tmpl_shape[1])) if tmpl_shape else (32, 200)
            cx, cy = int(center[0]), int(center[1])
            padx, pady = int(tw * 0.6), int(th * 0.8)
            x0 = max(0, cx - tw // 2 - padx); x1 = min(W, cx + tw // 2 + padx)
            y0 = max(0, cy - th // 2 - pady); y1 = min(H, cy + th // 2 + pady)
            crop = _np.asarray(im.crop((x0, y0, x1, y1)))
            reader = self.perception._get_ocr_reader()
            res = reader.readtext(crop, text_threshold=0.4)
            return " ".join((t or "") for _b, t, _c in res).lower()
        except Exception as ex:
            logger.debug("_ocr_text_at failed (%s)", ex)
            return ""

    def _vlm_locate_by_name(self, shot_bytes, target, stored=None):
        """Ground the frame and return the center of the element whose name matches
        ``target`` (normalized). None if not found."""
        try:
            els = self.perception.detect_and_name(shot_bytes)
        except Exception as ex:
            logger.debug("_vlm_locate_by_name ground failed (%s)", ex)
            return None
        named = [
            element for element in els
            if _name_match(target, _norm_name(element.name))
        ]
        if stored is not None:
            best = self._best_live_rebind_match(stored, els, shot_bytes)
            if best is not None and self._is_explicit_noninteractive(best):
                self._last_live_rebind_observation = {
                    "status": "noninteractive",
                    "fresh": best,
                    "method": "scroll_vlm",
                }
                return None
        for e in named:
            if e.interactive is not False:
                return [int(e.center[0]), int(e.center[1])]
        return None

    def _ocr_live_center_by_name(self, shot_bytes: bytes, elem: VisualElement,
                                 live_bbox_xywh=None) -> Optional[List[int]]:
        """Resolve a textual navigation target inside its own live region.

        Dense sidebars expose a failure mode that a second VLM call cannot fix:
        the label can be semantically correct while its returned bbox belongs to
        the adjacent row.  OCR is used only as a *local coordinate anchor* after
        the VLM has already supplied the target name and region.  This keeps the
        semantic/geometry responsibilities separate and avoids full-screen OCR
        boxes becoming traversal candidates.
        """
        target = _norm_name(
            getattr(elem, "action_label", "") or getattr(elem, "name", ""))
        role = (getattr(elem, "region", "") or "").lower()
        rb = getattr(elem, "region_bbox", None)
        if len(target) < 2:
            return None
        try:
            import io as _io
            import numpy as _np
            from PIL import Image as _Image

            image = _Image.open(_io.BytesIO(shot_bytes)).convert("RGB")
            if live_bbox_xywh is not None and len(live_bbox_xywh) == 4:
                x, y, w, h = [int(v) for v in live_bbox_xywh]
                x0, y0, x1, y1 = x, y, x + w, y + h
            elif role in {"nav_sidebar", "tab_bar"} and rb and len(rb) == 4:
                x0, y0, x1, y1 = [int(v) for v in rb]
            else:
                return None
            if (x0 < 0 or y0 < 0 or x1 > image.width or y1 > image.height
                    or x1 <= x0 or y1 <= y0):
                return None
            crop = _np.asarray(image.crop((x0, y0, x1, y1)))
            merged, words = self._map_name_index(crop)
            exact_words = [(x, y) for x, y, text in words
                           if _norm_name(text) == target]
            exact_lines = [(x, y) for x, y, text in merged
                           if _norm_name(text) == target]
            matches = exact_words or exact_lines or [
                (x, y) for x, y, text in merged
                if _name_match(target, _norm_name(text))]
            matches = [(x, y) for x, y in matches
                       if 0 <= x < (x1 - x0) and 0 <= y < (y1 - y0)]
            if len(matches) != 1:
                return None
            local = matches[0]
            point = [x0 + int(local[0]), y0 + int(local[1])]
            logger.info("live-center OCR anchor '%s' -> %s in %s",
                        elem.name, point, [x0, y0, x1, y1])
            return point
        except Exception as ex:
            logger.debug("live-center OCR anchor failed for '%s' (%s)",
                         getattr(elem, "name", ""), ex)
            return None
