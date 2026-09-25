"""Existing modular exploration contracts: ledger."""


import json

from gui_rewalk.src.core.explore.bundle import (
    _entry_snapshot,
    _projected_region_names,
    _region_snapshot,
)
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.tasks import TaskScheduler

from .explore_fixtures import _parameter_ledger, _seed_ledger


def test_legacy_v4_load_does_not_retroactively_create_parameter_gap(tmp_path):
    ledger = _parameter_ledger("unknown")
    path = tmp_path / "legacy.json"
    payload = ledger.snapshot()
    payload["schema"] = "modular_exploration.v4"
    for operation in payload["operations"]:
        operation.pop("parameter_status", None)
        operation.pop("parameter_summary", None)
        operation.pop("parameter_evidence_refs", None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = ExplorationLedger.load(path)

    assert loaded.schema == "modular_exploration.v4"
    assert next(iter(loaded.operations.values())).parameter_status == "unknown"
    assert not any("parameter_unknown" in gap
                   for gap in TaskScheduler.gaps(loaded))


def test_ledger_persists_thin_structure_and_rebuilds_runtime_indexes(tmp_path):
    ledger = _seed_ledger()
    ledger.canonical_operations["co1"].representative_goal = (
        "确认两个同类控件的交互关系")
    ledger.canonical_operations["co1"].representative_member_operation_ids = [
        "o1"]
    ledger.canonical_operations["co1"].representative_operation_ids = ["o1"]
    ledger.canonical_operations["co1"].representative_result = "same"
    before_region = _region_snapshot(
        ledger, _projected_region_names(ledger))
    before_entries, _ = _entry_snapshot(
        ledger, _projected_region_names(ledger))

    path = tmp_path / "exploration_ledger.json"
    ledger.save(path)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["schema"] == "modular_exploration.v7"
    assert set(saved["region_variants"][0]) == {"variant_id", "region_id"}
    assert not ({
        "operation_ids", "occurrence_ids", "variant_ids",
        "canonical_operation_ids", "element_ids",
    } & set(saved["regions"][0]))
    assert "operation_ids" not in saved["canonical_operations"][0]
    assert "operation_ids" not in saved["elements"][0]

    restored = ExplorationLedger.load(path)

    assert restored.regions["r1"].variant_ids == ["rv1"]
    assert restored.regions["r1"].occurrence_ids == ["ro1"]
    assert restored.regions["r1"].element_ids == ["el1"]
    assert restored.regions["r1"].operation_ids == ["o1"]
    assert restored.regions["r1"].canonical_operation_ids == ["co1"]
    assert restored.region_variants["rv1"].occurrence_ids == ["ro1"]
    assert restored.region_variants["rv1"].element_ids == ["el1"]
    assert restored.region_variants["rv1"].operation_ids == ["o1"]
    assert restored.elements["el1"].operation_ids == ["o1"]
    assert restored.canonical_operations["co1"].operation_ids == ["o1"]
    assert restored.canonical_operations[
        "co1"].representative_operation_ids == ["o1"]
    assert restored.canonical_operations[
        "co1"].representative_member_operation_ids == ["o1"]
    assert restored.canonical_operations["co1"].representative_result == "same"
    assert _region_snapshot(
        restored, _projected_region_names(restored)) == before_region
    restored_entries, _ = _entry_snapshot(
        restored, _projected_region_names(restored))
    assert restored_entries == before_entries


def test_v3_load_ignores_legacy_reverse_indexes_and_rebuilds_them(tmp_path):
    ledger = _seed_ledger()
    saved = ledger.snapshot()
    saved["schema"] = "modular_exploration.v3"
    saved["regions"][0]["operation_ids"] = ["stale-operation"]
    saved["region_variants"][0]["occurrence_ids"] = ["stale-occurrence"]
    saved["canonical_operations"][0]["operation_ids"] = ["stale-operation"]
    saved["elements"][0]["operation_ids"] = ["stale-operation"]
    path = tmp_path / "legacy_v3_ledger.json"
    path.write_text(json.dumps(saved), encoding="utf-8")

    restored = ExplorationLedger.load(path)

    assert restored.regions["r1"].operation_ids == ["o1"]
    assert restored.region_variants["rv1"].occurrence_ids == ["ro1"]
    assert restored.canonical_operations["co1"].operation_ids == ["o1"]
    assert restored.elements["el1"].operation_ids == ["o1"]
