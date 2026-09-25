"""Existing modular exploration contracts: regions."""


import pytest

from gui_rewalk.src.core.explore.contracts import parse_turn
from gui_rewalk.src.core.explore.inventory import apply_page_report
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.location import bind_screen
from gui_rewalk.src.core.explore.models import (
    ActionAttempt,
    CanonicalOperation,
    Element,
    Operation,
    Page,
    Region,
    PageState,
    RegionOccurrence,
    RegionVariant,
    Transition,
)
from gui_rewalk.src.core.explore.regions import (
    merge_region_identity,
    neighboring_region_candidates,
    region_card_similarity,
    shortlist_region_candidate_occurrences,
)

from .explore_fixtures import _known_screen, _new_screen, _report, _seed_ledger, _turn


def test_region_candidates_include_earlier_regions_from_same_page():
    ledger = _seed_ledger()
    for state_id, region_id, occurrence_id, name in [
        ("s2", "r2", "ro2", "中间状态区块"),
        ("s3", "r3", "ro3", "当前状态区块"),
    ]:
        ledger.states[state_id] = PageState(
            state_id=state_id,
            page_id="p1",
            name=state_id,
            summary=name,
            screenshot_ref=f"screenshots/{state_id}.png",
            region_occurrence_ids=[occurrence_id],
            survey_complete=True,
            inventory_passes=1,
        )
        ledger.pages["p1"].state_ids.append(state_id)
        ledger.regions[region_id] = Region(
            region_id=region_id,
            name=name,
            summary=name,
            occurrence_ids=[occurrence_id],
        )
        ledger.occurrences[occurrence_id] = RegionOccurrence(
            occurrence_id=occurrence_id,
            region_id=region_id,
            state_id=state_id,
            name=name,
            summary=name,
        )
    ledger.transitions.append(Transition(
        transition_id="e1",
        source_state_id="s2",
        target_state_id="s3",
        action={"kind": "click", "target": "进入当前状态"},
        attempt_id="a1",
        visible_result="当前状态已显示。",
    ))
    ledger.pages["p2"] = Page(
        page_id="p2", name="另一页面", summary="包含跨页共享候选",
        state_ids=["s4"],
    )
    ledger.states["s4"] = PageState(
        state_id="s4", page_id="p2", name="另一状态",
        summary="跨页候选状态", screenshot_ref="screenshots/s4.png",
        region_occurrence_ids=["ro4"], survey_complete=True,
        inventory_passes=1,
    )
    ledger.regions["r4"] = Region(
        region_id="r4", name="跨页共享区块", summary="较远的规范区块",
        occurrence_ids=["ro4"],
    )
    ledger.occurrences["ro4"] = RegionOccurrence(
        occurrence_id="ro4", region_id="r4", state_id="s4",
        name="跨页共享区块", summary="较远的规范区块",
    )

    assert neighboring_region_candidates(ledger, "s3") == ["r2", "r1", "r4"]


def test_region_text_shortlist_prefers_neighbor_and_filters_unmatched_catalog():
    ledger = _seed_ledger()
    ledger.states["s2"] = PageState(
        "s2", "p1", "邻居状态", "显示共享导航",
        "screenshots/s2.png", ["ro2", "ro5"], True, 1)
    ledger.pages["p1"].state_ids.append("s2")
    ledger.regions["r2"] = Region(
        "r2", "全局导航", "切换主要页面", occurrence_ids=["ro2"])
    ledger.occurrences["ro2"] = RegionOccurrence(
        "ro2", "r2", "s2", "全局导航", "切换主要页面")
    ledger.regions["r5"] = Region(
        "r5", "邻居辅助区块", "同一候选截图中的完整目录",
        occurrence_ids=["ro5"])
    ledger.occurrences["ro5"] = RegionOccurrence(
        "ro5", "r5", "s2", "邻居辅助区块", "候选页辅助内容")
    ledger.states["s3"] = PageState(
        "s3", "p1", "当前状态", "再次显示共享导航",
        "screenshots/s3.png", ["ro3"], True, 1)
    ledger.pages["p1"].state_ids.append("s3")
    ledger.regions["r3"] = Region(
        "r3", "全局导航", "切换主要页面", occurrence_ids=["ro3"])
    ledger.occurrences["ro3"] = RegionOccurrence(
        "ro3", "r3", "s3", "全局导航", "切换主要页面")
    ledger.pages["p2"] = Page("p2", "远端页", "远端候选", ["s4"])
    ledger.states["s4"] = PageState(
        "s4", "p2", "远端状态", "同名导航",
        "screenshots/s4.png", ["ro4"], True, 1)
    ledger.regions["r4"] = Region(
        "r4", "全局导航", "切换主要页面", occurrence_ids=["ro4"])
    ledger.occurrences["ro4"] = RegionOccurrence(
        "ro4", "r4", "s4", "全局导航", "切换主要页面")
    ledger.transitions.append(Transition(
        "e1", "s2", "s3", "a1", {"kind": "click"}, "进入当前状态"))

    shortlisted = shortlist_region_candidate_occurrences(
        ledger,
        state_id="s3",
        current_region_ids=["r3"],
        max_candidate_states=1,
    )

    assert shortlisted == [("r2", "ro2")]


