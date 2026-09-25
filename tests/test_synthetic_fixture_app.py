from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from gui_rewalk.src.config.config import (
    APP_BINARY_MAP,
    APP_CACHE_CLEAR_CMDS,
    APP_WINDOW_NAME_MAP,
)
from gui_rewalk.src.core import app_lifecycle
from gui_rewalk.src.core.visual_traversal.prompts.grounding import (
    SEMANTIC_INVENTORY_PROMPT,
)
from synthetic_app.qwen_responses import build_responses
from synthetic_app.validate_graph import validate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "synthetic_app"


def _oracle() -> dict:
    return json.loads((FIXTURE / "oracle.json").read_text(encoding="utf-8"))


def _elements(labels: list[str]) -> list[dict]:
    return [
        {
            "id": str(index),
            "name": label,
            "interactive": True,
            "category": "navigation",
        }
        for index, label in enumerate(labels)
    ]


def _happy_graph() -> dict:
    oracle = _oracle()
    nodes = []
    state_for_page = {}
    for page in oracle["pages"]:
        state_id = f"s_{page['id']}"
        state_for_page[page["id"]] = state_id
        labels = list(page["anchors"])
        for control in page.get("controls") or []:
            labels.append(control["label"])
            if control.get("alternate_label"):
                labels.append(control["alternate_label"])
        nodes.append({
            "state_id": state_id,
            "page_id": f"observed_{page['id']}",
            "variant_id": page["variants"][0]["id"],
            "page_name": page["title"],
            "elements": _elements(labels),
        })

    surface_state = {}
    for surface in oracle["surfaces"]:
        host = surface["host_pages"][0]
        state_id = f"s_surface_{surface['id'].replace('.', '_')}"
        surface_state[surface["id"]] = state_id
        nodes.append({
            "state_id": state_id,
            "page_id": f"observed_{host}",
            "variant_id": surface["id"],
            "page_name": surface["anchors"][0],
            "elements": _elements(
                list(surface["anchors"])
                + [control["label"] for control in surface["controls"]]
            ),
        })

    def label_for(transition: dict) -> str:
        if transition.get("action_label"):
            return transition["action_label"]
        if transition.get("action_labels"):
            return transition["action_labels"][0]
        return transition["action_label_pattern"] + "01"

    edges = []
    for index, transition in enumerate(oracle["transitions"], start=1):
        source_page = transition.get("source_page") or transition["source_pages"][0]
        target_page = transition["target_page"]
        if target_page == "$source":
            target_page = source_page
        source_state = state_for_page[source_page]
        if transition.get("source_surface"):
            source_state = surface_state[transition["source_surface"]]
        target_state = state_for_page[target_page]
        if transition.get("target_surface"):
            target_state = surface_state[transition["target_surface"]]
        label = label_for(transition)
        edges.append({
            "action_edge_id": f"ae_{index}",
            "source": source_state,
            "target": target_state,
            "action": {
                "action_type": "CLICK",
                "selector": {"element_label": label},
            },
            "element_label": label,
            "routing_verified": True,
            "attempts": [{
                "attempt_id": f"fixture:{index}",
                "committed": True,
                "landing_verified": True,
            }],
        })

    ledgers = []
    for page in oracle["pages"]:
        scroll = page["scroll"]
        if scroll["classification"] != "scrollable":
            continue
        ledgers.append({
            "scope_id": f"state:{state_for_page[page['id']]}:page",
            "state_ids": [state_for_page[page["id"]]],
            "role": "page",
            "classification": "scrollable",
            "termination": "viewport_stable",
            "bottom_reached": True,
            "top_restored": True,
            "steps": scroll["min_scroll_steps"],
            "complete": True,
        })
    return {
        "graph_schema_version": 3,
        "nodes": nodes,
        "action_edges": edges,
        "scroll_ledger": ledgers,
    }


