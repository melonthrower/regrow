"""Data-entry-FORM = ONE leaf node test (no emulator, no a11y, no VLM).

Validates the form-leaf fix: a data-entry FORM (contact editor, calendar event
editor, settings text-input form) must be explored as a SINGLE function page —
its input fields and value-picker / label dropdowns are DATA-ENTRY MECHANICS,
not separate function pages, so they must NOT each be enqueued as exploration
targets. USER DIRECTIVE: 只发现功能页面，不实现功能.

Reproduces the confirmed android_contacts bug (result_lc5_contacts): the
Create-contact form was over-explored field-by-field — 5 of 9 nodes were form
variants (Email/First-name/Last-name/Company TEXT FIELDS, the Home/Work/Mobile
phone-TYPE DROPDOWN, the Birthday/Significant-date date pickers, the Label
dropdown, Add-photo / More-fields). Each value-picker click opened a real overlay
that commit dff86e15 (correctly) registers as a new state — but for a DATA-ENTRY
FORM those overlays are data-entry mechanics, so the form ate the action budget
and the real navigation (Fix & manage -> Settings deep page) was never reached.

This is the screenshot-only analogue of the a11y traversal's
``_filter_obvious_value_entry_controls`` (drop a dense cluster of short
value-entry controls so a form is one page, not field-by-field).

Checks (purely offline; string/type heuristics only):

  (a) FORM = LEAF: on a Create-contact form, the cluster of text-input fields +
      their value-picker dropdowns (Mobile / Home phone-type, Significant date /
      Birthday date pickers, the Label dropdown) is NOT enqueued — but the
      genuinely-navigational chrome (Save, the X/Back that leaves the form, the
      ⋮ More-options overflow) DOES survive (still clickable).

  (b) NO dff86e15 REGRESSION — a real navigation OVERFLOW MENU (the dialer's
      ⋮ -> Call history / Settings / Help & feedback, all el_type=menu, ALL short
      enough to look like field values) is NOT suppressed, because it has ZERO
      text-input fields. The >=1-input gate is exactly what tells a value-picker
      FORM apart from a navigation menu/drawer/dialog (those have no text inputs),
      so the genuine-new-navigation overlays dff86e15 registers still split.

  (c) a real nav ROW page (Settings list: Import from file / Settings / Blocked
      numbers, no inputs) suppresses NOTHING — a non-form page is untouched.

  (d) the FORM-vs-search boundary: a lone SEARCH BOX (1 input, 0 value pickers)
      is NOT suppressed (its search page must still register / be clickable); only
      a genuine MULTI-FIELD form trips the gate.

The form node element sets are taken VERBATIM from the real result artifacts
(node be796f4c4c7f2002 = the More-fields-expanded Create-contact form; dialer
node f22d4ede2d583132 = the genuine overflow nav menu) so the test reproduces the
exact perception output, not an idealised one.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui_rewalk.src.core.visual_traversal.visual_filter import (
    form_field_indices, _looks_like_field_value, _FORM_MIN_FIELDS)


def _suppressed(els):
    """els: list of (name, el_type). Returns the set of NAMES form_field_indices
    would drop from the enqueueable click set."""
    names = [n for n, _ in els]
    types = [t for _, t in els]
    idx = form_field_indices(types, names)
    return {names[i] for i in idx}, {names[i] for i in range(len(names)) if i not in idx}


def test_a_form_is_a_single_leaf():
    # VERBATIM from result artifact node be796f4c4c7f2002 — the Create-contact
    # form with "More fields" expanded: a value-picker form (Significant date is a
    # text INPUT; Home / Birthday / Birthday-dropdown / Label-dropdown are the
    # phone-type / date / label VALUE PICKERS) + its nav chrome (More options ⋮,
    # Back). This is what BFS was exploding into separate states.
    form = [
        ("More options", "icon"),     # ⋮ overflow — genuine nav -> SURVIVES
        ("More options", "icon"),     # (perception double-boxed it)
        ("Back button", "icon"),      # leaves the form -> SURVIVES (backtrack)
        ("Significant date", "input"),  # TEXT INPUT field -> data-entry -> SUPPRESS
        ("Home", "menu"),             # phone-type value picker -> SUPPRESS
        ("Birthday", "menu"),         # date value picker -> SUPPRESS
        ("", "icon"),                 # an unnamed icon -> SURVIVES (not a field)
        ("Birthday dropdown", "menu"),  # date picker dropdown -> SUPPRESS
        ("Label dropdown", "menu"),   # the phone LABEL dropdown -> SUPPRESS
    ]
    suppressed, survive = _suppressed(form)

    # (a) every data-entry widget (the input + the value/label pickers) is dropped
    must_suppress = {"Significant date", "Home", "Birthday",
                     "Birthday dropdown", "Label dropdown"}
    assert must_suppress <= suppressed, (
        "(a) form input field + value-picker dropdowns must NOT be enqueued "
        f"(form=leaf); still-enqueued: {must_suppress - suppressed}")

    # ...and the genuinely-navigational chrome stays clickable (NOT over-pruned)
    assert "More options" in survive, (
        "(a) the ⋮ More-options overflow (opens a different menu) must stay "
        "clickable — only data-entry widgets are suppressed, not navigation")
    assert "Back button" in survive, (
        "(a) Back (leaves the form) must survive — handled by backtracking")
    print(f"(a) FORM = LEAF: suppressed {sorted(suppressed)}")
    print(f"    nav chrome survives: {sorted(survive)}")


def test_b_no_dff86e15_regression_overflow_menu_splits():
    # VERBATIM from dialer node f22d4ede2d583132 — a GENUINE overflow NAVIGATION
    # menu (⋮ -> Call history / Settings / Help & feedback). All three are
    # el_type=menu and ALL are short enough to pass _looks_like_field_value, so a
    # naive "cluster of short dropdowns" rule WOULD wrongly suppress them. The
    # >=1-input gate must protect them: this menu has NO text inputs -> a NEW
    # navigation surface that dff86e15 registers -> must NOT be suppressed.
    overflow_menu = [
        ("Call history", "menu"),
        ("Settings", "menu"),
        ("Help & feedback", "menu"),
        ("Keypad", "button"),
        ("Contacts", "tab"),
        ("Favorites", "tab"),
        ("Recents", "tab"),
        ("Make a call", "link"),
        ("Sign in", "button"),
        ("Skip", "button"),
    ]
    # precondition: these menu items DO look like field values (so the test is
    # meaningful — the input-gate, not the length cap, is doing the protecting).
    for nm in ("Call history", "Settings", "Help & feedback"):
        assert _looks_like_field_value(nm), (
            f"test precondition: '{nm}' should be short enough to look like a "
            "field value — proving the >=1-input gate is the real protection")
    suppressed, survive = _suppressed(overflow_menu)
    assert suppressed == set(), (
        "(b) REGRESSION of dff86e15: a genuine overflow NAVIGATION menu (no text "
        f"inputs) must NOT be suppressed; wrongly dropped: {sorted(suppressed)}")
    for nm in ("Call history", "Settings", "Help & feedback"):
        assert nm in survive
    print(f"(b) dff86e15 PRESERVED: overflow nav menu (Call history/Settings/Help, "
          f"all el_type=menu) suppressed NOTHING (no inputs -> not a form)")


def test_c_nav_row_page_untouched():
    # VERBATIM from contacts settings-nav node 9e9d52d4529547c5 — a plain list of
    # navigation rows (Import from file / Settings / Blocked numbers, Highlights/
    # Contacts/Fix&manage tabs). No inputs -> not a form -> suppress nothing.
    nav_page = [
        ("Import from file", "button"), ("Settings", "button"),
        ("Highlights", "tab"), ("Contacts", "tab"), ("Fix & manage", "tab"),
        ("Blocked numbers icon", "icon"), ("Settings", "text"),
        ("Blocked numbers", "text"), ("Settings gear", "icon"),
    ]
    suppressed, _ = _suppressed(nav_page)
    assert suppressed == set(), (
        f"(c) a navigation list page must be untouched; dropped: {sorted(suppressed)}")
    print("(c) navigation list page (no inputs) -> suppressed NOTHING")


def test_d_lone_search_box_not_a_form():
    # A search page: ONE input (the search box) + real result rows, NO value
    # pickers. Must NOT trip the form gate — the search box stays clickable so its
    # search page still registers. Only a MULTI-field form qualifies.
    search_page = [
        ("Search", "input"),          # the lone search box
        ("Wi-Fi", "text"), ("Notifications", "text"), ("Display", "text"),
        ("Back", "icon"),
    ]
    suppressed, survive = _suppressed(search_page)
    assert suppressed == set(), (
        "(d) a lone search box (1 input, 0 pickers) must NOT be suppressed as a "
        f"form — its search page must register; dropped: {sorted(suppressed)}")
    assert "Search" in survive
    print(f"(d) lone search box ({_FORM_MIN_FIELDS=}) -> not a form, search box "
          "stays clickable")


def test_e_two_text_inputs_alone_are_a_form():
    # A login form: username + password text inputs (>=2 inputs, 0 pickers) IS a
    # data-entry form even without value pickers — the two input FIELDS are
    # suppressed, but the Sign-in BUTTON (navigation/commit) survives.
    login = [
        ("Username", "input"), ("Password", "input"),
        ("Forgot password", "link"), ("Sign in", "button"),
    ]
    suppressed, survive = _suppressed(login)
    assert {"Username", "Password"} <= suppressed, (
        "(e) the two login text-input fields should be suppressed (data-entry)")
    assert "Sign in" in survive, "(e) the Sign-in nav/commit button must survive"
    print("(e) two text inputs alone -> form; fields suppressed, Sign-in survives")

def main():
    test_a_form_is_a_single_leaf()
    test_b_no_dff86e15_regression_overflow_menu_splits()
    test_c_nav_row_page_untouched()
    test_d_lone_search_box_not_a_form()
    test_e_two_text_inputs_alone_are_a_form()
    print("\nALL PASS — a data-entry FORM is explored as ONE leaf function (its "
          "input fields + value-picker dropdowns are NOT enqueued), while a genuine "
          "navigation menu/drawer/dialog (no text inputs) still SPLITS into a new "
          "state (dff86e15 preserved). Form-vs-navigation separated by text-input "
          "presence, no per-app rules.")


if __name__ == "__main__":
    main()
