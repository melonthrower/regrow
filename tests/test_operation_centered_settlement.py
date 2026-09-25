


from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

from gui_rewalk.src.core.explore.tasks import (
    apply_representative_probe,
    register_representative_probe,
    TaskScheduler,
)
from gui_rewalk.src.core.explore.actions import to_primitive
from gui_rewalk.src.core.explore.contracts import (
    ActionRequest,
    AgentTurn,
    CompletedElementAction,
    CompletedRegionAction,
    ElementReport,
    FunctionInfoUpdate,
    OperationReport,
    ParameterInfoUpdate,
    PageReport,
    PreviousActionReport,
    RepresentativeProbe,
    RegionReport,
    _parse_action,
    parse_turn,
)
from gui_rewalk.src.core.explore.bundle import _projected_region_names, _region_snapshot
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.inventory import apply_page_report
from gui_rewalk.src.core.explore.models import (
    ActionAttempt,
    CanonicalOperation,
    Element,
    Operation,
    Page,
    PageState,
    Region,
    RegionOccurrence,
    RegionVariant,
    Task,
)
from gui_rewalk.src.core.explore.prompts import RESPONSE_SCHEMA
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.settlement import (
    SettlementContractError,
    resolve_action_operation,
    settle_completed_actions,
)
from gui_rewalk.src.core.explore.status import (
    pending_action_record,
    semantic_exploration_focus,
)


def _ledger() -> ExplorationLedger:
    ledger = ExplorationLedger()
    ledger.pages["p1"] = Page("p1", "World", "World page", ["s1"])
    ledger.states["s1"] = PageState(
        "s1", "p1", "World empty", "World page", "screenshots/s1.png",
        ["ro1"], True, 1,
    )
    ledger.regions["r1"] = Region(
        "r1", "Top navigation", "App navigation",
        operation_ids=["o1"], occurrence_ids=["ro1"],
        variant_ids=["rv1"], canonical_operation_ids=["co1"],
        element_ids=["el1"],
    )
    ledger.region_variants["rv1"] = RegionVariant("rv1", "r1", ["ro1"], ["o1"], ["el1"])
    ledger.occurrences["ro1"] = RegionOccurrence("ro1", "r1", "s1", "Top navigation", "App navigation", "rv1")
    ledger.elements["el1"] = Element("el1", "r1", "rv1", "Alarms tab", ["o1"], ["ro1"])
    ledger.operations["o1"] = Operation(
        "o1", "r1", "click", "Alarms tab", "active",
        source_occurrence_ids=["ro1"], variant_id="rv1",
        canonical_operation_id="co1", element_id="el1",
        parameter_status="none", parameter_summary="无参数",
    )
    ledger.canonical_operations["co1"] = CanonicalOperation(
        "co1", "r1", "click", "Alarms tab", ["o1"])
    ledger.tasks["t1"] = Task("t1", "explore_operation", "active", "s1", "o1")
    ledger.attempts["a1"] = ActionAttempt(
        "a1", "t1", "s1", "operation", {
            "kind": "click", "owner_ref": "el1", "operation_ref": "o1",
            "target": "Alarms tab",
        }, "action_attempts/a1/before.png",
    )
    return ledger


def _representative_ledger() -> ExplorationLedger:
    ledger = _ledger()
    ledger.current_page_id = "p1"
    ledger.current_state_id = "s1"
    ledger.current_task_id = "t1"
    ledger.regions["r1"].element_ids.extend(["el2", "el3"])
    ledger.regions["r1"].operation_ids.extend(["o2", "o3"])
    ledger.region_variants["rv1"].element_ids.extend(["el2", "el3"])
    ledger.region_variants["rv1"].operation_ids.extend(["o2", "o3"])
    ledger.elements["el2"] = Element(
        "el2", "r1", "rv1", "1.25x", ["o2"], ["ro1"])
    ledger.elements["el3"] = Element(
        "el3", "r1", "rv1", "1.5x", ["o3"], ["ro1"])
    for operation_id, element_id, target in (
        ("o2", "el2", "1.25x playback speed"),
        ("o3", "el3", "1.5x playback speed"),
    ):
        ledger.operations[operation_id] = Operation(
            operation_id, "r1", "click", target, "pending",
            source_occurrence_ids=["ro1"], variant_id="rv1",
            canonical_operation_id="co1", element_id=element_id,
            parameter_status="observed",
            parameter_summary="播放速度枚举值",
        )
        task_id = "t" + operation_id[1:]
        ledger.tasks[task_id] = Task(
            task_id, "explore_operation", "pending", "s1", operation_id)
    ledger.canonical_operations["co1"].operation_ids.extend(["o2", "o3"])
    return ledger


def _separate_identity_representative_ledger() -> ExplorationLedger:
    ledger = _representative_ledger()
    ledger.canonical_operations["co1"].operation_ids = ["o1"]
    ledger.canonical_operations["co2"] = CanonicalOperation(
        "co2", "r1", "click", "1.25x playback speed", ["o2"])
    ledger.canonical_operations["co3"] = CanonicalOperation(
        "co3", "r1", "click", "1.5x playback speed", ["o3"])
    ledger.regions["r1"].canonical_operation_ids.extend(["co2", "co3"])
    ledger.operations["o2"].canonical_operation_id = "co2"
    ledger.operations["o3"].canonical_operation_id = "co3"
    ledger.operations["o2"].status = "recorded"
    ledger.operations["o3"].status = "recorded"
    ledger.tasks["t2"].status = "done"
    ledger.tasks["t3"].status = "done"
    return ledger


def _playback_probe() -> RepresentativeProbe:
    return RepresentativeProbe(
        operation_ref="co1",
        goal="确认播放速度选项是否采用相同的单选机制。",
        member_owner_refs=("el1", "el2", "el3"),
        representative_owner_refs=("el1", "el2"),
    )


def _registered_representative_ledger() -> ExplorationLedger:
    ledger = _representative_ledger()
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    register_representative_probe(runtime.ledger, ledger.tasks["t1"], _playback_probe())
    return ledger


def _settle_first_representative(ledger: ExplorationLedger) -> None:
    settle_completed_actions(
        ledger,
        ledger.attempts["a1"],
        PreviousActionReport(
            attempt_ref="a1",
            element_actions=(CompletedElementAction("el1", "click", True),),
            reason="0.75x 已选中；还需要第二个代表。",
        ),
    )


def _add_second_representative_attempt(ledger: ExplorationLedger) -> None:
    ledger.operations["o2"].status = "active"
    ledger.tasks["t2"].status = "active"
    ledger.current_task_id = "t2"
    ledger.attempts["a2"] = ActionAttempt(
        "a2", "t2", "s1", "operation", {
            "kind": "click", "owner_ref": "el2", "operation_ref": "o2",
            "target": "1.25x playback speed",
        }, "action_attempts/a2/before.png",
    )


def test_element_action_completion_automatically_finishes_operation_task():
    ledger = _ledger()
    report = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(CompletedElementAction("el1", "click", True),),
        region_actions=(),
        function_info=(FunctionInfoUpdate("r1", "顶部导航可切换主要功能页面。"),),
        reason="Alarms is selected and the Alarm page is visible.",
    )

    settled = settle_completed_actions(ledger, ledger.attempts["a1"], report)

    assert settled.operation_refs == ("o1",)
    assert ledger.operations["o1"].status == "verified"
    assert ledger.tasks["t1"].status == "done"
    assert ledger.regions["r1"].memory == "顶部导航可切换主要功能页面。"


