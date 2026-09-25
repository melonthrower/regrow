from io import BytesIO
from pathlib import Path
import sys
from types import SimpleNamespace

from PIL import Image
import pytest

from gui_rewalk import run_visual_traversal as traversal_entry
from gui_rewalk.env.local_html_gui_gen_env import LocalHTMLGUIGenEnv
from gui_rewalk.run_visual_traversal import parse_args


ROOT = Path(__file__).resolve().parents[1]
MINGLE = ROOT / "synthetic_mobile_app" / "index.html"
DAYLINE = ROOT / "synthetic_app" / "index.html"


def test_local_html_env_dispatches_pixel_actions_without_dom_perception():
    env = LocalHTMLGUIGenEnv(
        str(MINGLE), screen_size=(412, 915), clean_start=True)
    try:
        obs = env.reset()
        assert Image.open(BytesIO(obs["screenshot"])).size == (412, 915)
        assert env.vm_platform == "android"
        assert env._page.url.endswith("#/inbox")

        target = env._page.locator('[data-action-id="inbox.open_weekend"]')
        box = target.bounding_box()
        assert box
        env.step({
            "action_type": "CLICK",
            "parameters": {
                "x": box["x"] + box["width"] / 2,
                "y": box["y"] + box["height"] / 2,
            },
        }, pause=0)
        assert env._page.url.endswith("#/conversation")

        env.step({"action_type": "BACK"}, pause=0)
        assert env._page.url.endswith("#/inbox")

        env.step({"action_type": "navigate_home"}, pause=0)
        assert env._page.url.endswith("#/inbox")

        before = env._page.evaluate("window.scrollY")
        env.step({
            "action_type": "SCROLL",
            "parameters": {"direction": "down", "amount": 1},
        }, pause=0.2)
        after = env._page.evaluate("window.scrollY")
        assert after > before

        env._page.evaluate("scrollTo(0, 0)")
        env.step({
            "action_type": "SCROLL",
            "parameters": {"dy": -8},
        }, pause=0.2)
        # The traversal's desktop contract is wheel clicks, whereas Playwright
        # consumes pixels.  One canonical step must be materially visible.
        assert env._page.evaluate("window.scrollY") >= 100
    finally:
        env.close()


def test_local_html_start_hash_cli_default_and_explicit(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_visual_traversal.py"])
    assert parse_args().local_html_start_hash == "#/inbox"
    assert parse_args().autonomous_test_target_edge is None
    assert parse_args().explore_backend == "qwen_api"

    monkeypatch.setattr(
        sys, "argv",
        ["run_visual_traversal.py", "--local_html_start_hash", "#/workspace"])
    assert parse_args().local_html_start_hash == "#/workspace"


def test_modular_explore_codex_backend_cli_and_preflight_without_qwen_key(
    monkeypatch,
):
    monkeypatch.setattr(sys, "argv", [
        "run_visual_traversal.py",
        "--vm_provider", "local_html",
        "--html_path", str(MINGLE),
        "--app_name", "mingle",
        "--modular-explore",
        "--explore-backend", "codex_cli",
        "--explore-model", "gpt-5.6-luna",
        "--no_live_monitor",
    ])
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setattr(traversal_entry, "setup_live_monitor", lambda _args: None)
    captured = []
    monkeypatch.setattr(
        traversal_entry, "run_full",
        lambda args: captured.append(args) or 17,
    )

    assert traversal_entry.main() == 17
    assert captured[0].explore_backend == "codex_cli"


def test_autonomous_target_edge_cli_parses_exact_page_and_button(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "run_visual_traversal.py",
        "--autonomous_test_target_edge",
        " Kitchen notes :: Browse recipes :: Recipe collection ",
    ])

    assert parse_args().autonomous_test_target_edge == {
        "source_page": "Kitchen notes",
        "target": "Browse recipes",
        "expected_destination": "Recipe collection",
    }


@pytest.mark.parametrize(
    "value",
    ["", "Kitchen notes", "Kitchen notes::Browse recipes", "::Browse::Recipes"],
)
def test_autonomous_target_edge_cli_rejects_incomplete_pair(
    monkeypatch, value,
):
    monkeypatch.setattr(sys, "argv", [
        "run_visual_traversal.py", "--autonomous_test_target_edge", value,
    ])
    with pytest.raises(SystemExit):
        parse_args()


