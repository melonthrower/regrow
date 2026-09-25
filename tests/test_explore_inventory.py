"""Existing modular exploration contracts: inventory."""


import pytest

from gui_rewalk.src.core.explore.status import build_task_view
from gui_rewalk.src.core.explore.bundle import (
    _entry_snapshot,
    _projected_region_names,
    _region_snapshot,
)
from gui_rewalk.src.core.explore.contracts import (
    ActionRequest,
    ElementReport,
    OperationReport,
    PageReport,
    RegionReport,
    parse_turn,
)
from gui_rewalk.src.core.explore.inventory import apply_page_report
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.location import bind_screen
from gui_rewalk.src.core.explore.models import (
    Element,
    PageState,
    RegionVariant,
    Transition,
)
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.settlement import settle_completed_actions
from gui_rewalk.src.core.explore.tasks import TaskScheduler

from .explore_fixtures import (
    _known_screen,
    _new_screen,
    _owner_previous,
    _parameter_ledger,
    _pending_parameter_attempt,
    _report,
    _seed_ledger,
    _turn,
)


def test_incremental_element_can_bind_an_existing_region_operation():
    ledger = _seed_ledger()
    report = parse_turn(
        _turn(
            screen=_known_screen(),
            page_report={
                "regions": [{
                    "region_ref": "r1",
                    "name": "秒表显示与控制",
                    "summary": "显示计时并提供主要控制",
                    "memory": "当前又看见同一开始功能的本地入口。",
                    "elements": [{
                        "element_ref": "",
                        "name": "当前可见开始入口",
                        "operations": [{
                            "operation_ref": "co1",
                            "action": "click", "target": "开始当前秒表",
                            "handling": "explore", "reason": "绑定已有功能。",
                            "parameter_status": "none",
                            "parameter_summary": "无参数",
                        }],
                    }],
                    "region_operations": [],
                }],
                "survey_complete": True,
                "coverage_note": "补充当前可见入口。",
            },
        ),
        has_pending_action=False,
    ).page_report

    applied = apply_page_report(ledger, state_id="s1", report=report)

    assert applied.ok is True
    added = next(
        item for item in applied.ledger.operations.values()
        if item.operation_id != "o1")
    assert added.canonical_operation_id == "co1"
    assert applied.ledger.canonical_operations["co1"].operation_ids == [
        "o1", added.operation_id]
    assert len(applied.ledger.canonical_operations) == 1


def test_unknown_record_operation_remains_non_executable_parameter_gap():
    ledger = _parameter_ledger("unknown", handling="record")
    operation = next(iter(ledger.operations.values()))

    assert operation.status == "recorded"
    assert operation.parameter_status == "unknown"
    assert operation.parameter_evidence_refs == []
    assert ledger.operation_task(operation.operation_id) is None
    assert TaskScheduler.gaps(ledger) == [
        f"{operation.canonical_operation_id} parameter_unknown: "
        "完整值域尚未观察"
    ]


@pytest.mark.parametrize("handling,status", [("record", "recorded"), ("defer", "deferred")])
def test_explicit_unexecuted_binding_can_revise_exploration_decision(handling, status):
    ledger = _seed_ledger()
    TaskScheduler().choose(ledger)
    raw = _report()
    operation = raw["regions"][0]["operations"][0]
    operation.update(operation_ref="co1", handling=handling,
                     reason="Fresh observation changes whether this action should be explored.")
    report = parse_turn(_turn(screen=_known_screen(), page_report=raw),
                        has_pending_action=False).page_report
    applied = apply_page_report(ledger, state_id="s1", report=report)
    assert applied.ok
    assert applied.ledger.operations["o1"].status == status
    task = applied.ledger.operation_task("o1")
    assert task.status == ("done" if handling == "record" else "deferred")
    assert applied.ledger.operations["o1"].attempt_count == 0
    assert applied.ledger.attempts == ledger.attempts
    if handling == "record":
        operation["handling"] = "explore"
        reopened = apply_page_report(applied.ledger, state_id="s1", report=parse_turn(
            _turn(screen=_known_screen(), page_report=raw), has_pending_action=False).page_report)
        assert reopened.ok
        assert reopened.ledger.operations["o1"].status == "pending"
        assert reopened.ledger.operation_task("o1").status == "pending"


