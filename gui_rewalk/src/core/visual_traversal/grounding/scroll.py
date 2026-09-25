"""Viewport scroll capture and restoration for visual traversal.

The runtime receives only declared dependencies through :class:`ScrollContext`;
it does not import or own the traversal engine.
"""
from __future__ import annotations

import io
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...graph.state_graph import (
    page_scroll_scope_id,
    region_scroll_scope_id,
)
from .. import visual_relocate as _reloc
from ..visual_perception import (
    ACTIVE_OVERLAY_SURFACE_KINDS,
    ACTIVE_SURFACE_POPUP_MENU,
    VisualElement,
    _normalize_surface_kind,
)
from ..visual_state import ElementMatcher

logger = logging.getLogger(__name__)

DEFAULT_PAUSE = 2.0
SCROLL_PATIENCE = 2
MAX_SCROLL_STEPS = 8
DESKTOP_MAX_SCROLL_STEPS = 16
GROUND_STRIDE_DISTANCE = 12
DESKTOP_WHEEL_CLICKS = 8
REGION_SCROLL_MIN_CHANGED_FRACTION = 0.005
MAX_BELOW_FOLD_ON_RUNAWAY = 12
VIEW_STABLE_DISTANCE = 4
STITCH_SCROLL_FRAC = 0.42
STITCH_MAX_SCROLL_STEPS = 14
REGION_SCROLL_SAFETY_MAX_STEPS = 96
SCROLL_MAP_ENABLED = os.environ.get("GUIWALK_SCROLL_MAP", "0") == "1"

_NAME_TOK = re.compile(r"[0-9a-z一-鿿]+")

def _scroll_action(direction: str, amount: int = 1,
                   frac: Optional[float] = None,
                   slow: bool = False,
                   anchor: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
    """A SCROLL step. ``frac`` (0..1) requests a SHORTER finger swipe spanning that
    fraction of the screen instead of the default ~2/3 fling, and ``slow`` requests
    a longer-duration (low-momentum) gesture — together they give a small,
    well-overlapping scroll for full-page STITCHING (the production amount=1 fling
    advances ~1/3 the screen with momentum, leaving only ~1 ambiguous row of
    overlap). Both are additive params the Android controller honours; omitting
    them (the default) reproduces today's exact behaviour."""
    params: Dict[str, Any] = {"direction": direction, "amount": amount}
    if frac is not None:
        params["frac"] = float(frac)
    if slow:
        params["slow"] = True
    if anchor is not None:
        params["x"], params["y"] = int(anchor[0]), int(anchor[1])
    return {"action_type": "SCROLL", "parameters": params}


def _region_scroll_fraction(bbox_1000) -> float:
    """Scale the standard swipe span to one localized vertical viewport."""
    try:
        height_fraction = max(
            0.0, min(1.0, (float(bbox_1000[3])
                           - float(bbox_1000[1])) / 1000.0))
    except (IndexError, TypeError, ValueError):
        height_fraction = 1.0
    return STITCH_SCROLL_FRAC * height_fraction


def _region_scroll_max_steps(bbox_1000) -> int:
    """Return an emergency gesture cap; stable-boundary evidence ends normal lists."""
    del bbox_1000
    return REGION_SCROLL_SAFETY_MAX_STEPS


def _region_scroll_moved(
    previous: Any,
    current: Any,
    step_shift: int,
    step_score: float,
    *,
    min_shift: int,
    min_score: float,
) -> bool:
    """Accept a desktop region shift only with non-trivial pixel evidence."""
    try:
        import numpy as np
        if previous is None or current is None \
                or previous.shape != current.shape or previous.size == 0:
            return False
        delta = np.abs(
            previous.astype(np.int16) - current.astype(np.int16))
        changed_fraction = float((delta.max(axis=2) > 15).mean())
    except Exception:
        return False
    return bool(
        changed_fraction >= REGION_SCROLL_MIN_CHANGED_FRACTION
        and int(step_shift) >= int(min_shift)
        and float(step_score) >= float(min_score)
    )

def _norm_name(s: str) -> str:
    """Lowercase, keep alnum + CJK tokens, collapse whitespace."""
    return " ".join(_NAME_TOK.findall((s or "").lower()))


def _crop_normalized_region(screenshot: bytes, bbox_1000) -> bytes:
    """Crop one normalized Region bbox from a screenshot as PNG bytes."""
    from PIL import Image
    image = Image.open(io.BytesIO(screenshot)).convert("RGB")
    x0, y0, x1, y1 = [int(value) for value in bbox_1000]
    px = (
        max(0, min(image.width, round(x0 * image.width / 1000))),
        max(0, min(image.height, round(y0 * image.height / 1000))),
        max(0, min(image.width, round(x1 * image.width / 1000))),
        max(0, min(image.height, round(y1 * image.height / 1000))),
    )
    if px[2] <= px[0] or px[3] <= px[1]:
        return b""
    output = io.BytesIO()
    image.crop(px).save(output, format="PNG")
    return output.getvalue()


def _expanded_physical_scroll_bbox(
    semantic_bbox: List[int],
    region_bboxes: Dict[str, List[int]],
) -> List[int]:
    """Expand a semantic Region upward through adjacent full-width peers.

    Some mobile pages split a collapsing header and its list into separate
    functional Regions even though both move inside one physical scroll
    container.  The first failed crop match may therefore retry against the
    smallest vertically connected container above the declared scroll Region.
    The candidate is accepted by the caller only when the before/after pixels
    recover coherent vertical motion.
    """
    expanded = [int(value) for value in semantic_bbox]
    changed = True
    while changed:
        changed = False
        for candidate in (region_bboxes or {}).values():
            try:
                other = [int(value) for value in candidate]
            except (TypeError, ValueError):
                continue
            if len(other) != 4 or other == expanded:
                continue
            overlap = max(
                0, min(expanded[2], other[2]) - max(expanded[0], other[0]))
            narrower = max(
                1, min(expanded[2] - expanded[0], other[2] - other[0]))
            horizontally_aligned = overlap / narrower >= 0.75
            vertically_connected = (
                other[1] < expanded[1]
                and other[3] >= expanded[1] - 2
            )
            if not horizontally_aligned or not vertically_connected:
                continue
            expanded = [
                min(expanded[0], other[0]),
                min(expanded[1], other[1]),
                max(expanded[2], other[2]),
                max(expanded[3], other[3]),
            ]
            changed = True
    return expanded


def _trim_physical_scroll_composite(
    composite: bytes,
    physical_bbox: List[int],
    semantic_bbox: List[int],
    viewport_height_px: int,
) -> bytes:
    """Remove the prepended neighbouring Region from a physical long map."""
    if not composite or list(physical_bbox) == list(semantic_bbox):
        return composite
    from PIL import Image

    image = Image.open(io.BytesIO(composite)).convert("RGB")
    physical_w = max(1, int(physical_bbox[2]) - int(physical_bbox[0]))
    physical_h = max(1, int(physical_bbox[3]) - int(physical_bbox[1]))
    left = round(
        (int(semantic_bbox[0]) - int(physical_bbox[0]))
        * image.width / physical_w)
    right = round(
        (int(semantic_bbox[2]) - int(physical_bbox[0]))
        * image.width / physical_w)
    top = round(
        (int(semantic_bbox[1]) - int(physical_bbox[1]))
        * max(1, int(viewport_height_px)) / physical_h)
    left = max(0, min(image.width, left))
    right = max(left + 1, min(image.width, right))
    top = max(0, min(image.height - 1, top))
    output = io.BytesIO()
    image.crop((left, top, right, image.height)).save(output, format="PNG")
    return output.getvalue()


def _inferred_inner_scroll_bbox(
    previous: Any,
    current: Any,
    bbox_1000: List[int],
) -> Optional[List[int]]:
    """Shrink a declared Region past fixed top/bottom chrome when motion proves it.

    A semantic block may include a form's fixed title or action footer around an
    independently scrolling content viewport.  A full-crop shift then fails
    because its bottom probe strip is pinned.  Reuse the stitcher's generic
    sticky-band detector and accept a smaller viewport only when the remaining
    band has a strong coherent vertical shift.
    """
    try:
        from .stitch import (
            MIN_SHIFT_PX, SHIFT_MATCH_MIN, detect_sticky_bands, estimate_shift,
        )

        if (previous is None or current is None
                or previous.shape != current.shape
                or previous.ndim != 3 or previous.shape[0] < 3):
            return None
        sticky_top, sticky_bottom = detect_sticky_bands([previous, current])
        if sticky_top <= 0 and sticky_bottom <= 0:
            return None
        shift, score = estimate_shift(
            previous, current, sticky_top, sticky_bottom)
        if shift < MIN_SHIFT_PX or score < SHIFT_MATCH_MIN:
            return None

        height = int(previous.shape[0])
        inner_bottom = height - int(sticky_bottom)
        if inner_bottom <= int(sticky_top):
            return None
        x0, y0, x1, y1 = [int(value) for value in bbox_1000]
        span = y1 - y0
        inferred = [
            x0,
            y0 + int(round(sticky_top * span / height)),
            x1,
            y1 - int(round(sticky_bottom * span / height)),
        ]
        if inferred[1] >= inferred[3]:
            return None
        return inferred
    except Exception:
        return None


def _stitch_semantic_region_frames(
    frames_by_region: Dict[str, List[bytes]],
    shifts_by_region: Dict[str, List[Optional[float]]],
) -> Dict[str, bytes]:
    """Build only Region-local long images from mapped viewport crops.

    A scroll audit may still keep full frames for complete-surface inventory, but
    those pixels are not a safe source for a Region map: fixed sidebars and other
    non-scrolling blocks are repeated by the full-width stitch.  This helper
    accepts only crops already mapped to one stable ``region_id``.  A scrollable
    Region is emitted only when at least two compatible crops produce a taller
    image; otherwise the caller leaves its map absent and target execution fails
    closed without guessing a historical scroll depth.
    """
    import numpy as np
    from PIL import Image
    from .stitch import encode_png, stitch_region_crops

    composites: Dict[str, bytes] = {}
    for region_id, payloads in (frames_by_region or {}).items():
        arrays = []
        shifts = []
        for index, payload in enumerate(payloads or []):
            if not payload:
                continue
            try:
                array = np.asarray(
                    Image.open(io.BytesIO(payload)).convert("RGB"))
            except Exception:
                continue
            if arrays and array.shape[1] != arrays[0].shape[1]:
                continue
            arrays.append(array)
            source_shifts = shifts_by_region.get(region_id) or []
            shifts.append(source_shifts[index] if index < len(source_shifts) else None)
        if len(arrays) < 2:
            continue
        composite = stitch_region_crops(arrays, shifts=shifts)
        if composite is None or composite.shape[0] <= arrays[0].shape[0]:
            continue
        composites[str(region_id)] = encode_png(composite)
    return composites


@dataclass
class ScrollContext:
    env: Any
    perception: Any
    focus_guard: Any
    page_judge: Any
    block_identity_judge: Any
    region_registry: Any
    writer: Any
    state_data: Dict[str, Dict[str, Any]]
    pending_transition: Any
    is_touch: bool
    stitch_node_image: bool
    last_scroll_frames: List[bytes]
    last_scroll_offsets: List[Optional[float]]
    semantic_scroll_seed_region_crops: Dict[str, bytes]
    semantic_scroll_seed_region_bboxes: Dict[str, List[int]]
    frame_phash: Callable[[bytes], Any]
    screen_wh: Callable[[Dict[str, Any]], Tuple[int, int]]
    record_scroll_evidence: Callable[..., None]
    map_to_top: Callable[..., Any]
    begin_node_local_accumulation: Callable[[], None]
    accumulate_node_local_functions: Callable[[], None]
    collected_node_local_functions: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]
    semantic_scroll_force_top: bool = False


