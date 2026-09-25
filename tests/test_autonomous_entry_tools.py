"""Offline contracts for autonomous entry discovery and action evidence."""

from __future__ import annotations

import pytest

from gui_rewalk.src.core.visual_traversal.runtime.autonomous_entry_tools import (
    AutonomousEntryLedger,
    EntryStatus,
)
from gui_rewalk.src.core.visual_traversal.runtime.autonomous_entry_commit import (
    _coverage_entry_signature,
)


def _record(ledger, observations, *, region="List", frame="frame-1"):
    return ledger.record_agent_update(
        page_name="Chats",
        region_name=region,
        frame_id=frame,
        observations=observations,
    )


def _append_legacy_direct_backfill(
    payload,
    *,
    entry_id="ae99",
    action_id="aa99",
    page_name="Settings",
    region_name="full_screen",
    target="Legacy direct action",
    status="attempted",
    pending=True,
    task_eligible=False,
):
    payload.setdefault("entries", []).append({
        "entry_id": entry_id,
        "page_name": page_name,
        "region_name": region_name,
        "target": target,
        "control_type": "control",
        "status": status,
        "discovery_source": "direct_action_backfill",
        "task_eligible": task_eligible,
    })
    if pending:
        payload.setdefault("pending_actions", []).append({
            "action_id": action_id,
            "entry_id": entry_id,
            "frame_id": "legacy-frame",
            "backfilled": True,
        })
    return entry_id


def test_temporary_bbox_is_observation_evidence_and_not_resumed() -> None:
    ledger = AutonomousEntryLedger()
    _record(ledger, [{
        "target": "Search",
        "bbox_1000": [100, 200, 300, 400],
    }], frame="frame-a")

    record = ledger.get("ae1")
    assert record.temporary_bbox_1000 == (100.0, 200.0, 300.0, 400.0)
    assert record.bbox_frame_id == "frame-a"

    restored = AutonomousEntryLedger.from_snapshot(ledger.snapshot())

    assert restored.get("ae1").temporary_bbox_1000 is None
    assert restored.get("ae1").bbox_frame_id == ""


def test_record_only_operation_is_persisted_without_becoming_a_task() -> None:
    ledger = AutonomousEntryLedger()
    _record(ledger, [{
        "target": "Next item",
        "operation": "activate",
        "subject": "Current content",
        "exploration_policy": "record_only",
    }])

    record = ledger.get("ae1")
    assert record.status is EntryStatus.RECORDED
    assert record.task_eligible is False
    assert record.exploration_policy == "record_only"
    assert ledger.task_candidates() == ()

    restored = AutonomousEntryLedger.from_snapshot(ledger.snapshot())
    restored_record = restored.get("ae1")
    assert restored.snapshot()["schema"] == "gui_rewalk.autonomous_entries.v8"
    assert restored_record.status is EntryStatus.RECORDED
    assert restored_record.task_eligible is False


def test_coverage_signature_keeps_distinct_visible_entry_targets(
) -> None:
    assert _coverage_entry_signature([
        {
            "target": "Primary trigger",
            "operation": "Open item",
            "subject": "Item",
        },
        {
            "target": "Secondary trigger",
            "operation": "Open item",
            "subject": "Item",
        },
        {
            "target": "Primary trigger",
            "operation": "Select item",
            "subject": "Item",
        },
    ]) == [
        "open item:primary trigger",
        "open item:secondary trigger",
        "select item:primary trigger",
    ]


def test_same_semantic_target_keeps_distinct_operations() -> None:
    ledger = AutonomousEntryLedger()

    click = _record(ledger, [{
        "target": "Message row",
        "operation": "open message",
    }])
    long_press = _record(ledger, [{
        "target": "Message row",
        "operation": "select message",
        "subject": "Selection mode",
        "control_type": "input",
    }])

    assert click.added == ["ae1"]
    assert long_press.added == ["ae2"]
    assert [entry.operation for entry in ledger.entries] == [
        "open message", "select message",
    ]