def test_wrong_element_completion_cannot_finish_dispatched_operation():
    ledger = _ledger()
    report = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(CompletedElementAction("el999", "click", True),),
        region_actions=(),
        function_info=(),
        reason="A menu opened instead of Alarms.",
    )

    with pytest.raises(ValueError, match="source Variant"):
        settle_completed_actions(ledger, ledger.attempts["a1"], report)

    assert ledger.operations["o1"].status == "active"
    assert ledger.tasks["t1"].status == "active"


def test_model_contract_uses_owner_actions_not_task_results_or_route():
    previous = RESPONSE_SCHEMA["properties"]["previous_action"]["anyOf"][0]
    action = RESPONSE_SCHEMA["properties"]["action"]["anyOf"][0]

    assert set(previous["properties"]) == {
        "attempt_ref", "element_actions", "region_actions",
        "function_info", "parameter_info", "representative_same_kind", "region_effects", "reason",
    }
    assert "representative_probe" in RESPONSE_SCHEMA["properties"]
    assert "owner_ref" in action["properties"]
    assert "purpose" not in action["properties"]
    assert "operation_ref" not in action["properties"]
    assert "current_task_result" not in RESPONSE_SCHEMA["properties"]
    assert "finish" not in RESPONSE_SCHEMA["properties"]
    assert "finish" not in RESPONSE_SCHEMA["required"]


def test_new_model_contract_parses_completed_actions_and_owner_ref():
    turn = parse_turn({
        "app_scope": "target_app",
        "strategy": "切换到闹钟，并顺手记录导航功能。",
        "screen": {
            "identity": "known",
            "page_ref": "p1",
            "page_name": "Clock",
            "page_summary": "Clock main window",
            "state_ref": "s1",
            "state_name": "World clock",
            "state_summary": "World clock tab",
        },
        "previous_action": {
            "attempt_ref": "a1",
            "element_actions": [{
                "element_ref": "el1", "action": "click", "completed": True,
            }],
            "region_actions": [],
            "function_info": [{
                "region_ref": "r1", "memory": "顶部导航可切换主要功能。",
            }],
            "parameter_info": None,
            "reason": "闹钟页面已经出现。",
        },
        "page_report": None,
        "action": {
            "kind": "click",
            "owner_ref": "el1",
            "target": "Alarms tab",
            "point_1000": [500, 80],
            "text": None,
            "direction": None,
            "amount": None,
        },
        "finish": False,
        "reason": "继续探索闹钟。",
    }, has_pending_action=True, pending_attempt_id="a1")

    assert turn.previous_action.element_actions[0].element_ref == "el1"
    assert turn.action.owner_ref == "el1"
    assert turn.action.purpose == ""
    assert turn.current_task_result == ""


def test_model_can_propose_two_exact_representatives_before_acting():
    turn = parse_turn({
        "app_scope": "target_app",
        "strategy": "用两个播放速度确认这些选项采用同一单选机制。",
        "screen": {
            "identity": "known",
            "page_ref": "p1",
            "page_name": "YouTube",
            "page_summary": "Video player",
            "state_ref": "s1",
            "state_name": "Playback speed menu",
            "state_summary": "Playback speed choices are visible",
        },
        "previous_action": None,
        "representative_probe": {
            "operation_ref": "co1",
            "goal": "确认播放速度选项是否采用相同的单选机制。",
            "member_owner_refs": ["el1", "el2", "el3"],
            "representative_owner_refs": ["el1", "el2"],
        },
        "page_report": None,
        "action": {
            "kind": "click",
            "owner_ref": "el1",
            "target": "0.75x playback speed",
            "point_1000": [500, 420],
            "text": None,
            "direction": None,
            "amount": None,
        },
        "finish": False,
        "reason": "先执行第一个已声明的代表控件。",
    }, has_pending_action=False)

    assert turn.representative_probe.operation_ref == "co1"
    assert turn.representative_probe.representative_owner_refs == (
        "el1", "el2")
    assert turn.representative_probe.member_owner_refs == (
        "el1", "el2", "el3")


def test_runtime_applies_declared_probe_before_its_first_action():
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = _representative_ledger()
    proposal = _playback_probe()
    turn = AgentTurn(
        app_scope="target_app",
        strategy="先点第一个代表。",
        screen=None,
        previous_action=None,
        page_report=None,
        action=ActionRequest(
            kind="click", purpose="", target="0.75x playback speed",
            point_1000=[500, 420], text="", direction="", amount=650,
            operation_ref="", owner_ref="el1",
        ),
        current_task_result="",
        reason="先执行第一个已声明的代表控件。",
        representative_probe=proposal,
    )

    apply_representative_probe(runtime.ledger, runtime.ledger.tasks["t1"], turn)

    assert runtime.ledger.canonical_operations[
        "co1"].representative_operation_ids == ["o1", "o2"]


def test_probe_groups_new_same_region_members_before_representative_actions():
    ledger = _separate_identity_representative_ledger()
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    turn = AgentTurn(
        app_scope="target_app", strategy="先点第一个代表。", screen=None,
        previous_action=None, page_report=None,
        action=ActionRequest(
            kind="click", purpose="", target="0.75x playback speed",
            point_1000=[500, 420], text="", direction="", amount=650,
            operation_ref="", owner_ref="el1",
        ),
        current_task_result="",
        reason="两个代表用于确认所有播放速度的单选机制。",
        representative_probe=_playback_probe(),
    )

    apply_representative_probe(runtime.ledger, ledger.tasks["t1"], turn)

    identity = ledger.canonical_operations["co1"]
    assert identity.representative_operation_ids == ["o1", "o2"]
    assert identity.representative_member_operation_ids == ["o1", "o2", "o3"]
    assert ledger.operations["o2"].status == "pending"
    assert ledger.tasks["t2"].status == "pending"
    assert ledger.operations["o3"].status == "recorded"


def test_confirmed_probe_covers_members_that_started_with_separate_ids():
    ledger = _separate_identity_representative_ledger()
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    register_representative_probe(runtime.ledger, ledger.tasks["t1"], _playback_probe())
    _settle_first_representative(ledger)
    _add_second_representative_attempt(ledger)
    report = PreviousActionReport(
        attempt_ref="a2",
        element_actions=(CompletedElementAction("el2", "click", True),),
        function_info=(FunctionInfoUpdate(
            "r1",
            "播放速度为同类单选项；抽查两个值后，后选值替换先选值。",
        ),),
        representative_same_kind=True,
        reason="两个代表采用相同选择机制。",
    )

    settle_completed_actions(ledger, ledger.attempts["a2"], report)

    assert ledger.operations["o1"].status == "verified"
    assert ledger.operations["o2"].status == "verified"
    assert ledger.operations["o3"].status == "recorded"
    assert "两个代表" in ledger.operations["o3"].reason
    assert ledger.canonical_operations["co1"].representative_result == "same"


def test_first_representative_does_not_cover_the_second_or_other_members():
    ledger = _registered_representative_ledger()
    _settle_first_representative(ledger)

    assert ledger.operations["o1"].status == "verified"
    assert ledger.operations["o2"].status == "pending"
    assert ledger.operations["o3"].status == "pending"
    scheduler = TaskScheduler()
    assert scheduler.choose(ledger).task_id == "t2"
    assert scheduler.gaps(ledger)