def test_local_html_env_uses_explicit_start_hash():
    env = LocalHTMLGUIGenEnv(
        str(DAYLINE), screen_size=(1365, 900), start_hash="#/workspace")
    try:
        env.reset()
        assert env.start_hash == "#/workspace"
        assert env._page.url.endswith("#/workspace")
        assert env._page.locator("[data-page-id='workspace']").count() == 1
    finally:
        env.close()


@pytest.mark.parametrize(
    "start_hash", ["", "workspace", "#/", "#/work space", "#/workspace#detail"])
def test_local_html_env_rejects_invalid_start_hash(start_hash):
    with pytest.raises(ValueError, match=r"format '#/<route>'"):
        LocalHTMLGUIGenEnv(str(DAYLINE), start_hash=start_hash)


def test_fixture_oracle_supplies_visible_inventory_and_exact_grounding():
    env = LocalHTMLGUIGenEnv(
        str(MINGLE), screen_size=(412, 915), clean_start=True,
        fixture_oracle_inventory=True, fixture_oracle_grounding=True)
    try:
        env.reset()
        payload = env.fixture_semantic_inventory()
        assert payload["page"] == "Chats"
        assert payload["surface_kind"] == "page"
        assert payload["blocks"]
        assert all(block["fixture_oracle"] for block in payload["blocks"])
        assert all(
            isinstance(block.get("bbox_1000"), list)
            and len(block["bbox_1000"]) == 4
            for block in payload["blocks"])
        elements = [element for block in payload["blocks"]
                    for element in block["elements"]]
        names = {element["name"] for element in elements}
        assert {"Search chats", "Open Weekend Plan", "New chat",
                "Contacts", "Explore", "Me"} <= names
        selected = [element for element in elements if element["selected"]]
        assert [(element["name"], element["type"])
                for element in selected] == [("Chats", "tab")]
        search_inventory = next(
            element for element in elements if element["name"] == "Search chats")
        assert search_inventory["stateful"] is True
        assert search_inventory["reversible"] is True
        assert search_inventory["effect_scope"] == "function_set"
        assert search_inventory["category"] == "navigation"
        assert search_inventory["risk"] == "none"
        weekend_inventory = next(
            element for element in elements
            if element["name"] == "Open Weekend Plan")
        assert (weekend_inventory["category"], weekend_inventory["risk"]) == (
            "navigation", "none")
        # Long-list filler rows exist in the HTML but are intentionally absent
        # from the fixture contract and must not leak into oracle inventory.
        assert "City Volunteers" not in names

        assert "Recent chats" in names

        search = SimpleNamespace(
            name="Search chats", region="top_app_bar", el_type="button",
            category="navigation", back=False, enabled=True, selected=False)
        search_hit = env.resolve_fixture_grounding(search)
        assert search_hit["status"] == "matched"
        assert search_hit["action_id"] == "inbox.search"

        weekend = SimpleNamespace(
            name="Open Weekend Plan", region="conversation_list",
            el_type="button", category="navigation", back=False,
            enabled=True, selected=False)
        hit = env.resolve_fixture_grounding(weekend)
        assert hit["status"] == "matched"
        assert hit["action_id"] == "inbox.open_weekend"
        env.step({"action_type": "CLICK", "parameters": {
            "x": hit["center"][0], "y": hit["center"][1]}}, pause=0)
        assert env._page.url.endswith("#/conversation")

        info = SimpleNamespace(
            name="Chat info", region="top_app_bar", el_type="button",
            category="navigation", back=False, enabled=True, selected=False)
        info_hit = env.resolve_fixture_grounding(info)
        assert info_hit["status"] == "matched"
        assert info_hit["action_id"] == "conversation.info"

        invented = SimpleNamespace(
            name="Dark mode", region="message_thread", el_type="switch",
            category="navigation", back=False, enabled=True, selected=False)
        assert env.resolve_fixture_grounding(invented)["status"] == "not_found"

        env._page.evaluate("location.hash = '#/contact_profile'")
        env._page.wait_for_timeout(100)
        profile = env.fixture_semantic_inventory()
        favorite = next(
            element for block in profile["blocks"]
            for element in block["elements"]
            if element["name"] == "Add to favorites")
        assert favorite["stateful"] is True
        assert favorite["effect_scope"] == "data_only"
    finally:
        env.close()


