from __future__ import annotations

import pytest

from gui_rewalk.src.core.visual_traversal.runtime.autonomous_region_tools import (
    AutonomousRegionRegistry,
    AutonomousRegionState,
    REGION_MAPPING_PROMPT,
    REGION_MAPPING_SCHEMA,
    REGION_REVIEW_PROMPT,
    REGION_REVIEW_SCHEMA,
    RegionProtocolError,
    StaleFrameError,
    _region_for_point,
)


def _update(
    state: AutonomousRegionState,
    frame_id: str,
    *,
    name: str = "Main",
    complete: bool,
    survey_memory: str = "",
) -> None:
    state.apply_agent_update([{
        "name": name,
        "summary": "Visible application content",
        "survey_memory": survey_memory,
        "bbox_1000": [0, 0, 1000, 1000],
        "coverage_complete": complete,
    }], frame_id=frame_id)


def test_region_reviewer_uses_shared_surface_and_stable_region_contract() -> None:
    assert "只根据本轮固定完整证据截图" in REGION_REVIEW_PROMPT
    assert "不做跨页面区域映射" in REGION_REVIEW_PROMPT
    assert "不是矩形范围、位置或单个按钮" in REGION_REVIEW_PROMPT
    assert "不能仅因动作不同或本次漏报就拆成新区域" in REGION_REVIEW_PROMPT
    assert "不得把只由一个控件构成的碎片改名" in REGION_REVIEW_PROMPT
    assert "单独占位或动作不同" in REGION_REVIEW_PROMPT
    assert "提案排除它们是正确的，不能据此报遗漏" in REGION_REVIEW_PROMPT
    assert "不是封闭清单" in REGION_REVIEW_PROMPT
    assert "所有属于目标应用的稳定功能区域" in REGION_REVIEW_PROMPT
    assert "常驻、全局、重复出现" in REGION_REVIEW_PROMPT
    assert "不能省略整条应用栏" in REGION_REVIEW_PROMPT
    assert "不能把它们写入区域摘要" in REGION_REVIEW_PROMPT
    assert "后方不接收交互" in REGION_REVIEW_PROMPT
    assert "不猜测被遮住的边界" in REGION_REVIEW_PROMPT
    assert "默认保留当前页面已经复核通过的区域划分" in REGION_REVIEW_PROMPT
    assert "局部增量处理" in REGION_REVIEW_PROMPT
    assert "不要枚举区域中的按钮、Entry、候选数量、代表操作" in (
        REGION_REVIEW_PROMPT)
    assert "每个精确旧名称恰好出现一次" in REGION_REVIEW_PROMPT
    assert "keep 和 remove 不携带 merged_into" in REGION_REVIEW_PROMPT
    assert set(REGION_REVIEW_SCHEMA["required"]) == {
        "regions", "revisions", "reason",
    }
    assert set(REGION_REVIEW_SCHEMA["properties"]) == {
        "regions", "revisions", "reason",
    }
    assert set(REGION_REVIEW_SCHEMA["properties"]["regions"]["items"][
        "properties"]) == {"name", "summary"}
    revision = REGION_REVIEW_SCHEMA["properties"]["revisions"]["items"]
    assert revision["required"] == ["old_region", "decision", "reason"]
    assert revision["additionalProperties"] is False


def test_batch_region_mapper_requires_complete_after_partition() -> None:
    assert "一对一、一对多、多对一或多对多" in REGION_MAPPING_PROMPT
    assert "不能单独证明两个区域相同" in REGION_MAPPING_PROMPT
    assert "不得因为覆盖了原区域的位置" in REGION_MAPPING_PROMPT
    assert "动作后的每个区域必须且只能出现一次" in REGION_MAPPING_PROMPT
    assert set(REGION_MAPPING_SCHEMA["required"]) == {
        "matches", "new", "uncertain",
    }
    assert set(REGION_MAPPING_SCHEMA["properties"]) == {
        "matches", "new", "uncertain",
    }


def test_simple_region_can_finish_from_one_main_agent_update() -> None:
    state = AutonomousRegionState()
    state.observe_frame("frame-a")

    _update(state, "frame-a", complete=True)

    snapshot = state.snapshot()
    assert snapshot["coverage_complete"] is True
    assert snapshot["regions"][0]["acceptance_status"] == "complete"
    assert "scans" not in snapshot
    assert "pending" not in snapshot
    assert snapshot["schema"] == "gui_rewalk.autonomous_regions.v6"