def test_handling_revision_cannot_rewrite_an_executed_operation():
    ledger = _seed_ledger()
    ledger.operations["o1"].attempt_count = 1
    ledger.operations["o1"].status = "verified"
    raw = _report()
    raw["regions"][0]["operations"][0].update(operation_ref="co1", handling="defer")
    report = parse_turn(_turn(screen=_known_screen(), page_report=raw),
                        has_pending_action=False).page_report
    applied = apply_page_report(ledger, state_id="s1", report=report)
    assert applied.ok
    assert applied.ledger.operations["o1"].status == "verified"
    assert applied.ledger.operations["o1"].attempt_count == 1


def test_unknown_explore_operation_is_pending_for_one_parameter_probe():
    ledger = _parameter_ledger("unknown", handling="explore")
    operation = next(iter(ledger.operations.values()))

    assert operation.status == "pending"
    assert ledger.operation_task(operation.operation_id).status == "pending"


def test_direct_none_confirmation_is_recorded_with_inventory_screenshot():
    ledger = _parameter_ledger("none", handling="record")
    operation = next(iter(ledger.operations.values()))

    assert operation.status == "recorded"
    assert operation.parameter_status == "none"
    assert operation.parameter_evidence_refs == [
        "screenshots/parameter-source.png"]
    assert ledger.operation_task(operation.operation_id) is None


def test_incremental_parameter_confirmation_uses_current_inventory_frame():
    ledger = _parameter_ledger("unknown", handling="record")
    raw = _turn(screen=_known_screen(), page_report={
        "regions": [{
            "name": "参数设置",
            "summary": "包含一个参数化设置。",
            "memory": "已经观察完整参数域。",
            "elements": [{
                "name": "Volume buttons",
                "operations": [{
                    "action": "click",
                    "target": "选择音量按钮行为",
                    "handling": "record",
                    "reason": "参数已经从当前截图确认。",
                    "parameter_status": "observed",
                    "parameter_summary": "Control volume、Snooze、Dismiss",
                }],
            }],
            "region_operations": [],
        }],
        "survey_complete": True,
        "coverage_note": "参数设置已补充。",
    })
    report = parse_turn(raw, has_pending_action=False).page_report

    applied = apply_page_report(
        ledger,
        state_id="s1",
        report=report,
        screenshot_ref="screenshots/current-inventory.png",
    )

    assert applied.ok
    operation = next(iter(applied.ledger.operations.values()))
    assert operation.parameter_status == "observed"
    assert operation.parameter_evidence_refs == [
        "screenshots/current-inventory.png"]


@pytest.mark.parametrize("old_status,new_status", [("none", "observed"), ("observed", "none")])
def test_parameter_classification_can_be_corrected_without_rewriting_execution(old_status, new_status):
    ledger = _parameter_ledger(old_status, handling="record")
    operation = next(iter(ledger.operations.values()))
    operation.status = "verified"
    operation.attempt_count = 1
    operation.result = "Previously verified effect."
    old_summary = operation.parameter_summary
    element = ledger.elements[operation.element_id]
    region = ledger.regions[operation.region_id]
    operation_report = OperationReport(
        action=operation.action,
        target=operation.target,
        handling="record",
        reason="当前截图把可见值补充为参数。",
        parameter_status=new_status,
        parameter_summary="当前值为 Control volume。",
        operation_ref=operation.canonical_operation_id,
    )
    element_report = ElementReport(
        name=element.name,
        element_ref=element.element_id,
        operations=(operation_report,),
    )
    region_report = RegionReport(
        name=region.name,
        summary=region.summary,
        memory=region.memory,
        region_ref=region.region_id,
        elements=(element_report,),
        region_operations=(),
    )
    report = PageReport(
        regions=(region_report,),
        survey_complete=True,
        coverage_note="补充当前可见参数。",
    )

    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    before_facts = runtime._inventory_facts()
    result = apply_page_report(ledger, state_id="s1", report=report,
                              screenshot_ref="current.png")

    assert result.ok
    updated = result.ledger.operations[operation.operation_id]
    assert updated.parameter_status == new_status
    assert (updated.status, updated.attempt_count, updated.result) == (
        "verified", 1, "Previously verified effect.")
    assert operation.parameter_status == old_status
    event = next(e for e in result.ledger.events if e["kind"] == "parameter_observation_revised")
    assert event["payload"]["previous_summary"] == old_summary
    runtime.ledger = result.ledger
    assert runtime._inventory_facts() == before_facts


