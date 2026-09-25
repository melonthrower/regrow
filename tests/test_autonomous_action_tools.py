"""Offline contracts for explicit autonomous GUI action tools."""

from __future__ import annotations

import math

import pytest

from gui_rewalk.src.core.visual_traversal.runtime.autonomous_action_tools import (
    ActionValidationError,
    CLICK_REVIEW_SCHEMA,
    CLICK_REVIEW_PROMPT,
    INTERRUPTION_REVIEW_PROMPT,
    INTERRUPTION_REVIEW_SCHEMA,
    action_tool_catalog,
    build_action_result,
    validate_action_tool_call,
)


LATEST_FRAME = "frame-latest"
def test_action_reviewer_has_one_mode_and_no_action_rewrite_authority() -> None:
    assert "每次调用只完成请求中指定的一项工作" in CLICK_REVIEW_PROMPT
    assert "不判断动作结果" in CLICK_REVIEW_PROMPT
    assert "点位关系、任务作用和风险依据" in CLICK_REVIEW_PROMPT
    assert "有意选择的可见界面表面" in CLICK_REVIEW_PROMPT
    assert "不能仅因它不是控件而拒绝" in CLICK_REVIEW_PROMPT
    assert "是否生效由后续截图判断" in CLICK_REVIEW_PROMPT
    assert "不得替主 Agent 改目标、改坐标或换动作" in CLICK_REVIEW_PROMPT
    assert "这里提出的恢复动作已经完成行动复核" in (
        INTERRUPTION_REVIEW_PROMPT)
    assert CLICK_REVIEW_PROMPT == INTERRUPTION_REVIEW_PROMPT
    assert CLICK_REVIEW_SCHEMA["properties"]["reason"]["minLength"] == 1


def _click_arguments(**updates):
    arguments = {
        "target": "Weekend Plan",
        "point_1000": [500, 400],
        "entry_id": "ae7",
    }
    arguments.update(updates)
    return arguments


def _scroll_arguments(**updates):
    arguments = {
        "container_hint": "Conversation list viewport",
        "point_1000": [500, 500],
        "direction": "down",
        "amount": 600,
    }
    arguments.update(updates)
    return arguments


def _hover_arguments(**updates):
    arguments = {
        "target": "Software Updates notification card",
        "point_1000": [530, 60],
    }
    arguments.update(updates)
    return arguments


def _input_text_arguments(**updates):
    arguments = {
        "target": "City search field in Add City dialog",
        "point_1000": [500, 300],
        "text": "oslo",
    }
    arguments.update(updates)
    return arguments


def _gesture_arguments(**updates):
    arguments = {
        "operation": "long_press",
        "target": "Alarm row",
        "entry_id": "ae9",
        "point_1000": [500, 400],
    }
    arguments.update(updates)
    return arguments


def test_catalog_is_compact_dynamic_and_grants_only_explicit_authority() -> None:
    catalog = action_tool_catalog()

    assert [item["name"] for item in catalog] == [
        "click", "hover", "input_text", "scroll", "navigate"]
    required = {
        "name", "description", "input_schema", "effect", "returns",
        "requires_review", "executes_gui",
    }
    assert all(required <= set(item) for item in catalog)
    assert all("handler" not in item for item in catalog)
    assert all(len(item["description"]) <= 260 for item in catalog)
    assert sum(len(item["description"]) for item in catalog) <= 1050
    assert "实际控件或表面" in catalog[0]["description"]
    assert "有意选择的界面表面" in catalog[0]["description"]
    assert "不能写预期效果或不可见目标" in catalog[0]["description"]
    assert "Actual visible control or intentionally selected surface" in (
        catalog[0]["input_schema"]["properties"]["target"]["description"]
    )
    assert set(catalog[1]["input_schema"]["properties"]) == {
        "target", "point_1000",
    }
    assert set(catalog[2]["input_schema"]["properties"]) == {
        "target", "point_1000", "text",
    }
    assert set(catalog[3]["input_schema"]["properties"]) == {
        "container_hint", "point_1000", "direction", "amount",
    }
    assert set(catalog[0]["input_schema"]["properties"]) == {
        "target", "entry_id", "point_1000",
    }
    assert set(catalog[4]["input_schema"]["properties"]) == {"operation"}