class ScrollRuntime:
    """General touch/desktop scroll behavior over an explicit context."""

    def __init__(self, context: ScrollContext) -> None:
        self.context = context
        self.env = context.env
        self.perception = context.perception
        self.focus_guard = context.focus_guard
        self.page_judge = context.page_judge
        self.block_identity_judge = context.block_identity_judge
        self.region_registry = context.region_registry
        self.writer = context.writer
        self._state_data = context.state_data
        self._pending_transition = context.pending_transition
        self._is_touch = bool(context.is_touch)
        self._stitch_node_image = bool(context.stitch_node_image)
        self._last_scroll_frames = context.last_scroll_frames
        self._last_scroll_offsets = context.last_scroll_offsets
        self._semantic_scroll_seed_region_crops = dict(
            context.semantic_scroll_seed_region_crops or {})
        self._semantic_scroll_seed_region_bboxes = dict(
            context.semantic_scroll_seed_region_bboxes or {})
        self._semantic_scroll_force_top = bool(
            context.semantic_scroll_force_top)

    def _frame_phash(self, shot: bytes) -> Any:
        return self.context.frame_phash(shot)

    def _screen_wh(self, obs: Dict[str, Any]) -> Tuple[int, int]:
        return self.context.screen_wh(obs)

    def _record_scroll_evidence(self, **payload: Any) -> None:
        self.context.record_scroll_evidence(**payload)

    def _restore_semantic_region_to_top(
        self,
        current_obs: Dict[str, Any],
        bbox: List[int],
        up_action: Dict[str, Any],
        *,
        top_view: Any = None,
        minimum_swipes: int = 0,
        max_swipes: int,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Restore one Region using coherent reverse motion, not pixel equality.

        Dynamic values may keep changing after the physical viewport has reached
        its upper boundary.  The boundary is therefore established by consecutive
        up gestures with no coherent reverse vertical shift.  A matching saved
        top fingerprint remains a faster sufficient proof when available.
        """
        import numpy as np
        from PIL import Image
        from .stitch import MIN_SHIFT_PX, SHIFT_MATCH_MIN, estimate_shift

        shot = (current_obs or {}).get("screenshot")
        previous_bytes = _crop_normalized_region(shot, bbox) if shot else b""
        if not previous_bytes:
            return False, current_obs
        try:
            if top_view is not None and (
                    self._frame_phash(previous_bytes) - top_view
                    ) <= VIEW_STABLE_DISTANCE:
                return True, current_obs
            previous = np.asarray(
                Image.open(io.BytesIO(previous_bytes)).convert("RGB"))
        except Exception:
            return False, current_obs

        boundary_stale = 0
        for attempt in range(max(0, int(max_swipes))):
            try:
                next_obs = self.env.step(up_action, pause=1.0)
                next_shot = (next_obs or {}).get("screenshot")
                next_bytes = (
                    _crop_normalized_region(next_shot, bbox)
                    if next_shot else b"")
                if not next_bytes:
                    return False, current_obs
                if top_view is not None and (
                        self._frame_phash(next_bytes) - top_view
                        ) <= VIEW_STABLE_DISTANCE:
                    return True, next_obs
                current = np.asarray(
                    Image.open(io.BytesIO(next_bytes)).convert("RGB"))
                if current.shape != previous.shape:
                    return False, current_obs
                # estimate_shift reports content moving upward.  Reversing the
                # frame order converts an upward return gesture into that same
                # positive-motion convention.
                comparison_current = current
                comparison_previous = previous
                inner_bbox = _inferred_inner_scroll_bbox(
                    current, previous, [0, 0, 1000, 1000])
                if inner_bbox:
                    height, width = current.shape[:2]
                    x0, y0, x1, y1 = inner_bbox
                    px = (
                        max(0, min(width, round(x0 * width / 1000))),
                        max(0, min(height, round(y0 * height / 1000))),
                        max(0, min(width, round(x1 * width / 1000))),
                        max(0, min(height, round(y1 * height / 1000))),
                    )
                    if px[2] > px[0] and px[3] > px[1]:
                        comparison_current = current[
                            px[1]:px[3], px[0]:px[2]]
                        comparison_previous = previous[
                            px[1]:px[3], px[0]:px[2]]
                reverse_shift, reverse_score = estimate_shift(
                    comparison_current, comparison_previous, 0, 0)
                coherent = _region_scroll_moved(
                    comparison_current, comparison_previous,
                    reverse_shift, reverse_score,
                    min_shift=MIN_SHIFT_PX, min_score=SHIFT_MATCH_MIN)
                if coherent:
                    boundary_stale = 0
                elif attempt + 1 >= max(0, int(minimum_swipes)):
                    boundary_stale += 1
                else:
                    boundary_stale = 0
                current_obs = next_obs
                previous = current
                if boundary_stale >= SCROLL_PATIENCE:
                    return True, current_obs
            except Exception:
                return False, current_obs
        return False, current_obs

    def _map_to_top(self, *args: Any, **kwargs: Any) -> Any:
        return self.context.map_to_top(*args, **kwargs)

    def _begin_node_local_accumulation(self) -> None:
        self.context.begin_node_local_accumulation()

    def _accumulate_node_local_functions(self) -> None:
        self.context.accumulate_node_local_functions()

    def _collected_node_local_functions(
        self, initial: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return self.context.collected_node_local_functions(initial)

    def _is_short_non_scrollable_overlay(
        self,
        obs: Dict[str, Any],
        elements: List[VisualElement],
    ) -> bool:
        """Whether the current touch surface must not enter page aggregation.

        Android dropdown/overflow menus are transient active surfaces over a
        background list.  Swiping them as if they were the page dismisses or
        shifts the popup, then later clicks use an option label against the now
        active background row.  A structured ``popup_menu`` defaults to static;
        an explicitly scrollable option surface remains eligible.  For legacy
        modal responses without ``surface_kind``, a compact non-scrollable modal
        is also treated as static.
        """
        perception = getattr(self, "perception", None)
        is_modal = bool(getattr(perception, "last_is_modal", False))
        kind = _normalize_surface_kind(
            getattr(perception, "last_surface_kind", ""),
            is_modal=is_modal,
        )
        surface = getattr(perception, "last_window_xywh", None)
        scrollable = getattr(perception, "last_surface_scrollable", None)
        for element in elements or []:
            element_kind = _normalize_surface_kind(
                getattr(element, "surface_kind", ""),
                is_modal=(getattr(element, "surface_kind", "")
                          in ACTIVE_OVERLAY_SURFACE_KINDS),
            )
            if element_kind in ACTIVE_OVERLAY_SURFACE_KINDS:
                kind = element_kind
                is_modal = True
                surface = getattr(element, "surface_bbox_xywh", None) or surface
                if getattr(element, "surface_scrollable", None) is not None:
                    scrollable = element.surface_scrollable
                break
        # ``surface_scrollable=false`` is an active-surface contract, not an
        # overlay-only hint.  Touching a static full-screen surface can dismiss
        # or navigate it, so forcing a probe swipe here can contaminate this
        # node with the next page's elements.
        if scrollable is False:
            return True
        if not is_modal or kind not in ACTIVE_OVERLAY_SURFACE_KINDS:
            return False
        if scrollable is True:
            return False
        if kind == ACTIVE_SURFACE_POPUP_MENU:
            return True
        # Backward-compatible compact-dialog guard.  Old cached responses know
        # only ``is_modal``; do not send 3-6 page swipes through a small confirm or
        # option popup.  Large functional dialogs can still be audited normally.
        try:
            _sw, sh = self._screen_wh(obs)
            surface_height = float(surface[3])
        except Exception:
            return scrollable is False
        return surface_height <= max(1.0, float(sh) * 0.55)

    def _semantic_region_scroll_aggregate(
        self, obs: Dict[str, Any], first_elements: List[VisualElement],
        state_id: str = "",
    ) -> List[VisualElement]:
        """Capture every declared scrollable Region without per-step VLM calls."""
        import numpy as np
        from PIL import Image
        from .stitch import MIN_SHIFT_PX, SHIFT_MATCH_MIN, estimate_shift

        shot0 = obs.get("screenshot")
        blocks = list(getattr(
            self.perception, "last_semantic_blocks", []) or [])
        bboxes = dict(getattr(
            self, "_semantic_scroll_seed_region_bboxes", {}) or {})
        seed_crops = dict(getattr(
            self, "_semantic_scroll_seed_region_crops", {}) or {})
        scrollable = [
            block for block in blocks
            if block.get("scrollable") is True
            and str(block.get("region_id") or "") in bboxes
        ]
        if (shot0 and blocks
                and getattr(
                    self.perception, "last_surface_scrollable", None) is not True
                and all(block.get("scrollable") is False for block in blocks)):
            detail = "all declared Regions are non-scrollable"
            if state_id:
                region_blocks = {
                    str(block.get("region_id") or ""): block
                    for block in blocks
                    if str(block.get("region_id") or "")
                }
                if region_blocks:
                    for region_id, block in region_blocks.items():
                        self._record_scroll_evidence(
                            scope_id=region_scroll_scope_id(region_id),
                            state_id=state_id,
                            region_id=region_id,
                            role=str(block.get("role") or "region"),
                            classification="static",
                            termination="static",
                            bottom_reached=False,
                            top_restored=True,
                            steps=0,
                            max_steps=0,
                            detail=detail,
                        )
                else:
                    self._record_scroll_evidence(
                        scope_id=page_scroll_scope_id(state_id),
                        state_id=state_id,
                        role="page",
                        classification="static",
                        termination="static",
                        bottom_reached=False,
                        top_restored=True,
                        steps=0,
                        max_steps=0,
                        detail=detail,
                    )
            logger.info("scroll-aggregate: %s; skipping swipes", detail)
            return list(first_elements)
        if not shot0 or not scrollable:
            detail = (
                "no localized scrollable Region was declared "
                f"(count={len(scrollable)})")
            if state_id:
                unresolved = {
                    str(block.get("region_id") or ""): block
                    for block in blocks
                    if str(block.get("region_id") or "")
                    and block.get("scrollable") is not False
                }
                if not unresolved:
                    unresolved = {
                        str(block.get("region_id") or ""): block
                        for block in blocks
                        if str(block.get("region_id") or "")
                    }
                if unresolved:
                    for region_id, block in unresolved.items():
                        self._record_scroll_evidence(
                            scope_id=region_scroll_scope_id(region_id),
                            state_id=state_id,
                            region_id=region_id,
                            role=str(block.get("role") or "region"),
                            classification="unknown",
                            termination="perception_unavailable",
                            bottom_reached=False,
                            top_restored=True,
                            steps=0,
                            max_steps=STITCH_MAX_SCROLL_STEPS,
                            detail=detail,
                        )
                else:
                    self._record_scroll_evidence(
                        scope_id=page_scroll_scope_id(state_id),
                        state_id=state_id,
                        role="page",
                        classification="unknown",
                        termination="perception_unavailable",
                        bottom_reached=False,
                        top_restored=True,
                        steps=0,
                        max_steps=STITCH_MAX_SCROLL_STEPS,
                        detail=detail,
                    )
            logger.warning("scroll-aggregate: %s", detail)
            return list(first_elements)

        screen_w, screen_h = self._screen_wh(obs)
        aggregated = list(first_elements)
        scrollable_ids = {
            str(block.get("region_id") or "") for block in scrollable}
        region_images = {
            region_id: image for region_id, image in seed_crops.items()
            if region_id not in scrollable_ids
        }
        current_top_obs = obs
        completed_any = False
        for block in scrollable:
            region_id = str(block.get("region_id") or "")
            raw_bbox = list(bboxes[region_id])
            bbox = list(raw_bbox)
            if str(getattr(self.env, "provider_name", "")) == "android":
                from gui_rewalk.src.config.config import (
                    ANDROID_NAV_BAR_CROP_PX, ANDROID_STATUS_BAR_CROP_PX,
                )
                top = int(round(ANDROID_STATUS_BAR_CROP_PX / screen_h * 1000))
                bottom = int(round(
                    (screen_h - ANDROID_NAV_BAR_CROP_PX) / screen_h * 1000))
                bbox[1] = max(bbox[1], top)
                bbox[3] = min(bbox[3], bottom)
            semantic_bbox = list(bbox)
            top_shot = current_top_obs.get("screenshot") or shot0
            seed = (seed_crops.get(region_id) if bbox == raw_bbox else None) \
                or _crop_normalized_region(top_shot, bbox)
            if not seed:
                if state_id:
                    self._record_scroll_evidence(
                        scope_id=region_scroll_scope_id(region_id),
                        state_id=state_id,
                        region_id=region_id, role="region",
                        classification="unknown",
                        termination="perception_unavailable",
                        bottom_reached=False, top_restored=True, steps=0,
                        max_steps=STITCH_MAX_SCROLL_STEPS,
                        detail="localized scrollable Region crop was unavailable")
                continue

            anchor = (
                round((bbox[0] + bbox[2]) * screen_w / 2000),
                round((bbox[1] + bbox[3]) * screen_h / 2000),
            )
            gesture_frac = _region_scroll_fraction(bbox)
            region_max_steps = _region_scroll_max_steps(bbox)
            down = _scroll_action(
                "down", frac=gesture_frac, slow=True, anchor=anchor)
            up = _scroll_action(
                "up", frac=gesture_frac, slow=True, anchor=anchor)
            if self._semantic_scroll_force_top:
                restored, current_top_obs = (
                    self._restore_semantic_region_to_top(
                        current_top_obs, bbox, up,
                        minimum_swipes=0,
                        max_swipes=region_max_steps + SCROLL_PATIENCE))
                if not restored:
                    if state_id:
                        self._record_scroll_evidence(
                            scope_id=region_scroll_scope_id(region_id),
                            state_id=state_id, region_id=region_id,
                            role="region", classification="unknown",
                            termination="top_restore_failed",
                            bottom_reached=False, top_restored=False,
                            steps=0, max_steps=region_max_steps,
                            detail=(
                                "stable Region could not be restored to its "
                                "physical upper boundary before retry"))
                    break
                top_shot = current_top_obs.get("screenshot") or shot0
                seed = _crop_normalized_region(top_shot, bbox)
                if not seed:
                    break
            frames = [seed]
            shifts: List[Optional[float]] = [0]
            prev_crop = np.asarray(
                Image.open(io.BytesIO(seed)).convert("RGB"))
            top_view = self._frame_phash(seed)
            steps = 0
            stale = 0
            incoherent = 0
            moved_any = False
            termination = "unknown"
            detail = ""
            current_obs = current_top_obs
            physical_viewport_inferred = False
            inner_viewport_inferred = False

            while steps < region_max_steps and stale < SCROLL_PATIENCE:
                try:
                    current_obs = self.env.step(down, pause=DEFAULT_PAUSE)
                except Exception as exc:
                    termination, detail = "error", str(exc)[:240]
                    break
                steps += 1
                shot = current_obs.get("screenshot")
                if not shot:
                    termination, detail = "error", "scroll screenshot missing"
                    break
                crop_bytes = _crop_normalized_region(shot, bbox)
                if not crop_bytes:
                    termination, detail = "error", "scroll Region crop missing"
                    break
                crop = np.asarray(
                    Image.open(io.BytesIO(crop_bytes)).convert("RGB"))
                if crop.shape != prev_crop.shape:
                    termination, detail = "error", "scroll Region crop shape changed"
                    break
                delta = np.max(np.abs(
                    crop.astype(np.int16) - prev_crop.astype(np.int16)), axis=2)
                changed_fraction = float((delta > 15).mean())
                if changed_fraction < REGION_SCROLL_MIN_CHANGED_FRACTION:
                    stale += 1
                    continue
                shift, score = estimate_shift(prev_crop, crop, 0, 0)
                if (steps == 1 and not physical_viewport_inferred
                        and not inner_viewport_inferred):
                    inner_bbox = _inferred_inner_scroll_bbox(
                        prev_crop, crop, bbox)
                    inner_seed = (
                        _crop_normalized_region(top_shot, inner_bbox)
                        if inner_bbox else b"")
                    inner_current = (
                        _crop_normalized_region(shot, inner_bbox)
                        if inner_seed else b"")
                    if inner_seed and inner_current:
                        inner_previous_pixels = np.asarray(Image.open(
                            io.BytesIO(inner_seed)).convert("RGB"))
                        inner_current_pixels = np.asarray(Image.open(
                            io.BytesIO(inner_current)).convert("RGB"))
                        inner_shift, inner_score = estimate_shift(
                            inner_previous_pixels,
                            inner_current_pixels, 0, 0)
                    else:
                        inner_previous_pixels = None
                        inner_current_pixels = None
                        inner_shift, inner_score = 0, 0.0
                    if (inner_previous_pixels is not None
                            and inner_current_pixels is not None
                            and inner_shift >= MIN_SHIFT_PX
                            and inner_score >= SHIFT_MATCH_MIN):
                        bbox = list(inner_bbox)
                        frames = [inner_seed, inner_current]
                        shifts = [0, inner_shift]
                        prev_crop = inner_current_pixels
                        top_view = self._frame_phash(inner_seed)
                        stale = 0
                        incoherent = 0
                        moved_any = True
                        inner_viewport_inferred = True
                        anchor = (
                            round((bbox[0] + bbox[2])
                                  * screen_w / 2000),
                            round((bbox[1] + bbox[3])
                                  * screen_h / 2000),
                        )
                        gesture_frac = _region_scroll_fraction(bbox)
                        region_max_steps = _region_scroll_max_steps(bbox)
                        down = _scroll_action(
                            "down", frac=gesture_frac, slow=True,
                            anchor=anchor)
                        up = _scroll_action(
                            "up", frac=gesture_frac, slow=True,
                            anchor=anchor)
                        detail = (
                            "physical scroll viewport inferred by excluding "
                            "fixed chrome inside the declared Region")
                        continue
                if shift < MIN_SHIFT_PX or score < SHIFT_MATCH_MIN:
                    if steps == 1 and not physical_viewport_inferred:
                        expanded_bbox = _expanded_physical_scroll_bbox(
                            semantic_bbox, bboxes)
                        if str(getattr(
                                self.env, "provider_name", "")) == "android":
                            expanded_bbox[1] = max(expanded_bbox[1], top)
                            expanded_bbox[3] = min(expanded_bbox[3], bottom)
                        expanded_seed = (
                            _crop_normalized_region(top_shot, expanded_bbox)
                            if expanded_bbox != bbox else b"")
                        expanded_current = (
                            _crop_normalized_region(shot, expanded_bbox)
                            if expanded_seed else b"")
                        if expanded_seed and expanded_current:
                            expanded_previous = np.asarray(Image.open(
                                io.BytesIO(expanded_seed)).convert("RGB"))
                            expanded_crop = np.asarray(Image.open(
                                io.BytesIO(expanded_current)).convert("RGB"))
                            expanded_shift, expanded_score = estimate_shift(
                                expanded_previous, expanded_crop, 0, 0)
                        else:
                            expanded_shift, expanded_score = 0, 0.0
                        if (expanded_shift >= MIN_SHIFT_PX
                                and expanded_score >= SHIFT_MATCH_MIN):
                            bbox = list(expanded_bbox)
                            frames = [expanded_seed, expanded_current]
                            shifts = [0, expanded_shift]
                            prev_crop = expanded_crop
                            top_view = self._frame_phash(expanded_seed)
                            stale = 0
                            incoherent = 0
                            moved_any = True
                            physical_viewport_inferred = True
                            detail = (
                                "physical scroll viewport inferred from "
                                "coherent motion across adjacent semantic "
                                "Regions")
                            continue
                    try:
                        settled_obs = self.env.step(
                            {"action_type": "WAIT"}, pause=1.0)
                        settled_shot = settled_obs.get("screenshot")
                        settled_bytes = (
                            _crop_normalized_region(settled_shot, bbox)
                            if settled_shot else b"")
                        settled_crop = (
                            np.asarray(Image.open(
                                io.BytesIO(settled_bytes)).convert("RGB"))
                            if settled_bytes else None)
                    except Exception:
                        settled_obs = None
                        settled_bytes = b""
                        settled_crop = None
                    if (settled_crop is not None
                            and settled_crop.shape == prev_crop.shape):
                        settled_delta = np.max(np.abs(
                            settled_crop.astype(np.int16)
                            - prev_crop.astype(np.int16)), axis=2)
                        settled_changed = float(
                            (settled_delta > 15).mean())
                        if settled_changed < REGION_SCROLL_MIN_CHANGED_FRACTION:
                            current_obs = settled_obs
                            stale += 1
                            continue
                        settled_shift, settled_score = estimate_shift(
                            prev_crop, settled_crop, 0, 0)
                        if (settled_shift >= MIN_SHIFT_PX
                                and settled_score >= SHIFT_MATCH_MIN):
                            current_obs = settled_obs
                            stale = 0
                            incoherent = 0
                            moved_any = True
                            shifts.append(settled_shift)
                            frames.append(settled_bytes)
                            prev_crop = settled_crop
                            continue
                    incoherent += 1
                    if incoherent < SCROLL_PATIENCE:
                        continue
                    termination = "surface_changed"
                    detail = (
                        "the intended Region and its adjacent physical "
                        "viewport did not retain coherent vertical continuity")
                    break
                stale = 0
                incoherent = 0
                moved_any = True
                shifts.append(shift)
                frames.append(crop_bytes)
                prev_crop = crop

            if stale >= SCROLL_PATIENCE:
                termination = "viewport_stable"
            elif steps >= region_max_steps and termination == "unknown":
                termination = "hard_cap"
            elif termination == "unknown":
                termination = "error"

            top_restored = termination != "surface_changed"
            if top_restored and moved_any:
                # Keep the return path bounded, while reserving enough gestures
                # to observe the stable upper boundary after the last movement.
                restore_budget = steps + 3 + SCROLL_PATIENCE
                top_restored, current_obs = (
                    self._restore_semantic_region_to_top(
                        current_obs, bbox, up, top_view=top_view,
                        minimum_swipes=steps,
                        max_swipes=restore_budget))
            if top_restored:
                current_top_obs = current_obs

            if (termination == "viewport_stable" and top_restored
                    and len(frames) >= 2):
                composites = _stitch_semantic_region_frames(
                    {region_id: frames}, {region_id: shifts})
                composite = composites.get(region_id)
                if composite:
                    if physical_viewport_inferred:
                        composite = _trim_physical_scroll_composite(
                            composite, bbox, semantic_bbox,
                            viewport_height_px=prev_crop.shape[0])
                    inventory = getattr(
                        self.perception, "inventory_scrollable_region", None)
                    inventory_block = dict(block)
                    inventory_block["_viewport_height_px"] = int(
                        prev_crop.shape[0])
                    known_groups: Dict[str, List[str]] = {}
                    for element in aggregated:
                        if str(getattr(
                                element, "region_id", "") or "") != region_id:
                            continue
                        group = str(
                            getattr(element, "group", "") or "").strip()
                        name = str(
                            getattr(element, "name", "") or "").strip()
                        if not group or not name:
                            continue
                        examples = known_groups.setdefault(group, [])
                        if name not in examples and len(examples) < 3:
                            examples.append(name)
                    inventory_block["known_groups"] = [
                        {"group": group, "examples": examples}
                        for group, examples in known_groups.items()
                    ]
                    complete = inventory(
                        composite, inventory_block, region_id) \
                        if callable(inventory) else []
                    inventory_status = dict(getattr(
                        self.perception, "last_region_long_inventory", {}) or {})
                    if inventory_status.get("status") != "ok":
                        termination = "perception_unavailable"
                        detail = (
                            "completed Region map inventory failed: "
                            f"{inventory_status.get('status') or 'unreported'}"
                        )
                    else:
                        seen = {
                            _norm_name(element.name) for element in aggregated}
                        for element in complete:
                            key = _norm_name(element.name)
                            if not key or key in seen:
                                continue
                            aggregated.append(element)
                            seen.add(key)
                        region_images[region_id] = composite
                        completed_any = True
                else:
                    termination = "perception_unavailable"
                    detail = "Region crop sequence did not produce a taller composite"

            if state_id:
                self._record_scroll_evidence(
                    scope_id=region_scroll_scope_id(region_id),
                    state_id=state_id,
                    region_id=region_id, role="region",
                    classification=("scrollable" if moved_any else "static"),
                    termination=termination,
                    bottom_reached=(termination == "viewport_stable"),
                    top_restored=bool(top_restored), steps=steps,
                    max_steps=region_max_steps, detail=detail)
            if not top_restored:
                break

        if completed_any:
            state_data = self._state_data.setdefault(str(state_id), {})
            state_data["_semantic_scroll_blocks"] = blocks
            state_data["_semantic_scroll_region_crops"] = region_images
        return aggregated

    def _scroll_aggregate(self, obs: Dict[str, Any],
                          first_elements: List[VisualElement],
                          state_id: str = "") -> List[VisualElement]:
        """Aggregate a scrollable page's clickable elements over the WHOLE page.

        Starting from the top viewport (``first_elements`` already perceived),
        swipe down, re-perceive, and append only genuinely-new clickable elements
        (deduped against everything seen so far by appearance pHash via
        ``ElementMatcher``). Stop when the viewport is unchanged for
        ``SCROLL_PATIENCE`` swipes (true bottom — absorbs single-frame jitter) or
        ``MAX_SCROLL_STEPS`` is hit, then scroll back to the top so the page is
        left in its canonical (top) position. Each appended element records the
        ``scroll_steps`` (downward swipes from top) at which it became visible,
        so the engine can scroll it back into view before clicking.

        No-op (returns ``first_elements``) when the env can't scroll — keeps the
        desktop path and any non-scrollable page unaffected.

        When ``STITCH_NODE_IMAGE`` is on, this also records the ordered scroll
        frames and a per-frame element-anchored content offset (the median vertical
        delta of elements matched across consecutive frames) into
        ``self._last_scroll_frames`` / ``self._last_scroll_offsets`` for the caller
        to stitch — and uses a smaller/slower swipe for generous frame overlap.
        Legacy geometry mode keeps its element matcher. Semantic mode instead
        maps the changed viewport's Region table before aggregation and never
        uses transient target wording as a deduplication key.
        """
        # getattr-guarded so a partially-constructed engine (test shim binding this
        # method onto a bare object) and the default-OFF flag both behave as the
        # plain per-viewport path.
        # STITCH is touch-only (its small-swipe overlap capture is Android-tuned).
        # NOTE: desktop never reaches this line — the is_touch check ~10 lines below
        # early-returns into `_desktop_regional_scroll`, which does NOT capture stitch
        # frames. Un-gating here is inert for desktop; desktop perceive-once needs
        # frame capture built INTO the regional path (per-panel), not this gate.
        semantic = bool(getattr(
            getattr(self, "perception", None), "use_semantic_inventory", False))
        # Semantic mode needs one complete visual surface for a stable target
        # inventory. Capturing overlapping frames is therefore correctness
        # machinery, not the optional legacy annotated-image feature.
        stitching = bool(
            semantic or (
                getattr(self, "_stitch_node_image", False)
                and getattr(self, "_is_touch", True)))
        ScrollRuntime._begin_node_local_accumulation(self)
        # Reset capture buffers before every exit path; otherwise a popup skipped
        # after a stitched page could accidentally reuse that page's frames.
        self._last_scroll_frames = []
        self._last_scroll_offsets = []
        semantic_blocks = list(getattr(
            self.perception, "last_semantic_blocks", []) or [])
        has_scrollable_block = any(
            block.get("scrollable") is True for block in semantic_blocks)
        if (self._is_short_non_scrollable_overlay(obs, first_elements)
                and not (semantic and has_scrollable_block)):
            for element in first_elements:
                element.scroll_steps = 0
            if state_id:
                region_blocks = {
                    str(block.get("region_id") or ""): block
                    for block in semantic_blocks
                    if str(block.get("region_id") or "")
                } if semantic else {}
                targets = [
                    (
                        region_scroll_scope_id(region_id),
                        region_id,
                        str(block.get("role") or "region"),
                    )
                    for region_id, block in region_blocks.items()
                ] or [(
                    page_scroll_scope_id(state_id),
                    "",
                    ("active_overlay" if bool(getattr(
                        self.perception, "last_is_modal", False)) else "page"),
                )]
                for scope_id, region_id, role in targets:
                    self._record_scroll_evidence(
                        scope_id=scope_id,
                        state_id=state_id,
                        region_id=region_id,
                        role=role,
                        classification="static",
                        termination="static",
                        bottom_reached=False,
                        top_restored=True,
                        steps=0,
                        max_steps=0,
                        detail=(
                            "active surface is explicitly non-scrollable, or "
                            "is a short popup/menu; touch scroll skipped"),
                    )
            logger.info(
                "scroll-aggregate: active touch surface is static; skipping swipes")
            return list(first_elements)
        if semantic:
            return self._semantic_region_scroll_aggregate(
                obs, first_elements, state_id=state_id)
        # DESKTOP: panels scroll INDEPENDENTLY (Settings sidebar vs content). The
        # single center-parked wheel loop below only ever scrolled the content pane
        # (missing below-fold sidebar rows) AND sent {"dy":..} which this env's
        # SCROLL rejects -> every desktop swipe silently failed. Route desktop to a
        # dedicated region-aware path; the mobile/touch swipe loop below is untouched.
        # [REGION-SCROLL CHANGE 2a — revert: delete these 2 lines]
        if not getattr(self, "_is_touch", True):
            return self._desktop_regional_scroll(
                obs, first_elements, state_id=state_id)
        matcher = ElementMatcher()
        # seed matcher with the top-viewport elements (step 0)
        shot0 = obs.get("screenshot")
        if not shot0:
            if state_id:
                self._record_scroll_evidence(
                    scope_id=f"state:{state_id}:page", state_id=state_id,
                    role="page", classification="unknown",
                    termination="error", top_restored=False,
                    detail="initial screenshot missing")
            return first_elements
        for e in first_elements:
            matcher.match_or_add(shot0, e.bbox_xywh)
            e.scroll_steps = 0
            # Crop the element's appearance from the frame it was seen in, for
            # later template-match relocation (fast a11y-free "where is this
            # button now"). Step-0 elements live on the top frame.
            e._template = _reloc.save_template(shot0, e.bbox_xywh)
        aggregated: List[VisualElement] = list(first_elements)
        # Stitch capture: frame 0 is the settled top frame; its element y-positions
        # seed the element-anchored offset chain. (Offsets index 0 = the seed, so
        # there is no offset before it.)
        if stitching:
            self._last_scroll_frames.append(shot0)
            self._last_scroll_offsets.append(None)
            prev_frame_elems = list(first_elements)
            prev_frame_shot = shot0
        # Per-step scroll action. Touch: a down SWIPE (smaller/slower when stitching).
        # Desktop: park the cursor over the scrollable content ONCE (the wheel scrolls
        # whatever is under it), then each step is a vertical wheel scroll DOWN
        # (pyautogui.vscroll: negative = down). The cursor stays parked for the whole
        # loop, so one MOVE_TO suffices. All wrapped so a desktop scroll glitch falls
        # back to the top-viewport set instead of crashing the node.
        if getattr(self, "_is_touch", True):
            scroll_step_action = (_scroll_action("down", frac=STITCH_SCROLL_FRAC, slow=True)
                                  if stitching else _scroll_action("down"))
        else:
            try:
                _sw, _sh = self._screen_wh(obs)
                self.env.step({"action_type": "MOVE_TO",
                               "parameters": {"x": int(_sw // 2), "y": int(_sh * 0.5)}},
                              pause=0.3)
            except Exception as ex:
                logger.debug("desktop scroll: MOVE_TO content failed (%s)", ex)
            scroll_step_action = {"action_type": "SCROLL",
                                  "parameters": {"dy": -DESKTOP_WHEEL_CLICKS}}
        max_steps = (
            STITCH_MAX_SCROLL_STEPS if stitching else MAX_SCROLL_STEPS)

        try:
            prev_view = self._frame_phash(shot0)
        except Exception:
            if state_id:
                self._record_scroll_evidence(
                    scope_id=f"state:{state_id}:page", state_id=state_id,
                    role="page", classification="unknown",
                    termination="error", top_restored=False,
                    detail="initial viewport fingerprint failed")
            return first_elements

        top_view = prev_view  # the registered top frame; restore must return here

        steps = 0
        stale = 0
        hit_cap = False
        moved_any = False
        termination = "unknown"
        surface_change_detail = ""
        while steps < max_steps and stale < SCROLL_PATIENCE:
            try:
                obs = self.env.step(scroll_step_action, pause=DEFAULT_PAUSE)
            except Exception as ex:
                logger.debug("scroll-aggregate: swipe failed (%s); stopping", ex)
                termination = "error"
                break
            steps += 1
            shot = obs.get("screenshot")
            if not shot:
                termination = "error"
                break
            try:
                view = self._frame_phash(shot)
            except Exception:
                termination = "error"
                break
            if (view - prev_view) <= VIEW_STABLE_DISTANCE:
                # viewport did not move — at the bottom (or non-scrollable). Wait
                # SCROLL_PATIENCE such frames to absorb a single jittery dump.
                stale += 1
                prev_view = view
                continue
            stale = 0
            moved_any = True
            prev_view = view
            # perceive the newly-scrolled viewport and keep only genuinely-new
            # clickable elements (the same button shifted up is deduped out).
            # STITCH MODE: detect boxes WITHOUT VLM naming — the per-viewport naming
            # is exactly the cost we are eliminating; the whole page is named ONCE on
            # the composite afterwards. Unnamed boxes still drive scroll_steps /
            # dedup / the element-anchored offset (all geometry/appearance, no name).
            new_elems = (self._detect_boxes_only(shot) if stitching
                         else self.perception.detect_and_name(shot))
            if not stitching:
                ScrollRuntime._accumulate_node_local_functions(self)
            # (root cause #1) BOUNDARY GUARD: a down-swipe past the end of the
            # in-app list over-scrolls onto the Android home/app-suggestion strip,
            # whose launcher icons (Phone/Gmail/Camera/Maps/YouTube...) then get
            # perceived and appended as phantom 'navigation' rows of this in-app
            # node — and clicking them goes off-app -> dead-end. (priority-4) The
            # over-scroll junk only appears once the swipe starts revealing NEW
            # elements past the list's real bottom, so we run the focus guard ONLY
            # on a frame that produced new elements (not on every mid-list swipe —
            # those clearly stayed on-app and the per-swipe on_app call was pure
            # cost). The moment such a frame is judged off-app, STOP and DISCARD
            # its elements entirely.
            if new_elems and self.focus_guard is not None:
                try:
                    if self.focus_guard.on_app(shot) is not True:
                        logger.info("scroll-aggregate: foreground ownership was "
                                    "not confirmed at step %d — stopping and "
                                    "discarding the frame", steps)
                        steps -= 1  # this frame's elements are NOT counted
                        termination = "focus_not_confirmed"
                        break
                except Exception as ex:
                    logger.debug("scroll-aggregate: focus check failed (%s)", ex)
            # Stitch capture: record this settled frame and the element-anchored
            # content offset (how far content moved up since the previous frame),
            # measured from the y-positions of elements common to both frames. This
            # is the ROBUST shift for flat low-texture lists where the stitcher's
            # pixel correlation is weak; the stitcher prefers it only then.
            if stitching:
                off = self._element_anchored_offset(
                    prev_frame_shot, prev_frame_elems, shot, new_elems)
                self._last_scroll_frames.append(shot)
                self._last_scroll_offsets.append(off)
                prev_frame_shot = shot
                prev_frame_elems = list(new_elems)
            added = 0
            for e in new_elems:
                _uid, is_new = matcher.match_or_add(shot, e.bbox_xywh)
                if is_new:
                    e.scroll_steps = steps
                    # below-fold element: crop from THIS scrolled frame (its bbox
                    # is in this frame's coords, not the top frame's).
                    e._template = _reloc.save_template(shot, e.bbox_xywh)
                    aggregated.append(e)
                    added += 1
            if added == 0:
                # viewport moved but revealed nothing new clickable — count toward
                # patience so a footer/empty tail still terminates.
                stale += 1
            if steps >= max_steps and stale < SCROLL_PATIENCE:
                # Rammed into the hard cap WITHOUT the patience/bottom signal
                # firing — suspicious (a real list bottom would have settled). The
                # trailing frames are the most likely to be over-scrolled junk.
                hit_cap = True
        # Restore the canonical TOP position. (root cause #1) The registered
        # screenshot is the top frame and every step-0 element center holds a
        # top-viewport y; if the page is left scrolled-down those centers tap the
        # wrong row. A blind ``steps`` up-swipes is unreliable (down/up swipe
        # distances differ → incomplete restore). Instead swipe up until the live
        # frame pHash-matches the registered top frame, with a bounded budget.
        if termination == "surface_changed":
            # We are no longer on the source surface.  An inverse swipe would act
            # on the wrong page and cannot prove canonical-top restoration.
            top_restored = False
        elif getattr(self, "_is_touch", True):
            top_restored = self._scroll_back_to_top(top_view, steps)
        else:
            # desktop: wheel back UP (positive vscroll) to restore the canonical top
            # position so step-0 element centers still tap the right rows.
            top_restored = True
            for _ in range(steps + 1):
                try:
                    self.env.step({"action_type": "SCROLL",
                                   "parameters": {"dy": DESKTOP_WHEEL_CLICKS}}, pause=0.2)
                except Exception:
                    top_restored = False
                    break
        if hit_cap:
            termination = "hard_cap"
        elif stale >= SCROLL_PATIENCE:
            termination = "viewport_stable"
        elif termination == "unknown":
            termination = "error"
        if state_id:
            classification = "scrollable" if moved_any else "static"
            self._record_scroll_evidence(
                scope_id=f"state:{state_id}:page", state_id=state_id,
                role="page", classification=classification,
                termination=termination,
                bottom_reached=(termination == "viewport_stable"),
                top_restored=bool(top_restored), steps=steps,
                max_steps=max_steps,
                detail=("hard scroll cap reached" if hit_cap
                        else surface_change_detail),
            )
        if hit_cap:
            # Non-terminating list: drop the runaway tail so the element set is
            # STABLE across visits (else the same page is captured with a varying
            # count). ``aggregated`` is in scroll order (step-0 rows first, then
            # the below-fold rows as they were revealed), so keep ALL step-0 rows
            # plus only the first MAX_BELOW_FOLD_ON_RUNAWAY below-fold rows — a
            # fixed COUNT, hence reproducible despite non-deterministic fling
            # distance per swipe.
            before = len(aggregated)
            kept: List[VisualElement] = []
            below = 0
            for e in aggregated:
                if getattr(e, "scroll_steps", 0) <= 0:
                    kept.append(e)
                elif below < MAX_BELOW_FOLD_ON_RUNAWAY:
                    kept.append(e)
                    below += 1
            aggregated = kept
            if len(aggregated) < before:
                logger.warning(
                    "scroll-aggregate: hit max scroll steps (%d) without a bottom/"
                    "patience signal — non-terminating list; trimmed %d runaway-tail "
                    "rows (kept top viewport + %d below-fold = %d total) so the "
                    "node's element set is stable across visits",
                    max_steps, before - len(aggregated), below,
                    len(aggregated))
        if steps:
            logger.info("scroll-aggregate: %d clickable over %d down-swipes "
                        "(%d revealed below the fold)",
                        len(aggregated), steps, len(aggregated) - len(first_elements))
        return aggregated

    def _desktop_regional_scroll(self, obs, first_elements,
                                 state_id: str = ""):
        """DESKTOP region-aware scroll-aggregate.

        Desktop panels (Settings sidebar vs content) scroll INDEPENDENTLY, so the
        old single center-parked wheel only covered the content pane. Here we:
          1. cluster the top-viewport elements into candidate panels (left column
             = sidebar, right = content) from their x-centers;
          2. wheel-DIFF each panel (park cursor over it, scroll, diff the crop) to
             learn which actually scrolls — immune to hidden overlay scrollbars;
          3. scroll each scrollable panel to the bottom (cursor parked OVER it),
             re-perceiving and de-duping revealed rows (appearance match), tagging
             each with scroll_steps + a relocation template, then restore to top.
        Returns the unioned element list. Never raises (falls back to the top set).
        """
        import io
        import numpy as np
        from PIL import Image
        try:
            import imagehash
        except Exception:
            imagehash = None

        self._last_scroll_frames = []
        self._last_scroll_offsets = []
        shot0 = obs.get("screenshot")
        if not shot0:
            if state_id:
                self._record_scroll_evidence(
                    scope_id=f"state:{state_id}:page", state_id=state_id,
                    role="page", classification="unknown",
                    termination="error", top_restored=False,
                    detail="initial screenshot missing")
            return first_elements
        matcher = ElementMatcher()
        for e in first_elements:
            try:
                matcher.match_or_add(shot0, e.bbox_xywh)
                e.scroll_steps = 0
                e._template = _reloc.save_template(shot0, e.bbox_xywh)
            except Exception:
                pass
        aggregated = list(first_elements)
        # [REGION-SCROLL CHANGE 6 dedup] also de-dup by (normalized name, type) so a
        # look-alike row re-perceived at a slightly different scroll offset (appearance
        # match missed it) is not stored twice — fewer duplicate templates to false-
        # match against later. Seeded from the top-viewport set.
        _seen_nt = {(_norm_name(a.name), a.el_type) for a in aggregated
                    if (a.name or "").strip()}

        try:
            sw, sh = self._screen_wh(obs)
        except Exception:
            sw, sh = 1920, 1080
        win = getattr(self.perception, "last_window_xywh", None) or [0, 0, sw, sh]
        wx, wy, ww, wh = win

        def bbox_of(els, fb):
            if not els:
                return fb
            x0 = min(e.bbox_xywh[0] for e in els); y0 = min(e.bbox_xywh[1] for e in els)
            x1 = max(e.bbox_xywh[0] + e.bbox_xywh[2] for e in els)
            y1 = max(e.bbox_xywh[1] + e.bbox_xywh[3] for e in els)
            return [x0, y0, x1, y1]

        split_x = wx + 0.45 * ww
        left = [e for e in first_elements if e.center[0] < split_x]
        right = [e for e in first_elements if e.center[0] >= split_x]
        regions = []
        if len(left) >= 4:  # a tall left column of rows = a nav sidebar
            regions.append(("sidebar", bbox_of(left, [wx, wy, int(wx + 0.3 * ww), wy + wh])))
        regions.append(("content", bbox_of(right, [int(wx + 0.5 * ww), wy, wx + ww, wy + wh])))

        def gray_crop(b, rect):
            a = np.asarray(Image.open(io.BytesIO(b)).convert("L"), dtype=np.int16)
            x0, y0, x1, y1 = rect
            return a[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]

        def region_changed(a_b, b_b, rect):
            try:
                ca = gray_crop(a_b, rect); cb = gray_crop(b_b, rect)
                if ca.size == 0 or ca.shape != cb.shape:
                    return 0.0
                return float((np.abs(ca - cb) > 15).mean())
            except Exception:
                return 0.0

        def crop_ph(b, rect):
            if imagehash is None:
                return None
            try:
                return imagehash.phash(Image.open(io.BytesIO(b)).convert("RGB").crop(tuple(rect)))
            except Exception:
                return None

        def scroll_at(x, y, direction, n=1):
            for _ in range(n):
                try:
                    self.env.step({"action_type": "SCROLL",
                                   "parameters": {"x": int(x), "y": int(y),
                                                  "direction": direction,
                                                  "amount": DESKTOP_WHEEL_CLICKS}}, pause=0.3)
                except Exception as ex:
                    logger.debug("regional scroll step failed (%s)", ex)
                    break

        def cur_shot():
            try:
                return self.env._get_obs().get("screenshot")
            except Exception:
                return None

        for label, rect in regions:
            scope_id = f"state:{state_id}:region:{label}" if state_id else ""
            cx = (rect[0] + rect[2]) // 2; cy = (rect[1] + rect[3]) // 2
            a = cur_shot()
            scroll_at(cx, cy, "down", 2)
            b = cur_shot()
            chg = region_changed(a, b, rect) if (a and b) else 0.0
            scroll_at(cx, cy, "up", 2)  # restore before deciding
            restored_probe = cur_shot()
            probe_top_restored = bool(
                a and restored_probe
                and region_changed(a, restored_probe, rect) <= 0.02)
            if chg <= 0.02:
                logger.info("regional scroll: %-7s static (changed=%.3f) — skip", label, chg)
                if scope_id:
                    self._record_scroll_evidence(
                        scope_id=scope_id, state_id=state_id, role=label,
                        classification="static", termination="static",
                        bottom_reached=True,
                        top_restored=probe_top_restored, steps=0,
                        max_steps=DESKTOP_MAX_SCROLL_STEPS)
                continue
            logger.info("regional scroll: %-7s SCROLLABLE (changed=%.3f)", label, chg)
            # [REGION-SCROLL CHANGE 11] cheap movement tracking every step (crop-pHash,
            # no VLM); VLM-ground only when the view changed ~a page since the last
            # grounding, plus once at the true bottom. Stop when the view stopped
            # moving AND nothing new appeared for SCROLL_PATIENCE frames.
            prev = crop_ph(cur_shot(), rect); last_g = prev; steps = 0; stale = 0
            termination = "unknown"
            while steps < DESKTOP_MAX_SCROLL_STEPS and stale < SCROLL_PATIENCE:
                scroll_at(cx, cy, "down", 1)
                steps += 1
                shot = cur_shot()
                if not shot:
                    termination = "error"
                    break
                cph = crop_ph(shot, rect)
                moved = not (prev is not None and cph is not None
                             and (cph - prev) <= VIEW_STABLE_DISTANCE)
                prev = cph
                big = (last_g is None or cph is None or (cph - last_g) >= GROUND_STRIDE_DISTANCE)
                do_ground = big or (not moved and stale == 0)   # per-page + bottom-once
                added = 0
                if do_ground:
                    last_g = cph
                    try:
                        fresh = self.perception.detect_and_name(shot)
                        ScrollRuntime._accumulate_node_local_functions(self)
                    except Exception as ex:
                        logger.debug("regional scroll perceive failed (%s)", ex)
                        fresh = []
                    for e in fresh:
                        if not (rect[0] - 10 <= e.center[0] <= rect[2] + 10):
                            continue
                        _nt = (_norm_name(e.name), e.el_type)
                        if _nt[0] and _nt in _seen_nt:
                            continue
                        try:
                            _uid, is_new = matcher.match_or_add(shot, e.bbox_xywh)
                        except Exception:
                            is_new = True
                        if is_new:
                            e.scroll_steps = steps
                            try:
                                e._template = _reloc.save_template(shot, e.bbox_xywh)
                            except Exception:
                                pass
                            aggregated.append(e); added += 1
                            if e.name and e.name.strip():
                                _seen_nt.add((_norm_name(e.name), e.el_type))
                # [2026-07-06] Terminate on CROP MOVEMENT alone, not `added`: VLM
                # grounding is non-deterministic, so a STATIC frame re-detects the
                # same controls (jittered bboxes → matcher counts each as new) →
                # added>0 forever → the old `and added == 0` scrolled a non-scrolling
                # region to max (dialog: 16 steps, 17 controls counted ~6×). Crop
                # unmoved for SCROLL_PATIENCE steps = no new content = stop.
                stale = stale + 1 if not moved else 0
            if stale >= SCROLL_PATIENCE:
                termination = "viewport_stable"
            elif steps >= DESKTOP_MAX_SCROLL_STEPS:
                termination = "hard_cap"
            elif termination == "unknown":
                termination = "error"
            if SCROLL_MAP_ENABLED:
                # [SCROLL-MAP CHANGE 18] absorbing-state restore: wheel up until
                # the panel stops changing — count-based restore under-/overshoots
                # when a step was clamped at the bottom. Parks on the label column
                # (a content-pane CENTER can be a wheel-eating slider).
                # revert: else-branch only.
                self._map_to_top(rect)
            else:
                scroll_at(cx, cy, "up", steps + 1)  # restore panel to canonical top
            restored = cur_shot()
            top_restored = bool(
                a and restored and region_changed(a, restored, rect) <= 0.02)
            if scope_id:
                self._record_scroll_evidence(
                    scope_id=scope_id, state_id=state_id, role=label,
                    classification="scrollable", termination=termination,
                    bottom_reached=(termination == "viewport_stable"),
                    top_restored=top_restored, steps=steps,
                    max_steps=DESKTOP_MAX_SCROLL_STEPS)
        logger.info("desktop regional scroll: %d total (%d revealed below the fold)",
                    len(aggregated), len(aggregated) - len(first_elements))
        return aggregated

    def _detect_boxes_only(self, shot: bytes) -> List[VisualElement]:
        """YOLO(+OCR) detection with NO VLM naming — geometry-only VisualElements.

        Used by the stitch-mode scroll capture: per-viewport NAMING is the VLM cost
        the stitcher removes (the page is named once on the composite), but the
        capture loop still needs per-frame boxes to dedup new content, record
        scroll_steps, and measure the element-anchored offset — none of which need a
        name. Returns lightweight elements carrying only ``bbox_xywh`` + ``center``
        (name/category empty); on any failure returns ``[]`` so the loop falls back
        to pHash-settle termination."""
        from ..visual_perception import _xyxy_ratio_to_xywh_px, _to_pil
        try:
            image = _to_pil(shot)
            w, h = image.size
            dets = self.perception.detect(image)
        except Exception as e:
            logger.debug("stitch capture: YOLO-only detect failed (%s)", e)
            return []
        out: List[VisualElement] = []
        for i, d in enumerate(dets):
            try:
                xywh, center = _xyxy_ratio_to_xywh_px(d["bbox"], w, h)
            except Exception:
                continue
            out.append(VisualElement(
                id=i, name="", bbox_xywh=xywh, center=center,
                el_type="icon", interactive=True,
                score=round(float(d.get("_score", 0.0)), 4), source="yolo"))
        return out

    @staticmethod
    def _element_anchored_offset(
        prev_shot: bytes, prev_elems: List[VisualElement],
        cur_shot: bytes, cur_elems: List[VisualElement],
    ) -> Optional[float]:
        """Content shift (px the content moved UP) from ``prev`` to ``cur``,
        measured from the y-positions of elements common to both frames.

        For the stitcher's element-anchored fallback (flat low-texture lists where
        pixel correlation is ambiguous): the SAME control appears in both viewports
        at a higher y in ``cur`` (content scrolled up), so ``prev_y - cur_y`` is the
        shift. We match each ``cur`` element to the visually-nearest ``prev``
        element (normalised-appearance pHash, the engine's own ElementMatcher
        distance) and take the MEDIAN delta over confident matches — the median is
        robust to a stray mis-match and to a row that genuinely left/entered the
        viewport. Returns ``None`` when too few elements match to trust a value
        (the stitcher then falls back to its pixel estimate)."""
        if not prev_elems or not cur_elems:
            return None
        try:
            from ..visual_state import _normalized_region_phash, ELEMENT_MATCH_DISTANCE
            import imagehash
            from PIL import Image
            import io as _io

            prev_img = Image.open(_io.BytesIO(prev_shot)).convert("RGB")
            cur_img = Image.open(_io.BytesIO(cur_shot)).convert("RGB")
        except Exception:
            return None

        # precompute prev-frame appearance hashes + centers once
        prev_hashes = []
        for e in prev_elems:
            try:
                ph = imagehash.hex_to_hash(_normalized_region_phash(prev_img, e.bbox_xywh))
                prev_hashes.append((ph, float(e.center[1])))
            except Exception:
                continue
        if not prev_hashes:
            return None

        deltas: List[float] = []
        for e in cur_elems:
            try:
                cph = imagehash.hex_to_hash(_normalized_region_phash(cur_img, e.bbox_xywh))
            except Exception:
                continue
            best_d, best_prev_y = 1 << 30, None
            for ph, py in prev_hashes:
                d = cph - ph
                if d < best_d:
                    best_d, best_prev_y = d, py
            if best_prev_y is not None and best_d <= ELEMENT_MATCH_DISTANCE:
                # content moved up => element y decreased => prev_y - cur_y > 0
                deltas.append(best_prev_y - float(e.center[1]))

        # need at least a couple of agreeing anchors to trust the median
        if len(deltas) < 2:
            return None
        deltas.sort()
        mid = len(deltas) // 2
        median = (deltas[mid] if len(deltas) % 2 == 1
                  else 0.5 * (deltas[mid - 1] + deltas[mid]))
        return float(median) if median > 0 else None

    def _scroll_back_to_top(self, top_view, down_steps: int) -> bool:
        """Swipe up until the live frame matches the registered top frame.

        Verifies the restore by pHash-comparing each frame against ``top_view``
        (the frame the node was registered from) instead of trusting a fixed
        up-swipe count — down- and up-swipe travel differently, so a blind
        ``down_steps`` up-swipes routinely leaves the page mid-list, desyncing
        every stored element center from the live page (root cause #1). Budget is
        generous (down_steps + 3) but bounded so a non-scrollable/jittery page
        can't hang. Best-effort: stops on any error."""
        if down_steps <= 0:
            return True
        budget = max(0, down_steps) + 3
        for _ in range(budget):
            try:
                obs = self.env.step(_scroll_action("up"), pause=1.0)
            except Exception:
                return False
            shot = obs.get("screenshot")
            if not shot:
                return False
            try:
                view = self._frame_phash(shot)
            except Exception:
                return False
            if (view - top_view) <= VIEW_STABLE_DISTANCE:
                return True  # back at the registered top view
        logger.debug("scroll-aggregate: could not confirm restore-to-top within "
                     "%d up-swipes; element centers may be slightly off", budget)
        return False