def test_same_text_in_different_regions_is_not_automatically_merged() -> None:
    ledger = AutonomousEntryLedger()
    _record(ledger, [{"target": "More"}], region="Header")
    delta = _record(ledger, [{"target": "More"}], region="Card")

    assert [item.entry_id for item in ledger.entries] == ["ae1", "ae2"]
    assert delta.added == ["ae2"]


def test_explicit_action_requires_a_registered_entry() -> None:
    ledger = AutonomousEntryLedger()

    with pytest.raises(KeyError, match="unknown autonomous entry"):
        ledger.begin_explicit_action(
            "ae1", frame_id="frame-1", page_name="Chats")

    assert ledger.entries == ()


def test_explicit_action_binds_only_the_existing_entry_id() -> None:
    ledger = AutonomousEntryLedger()
    ledger.record_agent_update(
        page_name="Chats",
        region_name="Alarm List",
        frame_id="frame-1",
        source_state_id="page-state-a",
        owner_region_ref="rg1",
        representative_occurrence_ref="ro1",
        required_state_ref="rs1",
        observations=[{
            "target": "8:30 AM Expand Button",
            "bbox_1000": [800, 100, 950, 200],
        }],
    )

    pending = ledger.begin_explicit_action(
        "ae1", frame_id="frame-1", page_name="Chats",
        source_state_id="page-state-b")
    inherited = ledger.inherit_region_state_entries(
        region_ref="rg1",
        source_state_ref="rs1",
        destination_state_ref="rs2",
    )

    assert pending.entry_id == "ae1"
    assert pending.frame_id == "frame-1"
    assert len(ledger.entries) == 1
    assert ledger.get("ae1").target == "8:30 AM Expand Button"
    assert ledger.get("ae1").source_state_ids == [
        "page-state-a", "page-state-b"]
    assert inherited == ("ae1",)
    assert ledger.get("ae1").required_states == ["rs1", "rs2"]


def test_without_executed_verified_result_action_remains_unresolved() -> None:
    ledger = AutonomousEntryLedger()
    entry_id = _record(
        ledger, [{"target": "New chat"}], region="Header").added[0]
    pending = ledger.begin_explicit_action(
        entry_id, frame_id="frame-1", page_name="Chats")

    finished = ledger.finish_action(
        pending.action_id,
        action_executed=False,
        outcome_verified=True,
        result="dispatch failed",
    )

    assert finished.status == EntryStatus.UNRESOLVED
    assert [item.entry_id for item in ledger.task_candidates()] == [entry_id]


def test_independently_unsafe_entry_stays_unresolved_but_is_not_rescheduled() -> None:
    ledger = AutonomousEntryLedger()
    entry_id = _record(ledger, [{"target": "Delete Button"}]).added[0]

    record = ledger.mark_unsafe_to_execute(
        entry_id, reason="The click itself may delete user data.")

    assert record.status == EntryStatus.UNRESOLVED
    assert record.task_eligible is False
    assert record.last_result == "The click itself may delete user data."
    assert ledger.task_candidates() == ()


def test_exact_no_effect_probe_stays_unresolved_without_redispatch() -> None:
    ledger = AutonomousEntryLedger()
    entry_id = _record(ledger, [{"target": "Recipe card"}]).added[0]

    record = ledger.mark_no_effect_probe(
        entry_id,
        result="Exact target probed; no visible effect.",
        classification="not_interactive",
    )

    assert record.status == EntryStatus.UNRESOLVED
    assert record.task_eligible is False
    assert record.last_result == "Exact target probed; no visible effect."
    assert record.recent_results[-1]["classification"] == "not_interactive"
    assert ledger.task_candidates() == ()
    restored = AutonomousEntryLedger.from_snapshot(ledger.snapshot())
    restored_result = restored.get(entry_id).recent_results[-1]
    assert restored_result == record.recent_results[-1]
    assert restored_result["classification"] == "not_interactive"
    assert restored.task_candidates() == ()