def test_unknown_operation_rejects_settlement_without_parameter_info():
    ledger = _parameter_ledger("unknown", handling="explore")
    operation, attempt = _pending_parameter_attempt(ledger)

    with pytest.raises(ValueError, match="parameter confirmation"):
        settle_completed_actions(
            ledger, attempt, _owner_previous(None))

    assert operation.status == "pending"
    assert operation.parameter_status == "unknown"


def test_page_inventory_creates_tasks_and_preserves_offscreen_facts():
    ledger = _seed_ledger()
    repeated = bind_screen(
        ledger,
        parse_turn(_turn(screen={
            **_known_screen(), "identity": "new_page",
        }), has_pending_action=False).screen,
        screenshot_ref="screenshots/repeated.png",
    )
    assert repeated.ok
    assert repeated.created_state is False
    assert repeated.page_id == "p1"
    assert repeated.state_id == "s1"
    assert len(repeated.ledger.pages) == 1
    assert len(repeated.ledger.states) == 1

    same_name_new_page = bind_screen(
        ledger,
        parse_turn(_turn(screen={
            **_new_screen(),
            "page_ref": "",
            "state_ref": "",
            "state_name": "另一个状态",
        }), has_pending_action=False).screen,
        screenshot_ref="screenshots/same-name.png",
    )
    assert not same_name_new_page.ok
    assert "p1（Stopwatch）" in same_name_new_page.issue
    assert "identity=known" in same_name_new_page.issue
    assert len(same_name_new_page.ledger.pages) == 1
    assert len(same_name_new_page.ledger.states) == 1

    assert ledger.states["s1"].survey_complete is True
    assert ledger.operations["o1"].status == "pending"
    assert ledger.operation_task("o1").status == "pending"

    downgrade = _report()
    downgrade["regions"][0]["operations"][0]["handling"] = "record"
    downgrade_report = parse_turn(
        _turn(screen=_known_screen(), page_report=downgrade),
        has_pending_action=False,
    ).page_report
    preserved = apply_page_report(
        ledger, state_id="s1", report=downgrade_report)
    assert preserved.ok
    assert preserved.ledger.operations["o1"].status == "pending"
    assert preserved.ledger.operation_task("o1").status == "pending"

    deferred = ledger.clone()
    deferred.operations["o1"].status = "deferred"
    deferred.operation_task("o1").status = "deferred"
    deferred.current_task_id = ""
    revisited = TaskScheduler().choose(deferred)
    assert revisited.operation_id == "o1"
    assert revisited.status == "active"
    task_view_runtime = object.__new__(ExplorationRuntime)
    task_view_runtime.ledger = deferred
    assert "前置操作已record也可用于准备" in build_task_view(task_view_runtime.ledger,
        revisited, rediscovering=getattr(task_view_runtime, "resume_region_rediscovery_required", False))["instruction"]

    routed = ledger.clone()
    routed.states["s2"] = PageState(
        state_id="s2", page_id="p1", name="运行中",
        summary="秒表运行后的状态", screenshot_ref="screenshots/running.png",
        survey_complete=True, inventory_passes=2,
    )
    routed.pages["p1"].state_ids.append("s2")
    routed.transitions.append(Transition(
        transition_id="e1", source_state_id="s1", target_state_id="s2",
        attempt_id="a1", action={"kind": "click", "target": "开始按钮"},
        visible_result="秒表开始运行",
    ))
    routed.current_state_id = "s2"
    routed.current_task_id = ""
    chosen = TaskScheduler().choose(routed)
    assert chosen.operation_id == "o1"
    assert chosen.status == "active"

    representative = parse_turn(
        _turn(screen=_known_screen(), page_report={
            "regions": [{
                "name": "秒表显示与控制",
                "summary": "同质列表使用了另一条可见样本",
                "operations": [{
                    "action": "click", "target": "任一同质运行项",
                    "handling": "explore", "reason": "代表同一种列表操作。",
                }],
            }],
            "survey_complete": True,
            "coverage_note": "同质样本变化，但操作角色未变化。",
        }),
        has_pending_action=False,
    ).page_report
    rebound = apply_page_report(ledger, state_id="s1", report=representative)
    assert rebound.ok
    assert len(rebound.ledger.operations) == 1
    assert rebound.ledger.operations["o1"].target == "任一同质运行项"
    assert rebound.ledger.canonical_operations["co1"].target == (
        "任一同质运行项")

    incomplete_report = parse_turn(
        _turn(screen=_known_screen(), page_report=_report(include_start=False)),
        has_pending_action=False,
    ).page_report
    incremental = apply_page_report(
        ledger, state_id="s1", report=incomplete_report)

    assert incremental.ok is True
    assert incremental.ledger.operations["o1"].status == "pending"


