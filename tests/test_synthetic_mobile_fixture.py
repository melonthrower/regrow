from __future__ import annotations

import io
import json
import re
from pathlib import Path

from PIL import Image

from gui_rewalk.src.config.config import (
    ANDROID_CLEAR_DATA_APPS,
    get_android_activity,
    get_android_package,
)
from gui_rewalk.src.core.graph import mobile_ops
from gui_rewalk.src.core.visual_traversal.prompts.grounding import (
    SEMANTIC_INVENTORY_PROMPT,
)
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualPerception
from synthetic_app.validate_graph import validate
from synthetic_mobile_app.qwen_responses import build_responses
from synthetic_mobile_app.qwen_stub import QwenMobileFixtureStub


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "synthetic_mobile_app"


def _oracle() -> dict:
    return json.loads((FIXTURE / "oracle.json").read_text(encoding="utf-8"))


def _elements(labels: list[str]) -> list[dict]:
    return [
        {"id": str(index), "name": label, "interactive": True, "category": "navigation"}
        for index, label in enumerate(labels)
    ]


def _happy_graph() -> dict:
    oracle = _oracle()
    nodes = []
    state_for_page = {}
    for page in oracle["pages"]:
        state_id = f"m_{page['id']}"
        state_for_page[page["id"]] = state_id
        labels = list(page["anchors"])
        for control in page["controls"]:
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
        state_id = f"m_surface_{surface['id'].replace('.', '_')}"
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
            "action_edge_id": f"mobile_{index}",
            "source": source_state,
            "target": target_state,
            "action": {"action_type": "CLICK", "selector": {"element_label": label}},
            "element_label": label,
            "routing_verified": True,
            "attempts": [{
                "attempt_id": f"mingle:{index}",
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


def test_mobile_oracle_generated_assets_and_apk_are_consistent() -> None:
    oracle = _oracle()
    assert len(oracle["pages"]) == 8
    assert len(oracle["surfaces"]) == 3
    assert sum(
        page["scroll"]["classification"] == "scrollable"
        for page in oracle["pages"]
    ) == 3
    assert sum(len(page["controls"]) for page in oracle["pages"]) == 42

    for path in (
        FIXTURE / "index.html",
        FIXTURE / "app" / "src" / "main" / "assets" / "index.html",
    ):
        rendered = path.read_text(encoding="utf-8")
        assert "__REWALK_ORACLE_JSON__" not in rendered
        match = re.search(
            r'<script type="application/json" id="fixture-oracle">(.*?)</script>',
            rendered,
            flags=re.DOTALL,
        )
        assert match and json.loads(match.group(1)) == oracle
    assert (FIXTURE / "mingle-debug.apk").stat().st_size > 10_000


def test_mobile_legacy_responses_are_accepted_by_current_parser() -> None:
    responses = build_responses()
    persisted = json.loads((FIXTURE / "qwen_responses.json").read_text(encoding="utf-8"))
    assert responses == persisted
    assert len(responses) == 17
    forbidden = {"bbox", "box", "center", "point", "x", "y", "width", "height"}

    def check(value) -> None:
        if isinstance(value, dict):
            assert not (forbidden & {str(key).lower() for key in value})
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(responses)
    for response in responses.values():
        for block in response["blocks"]:
            assert block["scope"] == "target_app"
            assert block["interaction"] == "direct"
    assert '"areas"' in SEMANTIC_INVENTORY_PROMPT
    assert '"blocks"' not in SEMANTIC_INVENTORY_PROMPT
    stream = io.BytesIO()
    Image.new("RGB", (412, 915), "white").save(stream, "PNG")
    perception = VisualPerception(
        None,
        agent=QwenMobileFixtureStub("settings.notifications_off"),
        use_ocr=False,
    )
    elements = perception.semantic_inventory(stream.getvalue())
    notifications = next(item for item in elements if item.name == "Message notifications")
    assert perception.last_page_name == "Settings"
    assert notifications.stateful is True
    assert notifications.state_value == "off"
    assert notifications.effect_scope == "data_only"


def test_mingle_android_config_and_apk_install(monkeypatch) -> None:
    assert get_android_package("mingle") == "com.guirewalk.mingle"
    assert get_android_activity("mingle") == ".MainActivity"
    assert "mingle" in ANDROID_CLEAR_DATA_APPS

    calls = []

    class Result:
        returncode = 0
        stdout = "Success\n"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    class Env:
        adb_path = "adb"
        serial = "emulator-5554"

    monkeypatch.setattr(mobile_ops.subprocess, "run", fake_run)
    env = Env()
    assert mobile_ops._install_mobile_fixture_app(env) is True
    assert calls[0][0][:5] == ["adb", "-s", "emulator-5554", "install", "-r"]
    assert calls[0][0][-1].endswith("mingle-debug.apk")
    assert mobile_ops._install_mobile_fixture_app(env) is True
    assert len(calls) == 1


def test_mobile_validator_accepts_complete_graph_and_detects_missing_page() -> None:
    oracle = _oracle()
    graph = _happy_graph()
    report = validate(oracle, graph)
    assert report["status"] == "pass", report["findings"]
    graph["nodes"] = [
        node for node in graph["nodes"]
        if node["page_id"] != "observed_contacts"
    ]
    broken = validate(oracle, graph)
    assert broken["status"] == "fail"
    assert "missing_page" in {row["code"] for row in broken["findings"]}