def test_agent_can_report_one_group_with_equivalent_occurrences() -> None:
    ledger = AutonomousEntryLedger()
    delta = _record(ledger, [
        {
            "target": "Open a conversation detail",
            "equivalent_occurrences": [
                {"target": "Bob"},
                {"target": "Carol"},
            ],
        },
    ])

    assert delta.added == ["ae1"]
    assert delta.matched == []
    assert len(ledger.entries) == 1
    entry = ledger.get("ae1")
    assert entry.observation_count == 1
    assert [item["target"] for item in entry.equivalent_occurrences] == [
        "Bob", "Carol",
    ]


def test_same_words_do_not_imply_equivalence_without_agent_relation() -> None:
    ledger = AutonomousEntryLedger()
    _record(ledger, [{"target": "Settings"}], region="Header")
    _record(ledger, [{"target": "Settings"}], region="Footer")

    assert [item.entry_id for item in ledger.entries] == ["ae1", "ae2"]
    assert all(not item.representative_entry_id for item in ledger.entries)


def test_resume_reopens_only_registered_interrupted_entry_as_a_task() -> None:
    ledger = AutonomousEntryLedger()
    registered_delta = _record(
        ledger,
        [{"target": "Open details"}],
        region="Conversation list",
        frame="frame-1",
    )
    registered_id = registered_delta.added[0]
    ledger.begin_explicit_action(
        registered_id, frame_id="frame-1", page_name="Chats")
    payload = ledger.snapshot()
    legacy_id = _append_legacy_direct_backfill(
        payload,
        entry_id="ae2",
        action_id="aa2",
        page_name="Chats",
        region_name="Header",
        target="Transient navigation",
    )

    restored = AutonomousEntryLedger.from_snapshot(
        payload, prior_action_ids=["aa7"])

    record = restored.get(legacy_id)
    assert record.status == EntryStatus.UNRESOLVED
    assert record.task_eligible is False
    assert record.temporary_bbox_1000 is None
    assert [item.entry_id for item in restored.task_candidates()] == [
        registered_id,
    ]
    retried = restored.begin_explicit_action(
        registered_id, frame_id="frame-2", page_name="Chats")
    assert retried.action_id == "aa8"


def test_resume_clears_every_legacy_direct_backfill_task_flag() -> None:
    payload = {"entries": [], "pending_actions": [], "next_action": 1}
    legacy_id = _append_legacy_direct_backfill(
        payload,
        page_name="Settings",
        region_name="full_screen",
        target="Back Button",
        status="verified",
        pending=False,
        task_eligible=True,
    )
    payload["entries"][0]["status"] = "verified"
    payload["entries"][0]["last_result"] = "Returned to Clock"
    payload["entries"][0]["destination_page"] = "Clock"

    restored = AutonomousEntryLedger.from_snapshot(payload)

    assert restored.get(legacy_id).task_eligible is False
    assert restored.task_candidates() == ()


def test_agent_page_update_allocates_entry_id_without_model_id() -> None:
    ledger = AutonomousEntryLedger()

    delta = ledger.record_agent_update(
        page_name="Home",
        region_name="Main",
        frame_id="frame-1",
        observations=[{
            "region_name": "Main",
            "target": "Open details",
            "bbox_1000": [100, 200, 300, 400],
        }],
    )

    assert delta.added == ["ae1"]
    assert ledger.get("ae1").target == "Open details"


def test_agent_page_update_exact_repeat_is_idempotent() -> None:
    ledger = AutonomousEntryLedger()
    first = ledger.record_agent_update(
        page_name="Home",
        region_name="Main",
        frame_id="frame-1",
        observations=[{
            "region_name": "Main",
            "target": "Open details",
            "bbox_1000": [100, 200, 300, 400],
        }],
    )
    repeated = ledger.record_agent_update(
        page_name=" home ",
        region_name=" main ",
        frame_id="frame-2",
        observations=[{
            "region_name": "main",
            "target": " open   DETAILS ",
            "bbox_1000": [110, 210, 310, 410],
        }],
    )
    other_region = ledger.record_agent_update(
        page_name="Home",
        region_name="Footer",
        frame_id="frame-2",
        observations=[{
            "region_name": "Footer", "target": "Open details",
        }],
    )

    assert first.added == ["ae1"]
    assert repeated.added == []
    assert repeated.matched == ["ae1"]
    assert ledger.get("ae1").temporary_bbox_1000 == (
        110.0, 210.0, 310.0, 410.0)
    assert ledger.get("ae1").observation_count == 2
    assert other_region.added == ["ae2"]
    assert [entry.entry_id for entry in ledger.entries] == ["ae1", "ae2"]