def test_focus_and_final_pending_card_show_the_two_control_probe():
    ledger = _separate_identity_representative_ledger()
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    register_representative_probe(runtime.ledger, ledger.tasks["t1"], _playback_probe())
    ledger.operations["o1"].status = "verified"
    ledger.tasks["t1"].status = "done"
    _add_second_representative_attempt(ledger)

    focus = semantic_exploration_focus(ledger, ledger.tasks["t2"])
    pending = pending_action_record(ledger, "a2")

    assert focus["representative_probe"] == {
        "operation_ref": "co1",
        "goal": "确认播放速度选项是否采用相同的单选机制。",
        "member_owner_refs": ["el1", "el2", "el3"],
        "representative_owner_refs": ["el1", "el2"],
        "completed_owner_refs": ["el1"],
    }
    assert pending["representative_same_kind_required"] is True


def test_two_confirmed_representatives_cover_unexecuted_same_kind_members():
    ledger = _registered_representative_ledger()
    _settle_first_representative(ledger)
    _add_second_representative_attempt(ledger)
    turn = parse_turn({
        "app_scope": "target_app",
        "strategy": "记录单选结论并继续。",
        "screen": {
            "identity": "known", "page_ref": "p1", "page_name": "YouTube",
            "page_summary": "Video player", "state_ref": "s1",
            "state_name": "Playback speed menu",
            "state_summary": "1.25x is selected",
        },
        "previous_action": {
            "attempt_ref": "a2",
            "element_actions": [{
                "element_ref": "el2", "action": "click", "completed": True,
            }],
            "region_actions": [],
            "function_info": [{
                "region_ref": "r1",
                "memory": (
                    "播放速度是同类单选项；抽查 0.75x 和 1.25x，"
                    "后选值替换先选值且没有显露新功能区块。"),
            }],
            "parameter_info": None,
            "representative_same_kind": True,
            "reason": "第二个代表替换了第一个选中值，两个控件行为一致。",
        },
        "representative_probe": None,
        "page_report": None,
        "action": None,
        "finish": False,
        "reason": "代表探索完成。",
    }, has_pending_action=True, pending_attempt_id="a2")

    settle_completed_actions(
        ledger, ledger.attempts["a2"], turn.previous_action)

    assert ledger.operations["o1"].status == "verified"
    assert ledger.operations["o2"].status == "verified"
    assert ledger.operations["o3"].status == "recorded"
    assert "两个代表" in ledger.operations["o3"].reason
    assert "未执行" in ledger.operations["o3"].reason
    assert ledger.tasks["t3"].status == "done"
    assert ledger.canonical_operations["co1"].representative_result == "same"
    assert all(
        attempt.action.get("operation_ref") != "o3"
        for attempt in ledger.attempts.values())


def test_final_representative_requires_an_explicit_same_kind_result():
    ledger = _registered_representative_ledger()
    ledger.operations["o1"].status = "verified"
    ledger.tasks["t1"].status = "done"
    _add_second_representative_attempt(ledger)
    report = PreviousActionReport(
        attempt_ref="a2",
        element_actions=(CompletedElementAction("el2", "click", True),),
        reason="1.25x 已选中，但没有报告两个代表是否同类。",
    )

    with pytest.raises(
            SettlementContractError,
            match="final representative needs an explicit same-kind result"):
        settle_completed_actions(ledger, ledger.attempts["a2"], report)

    assert ledger.operations["o2"].status == "active"
    assert ledger.operations["o3"].status == "pending"


def test_different_representatives_also_require_a_region_summary():
    ledger = _registered_representative_ledger()
    ledger.operations["o1"].status = "verified"
    ledger.tasks["t1"].status = "done"
    _add_second_representative_attempt(ledger)
    report = PreviousActionReport(
        attempt_ref="a2",
        element_actions=(CompletedElementAction("el2", "click", True),),
        representative_same_kind=False,
        reason="第二个代表显露了不同功能区块。",
    )

    with pytest.raises(
            SettlementContractError,
            match="same-kind decision requires a Region function summary"):
        settle_completed_actions(ledger, ledger.attempts["a2"], report)


def test_action_contract_rejects_ambiguous_zero_to_one_coordinate_scale():
    with pytest.raises(ValueError, match="ambiguous 0..1 coordinate scale"):
        _parse_action({
            "kind": "click",
            "owner_ref": "el1",
            "target": "Clear search",
            "point_1000": [0.941, 0.082],
            "text": None,
            "direction": None,
            "amount": None,
        })


def test_android_input_text_primitive_replaces_existing_text():
    image = Image.new("RGB", (100, 200), "white")
    screenshot = BytesIO()
    image.save(screenshot, format="PNG")
    action = ActionRequest(
        kind="input_text", purpose="execute", target="Hotspot name",
        point_1000=[500, 500], text="AndroidAP_Test", direction="",
        amount=650, operation_ref="o1", owner_ref="el1",
    )

    primitive = to_primitive(
        action, screenshot=screenshot.getvalue(), platform="Android")

    assert primitive == {
        "action_type": "input_text",
        "x": 50,
        "y": 100,
        "text": "AndroidAP_Test",
        "clear_text": True,
    }


def test_region_action_maps_by_current_variant_and_direction():
    ledger = _ledger()
    ledger.regions["r1"].operation_ids.append("o2")
    ledger.region_variants["rv1"].operation_ids.append("o2")
    ledger.operations["o2"] = Operation(
        "o2", "r1", "scroll", "Alarm list", "pending",
        source_occurrence_ids=["ro1"], variant_id="rv1",
        canonical_operation_id="co2", scope="region", direction="down",
        parameter_status="observed", parameter_summary="direction=down",
    )

    assert resolve_action_operation(
        ledger, state_id="s1", owner_ref="r1", action="scroll",
        direction="down",
    ) == "o2"

    report = PreviousActionReport(
        attempt_ref="a1",
        region_actions=(CompletedRegionAction("r1", "scroll", True, "down"),),
        reason="列表向下滚动并显示新内容。",
    )
    ledger.attempts["a1"].action = {
        "kind": "scroll", "direction": "down", "owner_ref": "r1",
        "operation_ref": "o2",
    }
    settled = settle_completed_actions(ledger, ledger.attempts["a1"], report)
    assert settled.operation_refs == ("o2",)