def test_android_catalog_adds_one_strict_gesture_tool() -> None:
    catalog = action_tool_catalog(platform="androidworld")

    assert [item["name"] for item in catalog] == [
        "click", "input_text", "scroll", "navigate", "gesture"]
    schema = catalog[-1]["input_schema"]
    assert set(schema["properties"]) == {
        "operation", "target", "entry_id", "point_1000",
    }
    assert set(schema["required"]) == set(schema["properties"])
    assert set(schema["properties"]["operation"]["enum"]) == {
        "double_tap", "long_press",
    }
    assert schema["additionalProperties"] is False


def test_gesture_is_rejected_outside_android() -> None:
    with pytest.raises(ActionValidationError) as error:
        validate_action_tool_call(
            "gesture",
            _gesture_arguments(),
            latest_frame_id=LATEST_FRAME,
            platform="local_html",
        )

    assert error.value.code == "unsupported_platform"


def test_hover_is_desktop_only_and_preserves_visual_evidence_point() -> None:
    action = validate_action_tool_call(
        "hover",
        _hover_arguments(point_1000=[450, 75]),
        latest_frame_id=LATEST_FRAME,
        platform="local_html",
    )
    result = build_action_result(
        action,
        before_frame_id=LATEST_FRAME,
        after_frame_id="frame-after-hover",
    )

    assert action.operation == "hover"
    assert action.arguments == {
        "target": "Software Updates notification card",
        "point_1000": [450.0, 75.0],
    }
    assert result.to_dict()["point_1000"] == [450.0, 75.0]

    with pytest.raises(ActionValidationError) as error:
        validate_action_tool_call(
            "hover",
            _hover_arguments(),
            latest_frame_id=LATEST_FRAME,
            platform="androidworld",
        )
    assert error.value.code == "unsupported_platform"


def test_input_text_binds_exact_field_point_and_single_line_text() -> None:
    action = validate_action_tool_call(
        "input_text",
        _input_text_arguments(point_1000=[250, 750], text="Paris"),
        latest_frame_id=LATEST_FRAME,
        platform="local_html",
    )
    result = build_action_result(
        action,
        before_frame_id=LATEST_FRAME,
        after_frame_id="frame-after-query",
    )

    assert action.operation == "input_text"
    assert action.arguments == {
        "target": "City search field in Add City dialog",
        "point_1000": [250.0, 750.0],
        "text": "Paris",
    }
    assert result.to_dict()["point_1000"] == [250.0, 750.0]

    for invalid in ("", "   ", "one\ntwo", "x" * 201):
        with pytest.raises(ActionValidationError) as error:
            validate_action_tool_call(
                "input_text",
                _input_text_arguments(text=invalid),
                latest_frame_id=LATEST_FRAME,
            )
        assert error.value.code == "invalid_text"


def test_interruption_mode_exposes_bounded_recovery_strategies() -> None:
    assert set(INTERRUPTION_REVIEW_SCHEMA["properties"]["strategy"]["enum"]) == {
        "ignore", "wait", "hover", "click", "back", "unresolved",
    }
    assert "可能自行消失就 wait" in INTERRUPTION_REVIEW_PROMPT
    assert "hover 当前" in (
        INTERRUPTION_REVIEW_PROMPT)
    assert "整张通知、横幅、对话框或卡片不是其自身的关闭控件" in (
        INTERRUPTION_REVIEW_PROMPT)
    assert "click 仍会交给另一个独立 Click Reviewer 审核" in (
        INTERRUPTION_REVIEW_PROMPT)
    assert INTERRUPTION_REVIEW_SCHEMA["properties"]["reason"]["minLength"] == 1


@pytest.mark.parametrize("operation", ["long_press", "double_tap"])
def test_android_pointer_gesture_keeps_target_entry_and_point(operation) -> None:
    action = validate_action_tool_call(
        "gesture",
        _gesture_arguments(operation=operation, point_1000=[250, 750]),
        latest_frame_id=LATEST_FRAME,
        platform="android",
    )
    result = build_action_result(
        action,
        before_frame_id=LATEST_FRAME,
        after_frame_id="frame-after-gesture",
    )

    assert action.operation == operation
    assert action.arguments == {
        "target": "Alarm row",
        "entry_id": "ae9",
        "point_1000": [250.0, 750.0],
    }
    assert result.to_dict()["point_1000"] == [250.0, 750.0]