def test_agent_page_update_exact_repeat_preserves_retired_state_and_occurrences(
) -> None:
    ledger = AutonomousEntryLedger()
    ledger.record_agent_update(
        page_name="Home",
        region_name="Main",
        frame_id="frame-1",
        observations=[{
            "target": "Open details",
            "bbox_1000": [100, 200, 300, 400],
            "equivalent_occurrences": [{
                "target": "Second details card",
                "bbox_1000": [500, 200, 700, 400],
            }],
        }],
    )
    ledger.mark_no_effect_probe(
        "ae1",
        result="Exact target probed; no visible effect.",
        classification="temporarily_unavailable",
    )

    repeated = ledger.record_agent_update(
        page_name="Home",
        region_name="Main",
        frame_id="frame-2",
        observations=[{
            "target": "Open details",
            "bbox_1000": [110, 210, 310, 410],
        }],
    )

    record = ledger.get("ae1")
    assert repeated.matched == ["ae1"]
    assert record.status == EntryStatus.UNRESOLVED
    assert record.task_eligible is False
    assert record.last_result == "Exact target probed; no visible effect."
    assert record.recent_results[-1]["classification"] == (
        "temporarily_unavailable"
    )
    assert record.equivalent_occurrences == [{
        "target": "Second details card",
        "bbox_1000": [500.0, 200.0, 700.0, 400.0],
    }]


def test_entry_occurrences_accumulate_states_and_resume_without_stale_bbox(
) -> None:
    ledger = AutonomousEntryLedger()
    ledger.record_agent_update(
        page_name="World",
        region_name="Dialog",
        frame_id="frame-a",
        source_state_id="state-a",
        owner_region_ref="rg1",
        representative_occurrence_ref="ro1",
        required_state_ref="rs1",
        observations=[{
            "target": "Dismiss",
            "operation": "Dismiss dialog",
            "subject": "Dialog",
            "equivalent_occurrences": [{
                "target": "Second dismiss",
                "bbox_1000": [500, 100, 700, 200],
            }],
        }],
    )
    repeated = ledger.record_agent_update(
        page_name="World",
        region_name="Dialog",
        frame_id="frame-b",
        source_state_id="state-b",
        owner_region_ref="rg1",
        representative_occurrence_ref="ro1",
        required_state_ref="rs2",
        observations=[{
            "target": "Dismiss",
            "operation": "Dismiss dialog",
            "subject": "Dialog",
        }],
    )

    record = ledger.get("ae1")
    assert repeated.matched == ["ae1"]
    assert record.source_state_id == "state-a"
    assert record.source_state_ids == ["state-a", "state-b"]
    assert record.owner_region_ref == "rg1"
    assert record.representative_occurrence_ref == "ro1"
    assert record.required_states == ["rs1", "rs2"]

    snapshot = ledger.snapshot()
    assert snapshot["schema"] == "gui_rewalk.autonomous_entries.v8"
    assert snapshot["entries"][0]["operation"] == "Dismiss dialog"
    assert snapshot["entries"][0]["subject"] == "Dialog"
    assert snapshot["entries"][0]["equivalent_occurrences"] == [{
        "target": "Second dismiss"}]
    restored = AutonomousEntryLedger.from_snapshot(snapshot).get("ae1")
    assert restored.source_state_ids == ["state-a", "state-b"]
    assert restored.required_states == ["rs1", "rs2"]
    assert restored.operation == "Dismiss dialog"
    assert restored.subject == "Dialog"
    assert restored.equivalent_occurrences == [{"target": "Second dismiss"}]

    legacy = AutonomousEntryLedger.from_snapshot({
        "schema": "gui_rewalk.autonomous_entries.v3",
        "entries": [{
            "entry_id": "ae7",
            "page_name": "World",
            "region_name": "Toolbar",
            "target": "Add",
            "source_state_id": "legacy-state",
        }],
    }).get("ae7")
    assert legacy.source_state_ids == ["legacy-state"]
    assert legacy.operation == "Add"
    assert legacy.subject == "Toolbar"


