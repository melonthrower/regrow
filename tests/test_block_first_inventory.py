import io
import json

import numpy as np
from PIL import Image

from gui_rewalk.src.core.visual_traversal.block_first_inventory import (
    BlockFirstInventoryExperiment,
)
from gui_rewalk.src.core.visual_traversal.prompts.block_inventory import (
    PAGE_MAP_PROMPT,
)
from gui_rewalk.src.core.visual_traversal.visual_cache import VLMCallLedger


def _png(width=200, height=100):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    out = io.BytesIO()
    Image.fromarray(image).save(out, format="PNG")
    return out.getvalue()


class _Agent:
    model = "fake"
    model_version = "fake-v1"
    max_tokens = 100
    top_p = 0.9
    temperature = 0
    enable_thinking = False
    max_retry = 1

    def __init__(self, *, bbox=None, invalid_entry=False):
        self.calls = []
        self.bbox = bbox or [0, 200, 1000, 900]
        self.invalid_entry = invalid_entry

    def predict_mm_with_policy(
            self, prompt, images, max_attempts, timeout_seconds=None):
        self.calls.append((prompt, [image.shape for image in images]))
        if "Step 1: Determine active interaction surface" in prompt:
            return json.dumps({
                "interface_name": "Contacts",
                "regions": [
                    {"region_id": "r0", "name": "Header",
                     "description": "Primary page commands."},
                    {"region_id": "r1", "name": "Contacts",
                     "description": "Scrollable collection of people."},
                ],
            }), 10, 5, 1
        if "GUI Region locator" in prompt:
            return json.dumps({
                "region_id": "r1", "found": True,
                "bbox_1000": self.bbox, "scrollable": True,
                "reason": "The selected container is visually distinct.",
            }), 8, 4, 1
        entry = (
            {"entry_id": "", "target": "Alex Chen"}
            if self.invalid_entry else
            {"entry_id": "e0", "target": "Alex Chen"}
        )
        return json.dumps({
            "region_id": "r1", "function_entries": [entry],
        }), 8, 4, 1


def _run_to_location(experiment, screenshot):
    discovery = experiment.discover(screenshot)
    selected = experiment.choose(discovery["regions"], "Contacts")
    localization = experiment.locate(screenshot, discovery, selected)
    return discovery, selected, localization


def test_page_map_is_one_call_and_region_inventory_returns_function_entries():
    agent = _Agent()
    ledger = VLMCallLedger()
    experiment = BlockFirstInventoryExperiment(agent, ledger=ledger)
    screenshot = _png()
    discovery, selected, localization = _run_to_location(
        experiment, screenshot)
    inventory, crop = experiment.inventory(
        screenshot, discovery, selected, localization,
        image_mode="context_crop")

    assert discovery["status"] == "ok"
    assert [row["region_id"] for row in discovery["regions"]] == ["r0", "r1"]
    assert localization["bbox_1000"] == [0, 200, 1000, 900]
    assert inventory["function_entries"] == [{
        "entry_id": "e0", "target": "Alex Chen"}]
    assert inventory["input_image_count"] == 2
    assert crop.size == (200, 70)
    assert len(agent.calls) == 3
    roles = ledger.snapshot()["roles"]
    assert roles["semantic_page_map"]["calls"] == 1
    assert "semantic_active_region_filter" not in roles
    assert roles["semantic_region_localization"]["calls"] == 1
    assert roles["semantic_region_inventory"]["calls"] == 1


def test_region_locator_rebinds_from_each_supplied_complete_frame():
    agent = _Agent()
    experiment = BlockFirstInventoryExperiment(agent)
    screenshot = _png()
    discovery = experiment.discover(screenshot)
    selected = experiment.choose(discovery["regions"], "r1")
    first = experiment.locate(screenshot, discovery, selected)
    agent.bbox = [100, 100, 900, 800]
    second = experiment.locate(_png(width=300), discovery, selected,
                               force_refresh=True)

    assert first["bbox_1000"] == [0, 200, 1000, 900]
    assert second["bbox_1000"] == [100, 100, 900, 800]
    assert agent.calls[-1][1] == [(100, 300, 3)]


def test_empty_function_entries_is_a_valid_region_observation():
    agent = _Agent()
    experiment = BlockFirstInventoryExperiment(agent)
    screenshot = _png()
    discovery, selected, localization = _run_to_location(
        experiment, screenshot)
    agent.predict_mm_with_policy = lambda *_args, **_kwargs: (
        '{"region_id":"r1","function_entries":[]}', 1, 1, 1)

    inventory, _ = experiment.inventory(
        screenshot, discovery, selected, localization)

    assert inventory["status"] == "ok"
    assert inventory["function_entries"] == []


def test_invalid_function_entry_is_rejected_without_retry():
    agent = _Agent(invalid_entry=True)
    experiment = BlockFirstInventoryExperiment(agent)
    screenshot = _png()
    discovery, selected, localization = _run_to_location(
        experiment, screenshot)
    inventory, _ = experiment.inventory(
        screenshot, discovery, selected, localization)

    assert inventory["status"] == "partial"
    assert inventory["function_entries"] == []
    assert inventory["rejected_function_entries"][0]["reason"] == (
        "missing or duplicate entry_id")
    assert len(agent.calls) == 3


def test_confirmed_page_map_prompt_owns_active_surface_selection():
    assert "Step 1: Determine active interaction surface" in PAGE_MAP_PROMPT
    assert "当前截图只能存在一个 active interaction surface" in PAGE_MAP_PROMPT
    assert "inactive background 不允许出现在 regions 中" in PAGE_MAP_PROMPT
    assert "Region 是功能容器，不是单个操作目标" in PAGE_MAP_PROMPT
