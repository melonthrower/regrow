"""Offline contracts for the autonomous natural-language exploration tools."""

from __future__ import annotations

import io

from PIL import Image

from gui_rewalk.src.core.visual_traversal.runtime.autonomous_protocol import (
    ENTRY_REVIEW_SPECIALIST_PROMPT,
    EXPLORE_ENTRY_PROMPT,
    NaturalExplorationMap,
    PAGE_IDENTITY_RESPONSE_SCHEMA,
    PAGE_ONLY_IDENTITY_SPECIALIST_PROMPT,
    PROTOCOL_PROMPT,
    SURVEY_PAGE_PROMPT,
    VARIANT_ONLY_IDENTITY_SPECIALIST_PROMPT,
    protocol_prompt_for,
)


def _png(color: str, size: tuple[int, int] = (100, 80)) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


def _observe(
    natural_map: NaturalExplorationMap,
    name: str,
    *,
    regions=(),
    screenshot: bytes = b"",
) -> None:
    natural_map.observe(
        name=name,
        summary=f"Visible {name}",
        identity="new",
        matched_page_name="",
        surface_kind="page",
        regions=regions,
        screenshot=screenshot,
    )


def _revisit(natural_map: NaturalExplorationMap, name: str) -> None:
    natural_map.observe(
        name=name,
        summary=f"Visible {name}",
        identity="known",
        matched_page_name=name,
        surface_kind="page",
        regions=(),
        screenshot=b"",
    )


def test_prompts_keep_general_identity_and_function_entry_boundaries() -> None:
    assert "不判断页面状态版本" in PAGE_ONLY_IDENTITY_SPECIALIST_PROMPT
    assert "滚动位置、普通状态值、动态内容" in (
        PAGE_ONLY_IDENTITY_SPECIALIST_PROMPT)
    assert "标题、选中导航、主要内容容器" in (
        PAGE_ONLY_IDENTITY_SPECIALIST_PROMPT)
    assert "实质改变后续可执行操作" in (
        VARIANT_ONLY_IDENTITY_SPECIALIST_PROMPT)
    assert "滚动、悬停、焦点、时间" in (
        VARIANT_ONLY_IDENTITY_SPECIALIST_PROMPT)
    assert "只推进框架提供的当前任务和当前阶段" in PROTOCOL_PROMPT
    assert "最新完整截图优先于历史" in PROTOCOL_PROMPT
    assert "旧坐标不得复用" in PROTOCOL_PROMPT
    assert "共同承担一个稳定功能角色的组件组" in SURVEY_PAGE_PROMPT
    assert "不是单个按钮或矩形位置" in SURVEY_PAGE_PROMPT
    assert "所有稳定区域" in SURVEY_PAGE_PROMPT
    assert "task.region 调查只更新该区域" in SURVEY_PAGE_PROMPT
    assert "取得无遮挡截图后再调查" in SURVEY_PAGE_PROMPT
    assert "对理解或执行用户命令有意义的操作" in SURVEY_PAGE_PROMPT
    assert "无需真实探索" in SURVEY_PAGE_PROMPT
    assert "不要在主 Agent 阶段" in SURVEY_PAGE_PROMPT
    assert "same_group_as" in SURVEY_PAGE_PROMPT
    assert "operation 描述用户操作" in SURVEY_PAGE_PROMPT
    assert "target 是带必要功能上下文的控件名" in SURVEY_PAGE_PROMPT
    assert "control_type 只决定执行方式" in SURVEY_PAGE_PROMPT
    assert "先点击才显露输入框的目标仍是 control" in SURVEY_PAGE_PROMPT
    assert "page_update 只提交结构事实" in SURVEY_PAGE_PROMPT
    assert "路线、定位、恢复和真正尝试都属于这条任务" in (
        EXPLORE_ENTRY_PROMPT)
    assert "purpose=entry_attempt" in EXPLORE_ENTRY_PROMPT
    assert "真正尝试必须使用 input_text" in EXPLORE_ENTRY_PROMPT
    assert "点击聚焦只能作为 locating 中间步骤" in EXPLORE_ENTRY_PROMPT
    assert "RegionScan" not in SURVEY_PAGE_PROMPT
    assert "inspect_region" not in SURVEY_PAGE_PROMPT
    combined = SURVEY_PAGE_PROMPT + ENTRY_REVIEW_SPECIALIST_PROMPT
    assert all(term not in combined for term in ("闹钟", "照片", "铃声", "8:30"))


