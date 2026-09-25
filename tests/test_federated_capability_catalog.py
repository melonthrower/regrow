"""Offline tests for federated capability loading and composition."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.src.core.scenario.capability_instruction_gen import Instruction
from gui_rewalk.src.core.scenario.federated_capability_catalog import (
    AmbiguousCapabilityError,
    CapabilityCatalogError,
    FederatedCapabilityCatalog,
    dumps_instruction,
    loads_instruction,
)


def _write_page(
    root: Path,
    app_id: str,
    node_id: str,
    page_name: str,
    capabilities: Sequence[Mapping[str, Any]],
) -> Path:
    node = root / app_id / node_id
    node.mkdir(parents=True, exist_ok=True)
    (node / "page_capabilities.json").write_text(
        json.dumps(
            {
                "node_id": node_id,
                "page_name": page_name,
                "page_breakdown": "fixture",
                "capabilities": list(capabilities),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root / app_id


def _search_atom(capability_id: str = "shared") -> Mapping[str, Any]:
    return {
        "capability_id": capability_id,
        "name": "Search",
        "target_node": "results",
        "region": "content",
        "param": {"type": "string", "slot": "query"},
        "requires": [{"kind": "state", "fact": "app_ready"}],
        "success_predicate": "results are visible",
        "action_steps": 2,
        "elements": ["search_box"],
        "execution_recipe": [
            {
                "action_type": "CLICK",
                "selector": {"element_label": "Search", "element_type": "input"},
            },
            {"action_type": "TYPE", "parameters": {"text": "{{query}}"}},
        ],
    }


def _write_online_variant(
    root: Path,
    *,
    app_id: str,
    node_id: str,
    page_id: str,
    variant_id: str,
    capability: Mapping[str, Any],
) -> Path:
    node = root / app_id / node_id
    node.mkdir(parents=True, exist_ok=True)
    (node / "page_capabilities.json").write_text(
        json.dumps(
            {
                "schema_version": "capability.discovery.v1",
                "app_id": app_id,
                "node_id": node_id,
                "page_name": "Alarm",
                "page_id": page_id,
                "variant_id": variant_id,
                "capabilities": [dict(capability)],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root / app_id


def test_online_page_variants_merge_one_stable_capability(tmp_path: Path) -> None:
    capability_id = "cap_open_add_alarm"
    empty = {
        "capability_id": capability_id,
        "page_id": "page_alarm",
        "name": "open add alarm",
        "semantic_key": "open add alarm",
        "status": "discovered",
        "availability_status": "discovered",
        "target_node": "alarm_editor",
        "evidence_variants": ["variant_empty"],
        "entry_variants": ["variant_empty"],
        "source_elements": [
            {
                "state_id": "alarm_empty",
                "variant_id": "variant_empty",
                "element_id": "add_empty",
                "element_label": "Add alarm",
            }
        ],
        "available_when": {
            "variant_ids": ["variant_empty"],
            "facts_by_variant": {
                "variant_empty": {"present_groups": []},
            },
        },
        "execution_recipe": [
            {
                "action_type": "CLICK",
                "selector": {"element_label": "Add alarm", "region": "toolbar"},
            }
        ],
    }
    has_data = {
        **empty,
        "status": "verified",
        # Traversal promotion uses lifecycle status; stale availability must
        # not demote the merged executable atom.
        "availability_status": "discovered",
        "evidence_variants": ["variant_has_data"],
        "entry_variants": ["variant_has_data"],
        "source_elements": [
            {
                "state_id": "alarm_has_data",
                "variant_id": "variant_has_data",
                "element_id": "add_has_data",
                "element_label": "Add alarm",
            }
        ],
        "target_pages": ["page_alarm_editor"],
        "target_variants": ["variant_editor"],
        "action_edge_ids": ["edge_empty", "edge_has_data"],
        "available_when": {
            "variant_ids": ["variant_has_data"],
            "facts_by_variant": {
                "variant_has_data": {"present_groups": ["alarm_item"]},
            },
        },
    }
    app_dir = _write_online_variant(
        tmp_path,
        app_id="clock",
        node_id="alarm_empty",
        page_id="page_alarm",
        variant_id="variant_empty",
        capability=empty,
    )
    _write_online_variant(
        tmp_path,
        app_id="clock",
        node_id="alarm_has_data",
        page_id="page_alarm",
        variant_id="variant_has_data",
        capability=has_data,
    )

    catalog = FederatedCapabilityCatalog({"clock": app_dir})

    assert len(catalog.all_atoms()) == 1
    atom = catalog.get_by_capability_id(capability_id, app_id="clock")
    assert atom.page_id == "page_alarm"
    assert atom.semantic_key == "open add alarm"
    assert atom.availability_status == "verified"
    assert atom.node_id == "alarm_has_data"
    assert atom.evidence_variants == ("variant_empty", "variant_has_data")
    assert atom.entry_variants == ("variant_empty", "variant_has_data")
    assert {item["state_id"] for item in atom.source_elements} == {
        "alarm_empty",
        "alarm_has_data",
    }
    assert atom.action_edge_ids == ("edge_empty", "edge_has_data")
    assert atom.target_pages == ("page_alarm_editor",)
    assert atom.target_variants == ("variant_editor",)
    assert atom.available_when["variant_ids"] == [
        "variant_empty",
        "variant_has_data",
    ]
    assert set(atom.available_when["facts_by_variant"]) == {
        "variant_empty",
        "variant_has_data",
    }
    assert len(atom.source_paths) == 2
    assert catalog.load() == 1
    assert catalog.get_by_capability_id(
        capability_id, app_id="clock").to_dict() == atom.to_dict()


def test_variant_requirements_do_not_become_false_global_prerequisite(
    tmp_path: Path,
) -> None:
    requirement = {
        "kind": "authorization",
        "fact": "alarm permission required",
    }
    available = {
        "capability_id": "cap_open_alarm",
        "page_id": "page_alarm",
        "name": "open alarm",
        "semantic_key": "open alarm",
        "status": "verified",
        "availability_status": "discovered",
        "requires": [],
        "action_edge_ids": ["edge_open_alarm"],
        "available_when": {
            "variant_ids": ["variant_available"],
            "requires_by_variant": {"variant_available": []},
        },
    }
    blocked = {
        **available,
        "status": "discovered",
        "availability_status": "blocked",
        "requires": [requirement],
        "action_edge_ids": [],
        "available_when": {
            "variant_ids": ["variant_blocked"],
            "requires_by_variant": {"variant_blocked": [requirement]},
        },
    }
    app_dir = _write_online_variant(
        tmp_path,
        app_id="clock",
        node_id="alarm_available",
        page_id="page_alarm",
        variant_id="variant_available",
        capability=available,
    )
    _write_online_variant(
        tmp_path,
        app_id="clock",
        node_id="alarm_blocked",
        page_id="page_alarm",
        variant_id="variant_blocked",
        capability=blocked,
    )

    atom = FederatedCapabilityCatalog({"clock": app_dir}).get_by_capability_id(
        "cap_open_alarm", app_id="clock")

    assert atom.availability_status == "verified"
    assert atom.requires == ()
    assert atom.available_when["requires_by_variant"] == {
        "variant_available": [],
        "variant_blocked": [requirement],
    }
    assert atom.available_when["variant_ids"] == [
        "variant_available",
        "variant_blocked",
    ]

    # Compatibility ``requires`` remains usable when every variant has the
    # exact same requirement set (ordering differences are irrelevant).
    same_root = tmp_path / "same_requirement"
    same_a = {
        **available,
        "capability_id": "cap_same_requirement",
        "requires": [requirement],
        "available_when": {
            "variant_ids": ["variant_a"],
            "requires_by_variant": {"variant_a": [requirement]},
        },
    }
    same_b = {
        **same_a,
        "available_when": {
            "variant_ids": ["variant_b"],
            "requires_by_variant": {"variant_b": [requirement]},
        },
    }
    same_dir = _write_online_variant(
        same_root,
        app_id="clock",
        node_id="same_a",
        page_id="page_alarm",
        variant_id="variant_a",
        capability=same_a,
    )
    _write_online_variant(
        same_root,
        app_id="clock",
        node_id="same_b",
        page_id="page_alarm",
        variant_id="variant_b",
        capability=same_b,
    )
    same_atom = FederatedCapabilityCatalog(
        {"clock": same_dir}).get_by_capability_id(
            "cap_same_requirement", app_id="clock")
    assert same_atom.requires == (requirement,)


@pytest.mark.parametrize(
    ("second_page_id", "second_semantic_key", "message"),
    [
        ("page_alarm_detail", "open add alarm", "crosses pages"),
        ("page_alarm", "delete alarm", "conflicting semantic identity"),
    ],
)
def test_duplicate_capability_conflicts_remain_fail_closed(
    tmp_path: Path,
    second_page_id: str,
    second_semantic_key: str,
    message: str,
) -> None:
    base = {
        "capability_id": "cap_collision",
        "page_id": "page_alarm",
        "name": "open add alarm",
        "semantic_key": "open add alarm",
    }
    app_dir = _write_online_variant(
        tmp_path,
        app_id="clock",
        node_id="variant_a",
        page_id="page_alarm",
        variant_id="variant_a",
        capability=base,
    )
    conflicting = {
        **base,
        "page_id": second_page_id,
        "semantic_key": second_semantic_key,
    }
    _write_online_variant(
        tmp_path,
        app_id="clock",
        node_id="variant_b",
        page_id=second_page_id,
        variant_id="variant_b",
        capability=conflicting,
    )

    with pytest.raises(CapabilityCatalogError, match=message):
        FederatedCapabilityCatalog({"clock": app_dir})


def test_independent_app_namespaces_and_same_name_atoms_do_not_collide(tmp_path: Path) -> None:
    app_a_dir = _write_page(tmp_path, "app_a", "home", "Home", [_search_atom()])
    legacy_recipe_atom = dict(_search_atom())
    legacy_recipe_atom["action_recipe"] = legacy_recipe_atom.pop("execution_recipe")
    app_b_dir = _write_page(
        tmp_path, "app_b", "home", "Home", [legacy_recipe_atom]
    )

    catalog = FederatedCapabilityCatalog.from_node_dirs(
        {"app_a": app_a_dir, "app_b": app_b_dir}
    )

    assert len(catalog.all_atoms()) == 2
    atom_a = catalog.get_by_qualified_name("app_a::Home::Search")
    atom_b = catalog.get_by_qualified_name("app_b::Home::Search")
    assert atom_a.app_id == "app_a"
    assert atom_b.app_id == "app_b"
    assert atom_a.node_id == atom_b.node_id == "home"
    assert atom_a is not atom_b
    assert atom_a.execution_recipe[1]["parameters"]["text"] == "{{query}}"
    assert atom_b.execution_recipe == atom_a.execution_recipe
    assert catalog.get_by_capability_id("shared", app_id="app_a") is atom_a
    assert catalog.get_by_capability_id("shared", app_id="app_b") is atom_b
    with pytest.raises(AmbiguousCapabilityError):
        catalog.get_by_capability_id("shared")

    # The catalog owns semantic indices only; it never constructs a mixed graph.
    assert not hasattr(catalog, "graph")
    assert catalog.capability_id_index["shared"] == (atom_a, atom_b)


def test_deterministic_cross_app_instruction_has_ordered_m13_refs(tmp_path: Path) -> None:
    app_a_dir = _write_page(
        tmp_path, "app_a", "home", "Home", [_search_atom("cap_search")]
    )
    app_b_dir = _write_page(
        tmp_path,
        "app_b",
        "editor",
        "Editor",
        [
            {
                "capability_id": "cap_write",
                "name": "Write note",
                "param": {"type": "string", "slot": "content"},
                "requires": [{"kind": "resource", "fact": "note_open"}],
                "success_predicate": "note contains requested content",
                "action_steps": 3,
                "elements": ["editor"],
            }
        ],
    )
    catalog = FederatedCapabilityCatalog(
        {"app_a": app_a_dir, "app_b": app_b_dir}
    )

    instruction = catalog.compose_instruction(
        [
            {
                "atom_ref": "app_a::Home::Search",
                "ref_id": "search_step",
                "params": {"query": "rain tomorrow"},
                "desired_outcome": "results visible",
            },
            {
                "capability_id": "cap_write",
                "app_id": "app_b",
                "ref_id": "write_step",
                "params": {"content": "weather result"},
                "depends_on": ["search_step"],
            },
        ],
        instruction_text="Search in app A, then write the result in app B.",
        instruction_id="FED_XAPP",
    )

    assert isinstance(instruction, Instruction)
    data = instruction.to_dict()
    assert data["fixed_order"] is True
    assert data["apps_involved"] == ["app_a", "app_b"]
    assert data["type"] == "cross_app"
    assert [ref["ref_id"] for ref in data["capability_refs"]] == [
        "search_step",
        "write_step",
    ]
    assert [ref["app_id"] for ref in data["capability_refs"]] == [
        "app_a",
        "app_b",
    ]
    assert data["capability_refs"][0]["node_id"] == "home"
    assert data["capability_refs"][0]["target_node"] == "results"
    assert data["capability_refs"][0]["requires"] == [
        {"kind": "state", "fact": "app_ready"}
    ]
    assert data["capability_refs"][0]["action_steps"] == 2
    assert data["capability_refs"][0]["params"] == {"query": "rain tomorrow"}
    assert data["capability_refs"][0]["desired_outcome"] == "results visible"
    assert data["capability_refs"][0]["execution_recipe"] == [
        {
            "action_type": "CLICK",
            "selector": {"element_label": "Search", "element_type": "input"},
        },
        {"action_type": "TYPE", "parameters": {"text": "{{query}}"}},
    ]
    assert data["capability_refs"][1]["depends_on"] == ["search_step"]
    assert data["capability_refs"][1]["action_steps"] == 3


def test_injected_vlm_can_select_cross_app_atoms_but_cannot_invent_them(tmp_path: Path) -> None:
    app_a_dir = _write_page(
        tmp_path, "app_a", "home", "Home", [_search_atom("cap_search")]
    )
    app_b_dir = _write_page(
        tmp_path,
        "app_b",
        "editor",
        "Editor",
        [
            {
                "capability_id": "cap_write",
                "name": "Write note",
                "param": {"type": "string", "slot": "content"},
                "action_steps": 1,
            }
        ],
    )

    class _VLM:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def predict_mm(self, prompt: str, images):
            self.prompts.append(prompt)
            assert images == []
            return (
                json.dumps(
                    {
                        "instruction": "Write a note, then search for it.",
                        "ordered_atom_refs": [
                            {
                                "app_id": "app_b",
                                "capability_id": "cap_write",
                                "params": {"content": "storm"},
                            },
                            {
                                "atom_ref": "app_a::Home::Search",
                                "params": {"query": "storm"},
                            },
                        ],
                    }
                ),
                0,
                0,
            )

    vlm = _VLM()
    catalog = FederatedCapabilityCatalog(
        {"app_a": app_a_dir, "app_b": app_b_dir}, vlm=vlm
    )
    instruction = catalog.compose_with_vlm("record and search")
    data = instruction.to_dict()

    assert [ref["app_id"] for ref in data["capability_refs"]] == [
        "app_b",
        "app_a",
    ]
    assert data["apps_involved"] == ["app_b", "app_a"]
    assert data["fixed_order"] is True
    assert "app_a::Home::Search" in vlm.prompts[0]

    catalog.vlm = lambda _prompt: {
        "instruction": "invented",
        "ordered_atom_refs": [{"atom_ref": "app_c::Nowhere::Fake"}],
    }
    with pytest.raises(ValueError):
        catalog.compose_with_vlm("invent something")

    catalog.vlm = lambda _prompt: {
        "instruction": "outside candidates",
        "ordered_atom_refs": [
            {"app_id": "app_b", "capability_id": "cap_write"}
        ],
    }
    with pytest.raises(ValueError):
        catalog.compose_with_vlm(
            "escape candidate set",
            candidate_atom_refs=["app_a::Home::Search"],
        )


def test_instruction_json_roundtrip_preserves_federated_fields(tmp_path: Path) -> None:
    app_a_dir = _write_page(
        tmp_path, "app_a", "home", "Home", [_search_atom("cap_search")]
    )
    app_b_dir = _write_page(
        tmp_path,
        "app_b",
        "editor",
        "Editor",
        [
            {
                "capability_id": "cap_write",
                "name": "Write note",
                "param": {
                    "type": "string",
                    "slot": "content",
                    "source": "discover_at_runtime",
                },
                "action_steps": 4,
            }
        ],
    )
    catalog = FederatedCapabilityCatalog(
        {"app_a": app_a_dir, "app_b": app_b_dir}
    )
    original = catalog.compose_instruction(
        [
            {"capability_id": "cap_search", "app_id": "app_a"},
            {"capability_id": "cap_write", "app_id": "app_b"},
        ],
        instruction_text="Cross-app round trip",
        instruction_id="ROUNDTRIP",
    )

    restored = loads_instruction(dumps_instruction(original, indent=2))

    assert restored.to_dict() == original.to_dict()
    assert restored.fixed_order is True
    assert restored.apps_involved == ["app_a", "app_b"]
    assert restored.runtime_slots == ["content"]
    assert restored.capability_refs[1].to_dict()["params"] == {}