def test_long_region_stays_incomplete_until_main_agent_explicitly_finishes() -> None:
    state = AutonomousRegionState()
    state.observe_frame("frame-top", "state-settings")
    _update(
        state,
        "frame-top",
        complete=False,
        survey_memory=(
            "Started from Clock style; current open frontier continues down."),
    )

    state.observe_frame("frame-lower", "state-settings")
    retained_bbox = state.snapshot()["current_bboxes"]["main"]
    assert retained_bbox["frame_id"] == "frame-lower"
    assert retained_bbox["bbox_1000"] == [0.0, 0.0, 1000.0, 1000.0]
    _update(
        state,
        "frame-lower",
        complete=False,
        survey_memory=(
            "Continuous downward observations now reach Privacy; continue down."),
    )
    assert state.snapshot()["coverage_complete"] is False

    _update(state, "frame-lower", complete=True)

    snapshot = state.snapshot()
    assert snapshot["coverage_complete"] is True
    assert "observations" not in snapshot["regions"][0]
    assert snapshot["regions"][0]["last_incomplete_frame_id"] == ""
    assert snapshot["regions"][0]["survey_memory"] == (
        "Continuous downward observations now reach Privacy; continue down.")


def test_region_update_requires_current_frame_and_explicit_coverage() -> None:
    state = AutonomousRegionState()
    state.observe_frame("frame-a")

    with pytest.raises(StaleFrameError, match="stale frame"):
        _update(state, "frame-b", complete=False)

    with pytest.raises(RegionProtocolError, match="coverage_complete"):
        state.apply_agent_update([{
            "name": "Main",
            "bbox_1000": [0, 0, 1000, 1000],
        }], frame_id="frame-a")


def test_restore_keeps_region_facts_but_drops_old_frame_geometry() -> None:
    state = AutonomousRegionState.from_snapshot({
        "regions": [{
            "name": "Main",
            "summary": "Saved facts",
            "survey_memory": "Reached About; no unresolved survey direction.",
            "coverage_complete": True,
        }],
        "current_bboxes": {
            "main": {"frame_id": "old", "bbox_1000": [0, 0, 1000, 1000]},
        },
    })

    snapshot = state.snapshot()
    assert snapshot["coverage_complete"] is True
    assert snapshot["current_bboxes"] == {}
    assert snapshot["regions"][0]["survey_memory"] == (
        "Reached About; no unresolved survey direction.")
    assert "scroll_survey_memory" not in snapshot
    assert "scroll_frontier_reviewed" not in snapshot


def test_new_incomplete_region_reopens_page_coverage_without_erasing_memory() -> None:
    state = AutonomousRegionState()
    state.observe_frame("frame-a")
    _update(
        state, "frame-a", complete=True,
        survey_memory="Main content was fully observed.",
    )

    _update(state, "frame-a", name="Footer", complete=False)

    snapshot = state.snapshot()
    assert snapshot["coverage_complete"] is False
    assert snapshot["regions"][0]["survey_memory"] == (
        "Main content was fully observed.")


def test_region_registry_merges_only_an_explicit_agent_reference() -> None:
    registry = AutonomousRegionRegistry()
    first_ref, merged = registry.bind(
        page_name="Today overview",
        region_name="Team inbox",
        summary="Questions awaiting review",
    )
    separate_ref, merged_second = registry.bind(
        page_name="Project workspace",
        region_name="Team inbox",
        summary="Same visible title but not yet judged",
    )

    assert first_ref != separate_ref
    assert merged == merged_second == ""

    reused_ref, merged_old = registry.bind(
        page_name="Project workspace",
        region_name="Team inbox",
        equivalent_to_region_ref=first_ref,
        reason="The visible content and function entries are the same.",
    )

    assert reused_ref == first_ref
    assert merged_old == separate_ref
    assert len(registry.snapshot()["groups"]) == 1
    assert registry.region_ref(
        "Project workspace", "Team inbox") == first_ref