def test_main_prompt_does_not_make_cross_page_region_identity_decisions() -> None:
    assert "跨页面" not in SURVEY_PAGE_PROMPT
    assert "equivalent_to_region_ref" not in SURVEY_PAGE_PROMPT
    assert "全局去重" not in SURVEY_PAGE_PROMPT


def test_protocol_prompt_exposes_only_the_current_stage_contract() -> None:
    survey = protocol_prompt_for("survey_page", "survey_region")
    route = protocol_prompt_for("explore_entry", "route_to_source")
    settlement = protocol_prompt_for(
        "explore_entry", "locate_entry", has_pending_action=True)

    assert "当前阶段是继续调查 task.region" in survey
    assert "滚动或局部展开" in survey
    assert "coverage_complete" in survey
    record = protocol_prompt_for("survey_page", "record_regions")
    assert "一次提交当前可见功能区域" in record
    assert "只提交 page_update" in record
    assert "bbox_1000" not in record
    assert "根据最新截图和已验证路线" in route
    assert "一次只执行一个实际可见步骤" in route
    assert "判断这一个操作产生的真实可见结果" in settlement
    assert "中间导航或定位动作失败" in settlement
    assert "尚未完成的路线、定位和调查步骤继续保留" in settlement
    assert "visible_effect" in settlement
    assert "owner_structure" in settlement
    assert "review_scroll_frontier" not in survey


def test_dynamic_stage_prompts_do_not_repeat_or_reference_missing_fields() -> None:
    entry = protocol_prompt_for("explore_entry", "locate_entry")
    region_review = protocol_prompt_for(
        "survey_page", "review_region_equivalence")

    assert entry.count("purpose=entry_attempt") == 1
    assert "known_region_candidates" not in region_review
    assert "component_signature" not in region_review
    assert "verified_entries" not in region_review
    assert "响应结构中不存在的共享引用字段" in region_review


def test_entry_reviewer_keeps_information_bearing_operations() -> None:
    prompt = ENTRY_REVIEW_SPECIALIST_PROMPT

    assert "独立操作复核器" in prompt
    assert "固定完整截图" in prompt
    assert "候选不是封闭清单" in prompt
    assert "independent_entries 表示需要真实探索" in prompt
    assert "record_only_entries 表示值得正式记录" in prompt
    assert "这里只证明操作存在，不证明效果或路线已验证" in prompt
    assert "deferred_entries 表示操作有探索价值" in prompt
    assert "non_task_entries 只放" in prompt
    assert "不能用 non_task_entries 表示" in prompt
    assert "不能按距离猜测" in prompt
    assert "全局或顶级导航" in prompt
    assert "shared_region_entries" in prompt
    assert "entry_resolutions" in SURVEY_PAGE_PROMPT
    assert "task.region 内的候选" in SURVEY_PAGE_PROMPT
    assert "deferred_regions" in prompt
    assert len(prompt) < 1200


def test_observe_registers_natural_page_and_merges_local_control_memory() -> None:
    natural_map = NaturalExplorationMap()
    canonical, issue = natural_map.observe(
        name="  Chats  ",
        summary="Recent conversations",
        identity="new",
        matched_page_name="",
        surface_kind="main",
        regions=[{
            "name": "Conversation list",
            "summary": "Visible recent chats",
            "controls": ["Alice", "New chat", " new CHAT "],
        }],
        screenshot=_png("navy"),
    )

    assert (canonical, issue) == ("Chats", "")

    canonical, issue = natural_map.observe(
        name="ignored known-page label",
        summary="",
        identity="known",
        matched_page_name=" chats ",
        surface_kind="main",
        regions=[
            {
                "name": " conversation LIST ",
                "summary": "",
                "controls": ["Alice", "Bob"],
            },
            {
                "name": "Header",
                "summary": "Page actions",
                "controls": ["Search"],
            },
        ],
        screenshot=_png("orange"),
    )

    assert (canonical, issue) == ("Chats", "")
    shown = natural_map.prompt_view()
    assert shown["current_page"] == "Chats"
    assert shown["pages"] == [{
        "name": "Chats",
        "summary": "Recent conversations",
        "surface_kind": "main",
        "identity_status": "known",
            "variants": [{
                "name": "default",
                "visible_predicates": [],
            }],
    }]
    assert "regions" not in shown["pages"][0]
    details = natural_map.serializable()["page_details"][0]
    assert details["name"] == "Chats"
    assert details["regions"] == [
        {
            "name": "Conversation list",
            "summary": "Visible recent chats",
            "controls": ["Alice", "New chat", "Bob"],
        },
        {
            "name": "Header",
            "summary": "Page actions",
            "controls": ["Search"],
        },
    ]


