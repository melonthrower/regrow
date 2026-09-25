from __future__ import annotations

from PIL import Image

from tools.explore_ground_probe import (
    DEMO_CASES,
    build_prompt,
    crop_action_to_full,
    crop_geometry,
    expected_hit,
    validate_response,
)


def test_prompt_excludes_fixture_evaluation_geometry() -> None:
    prompt = build_prompt(DEMO_CASES["mingle_inbox"])

    assert "Open Weekend Plan" in prompt
    assert "expected_bbox_full_1000" not in prompt
    assert len(prompt) < 2600


def test_fixed_target_prompt_adds_only_textual_siblings_when_enabled() -> None:
    case = {
        **DEMO_CASES["mingle_inbox"],
        "fixed_target_choice_id": "c0",
        "include_sibling_text": False,
    }
    target_only = build_prompt(case)
    case["include_sibling_text"] = True
    with_siblings = build_prompt(case)

    assert "Open Weekend Plan" in target_only
    assert "Open Alex Chen chat" not in target_only
    assert "Open Alex Chen chat" in with_siblings
    assert "expected_bbox_full_1000" not in with_siblings


def test_validate_and_map_unique_action() -> None:
    case = DEMO_CASES["mingle_inbox"]
    parsed = {
        "resolved": [],
        "action": {
            "choice_id": "c0",
            "grounding_status": "unique",
            "bbox_crop_1000": [3, 3, 997, 106],
            "click_point_crop_1000": [500, 54],
            "visual_evidence": "Weekend Plan first row",
        },
    }

    clean, errors = validate_response(
        parsed, case["candidates"], case["verified"])
    assert errors == []
    mapped = crop_action_to_full(
        clean["action"], [14, 113, 398, 847], [412, 915])
    assert expected_hit(mapped, case["candidates"]) is True
    assert mapped["click_point_full_px"] == [206, 153]


def test_validate_rejects_inconsistent_or_unknown_geometry() -> None:
    case = DEMO_CASES["mingle_inbox"]
    parsed = {
        "resolved": [],
        "action": {
            "choice_id": "c9",
            "grounding_status": "unique",
            "bbox_crop_1000": [100, 100, 200, 200],
            "click_point_crop_1000": [250, 150],
            "visual_evidence": "unknown row",
        },
    }

    _clean, errors = validate_response(
        parsed, case["candidates"], case["verified"])
    assert "action references unknown choice_id 'c9'" in errors
    assert "click point is outside the proposed bbox" in errors


def test_validate_accepts_disabled_without_geometry() -> None:
    case = DEMO_CASES["mingle_inbox"]
    parsed = {
        "resolved": [],
        "action": {
            "choice_id": "c0",
            "grounding_status": "disabled",
            "visual_evidence": "control is visibly greyed out",
        },
    }

    clean, errors = validate_response(
        parsed, case["candidates"], case["verified"])

    assert errors == []
    assert clean["action"]["grounding_status"] == "disabled"
    assert "click_point_crop_1000" not in clean["action"]


def test_validate_rejects_wrong_fixed_target_choice() -> None:
    case = DEMO_CASES["mingle_inbox"]
    parsed = {
        "resolved": [],
        "action": {
            "choice_id": "c1",
            "grounding_status": "not_visible",
            "visual_evidence": "target not found",
        },
    }

    _clean, errors = validate_response(
        parsed, case["candidates"], case["verified"], "c0")

    assert "action must ground fixed choice_id 'c0'" in errors


def test_crop_geometry_clips_to_current_viewport() -> None:
    image = Image.new("RGB", (412, 915), "white")
    crop, box = crop_geometry(image, [34, 124, 966, 926])

    assert box == [14, 113, 398, 847]
    assert crop.size == (384, 734)