def test_region_shortlist_prefers_same_page_variant_of_shared_region():
    ledger = ExplorationLedger()
    ledger.pages["p1"] = Page("p1", "World", "世界时钟", ["s1"])
    ledger.pages["p2"] = Page(
        "p2", "Alarms", "闹钟", ["s2", "s3"])
    for state_id, page_id, occurrence_id, region_id, variant_id in (
        ("s1", "p1", "ro1", "r1", "rv1"),
        ("s2", "p2", "ro2", "r1", "rv2"),
        ("s3", "p2", "ro3", "r2", "rv3"),
    ):
        ledger.states[state_id] = PageState(
            state_id, page_id, state_id, "显示应用工具栏",
            f"screenshots/{state_id}.png", [occurrence_id], True, 1)
        ledger.occurrences[occurrence_id] = RegionOccurrence(
            occurrence_id, region_id, state_id,
            "应用工具栏", "提供应用菜单", variant_id)
        operation_id = "o" + state_id[1:]
        ledger.region_variants[variant_id] = RegionVariant(
            variant_id, region_id, [occurrence_id], [operation_id])
        ledger.operations[operation_id] = Operation(
            operation_id, region_id, "click", "应用菜单按钮", "pending",
            source_occurrence_ids=[occurrence_id], variant_id=variant_id)
    ledger.regions["r1"] = Region(
        "r1", "应用工具栏", "提供应用菜单",
        operation_ids=["o1", "o2"], occurrence_ids=["ro1", "ro2"],
        variant_ids=["rv1", "rv2"])
    ledger.regions["r2"] = Region(
        "r2", "应用工具栏", "提供应用菜单",
        operation_ids=["o3"], occurrence_ids=["ro3"],
        variant_ids=["rv3"])

    shortlisted = shortlist_region_candidate_occurrences(
        ledger,
        state_id="s3",
        current_region_ids=["r2"],
        max_candidate_states=2,
    )
    resume_shortlisted = shortlist_region_candidate_occurrences(
        ledger,
        state_id="s3",
        current_region_ids=["r2"],
        max_candidate_states=1,
        prefer_same_page=False,
    )

    assert shortlisted == [("r1", "ro2")]
    assert resume_shortlisted == [("r1", "ro1")]


def test_region_shortlist_does_not_offer_generic_main_with_different_actions():
    ledger = ExplorationLedger()
    ledger.pages["p1"] = Page("p1", "Workspace", "工作区", ["s1", "s2"])
    for state_id, region_id, occurrence_id, target in (
        ("s1", "r1", "ro1", "Open records"),
        ("s2", "r2", "ro2", "Open analytics"),
    ):
        ledger.states[state_id] = PageState(
            state_id, "p1", state_id, "主内容状态",
            f"screenshots/{state_id}.png", [occurrence_id], True, 1)
        ledger.regions[region_id] = Region(
            region_id, "Main Content Area", "主要内容区",
            operation_ids=["o" + state_id[1:]],
            occurrence_ids=[occurrence_id])
        ledger.occurrences[occurrence_id] = RegionOccurrence(
            occurrence_id, region_id, state_id,
            "Main Content Area", "主要内容区")
        ledger.operations["o" + state_id[1:]] = Operation(
            "o" + state_id[1:], region_id, "click", target, "pending",
            source_occurrence_ids=[occurrence_id])
    ledger.transitions.append(Transition(
        "e1", "s1", "s2", "a1", {"kind": "click"}, "进入分析页"))

    assert shortlist_region_candidate_occurrences(
        ledger, state_id="s2", current_region_ids=["r2"]) == []


