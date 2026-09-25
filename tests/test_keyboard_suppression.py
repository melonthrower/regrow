"""On-screen keyboard / search-box discover-only test (no emulator, no a11y).

Validates the D17 visual port: a search box may be CLICKED to register its
search page (allowed), but the soft keyboard it pops must NEVER be enqueued as
explorable elements — otherwise the engine clicks letter keys ('b','y','d'...),
TYPES a query into the search field, and spawns a PHANTOM search-results subtree
(observed on android_settings: "by by by…" → fake Do-Not-Disturb / Wi-Fi / SIMs
rows). This is the visual analogue of the a11y traversal's
``_filter_obvious_value_entry_controls`` (calculators / PIN pads / on-screen
keyboards).

The test reconstructs the EXACT element set perception produced for the corrupted
search-results node (the 'b'/'y'/'d' letter keys + IME chrome + a few real rows)
and asserts, purely offline (string heuristics only, no model, no device):

  (a) every soft-keyboard / keypad KEY (letters, ?123, space, delete, emoji,
      mic, the CJK-named IME keys) is identified and would be SUPPRESSED,
  (b) the real navigation rows (Wi-Fi, Notifications, Display, Search settings)
      are NOT suppressed — so clicking the search box to register its page, and
      exploring real rows, still works,
  (c) the cluster gate holds: a normal page with only a couple of short labels
      (a '+' add button, a single-letter avatar) suppresses NOTHING.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui_rewalk.src.core.visual_traversal.visual_filter import (
    is_keyboard_key_label, keyboard_key_indices, _KEYBOARD_MIN_KEYS)


def main():
    # ── (a)+(b) the real corrupted search-results node element names ─────────
    # Taken verbatim from result_lc3_settings node 94b9123d (the state whose
    # keyboard keys got clicked → "by by by…" typed). Letter/IME keys must be
    # suppressed; the real rows + the search box must survive.
    search_node_names = [
        "Search settings",          # the SEARCH BOX itself — must SURVIVE (nav click ok)
        "Wi-Fi",                    # real result row — must survive
        "Notifications",            # real row — must survive
        "Display",                  # real row — must survive
        "Do Not Disturb",           # real row — must survive
        # ── soft keyboard: letter keys (must all be suppressed) ──
        "q", "w", "e", "r", "t", "y", "u", "i", "o", "p",
        "a", "s", "d", "f", "g", "h", "j", "k", "l",
        "z", "x", "c", "v", "b", "n", "m",
        # ── IME chrome keys (must be suppressed) ──
        "Shift", "?123", "空格", "删除", "表情", "语音输入",
        "返回", "贴纸/表情", "更多选项", "GIF", "清除按钮", "语言切换键",
        ".", ",",
    ]
    real_rows = {"Search settings", "Wi-Fi", "Notifications", "Display",
                 "Do Not Disturb"}

    idx = keyboard_key_indices(search_node_names)
    suppressed = {search_node_names[i] for i in idx}
    survivors = {nm for i, nm in enumerate(search_node_names) if i not in idx}

    # (a) every letter key and IME control key is suppressed
    for key in ["b", "y", "d", "q", "m", "Shift", "?123", "空格", "删除",
                "表情", "语音输入", "GIF", ".", ","]:
        assert key in suppressed, f"(a) keyboard key {key!r} was NOT suppressed"
    n_keys = sum(1 for nm in search_node_names if nm not in real_rows)
    print(f"(a) suppressed {len(suppressed)}/{n_keys} keyboard/IME keys "
          f"(cluster of {len(idx)} >= {_KEYBOARD_MIN_KEYS} fired)")

    # (b) the real navigation rows + the search box are NOT suppressed
    for row in real_rows:
        assert row in survivors, f"(b) real row {row!r} was wrongly suppressed"
    assert "Search settings" in survivors, \
        "(b) the SEARCH BOX must stay clickable (register its page)"
    print(f"(b) real rows survive (incl. the search box): "
          f"{sorted(survivors & real_rows)}")

    # ── (c) cluster gate: a normal page with a FEW short labels suppresses none
    normal_page = [
        "Wi-Fi", "Bluetooth", "Display", "Sound",
        "+",            # an 'add' FAB — short, but a real control
        "A",            # a single-letter contact avatar — not a keyboard
        "Storage", "Battery",
    ]
    n_short = sum(1 for nm in normal_page if is_keyboard_key_label(nm))
    idx_normal = keyboard_key_indices(normal_page)
    assert idx_normal == set(), (
        "(c) a normal page (< cluster threshold) must suppress NOTHING; "
        f"got {[normal_page[i] for i in idx_normal]} ({n_short} short labels)")
    print(f"(c) normal page: {n_short} short label(s) < {_KEYBOARD_MIN_KEYS} "
          f"threshold -> 0 suppressed (no false amputation)")

    # Android may expose only the accessibility-labelled IME dismiss affordance
    # even when no six-key cluster is grounded.  It is system chrome, never an
    # application capability, so it is retired on its own.
    lone_ime = ["Notification history", "Hide keyboard", "Most recent"]
    idx_lone_ime = keyboard_key_indices(lone_ime)
    assert idx_lone_ime == {1}, idx_lone_ime
    print("(c2) lone Android 'Hide keyboard' system affordance is suppressed")

    # ── extra: a calculator/keypad cluster (general, not just IME) ───────────
    keypad = ["7", "8", "9", "÷", "4", "5", "6", "×", "1", "2", "3", "-",
              "0", ".", "=", "+", "History", "Mode"]
    idx_kp = keyboard_key_indices(keypad)
    sup_kp = {keypad[i] for i in idx_kp}
    assert "History" not in sup_kp and "Mode" not in sup_kp, \
        "keypad: real nav controls (History/Mode) must survive"
    for d in ["7", "0", "=", "+", "÷", "×"]:
        assert d in sup_kp, f"keypad: key {d!r} must be suppressed"
    print(f"(d) calculator keypad: suppressed {len(sup_kp)} keys, kept "
          f"History/Mode -> general value-entry handling works")

    print("ALL PASS — soft-keyboard / keypad keys are suppressed (no typing, no "
          "phantom search subtree); the search box and real rows stay clickable.")


if __name__ == "__main__":
    main()