def test_oracle_ids_and_generated_pages_are_consistent() -> None:
    oracle = _oracle()
    page_ids = [page["id"] for page in oracle["pages"]]
    assert len(page_ids) == len(set(page_ids)) == 9
    assert sum(page["scroll"]["classification"] == "scrollable" for page in oracle["pages"]) == 3
    assert {surface["kind"] for surface in oracle["surfaces"]} == {"popup_menu", "dialog"}

    workspace = next(page for page in oracle["pages"] if page["id"] == "workspace")
    nested = workspace["scroll"]["nested_regions"]
    assert workspace["scroll"]["outer_page_scrolls"] is False
    assert [region["depth_rank"] for region in nested] == [1, 2, 3]
    assert {region["region_id"] for region in nested} == {
        block["id"] for block in workspace["blocks"] if block["scrollable"]
    }
    assert {region["entry_control_id"] for region in nested} == {
        control["id"] for control in workspace["controls"]
        if control["block"].startswith("workspace.")
        and control["block"] != "workspace.app_bar"
    }

    known_pages = set(page_ids)
    for transition in oracle["transitions"]:
        sources = transition.get("source_pages") or [transition.get("source_page")]
        assert set(sources) <= known_pages
        assert transition["target_page"] == "$source" or transition["target_page"] in known_pages

    for name in ("index.html", "inspector.html"):
        rendered = (FIXTURE / name).read_text(encoding="utf-8")
        assert "__REWALK_ORACLE_JSON__" not in rendered
        match = re.search(
            r'<script type="application/json" id="fixture-oracle">(.*?)</script>',
            rendered,
            flags=re.DOTALL,
        )
        assert match
        assert json.loads(match.group(1)) == oracle


def test_fixture_responses_remain_legacy_and_document_live_contract() -> None:
    responses = build_responses()
    persisted = json.loads((FIXTURE / "qwen_responses.json").read_text(encoding="utf-8"))
    assert persisted == responses
    assert len(responses) == 15
    required_top = {
        "page", "surface_kind", "surface_scrollable", "is_system_dialog",
        "is_interruption", "blocks",
    }
    required_element = {
        "name", "type", "interactive", "category", "selected", "group",
        "back", "enabled", "requires_permission", "blocked_reason", "stateful",
        "state_key", "state_value", "effect_scope", "reversible", "risk",
        "identity_anchor",
    }
    forbidden = {"bbox", "box", "center", "point", "x", "y", "width", "height"}

    def check_no_geometry(value) -> None:
        if isinstance(value, dict):
            assert not (forbidden & {str(key).lower() for key in value})
            for child in value.values():
                check_no_geometry(child)
        elif isinstance(value, list):
            for child in value:
                check_no_geometry(child)

    for response in responses.values():
        assert set(response) == required_top
        assert response["surface_kind"] in {"page", "dialog", "popup_menu"}
        check_no_geometry(response)
        for block in response["blocks"]:
            assert set(block) == {
                "role", "scope", "interaction", "note", "scrollable", "elements",
            }
            assert block["scope"] == "target_app"
            assert block["interaction"] == "direct"
            for item in block["elements"]:
                assert set(item) == required_element
                assert item["category"] in {"navigation", "shallow", "dangerous", "display"}

    # Persisted fixture answers retain the legacy rich fixture schema so the
    # deterministic stub stays stable.  The current live VLM contract instead
    # describes interface areas and their controls.
    for field in {
        "interface_summary", "surface_kind", "areas", "bbox_1000",
        "controls", "name", "purpose", "execution_safety",
    }:
        assert f'"{field}"' in SEMANTIC_INVENTORY_PROMPT
    for field in {
        "category", "stateful", "state_value", "risk",
        "requires_permission", "blocks", "elements", "role",
    }:
        assert f'"{field}"' not in SEMANTIC_INVENTORY_PROMPT