def test_region_shortlist_does_not_filter_candidates_by_operation_word():
    ledger = ExplorationLedger()
    ledger.pages["p1"] = Page("p1", "Workspace", "工作区", ["s1", "s2"])
    for state_id, region_id, occurrence_id in (
        ("s1", "r1", "ro1"),
        ("s2", "r2", "ro2"),
    ):
        operation_id = "o" + state_id[1:]
        ledger.states[state_id] = PageState(
            state_id, "p1", state_id, "主内容状态",
            f"screenshots/{state_id}.png", [occurrence_id], True, 1)
        ledger.regions[region_id] = Region(
            region_id, "Main Content Area", "主内容区",
            operation_ids=[operation_id], occurrence_ids=[occurrence_id])
        ledger.occurrences[occurrence_id] = RegionOccurrence(
            occurrence_id, region_id, state_id,
            "Main Content Area", "主内容区")
        ledger.operations[operation_id] = Operation(
            operation_id, region_id, "click", "Add", "pending",
            source_occurrence_ids=[occurrence_id])

    assert shortlist_region_candidate_occurrences(
        ledger, state_id="s2", current_region_ids=["r2"]
    ) == [("r1", "ro1")]


def test_region_recall_uses_control_labels_when_context_wording_changes():
    ledger = ExplorationLedger()
    ledger.pages["p1"] = Page("p1", "Editor", "document editor", ["s1", "s2"])
    for index, name in [(1, "Document menu"), (2, "Document menu in alternate view")]:
        state_id, region_id, occurrence_id = f"s{index}", f"r{index}", f"ro{index}"
        ledger.states[state_id] = PageState(state_id, "p1", name, name, f"{state_id}.png", [occurrence_id])
        ledger.regions[region_id] = Region(region_id, name, name, occurrence_ids=[occurrence_id])
        ledger.occurrences[occurrence_id] = RegionOccurrence(occurrence_id, region_id, state_id, name, name)
        for slot, label in enumerate(["Properties", "Export", "Print"]):
            operation_id, element_id = f"o{index}-{slot}", f"el{index}-{slot}"
            target = f"菜单中的{label}入口" if index == 1 else f"{label} entry in document menu"
            ledger.elements[element_id] = Element(element_id, region_id, "", label, [operation_id], [occurrence_id])
            ledger.operations[operation_id] = Operation(operation_id, region_id, "click", target, "pending",
                source_occurrence_ids=[occurrence_id], element_id=element_id)
            ledger.regions[region_id].operation_ids.append(operation_id)
            ledger.regions[region_id].element_ids.append(element_id)
    assert shortlist_region_candidate_occurrences(
        ledger, state_id="s2", current_region_ids=["r2"]) == [("r1", "ro1")]
    # Recall supplies evidence to the reviewer; it does not merge identities.
    assert set(ledger.regions) == {"r1", "r2"}


def test_confirmed_region_does_not_infer_unreviewed_operation_identity():
    ledger = ExplorationLedger()
    ledger.regions["r1"] = Region(
        "r1", "Workspace Navigation", "共享导航",
        operation_ids=["o1", "o3"], occurrence_ids=["ro1"])
    ledger.regions["r2"] = Region(
        "r2", "Workspace Navigation", "共享导航",
        operation_ids=["o2", "o4"], occurrence_ids=["ro2"])
    ledger.occurrences["ro1"] = RegionOccurrence(
        "ro1", "r1", "s1", "Workspace Navigation", "共享导航")
    ledger.occurrences["ro2"] = RegionOccurrence(
        "ro2", "r2", "s2", "Workspace Navigation", "共享导航")
    for operation_id, region_id, target, canonical_id in (
        ("o1", "r1", "Home", "co1"),
        ("o2", "r2", "Home", "co2"),
        ("o3", "r1", "Add", "co3"),
        ("o4", "r2", "Add", "co4"),
    ):
        occurrence_id = "ro1" if region_id == "r1" else "ro2"
        ledger.operations[operation_id] = Operation(
            operation_id, region_id, "click", target, "recorded",
            source_occurrence_ids=[occurrence_id],
            canonical_operation_id=canonical_id)
        ledger.canonical_operations[canonical_id] = CanonicalOperation(
            canonical_id, region_id, "click", target, [operation_id])
        ledger.regions[region_id].canonical_operation_ids.append(canonical_id)

    merged = merge_region_identity(
        ledger,
        current_region_ids=["r2"],
        known_region_id="r1",
        shared_operations={},
        reason="完整截图确认是同一共享导航。",
    )

    assert merged.operations["o2"].canonical_operation_id == "co2"
    assert merged.operations["o4"].canonical_operation_id == "co4"
    assert not any(
        item["kind"] == "exact_operation_identity_inferred"
        for item in merged.events)