def test_known_revisit_keeps_private_page_id_stable_and_out_of_prompt() -> None:
    natural_map = NaturalExplorationMap()
    _observe(natural_map, "Settings", screenshot=_png("navy"))
    first_page_id = natural_map.page_id("Settings")

    _revisit(natural_map, "Settings")

    assert first_page_id == "auto_page_1"
    assert natural_map.page_id("settings") == first_page_id
    assert "internal_page_id" not in natural_map.prompt_view()["pages"][0]


def test_internal_route_hint_returns_natural_control_steps_from_current_page() -> None:
    natural_map = NaturalExplorationMap()
    for page_name in ("Chats", "Contact picker", "New conversation"):
        _observe(natural_map, page_name)
    _revisit(natural_map, "Chats")
    natural_map.connect("Chats", "Contact picker", "CLICK", "New chat")
    natural_map.connect(
        "Contact picker", "New conversation", "CLICK", "Alice")

    assert natural_map.route_hint(" new CONVERSATION ") == [
        {
            "from": "Chats",
            "via": "New chat",
            "action": "CLICK",
            "to": "Contact picker",
            "provenance": "observed",
        },
        {
            "from": "Contact picker",
            "via": "Alice",
            "action": "CLICK",
            "to": "New conversation",
            "provenance": "observed",
        },
    ]


def test_route_is_internal_and_unknown_tools_report_public_map_tools() -> None:
    natural_map = NaturalExplorationMap()
    _revisit(natural_map, "Chats")
    _observe(natural_map, "Settings")
    _observe(natural_map, "Chats")

    assert natural_map.route_hint("Settings") == []
    route_tool = natural_map.call_tool("route_to", {}, b"")
    unknown = natural_map.call_tool("do_everything", {}, b"")

    assert route_tool.status == "unknown_tool"
    assert unknown.status == "unknown_tool"
    assert "do_everything" not in unknown.data["known_tools"]
    assert set(unknown.data["known_tools"]) == {
        "page_identity", "report_record_error", "finish_exploration",
    }


def test_unreachable_evidence_is_stored_under_its_registered_page() -> None:
    natural_map = NaturalExplorationMap()
    _observe(natural_map, "Settings")

    issues = natural_map.record_unreachable_evidence([{
        "page_name": "Settings",
        "entry_id": "",
        "subject": "Developer options",
        "evidence": "Three distinct visible routes returned to Settings.",
    }])

    details = natural_map.serializable()["page_details"][0]
    assert issues == []
    assert details["unreachable_evidence"] == [{
        "page_name": "Settings",
        "entry_id": "",
        "subject": "Developer options",
        "evidence": "Three distinct visible routes returned to Settings.",
    }]


def test_report_record_error_marks_dispute_without_mutating_map() -> None:
    natural_map = NaturalExplorationMap()
    _observe(natural_map, "Chats")

    evidence = natural_map.call_tool("report_record_error", {
        "kind": "page_identity",
        "subject": "Chats",
        "observed_problem": "The foreground dialog was merged into the page.",
        "proposed_correction": "Keep the dialog as a separate surface.",
    }, b"")

    assert evidence.status == "reported"
    assert "账本未修改" in evidence.data["feedback"]
    assert "继续决策时仍以当前账本为准" in evidence.data["feedback"]
    assert "Chats" in evidence.data["feedback"]
    assert "report_id" not in evidence.data
    assert natural_map.prompt_view()["pages"][0]["name"] == "Chats"
    assert natural_map.prompt_view()["record_errors"][0]["subject"] == "Chats"