def test_region_registry_snapshot_round_trip_keeps_natural_occurrences() -> None:
    registry = AutonomousRegionRegistry()
    region_ref, _ = registry.bind(
        page_name="Today overview", region_name="Team inbox",
        variant_name="inbox-visible")
    registry.bind(
        page_name="Project workspace",
        region_name="Team inbox",
        equivalent_to_region_ref=region_ref,
        reason="Agent-confirmed shared Region",
    )

    restored = AutonomousRegionRegistry.from_snapshot(registry.snapshot())

    assert restored.region_ref("Today overview", "Team inbox") == region_ref
    assert restored.region_ref(
        "Project workspace", "Team inbox") == region_ref
    occurrence = restored.snapshot()["groups"][0]["occurrences"][0]
    assert occurrence["representative_variant_name"] == "inbox-visible"


def test_region_registry_accumulates_exact_state_occurrences_through_merge(
) -> None:
    registry = AutonomousRegionRegistry()
    shared_ref, _ = registry.bind(
        page_name="World",
        region_name="Toolbar",
        state_id="state-empty",
    )
    registry.mark_state_visible(
        page_name="World", region_name="Toolbar", state_id="state-empty")
    registry.bind(
        page_name="World",
        region_name="Toolbar",
        state_id="state-populated",
    )
    separate_ref, _ = registry.bind(
        page_name="Dialog",
        region_name="Toolbar",
        state_id="state-dialog",
    )
    registry.mark_state_visible(
        page_name="Dialog", region_name="Toolbar", state_id="state-dialog")
    assert separate_ref != shared_ref
    registry.bind(
        page_name="Dialog",
        region_name="Toolbar",
        state_id="state-results",
        equivalent_to_region_ref=shared_ref,
    )

    snapshot = registry.snapshot()
    assert snapshot["schema"] == "gui_rewalk.autonomous_region_groups.v6"
    occurrences = snapshot["groups"][0]["occurrences"]
    by_page = {item["page_name"]: item["state_ids"] for item in occurrences}
    assert by_page == {
        "World": ["state-empty", "state-populated"],
        "Dialog": ["state-dialog", "state-results"],
    }
    visible_by_page = {
        item["page_name"]: item["visible_state_ids"]
        for item in occurrences
    }
    assert visible_by_page == {
        "World": ["state-empty"],
        "Dialog": ["state-dialog"],
    }

    restored = AutonomousRegionRegistry.from_snapshot(snapshot)
    assert restored.has_state_occurrence("World", "state-empty")
    assert restored.has_state_occurrence("World", "state-populated")
    assert restored.has_state_occurrence("Dialog", "state-results")
    restored_occurrences = restored.snapshot()["groups"][0]["occurrences"]
    assert {
        item["page_name"]: item["visible_state_ids"]
        for item in restored_occurrences
    } == visible_by_page


def test_shared_region_coverage_versions_require_the_same_entry_signature() -> None:
    registry = AutonomousRegionRegistry()
    region_ref, _ = registry.bind(
        page_name="Clock", region_name="Navigation", state_id="state-clock")
    registry.bind(
        page_name="Alarm", region_name="Navigation", state_id="state-alarm",
        equivalent_to_region_ref=region_ref)

    version = registry.publish_coverage(
        region_ref=region_ref,
        page_name="Clock",
        region_name="Navigation",
        state_id="state-clock",
        frame_id="frame-clock",
        entry_signature=["control:alarm", "control:timer"],
    )

    assert version == 1
    assert registry.mapped_coverage_version(
        region_ref=region_ref,
        source_page="Clock",
        source_region="Navigation",
        target_page="Alarm",
        target_region="Navigation",
        entry_signature=["control:timer", "control:alarm"],
    ) == 1
    assert registry.mapped_coverage_version(
        region_ref=region_ref,
        source_page="Clock",
        source_region="Navigation",
        target_page="Alarm",
        target_region="Navigation",
        entry_signature=["control:alarm", "control:stopwatch"],
    ) == 0
    assert registry.inherit_mapped_coverage(
        region_ref=region_ref,
        source_page="Clock",
        source_region="Navigation",
        target_page="Alarm",
        target_region="Navigation",
        entry_signature=["control:alarm", "control:timer"],
    ) == 1

    restored = AutonomousRegionRegistry.from_snapshot(registry.snapshot())
    group = restored.snapshot()["groups"][0]
    assert group["coverage_versions"][0]["entry_signature"] == [
        "control:alarm", "control:timer",
    ]
    by_page = {
        item["page_name"]: item for item in group["occurrences"]
    }
    assert by_page["Clock"]["coverage_basis"] == "visual_entry_reviewer"
    assert by_page["Alarm"]["coverage_basis"] == "batch_region_mapping"