def test_single_element_region_and_region_operation_stay_distinct():
    ledger = ExplorationLedger()
    screen = parse_turn(
        _turn(screen=_new_screen()), has_pending_action=False).screen
    bound = bind_screen(
        ledger, screen, screenshot_ref="screenshots/single-button.png")
    report = parse_turn(_turn(screen=_known_screen(), page_report={
        "regions": [{
            "name": "横向计时卡片",
            "summary": "一个可横向滑动的计时功能区块",
            "elements": [{
                "name": "开始按钮",
                "operations": [{
                    "action": "click", "target": "开始计时按钮",
                    "handling": "explore", "reason": "会改变计时状态。",
                }],
            }],
            "region_operations": [{
                "action": "scroll", "direction": "left",
                "target": "横向计时卡片",
                "handling": "explore", "reason": "可查看下一张卡片。",
            }],
        }],
        "survey_complete": True,
        "coverage_note": "单按钮 Region 及其横向滑动均已登记。",
    }), has_pending_action=False).page_report

    applied = apply_page_report(bound.ledger, state_id="s1", report=report)

    assert applied.ok
    assert len(applied.ledger.regions) == 1
    assert len(applied.ledger.elements) == 1
    element = next(iter(applied.ledger.elements.values()))
    element_operation = applied.ledger.operations[element.operation_ids[0]]
    region_operation = next(
        item for item in applied.ledger.operations.values()
        if item.scope == "region")
    assert element_operation.scope == "element"
    assert element_operation.element_id == element.element_id
    assert region_operation.element_id == ""
    assert region_operation.direction == "left"
    assert set(applied.ledger.regions["r1"].operation_ids) == {
        element_operation.operation_id, region_operation.operation_id}
    projected_names = _projected_region_names(applied.ledger)
    entries, _lookup = _entry_snapshot(applied.ledger, projected_names)
    entry_by_scope = {
        item["operation_scope"]: item for item in entries["entries"]}
    assert entry_by_scope["element"]["subject"] == "开始按钮"
    assert entry_by_scope["region"]["subject"] == "横向计时卡片"
    assert entry_by_scope["region"]["direction"] == "left"
    region_group = _region_snapshot(
        applied.ledger, projected_names)["region_groups"]["groups"][0]
    assert region_group["element_refs"] == [element.element_id]
    assert region_group["region_operation_refs"] == [
        region_operation.operation_id]
    assert set(region_group["capability_operation_refs"]) == {
        element_operation.operation_id, region_operation.operation_id}

    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = applied.ledger
    runtime.platform = "mobile"
    task = applied.ledger.operation_task(region_operation.operation_id)
    task.status = "active"
    runtime.ledger.current_task_id = task.task_id
    issue = runtime._validate_action(task, ActionRequest(
        kind="scroll", purpose="execute", target="横向计时卡片",
        point_1000=None, text="", direction="right", amount=650,
        operation_ref=region_operation.operation_id, owner_ref="r1",
    ))
    assert "RegionOperation 方向不一致" in issue

    incremental_report = parse_turn(_turn(
        screen=_known_screen(), page_report={
            "regions": [{
                "name": "横向计时卡片",
                "summary": "滑动后显示了另一个控件",
                "elements": [{
                    "name": "重置按钮",
                    "operations": [{
                        "action": "click", "target": "重置计时按钮",
                        "handling": "record", "reason": "直接效果清楚。",
                    }],
                }],
                "region_operations": [],
            }],
            "survey_complete": True,
            "coverage_note": "只补报新显露的 Element。",
        }), has_pending_action=False).page_report
    incremental = apply_page_report(
        applied.ledger, state_id="s1", report=incremental_report)
    assert incremental.ok
    assert len(incremental.ledger.elements) == 2
    assert element_operation.operation_id in incremental.ledger.operations


