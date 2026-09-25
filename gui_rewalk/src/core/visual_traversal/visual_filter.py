"""Visual filtering — the screenshot-only analogue of app_filter.py.

The a11y traversal restricts elements to the target app window and drops
non-interactive display labels using a11y signals (st:focusable, st:sensitive,
window rect, app subtree) that a screenshot-only pipeline does not have. We
rebuild two of those filters from VLM output instead:

  1. window crop  — drop elements whose center falls outside the active app
                    window bbox (removes Dock / top status bar / desktop).
  2. category drop — drop elements the VLM tagged as display-only "static"
                    text (the "clicked it, nothing happened" labels).

Both signals come from the SAME VLM naming call (no extra round-trip): the
naming prompt is extended to also return the window bbox and a per-element
category. See visual_perception._VLM_NAMING_PROMPT.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Four-category model aligned with the a11y traversal (graph_prompts.py):
#   navigation = may reveal a new UI surface  -> CLICK (the only clickable class)
#   shallow    = predictable in-page action   -> skip, but record as node-local fn
#   dangerous  = terminates/commits/destroys  -> skip, never click
#   display    = read-only text               -> skip
NAVIGATION_CATEGORY = "navigation"
SHALLOW_CATEGORY = "shallow"
DANGEROUS_CATEGORY = "dangerous"
DISPLAY_CATEGORY = "display"
CLICKABLE_CATEGORIES = {NAVIGATION_CATEGORY}
# categories that are recorded but not clicked
SKIP_CATEGORIES = {SHALLOW_CATEGORY, DANGEROUS_CATEGORY, DISPLAY_CATEGORY}

# [2026-07-05] The _DANGER_NAMES keyword net was REMOVED — trust the VLM (用户决定).
# A substring net over element names mis-fired ("Restart tour" contains "restart" →
# forced dangerous → a harmless page never explored) and broke on other languages
# (Redémarrer / 再起動 / Neustart). Danger is now judged SOLELY by the VLM:
#   * perception emits category=dangerous (looks at the whole screenshot + context,
#     and distinguishes a power-menu "Restart" from an onboarding "Restart tour"),
#   * the shared perception context contract keeps final irreversible confirms in
#     ``dangerous``; deterministic Engine scheduling only admits navigation.
# Residual risk (accepted): a DIRECT session-killer (Shut Down / Log Out / Factory
# Reset that acts on the tap, no sub-page) now relies only on category=dangerous.

# ── On-screen keyboard / keypad keys (D17 visual port) ─────────────────────
# A search box, when clicked, is registered as a state (discover-only, allowed)
# but it pops a SOFT KEYBOARD. Perception (YOLO+OCR) then boxes every key
# ('q'..'p','a'..'l','z'..'m', ?123, space, emoji, mic, delete, ...) as a
# "clickable" element. With the keys in the candidate pool the deterministic
# its first-candidate fallback) clicks them — typing 'b','y','d',... into the
# field — which spawns a PHANTOM search-results subtree (settings: "by by by…" →
# fake Do-Not-Disturb/Wi-Fi/SIMs rows). The a11y traversal solved the same class
# generically with ``_filter_obvious_value_entry_controls`` (drop dense clusters
# of short single-char/value-entry controls — calculators, PIN pads, ON-SCREEN
# KEYBOARDS). We mirror that intent here: when a frame contains such a cluster,
# its key elements are dropped from the ENQUEUEABLE click set, so a soft keyboard
# is never explorable and the engine can never type a query. Clicking the search
# BOX itself stays a normal navigation click (registers the search page) — only
# the keyboard KEYS are suppressed.
#
# Single-character / value-entry key glyphs (letters a-z, digits, operators,
# punctuation a key carries). Lower-cased; matched whole.
_KEY_GLYPHS = frozenset({
    # digits + operators + common keypad glyphs (calculator / PIN pad / dialer)
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    ".", ",", "+", "-", "−", "–", "—", "*", "×", "/", "÷",
    "=", "%", "±", "+/-", "#", "⌫", "<", ">",
} | {chr(c) for c in range(ord("a"), ord("z") + 1)})  # a..z letter keys

# Multi-glyph but unmistakable on-screen-keyboard CHROME (IME control keys). These
# carry no app function: they only edit text or switch the keyboard. Lower-cased;
# matched against the compacted (whitespace-stripped) label. EN + the Qwen-named
# CJK forms observed in the wild (删除/空格/表情/语音输入/返回/清除按钮/语言切换键…).
_KEYBOARD_CHROME = frozenset({
    "shift", "delete", "backspace", "enter", "return", "space", "spacebar",
    "?123", "123", "abc", "=\\<", "gif", "emoji", "mic", "ctrl", "alt", "tab",
    "caps", "capslock", "del",
    "空格", "删除", "回车", "换行", "符号", "表情", "贴纸", "贴纸/表情", "语音输入",
    "清除按钮", "清除", "语言切换键", "键盘", "设置/键盘设置", "更多选项", "数字键盘",
})

# How many key-like elements must co-occur before we treat the cluster as a
# keyboard/keypad (mirrors the a11y ``keypad_like < 6`` gate — a handful of stray
# short labels on a normal page must NOT trip this; only a real key grid does).
_KEYBOARD_MIN_KEYS = 6

# These accessibility-labelled IME affordances can be the *only* keyboard box
# that grounding returns (Android commonly exposes the bottom-right dismiss
# button while individual letter keys are below the detector threshold).  They
# are unambiguously system input chrome and therefore do not need the usual
# six-key cluster guard.
_ALWAYS_IME_CHROME = frozenset({
    "hidekeyboard", "showkeyboard", "dismisskeyboard", "closekeyboard",
    "keyboardhide", "keyboarddismiss",
})


def _compact(label) -> str:
    return "".join(str(label or "").strip().lower().split())


def is_keyboard_key_label(name) -> bool:
    """True iff ``name`` looks like a single on-screen-keyboard / keypad key or
    an IME control key (Shift / ?123 / space / delete / emoji / mic / …).

    General — keys off the glyph/chrome shape only, nothing app-specific. A real
    navigation row ('Wi-Fi', 'Notifications', 'Display') never matches; a single
    letter/digit key or a keyboard control key does.
    """
    compact = _compact(name)
    if not compact:
        return False
    if compact in _KEYBOARD_CHROME:
        return True
    # a single key glyph: 'b', 'y', '7', '+', '×', '⌫' …
    if compact in _KEY_GLYPHS:
        return True
    # 'shift'/'⇧' arrow variants and lone punctuation a key shows
    if len(compact) == 1 and not compact.isalnum():
        return True
    return False


def keyboard_key_indices(names) -> set:
    """Given the ordered element names of ONE frame, return the indices that are
    on-screen-keyboard / keypad keys — but ONLY when they form a real cluster
    (``>= _KEYBOARD_MIN_KEYS`` of them). Below the threshold the page just has a
    few short labels (e.g. a '+' add button, a single-letter avatar) and nothing
    is suppressed, so legitimate controls are never amputated.

    Returns an empty set when no keyboard is present — the common case, zero cost
    to every keyboard-free page.
    """
    always_idx = {
        i for i, name in enumerate(names)
        if _compact(name) in _ALWAYS_IME_CHROME
    }
    key_idx = {i for i, nm in enumerate(names) if is_keyboard_key_label(nm)}
    if len(key_idx) < _KEYBOARD_MIN_KEYS:
        return always_idx
    return key_idx | always_idx


# ── Data-entry FORM suppression (visual port of the a11y form-vs-page intent) ─
# USER DIRECTIVE: "只发现功能页面，不实现功能" — a data-entry FORM (contact editor,
# calendar event editor, a settings text-input form) is ONE explorable function:
# the form EXISTS = a capability. Its individual input fields (First/Last name,
# Company, Email, Phone …), its value-picker / label dropdowns (the phone-type
# Home/Work/Mobile picker, the date Birthday/Anniversary picker, the
# relationship Assistant/Manager picker) and "More fields"/"Add photo" widgets
# are DATA-ENTRY MECHANICS, not separate function pages — clicking each one fills
# in / picks a value, it does not map a new feature surface. The a11y traversal
# collapses exactly this with ``_filter_obvious_value_entry_controls`` (drop a
# dense cluster of short value-entry controls so a form is one node, not
# field-by-field). This is the screenshot-only analogue.
#
# WHY THIS DOES NOT REGRESS dff86e15 (genuine drawers / menus / dialogs that
# expose NEW NAVIGATION still split): the gate REQUIRES at least one real TEXT
# INPUT field (``el_type=="input"``) to be present. A nav drawer, an options /
# overflow menu, a confirm dialog, a bottom sheet — the surfaces dff86e15
# intentionally registers — contain ZERO text-input fields (you tap a row, you
# do not type), so this gate never fires on them. The distinction is precisely
# data-entry-widget (input field + its value picker) vs navigation (a row / menu
# item that opens a different page). Only a real form trips it.
#
# A "value-picker" is a CLOSED dropdown whose visible text is the CURRENT value
# of an adjacent input field (Mobile / Home / Work / Birthday / Assistant …),
# emitted by perception as ``el_type in {menu, dropdown}``. We only treat such a
# dropdown as a value-picker (and suppress it) WHEN a form context is confirmed
# by the presence of input fields — so a STANDALONE navigation dropdown on a
# non-form page (which would have no sibling text inputs) is left clickable and
# still splits per dff86e15.
_FORM_FIELD_INPUT_TYPES = frozenset({"input", "textfield", "edittext", "textbox"})
_FORM_VALUE_PICKER_TYPES = frozenset({"menu", "dropdown", "spinner", "select", "combobox"})

# A value-picker label is the SHORT current value of a field, not a multi-word
# navigation phrase. Cap the token/char length so a genuine navigation menu item
# ("Manage accounts on this device", "Import from file") is never mistaken for a
# field value. Generic/blank names are handled by the caller's generic filter.
_FORM_VALUE_MAX_TOKENS = 3
_FORM_VALUE_MAX_CHARS = 22

# A page is judged a data-entry FORM when it has either:
#   * >= _FORM_MIN_INPUTS text-input fields (two stacked text boxes is already a
#     form — login, name-entry — never a navigation surface); OR
#   * >= 1 text input AND >= _FORM_MIN_FIELDS total form-field widgets
#     (the 1-input + many-value-pickers shape: the contact/event editor).
# A lone search box (1 input, 0 pickers) satisfies NEITHER, so it stays clickable
# and its search page still registers — only a genuine multi-field form trips this.
_FORM_MIN_INPUTS = 2
_FORM_MIN_FIELDS = 3


def _looks_like_field_value(name) -> bool:
    """True iff ``name`` looks like the SHORT current value of a form field
    (a closed value-picker's text), not a navigation phrase. Length-gated so a
    multi-word nav menu row never qualifies. Generic/blank handled elsewhere."""
    txt = str(name or "").strip()
    if not txt:
        return False
    if len(txt) > _FORM_VALUE_MAX_CHARS:
        return False
    # token count: Latin words by whitespace, CJK by character (no word breaks)
    latin = [t for t in txt.split() if any(ch.isalpha() for ch in t)]
    cjk = [c for c in txt if "一" <= c <= "鿿"]
    if cjk:
        return len(cjk) <= _FORM_VALUE_MAX_TOKENS
    return len(latin) <= _FORM_VALUE_MAX_TOKENS if latin else len(txt) <= _FORM_VALUE_MAX_CHARS


def form_field_indices(el_types, names) -> set:
    """Indices of the data-entry-FORM widgets to suppress from the click set —
    BUT ONLY when the page is a genuine data-entry form.

    ``el_types`` / ``names`` are the parallel per-element type / name lists of one
    state's full element set. Returns the indices of every text-input field and
    every value-picker dropdown that belongs to a confirmed form, so a form is
    explored as ONE leaf node instead of field-by-field. Genuinely-navigational
    chrome (Save, the X/Back that leaves the form, a "More options" overflow that
    opens a different menu) is ``el_type`` icon/button — never an input or a
    value-picker — so it is NEVER in the returned set and stays clickable.

    Gate (general, no per-app rules) — a form is confirmed iff at least one real
    TEXT INPUT is present (``el_type=="input"``: this is what tells a form apart
    from a nav drawer / options menu / dialog, which have NO text inputs, so
    dff86e15 is preserved) AND either:
      * there are ``>= _FORM_MIN_INPUTS`` text inputs (two stacked text boxes is
        already a form), or
      * the total form-field widget count (inputs + value-pickers) is
        ``>= _FORM_MIN_FIELDS`` (the 1-input + many-pickers editor shape).
    A lone search box satisfies neither, so it is left clickable.

    Returns an empty set on any non-form page (zero cost to the common case).
    """
    n = min(len(el_types), len(names))
    input_idx, picker_idx = set(), set()
    for i in range(n):
        et = str(el_types[i] or "").strip().lower()
        if et in _FORM_FIELD_INPUT_TYPES:
            input_idx.add(i)
        elif et in _FORM_VALUE_PICKER_TYPES and _looks_like_field_value(names[i]):
            picker_idx.add(i)
    # No text-input field => not a data-entry form (it's a nav surface). Bail so a
    # standalone navigation dropdown / drawer / menu is untouched (dff86e15).
    if not input_idx:
        return set()
    field_idx = input_idx | picker_idx
    is_form = len(input_idx) >= _FORM_MIN_INPUTS or len(field_idx) >= _FORM_MIN_FIELDS
    if not is_form:
        return set()
    return field_idx


# Window-crop margin (fraction of screen) — keep elements slightly outside the
# reported window box, since VLM bbox is approximate.
WINDOW_MARGIN = 0.02


def center_in_window(center_px: List[int], window_xywh_px: Optional[List[int]],
                     screen_wh: Tuple[int, int]) -> bool:
    """True if the element center is inside the active window (with margin).

    When no window bbox is available, returns True (no cropping).
    """
    if not window_xywh_px:
        return True
    w, h = screen_wh
    mx, my = WINDOW_MARGIN * w, WINDOW_MARGIN * h
    wx, wy, ww, wh = window_xywh_px
    cx, cy = center_px
    return (wx - mx) <= cx <= (wx + ww + mx) and (wy - my) <= cy <= (wy + wh + my)


# ── System-UI band suppression (Android status bar + gesture nav bar) ─────────
# The top status bar (clock / battery / signal / Wi-Fi / DND) and the bottom
# gesture nav bar are SYSTEM UI — not part of any app. A screenshot-only pipeline
# has no a11y "app subtree" to crop them out, and for a FULLSCREEN app (Settings,
# most apps) the VLM reports the window as the WHOLE screen, so center_in_window
# does NOT remove them. They may then reach the navigation frontier and get clicked — producing
# useless self-loop edges (the "2:13" clock, "100%" battery, "AM") that burn
# exploration budget + a VLM judge call each, and because the clock TEXT CHANGES
# every minute ("2:13"->"3:15"->"4:19") it also perturbs pHash/SSIM state
# identity (the dynamic-text state-split failure mode).
#
# This is platform GEOMETRY, not app semantics: the Android status bar is a fixed
# ~24-32dp strip at the very top and the nav bar a fixed strip at the very bottom
# on EVERY screen of EVERY app. So a thin top/bottom band is the correct,
# deterministic tool (a VLM prompt would pay a call per frame to re-derive a
# constant, and the VLM window bbox is too imprecise to catch it — which is
# exactly why the clock survives today). App content and toolbars (back-arrow,
# page title, search bar) always sit BELOW the status bar, so a conservative band
# never clips a real control — measured: status bar ends ~3.3% of height, the
# nearest real control (back arrow) sits at ~7%.
SYSTEM_UI_BAND_ENABLED = True
STATUS_BAR_FRAC = 0.04   # top 4% (~77px @1920h): status bar only, above any app toolbar
# Bottom band is deliberately TIGHTER than the top: the gesture pill is rarely
# even detected as a candidate, so this band's only real job is the literal
# nav-bar strip. Kept at 2% (~38px) so it never clips a real row that scrolled to
# the bottom edge — verified against live data: every real row dropped here also
# exists mid-screen (scroll-aggregate brings every row into the viewport centre),
# so the bottom copy is redundant; only OCR garbage on the nav strip is removed.
NAV_BAR_FRAC = 0.02      # bottom 2% (~38px): gesture pill region only


def in_system_ui_band(center_px: List[int], screen_wh: Tuple[int, int],
                      top: bool = True, bottom: bool = True) -> bool:
    """True iff the element center sits in the top status-bar band or the bottom
    nav-bar band — system UI that no app traversal should ever click.

    General to all Android apps (platform geometry, not per-app). Returns False
    when ``SYSTEM_UI_BAND_ENABLED`` is off (e.g. a future desktop port).

    [SCROLL-MAP CHANGE 18/B1] ``top``/``bottom`` let a caller check only ONE band:
    a tall stitched composite is perceived in CHUNKS, and for a middle chunk the
    top 4% / bottom 2% are REAL page rows, not the status/nav bar — the bars exist
    only at the composite's very top (first chunk) and very bottom (last chunk).
    Defaults keep the original both-bands behaviour. revert: drop the two kwargs.
    """
    if not SYSTEM_UI_BAND_ENABLED or not (top or bottom):
        return False
    _, h = screen_wh
    cy = center_px[1]
    return ((top and cy < STATUS_BAR_FRAC * h)
            or (bottom and cy > (1.0 - NAV_BAR_FRAC) * h))


def effective_category(category: Optional[str], name: Optional[str]) -> str:
    """Resolve the final category — trust the VLM's judgment.

    [2026-07-05] The name-keyword danger net (_DANGER_NAMES) was removed (trust the
    VLM): a substring net mis-fired ("Restart tour" → dangerous) and broke on other
    languages. Danger is judged by the VLM ``category=dangerous`` (+ the frontier
    prompt's "never press the final confirm" clause). Empty/unknown category
    defaults to ``navigation`` (explore rather than miss). ``name`` is kept for
    call-site signature compatibility but is no longer consulted here.
    """
    cat = (category or "").strip().lower()
    if cat in (NAVIGATION_CATEGORY, SHALLOW_CATEGORY, DANGEROUS_CATEGORY, DISPLAY_CATEGORY):
        return cat
    return NAVIGATION_CATEGORY  # unknown -> explore


# [2026-07-07 用户 删除] should_click 已删；当前由 category frontier 过滤取代。


# Priority ORDER hint (priority-1): instead of HARD-dropping display/shallow at
# perception time (the dominant silent, unrecoverable coverage loss — Settings
# home kept only 2/9, pages 2/10, 7/27, 1/30 because most real navigation rows
# get mis-tagged ``display``), every non-dangerous element is now KEPT and
# retained as inventory before the deterministic frontier applies category.
# The cheap per-element category is the execution boundary:
# likely-navigation rows first and the likely-display rows last. Lower number =
# explored first. ``dangerous`` is never enqueued (still dropped).
_CATEGORY_PRIORITY = {
    NAVIGATION_CATEGORY: 0,
    "": 1,            # unknown — treat as mid (explore, don't bury)
    SHALLOW_CATEGORY: 2,
    DISPLAY_CATEGORY: 3,
    DANGEROUS_CATEGORY: 99,
}


def candidate_priority(category: Optional[str], name: Optional[str]) -> int:
    """Lower = explore first. Cheap deterministic ORDER hint only — never a
    keep/drop decision; the engine's deterministic frontier executes navigation only.
    """
    return _CATEGORY_PRIORITY.get(effective_category(category, name), 1)


_DISABLED_REASONS = frozenset({"disabled", "not_enabled", "unavailable"})


def candidate_access_outcome(
    *,
    enabled: Optional[bool] = None,
    requires_permission: bool = False,
    blocked_reason: Optional[str] = "",
    category: Optional[str] = None,
    el_type: Optional[str] = None,
) -> Optional[str]:
    """Return the terminal access outcome, or ``None`` when exploration is safe.

    Missing fields preserve legacy behavior. Permission evidence is fail-closed
    and has no application-, control-, or page-specific exception.
    """
    reason = " ".join(str(blocked_reason or "").strip().lower().split())
    if enabled is False or reason in _DISABLED_REASONS:
        return "disabled"

    permission_evidence = bool(requires_permission or reason)
    if not permission_evidence:
        return None

    return "permission_blocked"


def is_enqueueable(
    category: Optional[str],
    name: Optional[str],
    *,
    enabled: Optional[bool] = None,
    requires_permission: bool = False,
    blocked_reason: Optional[str] = "",
    el_type: Optional[str] = None,
) -> bool:
    """True for every element perception may retain for inventory/frontier filtering.

    Priority-1 widening: this keeps navigation/shallow/display (the engine
    decides from the screenshot whether a low-priority row actually does
    anything, and PageIdentityJudge.same_page retires it post-click if the
    screen didn't change). Only ``dangerous`` (truly-irreversible-on-tap) stays
    excluded from the click pool.
    """
    if candidate_access_outcome(
            enabled=enabled,
            requires_permission=requires_permission,
            blocked_reason=blocked_reason,
            category=category,
            el_type=el_type) is not None:
        return False
    return effective_category(category, name) != DANGEROUS_CATEGORY


def should_record_node_local(category: Optional[str], name: Optional[str]) -> bool:
    """True for shallow — skipped during traversal but saved as a node-local
    function (aligns a11y's node_local_functions: discover, don't execute)."""
    return effective_category(category, name) == SHALLOW_CATEGORY


def window_ratio_to_px(window_ratio, screen_wh: Tuple[int, int]) -> Optional[List[int]]:
    """Convert a [x0,y0,x1,y1] (0-1) window box from the VLM to pixel xywh."""
    if not window_ratio or len(window_ratio) != 4:
        return None
    w, h = screen_wh
    try:
        x0, y0, x1, y1 = [float(v) for v in window_ratio]
    except (TypeError, ValueError):
        return None
    # tolerate either ratio (0-1) or already-pixel inputs
    if max(x0, y0, x1, y1) <= 1.5:
        x0, y0, x1, y1 = x0 * w, y0 * h, x1 * w, y1 * h
    px, py = int(min(x0, x1)), int(min(y0, y1))
    pw, ph = int(abs(x1 - x0)), int(abs(y1 - y0))
    if pw <= 0 or ph <= 0:
        return None
    return [px, py, pw, ph]