def test_region_card_similarity_keeps_inverse_operations_distinct():
    shared = {
        "left_name": "Workspace toolbar",
        "left_summary": "共享工具栏",
        "right_name": "Workspace toolbar",
        "right_summary": "共享工具栏",
    }
    same = region_card_similarity(
        **shared,
        left_operations=[{
            "action": "click", "scope": "element", "direction": "",
            "target": "Show library",
        }],
        right_operations=[{
            "action": "click", "scope": "element", "direction": "",
            "target": "Show library",
        }],
    )
    inverse = region_card_similarity(
        **shared,
        left_operations=[{
            "action": "click", "scope": "element", "direction": "",
            "target": "Hide library",
        }],
        right_operations=[{
            "action": "click", "scope": "element", "direction": "",
            "target": "Show library",
        }],
    )

    assert same == pytest.approx(1.0)
    assert inverse < 0.72


def test_region_merge_rewrites_revealed_region_reference():
    ledger = _seed_ledger()
    ledger.regions["r2"] = Region(
        "r2", "结果区块副本", "稍后确认与 r1 相同",
        occurrence_ids=["ro2"])
    ledger.occurrences["ro2"] = RegionOccurrence(
        "ro2", "r2", "s1", "结果区块副本", "稍后确认与 r1 相同")
    ledger.states["s1"].region_occurrence_ids.append("ro2")
    ledger.attempts["a1"] = ActionAttempt(
        "a1", "t1", "s1", "survey",
        {"kind": "scroll", "owner_ref": "r2", "direction": "down"},
        "before.png", outcome="success", target_state_id="s1")
    ledger.transitions.append(Transition(
        "e1", "s1", "s1", "a1",
        {"kind": "scroll", "owner_ref": "r2", "direction": "down"},
        "结果区块已显示。", revealed_region_ids=["r2"],
        hidden_region_ids=["r2"]))
    ledger.add_history(
        task_id="t1", purpose="survey", action="scroll",
        target="结果区块副本", parameters={"owner_ref": "r2"},
        result="结果区块已显示。", source_state_id="s1",
        target_state_id="s1",
    )

    merged = merge_region_identity(
        ledger,
        current_region_ids=["r2"],
        known_region_id="r1",
        shared_operations={},
        reason="完整截图确认是同一个稳定 Region。",
    )

    assert merged.transitions[0].revealed_region_ids == ["r1"]
    assert merged.transitions[0].hidden_region_ids == ["r1"]
    assert merged.attempts["a1"].action["owner_ref"] == "r1"
    assert merged.transitions[0].action["owner_ref"] == "r1"
    assert merged.history[0].parameters["owner_ref"] == "r1"