def test_known_variant_refs_prevent_element_name_drift():
    ledger = _seed_ledger()
    existing_element = next(iter(ledger.elements.values()))
    existing_operation = next(iter(ledger.operations.values()))
    existing_canonical = existing_operation.canonical_operation_id
    raw = _turn(screen=_known_screen(), page_report={
        "regions": [{
            "region_ref": "r1",
            "name": "改写后的秒表控制区名称",
            "summary": "同一已知区块",
            "elements": [{
                "element_ref": existing_element.element_id,
                "name": "改写后的开始控件名称",
                "operations": [{
                    "action": "click", "target": "开始秒表计时",
                    "handling": "explore", "reason": "同一个已知按钮。",
                }],
            }],
            "region_operations": [],
        }],
        "survey_complete": True,
        "coverage_note": "使用已有ref更新已知对象。",
    })
    report = parse_turn(raw, has_pending_action=False).page_report

    applied = apply_page_report(ledger, state_id="s1", report=report)

    assert applied.ok
    assert list(applied.ledger.elements) == [existing_element.element_id]
    assert list(applied.ledger.operations) == [existing_operation.operation_id]
    assert applied.ledger.operations[
        existing_operation.operation_id].canonical_operation_id == (
            existing_canonical)


def test_known_variant_rejects_element_ref_from_another_variant():
    ledger = _seed_ledger()
    ledger.region_variants["rv-other"] = RegionVariant("rv-other", "r1")
    ledger.elements["el-other"] = Element(
        "el-other", "r1", "rv-other", "其他状态按钮")
    raw = _turn(screen=_known_screen(), page_report={
        "regions": [{
            "region_ref": "r1", "name": "秒表显示与控制",
            "summary": "当前状态", "elements": [{
                "element_ref": "el-other", "name": "错误按钮",
                "operations": [{
                    "action": "click", "target": "错误按钮",
                    "handling": "record", "reason": "错误跨Variant引用。",
                }],
            }], "region_operations": [],
        }],
        "survey_complete": True, "coverage_note": "错误引用。",
    })
    report = parse_turn(raw, has_pending_action=False).page_report

    applied = apply_page_report(ledger, state_id="s1", report=report)

    assert applied.ok is False
    assert "element_ref" in applied.issue
    assert "el-other" in applied.issue