def test_android_swipe_is_rejected_in_favour_of_scroll() -> None:
    with pytest.raises(ActionValidationError) as error:
        validate_action_tool_call(
            "gesture",
            {"operation": "swipe", "direction": "LEFT"},
            latest_frame_id=LATEST_FRAME,
            platform="androidworld",
        )

    assert error.value.code == "invalid_arguments"


@pytest.mark.parametrize("arguments", [
    {"operation": "swipe"},
    {"operation": "swipe", "direction": "diagonal"},
    {"operation": "long_press", "target": "Alarm row", "entry_id": ""},
    {"operation": "tap", "direction": "down"},
])
def test_android_gesture_rejects_incomplete_or_unknown_requests(arguments) -> None:
    with pytest.raises(ActionValidationError):
        validate_action_tool_call(
            "gesture",
            arguments,
            latest_frame_id=LATEST_FRAME,
            platform="android",
        )


def test_analysis_tool_name_cannot_produce_an_action_request() -> None:
    with pytest.raises(ActionValidationError) as error:
        validate_action_tool_call(
            "inspect_region",
            {},
            latest_frame_id=LATEST_FRAME,
        )

    assert error.value.code == "not_an_action_tool"


def test_click_accepts_full_screen_boundaries_on_latest_frame() -> None:
    action = validate_action_tool_call(
        "click",
        _click_arguments(point_1000=[0, 1000]),
        latest_frame_id=LATEST_FRAME,
    )

    assert action.operation == "click"
    assert action.arguments["point_1000"] == [0.0, 1000.0]
    assert action.frame_id == LATEST_FRAME
    assert action.env_action is True


def test_action_is_bound_to_framework_current_frame_without_model_echo() -> None:
    latest = "0123456789abcdef" + "a" * 48
    action = validate_action_tool_call(
        "click",
        _click_arguments(),
        latest_frame_id=latest,
    )

    assert action.frame_id == latest


@pytest.mark.parametrize("point", [
    [-0.01, 0],
    [1000.01, 0],
    [math.nan, 0],
    [True, 0],
    [500],
])
def test_click_rejects_invalid_or_out_of_bounds_coordinates(point) -> None:
    with pytest.raises(ActionValidationError) as error:
        validate_action_tool_call(
            "click",
            _click_arguments(point_1000=point),
            latest_frame_id=LATEST_FRAME,
        )

    assert error.value.code in {
        "invalid_coordinates", "coordinates_out_of_bounds"}


def test_scroll_preserves_direct_container_hint_point_and_result() -> None:
    action = validate_action_tool_call(
        "scroll",
        _scroll_arguments(
            container_hint=" conversation   LIST viewport ",
            point_1000=[250, 700]),
        latest_frame_id=LATEST_FRAME,
    )
    result = build_action_result(
        action,
        before_frame_id=LATEST_FRAME,
        after_frame_id="frame-after-scroll",
        moved=True,
        position_hint="middle; more content below",
    )

    assert action.arguments == {
        "container_hint": "conversation LIST viewport",
        "point_1000": [250.0, 700.0],
        "direction": "down",
        "amount": 600,
    }
    assert result.to_dict() == {
        "status": "observed",
        "tool_name": "scroll",
        "operation": "scroll",
        "before_frame_id": LATEST_FRAME,
        "after_frame_id": "frame-after-scroll",
        "env_action": True,
        "container_hint": "conversation LIST viewport",
        "point_1000": [250.0, 700.0],
        "moved": True,
        "position_hint": "middle; more content below",
    }


def test_scroll_container_hint_does_not_require_a_registered_region() -> None:
    action = validate_action_tool_call(
        "scroll",
        _scroll_arguments(
            container_hint="outer page below the visible cards",
            point_1000=[500, 500],
        ),
        latest_frame_id=LATEST_FRAME,
    )

    assert action.arguments == {
        "container_hint": "outer page below the visible cards",
        "point_1000": [500.0, 500.0],
        "direction": "down",
        "amount": 600,
    }