def test_page_identity_receives_current_frame_map_and_returns_evidence() -> None:
    natural_map = NaturalExplorationMap()
    representative = _png("navy")
    _observe(natural_map, "Chats", screenshot=representative)
    current = _png("blue")
    requests = []

    def resolver(request):
        requests.append(request)
        return {
            "status": "known",
            "matched_page_name": "Chats",
            "surface_kind": "page",
            "summary": "The chat list is visible.",
            "supporting_evidence": ["same navigation and list layout"],
            "conflicting_evidence": ["different message preview"],
            "checked_candidates": ["Chats"],
            "reason": "Dynamic content changed but the operable page did not.",
        }

    evidence = natural_map.call_tool(
        "page_identity",
        {
            "suspected_pages": ["chats"],
            "proposed_new_name": "Conversation list",
            "reason": "The visible rows changed.",
        },
        current,
        page_identity_resolver=resolver,
        identity_feedback={
            "decision": "reject", "reason": "wrong overlay",
            "correction": "compare the foreground dialog",
        },
        page_identity_context={
            "source_page": "Home",
            "via_control": "Open chats",
            "source_neighbors": [{"from": "Home", "to": "Chats"}],
        },
    )

    assert evidence.status == "known"
    assert evidence.data == {
        "page_name": "Chats",
        "matched_page_name": "Chats",
        "variant_name": "default",
        "variant_identity": "known",
        "visible_predicates": [],
        "surface_kind": "page",
        "summary": "The chat list is visible.",
        "supporting_evidence": ["same navigation and list layout"],
        "conflicting_evidence": ["different message preview"],
        "checked_candidates": ["Chats"],
        "reason": "Dynamic content changed but the operable page did not.",
    }
    assert requests[0]["current_screenshot"] == current
    assert requests[0]["registered_pages"][0]["variants"][0][
        "representative_screenshot"] == representative
    assert requests[0]["registered_page_count"] == 1
    assert requests[0]["arrival_context"]["source_page"] == "Home"
    assert requests[0]["arrival_context"]["via_control"] == "Open chats"
    assert "specialist_prompt" not in requests[0]
    assert requests[0]["previous_tool_feedback"]["correction"] == (
        "compare the foreground dialog")


def test_staged_page_identity_hides_variants_until_page_is_selected() -> None:
    natural_map = NaturalExplorationMap()
    natural_map.observe(
        name="Alarms",
        summary="Alarm list",
        identity="new",
        matched_page_name="",
        surface_kind="page",
        regions=(),
        screenshot=_png("red"),
        variant_name="empty_state",
        variant_identity="new",
    )
    natural_map.observe(
        name="Timer",
        summary="Timer setup",
        identity="new",
        matched_page_name="",
        surface_kind="page",
        regions=(),
        screenshot=_png("blue"),
        variant_name="initial_state",
        variant_identity="new",
    )
    requests = []

    def page_resolver(request):
        requests.append(request)
        return {
            "status": "known",
            "page_name": "Timer",
            "matched_page_name": "Timer",
            "surface_kind": "page",
            "summary": "Timer setup is visible.",
            "supporting_evidence": ["Timer navigation is selected."],
            "conflicting_evidence": [],
            "checked_candidates": ["Alarms", "Timer"],
            "reason": "The stable Timer page anchors match.",
        }

    page_result = natural_map.call_tool(
        "page_identity",
        {
            "suspected_pages": ["Alarms", "Timer"],
            "proposed_new_name": "Timer",
            "reason": "Resolve the landing Page.",
        },
        _png("cyan"),
        page_identity_resolver=page_resolver,
        page_identity_context={"identity_stage": "page"},
    )

    assert page_result.status == "known"
    assert page_result.data["page_name"] == "Timer"
    assert page_result.data["variant_name"] == ""
    assert all("variants" not in page for page in requests[0]["registered_pages"])

    def variant_resolver(request):
        requests.append(request)
        return {
            "variant_name": "initial_state",
            "variant_identity": "known",
            "visible_predicates": ["Select Duration is visible."],
            "supporting_evidence": ["The duration picker matches."],
            "conflicting_evidence": [],
            "checked_candidates": ["initial_state"],
            "reason": "The registered Timer initial state matches.",
        }

    variant_result = natural_map.call_tool(
        "page_identity",
        {
            "suspected_pages": [],
            "proposed_new_name": "",
            "reason": "Resolve the selected Page Variant.",
        },
        _png("cyan"),
        page_identity_resolver=variant_resolver,
        page_identity_context={
            "identity_stage": "variant",
            "selected_page": {
                "page_name": "Timer",
                "identity": "known",
            },
        },
    )

    assert variant_result.status == "known"
    assert variant_result.data["page_name"] == "Timer"
    assert variant_result.data["variant_name"] == "initial_state"
    assert [
        page["page_name"] for page in requests[1]["registered_pages"]
    ] == ["Timer"]
    assert [
        item["variant_name"]
        for item in requests[1]["registered_pages"][0]["variants"]
    ] == ["initial_state"]


