from __future__ import annotations

import io
from PIL import Image

from gui_rewalk.src.core.visual_traversal.grounding.region.registry import (
    RegionRegistry,
)
from gui_rewalk.src.core.visual_traversal.state.registry import VisualStateRegistry


def test_only_mapped_names_enter_region_coverage():
    registry = RegionRegistry()
    region_id = registry.mint_semantic_concept(
        role="block", names=[], action_names=[])

    registry.record_mapped_elements(region_id, ["More options"])

    assert registry.buttons(region_id) == {"more options"}
    assert "open overflow choices" not in registry.buttons(region_id)


def test_observer_correction_replaces_state_button_name():
    registry = VisualStateRegistry()
    registry.set_buttons("calendar", ["Date picker", "New event"])
    registry.mark_clicked("calendar", "Date picker")

    registry.rename_button(
        "calendar", "Date picker", "Manage your calendars")

    assert "date picker" not in registry._coverage["calendar"]
    assert "manage your calendars" in registry._coverage["calendar"]
    assert "date picker" not in registry._clicked["calendar"]
    assert "manage your calendars" in registry._clicked["calendar"]


def test_confirmed_page_target_beats_an_exact_duplicate_frame(tmp_path):
    registry = VisualStateRegistry()
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(stream, "PNG")
    screenshot = stream.getvalue()
    registry._states = {
        "wrong": (None, str(tmp_path / "wrong.png")),
        "confirmed": (None, str(tmp_path / "confirmed.png")),
    }
    registry.exact_frame_state_ids = lambda _shot: ("wrong",)

    state_id, is_new = registry.register(
        screenshot, str(tmp_path / "live.png"),
        preferred_state_id="confirmed", page_name="Clock")

    assert state_id == "confirmed"
    assert is_new is False