@pytest.mark.parametrize(
    ("changed", "expected_outcome", "expected_operation_status"),
    [(False, "no_effect", "pending"), (True, "success", "verified")],
)
def test_framework_only_vetoes_region_scroll_when_decoded_pixels_are_identical(
    changed, expected_outcome, expected_operation_status,
):
    class _Artifacts:
        @staticmethod
        def save_attempt_after(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/after.png"

    ledger = _ledger()
    ledger.regions["r1"].operation_ids.append("o2")
    ledger.region_variants["rv1"].operation_ids.append("o2")
    ledger.operations["o2"] = Operation(
        "o2", "r1", "scroll", "Alarm list", "pending",
        source_occurrence_ids=["ro1"], variant_id="rv1",
        canonical_operation_id="co2", scope="region", direction="down",
        parameter_status="observed", parameter_summary="direction=down",
    )
    ledger.canonical_operations["co2"] = CanonicalOperation(
        "co2", "r1", "scroll", "Alarm list", ["o2"],
        scope="region", direction="down",
    )
    ledger.tasks["t1"] = Task("t1", "survey_page", "active", "s1")
    ledger.attempts["a1"] = ActionAttempt(
        "a1", "t1", "s1", "survey", {
            "kind": "scroll", "direction": "down", "target": "Alarm list",
            "owner_ref": "r1", "operation_ref": "o2",
        }, "action_attempts/a1/before.png",
    )
    ledger.current_page_id = "p1"
    ledger.current_state_id = "s1"
    ledger.current_task_id = "t1"
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()
    runtime.artifacts = _Artifacts()
    runtime.pending_attempt_id = "a1"
    from io import BytesIO
    from PIL import Image
    image = Image.new('RGB', (120, 80), 'white')
    first = BytesIO(); image.save(first, format='PNG', compress_level=0)
    if changed:
        image.putpixel((0, 0), (254, 255, 255))  # one pixel, outside old cropped threshold
    second = BytesIO(); image.save(second, format='PNG', compress_level=9)
    runtime.pending_before = first.getvalue()
    runtime.state_identity_rechecks = set()
    runtime._reconcile_verified_operation_reuse = lambda _operation_ref: None
    report = PreviousActionReport(
        attempt_ref="a1",
        region_actions=(CompletedRegionAction("r1", "scroll", True, "down"),),
        reason=(
            "本次滚动没有产生位移；列表仍有截断，后续可调整落点重试。"
        ),
    )
    turn = AgentTurn(
        app_scope="target_app", strategy="调整落点后继续调查", screen=None,
        previous_action=report, page_report=None, action=None,
        current_task_result="", reason=report.reason,
    )

    runtime._settle_pending(
        turn, screenshot=second.getvalue(), frame_ref="screenshots/after.png")

    assert ledger.attempts["a1"].outcome == expected_outcome
    assert ledger.operations["o2"].status == expected_operation_status
    assert ledger.tasks["t1"].status == "active"
    assert runtime.pending_attempt_id == ""


def test_function_info_can_update_a_known_region_visible_after_the_action():
    ledger = _ledger()
    ledger.pages["p1"].state_ids.append("s2")
    ledger.states["s2"] = PageState(
        "s2", "p1", "Alarm page", "Alarm content is visible",
        "screenshots/s2.png", ["ro2"], True, 1,
    )
    ledger.regions["r2"] = Region(
        "r2", "Alarm content", "Alarm list", occurrence_ids=["ro2"])
    ledger.occurrences["ro2"] = RegionOccurrence(
        "ro2", "r2", "s2", "Alarm content", "Alarm list")
    ledger.current_state_id = "s2"
    report = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(CompletedElementAction("el1", "click", True),),
        function_info=(FunctionInfoUpdate(
            "r2", "动作后重新可见的闹钟内容区。"),),
        reason="Alarms 页面已经出现。",
    )

    settle_completed_actions(ledger, ledger.attempts["a1"], report)

    assert ledger.regions["r2"].memory == "动作后重新可见的闹钟内容区。"


def test_invalid_optional_notes_do_not_block_valid_owner_settlement():
    ledger = _ledger()
    ledger.regions["r-other"] = Region("r-other", "Other page", "Not visible", memory="Keep this.")
    report = PreviousActionReport(
        attempt_ref="a1", element_actions=(CompletedElementAction("el1", "click", True),),
        function_info=(FunctionInfoUpdate("r1", "Useful source observation."),
                       FunctionInfoUpdate("r-other", "Wrong target."),
                       FunctionInfoUpdate("r-missing", "Invented reference.")),
        reason="The destination is visible.")
    result = settle_completed_actions(ledger, ledger.attempts["a1"], report)
    assert result.operation_refs == ("o1",)
    assert ledger.operations["o1"].status == "verified"
    assert ledger.regions["r1"].memory == "Useful source observation."
    assert ledger.regions["r-other"].memory == "Keep this."
    assert "r-missing" not in ledger.regions
    rejected = [e for e in ledger.events if e["kind"] == "function_note_rejected"]
    assert [e["payload"]["region_ref"] for e in rejected] == ["r-other", "r-missing"]


def test_optional_note_rejection_does_not_bypass_owner_validation():
    ledger = _ledger()
    report = PreviousActionReport(
        attempt_ref="a1", element_actions=(CompletedElementAction("el-bad", "click", True),),
        function_info=(FunctionInfoUpdate("r-missing", "Wrong note."),), reason="Claim.")
    with pytest.raises(SettlementContractError):
        settle_completed_actions(ledger, ledger.attempts["a1"], report)
    assert ledger.operations["o1"].status == "active"
    assert not any(e["kind"] == "function_note_rejected" for e in ledger.events)


@pytest.mark.parametrize("old_status,new_status", [("none", "observed"), ("observed", "none")])
def test_unrequested_parameter_info_does_not_block_or_relabel_an_owner(old_status, new_status):
    ledger = _ledger()
    ledger.operations["o1"].parameter_status = old_status
    report = PreviousActionReport(
        attempt_ref="a1", element_actions=(CompletedElementAction("el1", "click", True),),
        parameter_info=ParameterInfoUpdate(new_status, "Latest observed parameter description."),
        reason="The actual owner effect is visible.")
    settle_completed_actions(ledger, ledger.attempts["a1"], report)
    assert ledger.operations["o1"].parameter_status == old_status
    assert ledger.operations["o1"].status == "verified"
    assert any(e["kind"] == "parameter_info_ignored_not_requested" for e in ledger.events)


def test_settlement_error_identifies_invalid_owner_field():
    ledger = _ledger()
    report = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(CompletedElementAction("el999", "click", True),),
        reason="错误 owner。",
    )

    with pytest.raises(SettlementContractError) as caught:
        settle_completed_actions(ledger, ledger.attempts["a1"], report)

    error = caught.value
    assert error.code == "UNKNOWN_OWNER"
    assert error.field_path == "previous_action.element_actions[0].element_ref"
    assert error.expected == "known Element or Region in the current source Variant"
    assert error.received == "el999"


def test_settlement_error_identifies_primitive_mismatch():
    ledger = _ledger()
    report = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(
            CompletedElementAction("el1", "input_text", True),),
        reason="错误 primitive。",
    )

    with pytest.raises(SettlementContractError) as caught:
        settle_completed_actions(ledger, ledger.attempts["a1"], report)

    error = caught.value
    assert error.code == "COMPLETED_PRIMITIVE_MISMATCH"
    assert error.field_path == "previous_action.element_actions[0].action"
    assert error.expected == "click"
    assert error.received == "input_text"


def test_settlement_error_identifies_parameter_without_completed_owner():
    ledger = _ledger()
    report = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(CompletedElementAction("el1", "click", False),),
        parameter_info=ParameterInfoUpdate("observed", "显示 5 minutes"),
        reason="没有完成 owner。",
    )

    with pytest.raises(SettlementContractError) as caught:
        settle_completed_actions(ledger, ledger.attempts["a1"], report)

    error = caught.value
    assert error.code == "PARAMETER_WITHOUT_COMPLETED_OWNER"
    assert error.field_path == "previous_action.parameter_info"
    assert error.expected == "exactly one completed owner"
    assert error.received == "0 completed owners"


def _runtime_for_pending_report_budget(monkeypatch):
    class _Artifacts:
        @staticmethod
        def save_attempt_after(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/after.png"

    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = _ledger()
    runtime.ledger.current_page_id = "p1"
    runtime.ledger.current_state_id = "s1"
    runtime.ledger.current_task_id = "t1"
    runtime.scheduler = TaskScheduler()
    runtime.artifacts = _Artifacts()
    runtime.pending_attempt_id = "a1"
    runtime.pending_before = b"before"
    runtime.pending_action_error = ""
    runtime.pending_report_correction = {}
    runtime.state_identity_rechecks = set()
    runtime.restart_recovery_task_id = ""
    runtime.restarted_recovery_task_ids = set()
    runtime.actions_used = 1
    runtime.app_name = "clock"
    runtime.platform = "desktop"
    runtime.last_context_task_id = None
    runtime.rejection_task_id = ""
    runtime.rejection_issue = ""
    runtime.rejection_streak = 0
    runtime.correction = ""
    runtime._reconcile_verified_operation_reuse = lambda _operation_ref: None
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.runtime.visible_change_ratio",
        lambda *_args: 0.0,
    )
    return runtime