def test_new_page_variant_stage_has_no_registered_variant_candidates() -> None:
    natural_map = NaturalExplorationMap()
    natural_map.observe(
        name="Alarms",
        summary="Alarm list",
        identity="new",
        matched_page_name="",
        surface_kind="page",
        regions=(),
        screenshot=_png("red"),
        variant_name="empty_state",
        variant_identity="new",
    )
    requests = []

    def resolver(request):
        requests.append(request)
        return {
            "variant_name": "initial_state",
            "variant_identity": "new",
            "visible_predicates": ["The stopwatch controls are visible."],
            "supporting_evidence": ["No Variant exists on this new Page."],
            "conflicting_evidence": [],
            "checked_candidates": [],
            "reason": "This is the new Page's initial material Variant.",
        }

    result = natural_map.call_tool(
        "page_identity",
        {
            "suspected_pages": [],
            "proposed_new_name": "",
            "reason": "Resolve the new Page's initial Variant.",
        },
        _png("green"),
        page_identity_resolver=resolver,
        page_identity_context={
            "identity_stage": "variant",
            "selected_page": {
                "page_name": "Stopwatch",
                "identity": "new",
            },
        },
    )

    assert requests[0]["registered_pages"] == []
    assert result.status == "new"
    assert result.data["page_name"] == "Stopwatch"
    assert result.data["variant_name"] == "initial_state"


def test_page_identity_has_no_interruption_identity_status() -> None:
    statuses = PAGE_IDENTITY_RESPONSE_SCHEMA["properties"]["status"]["enum"]

    assert statuses == ["known", "new", "uncertain"]
    assert PAGE_IDENTITY_RESPONSE_SCHEMA["properties"]["reason"][
        "minLength"
    ] == 1
    assert PAGE_IDENTITY_RESPONSE_SCHEMA["properties"]["variant_identity"][
        "enum"
    ] == ["known", "new", "uncertain"]
    assert "临时弹窗、提示或遮挡不是页面" in (
        PAGE_ONLY_IDENTITY_SPECIALIST_PROMPT)


def test_page_identity_without_reason_is_returned_as_uncertain() -> None:
    natural_map = NaturalExplorationMap()
    _observe(natural_map, "Chats", screenshot=_png("navy"))

    evidence = natural_map.call_tool(
        "page_identity",
        {
            "suspected_pages": ["Chats"],
            "proposed_new_name": "",
            "reason": "Check whether the dynamic chat list is the known Page.",
        },
        _png("orange"),
        page_identity_resolver=lambda _request: {
            "status": "known", "page_name": "Chats", "reason": "",
        },
    )

    assert evidence.status == "uncertain"
    assert evidence.data["reason"] == (
        "独立 Page Identity specialist 没有说明判断依据，页面身份保持未决。"
    )


def test_page_identity_allows_clear_root_page_without_old_candidates() -> None:
    requests = []

    def resolver(request):
        requests.append(request)
        return {
            "status": "new",
            "page_name": "Chats",
            "matched_page_name": "",
            "surface_kind": "page",
            "summary": "The initial chat list is visible.",
            "supporting_evidence": ["Chats title and chat list are visible."],
            "conflicting_evidence": [],
            "checked_candidates": [],
            "reason": "No page is registered yet and the foreground is clear.",
        }

    evidence = NaturalExplorationMap().call_tool(
        "page_identity",
        {
            "suspected_pages": ["Chats"],
            "proposed_new_name": "Chats",
            "reason": "Register the initial page.",
        },
        _png("white"),
        page_identity_resolver=resolver,
    )

    assert evidence.status == "new"
    assert evidence.data["page_name"] == "Chats"
    assert requests[0]["registered_page_count"] == 0
    assert requests[0]["registered_pages"] == []
    assert "specialist_prompt" not in requests[0]


