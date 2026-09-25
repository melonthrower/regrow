"""Perception layer: screenshot -> YOLO boxes -> SoM numbering -> VLM naming.

Pure-visual element discovery. No a11y tree is read anywhere here.

Reuses OmniParser building blocks from ``gui_rewalk.env.utils`` (import-only):
``predict_yolo`` -> pixel-space xyxy, ``remove_overlap_new`` -> drop overlaps,
``get_parsed_content_icon`` -> Florence-2 caption fallback. The naming step
sends one Set-of-Mark (numbered) screenshot to the VLM via
``agent.predict_mm`` and asks for a JSON array of {id, name, type, interactive}.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .stateful import normalize_state_key
from .prompts.grounding import (
    SCROLL_MAP_TARGET_PROMPT,
    SCROLL_VIEWPORT_REVIEW_PROMPT,
    SEMANTIC_INVENTORY_PROMPT,
    SEMANTIC_TARGET_RECONCILIATION_PROMPT,
    TARGET_GROUNDING_PROMPT,
    VLM_GROUNDING_PROMPT,
    VLM_NAMING_PROMPT,
)

logger = logging.getLogger(__name__)

# A modal disables the page behind it.  Center-only cropping is unsafe because a
# wide background box can have its center inside the dialog while most of the box
# remains on the inactive page.  Keep a small amount of grounding-box jitter, but
# require the substantial majority of each box to occupy the modal surface.
MODAL_MIN_BBOX_COVERAGE = 0.80
ACTIVE_SURFACE_PAGE = "page"
ACTIVE_SURFACE_DIALOG = "dialog"
ACTIVE_SURFACE_POPUP_MENU = "popup_menu"
ACTIVE_OVERLAY_SURFACE_KINDS = frozenset({
    ACTIVE_SURFACE_DIALOG,
    ACTIVE_SURFACE_POPUP_MENU,
})


def _normalize_surface_kind(value: Any, *, is_modal: bool = False) -> str:
    """Return the canonical active-surface kind from tolerant VLM output.

    Older cached responses only contain ``is_modal``.  They remain valid and are
    conservatively treated as dialogs.  Popup/menu aliases are kept distinct so
    the touch traversal can avoid treating a short transient option surface as a
    long page that needs scroll aggregation.
    """
    normalized = "_".join(
        str(value or "").strip().casefold().replace("-", " ").split())
    aliases = {
        "": ACTIVE_SURFACE_DIALOG if is_modal else ACTIVE_SURFACE_PAGE,
        "main": ACTIVE_SURFACE_PAGE,
        "main_page": ACTIVE_SURFACE_PAGE,
        "window": ACTIVE_SURFACE_PAGE,
        "modal": ACTIVE_SURFACE_DIALOG,
        "modal_dialog": ACTIVE_SURFACE_DIALOG,
        "popup": ACTIVE_SURFACE_POPUP_MENU,
        "menu": ACTIVE_SURFACE_POPUP_MENU,
        "dropdown": ACTIVE_SURFACE_POPUP_MENU,
        "drop_down": ACTIVE_SURFACE_POPUP_MENU,
        "option_list": ACTIVE_SURFACE_POPUP_MENU,
        "options": ACTIVE_SURFACE_POPUP_MENU,
        "context_menu": ACTIVE_SURFACE_POPUP_MENU,
        "overflow_menu": ACTIVE_SURFACE_POPUP_MENU,
        "bottom_sheet": ACTIVE_SURFACE_POPUP_MENU,
    }
    kind = aliases.get(normalized, normalized)
    if kind not in {
            ACTIVE_SURFACE_PAGE,
            ACTIVE_SURFACE_DIALOG,
            ACTIVE_SURFACE_POPUP_MENU}:
        kind = ACTIVE_SURFACE_DIALOG if is_modal else ACTIVE_SURFACE_PAGE
    if is_modal and kind == ACTIVE_SURFACE_PAGE:
        return ACTIVE_SURFACE_DIALOG
    return kind


def _bbox_sufficiently_inside_surface(
    bbox_xywh: List[int],
    surface_xywh: Optional[List[int]],
    min_coverage: float = MODAL_MIN_BBOX_COVERAGE,
) -> bool:
    """Whether enough of an element bbox lies inside an active modal surface.

    Both boxes use pixel ``[x, y, width, height]`` coordinates.  Missing or
    malformed modal geometry fails closed: without a trustworthy active surface
    the traversal must not click possibly inactive background controls.
    """
    if not (isinstance(bbox_xywh, (list, tuple)) and len(bbox_xywh) == 4
            and isinstance(surface_xywh, (list, tuple))
            and len(surface_xywh) == 4):
        return False
    try:
        bx, by, bw, bh = (float(v) for v in bbox_xywh)
        sx, sy, sw, sh = (float(v) for v in surface_xywh)
        threshold = float(min_coverage)
    except (TypeError, ValueError):
        return False
    if bw <= 0 or bh <= 0 or sw <= 0 or sh <= 0:
        return False
    threshold = max(0.0, min(1.0, threshold))
    ix0, iy0 = max(bx, sx), max(by, sy)
    ix1, iy1 = min(bx + bw, sx + sw), min(by + bh, sy + sh)
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    return intersection / (bw * bh) >= threshold

# [G2 表单抑制退休, 2026-07-03; 2026-07-07 用户 删除开关] 表单"整表算一个功能"的判定交给
# VLM(category=shallow)+deterministic frontier;旧的 form_field_indices 结构启发式(几何盲、把导航侧栏误当
# 表单抹掉)已彻底退休,form_idx 恒空。


def _long_region_inventory_views(
    image: Image.Image,
    viewport_height_px: Any,
) -> List[Image.Image]:
    """Keep text legible by slicing a very tall map into overlapping views."""
    try:
        viewport_height = int(viewport_height_px)
    except (TypeError, ValueError):
        viewport_height = image.height
    viewport_height = max(1, min(image.height, viewport_height))
    tile_height = min(image.height, 2 * viewport_height)
    if image.height <= tile_height:
        return [image]
    overlap = max(1, viewport_height // 4)
    views: List[Image.Image] = []
    top = 0
    while top < image.height:
        bottom = min(image.height, top + tile_height)
        views.append(image.crop((0, top, image.width, bottom)))
        if bottom >= image.height:
            break
        next_top = bottom - overlap
        if image.height - next_top < tile_height:
            next_top = max(top + 1, image.height - tile_height)
        top = next_top
    return views


REGION_LONG_INVENTORY_MAX_VIEWS_PER_CALL = 4


@dataclass
class VisualElement:
    """A single detected, named, clickable region. Coordinates are pixels."""

    id: int                       # SoM index within its own state
    name: str                     # VLM-given semantic name (or caption fallback)
    bbox_xywh: List[int]          # [x, y, w, h] pixel space
    center: List[int]             # [cx, cy] pixel space — the click point
    el_type: str = "icon"         # button / icon / text / input / ...
    interactive: bool = True
    category: str = ""            # control | nav | input | static (VLM-assigned)
    back: bool = False            # [2026-07-07 用户] VLM-flagged "go back ONE level"
                                  # control (top-left ‹/Back/返回, or a dialog's own
                                  # close ×) — a backtrack STEP. NOT the window-close
                                  # × that quits the app (that is category=dangerous).
                                  # Consumed by _router_back; VLM labels, code doesn't
                                  # guess by position.
    selected: bool = False        # Observation-local active/highlighted state.
                                  # It is context for the Explorer, not completion
                                  # evidence by itself.
    score: float = 0.0            # YOLO confidence
    source: str = "yolo"          # yolo | caption | vlm | ocr
    uid: str = ""                 # cross-state visual identity (filled later)
    visited: bool = False
    scroll_steps: int = 0         # downward swipes from page top to reveal it
    priority: int = 0             # explore-order hint (0=nav .. 3=display); set
                                  # from category, NOT a keep/drop signal
    group: str = ""               # homogeneous-list group tag (VLM-assigned):
                                  # repeated same-kind items (multiple alarms /
                                  # contacts / songs) share one group label, so the
                                  # engine explores ONE representative not all N
    region: str = ""              # [REGION-SCROLL CHANGE 14] sub-region role this
                                  # element belongs to (nav_sidebar/content/toolbar/
                                  # tab_bar/form/...), set by _regional_scroll_dedup.
                                  # Carried into elem_dicts -> graph -> capability
                                  # synth's node->region->function grouping.
    region_id: str = ""           # [2026-07-08 用户 三层框架第2层] STABLE cross-node
                                  # region id (RegionRegistry rid, e.g. "r3"), set by
                                  # _regional_scroll_dedup alongside ``region``. Unlike
                                  # the role string (many regions share role
                                  # "nav_sidebar"), this is the identity the click
                                  # ledger keys on so a shared sidebar is deduped with
                                  # no seen_on>1 warm-up. Empty on mobile / no-dedup.
    abnormal_reason: str = ""     # terminal local outcome such as ``app_crash``;
                                  # persisted for resume/audit but never treated as
                                  # successful region/function coverage
    abnormal_detail: str = ""     # short human-readable evidence from focus guard
    # Appended after the legacy fields to preserve positional-constructor
    # compatibility.  Explicit availability is separate from the historically
    # noisy ``interactive`` guess.  ``None`` means the VLM did not provide
    # evidence, preserving old graphs/cached responses.  A visible disabled state
    # is terminal audit evidence, never a click candidate.
    enabled: Optional[bool] = None
    requires_permission: bool = False
    # Short VLM description of the visible blocking condition. It is
    # intentionally semantic context rather than a name-keyword heuristic.
    blocked_reason: str = ""
    # Stateful controls are orthogonal to the historical four-way category.
    # Most value widgets stay node-local, but a reversible control whose value
    # changes which functions are visible/reachable is a functional-surface
    # transition and must be explored, regardless of application/control label.
    # Fields are appended for positional-constructor and old-graph compatibility.
    stateful: bool = False
    state_key: str = ""
    state_value: str = ""          # off | on | mixed | unknown
    effect_scope: str = ""         # function_set | data_only | unknown
    reversible: Optional[bool] = None
    risk: str = ""                 # none | connectivity | destructive | authentication | unknown
    # The active surface is observation-local geometry used only for safe live
    # rebinding.  It remains sidecar evidence, never a portable recipe address.
    # Overlay-bound elements must be re-grounded on the same live surface before
    # a click; a background look-alike cannot inherit this binding.
    surface_kind: str = ""          # page | dialog | popup_menu
    surface_bbox_xywh: Optional[List[int]] = None
    surface_scrollable: Optional[bool] = None
    # Optional VLM stability judgement used only for local block identity.
    # False excludes a volatile value from the block member signature; None
    # preserves legacy/cached observations and remains eligible.
    identity_anchor: Optional[bool] = None
    geometry_status: str = "grounded"
    # Stable identity remains ``name``.  This optional current-frame alias is
    # the exact text on a subordinate button/value affordance inside a labeled
    # compound control and is used only for live rebinding.
    action_label: str = ""
    # Explorer-owned completion for this stable source-local button. ``visited``
    # remains a compatibility projection and becomes true only for a terminal
    # exploration status, never merely because one action was executed.
    exploration_status: str = ""  # pending | complete | covered | semantic_only | terminal
    covered_by: str = ""           # stable representative element id
    covered_by_state: str = ""     # representative source State; empty means local
    exploration_reason: str = ""   # auditable Explorer/framework resolution reason
    # Model-facing semantic context.  These fields preserve what the inventory
    # actually said instead of collapsing unlike controls into the legacy
    # ``navigation``/``shallow`` compatibility categories.
    purpose: str = ""
    expected_immediate_effect: str = ""
    visible_state: str = ""
    semantic_evidence: str = ""
    execution_safety: str = ""     # safe | do_not_execute | uncertain
    changes_available_controls: Optional[bool] = None
    # Current-frame Region boundary in pixel xyxy coordinates. It is persisted
    # only as grounding safety evidence and never used as a portable selector.
    region_bbox: Optional[List[int]] = None

    def is_dangerous(self) -> bool:
        category = " ".join((self.category or "").strip().lower().split())
        risk = " ".join((self.risk or "").strip().lower().split())
        return category == "dangerous" or risk not in {"", "none"}

    def is_safe_stateful_surface(self) -> bool:
        """Whether this control may create a bounded functional-state branch.

        This is deliberately fail-closed: an ordinary toggle is not enough.
        Perception must explicitly say that it changes the available function
        set, is reversible, has no risk, and needs no permission/login.
        """
        return (
            bool(self.stateful)
            and self.effect_scope == "function_set"
            and self.state_value in {"off", "on"}
            and self.reversible is True
            and self.risk == "none"
            and self.enabled is not False
            and not self.requires_permission
            and not self.blocked_reason
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _function_record(element: VisualElement, category: str) -> Dict[str, Any]:
    """Portable observed-function record for controls not put on the frontier.

    Final destructive/commit buttons and ordinary form fields still describe
    application capabilities.  They must remain discoverable even when the
    exploration safety policy correctly refuses to click them.
    """
    return {
        "id": element.id,
        "name": element.name,
        "action_label": element.action_label,
        "el_type": element.el_type,
        "interactive": element.interactive,
        "enabled": element.enabled,
        "requires_permission": element.requires_permission,
        "blocked_reason": element.blocked_reason,
        "center": element.center,
        "bbox_xywh": element.bbox_xywh,
        "category": category,
        "group": element.group,
        "region": element.region,
        "region_id": element.region_id,
        "stateful": element.stateful,
        "state_key": element.state_key,
        "state_value": element.state_value,
        "effect_scope": element.effect_scope,
        "reversible": element.reversible,
        "risk": element.risk,
        "purpose": element.purpose,
        "expected_immediate_effect": element.expected_immediate_effect,
        "visible_state": element.visible_state,
        "semantic_evidence": element.semantic_evidence,
        "execution_safety": element.execution_safety,
        "changes_available_controls": element.changes_available_controls,
    }


def _optional_bool(value: Any) -> Optional[bool]:
    """Parse a VLM boolean without turning the string ``"false"`` into True."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