def test_first_pending_report_error_returns_precise_correction_card(monkeypatch):
    runtime = _runtime_for_pending_report_budget(monkeypatch)
    report = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(CompletedElementAction("el999", "click", True),),
        reason="错误 owner。",
    )
    turn = AgentTurn(
        app_scope="target_app", strategy="只修正报告", screen=None,
        previous_action=report, page_report=None, action=None,
        current_task_result="", reason=report.reason,
    )
    error = SettlementContractError(
        code="UNKNOWN_OWNER",
        field_path="owner_ref",
        expected="known owner in source Variant",
        received="el999",
        message="unknown owner el999 in current source Variant",
    )

    exhausted = runtime._handle_pending_report_rejection(
        turn=turn,
        task=runtime.ledger.tasks["t1"],
        error=error,
        screenshot=b"after",
        frame_ref="screenshots/after.png",
    )

    assert exhausted is False
    assert runtime.pending_attempt_id == "a1"
    assert runtime.actions_used == 1
    assert len(runtime.ledger.attempts) == 1
    assert runtime.pending_report_correction == {
        "pending_attempt_ref": "a1",
        "error_code": "UNKNOWN_OWNER",
        "field_path": "owner_ref",
        "expected": "known owner in source Variant",
        "received": "el999",
        "accepted_facts": [
            "attempt_ref=a1",
            "GUI action already executed",
            "the real action and before screenshot are retained; after is the current observation",
        ],
        "required_change": (
            "修正 owner_ref；若分区或状态相关，同步修正 screen/page_report/previous_action.region_effects"
            f"\n本轮具体反馈（仅用于修正当前报告，不改变动作与安全合同）：{error}"),
        "forbidden": [
            "action must be null",
            "do not repeat the GUI action",
        ],
        "correction_count": 1,
        "correction_limit": 3,
    }
    context = runtime._context(runtime.ledger.tasks["t1"], "target")
    assert context["合同纠正卡"] == runtime.pending_report_correction


def test_third_pending_report_error_releases_attempt_without_new_action(
    monkeypatch,
):
    runtime = _runtime_for_pending_report_budget(monkeypatch)
    report = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(CompletedElementAction("el999", "click", True),),
        reason="仍然是错误 owner。",
    )
    turn = AgentTurn(
        app_scope="target_app", strategy="只修正报告", screen=None,
        previous_action=report, page_report=None, action=None,
        current_task_result="", reason=report.reason,
    )
    error = SettlementContractError(
        code="UNKNOWN_OWNER",
        field_path="owner_ref",
        expected="known owner in source Variant",
        received="el999",
        message="unknown owner el999 in current source Variant",
    )
    runtime._handle_pending_report_rejection(
        turn=turn, task=runtime.ledger.tasks["t1"], error=error,
        screenshot=b"after", frame_ref="screenshots/after.png")
    runtime._handle_pending_report_rejection(
        turn=turn, task=runtime.ledger.tasks["t1"], error=error,
        screenshot=b"after", frame_ref="screenshots/after.png")

    exhausted = runtime._handle_pending_report_rejection(
        turn=turn,
        task=runtime.ledger.tasks["t1"],
        error=error,
        screenshot=b"after",
        frame_ref="screenshots/after.png",
    )

    assert exhausted is True
    assert runtime.pending_attempt_id == ""
    assert runtime.actions_used == 1
    assert len(runtime.ledger.attempts) == 1
    assert runtime.ledger.attempts["a1"].outcome == "uncertain"
    assert runtime.ledger.operations["o1"].status == "failed"
    assert runtime.ledger.tasks["t1"].status == "failed"
    assert runtime.pending_report_correction == {}
    assert any(
        item["kind"] == "pending_report_correction_budget_exhausted"
        for item in runtime.ledger.events
    )


def test_corrected_second_report_settles_without_forced_failure(monkeypatch):
    runtime = _runtime_for_pending_report_budget(monkeypatch)
    bad_report = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(CompletedElementAction("el999", "click", True),),
        reason="错误 owner。",
    )
    bad_turn = AgentTurn(
        app_scope="target_app", strategy="只修正报告", screen=None,
        previous_action=bad_report, page_report=None, action=None,
        current_task_result="", reason=bad_report.reason,
    )
    error = SettlementContractError(
        code="UNKNOWN_OWNER", field_path="owner_ref",
        expected="known owner in source Variant", received="el999",
        message="unknown owner el999 in current source Variant",
    )
    runtime._handle_pending_report_rejection(
        turn=bad_turn, task=runtime.ledger.tasks["t1"], error=error,
        screenshot=b"after", frame_ref="screenshots/after.png")
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.runtime.visible_change_ratio",
        lambda *_args: 0.01,
    )
    corrected = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(CompletedElementAction("el1", "click", True),),
        reason="Alarms 页面已经出现。",
    )
    corrected_turn = AgentTurn(
        app_scope="target_app", strategy="报告已修正", screen=None,
        previous_action=corrected, page_report=None, action=None,
        current_task_result="", reason=corrected.reason,
    )

    runtime._settle_pending(
        corrected_turn,
        screenshot=b"after",
        frame_ref="screenshots/after.png",
    )

    assert runtime.ledger.operations["o1"].status == "verified"
    assert runtime.ledger.tasks["t1"].status == "done"
    assert runtime.pending_attempt_id == ""
    assert runtime.pending_report_correction == {}


def test_agent_schema_exhaustion_releases_pending_without_runtime_retry(
    monkeypatch,
):
    runtime = _runtime_for_pending_report_budget(monkeypatch)

    for _ in range(2):
        runtime._handle_agent_decide_failure(
            task=runtime.ledger.tasks["t1"], error=ValueError("previous_action.element_actions is invalid"),
            screenshot=b"after", frame_ref="screenshots/after.png")
    handled = runtime._handle_agent_decide_failure(
        task=runtime.ledger.tasks["t1"],
        error=ValueError("previous_action.element_actions is invalid"),
        screenshot=b"after",
        frame_ref="screenshots/after.png",
    )

    assert handled is True
    assert runtime.pending_attempt_id == ""
    assert runtime.actions_used == 1
    assert len(runtime.ledger.attempts) == 1
    assert runtime.ledger.operations["o1"].status == "failed"
    exhausted = [
        item for item in runtime.ledger.events
        if item["kind"] == "pending_report_correction_budget_exhausted"
    ]
    assert exhausted[-1]["payload"]["error_code"] == (
        "UNMAPPED_REPORT_CONTRACT_ERROR")


def test_identical_frame_click_is_no_effect_even_when_model_marks_owner_completed(
    monkeypatch,
):
    class _Artifacts:
        @staticmethod
        def save_attempt_after(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/after.png"

    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = _ledger()
    runtime.ledger.current_page_id = "p1"
    runtime.ledger.current_state_id = "s1"
    runtime.ledger.current_task_id = "t1"
    runtime.scheduler = TaskScheduler()
    runtime.artifacts = _Artifacts()
    runtime.pending_attempt_id = "a1"
    from .explore_fixtures import _png
    runtime.pending_before = _png("white")
    runtime.state_identity_rechecks = set()
    runtime.restart_recovery_task_id = ""
    runtime.restarted_recovery_task_ids = set()
    runtime._reconcile_verified_operation_reuse = lambda _operation_ref: None
    report = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(CompletedElementAction("el1", "click", True),),
        reason="点击后界面完全没有变化。",
    )
    turn = AgentTurn(
        app_scope="target_app", strategy="换一个可靠落点重试", screen=None,
        previous_action=report, page_report=None, action=None,
        current_task_result="", reason=report.reason,
    )

    runtime._settle_pending(
        turn, screenshot=runtime.pending_before, frame_ref="screenshots/after.png")

    assert runtime.ledger.attempts["a1"].outcome == "no_effect"
    assert runtime.ledger.operations["o1"].status == "active"
    assert runtime.ledger.tasks["t1"].status == "active"
    assert runtime.pending_attempt_id == ""