def test_unknown_suspected_names_fall_back_to_registered_pages() -> None:
    natural_map = NaturalExplorationMap()
    _observe(natural_map, "Chats", screenshot=_png("navy"))
    requests = []

    def resolver(request):
        requests.append(request)
        return {
            "status": "known",
            "page_name": "Chats",
            "matched_page_name": "Chats",
            "surface_kind": "page",
            "summary": "The Chats page is visible.",
            "supporting_evidence": [],
            "conflicting_evidence": [],
            "checked_candidates": ["Chats"],
            "reason": "The registered Chats page matches.",
        }

    evidence = natural_map.call_tool(
        "page_identity",
        {
            "suspected_pages": ["unregistered alias"],
            "proposed_new_name": "Chats copy",
            "reason": "Resolve the landing.",
        },
        _png("blue"),
        page_identity_resolver=resolver,
    )

    assert evidence.status == "known"
    assert [item["page_name"] for item in requests[0]["registered_pages"]] == [
        "Chats"
    ]


def test_page_identity_without_resolver_is_honestly_uncertain() -> None:
    evidence = NaturalExplorationMap().call_tool(
        "page_identity",
        {
            "suspected_pages": [],
            "proposed_new_name": "Home",
            "reason": "No registered page appears to match.",
        },
        _png("white"),
    )

    assert evidence.status == "uncertain"
    assert evidence.data["page_name"] == ""
    assert "no model was called" in evidence.data["reason"]


def test_unresolved_identity_and_duplicate_new_name_do_not_pollute_map() -> None:
    natural_map = NaturalExplorationMap()
    _observe(natural_map, "Chats")

    _name, issue = natural_map.observe(
        name="Maybe Chats", summary="unclear", identity="uncertain",
        matched_page_name="Chats", surface_kind="page", regions=(),
        screenshot=_png("gray"))
    assert "uncertain" in issue
    assert natural_map.prompt_view()["current_page"] == ""
    assert len(natural_map.prompt_view()["pages"]) == 1

    _name, issue = natural_map.observe(
        name=" chats ", summary="different surface", identity="new",
        matched_page_name="", surface_kind="dialog", regions=(),
        screenshot=_png("black"))
    assert "existing natural name" in issue
    assert len(natural_map.prompt_view()["pages"]) == 1


def test_material_variants_are_page_scoped_and_fail_closed() -> None:
    natural_map = NaturalExplorationMap()
    page_name, issue = natural_map.observe(
        name="World",
        summary="World clock",
        identity="new",
        matched_page_name="",
        surface_kind="page",
        regions=(),
        screenshot=_png("white"),
        variant_name="world.empty",
        variant_identity="new",
        visible_predicates=["City list is empty"],
    )
    assert (page_name, issue) == ("World", "")
    first_id = natural_map.variant_id("World", "world.empty")

    page_name, issue = natural_map.observe(
        name="World",
        summary="World clock",
        identity="known",
        matched_page_name="World",
        surface_kind="dialog",
        regions=(),
        screenshot=_png("blue"),
        variant_name="world.add_dialog",
        variant_identity="new",
        visible_predicates=["City search input is visible"],
    )
    assert (page_name, issue) == ("World", "")
    second_id = natural_map.variant_id("World", "world.add_dialog")
    assert first_id and second_id and first_id != second_id
    assert len(natural_map.pages["World"]["variants"]) == 2
    assert "identity_status" not in natural_map.variant_facts(
        "World", "world.add_dialog")
    assert natural_map.variant_id("World", "world.unknown") == ""
    assert natural_map.variant_facts("World", "world.unknown") == {}


    _page_name, duplicate_issue = natural_map.observe(
        name="World",
        summary="World clock",
        identity="known",
        matched_page_name="World",
        surface_kind="dialog",
        regions=(),
        screenshot=_png("blue"),
        variant_name="world.add_dialog",
        variant_identity="new",
        visible_predicates=["City search input is visible"],
    )
    assert "reuses an existing natural name" in duplicate_issue
    assert len(natural_map.pages["World"]["variants"]) == 2

    _page_name, unknown_issue = natural_map.observe(
        name="World",
        summary="World clock",
        identity="known",
        matched_page_name="World",
        surface_kind="page",
        regions=(),
        screenshot=_png("green"),
        variant_name="world.unknown",
        variant_identity="known",
        visible_predicates=["Unknown state"],
    )
    assert "known variant is not registered" in unknown_issue
    assert len(natural_map.pages["World"]["variants"]) == 2


def test_page_map_does_not_bind_identity_by_screenshot_bytes() -> None:
    natural_map = NaturalExplorationMap()
    screenshot = _png("blue")
    _observe(natural_map, "Chats", screenshot=screenshot)

    assert not hasattr(natural_map, "exact_frame_page")