def test_agent_page_update_near_synonym_remains_a_new_entry() -> None:
    ledger = AutonomousEntryLedger()
    ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id="frame-1",
        observations=[{"target": "Open details"}],
    )

    second = ledger.record_agent_update(
        page_name="Home", region_name="Main", frame_id="frame-2",
        observations=[{"target": "Open detail panel"}],
    )

    assert second.added == ["ae2"]
    assert second.matched == []
    assert [entry.target for entry in ledger.entries] == [
        "Open details", "Open detail panel",
    ]


def test_agent_page_update_rejects_model_supplied_entry_id() -> None:
    ledger = AutonomousEntryLedger()

    with pytest.raises(ValueError, match="unsupported fields.*entry_id"):
        ledger.record_agent_update(
            page_name="Home",
            region_name="Main",
            frame_id="frame-1",
            observations=[{
                "region_name": "Main",
                "target": "Open details",
                "entry_id": "ae13",
            }],
        )

    assert ledger.entries == ()


def test_agent_page_update_can_link_to_preexisting_representative() -> None:
    ledger = AutonomousEntryLedger()
    _record(ledger, [{"target": "Open details"}], region="Main")
    pending = ledger.begin_explicit_action(
        "ae1", frame_id="frame-1", page_name="Chats")
    ledger.finish_action(
        pending.action_id,
        action_executed=True,
        outcome_verified=True,
        result="Details opened",
        destination_page="Details",
        destination_state_id="state-details",
    )

    delta = ledger.record_agent_update(
        page_name="Home",
        region_name="Main",
        frame_id="frame-2",
        observations=[{
            "region_name": "Main",
            "target": "Open the same details from the footer",
            "equivalent_to_entry_id": "ae1",
        }],
    )

    assert delta.added == ["ae2"]
    linked = ledger.get("ae2")
    assert linked.representative_entry_id == "ae1"
    assert linked.status == EntryStatus.INFERRED
    assert linked.destination_page == "Details"


def test_agent_page_update_does_not_reuse_an_unverified_representative() -> None:
    ledger = AutonomousEntryLedger()
    _record(ledger, [{"target": "Open details"}], region="Main")

    with pytest.raises(
        ValueError, match="must reference the same committed shared Region",
    ):
        ledger.record_agent_update(
            page_name="Home",
            region_name="Main",
            frame_id="frame-2",
            observations=[{
                "region_name": "Main",
                "target": "Open the same details from the footer",
                "equivalent_to_entry_id": "ae1",
            }],
        )

    assert [entry.entry_id for entry in ledger.entries] == ["ae1"]


def test_invalidated_entry_keeps_discovery_evidence_without_rescheduling() -> None:
    ledger = AutonomousEntryLedger()
    entry_id = ledger.record_agent_update(
        page_name="Home",
        region_name="Main",
        frame_id="frame-1",
        source_state_id="state-home",
        discovery_screenshot_path="entry_discovery_frames/000001/screenshot.png",
        observations=[{"target": "Unknown icon"}],
    ).added[0]

    record = ledger.mark_invalidated(
        entry_id,
        reason="Neither the discovery frame nor the current frame shows it.",
    )
    restored = AutonomousEntryLedger.from_snapshot(ledger.snapshot()).get(
        entry_id)

    assert record.status == EntryStatus.INVALIDATED
    assert record.task_eligible is False
    assert restored.status == EntryStatus.INVALIDATED
    assert restored.task_eligible is False
    assert restored.discovery_screenshot_path.endswith("screenshot.png")