def test_region_merge_reuses_only_reviewed_same_action_operations():
    ledger = _seed_ledger()
    ledger.operations["o1"].status = "deferred"
    ledger.operation_task("o1").status = "deferred"
    second = bind_screen(
        ledger,
        parse_turn(
            _turn(screen={
                **_new_screen(),
                "page_name": "Alarms",
                "page_summary": "闹钟页面",
                "state_name": "空列表",
                "state_summary": "尚无闹钟",
            }, page_report=_report()),
            has_pending_action=False,
        ).screen,
        screenshot_ref="screenshots/second.png",
    )
    second_report = parse_turn(
        _turn(screen={
            **_known_screen(), "page_ref": "p2", "page_name": "Alarms",
            "page_summary": "闹钟页面", "state_ref": "s2",
            "state_name": "空列表", "state_summary": "尚无闹钟",
        }, page_report={
            "regions": [{
                "name": "秒表显示与控制的另一次划分",
                "summary": "测试共享区块",
                "operations": [
                    {"action": "click", "target": "开始按钮", "handling": "record",
                     "reason": "与已有操作精确一致，当前只需记录。"},
                    {"action": "long_press", "target": "开始按钮", "handling": "explore",
                     "reason": "动作不同，不能自动复用。"},
                ],
            }],
            "survey_complete": True,
            "coverage_note": "测试清单完整。",
        }),
        has_pending_action=False,
    ).page_report
    applied = apply_page_report(second.ledger, state_id="s2", report=second_report)
    with pytest.raises(ValueError, match="exact action"):
        merge_region_identity(
            applied.ledger,
            current_region_ids=["r2"],
            known_region_id="r1",
            shared_operations={"o3": "o1"},
            reason="动作不同，不能复用。",
        )
    merged = merge_region_identity(
        applied.ledger,
        current_region_ids=["r2"],
        known_region_id="r1",
        shared_operations={"o2": "o1"},
        reason="模型确认是同一完整功能组件。",
    )

    operations = merged.region_operations("r1")
    assert [(item.action, item.target) for item in operations] == [
        ("click", "开始按钮"), ("click", "开始按钮"),
        ("long_press", "开始按钮")]
    assert operations[0].status == "deferred"
    assert merged.operation_task("o1").status == "deferred"
    assert operations[1].status == "recorded"
    assert operations[0].canonical_operation_id == (
        operations[1].canonical_operation_id)
    assert operations[2].canonical_operation_id != (
        operations[0].canonical_operation_id)
    assert len(merged.regions["r1"].variant_ids) == 2


def test_region_merge_coalesces_reconstructed_fragments_into_state_variant():
    ledger = _seed_ledger()
    ledger.regions["r1"].name = "Alarm List"
    ledger.regions["r1"].summary = "完整闹钟列表"
    ledger.operations["o1"].target = "任一闹钟开关"
    ledger.canonical_operations["co1"].target = "任一闹钟开关"
    second = bind_screen(
        ledger,
        parse_turn(_turn(screen={
            **_new_screen(), "identity": "new_state", "page_ref": "p1",
            "state_name": "一个条目已展开",
            "state_summary": "同一列表包含展开条目和折叠条目",
        }), has_pending_action=False).screen,
        screenshot_ref="screenshots/expanded.png",
    )
    assert second.ok, second.issue
    report = parse_turn(_turn(
        screen=_known_screen(),
        page_report={
            "regions": [
                {
                    "name": "展开条目片段",
                    "summary": "完整列表中的展开条目",
                    "operations": [
                        {"action": "click", "target": "Work 闹钟开关",
                         "handling": "explore", "reason": "切换闹钟。"},
                        {"action": "click", "target": "暂停闹钟",
                         "handling": "explore", "reason": "打开暂停设置。"},
                    ],
                },
                {
                    "name": "折叠条目片段",
                    "summary": "完整列表中的其余折叠条目",
                    "operations": [{
                        "action": "click", "target": "9:00 闹钟开关",
                        "handling": "explore", "reason": "切换闹钟。",
                    }],
                },
            ],
            "survey_complete": True,
            "coverage_note": "两个片段共同覆盖完整列表。",
        },
    ), has_pending_action=False).page_report
    applied_result = apply_page_report(
        second.ledger, state_id=second.state_id, report=report)
    assert applied_result.ok, applied_result.issue
    applied = applied_result.ledger
    expanded_region = next(
        item for item in applied.regions.values()
        if item.name == "展开条目片段")
    collapsed_region = next(
        item for item in applied.regions.values()
        if item.name == "折叠条目片段")
    expanded_toggle, pause_operation = expanded_region.operation_ids
    collapsed_toggle = collapsed_region.operation_ids[0]

    merged = merge_region_identity(
        applied,
        current_region_ids=[
            expanded_region.region_id, collapsed_region.region_id],
        known_region_id="r1",
        shared_operations={
            expanded_toggle: "o1",
            collapsed_toggle: "o1",
        },
        reason="两个当前片段共同重构同一完整列表。",
    )

    assert list(merged.regions) == ["r1"]
    assert len(merged.regions["r1"].variant_ids) == 2
    current_occurrences = merged.state_occurrences(second.state_id)
    assert len(current_occurrences) == 2
    current_variant_ids = {
        item.variant_id for item in current_occurrences}
    assert len(current_variant_ids) == 1
    current_variant = merged.region_variants[current_variant_ids.pop()]
    assert len(current_variant.operation_ids) == 2
    assert expanded_toggle in current_variant.operation_ids
    assert pause_operation in current_variant.operation_ids
    assert collapsed_toggle not in merged.operations
    assert len(merged.operations) == 3
    assert len(merged.canonical_operations) == 2
    assert merged.operations[expanded_toggle].canonical_operation_id == "co1"
    assert any(
        item["kind"] == "region_variants_coalesced"
        for item in merged.events)
    assert any(
        item["kind"] == "variant_operations_merged"
        for item in merged.events)