def test_unbound_parameter_info_is_ignored_when_owner_is_not_completed(
    monkeypatch,
):
    class _Artifacts:
        @staticmethod
        def save_attempt_after(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/after.png"

    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = _ledger()
    operation = runtime.ledger.operations["o1"]
    operation.parameter_status = "unknown"
    operation.parameter_summary = "完整值域尚未观察"
    runtime.ledger.current_page_id = "p1"
    runtime.ledger.current_state_id = "s1"
    runtime.ledger.current_task_id = "t1"
    runtime.scheduler = TaskScheduler()
    runtime.artifacts = _Artifacts()
    runtime.pending_attempt_id = "a1"
    runtime.pending_before = b"before"
    runtime.state_identity_rechecks = set()
    runtime.restart_recovery_task_id = ""
    runtime.restarted_recovery_task_ids = set()
    runtime._reconcile_verified_operation_reuse = lambda _operation_ref: None
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.runtime.visible_change_ratio",
        lambda *_args: 0.001,
    )
    report = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(CompletedElementAction("el1", "click", False),),
        parameter_info=ParameterInfoUpdate(
            "observed", "当前仍只看见 5 minutes，值域未展开"),
        reason="参数入口点击后没有展开。",
    )
    turn = AgentTurn(
        app_scope="target_app", strategy="使用新截图重新定位", screen=None,
        previous_action=report, page_report=None, action=None,
        current_task_result="", reason=report.reason,
    )

    runtime._settle_pending(
        turn, screenshot=b"after", frame_ref="screenshots/after.png")

    assert runtime.ledger.attempts["a1"].outcome == "uncertain"
    assert operation.status == "active"
    assert operation.parameter_status == "unknown"
    assert runtime.pending_attempt_id == ""
    assert any(
        item["kind"] == "parameter_info_ignored_without_completed_owner"
        for item in runtime.ledger.events
    )


def test_second_no_effect_execute_attempt_closes_operation_as_failed_gap():
    ledger = _ledger()
    ledger.attempts["a1"].purpose = "execute"
    ledger.attempts["a1"].outcome = "no_effect"
    ledger.attempts["a2"] = ActionAttempt(
        "a2", "t1", "s1", "execute", {
            "kind": "click", "owner_ref": "el1", "operation_ref": "o1",
            "target": "Alarms tab", "point_1000": [620, 80],
        }, "action_attempts/a2/before.png", outcome="no_effect",
    )
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()

    exhausted = runtime._fail_repeated_no_effect_operation(
        ledger.tasks["t1"])

    assert exhausted is True
    assert ledger.tasks["t1"].status == "failed"
    assert ledger.operations["o1"].status == "failed"
    assert "fresh-frame" in ledger.tasks["t1"].reason


def test_android_input_delivery_error_overrides_completed_owner(monkeypatch):
    class _Artifacts:
        @staticmethod
        def save_attempt_after(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/after.png"

    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = _ledger()
    runtime.ledger.operations["o1"].action = "input_text"
    runtime.ledger.attempts["a1"].purpose = "execute"
    runtime.ledger.attempts["a1"].action.update({
        "kind": "input_text", "text": "8:30 AM 闹钟标签文本",
    })
    runtime.ledger.current_page_id = "p1"
    runtime.ledger.current_state_id = "s1"
    runtime.ledger.current_task_id = "t1"
    runtime.scheduler = TaskScheduler()
    runtime.artifacts = _Artifacts()
    runtime.pending_attempt_id = "a1"
    runtime.pending_before = b"before"
    runtime.pending_action_error = "input_text_unsupported_non_ascii"
    runtime.state_identity_rechecks = set()
    runtime.restart_recovery_task_id = ""
    runtime.restarted_recovery_task_ids = set()
    runtime._reconcile_verified_operation_reuse = lambda _operation_ref: None
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.runtime.visible_change_ratio",
        lambda *_args: 0.2,
    )
    report = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(CompletedElementAction("el1", "input_text", True),),
        reason="输入框只显示了部分文本。",
    )
    turn = AgentTurn(
        app_scope="target_app", strategy="改用 ASCII 代表文本", screen=None,
        previous_action=report, page_report=None, action=None,
        current_task_result="", reason=report.reason,
    )

    runtime._settle_pending(
        turn, screenshot=b"after", frame_ref="screenshots/after.png")

    assert runtime.ledger.attempts["a1"].outcome == "no_effect"
    assert runtime.ledger.operations["o1"].status == "active"
    assert runtime.ledger.tasks["t1"].status == "active"
    assert any(
        event["kind"] == "action_delivery_error_overrode_completion"
        for event in runtime.ledger.events)


def test_successful_survey_scroll_to_new_state_records_transition(monkeypatch):
    class _Artifacts:
        @staticmethod
        def save_attempt_after(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/after.png"

    ledger = _ledger()
    ledger.states["s2"] = PageState(
        "s2", "p1", "World lower viewport", "More rows", "screenshots/s2.png")
    ledger.pages["p1"].state_ids.append("s2")
    ledger.regions["r1"].operation_ids.append("o2")
    ledger.region_variants["rv1"].operation_ids.append("o2")
    ledger.operations["o2"] = Operation(
        "o2", "r1", "scroll", "World list", "pending",
        source_occurrence_ids=["ro1"], variant_id="rv1",
        canonical_operation_id="co2", scope="region", direction="down",
        parameter_status="observed", parameter_summary="direction=down",
    )
    ledger.canonical_operations["co2"] = CanonicalOperation(
        "co2", "r1", "scroll", "World list", ["o2"],
        scope="region", direction="down",
    )
    ledger.tasks["t1"] = Task("t1", "survey_page", "active", "s1")
    ledger.attempts["a1"] = ActionAttempt(
        "a1", "t1", "s1", "survey", {
            "kind": "scroll", "direction": "down", "target": "World list",
        }, "action_attempts/a1/before.png",
    )
    ledger.current_page_id = "p1"
    ledger.current_state_id = "s2"
    ledger.current_task_id = "t1"
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()
    runtime.artifacts = _Artifacts()
    runtime.pending_attempt_id = "a1"
    runtime.pending_before = b"before"
    runtime.state_identity_rechecks = set()
    runtime._reconcile_verified_operation_reuse = lambda _operation_ref: None
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.runtime.visible_change_ratio",
        lambda *_args: 0.1,
    )
    report = PreviousActionReport(
        attempt_ref="a1",
        region_actions=(CompletedRegionAction("r1", "scroll", True, "down"),),
        reason="列表滚动并显示新的行。",
    )
    turn = AgentTurn(
        app_scope="target_app", strategy="清点新内容", screen=None,
        previous_action=report, page_report=None, action=None,
        current_task_result="", reason=report.reason,
    )

    runtime._settle_pending(
        turn, screenshot=b"after", frame_ref="screenshots/after.png")

    assert ledger.attempts["a1"].outcome == "success"
    assert [(edge.source_state_id, edge.target_state_id, edge.attempt_id)
            for edge in ledger.transitions] == [("s1", "s2", "a1")]