def test_region_group_tracks_independent_occurrences_and_local_transition(
) -> None:
    registry = AutonomousRegionRegistry()
    region_ref, _ = registry.bind(
        page_name="Alarm", region_name="Alarm item 8:30",
        state_id="alarm-collapsed")
    registry.bind(
        page_name="Alarm", region_name="Alarm item 9:00",
        state_id="alarm-collapsed", equivalent_to_region_ref=region_ref)
    navigation_ref, _ = registry.bind(
        page_name="Alarm", region_name="Navigation",
        state_id="alarm-collapsed")

    transition = registry.record_local_transition(
        page_name="Alarm",
        region_name="Alarm item 8:30",
        source_state_id="alarm-collapsed",
        destination_state_id="alarm-expanded",
        trigger_entry_id="ae1",
        effect_text="Alarm item expanded and revealed its edit controls.",
        effect_kind="structure",
        evidence_action_id="attempt-1",
    )

    snapshot = registry.snapshot()
    group = next(
        item for item in snapshot["groups"]
        if item["region_ref"] == region_ref)
    by_name = {
        item["region_name"]: item for item in group["occurrences"]
    }
    assert by_name["Alarm item 8:30"]["occurrence_ref"] != (
        by_name["Alarm item 9:00"]["occurrence_ref"])
    assert by_name["Alarm item 9:00"][
        "inference_source_occurrence_ref"] == group[
            "representative_occurrence_ref"]
    assert transition is not None
    assert transition["effects"] == [{
        "scope": by_name["Alarm item 8:30"]["occurrence_ref"],
        "kind": "structure",
    }]
    assert by_name["Alarm item 8:30"]["state_by_page_state"][
        "alarm-expanded"] != by_name["Alarm item 8:30"][
            "state_by_page_state"]["alarm-collapsed"]
    assert by_name["Alarm item 9:00"]["state_by_page_state"][
        "alarm-expanded"] == by_name["Alarm item 9:00"][
            "state_by_page_state"]["alarm-collapsed"]
    navigation = next(
        item for item in snapshot["groups"]
        if item["region_ref"] == navigation_ref)["occurrences"][0]
    assert navigation["state_by_page_state"]["alarm-expanded"] == (
        navigation["state_by_page_state"]["alarm-collapsed"])

    restored = AutonomousRegionRegistry.from_snapshot(snapshot)
    assert restored.snapshot() == snapshot


def test_region_bbox_is_bound_to_state_even_when_frame_hash_matches() -> None:
    state = AutonomousRegionState()
    state.observe_frame("same-frame", "state-a")
    state.apply_agent_update([{
        "name": "Toolbar",
        "summary": "Stable controls",
        "bbox_1000": [0, 0, 1000, 100],
        "coverage_complete": False,
    }], frame_id="same-frame")
    bbox = state.snapshot()["current_bboxes"]["toolbar"]
    assert bbox["state_id"] == "state-a"

    assert state.observe_frame("same-frame", "state-b") == {"changed": True}
    assert state.snapshot()["current_bboxes"] == {}


def test_region_bbox_survives_passive_pixel_changes_in_same_state() -> None:
    state = AutonomousRegionState()
    state.observe_frame("frame-before-passive-change", "state-search-dialog")
    state.apply_agent_update([{
        "name": "Search Results",
        "summary": "Search field and result surface",
        "bbox_1000": [300, 200, 700, 800],
        "coverage_complete": True,
    }], frame_id="frame-before-passive-change")

    assert state.observe_frame(
        "frame-after-passive-change", "state-search-dialog",
    ) == {"changed": True}

    bbox = state.snapshot()["current_bboxes"]["search results"]
    assert bbox["frame_id"] == "frame-after-passive-change"
    assert bbox["state_id"] == "state-search-dialog"
    assert _region_for_point(state, [500, 300]) == "Search Results"