def test_cross_page_navigation_variants_share_canonical_operations_selectively():
    ledger = ExplorationLedger()

    def _navigation_report(plus_target):
        targets = [
            plus_target, "World tab", "Alarms tab", "Stopwatch tab",
            "Timer tab", "Menu button (hamburger icon)",
        ]
        return parse_turn(_turn(
            screen=_known_screen(),
            page_report={
                "regions": [{
                    "name": "Top Navigation Bar",
                    "summary": "Global navigation and page-context controls.",
                    "operations": [{
                        "action": "click", "target": target,
                        "handling": "explore", "reason": "测试导航变体。",
                    } for target in targets],
                }],
                "survey_complete": True,
                "coverage_note": "顶部栏完整。",
            },
        ), has_pending_action=False).page_report

    world = bind_screen(
        ledger,
        parse_turn(_turn(screen=_new_screen()),
                   has_pending_action=False).screen,
        screenshot_ref="screenshots/world.png",
    )
    world_ledger = apply_page_report(
        world.ledger, state_id="s1",
        report=_navigation_report("Add World Clock button (+)"),
    ).ledger
    for operation_id in ("o3", "o4", "o6"):
        world_ledger.operations[operation_id].status = "verified"
        world_ledger.operations[operation_id].result = "已验证直接结果"
        world_ledger.operation_task(operation_id).status = "done"

    timer_screen = {
        **_new_screen(),
        "page_name": "Timer",
        "page_summary": "计时器页面",
        "state_name": "Running",
        "state_summary": "计时器正在运行",
    }
    timer = bind_screen(
        world_ledger,
        parse_turn(_turn(screen=timer_screen),
                   has_pending_action=False).screen,
        screenshot_ref="screenshots/timer.png",
    )
    timer_report = _navigation_report("Add new timer button (+)")
    merged_input = apply_page_report(
        timer.ledger, state_id="s2", report=timer_report).ledger

    merged = merge_region_identity(
        merged_input,
        current_region_ids=["r2"],
        known_region_id="r1",
        shared_operations={
            "o8": "o2",
            "o9": "o3",
            "o10": "o4",
            "o11": "o5",
            "o12": "o6",
        },
        shared_operation_levels={
            "o8": "identity",
            "o9": "result",
            "o10": "result",
            "o11": "identity",
            "o12": "result",
        },
        shared_result_texts={
            "o9": "进入 Alarms 页面。",
            "o10": "进入 Stopwatch 页面。",
            "o12": "打开全局菜单。",
        },
        reason="完整截图确认稳定导航，已选标签只共享身份。",
    )

    assert len(merged.regions) == 1
    assert len(merged.regions["r1"].variant_ids) == 2
    assert len(merged.operations) == 12
    assert len(merged.canonical_operations) == 7
    assert merged.operations["o1"].canonical_operation_id != (
        merged.operations["o7"].canonical_operation_id)
    for current_id, known_id in {
            "o8": "o2", "o9": "o3", "o10": "o4",
            "o11": "o5", "o12": "o6"}.items():
        assert merged.operations[current_id].canonical_operation_id == (
            merged.operations[known_id].canonical_operation_id)
    assert merged.operations["o8"].status == "pending"
    assert merged.operations["o11"].status == "pending"
    assert merged.operations["o9"].status == "verified"
    assert merged.operations["o10"].status == "verified"
    assert merged.operations["o12"].status == "verified"