def _availability_from_item(item: Optional[Dict[str, Any]]) -> Tuple[Optional[bool], bool, str]:
    """Return backward-compatible availability fields from one VLM element."""
    item = item if isinstance(item, dict) else {}
    enabled = _optional_bool(item.get("enabled"))
    requires_permission = _optional_bool(item.get("requires_permission"))
    blocked_reason = str(item.get("blocked_reason") or "").strip().lower()
    return enabled, bool(requires_permission), blocked_reason


def _action_label_from_item(item: Optional[Dict[str, Any]], *, name: str,
                            interactive: bool, category: str) -> str:
    """Keep only a distinct live affordance label for an interactive control."""
    item = item if isinstance(item, dict) else {}
    label = str(item.get("action_label") or "").strip()
    if not interactive or category == "display":
        return ""
    normalize = lambda value: " ".join(str(value or "").casefold().split())
    return "" if normalize(label) == normalize(name) else label


_STATE_VALUES = frozenset({"off", "on", "mixed", "unknown"})
_EFFECT_SCOPES = frozenset({"function_set", "data_only", "unknown"})
_STATE_RISKS = frozenset({
    "none", "connectivity", "destructive", "authentication", "unknown",
})
_SEMANTIC_CATEGORIES = frozenset({
    "navigation", "shallow", "dangerous", "display",
})
_SEMANTIC_RESULTS = frozenset({
    "opens", "acts", "read_only", "avoid",
})
_SEMANTIC_STATE_EFFECTS = frozenset({
    "controls", "value", "outside", "unclear",
})
_EXECUTION_SAFETY = frozenset({"safe", "do_not_execute", "uncertain"})


def _canonical_enum(value: Any, allowed, default: str = "unknown") -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "enabled": "on", "disabled": "off", "true": "on", "false": "off",
        "functionset": "function_set", "value_only": "data_only",
        "data": "data_only", "auth": "authentication",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in allowed else default


def _semantic_category_and_risk(
    item: Dict[str, Any], *, fixture_oracle: bool = False,
) -> Tuple[str, str]:
    """Parse the bbox-free inventory's execution semantics fail-closed."""
    if not fixture_oracle and "execution_safety" in item:
        safety = _canonical_enum(
            item.get("execution_safety"), _EXECUTION_SAFETY, "uncertain")
        if item.get("state") not in {None, ""}:
            state_effect = _canonical_enum(
                item.get("state_effect"), _SEMANTIC_STATE_EFFECTS, "")
            if state_effect in {"outside", "unclear"}:
                return "dangerous", "unknown"
        if safety != "safe":
            return "dangerous", "unknown"
        changes_controls = _optional_bool(
            item.get("changes_available_controls"))
        return (
            "navigation" if changes_controls is True else "shallow",
            "none",
        )
    if not fixture_oracle and "result" in item:
        result = _canonical_enum(
            item.get("result"), _SEMANTIC_RESULTS, "avoid")
        state_effect = _canonical_enum(
            item.get("state_effect"), _SEMANTIC_STATE_EFFECTS, "")
        if state_effect in {"outside", "unclear"}:
            result = "avoid"
        if result == "opens" and _optional_bool(item.get("selected")) is True:
            result = "acts"
        return {
            "opens": ("navigation", "none"),
            "acts": ("shallow", "none"),
            "read_only": ("display", "none"),
            "avoid": ("dangerous", "unknown"),
        }[result]
    category_default = "navigation" if fixture_oracle else "dangerous"
    category = _canonical_enum(
        item.get("category"), _SEMANTIC_CATEGORIES, category_default)
    if category == "display":
        return category, "none"
    if "risk" not in item and fixture_oracle:
        return category, "none"
    risk = _canonical_enum(item.get("risk"), _STATE_RISKS)
    return category, risk


def _state_semantics_from_item(
    item: Optional[Dict[str, Any]],
) -> Tuple[bool, str, str, str, Optional[bool], str]:
    """Parse structured state semantics without guessing from control names."""
    item = item if isinstance(item, dict) else {}
    if "result" in item or "execution_safety" in item:
        if item.get("state") in {None, ""}:
            return False, "", "", "", None, ""
        state_value = _canonical_enum(item.get("state"), _STATE_VALUES)
        state_key = normalize_state_key(
            item.get("state_axis") or item.get("state_key") or item.get("name"))
        if "state_effect" in item:
            state_effect = _canonical_enum(
                item.get("state_effect"), _SEMANTIC_STATE_EFFECTS, "unclear")
            effect_scope = {
                "controls": "function_set",
                "value": "data_only",
                "outside": "unknown",
                "unclear": "unknown",
            }[state_effect]
            safe = state_effect in {"controls", "value"}
            return (
                True,
                state_key,
                state_value,
                effect_scope,
                True if safe else None,
                "" if safe else "unknown",
            )
        changes_controls = _optional_bool(item.get("changes_controls"))
        effect_scope = (
            "function_set" if changes_controls is True
            else "data_only" if changes_controls is False
            else "unknown"
        )
        return (
            True,
            state_key,
            state_value,
            effect_scope,
            _optional_bool(item.get("reversible")),
            "",
        )
    state_fields = {
        "stateful", "state_key", "state_value", "effect_scope", "reversible",
    }
    if not any(field in item for field in state_fields):
        # Preserve the exact old-cache/old-graph defaults.  Empty means the old
        # schema did not make a state claim; ``unknown`` means the new schema was
        # present but the model could not determine that field.
        risk = (_canonical_enum(item.get("risk"), _STATE_RISKS)
                if "risk" in item else "")
        return False, "", "", "", None, risk
    effect_scope = _canonical_enum(item.get("effect_scope"), _EFFECT_SCOPES)
    stateful_raw = _optional_bool(item.get("stateful"))
    if stateful_raw is False and not any(
            field in item for field in (
                "state_key", "state_value", "effect_scope", "reversible")):
        risk = (_canonical_enum(item.get("risk"), _STATE_RISKS)
                if "risk" in item else "")
        return False, "", "", "", None, risk
    stateful = bool(stateful_raw) or effect_scope == "function_set"
    state_key = normalize_state_key(item.get("state_key"))
    state_value = _canonical_enum(item.get("state_value"), _STATE_VALUES)
    reversible = _optional_bool(item.get("reversible"))
    risk = _canonical_enum(item.get("risk"), _STATE_RISKS)
    return stateful, state_key, state_value, effect_scope, reversible, risk


_STATEFUL_WIDGET_TYPES = frozenset({
    "switch", "toggle", "checkbox", "radio", "radio button",
})


def _dedupe_stateful_aliases(
    elements: List["VisualElement"],
) -> List["VisualElement"]:
    """Collapse row-label/control aliases that describe one state axis.

    Mobile Settings commonly grounds both the whole labelled row and its compact
    trailing switch as interactive stateful controls.  A stable ``state_key`` is
    their semantic identity; the smallest explicit widget is the safest click
    target.  Conflicting known values are retained fail-closed.
    """
    grouped: Dict[str, List[Tuple[int, VisualElement]]] = {}
    for index, element in enumerate(elements or []):
        key = normalize_state_key(getattr(element, "state_key", ""))
        if bool(getattr(element, "stateful", False)) and key:
            grouped.setdefault(key, []).append((index, element))
    if not any(len(items) > 1 for items in grouped.values()):
        return list(elements or [])

    keep_ids = {id(element) for element in (elements or [])}
    for _key, items in grouped.items():
        if len(items) < 2:
            continue
        known_values = {
            str(getattr(element, "state_value", "") or "").casefold()
            for _index, element in items
            if str(getattr(element, "state_value", "") or "").casefold()
            in {"off", "on"}
        }
        if len(known_values) > 1:
            continue

        def _rank(item: Tuple[int, VisualElement]):
            index, element = item
            element_type = " ".join(
                str(getattr(element, "el_type", "") or "")
                .casefold().split())
            try:
                area = max(1, int(element.bbox_xywh[2])) * max(
                    1, int(element.bbox_xywh[3]))
            except Exception:
                area = 1 << 60
            return (
                element_type in _STATEFUL_WIDGET_TYPES,
                getattr(element, "interactive", None) is not False,
                -area,
                -index,
            )

        _canonical_index, canonical = max(items, key=_rank)
        for _index, alias in items:
            if alias is canonical:
                continue
            keep_ids.discard(id(alias))
    return [element for element in (elements or []) if id(element) in keep_ids]