def test_workspace_regions_scroll_independently_and_reveal_hidden_entries() -> None:
    oracle = _oracle()
    workspace = next(page for page in oracle["pages"] if page["id"] == "workspace")
    truth = workspace["scroll"]["nested_regions"]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1365, "height": 900})
        page.goto((FIXTURE / "index.html").as_uri() + "#/workspace")
        page.wait_for_function("window.__fixture?.snapshot().page === 'workspace'")

        assert page.evaluate(
            "document.scrollingElement.scrollHeight === innerHeight"
        )
        initial = page.evaluate("""
            () => Object.fromEntries(
              [...document.querySelectorAll('[data-scroll-region-id]')].map(node => {
                const button = node.querySelector('button[data-action-id]');
                return [node.dataset.scrollRegionId, {
                  scrollTop: node.scrollTop,
                  scrollHeight: node.scrollHeight,
                  clientHeight: node.clientHeight,
                  regionBottom: node.getBoundingClientRect().bottom,
                  entryTop: button.getBoundingClientRect().top
                }];
              })
            )
        """)
        assert set(initial) == {region["region_id"] for region in truth}
        assert all(item["scrollHeight"] > item["clientHeight"] for item in initial.values())
        assert all(item["scrollTop"] == 0 for item in initial.values())
        assert all(item["entryTop"] >= item["regionBottom"] for item in initial.values())

        revealed_depths = []
        for region in truth:
            page.eval_on_selector_all(
                "[data-scroll-region-id]", "nodes => nodes.forEach(node => node.scrollTop = 0)"
            )
            selector = f'[data-scroll-region-id="{region["region_id"]}"]'
            scroller = page.locator(selector)
            button = scroller.get_by_role("button", name=region["entry_label"])
            button.scroll_into_view_if_needed()

            positions = page.evaluate("""
                () => Object.fromEntries(
                  [...document.querySelectorAll('[data-scroll-region-id]')]
                    .map(node => [node.dataset.scrollRegionId, node.scrollTop])
                )
            """)
            assert positions[region["region_id"]] > 0
            assert all(
                value == 0 for name, value in positions.items()
                if name != region["region_id"]
            )
            assert page.evaluate("scrollY") == 0
            revealed_depths.append(positions[region["region_id"]])

            button.click()
            assert page.locator("[data-workspace-status]").inner_text() == (
                region["expected_outcome"]
            )
            assert page.locator("#fixture-app").get_attribute(
                "data-workspace-selection"
            ) == region["entry_control_id"]

        assert revealed_depths == sorted(revealed_depths)
        assert len(set(revealed_depths)) == 3
        browser.close()


def test_framework_fixture_launch_configuration_and_guest_install(monkeypatch, tmp_path) -> None:
    fixture = tmp_path / "index.html"
    fixture.write_bytes(b"<title>fixture sentinel</title>")
    commands = []

    class Controller:
        def execute_python_command(self, command: str):
            commands.append(command)
            return {"output": "fixture_ready"}

    class Env:
        controller = Controller()

    monkeypatch.setattr(app_lifecycle, "_fixture_asset_path", lambda: fixture)
    assert app_lifecycle._install_embedded_fixture_app(Env()) is True
    assert len(commands) == 1
    encoded = base64.b64encode(fixture.read_bytes()).decode("ascii")
    assert encoded in commands[0]
    assert app_lifecycle.FIXTURE_GUEST_DIR in commands[0]

    command = APP_BINARY_MAP[app_lifecycle.FIXTURE_APP_NAME]
    assert "file:///tmp/gui_rewalk_fixture/index.html" in command
    assert "--user-data-dir=/tmp/gui_rewalk_fixture/profile" in command
    assert app_lifecycle.FIXTURE_APP_NAME == "dayline"
    assert "Dayline" in APP_WINDOW_NAME_MAP[app_lifecycle.FIXTURE_APP_NAME]
    assert "rewalk fixture" in app_lifecycle.FIXTURE_APP_NAMES
    assert APP_BINARY_MAP["rewalk fixture"]
    assert APP_CACHE_CLEAR_CMDS[app_lifecycle.FIXTURE_APP_NAME] == [
        "rm -rf /tmp/gui_rewalk_fixture/profile"
    ]


def test_oracle_validator_accepts_complete_graph_and_explains_breakage() -> None:
    oracle = _oracle()
    graph = _happy_graph()
    report = validate(oracle, graph)
    assert report["status"] == "pass", report["findings"]

    graph["nodes"] = [
        node for node in graph["nodes"]
        if node["page_id"] != "observed_activity"
    ]
    graph["scroll_ledger"] = []
    broken = validate(oracle, graph)
    assert broken["status"] == "fail"
    codes = {finding["code"] for finding in broken["findings"]}
    assert "missing_page" in codes
    assert "missing_verified_transition" in codes
    assert "incomplete_scroll_scope" in codes
