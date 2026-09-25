from __future__ import annotations

import io
import json
from types import SimpleNamespace

import networkx as nx
from PIL import Image

from gui_rewalk.src.core.visual_traversal.grounding.region.registry import (
    RegionRegistry,
)
from gui_rewalk.src.core.visual_traversal.state.block_identity import (
    compare_state_regions,
    resolve_semantic_blocks,
    semantic_region_set,
)
from gui_rewalk.src.core.visual_traversal.state.registration import (
    _refresh_semantic_block_members,
)
from gui_rewalk.src.core.visual_traversal.state.registration import (
    _apply_region_aliases,
    _preferred_page_id_for_observation,
)
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement


def _frame() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (300, 300), "white").save(stream, "PNG")
    return stream.getvalue()


def _elements(region_id: str, names):
    return [
        VisualElement(
            id=index, name=name, bbox_xywh=[0, 0, 0, 0], center=[0, 0],
            el_type="button", category="navigation", region_id=region_id,
            source="semantic_inventory", geometry_status="semantic_only",
        )
        for index, name in enumerate(names)
    ]


def _state(page_name: str, rows):
    elements = []
    blocks = []
    for region_id, names in rows:
        members = _elements(region_id, names)
        elements.extend(members)
        blocks.append({
            "region_id": region_id,
            "element_names": list(names),
            "element_ids": [item.id for item in members],
        })
    return {
        "page_name": page_name,
        "elements": elements,
        "semantic_blocks": blocks,
    }


class _Perception:
    last_surface_kind = "page"

    def __init__(self):
        self.calls = 0
        self.last_block_localization = {}


class _Writer:
    def __init__(self):
        self.rows = []

    def save_block_identity_attempt(self, **kwargs):
        self.rows.append(kwargs)


def test_stable_block_refresh_retains_scrollability_for_region_map_runtime():
    elements = _elements("r1", ["Open Document 01"])
    blocks = [{
        "local_id": "b0", "region_id": "r1", "role": "content_list",
        "scrollable": True, "bbox_1000": [100, 100, 900, 900],
    }]

    _refresh_semantic_block_members(blocks, elements)

    assert blocks == [{
        "region_id": "r1", "scrollable": True,
        "element_ids": [0], "element_names": ["Open Document 01"],
    }]


class _RegionJudge:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.last_raw_response = json.dumps(result)

    def align_regions(self, interface_a, regions_a, interface_b, regions_b):
        self.calls.append((interface_a, regions_a, interface_b, regions_b))
        return self.result


def test_new_node_regions_are_minted_without_cross_node_guessing():
    blocks = [
        {"local_id": "b0", "role": "top", "bbox_1000": [0, 0, 1000, 400],
         "element_names": ["More"]},
        {"local_id": "b1", "role": "bottom", "bbox_1000": [0, 400, 1000, 1000],
         "element_names": ["Clock"]},
    ]
    elements = _elements("b0", ["More"]) + _elements("b1", ["Clock"])
    registry = RegionRegistry()
    perception = _Perception()
    writer = _Writer()

    audit, crops = resolve_semantic_blocks(
        screenshot=_frame(), blocks=blocks, elements=elements,
        perception=perception, judge=object(), region_registry=registry,
        writer=writer, state_data={})

    assert audit["method"] == "new_node_region_mint"
    assert len(audit["created_concepts"]) == 2
    assert [block["region_id"] for block in blocks] == ["r1", "r2"]
    assert [element.region_id for element in elements] == ["r1", "r2"]
    assert set(crops) == {"r1", "r2"}
    assert perception.calls == 0
    assert perception.last_block_localization["method"] == "semantic_inventory"


def test_known_menu_and_clock_region_tables_do_not_merge():
    menu = _state("Clock App Overflow Menu", [
        ("r5", ["Screen saver", "Settings", "Privacy policy",
                "Send feedback", "Help"]),
    ])
    clock = _state("Clock", [
        ("r1", ["More options"]),
        ("r2", ["You can find the privacy policy here"]),
        ("r3", ["Add"]),
        ("r4", ["Alarm", "Clock", "Timer", "Stopwatch", "Bedtime"]),
    ])
    result = {
        "same_regions": [],
        "interface_a_final_regions": ["A1"],
        "interface_b_final_regions": ["B1", "B2", "B3", "B4"],
    }
    judge = _RegionJudge(result)

    audit, aliases = compare_state_regions(
        state_a=menu, state_b=clock, judge=judge)

    assert aliases == {}
    assert audit["status"] == "mapped"
    assert audit["same_regions"] == []
    assert judge.calls[0][1][0]["contains"] == [
        "Screen saver", "Settings", "Privacy policy", "Send feedback", "Help"]


def test_same_bottom_bar_maps_to_the_older_stable_region():
    alarm = _state("Alarm", [
        ("r8", ["Add alarm"]),
        ("r9", ["Alarm", "Clock", "Timer", "Stopwatch", "Bedtime"]),
    ])
    clock = _state("Clock", [
        ("r2", ["Add"]),
        ("r4", ["Alarm", "Clock", "Timer", "Stopwatch", "Bedtime"]),
    ])
    judge = _RegionJudge({
        "same_regions": [{
            "same_region": "S1",
            "interface_a_region": "A2",
            "interface_b_region": "B2",
        }],
        "interface_a_final_regions": ["A1", "S1"],
        "interface_b_final_regions": ["B1", "S1"],
    })

    audit, aliases = compare_state_regions(
        state_a=alarm, state_b=clock, judge=judge)

    assert aliases == {"r9": "r4"}
    assert audit["same_regions"] == [{
        "interface_a_region": "r9",
        "interface_b_region": "r4",
    }]