@pytest.mark.parametrize(("known_target", "current_target"), [
    ("Timer 标签", "Timer 功能页"),
    ("顶部新增按钮", "Add button"),
])
def test_cross_page_operation_identity_honors_reviewer_not_target_wording(
        known_target, current_target):
    ledger = ExplorationLedger()
    ledger.pages["p1"] = Page("p1", "World", "世界时钟", ["s1"])
    ledger.pages["p2"] = Page("p2", "Alarms", "闹钟", ["s2"])
    ledger.states["s1"] = PageState(
        "s1", "p1", "World", "世界时钟", "screenshots/s1.png", ["ro1"],
        True, 1)
    ledger.states["s2"] = PageState(
        "s2", "p2", "Current", "当前页面", "screenshots/s2.png",
        ["ro2"], True, 1)
    for index in (1, 2):
        region_id = f"r{index}"
        variant_id = f"rv{index}"
        occurrence_id = f"ro{index}"
        element_id = f"el{index}"
        operation_id = f"o{index}"
        canonical_id = f"co{index}"
        state_id = f"s{index}"
        target = known_target if index == 1 else current_target
        ledger.regions[region_id] = Region(
            region_id, "顶部导航栏", "共享导航",
            [operation_id], [occurrence_id], [variant_id], [canonical_id],
            [element_id])
        ledger.region_variants[variant_id] = RegionVariant(
            variant_id, region_id, [occurrence_id], [operation_id],
            [element_id])
        ledger.occurrences[occurrence_id] = RegionOccurrence(
            occurrence_id, region_id, state_id, "顶部导航栏", "共享导航",
            variant_id)
        ledger.elements[element_id] = Element(
            element_id, region_id, variant_id, "新增按钮", [operation_id],
            [occurrence_id])
        ledger.operations[operation_id] = Operation(
            operation_id, region_id, "click", target, "pending",
            source_occurrence_ids=[occurrence_id], variant_id=variant_id,
            canonical_operation_id=canonical_id, element_id=element_id)
        ledger.canonical_operations[canonical_id] = CanonicalOperation(
            canonical_id, region_id, "click", target, [operation_id])

    merged = merge_region_identity(
        ledger,
        current_region_ids=["r2"],
        known_region_id="r1",
        shared_operations={"o2": "o1"},
        reason="Reviewer从完整截图判断两边是同一功能。",
    )

    assert (
        merged.operations["o2"].canonical_operation_id
        == merged.operations["o1"].canonical_operation_id)


def test_region_merge_keeps_unreviewed_same_named_operations_local():
    ledger = _seed_ledger()
    ledger.operations["o1"].target = "更多选项"
    ledger.operations["o1"].reason = "当前页面的专属菜单。"
    second = bind_screen(
        ledger,
        parse_turn(_turn(screen={
            **_new_screen(),
            "page_name": "Alarms",
            "page_summary": "闹钟页面",
            "state_name": "空列表",
            "state_summary": "尚无闹钟",
        }), has_pending_action=False).screen,
        screenshot_ref="screenshots/second.png",
    )
    report = parse_turn(_turn(screen={
        **_known_screen(), "page_ref": "p2", "page_name": "Alarms",
        "page_summary": "闹钟页面", "state_ref": "s2",
        "state_name": "空列表", "state_summary": "尚无闹钟",
    }, page_report={
        "regions": [{
            "name": "顶部应用栏",
            "summary": "包含当前页面的更多选项。",
            "operations": [{
                "action": "click", "target": "更多选项",
                "handling": "explore",
                "reason": "同名控件在当前页面打开页面专属菜单。",
            }],
        }],
        "survey_complete": True,
        "coverage_note": "当前页面清点完整。",
    }), has_pending_action=False).page_report
    applied = apply_page_report(second.ledger, state_id="s2", report=report)

    merged = merge_region_identity(
        applied.ledger,
        current_region_ids=["r2"],
        known_region_id="r1",
        shared_operations={},
        reason="应用栏是同一区块，但页面专属操作没有配对。",
    )

    operations = merged.region_operations("r1")
    assert len(operations) == 2
    assert [item.operation_id for item in operations] == ["o1", "o2"]
    assert operations[0].source_occurrence_ids == ["ro1"]
    assert operations[1].source_occurrence_ids == ["ro2"]
    assert operations[0].canonical_operation_id != (
        operations[1].canonical_operation_id)