def test_new_state_old_refs_become_reviewed_candidates():
    ledger = _seed_ledger()
    ledger.pages["p1"].state_ids.append("s2")
    ledger.states["s2"] = PageState(
        "s2", "p1", "新状态", "同页新状态", "screenshots/s2.png")
    raw = _turn(screen={
        **_known_screen(), "state_ref": "s2", "state_name": "新状态",
    }, page_report={
        "regions": [{
            "region_ref": "r1", "name": "秒表显示与控制",
            "summary": "延续的已知Region", "elements": [{
                "element_ref": "el1", "name": "开始按钮",
                "operations": [{
                    "action": "click", "target": "开始按钮",
                    "handling": "record", "reason": "旧Variant提示。",
                }],
            }], "region_operations": [],
        }],
        "survey_complete": True, "coverage_note": "新State首帧。",
    })
    report = parse_turn(raw, has_pending_action=False).page_report
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger

    normalized = runtime._normalize_page_report_refs_for_state(
        report=report, state_id="s2", screen_identity="new_state")

    assert normalized.regions[0].region_ref == ""
    assert normalized.regions[0].elements[0].element_ref == ""
    assert any(
        item["kind"] == "new_state_inventory_refs_deferred"
        and item["payload"]["suggested_region_ref"] == "r1"
        for item in ledger.events)


def test_known_state_wrong_refs_are_not_normalized_away():
    ledger = _seed_ledger()
    raw = _turn(screen=_known_screen(), page_report={
        "regions": [{
            "region_ref": "r-missing", "name": "错误Region",
            "summary": "错误引用", "elements": [{
                "element_ref": "el1", "name": "开始按钮",
                "operations": [],
            }], "region_operations": [],
        }],
        "survey_complete": True, "coverage_note": "错误引用。",
    })
    report = parse_turn(raw, has_pending_action=False).page_report
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger

    normalized = runtime._normalize_page_report_refs_for_state(
        report=report, state_id="s1", screen_identity="known")
    applied = apply_page_report(ledger, state_id="s1", report=normalized)

    assert normalized.regions[0].region_ref == "r-missing"
    assert applied.ok is False


def test_vertical_region_scroll_is_recorded_without_duplicate_operation_task():
    ledger = ExplorationLedger()
    screen = parse_turn(
        _turn(screen=_new_screen()), has_pending_action=False).screen
    bound = bind_screen(
        ledger, screen, screenshot_ref="screenshots/vertical-list.png")
    report = parse_turn(_turn(screen=_known_screen(), page_report={
        "regions": [{
            "name": "声音列表",
            "summary": "可纵向调查的连续声音列表",
            "elements": [],
            "region_operations": [{
                "action": "scroll", "direction": "down",
                "target": "声音列表",
                "handling": "explore", "reason": "调查视口下方的内容。",
            }],
        }],
        "survey_complete": False,
        "coverage_note": "仍需向下调查。",
    }), has_pending_action=False).page_report

    applied = apply_page_report(bound.ledger, state_id="s1", report=report)

    assert applied.ok
    operation = next(iter(applied.ledger.operations.values()))
    assert operation.scope == "region"
    assert operation.direction == "down"
    assert operation.status == "recorded"
    assert applied.ledger.operation_task(operation.operation_id) is None
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = applied.ledger
    task = applied.ledger.survey_task("s1")
    assert "普通纵向scroll记record" in build_task_view(runtime.ledger,
        task, rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))["instruction"]
    assert "同质数据结构明确即可收束" in build_task_view(runtime.ledger,
        task, rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))["instruction"]
    assert "完整且可安全关闭前景时可同轮back" in build_task_view(runtime.ledger,
        task, rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))["instruction"]


def test_incremental_report_cannot_reopen_completed_state_survey():
    ledger = _seed_ledger()
    report = _report(include_start=False)
    report["survey_complete"] = False
    report["coverage_note"] = "回访时补报新事实，不重新调查已完成页面。"
    incremental = parse_turn(
        _turn(screen=_known_screen(), page_report=report),
        has_pending_action=False,
    ).page_report

    applied = apply_page_report(
        ledger, state_id="s1", report=incremental)

    assert applied.ok
    assert applied.ledger.states["s1"].survey_complete is True
    assert applied.ledger.states["s1"].inventory_passes >= 1
    assert applied.ledger.survey_task("s1").status == "done"
    assert any(
        event["kind"] == "survey_completion_preserved"
        for event in applied.ledger.events
    )
