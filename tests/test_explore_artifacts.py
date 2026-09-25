"""Existing modular exploration contracts: artifacts."""


import json

from gui_rewalk.src.core.explore.artifacts import ArtifactStore
from gui_rewalk.src.core.explore.bundle import (
    _build_graph,
    _entry_snapshot,
    _projected_region_names,
    _region_route_snapshot,
    compile_modular_bundle,
)
from gui_rewalk.src.core.explore.models import (
    Operation,
    PageState,
    RegionOccurrence,
    RegionVariant,
)

from .explore_fixtures import (
    _contextual_region_route_ledger,
    _parameter_ledger,
    _region_reveal_runtime,
    _seed_ledger,
)


def test_artifact_store_continues_frame_numbers_without_overwrite(tmp_path):
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    (screenshots / "frame_00001.png").write_bytes(b"first")
    (screenshots / "frame_00003.png").write_bytes(b"third")

    store = ArtifactStore(str(tmp_path))
    saved = store.save_frame(b"fourth")

    assert saved == "screenshots/frame_00004.png"
    assert (screenshots / "frame_00001.png").read_bytes() == b"first"
    assert (screenshots / "frame_00003.png").read_bytes() == b"third"
    assert (screenshots / "frame_00004.png").read_bytes() == b"fourth"


def test_parameter_confirmation_is_projected_to_canonical_entry():
    ledger = _parameter_ledger("unknown")
    operation = next(iter(ledger.operations.values()))
    operation.parameter_status = "observed"
    operation.parameter_summary = "可选 Control volume、Snooze、Dismiss"
    operation.parameter_evidence_refs = ["screenshots/selector.png"]

    entries, _ = _entry_snapshot(ledger, _projected_region_names(ledger))
    entry = entries["entries"][0]

    assert entry["parameter_status"] == "observed"
    assert entry["parameter_summaries"] == [
        "可选 Control volume、Snooze、Dismiss"]
    assert entry["parameter_evidence_refs"] == ["screenshots/selector.png"]
    assert entry["parameter_conflict"] is False


def test_conflicting_parameter_bindings_are_visible_in_bundle_projection():
    ledger = _parameter_ledger("none")
    first = next(iter(ledger.operations.values()))
    identity = ledger.canonical_operations[first.canonical_operation_id]
    second = Operation(
        operation_id="o-conflict",
        region_id=first.region_id,
        action=first.action,
        target=first.target,
        status="verified",
        canonical_operation_id=identity.canonical_operation_id,
        parameter_status="observed",
        parameter_summary="可选 Control volume、Snooze、Dismiss",
        parameter_evidence_refs=["screenshots/selector.png"],
        source_occurrence_ids=list(first.source_occurrence_ids),
        variant_id=first.variant_id,
    )
    ledger.operations[second.operation_id] = second
    identity.operation_ids.append(second.operation_id)

    entries, _ = _entry_snapshot(ledger, _projected_region_names(ledger))

    assert entries["entries"][0]["parameter_conflict"] is True


def test_bundle_projects_revealed_regions_on_the_existing_action_edge(tmp_path):
    runtime, _payload = _region_reveal_runtime()
    ledger = runtime.ledger
    ledger.transitions[0].revealed_region_ids = ["r2"]
    ledger.transitions[0].hidden_region_ids = ["r1"]

    graph = _build_graph(
        ledger,
        output_root=tmp_path,
        app_name="test-app",
        entry_lookup={},
        stop_reason="complete",
    )

    edge = graph.action_edges[0]
    assert edge["region"] == "r1"
    assert edge["attempts"][0]["evidence"]["revealed_region_refs"] == ["r2"]
    assert edge["attempts"][0]["evidence"]["hidden_region_refs"] == ["r1"]


def test_region_route_bundle_groups_pages_and_preserves_context_evidence():
    ledger = _contextual_region_route_ledger()
    world_transition = next(
        item for item in ledger.transitions if item.transition_id == "e-world")
    original_revealed = list(world_transition.revealed_region_ids)
    original_hidden = list(world_transition.hidden_region_ids)

    snapshot = _region_route_snapshot(ledger)

    assert snapshot["schema"] == "modular_region_routes.v1"
    world = next(
        item for item in snapshot["page_region_groups"]
        if item["page_ref"] == "p-world")
    assert world["region_refs"] == [
        "r-nav", "r-world-body", "r-world-dialog"]
    relation = next(
        item for item in snapshot["relations"]
        if item["evidence_transition_ref"] == "e-world")
    assert relation["source_region_ref"] == "r-nav"
    assert relation["source_variant_ref"] == "rv-nav-world"
    assert relation["canonical_operation_ref"] == "co-world"
    assert relation["revealed_region_refs"] == ["r-world-dialog"]
    assert relation["hidden_region_refs"] == ["r-nav", "r-world-body"]
    assert relation["evidence_attempt_ref"] == "a-world"
    assert world_transition.revealed_region_ids == original_revealed
    assert world_transition.hidden_region_ids == original_hidden


def test_compile_modular_bundle_writes_region_route_artifact(
    tmp_path, monkeypatch,
):
    ledger = _contextual_region_route_ledger()
    monkeypatch.setattr(
        "gui_rewalk.src.core.scenario.capability_induction."
        "compile_collection_bundle",
        lambda *_args, **_kwargs: {
            "annotated_graph_path": "annotated.json",
            "capability_graph_path": "capabilities.json",
        },
    )

    result = compile_modular_bundle(
        ledger,
        output_root=str(tmp_path),
        app_name="clock",
        stop_reason="complete",
    )

    path = tmp_path / "modular_region_routes.json"
    assert result["region_routes_path"] == str(path)
    assert json.loads(path.read_text(encoding="utf-8"))["relations"]


def test_bundle_projects_shared_operation_once_per_page():
    ledger = _seed_ledger()
    ledger.states["s2"] = PageState(
        state_id="s2", page_id="p1", name="运行状态", summary="秒表运行中",
        screenshot_ref="screenshots/second.png", region_occurrence_ids=["ro2"],
        survey_complete=True, inventory_passes=1,
    )
    ledger.pages["p1"].state_ids.append("s2")
    ledger.occurrences["ro2"] = RegionOccurrence(
        occurrence_id="ro2", region_id="r1", state_id="s2",
        name="运行时控制区", summary="同一秒表控制组件的运行状态",
        variant_id="rv2",
    )
    ledger.regions["r1"].occurrence_ids.append("ro2")
    ledger.regions["r1"].variant_ids.append("rv2")
    ledger.regions["r1"].operation_ids.append("o2")
    ledger.region_variants["rv2"] = RegionVariant(
        "rv2", "r1", ["ro2"], ["o2"])
    ledger.operations["o2"] = Operation(
        "o2", "r1", "click", "开始按钮", "pending",
        source_occurrence_ids=["ro2"], variant_id="rv2",
        canonical_operation_id="co1",
    )
    ledger.canonical_operations["co1"].operation_ids.append("o2")

    projected_names = _projected_region_names(ledger)
    snapshot, lookup = _entry_snapshot(ledger, projected_names)

    assert projected_names["ro1"] == projected_names["ro2"]
    assert len(snapshot["entries"]) == 1
    assert snapshot["entries"][0]["source_state_ids"] == ["s1", "s2"]
    assert lookup["o1", "s1"] == lookup["o2", "s2"] == "co1"