def test_semantic_focus_projects_region_memory_without_a_second_graph():
    ledger = _ledger()
    ledger.current_page_id = "p1"
    ledger.current_state_id = "s1"
    ledger.regions["r1"].memory = "顶部导航可切换 World、Alarm、Timer。"

    focus = semantic_exploration_focus(ledger, ledger.tasks["t1"])

    assert focus["path"] == ["World", "Top navigation", "Alarms tab"]
    assert focus["region_memories"] == [{
        "region_ref": "r1",
        "name": "Top navigation",
        "memory": "顶部导航可切换 World、Alarm、Timer。",
    }]
    assert "operation_ref" not in focus


def test_runtime_binds_model_owner_to_framework_operation():
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = _ledger()
    runtime.ledger.current_page_id = "p1"
    runtime.ledger.current_state_id = "s1"
    action = ActionRequest(
        kind="click", purpose="", target="Alarms tab",
        point_1000=[500, 80], text="", direction="", amount=650,
        operation_ref="", owner_ref="el1",
    )

    bound = runtime._bind_action(runtime.ledger.tasks["t1"], action)

    assert bound.purpose == "execute"
    assert bound.operation_ref == "o1"
    assert bound.owner_ref == "el1"


def test_runtime_derives_task_settlement_from_completed_owner_action():
    class _Artifacts:
        @staticmethod
        def save_attempt_after(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/after.png"

    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = _ledger()
    runtime.ledger.current_page_id = "p1"
    runtime.ledger.current_state_id = "s1"
    runtime.ledger.current_task_id = "t1"
    runtime.scheduler = TaskScheduler()
    runtime.artifacts = _Artifacts()
    runtime.pending_attempt_id = "a1"
    runtime.pending_before = b"not-an-image"
    runtime.state_identity_rechecks = set()
    runtime._reconcile_verified_operation_reuse = lambda _operation_ref: None
    report = PreviousActionReport(
        attempt_ref="a1",
        element_actions=(CompletedElementAction("el1", "click", True),),
        reason="Alarms 页面已经出现。",
    )
    turn = AgentTurn(
        app_scope="target_app", strategy="继续探索 Alarms", screen=None,
        previous_action=report, page_report=None, action=None,
        current_task_result="", reason=report.reason,
    )

    runtime._settle_pending(
        turn, screenshot=b"not-an-image", frame_ref="screenshots/after.png")

    assert runtime.ledger.attempts["a1"].outcome == "success"
    assert runtime.ledger.operations["o1"].status == "verified"
    assert runtime.ledger.tasks["t1"].status == "done"
    assert runtime.pending_attempt_id == ""


def test_formal_region_projection_keeps_natural_language_memory():
    ledger = _ledger()
    ledger.regions["r1"].memory = "顶部导航可进入 Alarm，并可继续探索编辑器。"

    snapshot = _region_snapshot(ledger, _projected_region_names(ledger))

    assert snapshot["region_groups"]["groups"][0]["memory"] == (
        "顶部导航可进入 Alarm，并可继续探索编辑器。"
    )


def test_inventory_rejects_parameter_values_as_duplicate_owner_actions():
    ledger = _ledger()
    report = PageReport(regions=(RegionReport(
        name="Top navigation",
        summary="App navigation",
        memory="导航可选择主要页面。",
        elements=(ElementReport("Alarms tab", operations=(
            OperationReport("click", "Alarms value 1", "explore", "代表值"),
            OperationReport("click", "Alarms value 2", "explore", "重复值"),
        )),),
        region_operations=(),
    ),), survey_complete=True, coverage_note="完整")

    result = apply_page_report(ledger, state_id="s1", report=report)

    assert result.ok is False
    assert "同一 owner/action" in result.issue


def test_opportunistic_owner_completion_keeps_current_focus_task_active():
    class _Artifacts:
        @staticmethod
        def save_attempt_after(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/after.png"

    ledger = _ledger()
    ledger.elements["el2"] = Element(
        "el2", "r1", "rv1", "Timer tab", ["o2"], ["ro1"])
    ledger.regions["r1"].element_ids.append("el2")
    ledger.region_variants["rv1"].element_ids.append("el2")
    ledger.regions["r1"].operation_ids.append("o2")
    ledger.region_variants["rv1"].operation_ids.append("o2")
    ledger.operations["o2"] = Operation(
        "o2", "r1", "click", "Timer tab", "pending",
        source_occurrence_ids=["ro1"], variant_id="rv1",
        canonical_operation_id="co2", element_id="el2",
        parameter_status="none", parameter_summary="无参数",
    )
    ledger.canonical_operations["co2"] = CanonicalOperation(
        "co2", "r1", "click", "Timer tab", ["o2"])
    ledger.tasks["t2"] = Task(
        "t2", "explore_operation", "pending", "s1", "o2")
    ledger.attempts["a2"] = ActionAttempt(
        "a2", "t1", "s1", "execute",
        {"kind": "click", "owner_ref": "el2", "operation_ref": "o2"},
        "action_attempts/a2/before.png",
    )
    ledger.current_task_id = "t1"
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()
    runtime.artifacts = _Artifacts()
    runtime.pending_attempt_id = "a2"
    runtime.pending_before = b"not-an-image"
    runtime.state_identity_rechecks = set()
    runtime._reconcile_verified_operation_reuse = lambda _operation_ref: None
    turn = AgentTurn(
        app_scope="target_app", strategy="顺手进入 Timer", screen=None,
        previous_action=PreviousActionReport(
            attempt_ref="a2",
            element_actions=(CompletedElementAction("el2", "click", True),),
            reason="Timer 页面已经出现。",
        ),
        page_report=None, action=None, current_task_result="",
        reason="Timer 页面已经出现。",
    )

    runtime._settle_pending(
        turn, screenshot=b"not-an-image", frame_ref="screenshots/after.png")

    assert ledger.tasks["t2"].status == "done"
    assert ledger.tasks["t1"].status == "active"
    assert ledger.current_task_id == "t1"


def _same_page_duplicate_element_runtime(*, target):
    class _Artifacts:
        @staticmethod
        def save_attempt_after(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/after.png"

    ledger = _ledger()
    ledger.operations["o1"].target = target
    ledger.operations["o1"].status = "active"
    ledger.operations["o1"].parameter_status = "none"
    ledger.operations["o1"].parameter_summary = "无参数"
    ledger.elements["el1"].name = target
    ledger.canonical_operations["co1"].target = target
    ledger.states["s2"] = PageState(
        "s2", "p1", "Search state", "Search", "screenshots/s2.png",
        region_occurrence_ids=["ro2"], survey_complete=True,
        inventory_passes=1,
    )
    ledger.pages["p1"].state_ids.append("s2")
    ledger.regions["r2"] = Region(
        "r2", "Search toolbar", "Search toolbar variant",
        occurrence_ids=["ro2"], canonical_operation_ids=["co2"],
        operation_ids=["o2"], element_ids=["el2"],
    )
    ledger.region_variants["rv2"] = RegionVariant(
        "rv2", "r2", ["ro2"], ["o2"], ["el2"])
    ledger.occurrences["ro2"] = RegionOccurrence(
        "ro2", "r2", "s2", "Search toolbar", "Search", "rv2")
    ledger.elements["el2"] = Element(
        "el2", "r2", "rv2", target, ["o2"], ["ro2"])
    ledger.operations["o2"] = Operation(
        "o2", "r2", "click", target, "active",
        source_occurrence_ids=["ro2"], variant_id="rv2",
        canonical_operation_id="co2", element_id="el2",
        parameter_status="none", parameter_summary="无参数",
    )
    ledger.canonical_operations["co2"] = CanonicalOperation(
        "co2", "r2", "click", target, ["o2"])
    ledger.tasks["t2"] = Task(
        "t2", "explore_operation", "active", "s2", "o2")
    ledger.attempts["a2"] = ActionAttempt(
        "a2", "t1", "s2", "execute",
        {"kind": "click", "owner_ref": "el2", "operation_ref": "o2"},
        "action_attempts/a2/before.png",
    )
    ledger.current_page_id = "p1"
    ledger.current_state_id = "s2"
    ledger.current_task_id = "t1"
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()
    runtime.artifacts = _Artifacts()
    runtime.pending_attempt_id = "a2"
    runtime.pending_before = b"not-an-image"
    runtime.state_identity_rechecks = set()
    runtime.restart_recovery_task_id = ""
    runtime.restarted_recovery_task_ids = set()
    runtime._reconcile_verified_operation_reuse = lambda _operation_ref: None
    report = PreviousActionReport(
        attempt_ref="a2",
        element_actions=(CompletedElementAction("el2", "click", True),),
        reason="同一 Page 的第二个工具栏设置按钮到达同一设置功能。",
    )
    turn = AgentTurn(
        app_scope="target_app", strategy="结算设置按钮", screen=None,
        previous_action=report, page_report=None, action=None,
        current_task_result="", reason=report.reason,
    )
    return runtime, turn


@pytest.mark.parametrize("target", ["日历设置", "保存"])
def test_same_page_text_match_does_not_settle_unreviewed_operation_identity(
        target):
    runtime, turn = _same_page_duplicate_element_runtime(target=target)

    runtime._settle_pending(
        turn, screenshot=b"not-an-image", frame_ref="screenshots/after.png")

    assert runtime.ledger.tasks["t2"].status == "done"
    assert runtime.ledger.tasks["t1"].status == "active"
    assert runtime.ledger.operations["o1"].status == "active"
    assert not any(
        item["kind"] == "same_page_exact_element_operation_satisfied"
        for item in runtime.ledger.events)


def test_survey_return_can_use_and_complete_a_registered_navigation_owner():
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = _ledger()
    runtime.platform = "desktop"
    runtime.ledger.states["s2"] = PageState(
        "s2", "p1", "Alarm editor", "Editor", "screenshots/s2.png")
    runtime.ledger.pages["p1"].state_ids.append("s2")
    survey = Task("ts", "survey_page", "active", state_id="s2")
    runtime.ledger.tasks["ts"] = survey
    runtime.ledger.current_page_id = "p1"
    runtime.ledger.current_state_id = "s1"
    action = ActionRequest(
        kind="click", purpose="", target="Alarms tab",
        point_1000=[500, 80], text="", direction="", amount=650,
        operation_ref="", owner_ref="el1",
    )

    bound = runtime._bind_action(survey, action)

    assert bound.operation_ref == "o1"
    assert runtime._validate_action(survey, bound) == ""


def test_pending_context_echoes_exact_dispatched_owner_and_before_regions():
    ledger = _ledger()

    record = pending_action_record(ledger, "a1")

    assert record == {
        "attempt_ref": "a1",
        "kind": "click",
        "owner_ref": "el1",
        "target": "Alarms tab",
        "point_1000": None,
        "direction": "",
        "parameter_confirmation_required": False,
        "parameter_status": "none",
        "parameter_summary": "无参数",
        "before_region_refs": ["r1"],
    }
    assert "operation_ref" not in record


def test_detour_attempt_stays_attributed_to_current_focus(monkeypatch):
    class _Artifacts:
        @staticmethod
        def save_attempt_before(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/before.png"

    class _Env:
        @staticmethod
        def _get_obs():
            return {}

    ledger = _ledger()
    ledger.elements["el2"] = Element(
        "el2", "r1", "rv1", "Timer tab", ["o2"], ["ro1"])
    ledger.regions["r1"].element_ids.append("el2")
    ledger.region_variants["rv1"].element_ids.append("el2")
    ledger.regions["r1"].operation_ids.append("o2")
    ledger.region_variants["rv1"].operation_ids.append("o2")
    ledger.operations["o2"] = Operation(
        "o2", "r1", "click", "Timer tab", "verified",
        source_occurrence_ids=["ro1"], variant_id="rv1",
        canonical_operation_id="co2", element_id="el2",
    )
    ledger.canonical_operations["co2"] = CanonicalOperation(
        "co2", "r1", "click", "Timer tab", ["o2"])
    ledger.tasks["t2"] = Task(
        "t2", "explore_operation", "done", "s1", "o2")
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.env = _Env()
    runtime.artifacts = _Artifacts()
    runtime.platform = "desktop"
    runtime.actions_used = 0
    runtime.pending_attempt_id = ""
    runtime.pending_before = b""
    runtime.confirmed_state_id = "s1"
    runtime.confirmed_screenshot = b"before"
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.runtime.to_primitive",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.actions.to_primitive",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.runtime.time.sleep",
        lambda *_args, **_kwargs: None,
    )
    action = ActionRequest(
        kind="click", purpose="execute", target="Timer tab",
        point_1000=[500, 80], text="", direction="", amount=650,
        operation_ref="o2", owner_ref="el2",
    )

    runtime._execute(
        task=ledger.tasks["t1"], action=action, screenshot=b"before")

    attempt = ledger.attempts[runtime.pending_attempt_id]
    assert attempt.task_id == "t1"
    assert ledger.tasks["t1"].attempt_count == 1
    assert ledger.tasks["t2"].attempt_count == 0


def test_successful_preparatory_action_does_not_become_a_permanent_ban():
    runtime = ExplorationRuntime.__new__(ExplorationRuntime)
    runtime.ledger = _ledger()
    runtime.platform = "desktop"
    action = ActionRequest(
        kind="click", purpose="execute", target="Alarms tab",
        point_1000=[500, 80], text="", direction="", amount=650,
        operation_ref="o1", owner_ref="el1",
    )
    focus = Task("focus", "explore_operation", "active", "s1", "other")
    runtime.ledger.tasks["focus"] = focus
    runtime.ledger.attempts["detour"] = ActionAttempt(
        "detour", "focus", "s1", "execute",
        {
            "kind": "click", "purpose": "execute",
            "target": "Alarms tab", "point_1000": [501, 81],
            "text": "", "direction": "", "amount": 650,
            "operation_ref": "o1", "owner_ref": "el1",
        },
        "before.png", after_ref="after.png", outcome="success",
        target_state_id="s1",
    )

    issue = runtime._validate_action(focus, action)

    assert issue == ""
    far_issue = runtime._validate_action(
        focus, replace(action, point_1000=[500, 200]))
    assert far_issue == ""


@pytest.mark.parametrize(("operation_status", "task_status"), (
    ("verified", "done"),
    ("recorded", "done"),
    ("failed", "failed"),
    ("cancelled", "cancelled"),
))
def test_scheduler_reconciles_open_task_from_terminal_operation(
    operation_status,
    task_status,
):
    ledger = _ledger()
    ledger.current_page_id = "p1"
    ledger.current_state_id = "s1"
    ledger.current_task_id = ""
    ledger.operations["o1"].status = operation_status
    ledger.operations["o1"].result = "terminal operation evidence"
    ledger.tasks["t1"].status = "active"

    chosen = TaskScheduler().choose(ledger)

    assert chosen is None
    assert ledger.tasks["t1"].status == task_status
    assert ledger.tasks["t1"].reason == "terminal operation evidence"