@pytest.mark.parametrize(
    "obsolete_field",
    ["region_name", "region_scan_id", "target_region", "frame_id", "purpose"],
)
def test_scroll_rejects_fields_outside_public_contract(obsolete_field) -> None:
    arguments = _scroll_arguments()
    arguments[obsolete_field] = "obsolete"
    with pytest.raises(ActionValidationError) as error:
        validate_action_tool_call(
            "scroll",
            arguments,
            latest_frame_id=LATEST_FRAME,
        )

    assert error.value.code == "invalid_arguments"


@pytest.mark.parametrize(("updates", "code"), [
    ({"direction": "diagonal"}, "invalid_direction"),
    ({"amount": 0}, "invalid_amount"),
    ({"amount": 1001}, "invalid_amount"),
    ({"amount": True}, "invalid_amount"),
    ({"point_1000": [1001, 500]}, "coordinates_out_of_bounds"),
])
def test_scroll_rejects_invalid_parameters(updates, code) -> None:
    with pytest.raises(ActionValidationError) as error:
        validate_action_tool_call(
            "scroll",
            _scroll_arguments(**updates),
            latest_frame_id=LATEST_FRAME,
        )

    assert error.value.code == code


def test_navigate_needs_only_the_operation() -> None:
    navigate = validate_action_tool_call(
        "navigate",
        {"operation": "wait"},
        latest_frame_id=LATEST_FRAME,
    )

    assert navigate.arguments == {}


def test_scroll_result_requires_movement_fact_and_position_hint() -> None:
    action = validate_action_tool_call(
        "scroll",
        _scroll_arguments(),
        latest_frame_id=LATEST_FRAME,
    )

    with pytest.raises(ActionValidationError) as missing_moved:
        build_action_result(
            action,
            before_frame_id=LATEST_FRAME,
            after_frame_id="frame-after",
            position_hint="bottom",
        )
    assert missing_moved.value.code == "invalid_scroll_result"

    with pytest.raises(ActionValidationError) as missing_hint:
        build_action_result(
            action,
            before_frame_id=LATEST_FRAME,
            after_frame_id="frame-after",
            moved=False,
        )
    assert missing_hint.value.code == "invalid_scroll_result"


def test_navigate_allows_only_back_or_wait() -> None:
    back = validate_action_tool_call(
        "navigate",
        {"operation": "back"},
        latest_frame_id=LATEST_FRAME,
    )
    assert back.env_action is True

    with pytest.raises(ActionValidationError) as error:
        validate_action_tool_call(
            "navigate",
            {"operation": "forward"},
            latest_frame_id=LATEST_FRAME,
        )
    assert error.value.code == "invalid_navigation"


def test_wait_is_fresh_capture_request_not_environment_action() -> None:
    wait = validate_action_tool_call(
        "navigate",
        {"operation": "wait"},
        latest_frame_id=LATEST_FRAME,
    )
    result = build_action_result(
        wait,
        before_frame_id=LATEST_FRAME,
        after_frame_id=LATEST_FRAME,
    )

    assert wait.reobserve_only is True
    assert wait.env_action is False
    assert result.status == "reobserved"
    assert result.env_action is False
    assert result.before_frame_id == result.after_frame_id == LATEST_FRAME


def test_previous_tool_review_can_accompany_next_normal_action() -> None:
    action = validate_action_tool_call(
        "click",
        _click_arguments(),
        latest_frame_id=LATEST_FRAME,
        previous_tool_review={
            "decision": "accept",
            "reason": "The evidence matches the latest full screenshot",
        },
    )

    assert action.operation == "click"
    assert action.env_action is True
    assert action.previous_tool_review is not None
    assert action.previous_tool_review.decision == "accept"


def test_result_rejects_a_different_before_frame() -> None:
    action = validate_action_tool_call(
        "click",
        _click_arguments(),
        latest_frame_id=LATEST_FRAME,
    )

    with pytest.raises(ActionValidationError) as error:
        build_action_result(
            action,
            before_frame_id="frame-newer",
            after_frame_id="frame-after",
        )

    assert error.value.code == "stale_frame"