def _to_pil(screenshot_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")


_TOKEN_RE = re.compile(r"[0-9a-z一-鿿]+")


def _shares_token(a: str, b: str) -> bool:
    """True iff the two labels share any meaningful token (case-insensitive).

    Used to detect VLM name-vs-OCR drift on dense screenshots: if a box's VLM
    name and its own OCR text overlap in NO token, the VLM name was mis-bound to
    this box. Latin words are matched as whole tokens; CJK by single character
    (no word boundaries). Empty/whitespace-only inputs never 'share'."""
    ta = set(_TOKEN_RE.findall((a or "").lower()))
    tb = set(_TOKEN_RE.findall((b or "").lower()))
    # also compare CJK at character granularity so '网络设置' vs '网络' overlaps
    ta |= {c for c in (a or "").lower() if "一" <= c <= "鿿"}
    tb |= {c for c in (b or "").lower() if "一" <= c <= "鿿"}
    return bool(ta and tb and (ta & tb))


def _xyxy_ratio_to_xywh_px(box: List[float], w: int, h: int) -> Tuple[List[int], List[int]]:
    """[x0,y0,x1,y1] in [0,1] -> ([x,y,w,h]px, [cx,cy]px)."""
    x0, y0, x1, y1 = box
    px = int(round(x0 * w))
    py = int(round(y0 * h))
    pw = max(1, int(round((x1 - x0) * w)))
    ph = max(1, int(round((y1 - y0) * h)))
    cx = px + pw // 2
    cy = py + ph // 2
    return [px, py, pw, ph], [cx, cy]



# Structured functional-state semantics are appended separately so the legacy
# SoM prompt remains byte-for-byte reviewable despite its historical encoding.


# Grounding prompt: ONE call directly locates + names + classifies every element.
# Unlike VLM_NAMING_PROMPT (which only labels pre-drawn YOLO boxes), this asks
# the VLM to find the elements itself and return their bbox, so prominent rows
# YOLO never boxed (the Settings home "Network & internet") are recovered and no
# OCR garbage is produced. Coordinates are 0~1000 normalized (Qwen convention);
# the parser converts x/1000*W, y/1000*H. Same four-category taxonomy as naming.
# VLM grounding is RETRIED on an empty/failed result rather than dropping to
# YOLO+OCR: an empty grounding is almost always TRANSIENT (a timeout or unparseable
# JSON), and a re-ask returns the same high-quality elements — whereas YOLO+OCR
# misses prominent rows (Settings "Network & internet") AND injects OCR garbage the
# user does not trust. Bounded so a genuinely element-less frame still terminates.
_GROUNDING_MAX_ATTEMPTS = 1
_GROUNDING_REQUEST_TIMEOUT = float(
    os.environ.get("GUIWALK_GROUNDING_TIMEOUT", "150"))




# A functional state branch exists only when the current target application's
# own interactive surface expands or contracts.  Keep this boundary identical
# for SoM naming and direct grounding so layout/theme controls cannot enter the
# reversible state transaction merely because they visibly change the screen.


# Completion is a traversal transition when it safely creates or opens another
# in-app state.  Keep this context rule identical in both perception paths and
# deliberately avoid a label allowlist: the same word can be safe or sensitive.


# Keep the execution-facing category policy identical in both perception paths.
# The VLM proposes a compact feature-entry label; the engine still verifies the
# real transition after clicking and retains all existing safety gates.


def _draw_som(image: Image.Image, boxes_xywh: List[List[int]]) -> np.ndarray:
    """Draw numbered red boxes (Set-of-Mark) on a copy. Returns ndarray (RGB)."""
    img = image.copy()
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    for idx, (x, y, w, h) in enumerate(boxes_xywh):
        draw.rectangle([x, y, x + w, y + h], outline=(255, 0, 0), width=2)
        label = str(idx)
        ly = max(0, y - 16)
        # filled label chip for readability
        draw.rectangle([x, ly, x + 8 * len(label) + 4, ly + 15], fill=(255, 0, 0))
        draw.text((x + 2, ly), label, fill=(255, 255, 255), font=font)
    return np.asarray(img)


def _parse_vlm_json(raw: str):
    """Tolerant parse of the naming response.

    Returns ``(elements_list, meta)`` including the active-surface contract.
    Accepts the object shape {"window":..,"is_modal":..,"modal":..,"elements":[..]}
    or a bare [...] array (back-compat / model drift).
    """
    empty_meta = {
        "window": None,
        "is_modal": False,
        "modal": None,
        "surface_kind": ACTIVE_SURFACE_PAGE,
        "active_surface": None,
        "surface_scrollable": None,
        "is_system_dialog": False,
        "is_interruption": False,
        "page": None,
    }
    if not raw:
        return None, empty_meta
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?", "", txt).strip()
    txt = re.sub(r"```$", "", txt).strip()

    def _split(obj):
        if isinstance(obj, dict):
            is_modal = bool(obj.get("is_modal", False))
            surface_kind = _normalize_surface_kind(
                obj.get("surface_kind"), is_modal=is_modal)
            active_surface = obj.get("active_surface")
            if active_surface is None:
                active_surface = (obj.get("modal")
                                  if surface_kind in ACTIVE_OVERLAY_SURFACE_KINDS
                                  else obj.get("window"))
            # A structured popup/menu claim is itself an active-overlay claim,
            # even when an older/model-drift response forgot ``is_modal=true``.
            is_modal = bool(
                is_modal or surface_kind in ACTIVE_OVERLAY_SURFACE_KINDS)
            meta = {"window": obj.get("window"),
                    "is_modal": is_modal,
                    "modal": (obj.get("modal")
                              if obj.get("modal") is not None
                              else (active_surface if is_modal else None)),
                    "surface_kind": surface_kind,
                    "active_surface": active_surface,
                    "surface_scrollable": _optional_bool(
                        obj.get("surface_scrollable")),
                    "is_system_dialog": bool(obj.get("is_system_dialog", False)),
                    "is_interruption": bool(obj.get("is_interruption", False)),
                    "page": obj.get("page")}
            return obj.get("elements"), meta
        if isinstance(obj, list):
            return obj, dict(empty_meta)
        return None, dict(empty_meta)

    try:
        return _split(json.loads(txt))
    except Exception:
        pass
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    if m:
        try:
            return _split(json.loads(m.group(0)))
        except Exception:
            pass
    m = re.search(r"\[.*\]", txt, re.DOTALL)
    if m:
        try:
            return _split(json.loads(m.group(0)))
        except Exception:
            return None, dict(empty_meta)
    return None, dict(empty_meta)


class VisualPerception:
    """Detects and names clickable regions from a screenshot, no a11y.

    Parameters
    ----------
    yolo_model : ultralytics YOLO model (from get_yolo_model)
    agent : GUIGenAgent — used for VLM unified naming via predict_mm
    caption_mp : optional Florence-2 {'model','processor'} for caption fallback
    box_threshold / iou_threshold : YOLO detection / overlap-removal knobs
    use_ocr : when True, run easyocr to recover text-only entries (e.g. left-nav
        menu items) that YOLO can't box. These get merged via the same
        ``remove_overlap_new`` OCR-priority logic the full OmniParser uses.
    ocr_engine : "easyocr" (official default) or "paddleocr". OmniParser itself
        ships NO OCR model — it imports easyocr/paddleocr exactly like this.
    ocr_languages : easyocr language list (default English + simplified Chinese)
    """

    def __init__(
        self,
        yolo_model,
        agent=None,
        caption_mp: Optional[Dict[str, Any]] = None,
        box_threshold: float = 0.05,
        iou_threshold: float = 0.7,
        batch_size: int = 128,
        use_ocr: bool = True,
        ocr_engine: str = "easyocr",
        ocr_languages: Optional[List[str]] = None,
        ocr_text_threshold: float = 0.5,
    ):
        self.yolo_model = yolo_model
        self.agent = agent
        self.caption_mp = caption_mp
        self.box_threshold = box_threshold
        self.iou_threshold = iou_threshold
        self.batch_size = batch_size
        self.use_ocr = use_ocr
        self.ocr_engine = ocr_engine
        self.ocr_languages = ocr_languages or ["en", "ch_sim"]
        self.ocr_text_threshold = ocr_text_threshold
        self.last_som_image: Optional[np.ndarray] = None
        # When True, detect_and_name sources elements from a SINGLE VLM grounding
        # call (name+type+category+bbox in one shot) instead of YOLO+OCR+SoM-naming.
        # Recovers prominent rows YOLO misses (Settings "Network & internet") and
        # emits no OCR garbage. Set by the engine/run for the pure-visual path;
        # YOLO+OCR stays as the automatic fallback when grounding returns nothing.
        self.use_vlm_grounding = False
        self.use_semantic_inventory = False
        self.fixture_inventory_provider = None
        self.last_semantic_blocks: List[Dict[str, Any]] = []
        self.last_semantic_inventory_response: Optional[str] = None
        self.last_scroll_viewport_review: Dict[str, Any] = {}
        self.last_block_localization: Dict[str, Any] = {}
        self.last_target_grounding: Dict[str, Any] = {}
        self.last_scroll_map_grounding: Dict[str, Any] = {}
        self.last_window_xywh: Optional[List[int]] = None  # active surface px
        # [A: real-window crop] desktop engine sets this to the wmctrl window rect
        # [x,y,w,h]px so grounding is cropped to the app window (GNOME Dock + top
        # bar dropped, not clicked). None on mobile/unset → fall back to the
        # VLM-reported window bbox (self.last_window_xywh) below.
        self.window_px_override: Optional[List[int]] = None
        self.last_is_modal: bool = False
        self.last_surface_kind: str = ACTIVE_SURFACE_PAGE
        self.last_surface_scrollable: Optional[bool] = None
        self.last_passive_feedback_present: bool = False
        # [2026-07-07 用户] 整页 VLM 语义名(grounding 顺带出的 page 字段),供注册日志/
        # 监视窗口即时显示"这是什么页"(如"网络""蓝牙""搜索")。None = 本帧未命名。
        self.last_page_name: Optional[str] = None
        # [2026-07-07 用户] 过滤前的全量元素(含 display 标题),供 region-set 身份用。
        self.last_all_elements: List["VisualElement"] = []
        # [VLM label] the current overlay is a SYSTEM dialog (file chooser / print /
        # OS permission) — not an app function; engine skips exploring it. Set from
        # the grounding meta, replacing the old目录名 code heuristic.
        self.last_is_system_dialog: bool = False
        # [interruption dismiss] boot/first-run wizard, cookie/consent, update,
        # rating/permission/ad popup — an overlay to CLOSE, not explore; the engine
        # dismisses it to reveal the real page (task #42).
        self.last_is_interruption: bool = False
        self.last_node_local_functions: List[Dict[str, Any]] = []  # shallow recs
        self._ocr_reader = None  # lazy-initialised easyocr.Reader / PaddleOCR
        # Optional shared VLMRoleCache set by the engine. SoM naming uses a tight
        # pHash bucket; geometry-bearing grounding uses exact screenshot MD5 and
        # caches the raw response so every hit rebuilds fresh element objects.
        self.cache = None
        self.vlm_ledger = None
        self._cur_frame_bytes: Optional[bytes] = None  # frame being named now
        self.last_grounding_response: Optional[str] = None
        # [2026-07-07 用户 删除] state-reuse hook 已删(pHash 抄近路暗坑)——每帧真感知。

    @staticmethod
    def _semantic_token(value: Any) -> str:
        return "_".join(str(value or "").strip().casefold().replace("-", " ").split())

    @staticmethod
    def _json_object(response: Any) -> Optional[Dict[str, Any]]:
        text = str(response or "").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else None
        except Exception:
            match = re.search(r"\{.*\}", text, re.S)
            if not match:
                return None
            try:
                value = json.loads(match.group(0))
                return value if isinstance(value, dict) else None
            except Exception:
                return None

    def _review_scroll_viewports(
        self,
        screenshot_bytes: bytes,
        blocks: List[Dict[str, Any]],
        *,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Resolve a contradictory surface/block scroll declaration."""
        summary = [
            {
                "block_index": index,
                "role": block.get("role"),
                "bbox_1000": block.get("bbox_1000"),
                "scrollable": block.get("scrollable"),
                "elements": block.get("element_names"),
            }
            for index, block in enumerate(blocks)
        ]
        prompt = SCROLL_VIEWPORT_REVIEW_PROMPT.format(
            blocks_json=json.dumps(summary, ensure_ascii=False))
        image = _to_pil(screenshot_bytes).convert("RGB")
        evidence = Image.new("RGB", image.size, "black")
        width, height = image.size
        copied = False
        for block in blocks:
            bbox = block.get("bbox_1000")
            try:
                x0, y0, x1, y1 = [int(value) for value in bbox]
                box = (
                    max(0, min(width, round(x0 * width / 1000))),
                    max(0, min(height, round(y0 * height / 1000))),
                    max(0, min(width, round(x1 * width / 1000))),
                    max(0, min(height, round(y1 * height / 1000))),
                )
                if box[0] >= box[2] or box[1] >= box[3]:
                    continue
            except (TypeError, ValueError):
                continue
            evidence.paste(image.crop(box), box)
            copied = True
        if not copied:
            self.last_scroll_viewport_review = {
                "status": "uncertain",
                "reason": "active block evidence could not be cropped",
            }
            return []
        try:
            from .visual_cache import predict_mm_role
            response, *_ = predict_mm_role(
                self.agent, "scroll_viewport_review", prompt,
                [np.asarray(evidence)],
                getattr(self, "vlm_ledger", None),
                max_attempts=1, timeout_seconds=_GROUNDING_REQUEST_TIMEOUT,
                use_response_cache=not force_refresh)
        except Exception as exc:
            self.last_scroll_viewport_review = {
                "status": "uncertain", "reason": str(exc)[:240]}
            return []
        payload = self._json_object(response)
        status = str((payload or {}).get("status") or "").casefold()
        if status == "static" and not ((payload or {}).get("viewports") or []):
            self.last_scroll_viewport_review = {
                "status": "static",
                "reason": "movement review confirmed the active interface fits",
                "raw_response": str(response or ""),
            }
            return []
        if not payload or status != "ok":
            self.last_scroll_viewport_review = {
                "status": "uncertain",
                "reason": "movement review returned no confirmed viewport",
                "raw_response": str(response or ""),
            }
            return []

        reviewed: List[Dict[str, Any]] = []
        for raw in payload.get("viewports") or []:
            if not isinstance(raw, dict):
                continue
            try:
                bbox = [int(float(value)) for value in raw.get("bbox_1000")]
                if (len(bbox) != 4
                        or not (0 <= bbox[0] < bbox[2] <= 1000)
                        or not (0 <= bbox[1] < bbox[3] <= 1000)):
                    raise ValueError("invalid viewport bbox")
            except (TypeError, ValueError):
                self.last_scroll_viewport_review = {
                    "status": "uncertain",
                    "reason": "movement review violated the viewport schema",
                    "raw_response": str(response or ""),
                }
                return []
            reviewed.append({
                "bbox_1000": bbox,
                "reason": str(raw.get("reason") or "").strip(),
            })
        if not reviewed:
            self.last_scroll_viewport_review = {
                "status": "uncertain",
                "reason": "movement review returned an empty viewport list",
                "raw_response": str(response or ""),
            }
            return []
        self.last_scroll_viewport_review = {
            "status": "ok",
            "viewports": reviewed,
            "raw_response": str(response or ""),
        }
        return reviewed

    @staticmethod
    def _append_reviewed_scroll_viewports(
        blocks: List[Dict[str, Any]],
        viewports: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Add movement-only parent Regions without rewriting function blocks."""
        result = list(blocks)
        for viewport in viewports:
            result.append({
                "local_id": f"b{len(result)}",
                "role": "scroll_viewport",
                "scope": "target_app",
                "interaction": "direct",
                "note": str(viewport.get("reason") or ""),
                "scrollable": True,
                "bbox_1000": list(viewport["bbox_1000"]),
                "fixture_oracle": False,
                "element_ids": [],
                "element_names": [],
            })
        return result

    def semantic_inventory(self, screenshot_bytes: bytes, *,
                           force_refresh: bool = False,
                           navigation_context: str = "",
                           full_surface: bool = False) -> List["VisualElement"]:
        """Return semantic blocks/elements; neither contract contains geometry."""
        self._cur_frame_bytes = screenshot_bytes
        self.last_semantic_blocks = []
        self.last_semantic_inventory_response = None
        self.last_semantic_group_review = {}
        self.last_scroll_viewport_review = {}
        self.last_block_localization = {}
        self.last_target_grounding = {}
        self.last_page_name = None
        self.last_all_elements = []
        self.last_node_local_functions = []
        self.last_som_image = None
        self.last_window_xywh = None
        self.last_is_modal = False
        self.last_surface_kind = ACTIVE_SURFACE_PAGE
        self.last_surface_scrollable = None
        self.last_passive_feedback_present = False
        self.last_is_system_dialog = False
        self.last_is_interruption = False
        provider = getattr(self, "fixture_inventory_provider", None)
        if callable(provider):
            try:
                if full_surface:
                    try:
                        payload = provider(full_surface=True)
                    except TypeError:
                        payload = provider()
                else:
                    payload = provider()
            except Exception as exc:
                logger.warning("fixture oracle inventory failed: %s", exc)
                return []
            response = json.dumps(payload, ensure_ascii=False)
        else:
            if self.agent is None:
                return []
            image = _to_pil(screenshot_bytes)
            inventory_prompt = SEMANTIC_INVENTORY_PROMPT
            if str(navigation_context or "").strip():
                inventory_prompt += (
                    "\n\nNAVIGATION CONTEXT (factual supporting evidence):\n"
                    + str(navigation_context).strip()
                    + "\nUse this context only to disambiguate a visually sparse "
                      "destination. The screenshot remains primary, but do not "
                      "discard a clear source/action chain when naming an "
                      "ambiguous frame."
                )
            try:
                from .visual_cache import predict_mm_role
                response, *_ = predict_mm_role(
                    self.agent, "semantic_inventory", inventory_prompt,
                    [np.asarray(image)], getattr(self, "vlm_ledger", None),
                    max_attempts=1, timeout_seconds=_GROUNDING_REQUEST_TIMEOUT,
                    use_response_cache=not force_refresh)
            except Exception as exc:
                logger.warning("semantic inventory call failed: %s", exc)
                return []
            payload = self._json_object(response)
        if not payload:
            logger.warning("semantic inventory returned invalid JSON")
            return []
        self.last_semantic_inventory_response = str(response or "")
        self.last_page_name = str(
            payload.get("interface_summary")
            or payload.get("page")
            or "").strip() or None
        self.last_surface_kind = _normalize_surface_kind(payload.get("surface_kind"))
        self.last_is_modal = self.last_surface_kind in ACTIVE_OVERLAY_SURFACE_KINDS
        self.last_surface_scrollable = _optional_bool(payload.get("surface_scrollable"))
        self.last_passive_feedback_present = bool(
            payload.get("passive_feedback_present", False))
        self.last_is_system_dialog = bool(payload.get("is_system_dialog", False))
        self.last_is_interruption = bool(payload.get("is_interruption", False))
        elements: List[VisualElement] = []
        blocks: List[Dict[str, Any]] = []
        node_local: List[Dict[str, Any]] = []
        background_scrollable = False
        formal_inventory = not callable(provider)
        descriptive_inventory = (
            formal_inventory and isinstance(payload.get("areas"), list))
        raw_blocks = (
            payload.get("areas")
            if descriptive_inventory else payload.get("blocks")
        ) or []
        for raw_block in raw_blocks:
            if not isinstance(raw_block, dict):
                continue
            fixture_oracle = bool(raw_block.get("fixture_oracle", False))
            scope = (
                "target_app" if descriptive_inventory else
                str(raw_block.get("scope") or "").strip().casefold()
            )
            interaction = (
                "direct" if descriptive_inventory else
                str(raw_block.get("interaction") or "").strip().casefold()
            )
            if callable(provider) and not scope:
                scope = "target_app"
            if callable(provider) and not interaction:
                interaction = "direct"
            if scope not in {"target_app", "auxiliary"}:
                logger.warning(
                    "semantic inventory omitted invalid block scope for role=%r",
                    raw_block.get("role"))
                continue
            if interaction not in {"direct", "background"}:
                logger.warning(
                    "semantic inventory omitted invalid block interaction for role=%r",
                    raw_block.get("role"))
                continue
            if scope == "auxiliary" or interaction == "background":
                if (interaction == "background"
                        and raw_block.get("scrollable") is True):
                    background_scrollable = True
                continue
            members = [
                value for value in (
                    raw_block.get("controls")
                    if descriptive_inventory else raw_block.get("elements")
                ) or []
                if isinstance(value, dict)
            ]
            role = self._semantic_token(
                raw_block.get("name") if descriptive_inventory
                else raw_block.get("role")) or "other"
            local_id = f"b{len(blocks)}"
            block_bbox = raw_block.get("bbox_1000")
            try:
                if len(block_bbox) != 4:
                    raise ValueError("wrong bbox length")
                block_bbox = [int(float(value)) for value in block_bbox]
                if not (0 <= block_bbox[0] < block_bbox[2] <= 1000
                        and 0 <= block_bbox[1] < block_bbox[3] <= 1000):
                    raise ValueError("bbox outside normalized image")
            except (TypeError, ValueError, IndexError):
                block_bbox = None
            member_ids: List[int] = []
            for item in members:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                category, risk = _semantic_category_and_risk(
                    item, fixture_oracle=fixture_oracle)
                (stateful, state_key, state_value, effect_scope,
                 reversible, state_risk) = _state_semantics_from_item(item)
                if state_risk and (not fixture_oracle or "risk" in item):
                    risk = state_risk
                bbox = item.get("bbox_xywh")
                fixture_full_surface = bool(
                    fixture_oracle and full_surface
                    and isinstance(bbox, list) and len(bbox) == 4)
                if fixture_full_surface:
                    bbox = [int(round(float(value))) for value in bbox]
                    center = [bbox[0] + bbox[2] // 2,
                              bbox[1] + bbox[3] // 2]
                else:
                    bbox = [0, 0, 0, 0]
                    center = [0, 0]
                element = VisualElement(
                    id=len(elements), name=name, bbox_xywh=bbox, center=center,
                    el_type="target", interactive=category != "display",
                    category=category, risk=risk,
                    group=str(item.get("group") or "").strip().casefold(),
                    back=(bool(item.get("back", False))
                          if fixture_oracle else False),
                    selected=bool(item.get("selected", False)),
                    enabled=_optional_bool(item.get("enabled")),
                    requires_permission=(
                        bool(item.get("requires_permission", False))
                        if fixture_oracle else False),
                    blocked_reason=(
                        str(item.get("blocked_reason") or "").strip()
                        if fixture_oracle else ""),
                    stateful=stateful,
                    state_key=state_key,
                    state_value=state_value,
                    effect_scope=effect_scope,
                    reversible=reversible,
                    identity_anchor=(
                        _optional_bool(item.get("identity_anchor"))
                        if fixture_oracle else None),
                    score=1.0, source="semantic_inventory",
                    region=role, region_id=local_id,
                    surface_kind=self.last_surface_kind,
                    purpose=str(item.get("purpose") or "").strip(),
                    expected_immediate_effect=str(
                        item.get("expected_immediate_effect") or "").strip(),
                    visible_state=str(item.get("visible_state") or "").strip(),
                    semantic_evidence=str(item.get("evidence") or "").strip(),
                    execution_safety=str(
                        item.get("execution_safety") or "").strip().casefold(),
                    changes_available_controls=_optional_bool(
                        item.get("changes_available_controls")),
                    geometry_status=("fixture_full_surface"
                                     if fixture_full_surface else "semantic_only"))
                member_ids.append(element.id)
                elements.append(element)
            if member_ids or (fixture_oracle
                              and raw_block.get("scrollable") is True):
                blocks.append({"local_id": local_id, "role": role,
                               "scope": scope,
                               "interaction": interaction,
                               "note": str(
                                   raw_block.get("note") or "").strip(),
                               "context_labels": [
                                   str(value).strip()
                                   for value in raw_block.get(
                                       "context_labels") or []
                                   if str(value).strip()
                               ],
                               "scrollable": _optional_bool(raw_block.get("scrollable")),
                               "bbox_1000": block_bbox,
                               "fixture_oracle": fixture_oracle,
                               "element_ids": member_ids,
                               "element_names": [elements[i].name for i in member_ids]})
        scroll_contradiction = (
            not callable(provider)
            and self.last_surface_scrollable is True
            and blocks
            and all(block.get("scrollable") is False for block in blocks)
        )
        if scroll_contradiction and background_scrollable:
            self.last_surface_scrollable = False
            self.last_scroll_viewport_review = {
                "status": "static",
                "reason": (
                    "top-level scrollability was attributed only to an "
                    "explicitly background block"
                ),
            }
        elif scroll_contradiction:
            viewports = self._review_scroll_viewports(
                screenshot_bytes, blocks, force_refresh=force_refresh)
            if viewports:
                blocks = self._append_reviewed_scroll_viewports(
                    blocks, viewports)
            elif self.last_scroll_viewport_review.get("status") == "static":
                self.last_surface_scrollable = False
            else:
                # The surface and block scroll declarations contradict each
                # other. Preserve the uncertainty so completion cannot certify
                # the page as static.
                for block in blocks:
                    block["scrollable"] = None
        elements = _drop_inconsistent_group_labels(elements)
        self.last_semantic_blocks = blocks
        self.last_all_elements = list(elements)
        self.last_node_local_functions = node_local
        return elements

    def reconcile_semantic_targets(
            self, historical: List["VisualElement"],
            live: List["VisualElement"]) -> Dict[str, str]:
        """Map live aliases to old function targets without geometry."""
        self.last_semantic_target_reconciliation = {}
        if self.agent is None or not historical or not live:
            return {}
        historical_payload = [{
            "id": str(element.id),
            "name": str(element.name),
            "purpose": str(element.purpose or ""),
            "expected_immediate_effect": str(
                element.expected_immediate_effect or ""),
            "visible_state": str(element.visible_state or ""),
            "selected": bool(element.selected),
        } for element in historical]
        live_payload = [{
            "id": str(element.id),
            "name": str(element.name),
            "purpose": str(element.purpose or ""),
            "expected_immediate_effect": str(
                element.expected_immediate_effect or ""),
            "visible_state": str(element.visible_state or ""),
            "selected": bool(element.selected),
        } for element in live]
        prompt = SEMANTIC_TARGET_RECONCILIATION_PROMPT.format(
            historical_json=json.dumps(
                historical_payload, ensure_ascii=False, separators=(",", ":")),
            live_json=json.dumps(
                live_payload, ensure_ascii=False, separators=(",", ":")),
        )
        try:
            from .visual_cache import predict_mm_role
            response, *_ = predict_mm_role(
                self.agent, "semantic_target_reconciliation", prompt, [],
                getattr(self, "vlm_ledger", None), max_attempts=1,
                timeout_seconds=_GROUNDING_REQUEST_TIMEOUT)
        except Exception as exc:
            logger.warning("semantic target reconciliation failed: %s", exc)
            return {}
        payload = self._json_object(response)
        self.last_semantic_target_reconciliation = {
            "response": str(response or ""),
            "historical": historical_payload,
            "live": live_payload,
        }
        if not payload:
            return {}
        historical_by_id = {
            str(element.id): element for element in historical}
        live_by_id = {str(element.id): element for element in live}
        mappings: Dict[str, str] = {}
        used_historical = set()
        for row in payload.get("mappings") or []:
            if not isinstance(row, dict):
                continue
            live_id = str(row.get("live_id") or "")
            historical_id = str(row.get("historical_id") or "")
            live_element = live_by_id.get(live_id)
            historical_element = historical_by_id.get(historical_id)
            if (live_element is None
                    or historical_element is None
                    or historical_id in used_historical):
                continue
            mappings[live_id] = historical_id
            used_historical.add(historical_id)
        self.last_semantic_target_reconciliation["mappings"] = dict(mappings)
        return mappings

    def inventory_scrollable_region(
        self, image_bytes: bytes, block: Dict[str, Any], region_id: str,
    ) -> List["VisualElement"]:
        """Inventory one completed Region composite in bounded VLM batches."""
        self.last_region_long_inventory = {}
        if not image_bytes or not region_id:
            self.last_region_long_inventory = {"status": "invalid_request"}
            return []
        provider = getattr(self, "fixture_inventory_provider", None)
        if callable(provider):
            saved = {
                name: getattr(self, name)
                for name in (
                    "last_semantic_blocks", "last_all_elements",
                    "last_node_local_functions", "last_page_name",
                    "last_surface_kind", "last_is_modal",
                    "last_surface_scrollable", "last_is_system_dialog",
                    "last_is_interruption", "last_passive_feedback_present",
                    "last_semantic_inventory_response",
                )
            }
            try:
                all_elements = self.semantic_inventory(
                    image_bytes, full_surface=True)
                role = str(block.get("role") or "")
                matches = [
                    candidate for candidate in self.last_semantic_blocks
                    if str(candidate.get("role") or "") == role
                ]
                if len(matches) != 1:
                    self.last_region_long_inventory = {
                        "status": "fixture_region_ambiguous",
                        "role": role, "match_count": len(matches),
                    }
                    return []
                local_id = str(matches[0].get("local_id") or "")
                elements = [
                    element for element in all_elements
                    if str(getattr(element, "region_id", "") or "") == local_id
                ]
                for element in elements:
                    element.region = role
                    element.region_id = str(region_id)
                    element.source = "fixture_full_surface_inventory"
                    element.geometry_status = "fixture_full_surface"
                    element.scroll_steps = 0
                self.last_region_long_inventory = {
                    "status": "ok", "method": "fixture_oracle_full_surface",
                    "target_count": len(elements),
                    "region_id": str(region_id),
                }
                return elements
            finally:
                for name, value in saved.items():
                    setattr(self, name, value)
        if self.agent is None:
            self.last_region_long_inventory = {"status": "agent_unavailable"}
            return []
        image = _to_pil(image_bytes)
        views = _long_region_inventory_views(
            image, block.get("_viewport_height_px"))
        rows: List[Dict[str, Any]] = []
        responses: List[str] = []
        batch_size = REGION_LONG_INVENTORY_MAX_VIEWS_PER_CALL
        batch_count = (len(views) + batch_size - 1) // batch_size
        from .block_first_inventory import BlockFirstInventoryExperiment
        inventory = BlockFirstInventoryExperiment(
            self.agent, ledger=getattr(self, "vlm_ledger", None))
        context = {
            "interface_name": str(self.last_page_name or ""),
            "region_id": str(region_id),
            "name": str(block.get("role") or ""),
            "description": str(block.get("description")
                               or block.get("note") or ""),
            "bbox_1000": (
                block.get("viewport_bbox_1000")
                or block.get("bbox_1000")
            ),
            "scrollable": True,
        }
        for batch_index, start in enumerate(range(0, len(views), batch_size)):
            batch = views[start:start + batch_size]
            try:
                result = inventory.inventory_views(
                    batch, context, image_mode="long_region")
            except Exception as exc:
                self.last_region_long_inventory = {
                    "status": "request_failed", "detail": str(exc),
                    "failed_batch": batch_index + 1,
                    "batch_count": batch_count,
                }
                return []
            if result.get("status") != "ok":
                self.last_region_long_inventory = {
                    "status": str(result.get("status") or "invalid_response"),
                    "raw_response": str(result.get("raw_response") or ""),
                    "failed_batch": batch_index + 1,
                    "batch_count": batch_count,
                }
                return []
            rows.extend(result.get("function_entries") or [])
            responses.append(str(result.get("raw_response") or ""))
        elements: List[VisualElement] = []
        seen = set()
        for row in rows:
            name = str((row or {}).get("target") or "").strip() \
                if isinstance(row, dict) else ""
            key = " ".join(name.casefold().split())
            if not key or key in seen:
                continue
            seen.add(key)
            element = VisualElement(
                id=len(elements), name=name, bbox_xywh=[0, 0, 0, 0],
                center=[0, 0], el_type="button",
                interactive=True, category="control", risk="none",
                enabled=True, stateful=False,
                source="region_inventory",
                region=str(block.get("role") or ""), region_id=str(region_id),
                surface_kind=self.last_surface_kind,
                geometry_status="semantic_only",
                action_label=f"e{len(elements)}",
                execution_safety="safe")
            element.scroll_steps = 0
            elements.append(element)
        self.last_region_long_inventory = {
            "status": "ok", "raw_responses": responses,
            "target_count": len(elements), "region_id": str(region_id),
            "image_size": [image.width, image.height],
            "view_sizes": [[view.width, view.height] for view in views],
            "batch_count": batch_count,
        }
        return elements

    def ground_target(self, screenshot_bytes: bytes, stored_target: "VisualElement",
                      force_refresh: bool = False,
                      correction_hint: str = "") -> Optional["VisualElement"]:
        """Ground one target in normalized_1000 and convert it to image pixels."""
        self.last_target_grounding = {}
        if self.agent is None:
            self.last_target_grounding = {"status": "agent_unavailable"}
            return None
        image = _to_pil(screenshot_bytes)
        full_width, full_height = image.size
        siblings: List[str] = []
        region_bbox_1000 = None
        for block in self.last_semantic_blocks:
            if block.get("region_id") == getattr(stored_target, "region_id", ""):
                siblings = [str(v) for v in block.get("element_names") or []
                            if str(v) != str(getattr(stored_target, "name", ""))][:8]
                candidate_bbox = block.get("bbox_1000")
                if isinstance(candidate_bbox, list) and len(candidate_bbox) == 4:
                    region_bbox_1000 = list(candidate_bbox)
                break
        prompt_region_bbox_1000 = None
        if region_bbox_1000 is not None:
            try:
                rx0, ry0, rx1, ry1 = [
                    int(float(value)) for value in region_bbox_1000]
                candidate = [
                    max(0, min(1000, rx0)),
                    max(0, min(1000, ry0)),
                    max(0, min(1000, rx1)),
                    max(0, min(1000, ry1)),
                ]
                if candidate[0] < candidate[2] and candidate[1] < candidate[3]:
                    prompt_region_bbox_1000 = [
                        candidate[0], candidate[1], candidate[2], candidate[3],
                    ]
            except (TypeError, ValueError):
                prompt_region_bbox_1000 = None
        width, height = image.size
        if str(getattr(stored_target, "source", "") or "") == \
                "region_inventory":
            target = {
                "target": str(getattr(stored_target, "name", "") or ""),
                "region_bbox_1000": prompt_region_bbox_1000,
            }
        else:
            target = {
                "name": getattr(stored_target, "name", ""),
                "action_label": getattr(stored_target, "action_label", ""),
                "purpose": getattr(stored_target, "purpose", ""),
                "expected_immediate_effect": getattr(
                    stored_target, "expected_immediate_effect", ""),
                "visible_state": getattr(stored_target, "visible_state", ""),
                "block_role": getattr(stored_target, "region", ""),
                "region_bbox_1000": prompt_region_bbox_1000,
                "siblings": siblings,
            }
        prompt = TARGET_GROUNDING_PROMPT.format(
            width=width, height=height,
            target_json=json.dumps(target, ensure_ascii=False, sort_keys=True),
            correction_hint=str(correction_hint or "").strip())
        try:
            from .visual_cache import predict_mm_role
            response, *_ = predict_mm_role(
                self.agent, "target_grounding", prompt,
                [np.asarray(image)],
                getattr(self, "vlm_ledger", None), max_attempts=1,
                timeout_seconds=_GROUNDING_REQUEST_TIMEOUT,
                use_response_cache=not force_refresh)
        except Exception as exc:
            self.last_target_grounding = {"status": "request_failed", "detail": str(exc)}
            return None
        payload = self._json_object(response)
        diagnostic = {"raw_response": str(response or ""),
                      "force_refresh": bool(force_refresh),
                      "correction_hint": str(correction_hint or "")}
        if not payload or payload.get("found") is not True:
            diagnostic.update({"status": "target_not_found",
                               "reason": (payload or {}).get("reason", "invalid response")})
            self.last_target_grounding = diagnostic
            return None
        if payload.get("coordinate_space") != "normalized_1000":
            diagnostic.update({"status": "invalid_coordinate_space",
                               "reason": "coordinate_space must be normalized_1000",
                               "received_coordinate_space": payload.get(
                                   "coordinate_space")})
            self.last_target_grounding = diagnostic
            return None
        bbox, point = payload.get("bbox_1000"), payload.get("click_point_1000")
        try:
            if len(bbox) != 4 or len(point) != 2:
                raise ValueError("wrong geometry length")
            raw_values = list(bbox) + list(point)
            if any(isinstance(v, bool) or float(v) != int(float(v)) for v in raw_values):
                raise ValueError("coordinates must be normalized integers")
            x0, y0, x1, y1 = [int(float(v)) for v in bbox]
            cx, cy = [int(float(v)) for v in point]
        except (TypeError, ValueError, IndexError):
            diagnostic.update({"status": "invalid_geometry",
                               "reason": "missing/non-integer normalized coordinates"})
            self.last_target_grounding = diagnostic
            return None
        if any(value < 0 or value > 1000
               for value in (x0, y0, x1, y1, cx, cy)):
            diagnostic.update({"status": "coordinate_out_of_range",
                               "reason": "coordinate outside normalized_1000 range 0..1000",
                               "bbox_1000": [x0, y0, x1, y1],
                               "click_point_1000": [cx, cy]})
            self.last_target_grounding = diagnostic
            return None
        if not (x0 < x1 and y0 < y1):
            diagnostic.update({"status": "invalid_geometry",
                               "reason": "bbox_1000 must have positive area",
                               "bbox_1000": [x0, y0, x1, y1],
                               "click_point_1000": [cx, cy]})
            self.last_target_grounding = diagnostic
            return None
        if not (x0 <= cx < x1 and y0 <= cy < y1):
            diagnostic.update({"status": "invalid_geometry",
                               "reason": "click_point_1000 must be inside bbox_1000",
                               "bbox_1000": [x0, y0, x1, y1],
                               "click_point_1000": [cx, cy]})
            self.last_target_grounding = diagnostic
            return None
        px0 = max(
            0, min(width - 1, int(round(x0 / 1000.0 * width))))
        py0 = max(
            0, min(height - 1, int(round(y0 / 1000.0 * height))))
        px1 = max(
            0, min(width, int(round(x1 / 1000.0 * width))))
        py1 = max(
            0, min(height, int(round(y1 / 1000.0 * height))))
        pcx = max(
            0, min(width - 1, int(round(cx / 1000.0 * width))))
        pcy = max(
            0, min(height - 1, int(round(cy / 1000.0 * height))))
        if not (px0 < px1 and py0 < py1
                and px0 <= pcx < px1 and py0 <= pcy < py1):
            diagnostic.update({"status": "invalid_geometry",
                               "reason": "normalized geometry collapsed after pixel conversion",
                               "bbox_1000": [x0, y0, x1, y1],
                               "click_point_1000": [cx, cy],
                               "image_size": [width, height]})
            self.last_target_grounding = diagnostic
            return None
        grounded = VisualElement(
            id=int(getattr(stored_target, "id", 0)), name=str(stored_target.name),
            bbox_xywh=[px0, py0, px1 - px0, py1 - py0], center=[pcx, pcy],
            el_type=str(getattr(stored_target, "el_type", "other")), interactive=True,
            category=str(getattr(stored_target, "category", "")),
            source="vlm_target_ground", region=str(getattr(stored_target, "region", "")),
            region_id=str(getattr(stored_target, "region_id", "")),
            geometry_status="live_target",
            action_label=str(getattr(stored_target, "action_label", "") or ""),
            purpose=str(getattr(stored_target, "purpose", "") or ""),
            expected_immediate_effect=str(getattr(
                stored_target, "expected_immediate_effect", "") or ""),
            visible_state=str(getattr(stored_target, "visible_state", "") or ""),
            semantic_evidence=str(getattr(
                stored_target, "semantic_evidence", "") or ""),
            execution_safety=str(getattr(
                stored_target, "execution_safety", "") or ""),
            changes_available_controls=getattr(
                stored_target, "changes_available_controls", None))
        diagnostic.update({"status": "matched", "reason": str(payload.get("reason") or ""),
                           "coordinate_space": "normalized_1000",
                           "bbox_1000": [x0, y0, x1, y1],
                           "click_point_1000": [cx, cy],
                           "image_size": [full_width, full_height],
                           "grounding_crop_px_xyxy": None,
                           "target_region_bbox_1000": prompt_region_bbox_1000,
                           "bbox_px_xyxy": [px0, py0, px1, py1],
                           "click_point_px": [pcx, pcy]})
        self.last_target_grounding = diagnostic
        return grounded

    def ground_target_with_scroll_map(
        self, screenshot_bytes: bytes, region_map_bytes: bytes,
        stored_target: "VisualElement", *, force_refresh: bool = False,
        correction_hint: str = "",
    ) -> Optional["VisualElement"]:
        """Jointly locate one target from the live frame and its Region long map."""
        self.last_scroll_map_grounding = {}
        if self.agent is None or not screenshot_bytes or not region_map_bytes:
            self.last_scroll_map_grounding = {"status": "agent_unavailable"}
            return None
        image = _to_pil(screenshot_bytes)
        region_map = _to_pil(region_map_bytes)
        if str(getattr(stored_target, "source", "") or "") == \
                "region_inventory":
            target = {
                "target": str(getattr(stored_target, "name", "") or ""),
            }
        else:
            target = {
                "name": str(getattr(stored_target, "name", "") or ""),
                "purpose": str(getattr(stored_target, "purpose", "") or ""),
                "expected_immediate_effect": str(getattr(
                    stored_target, "expected_immediate_effect", "") or ""),
                "block_role": str(getattr(stored_target, "region", "") or ""),
            }
        prompt = SCROLL_MAP_TARGET_PROMPT.format(
            target_json=json.dumps(target, ensure_ascii=False, sort_keys=True),
            correction_hint=str(correction_hint or "").strip())
        try:
            from .visual_cache import predict_mm_role
            response, *_ = predict_mm_role(
                self.agent, "scroll_map_target", prompt,
                [np.asarray(image), np.asarray(region_map)],
                getattr(self, "vlm_ledger", None), max_attempts=1,
                timeout_seconds=_GROUNDING_REQUEST_TIMEOUT,
                use_response_cache=not force_refresh)
        except Exception as exc:
            self.last_scroll_map_grounding = {
                "status": "request_failed", "detail": str(exc)}
            return None
        payload = self._json_object(response)
        status = str((payload or {}).get("status") or "").strip().casefold()
        diagnostic: Dict[str, Any] = {
            "status": status or "invalid_response",
            "reason": str((payload or {}).get("reason") or ""),
            "raw_response": str(response or ""),
            "force_refresh": bool(force_refresh),
            "correction_hint": str(correction_hint or ""),
            "image_size": [image.width, image.height],
            "region_map_size": [region_map.width, region_map.height],
        }
        allowed = {"visible", "above", "below", "absent", "map_mismatch", "uncertain"}
        if status not in allowed:
            self.last_scroll_map_grounding = diagnostic
            return None
        if status in {"above", "below"}:
            anchor = (payload or {}).get("scroll_anchor_1000")
            try:
                if len(anchor) != 2:
                    raise ValueError("wrong anchor length")
                ax, ay = [int(float(value)) for value in anchor]
                if not (0 <= ax <= 1000 and 0 <= ay <= 1000):
                    raise ValueError("anchor outside normalized_1000")
            except (TypeError, ValueError, IndexError):
                diagnostic["status"] = "invalid_geometry"
                self.last_scroll_map_grounding = diagnostic
                return None
            diagnostic.update({
                "scroll_anchor_1000": [ax, ay],
                "scroll_anchor_px": [
                    max(0, min(image.width - 1,
                               int(round(ax / 1000.0 * image.width)))),
                    max(0, min(image.height - 1,
                               int(round(ay / 1000.0 * image.height)))),
                ],
            })
            self.last_scroll_map_grounding = diagnostic
            return None
        if status != "visible":
            self.last_scroll_map_grounding = diagnostic
            return None
        if (payload or {}).get("coordinate_space") != "normalized_1000":
            diagnostic["status"] = "invalid_coordinate_space"
            self.last_scroll_map_grounding = diagnostic
            return None
        bbox = (payload or {}).get("bbox_1000")
        point = (payload or {}).get("click_point_1000")
        try:
            if len(bbox) != 4 or len(point) != 2:
                raise ValueError("wrong geometry length")
            values = list(bbox) + list(point)
            if any(isinstance(value, bool)
                   or float(value) != int(float(value)) for value in values):
                raise ValueError("coordinates must be integers")
            x0, y0, x1, y1 = [int(float(value)) for value in bbox]
            cx, cy = [int(float(value)) for value in point]
            if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000
                    and x0 <= cx < x1 and y0 <= cy < y1):
                raise ValueError("geometry outside normalized_1000")
        except (TypeError, ValueError, IndexError):
            diagnostic["status"] = "invalid_geometry"
            self.last_scroll_map_grounding = diagnostic
            return None
        px0 = max(0, min(image.width - 1, int(round(x0 / 1000.0 * image.width))))
        py0 = max(0, min(image.height - 1, int(round(y0 / 1000.0 * image.height))))
        px1 = max(0, min(image.width, int(round(x1 / 1000.0 * image.width))))
        py1 = max(0, min(image.height, int(round(y1 / 1000.0 * image.height))))
        pcx = max(0, min(image.width - 1, int(round(cx / 1000.0 * image.width))))
        pcy = max(0, min(image.height - 1, int(round(cy / 1000.0 * image.height))))
        if not (px0 < px1 and py0 < py1 and px0 <= pcx < px1 and py0 <= pcy < py1):
            diagnostic["status"] = "invalid_geometry"
            self.last_scroll_map_grounding = diagnostic
            return None
        grounded = VisualElement(
            id=int(getattr(stored_target, "id", 0)),
            name=str(getattr(stored_target, "name", "")),
            bbox_xywh=[px0, py0, px1 - px0, py1 - py0],
            center=[pcx, pcy],
            el_type=str(getattr(stored_target, "el_type", "other")),
            interactive=True,
            category=str(getattr(stored_target, "category", "")),
            source="vlm_scroll_map_target",
            region=str(getattr(stored_target, "region", "")),
            region_id=str(getattr(stored_target, "region_id", "")),
            geometry_status="live_scroll_map_target",
            purpose=str(getattr(stored_target, "purpose", "") or ""),
            expected_immediate_effect=str(getattr(
                stored_target, "expected_immediate_effect", "") or ""),
            visible_state=str(getattr(stored_target, "visible_state", "") or ""),
            semantic_evidence=str(getattr(
                stored_target, "semantic_evidence", "") or ""),
            execution_safety=str(getattr(
                stored_target, "execution_safety", "") or ""),
            changes_available_controls=getattr(
                stored_target, "changes_available_controls", None))
        diagnostic.update({
            "bbox_1000": [x0, y0, x1, y1],
            "click_point_1000": [cx, cy],
            "bbox_px_xyxy": [px0, py0, px1, py1],
            "click_point_px": [pcx, pcy],
        })
        self.last_scroll_map_grounding = diagnostic
        return grounded

    def _get_ocr_reader(self):
        """Lazy OCR init, mirroring official OmniParser (which imports both
        easyocr and paddleocr). The repo's ``check_ocr_box`` references an
        uninitialised global ``paddle_ocr``/``reader`` (OCR was never actually
        wired here), so we own the reader instead of calling that helper.
        """
        if self._ocr_reader is None:
            import torch
            if self.ocr_engine == "paddleocr":
                from paddleocr import PaddleOCR
                # Match official OmniParser PaddleOCR config (lang fixed to 'en';
                # paddle's 'ch' model also reads latin, good enough for GUIs).
                self._ocr_reader = PaddleOCR(
                    lang="ch", use_angle_cls=False, show_log=False,
                    use_dilation=True, det_db_score_mode="slow")
            else:
                import easyocr
                self._ocr_reader = easyocr.Reader(
                    self.ocr_languages, gpu=torch.cuda.is_available())
        return self._ocr_reader

    def _ocr_elements(self, image: Image.Image) -> List[Dict[str, Any]]:
        """Return OCR text boxes as remove_overlap_new-style elements ([0,1] xyxy)."""
        from gui_rewalk.env.utils import int_box_area
        w, h = image.size
        img_np = np.asarray(image)
        try:
            reader = self._get_ocr_reader()
            if self.ocr_engine == "paddleocr":
                # paddle returns [[ [poly, (text, conf)], ... ]]
                result = reader.ocr(img_np, cls=False)[0] or []
                raw = [(item[0], item[1][0], item[1][1]) for item in result
                       if item[1][1] >= self.ocr_text_threshold]
            else:
                raw = reader.readtext(img_np, text_threshold=self.ocr_text_threshold)
        except Exception as e:
            logger.warning("OCR (%s) failed (%s); continuing YOLO-only",
                           self.ocr_engine, e)
            return []
        elems = []
        for poly, text, _conf in raw:
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            bbox = [min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h]
            if int_box_area(bbox, w, h) <= 0:
                continue
            elems.append({"type": "text", "bbox": bbox, "interactivity": False,
                          "content": (text or "").strip(),
                          "source": "box_ocr_content_ocr"})
        return elems

    # ── detection ────────────────────────────────────────────────────────
    def detect(self, image: Image.Image) -> List[Dict[str, Any]]:
        """YOLO (+optional OCR) + overlap removal. Returns dicts: [0,1] xyxy bbox.

        With OCR enabled the result includes text-only entries (e.g. left-nav
        menu items) that YOLO alone misses — the dominant gap measured on the
        Settings page (YOLO 56 vs YOLO+OCR 78 boxes).
        """
        from gui_rewalk.env.utils import predict_yolo, remove_overlap_new
        import torch

        image = image.convert("RGB")
        w, h = image.size
        xyxy, conf, _ = predict_yolo(
            model=self.yolo_model, image=image, box_threshold=self.box_threshold,
            imgsz=(h, w), scale_img=False, iou_threshold=0.1, yolo_print=False,
        )
        yolo_ratio = (xyxy / torch.tensor([w, h, w, h], device=xyxy.device)).cpu().tolist() \
            if len(xyxy) else []
        conf_list = conf.cpu().tolist() if len(xyxy) else []
        elems = [
            {"type": "icon", "bbox": b, "interactivity": True, "content": None, "_score": s}
            for b, s in zip(yolo_ratio, conf_list)
        ]

        ocr_bbox = self._ocr_elements(image) if self.use_ocr else None
        if not elems and not ocr_bbox:
            return []

        filtered = remove_overlap_new(
            boxes=elems, iou_threshold=self.iou_threshold, ocr_bbox=ocr_bbox or None)
        score_by_box = {tuple(e["bbox"]): e.get("_score", 0.0) for e in elems}
        for e in filtered:
            if "_score" not in e:
                e["_score"] = score_by_box.get(tuple(e["bbox"]), 0.0)
        return filtered or []

    # ── naming ───────────────────────────────────────────────────────────
    def _name_with_vlm(self, som_image: np.ndarray, n: int):
        """Return (names_by_id, meta). meta = {window, is_modal, modal}.

        Priority-4: memoised by the SOURCE frame's pHash via the shared cache (if
        wired). YOLO boxes are recomputed deterministically from the same frame,
        so a cached id->name table stays valid for an identical re-perception.
        """
        empty_meta = {
            "window": None,
            "is_modal": False,
            "modal": None,
            "surface_kind": ACTIVE_SURFACE_PAGE,
            "active_surface": None,
            "surface_scrollable": None,
        }
        if self.agent is None:
            return {}, empty_meta
        cache = getattr(self, "cache", None)
        frame = getattr(self, "_cur_frame_bytes", None)
        if cache is not None and frame:
            hit, cached = cache.lookup_naming(frame)
            if hit:
                return cached
        try:
            from .visual_cache import predict_mm_role
            resp, *_ = predict_mm_role(
                self.agent, "perception_naming", VLM_NAMING_PROMPT,
                [som_image], getattr(self, "vlm_ledger", None))
        except Exception as e:
            logger.warning("VLM naming call failed: %s", e)
            return {}, empty_meta
        parsed, meta = _parse_vlm_json(resp)
        if not parsed:
            logger.warning("VLM naming returned unparseable JSON; caption fallback")
            return {}, meta
        out: Dict[int, Dict[str, Any]] = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if 0 <= idx < n:
                out[idx] = item
        if cache is not None and frame:
            cache.put_naming(frame, (out, meta))
        return out, meta

    def _caption_fallback(self, filtered: List[Dict[str, Any]], image_np: np.ndarray) -> List[str]:
        if not self.caption_mp:
            return ["" for _ in filtered]
        try:
            from gui_rewalk.env.utils import get_parsed_content_icon
            import torch
            boxes_t = torch.tensor([e["bbox"] for e in filtered])
            caps = get_parsed_content_icon(
                boxes_t, starting_idx=0, image_source=image_np,
                caption_model_processor=self.caption_mp, prompt=None,
                batch_size=self.batch_size,
            )
            return [(c or "").strip() for c in caps]
        except Exception as e:
            logger.warning("Florence-2 caption fallback failed: %s", e)
            return ["" for _ in filtered]

    # ── VLM grounding (alternative element source) ───────────────────────
    def _ground_with_vlm(self, image, image_np, w, h, *,
                         force_refresh: bool = False) -> List["VisualElement"]:
        """One predict_mm returns ALL interactive elements with name/type/category
        + bbox (normalized [0,1000] -> px). No YOLO/OCR. Sets last_som_image (boxes
        drawn on the frame), last_window_xywh and last_is_modal. Returns the
        VisualElement list (empty list = grounding yielded nothing -> caller falls
        back to YOLO+OCR)."""
        from .visual_filter import window_ratio_to_px
        self.last_window_xywh = None
        self.last_is_modal = False
        self.last_surface_kind = ACTIVE_SURFACE_PAGE
        self.last_surface_scrollable = None
        self.last_is_system_dialog = False
        self.last_is_interruption = False
        self.last_grounding_response = None
        if self.agent is None:
            self.last_som_image = image_np
            return []
        frame = getattr(self, "_cur_frame_bytes", None)
        cache = getattr(self, "cache", None)
        cache_hit = False
        resp = None
        if cache is not None and frame and not force_refresh:
            cache_hit, resp = cache.lookup_grounding(frame)
        if not cache_hit:
            try:
                from .visual_cache import predict_mm_role
                resp, *_ = predict_mm_role(
                    self.agent, "grounding", VLM_GROUNDING_PROMPT,
                    [image_np], getattr(self, "vlm_ledger", None),
                    max_attempts=1,
                    timeout_seconds=_GROUNDING_REQUEST_TIMEOUT,
                    use_response_cache=not force_refresh)
            except Exception as e:
                logger.warning("VLM grounding call failed: %s", e)
                self.last_som_image = image_np
                return []
        self.last_grounding_response = resp
        parsed, meta = _parse_vlm_json(resp)

        # window / modal also come back in [0,1000] -> ratio for *_ratio_to_px
        def _ratio(b):
            if isinstance(b, (list, tuple)) and len(b) == 4:
                try:
                    return [max(0.0, min(1.0, float(v) / 1000.0)) for v in b]
                except (TypeError, ValueError):
                    return None
            return None
        surface_kind = _normalize_surface_kind(
            meta.get("surface_kind"), is_modal=bool(meta.get("is_modal")))
        surface_ratio = _ratio(meta.get("active_surface"))
        if surface_ratio is None and surface_kind in ACTIVE_OVERLAY_SURFACE_KINDS:
            surface_ratio = _ratio(meta.get("modal"))
        if surface_kind in ACTIVE_OVERLAY_SURFACE_KINDS:
            self.last_window_xywh = window_ratio_to_px(surface_ratio, (w, h))
            self.last_is_modal = True
            self.last_surface_kind = surface_kind
        else:
            self.last_window_xywh = window_ratio_to_px(_ratio(meta.get("window")), (w, h))
            self.last_is_modal = False
            self.last_surface_kind = ACTIVE_SURFACE_PAGE
        self.last_surface_scrollable = _optional_bool(
            meta.get("surface_scrollable"))
        self.last_is_system_dialog = bool(meta.get("is_system_dialog"))
        # [2026-07-08] grounding 路径此前漏设 is_interruption(只 reset 不赋值)→
        # dismisser 恢复门永远看到 False、从不触发关闭浮层。
        # 补上后, VLM 判定的更新/cookie/欢迎页等打断浮层才会被真正点掉再重看。
        self.last_is_interruption = bool(meta.get("is_interruption"))
        self.last_page_name = (str(meta.get("page") or "").strip() or None)

        elements: List[VisualElement] = []
        for item in (parsed or []):
            if not isinstance(item, dict):
                continue
            bbox = item.get("bbox") or item.get("bbox_2d") or item.get("box")
            if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
                continue
            try:
                x0, y0, x1, y1 = (float(v) for v in bbox)
            except (TypeError, ValueError):
                continue
            if x1 < x0:
                x0, x1 = x1, x0
            if y1 < y0:
                y0, y1 = y1, y0
            px = max(0, min(w - 1, int(round(x0 / 1000.0 * w))))
            py = max(0, min(h - 1, int(round(y0 / 1000.0 * h))))
            pw = max(1, int(round((x1 - x0) / 1000.0 * w)))
            ph_ = max(1, int(round((y1 - y0) / 1000.0 * h)))
            name = str(item.get("name", "")).strip()
            enabled, requires_permission, blocked_reason = _availability_from_item(item)
            (stateful, state_key, state_value, effect_scope,
             reversible, risk) = _state_semantics_from_item(item)
            elements.append(VisualElement(
                id=len(elements), name=name,
                bbox_xywh=[px, py, pw, ph_], center=[px + pw // 2, py + ph_ // 2],
                el_type=str(item.get("type", "icon")),
                interactive=bool(item.get("interactive", True)),
                enabled=enabled,
                requires_permission=requires_permission,
                blocked_reason=blocked_reason,
                stateful=stateful,
                state_key=state_key,
                state_value=state_value,
                effect_scope=effect_scope,
                reversible=reversible,
                risk=risk,
                category=str(item.get("category", "")).strip().lower(),
                score=1.0, source="vlm_ground",
                group=str(item.get("group", "")).strip().lower(),
                back=bool(item.get("back", False)),
                selected=bool(item.get("selected", False)),
                identity_anchor=(item.get("identity_anchor")
                                 if isinstance(item.get("identity_anchor"), bool)
                                 else None),
                action_label=_action_label_from_item(
                    item, name=name, interactive=bool(item.get("interactive", True)),
                    category=str(item.get("category") or "display").strip().lower()),
            ))
        self.last_som_image = (_draw_som(image, [e.bbox_xywh for e in elements])
                               if elements else image_np)
        # Cache only a usable response.  Empty/unparseable results keep the retry
        # path alive; a reviewer-triggered force refresh overwrites an older bad
        # but parseable grounding with the newer response.
        if (elements and cache is not None and frame
                and not cache_hit and not force_refresh):
            cache.put_grounding(frame, resp)
        return elements

    def _yolo_detect_name(self, image, image_np, w, h) -> Optional[List["VisualElement"]]:
        """Original pipeline: YOLO(+OCR) detect -> SoM -> VLM naming -> elements.
        Returns None when detection finds nothing. Sets last_som_image/window."""
        from .visual_filter import window_ratio_to_px
        filtered = self.detect(image)
        if not filtered:
            self.last_som_image = image_np
            return None

        boxes_xywh, centers = [], []
        for e in filtered:
            xywh, center = _xyxy_ratio_to_xywh_px(e["bbox"], w, h)
            boxes_xywh.append(xywh)
            centers.append(center)

        som_image = _draw_som(image, boxes_xywh)
        self.last_som_image = som_image
        vlm_names, vlm_meta = self._name_with_vlm(som_image, len(filtered))
        # Active surface = modal bbox when a modal is present (aligns with the
        # a11y traversal's _pick_active_surface), else the main window.
        if vlm_meta.get("is_modal") and vlm_meta.get("modal"):
            crop_box = window_ratio_to_px(vlm_meta.get("modal"), (w, h))
            self.last_is_modal = True
            self.last_surface_kind = _normalize_surface_kind(
                vlm_meta.get("surface_kind"), is_modal=True)
        else:
            crop_box = window_ratio_to_px(vlm_meta.get("window"), (w, h))
            self.last_is_modal = False
            self.last_surface_kind = ACTIVE_SURFACE_PAGE
        self.last_surface_scrollable = _optional_bool(
            vlm_meta.get("surface_scrollable"))
        self.last_window_xywh = crop_box
        captions = None
        if len(vlm_names) < len(filtered):
            captions = self._caption_fallback(filtered, image_np)

        elements: List[VisualElement] = []
        for i, e in enumerate(filtered):
            meta = vlm_names.get(i)
            enabled, requires_permission, blocked_reason = _availability_from_item(meta)
            (stateful, state_key, state_value, effect_scope,
             reversible, risk) = _state_semantics_from_item(meta)
            ocr_content = (e.get("content") or "").strip()
            is_text_box = e.get("type") == "text"
            category = ""
            if meta and (meta.get("name") or "").strip():
                name = str(meta["name"]).strip()
                el_type = str(meta.get("type", "icon"))
                interactive = bool(meta.get("interactive", True))
                category = str(meta.get("category", "")).strip().lower()
                source = "vlm"
                # (root cause #2) The VLM SoM-id->name table DRIFTS on dense
                # screenshots: it names a real row, but binds that name to the
                # WRONG box (a launcher app name on a Settings row). OCR text is
                # geometry-bound to THIS exact box and cannot drift across the map.
                # So when this box has its own OCR text AND the VLM name shares no
                # token with it, the VLM name is mis-bound — prefer the OCR label,
                # which actually sits at this box's location. Only overrides on a
                # genuine disagreement (no shared token); a matching name is kept.
                if ocr_content and not _shares_token(name, ocr_content):
                    logger.debug("name re-bind (drift): VLM '%s' != OCR '%s' at "
                                 "box %d -> using OCR", name, ocr_content, i)
                    name = ocr_content
                    source = "ocr_rebind"
            elif ocr_content:
                # OCR recovered the label (e.g. left-nav menu item). Treat as a
                # clickable nav entry — this is the whole point of adding OCR.
                name = ocr_content
                el_type = "text" if is_text_box else "icon"
                interactive = True
                category = "navigation"
                source = "ocr"
            else:
                name = (captions[i] if captions else "") or ""
                el_type = "icon"
                interactive = True
                source = "caption" if name else "yolo"
            elements.append(VisualElement(
                id=i, name=name, bbox_xywh=boxes_xywh[i], center=centers[i],
                el_type=el_type, interactive=interactive, category=category,
                enabled=enabled, requires_permission=requires_permission,
                blocked_reason=blocked_reason,
                stateful=stateful, state_key=state_key,
                state_value=state_value, effect_scope=effect_scope,
                reversible=reversible, risk=risk,
                score=round(float(e.get("_score", 0.0)), 4), source=source,
                selected=bool(meta.get("selected", False)) if meta else False,
                identity_anchor=(meta.get("identity_anchor")
                                 if meta and isinstance(
                                     meta.get("identity_anchor"), bool)
                                 else None),
                action_label=_action_label_from_item(
                    meta, name=name, interactive=interactive, category=category),
            ))
        return elements

    # ── public API ───────────────────────────────────────────────────────
    def detect_and_name(self, screenshot_bytes: bytes,
                        apply_filter: bool = True,
                        system_band: str = "both",
                        force_refresh: bool = False) -> List[VisualElement]:
        """Full pipeline: returns named VisualElements with pixel coords.

        When ``apply_filter`` is True (engine default), the result is the
        screenshot-only analogue of app_filter.py: elements outside the active
        surface (window, or modal bbox when a modal is present) are dropped, and
        the four-category model (graph_prompts.py) is applied —
        ``navigation`` is kept (clickable), while ``dangerous`` / ``shallow`` /
        ``display`` are dropped from the click set. ``shallow`` elements are
        also recorded in ``self.last_node_local_functions`` (discover, don't
        execute). Set ``apply_filter=False`` to keep everything (annotation).
        """
        from .visual_filter import (
            center_in_window, in_system_ui_band, should_record_node_local,
            candidate_priority, is_enqueueable, effective_category,
            window_ratio_to_px, keyboard_key_indices,
            NAVIGATION_CATEGORY, candidate_access_outcome)

        # Remember the source frame so _name_with_vlm can pHash-key its cache.
        self._cur_frame_bytes = screenshot_bytes
        # A failed perception must not leak semantic metadata from the previous
        # frame into identity, review, or graph output.
        self.last_page_name = None
        self.last_all_elements = []
        self.last_node_local_functions = []
        self.last_grounding_response = None

        # [2026-07-07 用户 删除] pHash state-reuse 已删(暗坑): 它在 grounding 前用
        # pHash 判帧、绕过 region-set,框架相似的子页被误判成已见帧→复用旧元素→content
        # 永不更新→全部假合并。每帧都真感知,region-set 身份才可靠。

        image = _to_pil(screenshot_bytes)
        w, h = image.size
        image_np = np.asarray(image)

        # Element production — two interchangeable sources, then the shared filter:
        #   (A) VLM grounding (use_vlm_grounding=True): ONE predict_mm returns every
        #       interactive element with name/type/category + bbox directly
        #       ([0,1000]-normalized -> px), no YOLO/OCR. Recovers prominent rows
        #       YOLO never boxed (the Settings home "Network & internet") and emits
        #       none of the OCR garbage ("uuunU"/"VIUIAUIUI") YOLO+OCR produced.
        #   (B) YOLO(+OCR) -> SoM -> VLM naming (the original pipeline; fallback).
        # Each helper sets last_som_image/last_window_xywh/last_is_modal and returns
        # a VisualElement list (or None = nothing detected); the tail is shared.
        elements: Optional[List[VisualElement]] = None
        if getattr(self, "use_vlm_grounding", False):
            # Grounding gets one longer request (large structured output) instead
            # of short nested retries. Failure is handled fail-closed by _register.
            for _attempt in range(1, _GROUNDING_MAX_ATTEMPTS + 1):
                try:
                    elements = self._ground_with_vlm(
                        image, image_np, w, h,
                        force_refresh=force_refresh) or None
                except Exception as e:
                    logger.warning("VLM grounding call errored (attempt %d/%d): %s",
                                   _attempt, _GROUNDING_MAX_ATTEMPTS, e)
                    elements = None
                if elements is not None:
                    break
                if _attempt < _GROUNDING_MAX_ATTEMPTS:
                    logger.info("VLM grounding empty/failed; retrying (%d/%d)",
                                _attempt, _GROUNDING_MAX_ATTEMPTS)
                else:
                    logger.info("VLM grounding still empty after %d attempts; "
                                "returning [] (no YOLO/OCR fallback in grounding "
                                "mode — distrusted)", _GROUNDING_MAX_ATTEMPTS)
        else:
            elements = self._yolo_detect_name(image, image_np, w, h)
        if elements is None:
            return []  # nothing detected (blank frame, or all grounding retries empty)

        # normalise category to the resolved four-category value on every elem
        for el in elements:
            el.category = effective_category(el.category, el.name)
        # Modal active-surface isolation must use the WHOLE element box, not only
        # its center.  A background/sidebar box can span underneath a dialog and
        # still place its center inside the modal; accepting it pollutes both the
        # click frontier and the function-signature identity.  Retain boxes with
        # small grounding jitter (>=80% area inside), reject the rest.  If a
        # frame is labelled modal but its surface geometry is unusable, fail
        # closed to an empty active set.
        _modal_rejected = 0
        if self.last_is_modal:
            active_elements = [
                el for el in elements
                if _bbox_sufficiently_inside_surface(
                    el.bbox_xywh, self.last_window_xywh)
            ]
            _modal_rejected = len(elements) - len(active_elements)
        else:
            active_elements = list(elements)
        active_surface_kind = _normalize_surface_kind(
            getattr(self, "last_surface_kind", ""),
            is_modal=bool(self.last_is_modal))
        for element in active_elements:
            element.surface_kind = active_surface_kind
            element.surface_bbox_xywh = (
                list(self.last_window_xywh)
                if isinstance(self.last_window_xywh, (list, tuple))
                and len(self.last_window_xywh) == 4
                else None)
            element.surface_scrollable = getattr(
                self, "last_surface_scrollable", None)
        active_elements = _dedupe_stateful_aliases(active_elements)
        # [2026-07-07 用户] 存过滤前的【全量元素】(含 display 分区标题等非交互项)。页面
        # 身份(region-set)要看所有元素 —— display 标题(Wired/VPN/Network Proxy…)最稳定、
        # 最能锚定页面身份; 探索才只用 navigation 候选(下面过滤后的 kept)。模态帧的
        # “全量”严格指 active modal surface 内的全量，不包括失活背景。
        self.last_all_elements = list(active_elements)

        if not apply_filter:
            return elements

        # From this point on every modal candidate is already bbox-contained in
        # the active surface.  Non-modal behavior remains unchanged.
        elements = active_elements

        # (priority-1) Stop HARD-dropping display/shallow rows here — that was
        # the dominant silent, unrecoverable coverage loss (most real Settings
        # navigation rows get mis-tagged ``display``/``shallow`` by the one-shot
        # per-element category. Now we keep non-dangerous in-window inventory;
        # the deterministic frontier later executes only navigation. ``shallow``
        # rows are ALSO recorded as
        # node-local functions (discover, don't execute) as before. Only
        # ``dangerous`` (truly-irreversible-on-tap) and out-of-window stay out.
        # (D17 visual port) On-screen keyboard / keypad suppression. A search box
        # is discover-only: clicking it to register the search page is fine, but
        # the soft keyboard it pops must NEVER be explorable — otherwise the
        # engine clicks letter keys ('b','y','d'...), TYPES a query, and spawns a
        # phantom search-results subtree. Detect a real key CLUSTER (>= N keys)
        # and drop those keys from the enqueueable set (the same generic intent as
        # the a11y _filter_obvious_value_entry_controls). Keyboard-free pages are
        # untouched (empty set). Indices are over the full ``elements`` list.
        kbd_idx = keyboard_key_indices([el.name for el in elements])

        # (form-leaf port) Data-entry FORM suppression. A contact/event/settings
        # editor is ONE explorable function (the form exists = a capability); its
        # input fields + value-picker dropdowns (phone-type Home/Work/Mobile, date
        # Birthday, relationship Assistant) are data-entry mechanics, NOT separate
        # function pages, so they must NOT each be enqueued (else BFS over-explores
        # the form field-by-field — contacts: the Create-contact form ate 5 of 9
        # nodes via its pickers, so "Fix & manage -> Settings" was never reached).
        # USER DIRECTIVE: 只发现功能页面，不实现功能. Mirrors the a11y
        # _filter_obvious_value_entry_controls. Gate requires >=1 real text input,
        # so a nav drawer / options menu / dialog (no inputs) is untouched —
        # dff86e15 (genuine NEW-navigation overlays still split) is preserved. The
        # form's genuinely-navigational chrome (Save / X-close / Back / a "More
        # options" overflow) is an icon/button, never an input/picker -> survives.
        # [2026-07-07 用户 删除] FORM_FIELD_SUPPRESS 已退休(恒 False)——form_idx 恒空。
        form_idx: set = set()

        kept: List[VisualElement] = []
        node_local: List[Dict[str, Any]] = []
        n_win = n_danger = n_shallow = n_lowprio = n_kbd = n_form = n_sysui = 0
        # [SCROLL-MAP CHANGE 18/B1] which bands apply to THIS image: a middle
        # chunk of a tall stitched composite has real rows in both bands
        # ("none"); the first chunk only has the status bar ("top"), the last
        # only the nav bar ("bottom"). Default "both" = original behaviour.
        _band_top = system_band in ("both", "top")
        _band_bottom = system_band in ("both", "bottom")
        for idx, el in enumerate(elements):
            _safe_stateful = el.is_safe_stateful_surface()
            if in_system_ui_band(el.center, (w, h),
                                 top=_band_top, bottom=_band_bottom):
                # top status bar (clock/battery/signal/Wi-Fi/DND) or bottom nav
                # bar — system UI, never an app function. Drop it (do not enqueue,
                # do not record): clicking it yields a self-loop and its dynamic
                # clock text would pollute state identity.
                n_sysui += 1
                continue
            # Focus priority: when a MODAL dialog is open, crop to it (last_window_xywh
            # already = the modal bbox) so the BACKGROUND sidebar/content — which the
            # dialog covers and deactivates — is dropped, not treated as clickable.
            # Only WITHOUT a modal does the real-window override (Dock/top-bar crop)
            # apply. The A override must NOT outrank the modal, else a dialog's
            # background sidebar re-enters the click set and the router keeps aiming
            # at a covered sidebar item → loop (2026-07-03 Backups dialog).
            _win = (self.last_window_xywh if self.last_is_modal
                    else (self.window_px_override or self.last_window_xywh))
            if not center_in_window(el.center, _win, (w, h)):
                n_win += 1
                continue
            if idx in kbd_idx:
                # soft-keyboard / keypad key — never a function entry; do not
                # enqueue (so it is never clicked / typed). Not recorded as a
                # node-local function either (it carries no app capability).
                n_kbd += 1
                continue
            if idx in form_idx:
                # data-entry-form field / value-picker — the form is ONE leaf
                # function; do NOT enqueue this widget as a separate exploration
                # target. Record it as a node-local function so the form's fields
                # are still DISCOVERED (capability inventory), never EXECUTED.
                node_local.append(_function_record(el, "form-field"))
                n_form += 1
                continue
            if should_record_node_local(el.category, el.name) and not _safe_stateful:
                # shallow: record as a node-local function (discover, don't run)
                node_local.append(_function_record(el, "shallow"))
                n_shallow += 1
            # Retain explicitly unavailable controls in the node artifact so the
            # engine can persist an auditable ``disabled``/``permission_blocked``
            # terminal outcome.  They are not executable navigation candidates.
            _access_outcome = candidate_access_outcome(
                enabled=el.enabled,
                requires_permission=el.requires_permission,
                blocked_reason=el.blocked_reason,
                category=el.category,
                el_type=el.el_type,
            )
            if not is_enqueueable(
                    el.category, el.name,
                    enabled=el.enabled,
                    requires_permission=el.requires_permission,
                    blocked_reason=el.blocked_reason,
                    el_type=el.el_type) and not _access_outcome and not _safe_stateful:
                # Safety and discovery are orthogonal.  Do not execute a final
                # destructive/commit control, but retain it as an observed
                # (unverified) capability for the page/variant catalog.
                if el.category == "dangerous":
                    node_local.append(_function_record(el, "dangerous"))
                n_danger += 1
                continue  # dangerous — never enqueue
            el.priority = (-1 if _safe_stateful else
                           (98 if _access_outcome
                            else candidate_priority(el.category, el.name)))
            if el.category != NAVIGATION_CATEGORY and not _safe_stateful:
                n_lowprio += 1
            kept.append(el)
        self.last_node_local_functions = node_local
        if (_modal_rejected or n_win or n_danger or n_shallow or n_lowprio
                or n_kbd or n_form or n_sysui):
            logger.info("visual_filter: dropped %d modal-background + %d system-UI + %d outside + %d "
                        "dangerous + %d keyboard-keys + %d form-fields; kept %d/%d "
                        "(%d low-priority display/shallow retained as inventory, %d "
                        "shallow also recorded node-local, %d form-fields recorded "
                        "node-local, modal=%s)",
                        _modal_rejected, n_sysui, n_win, n_danger, n_kbd, n_form,
                        len(kept), len(elements), n_lowprio, n_shallow, n_form,
                        self.last_is_modal)
        # re-index so SoM ids stay contiguous for the kept set
        for new_id, el in enumerate(kept):
            el.id = new_id
        return kept


def _drop_inconsistent_group_labels(
    elements: List["VisualElement"],
) -> List["VisualElement"]:
    """Reject only group claims contradicted by the same observation.

    ``group`` is allowed to collapse repeated data instances after one verified
    result. Members that disagree about their immediate result cannot satisfy
    that contract. Current selection may differ between equivalent instances.
    This is a consistency check over model outputs, not a widget- or
    application-specific grouping rule.
    """
    grouped: Dict[Tuple[str, str], List["VisualElement"]] = {}
    for element in elements:
        group = " ".join(str(element.group or "").casefold().split())
        if group:
            grouped.setdefault((str(element.region_id or ""), group), []).append(
                element)
    for members in grouped.values():
        if len(members) < 2:
            continue
        categories = {
            " ".join(str(member.category or "").casefold().split())
            for member in members
        }
        if len(categories) > 1:
            for member in members:
                member.group = ""
    return elements