def test_autonomous_fixture_audit_records_truth_without_enabling_oracle_inputs():
    env = LocalHTMLGUIGenEnv(
        str(MINGLE), screen_size=(412, 915), clean_start=True)
    try:
        env.reset()
        assert env.fixture_oracle_inventory is False
        assert env.fixture_oracle_grounding is False
        target = env._page.locator('[data-action-id="inbox.open_weekend"]')
        box = target.bounding_box()
        assert box
        action = {"action_type": "CLICK", "parameters": {
            "x": box["x"] + box["width"] / 2,
            "y": box["y"] + box["height"] / 2,
        }}

        before = env.autonomous_fixture_audit(action)
        env.step(action, pause=0)
        after = env.autonomous_fixture_audit()

        assert before["page"] == "inbox"
        assert before["action_id"] == "inbox.open_weekend"
        assert before["action_disabled"] is False
        assert after["page"] == "conversation"
        assert after["action_id"] == ""
        assert after["state"]["muted"] is False
    finally:
        env.close()


def test_fixture_oracle_retains_scrollable_content_block_without_controls():
    env = LocalHTMLGUIGenEnv(
        str(MINGLE), screen_size=(412, 915), clean_start=True,
        fixture_oracle_inventory=True)
    try:
        env.reset()
        env._page.evaluate("location.hash = '#/conversation'")
        env._page.wait_for_timeout(100)
        payload = env.fixture_semantic_inventory()
        thread = next(
            block for block in payload["blocks"]
            if block["role"] == "message_thread")
        assert thread["scrollable"] is True
        assert not any(
            element.get("interactive") is True
            for element in thread["elements"])
        assert len(thread["bbox_1000"]) == 4
    finally:
        env.close()


def test_fixture_oracle_full_surface_includes_below_fold_controls():
    env = LocalHTMLGUIGenEnv(
        str(DAYLINE), screen_size=(1365, 900), clean_start=True,
        fixture_oracle_inventory=True)
    try:
        env.reset()
        env._page.evaluate("location.hash = '#/library'")
        env._page.wait_for_timeout(100)

        visible = env.fixture_semantic_inventory()
        complete = env.fixture_semantic_inventory(full_surface=True)
        visible_names = {element["name"] for block in visible["blocks"]
                         for element in block["elements"]
                         if element.get("interactive") is True}
        complete_elements = [element for block in complete["blocks"]
                             for element in block["elements"]]
        complete_names = {element["name"] for element in complete_elements}

        assert "Open Document 09" not in visible_names
        assert "Open Document 09" in complete_names
        below_fold = next(element for element in complete_elements
                          if element["name"] == "Open Document 09")
        assert below_fold["bbox_xywh"][1] > 900
    finally:
        env.close()


def test_fixture_grounding_accepts_selected_navigation_omitted_from_oracle_actions():
    env = LocalHTMLGUIGenEnv(
        str(DAYLINE), screen_size=(1365, 900), clean_start=True,
        fixture_oracle_inventory=True, fixture_oracle_grounding=True)
    try:
        env.reset()
        env._page.evaluate("location.hash = '#/settings'")
        env._page.wait_for_timeout(100)
        payload = env.fixture_semantic_inventory()
        selected = [
            element for block in payload["blocks"]
            for element in block["elements"]
            if element.get("selected") is True
        ]
        assert [element["name"] for element in selected] == ["Settings"]

        hit = env.resolve_fixture_grounding(SimpleNamespace(
            name="Settings", region="primary_navigation", el_type="target",
            category="navigation", back=False, enabled=None, selected=True))
        assert hit["status"] == "matched"
        assert hit["action_id"] == "settings.nav_settings"
        assert hit["selected"] is True
        env.step({"action_type": "CLICK", "parameters": {
            "x": hit["center"][0], "y": hit["center"][1]}}, pause=0)
        assert env._page.url.endswith("#/settings")
    finally:
        env.close()
