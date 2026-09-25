"""Canonical visual element matching and appearance identity."""
from __future__ import annotations

import hashlib
import io
import logging
from typing import Dict, List

import imagehash
from PIL import Image

logger = logging.getLogger(__name__)

# pHash Hamming distance <= this => same state (matches traversal default).
PHASH_DISTANCE_THRESHOLD = 5
# SSIM >= this confirms a pHash match is a true duplicate.
SSIM_CONFIRM_THRESHOLD = 0.85


def _to_pil(screenshot_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")


def _normalized_region_phash(img: Image.Image, bbox_xywh: List[int],
                             expand: float = 0.12, size: int = 64) -> str:
    """pHash of an element crop, made robust to YOLO/OCR box jitter.

    Two normalisations absorb the "this time the box is bigger, next time
    smaller" problem the user flagged:
      * expand the box by ``expand`` on each side (eat boundary wobble), then
      * resize the crop to a fixed ``size``x``size`` before hashing.
    Works for nameless icon buttons too — it is purely visual.
    """
    w, h = img.size
    x, y, bw, bh = bbox_xywh
    ex, ey = int(bw * expand), int(bh * expand)
    x0 = max(0, x - ex)
    y0 = max(0, y - ey)
    x1 = min(w, x + bw + ex)
    y1 = min(h, y + bh + ey)
    if x1 <= x0 or y1 <= y0:
        return "0" * 16
    crop = img.crop((x0, y0, x1, y1)).resize((size, size))
    return str(imagehash.phash(crop))


# [方向1 2026-07-08] REMOVED chrome_band_phash + CHROME_TOP/BOT_FRAC: the
# content-insensitive chrome-band pHash only fed the removed loose-candidate →
# VLM-judge merge path. Identity is now region-set / button-set content, so the
# chrome band has no consumer. revert: restore from git with _loose_candidates.


def compute_element_uid(screenshot_bytes: bytes, bbox_xywh: List[int],
                        occurrence: int = 0) -> str:
    """Scroll-invariant visual identity for one element.

    uid = normalised-appearance pHash (+ an occurrence index only when several
    same-looking elements coexist on one screen). It deliberately does NOT use
    absolute screen position, so scrolling a button up/down keeps its uid — the
    bug this replaces. ``occurrence`` disambiguates visually identical siblings
    and is assigned by :func:`assign_element_uids`.
    """
    img = _to_pil(screenshot_bytes)
    region_hash = _normalized_region_phash(img, bbox_xywh)
    raw = region_hash if occurrence == 0 else f"{region_hash}#{occurrence}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def assign_element_uids(screenshot_bytes: bytes, elements) -> None:
    """Assign a scroll-invariant ``uid`` to each element in-place.

    Elements sharing the same normalised appearance hash get an occurrence
    index in reading order (top→bottom, left→right) so a row of identical
    icons stays distinguishable, while a single button keeps a stable, position-
    free uid across scrolls. ``elements`` are objects with ``.bbox_xywh``,
    ``.center`` and a writable ``.uid`` (VisualElement).
    """
    img = _to_pil(screenshot_bytes)
    # reading order so occurrence indices are deterministic across visits
    order = sorted(range(len(elements)),
                   key=lambda i: (elements[i].center[1], elements[i].center[0]))
    seen: Dict[str, int] = {}
    for i in order:
        el = elements[i]
        ph = _normalized_region_phash(img, el.bbox_xywh)
        occ = seen.get(ph, 0)
        seen[ph] = occ + 1
        raw = ph if occ == 0 else f"{ph}#{occ}"
        el.uid = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


# Ubiquitous chrome labels that appear on many pages are excluded from the
# folded functional summary and coverage universe.
_GENERIC_BUTTONS = frozenset({
    "back", "navigate up", "up", "more options", "more", "menu", "close", "ok",
    "cancel", "done", "next", "search",
    # [REGION-SCROLL CHANGE 5b] window controls are chrome, never page content —
    # drop them so a content-empty page's signature doesn't collapse to {min,max}
    # and falsely match another empty page.
    "minimize", "maximize", "restore", "unmaximize", "minimise", "maximise",
    "返回", "向上", "更多", "更多选项", "菜单", "关闭", "确定", "取消", "下一步", "搜索",
    "最小化", "最大化", "还原",
})


def normalize_button_names(names) -> set:
    """Normalize grounded names for page identity and coverage ledgers."""
    out = set()
    for name in names or []:
        value = " ".join(str(name or "").lower().split())
        if len(value) < 2 or value in _GENERIC_BUTTONS:
            continue
        out.add(value)
    return out


# Element appearance match threshold (pHash Hamming distance). Two crops within
# this distance are treated as the SAME element — absorbs YOLO/OCR box jitter
# (measured 6-26 bits under jitter, so精确相等 fails; approximate matching works).
ELEMENT_MATCH_DISTANCE = 12


class ElementMatcher:
    """Node-internal element identity by approximate appearance matching.

    Realises the user's insight: scrolling does NOT create a new page, so the
    question is never "what is this element's global id" but "within THIS page
    node, have I already seen this element?". We answer it by comparing the
    normalised-appearance pHash against the elements already recorded for the
    node, using Hamming distance <= ELEMENT_MATCH_DISTANCE (not string equality,
    which breaks under box jitter). Each node owns one matcher; scrolling feeds
    newly detected elements through ``match_or_add`` to accumulate only the
    genuinely new ones.
    """

    def __init__(self, distance: int = ELEMENT_MATCH_DISTANCE):
        self.distance = distance
        self._hashes: List[imagehash.ImageHash] = []  # one per known element
        self._uids: List[str] = []

    def _uid_for(self, ph_hex: str, slot: int) -> str:
        raw = f"{ph_hex}@{slot}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    def match_or_add(self, screenshot_bytes: bytes, bbox_xywh: List[int]):
        """Return (uid, is_new) for an element on the current screen.

        is_new=False means it matches an element already seen in this node
        (e.g. the same button before/after a scroll) and should not be
        re-explored; True means it is genuinely new (freshly revealed).
        """
        img = _to_pil(screenshot_bytes)
        ph = imagehash.hex_to_hash(_normalized_region_phash(img, bbox_xywh))
        best_i, best_d = -1, 1 << 30
        for i, known in enumerate(self._hashes):
            d = ph - known
            if d < best_d:
                best_i, best_d = i, d
        if best_i >= 0 and best_d <= self.distance:
            return self._uids[best_i], False
        slot = len(self._hashes)
        uid = self._uid_for(str(ph), slot)
        self._hashes.append(ph)
        self._uids.append(uid)
        return uid, True

    def __len__(self) -> int:
        return len(self._hashes)