def test_region_registry_merges_only_after_confirmed_correspondence():
    registry = RegionRegistry()
    keep = registry.mint_semantic_concept(
        role="block", names=["Clock"], action_names=["Clock"])
    drop = registry.mint_semantic_concept(
        role="block", names=["Alarm"], action_names=["Alarm"])
    registry.mark_seen(keep, "clock")
    registry.mark_seen(drop, "alarm")

    assert registry.merge_semantic_concepts(keep, drop) is True
    merged = registry.semantic_candidate(keep)
    assert registry.semantic_candidate(drop) is None
    assert merged["names"] == ["alarm", "clock"]
    assert merged["seen_on"] == ["alarm", "clock"]


def test_failed_region_mapping_discards_only_unobserved_concepts():
    registry = RegionRegistry()
    request_local = registry.mint_semantic_concept(
        role="block", names=["Temporary"], action_names=["Temporary"])
    registered = registry.mint_semantic_concept(
        role="block", names=["Saved"], action_names=["Saved"])
    registry.mark_seen(registered, "known-node")

    registry.discard_unobserved_semantic_concepts(
        [request_local, registered])

    assert registry.semantic_candidate(request_local) is None
    assert registry.semantic_candidate(registered) is not None


def test_confirmed_region_merge_rewrites_nodes_and_existing_edges():
    regions = RegionRegistry()
    keep = regions.mint_semantic_concept(
        role="block", names=["Clock"], action_names=["Clock"])
    drop = regions.mint_semantic_concept(
        role="block", names=["Clock"], action_names=["Clock"])
    source_element = _elements(keep, ["Clock"])[0]
    target_element = _elements(drop, ["Clock"])[0]
    graph_data = nx.DiGraph()
    graph_data.add_node("a", elements=[source_element.to_dict()],
                        semantic_blocks=[{"region_id": keep}])
    graph_data.add_node("b", elements=[target_element.to_dict()],
                        semantic_blocks=[{"region_id": drop}])
    graph_data.add_edge("b", "a", source_region_id=drop,
                        attempts=[{"region_id": drop}])
    graph = SimpleNamespace(
        graph=graph_data,
        action_edges=[{"source_region_id": drop}],
        abnormal_buttons=[{"region_id": drop}],
        scroll_ledger={"scope": {"region_id": drop}},
    )
    host = SimpleNamespace(
        region_registry=regions,
        registry=SimpleNamespace(_region_sets={
            "a": {f"region:{keep}"}, "b": {f"region:{drop}"}}),
        _state_data={
            "a": {"elements": [source_element],
                  "semantic_blocks": [{"region_id": keep}]},
            "b": {"elements": [target_element],
                  "semantic_blocks": [{"region_id": drop}]},
        },
        graph=graph,
    )

    changed = _apply_region_aliases(host, {drop: keep})

    assert changed == ["b"]
    assert target_element.region_id == keep
    assert host._state_data["b"]["semantic_blocks"][0]["region_id"] == keep
    assert graph_data.nodes["b"]["elements"][0]["region_id"] == keep
    assert graph_data.edges["b", "a"]["source_region_id"] == keep
    assert graph.action_edges[0]["source_region_id"] == keep
    assert host.registry._region_sets["b"] == {f"region:{keep}"}


def test_fixture_oracle_keeps_deterministic_region_registration():
    blocks = [{
        "local_id": "b0", "role": "bottom", "element_names": ["Clock"],
        "fixture_oracle": True, "bbox_1000": [0, 200, 1000, 1000],
    }]
    elements = _elements("b0", ["Clock"])
    perception = _Perception()

    audit, crops = resolve_semantic_blocks(
        screenshot=_frame(), blocks=blocks, elements=elements,
        perception=perception, judge=object(), region_registry=RegionRegistry(),
        writer=_Writer(), state_data={})

    assert audit["method"] == "fixture_oracle_inventory"
    assert audit["localization"]["bboxes_1000"] == {
        "b0": [0, 200, 1000, 1000]}
    assert set(crops) == {blocks[0]["region_id"]}
    assert perception.calls == 0
    assert blocks[0]["region_id"] == elements[0].region_id


def test_active_overlay_inherits_source_page_id():
    registry = SimpleNamespace(
        page_id_of=lambda state_id: {
            "source": "page-source", "preferred": "page-other",
        }.get(state_id))
    host = SimpleNamespace(
        registry=registry,
        _state_data={"source": {"page_id": "page-source"}},
        _pending_transition={"source_id": "source"},
    )

    assert _preferred_page_id_for_observation(
        host, "preferred", "popup_menu") == "page-source"
    assert _preferred_page_id_for_observation(
        host, "preferred", "page") == "page-other"


def test_semantic_region_set_contains_only_stable_region_references():
    blocks = [{"region_id": "r1"}, {"region_id": "r2"}]
    assert semantic_region_set(blocks, []) == {"region:r1", "region:r2"}
