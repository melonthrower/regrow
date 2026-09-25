from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from gui_rewalk.run_capability_induction import main as run_capability_induction
from gui_rewalk.run_capability_task_synthesis import main as run_task_synthesis
from gui_rewalk.run_visual_collection import (
    build_parser, main as run_visual_collection, prepare_collection,
)
from gui_rewalk.src.core.graph.state_graph import StateGraph
from gui_rewalk.src.core.scenario.capability_instruction_gen import (
    _is_task_eligible_capability,
)
from gui_rewalk.src.core.scenario.capability_task_synthesis import (
    compose_instruction_drafts,
    selected_capability_context,
    synthesize_cleanup_cycle_instructions,
    synthesize_single_capability_instructions,
)
from gui_rewalk.src.core.scenario.visual_collection_executor import (
    CapabilityExecutionRef,
)


def _capability(
    capability_id: str,
    verification_level: str,
    *,
    parameters: list[dict] | None = None,
    parameter_examples: list[dict] | None = None,
) -> dict:
    return {
        "capability_id": capability_id,
        "name": capability_id.replace("_", " "),
        "verification_level": verification_level,
        "entry_surfaces": [{
            "page_id": "alarms",
            "variant_id": "empty",
            "state_id": "n1",
            "region_ref": "rg:alarms:form",
            "entry_id": "ae:add",
            "selector": {"element_label": "Add"},
        }],
        "execution_recipe": [{
            "action_type": "CLICK",
            "selector": {"element_label": "Save"},
        }],
        "preconditions": [],
        "effects": [{
            "kind": "state_change",
            "changes": [{
                "scope": {"region_ref": "rg:alarms:list"},
                "fact": "alarm.enabled",
                "value": True,
            }],
        }],
        "success_predicate": {
            "all": [{
                "equals": {
                    "scope": {"region_ref": "rg:alarms:list"},
                    "fact": "alarm.enabled",
                    "value": True,
                },
            }],
        },
        "evidence_refs": [{"action_edge_id": "edge1", "attempt_id": "attempt1"}],
        "effect_refs": [{
            "action_edge_id": "edge1",
            "attempt_id": "attempt1",
            "observation_index": 0,
        }],
        **({"parameters": parameters} if parameters is not None else {}),
        **({"parameter_examples": parameter_examples}
           if parameter_examples is not None else {}),
    }


def _capability_graph(source_graph_digest: str = "digest") -> dict:
    return {
        "schema_version": "gui_rewalk.capability_graph.v1",
        "app_id": "clock",
        "source_graph_digest": source_graph_digest,
        "capabilities": [
            _capability("discovered_alarm", "discovered"),
            _capability("executable_alarm", "executable"),
            _capability(
                "create_alarm",
                "effect_verified",
                parameters=[{
                    "name": "time",
                    "domain": {"values": ["07:30", "08:00"]},
                }],
            ),
            _capability(
                "set_alarm_enabled",
                "composable",
                parameters=[{
                    "name": "enabled",
                    "domain": {"values": [False, True]},
                }],
            ),
        ],
        "probe_episodes": [],
        "relations": [],
    }


def test_task_synthesis_accepts_discovery_without_promoting_evidence() -> None:
    graph = _capability_graph()

    instructions = synthesize_single_capability_instructions(graph)

    assert [
        item.capability_refs[0].capability_id for item in instructions
    ] == ["discovered_alarm", "executable_alarm", "create_alarm", "set_alarm_enabled"]
    assert instructions[0].to_dict()["capability_refs"][0]["availability_status"] == "discovered"
    first = instructions[2].to_dict()
    assert first["capability_refs"][0]["verification_level"] == "effect_verified"
    assert first["capability_refs"][0]["target_node"] == ""
    assert first["capability_refs"][0]["params"] == {"time": "07:30"}
    assert first["capability_refs"][0]["execution_recipe"][0][
        "selector"]["element_label"] == "Save"
    second = instructions[3].to_dict()
    assert second["capability_refs"][0]["params"] == {"enabled": False}
    assert second["capability_refs"][0]["value"] == "false"
    assert second["params"] == {"enabled": "false"}

    assert _is_task_eligible_capability({"verification_level": "discovered"}) is True
    assert _is_task_eligible_capability({"verification_level": "executable"}) is True
    assert _is_task_eligible_capability({"verification_level": "effect_verified"}) is True
    assert _is_task_eligible_capability({"verification_level": "composable"}) is True
    assert _is_task_eligible_capability({"availability_status": "verified"}) is True
    assert _is_task_eligible_capability({}) is True


class _CompositionAgent:
    def __init__(self, skeleton_id: str = "sk001") -> None:
        self.prompt = ""
        self.skeleton_id = skeleton_id

    def predict_mm(self, prompt, _images):
        self.prompt = prompt
        return json.dumps({
            "instructions": [{
                "skeleton_id": self.skeleton_id,
                "instruction": "在世界时钟中添加伦敦。",
                # The framework must ignore any attempted capability rewrite.
                "capabilities": [{
                    "capability_id": "invented_capability",
                    "params": {},
                }],
            }],
        }), None


def test_composition_uses_short_cards_then_fetches_only_selected_recipe() -> None:
    graph = _capability_graph()
    add_city = _capability(
        "add_world_clock",
        "discovered",
    )
    add_city["parameter_candidates"] = {"city_query": ["London"]}
    add_city["name"] = "Add a world clock"
    add_city["entry_surfaces"][0]["page_id"] = "world"
    add_city["predicate_description"] = "The selected city appears as a clock card."
    add_city["execution_recipe"] = [{
        "action_type": "CLICK",
        "selector": {"element_label": "Add world clock"},
    }, {
        "action_type": "TYPE",
        "selector": {"element_label": "City search"},
        "parameters": {"text": "{{city_query}}"},
    }, {
        "action_type": "CLICK",
        "selector": {"element_label": "Matching city result"},
    }, {
        "action_type": "CLICK",
        "selector": {"element_label": "secret-final-add-target"},
    }]
    graph["capabilities"] = [add_city]
    agent = _CompositionAgent()

    drafts = compose_instruction_drafts(graph, agent, n=1)

    assert drafts == [{
        "instruction": "在世界时钟中添加伦敦。",
        "capabilities": [{
            "capability_id": "add_world_clock",
            "params": {},
        }],
    }]
    assert "Add a world clock" in agent.prompt
    assert "London" in agent.prompt
    assert "execution_recipe" not in agent.prompt
    assert "evidence_refs" not in agent.prompt
    assert "secret-final-add-target" not in agent.prompt

    context = selected_capability_context(
        graph, drafts[0]["capabilities"])

    assert [item["capability_id"] for item in context] == ["add_world_clock"]
    assert context[0]["params"] == {}
    assert context[0]["steps"] == [
        "CLICK Add world clock",
        "TYPE London in City search",
        "CLICK Matching city result",
        "CLICK secret-final-add-target",
    ]
    assert context[0]["success"] == (
        "The selected city appears as a clock card.")
    assert all(
        item["capability_id"] != "create_alarm" for item in context)


def test_composition_pages_large_catalog_without_letting_agent_choose_refs() -> None:
    graph = _capability_graph()
    capabilities = []
    for index in range(10):
        capability = _capability(f"cap_{index}", "discovered")
        capability["name"] = f"Feature {index}"
        capability["entry_surfaces"][0]["page_id"] = "settings"
        capability["execution_recipe"][0]["selector"][
            "element_label"] = f"secret recipe target {index}"
        capabilities.append(capability)
    graph["capabilities"] = capabilities
    agent = _CompositionAgent(skeleton_id="sk002")

    drafts = compose_instruction_drafts(graph, agent, n=1, start=1)

    assert [
        item["capability_id"] for item in drafts[0]["capabilities"]
    ] == ["cap_1"]
    assert "Feature 1" in agent.prompt
    assert "Feature 0" not in agent.prompt
    assert "Feature 2" not in agent.prompt
    assert "Feature 3" not in agent.prompt
    assert "secret recipe target" not in agent.prompt



def test_multi_parameter_task_uses_one_observed_tuple() -> None:
    graph = _capability_graph()
    capability = graph["capabilities"][2]
    capability["parameters"] = [
        {"name": "city_query", "domain": {"values": ["a", "z"]}},
        {"name": "selected_result", "domain": {
            "values": ["Alpha", "Zulu"]}},
    ]
    capability["parameter_examples"] = [
        {"city_query": "a", "selected_result": "Zulu"},
        {"city_query": "z", "selected_result": "Alpha"},
    ]
    capability["execution_recipe"] = [{
        "action_type": "TYPE",
        "parameters": {"text": "{{city_query}}"},
    }, {
        "action_type": "CLICK",
        "selector": {"element_label": "{{selected_result}}"},
    }]

    instruction = next(
        item for item in synthesize_single_capability_instructions(graph)
        if item.capability_refs[0].capability_id == "create_alarm"
    ).to_dict()

    assert instruction["capability_refs"][0]["params"] == {
        "city_query": "a", "selected_result": "Zulu"}
    assert instruction["params"] == {
        "city_query": "a", "selected_result": "Zulu"}

    capability.pop("parameter_examples")
    with pytest.raises(ValueError, match="parameter_examples"):
        synthesize_single_capability_instructions(graph)

def _cleanup_graph(source_graph_digest: str = "digest") -> dict:
    graph = _capability_graph(source_graph_digest)
    cleanup = _capability(
        "delete_alarm",
        "effect_verified",
        parameters=[{
            "name": "time",
            "domain": {"values": ["07:30", "08:00"]},
        }],
    )
    cleanup["effects"][0]["kind"] = "object_removal"
    graph["capabilities"].append(cleanup)
    graph["relations"] = [{
        "relation_id": "rel_alarm_cleanup",
        "relation_type": "cleanup_cycle",
        "source_capability_id": "create_alarm",
        "cleanup_capability_id": "delete_alarm",
        "baseline_state_id": "n1",
        "effect_state_id": "n1",
        "parameter_links": [{
            "source_parameter": "time",
            "cleanup_parameter": "time",
            "values": ["07:30", "08:00"],
        }],
        "evidence_refs": [
            {"source_effect_ref": {}, "cleanup_effect_ref": {}},
            {"source_effect_ref": {}, "cleanup_effect_ref": {}},
        ],
    }]
    return graph


def test_cleanup_relation_preserves_observed_source_tuple() -> None:
    graph = _cleanup_graph()
    source = next(
        item for item in graph["capabilities"]
        if item["capability_id"] == "create_alarm")
    cleanup = next(
        item for item in graph["capabilities"]
        if item["capability_id"] == "delete_alarm")
    source["parameters"] = [
        {"name": "city_query", "domain": {"values": ["a", "z"]}},
        {"name": "selected_result", "domain": {
            "values": ["Alpha", "Zulu"]}},
    ]
    source["parameter_examples"] = [
        {"city_query": "a", "selected_result": "Zulu"},
        {"city_query": "z", "selected_result": "Alpha"},
    ]
    cleanup["parameters"] = [{
        "name": "selected_result",
        "domain": {"values": ["Alpha", "Zulu"]},
    }]
    relation = graph["relations"][0]
    relation["parameter_links"] = [{
        "source_parameter": "selected_result",
        "cleanup_parameter": "selected_result",
        "values": ["Alpha", "Zulu"],
    }]

    instruction = synthesize_cleanup_cycle_instructions(graph)[0].to_dict()

    assert instruction["capability_refs"][0]["params"] == {
        "city_query": "a", "selected_result": "Zulu"}
    assert instruction["capability_refs"][1]["params"] == {
        "selected_result": "Zulu"}


def test_cleanup_relation_synthesizes_two_ordered_refs() -> None:
    instructions = synthesize_cleanup_cycle_instructions(_cleanup_graph())

    assert len(instructions) == 1
    instruction = instructions[0].to_dict()
    assert instruction["instruction_id"] == "rel_alarm_cleanup"
    assert instruction["type"] == "cleanup_cycle"
    assert instruction["fixed_order"] is True
    assert [item["capability_id"] for item in instruction[
        "capability_refs"]] == ["create_alarm", "delete_alarm"]
    source, cleanup = instruction["capability_refs"]
    assert source["params"] == {"time": "07:30"}
    assert cleanup["params"] == {"time": "07:30"}
    assert cleanup["depends_on"] == ["create_alarm"]
    assert "恢复初始状态" in instruction["instruction"]


def test_cleanup_relation_cli_and_m13_validate_only(
    tmp_path: Path,
) -> None:
    state_graph_path, node_dir, capability_graph_path, instruction_path = (
        _collection_fixture(tmp_path))
    source_digest = hashlib.sha256(
        state_graph_path.read_bytes()).hexdigest()
    authority = _cleanup_graph(source_digest)
    capability_graph_path.write_text(
        json.dumps(authority, ensure_ascii=False), encoding="utf-8")
    relation_instruction = synthesize_cleanup_cycle_instructions(
        authority)[0].to_dict()
    instruction_path.write_text(
        json.dumps(relation_instruction, ensure_ascii=False), encoding="utf-8")

    prepared = prepare_collection(_collection_args(
        state_graph_path, node_dir, capability_graph_path, instruction_path))

    assert prepared.capability_count == 5
    refs = prepared.instruction["capability_refs"]
    assert [item["capability_id"] for item in refs] == [
        "create_alarm", "delete_alarm"]
    assert refs[1]["depends_on"] == ["create_alarm"]
    assert refs[0]["params"] == refs[1]["params"] == {"time": "07:30"}

    graph_path = tmp_path / "cleanup_capability_graph.json"
    cli_output = tmp_path / "cleanup_instruction.json"
    graph_path.write_text(
        json.dumps(authority, ensure_ascii=False), encoding="utf-8")
    assert run_task_synthesis([
        "--capability-graph", str(graph_path),
        "--relation-id", "rel_alarm_cleanup",
        "--output", str(cli_output),
    ]) == 0
    saved = json.loads(cli_output.read_text(encoding="utf-8"))
    assert saved["instruction_id"] == "rel_alarm_cleanup"
    assert len(saved["capability_refs"]) == 2


def test_cleanup_relation_rejects_value_outside_confirmed_domain() -> None:
    graph = _cleanup_graph()
    graph["relations"][0]["parameter_links"][0]["values"] = ["09:00"]

    with pytest.raises(ValueError, match="outside a confirmed parameter domain"):
        synthesize_cleanup_cycle_instructions(graph)


def test_task_synthesis_cli_selects_one_eligible_capability(tmp_path: Path) -> None:
    graph_path = tmp_path / "capability_graph.json"
    output = tmp_path / "instruction.json"
    graph_path.write_text(
        json.dumps(_capability_graph(), ensure_ascii=False), encoding="utf-8")

    assert run_task_synthesis([
        "--capability-graph", str(graph_path),
        "--capability-id", "create_alarm",
        "--output", str(output),
    ]) == 0

    instruction = json.loads(output.read_text(encoding="utf-8"))
    assert instruction["instruction_id"] == "CAP003"
    assert instruction["capability_refs"][0]["capability_id"] == "create_alarm"
    assert run_task_synthesis([
        "--capability-graph", str(graph_path),
        "--capability-id", "executable_alarm",
        "--output", str(output),
    ]) == 0
    instruction = json.loads(output.read_text(encoding="utf-8"))
    assert instruction["capability_refs"][0]["verification_level"] == "executable"


def _collection_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    state_graph_path = tmp_path / "graph.json"
    state_graph = StateGraph("clock")
    state_graph.add_state(
        "n1",
        [{
            "id": 0,
            "name": "Add",
            "bbox_xywh": [0, 0, 1, 1],
            "center": [0, 0],
            "el_type": "button",
            "interactive": True,
            "category": "navigation",
            "source": "semantic_inventory",
            "uid": "autonomous-entry:ae:add",
            "visited": False,
            "region": "Alarm Form",
            "region_id": "rg:alarms:form",
            "geometry_status": "semantic_only",
        }],
        "n1.png", "clock", page_name="Alarms",
        page_id="alarms", variant_id="empty",
        semantic_blocks=[{
            "region_id": "rg:alarms:form",
            "role": "Alarm Form",
            "element_ids": [0],
            "element_names": ["Add"],
        }],
        perception_mode="autonomous_vlm")
    state_graph.add_state(
        "n2", [], "n2.png", "clock", page_name="Alarms",
        page_id="alarms", variant_id="saved",
        perception_mode="autonomous_vlm")
    state_graph.save(str(state_graph_path))
    source_digest = hashlib.sha256(state_graph_path.read_bytes()).hexdigest()
    authority = _capability_graph(source_digest)

    node_dir = tmp_path / "nodes"
    node_dir.mkdir()
    capability_graph_path = tmp_path / "capability_graph.json"
    capability_graph_path.write_text(
        json.dumps(authority, ensure_ascii=False), encoding="utf-8")
    instruction_path = tmp_path / "instruction.json"
    instruction = next(item for item in synthesize_single_capability_instructions(
        authority) if item.capability_refs[0].capability_id == "create_alarm").to_dict()
    ref = instruction["capability_refs"][0]
    ref["execution_recipe"] = [{
        "action_type": "CLICK",
        "selector": {"element_label": "Malicious override"},
    }]
    ref["effects"] = [{"kind": "invented"}]
    ref["success_predicate"] = {"all": [{"equals": {"fact": "invented"}}]}
    instruction_path.write_text(
        json.dumps(instruction, ensure_ascii=False), encoding="utf-8")
    return state_graph_path, node_dir, capability_graph_path, instruction_path


def _collection_args(
    state_graph_path: Path,
    node_dir: Path,
    capability_graph_path: Path,
    instruction_path: Path,
):
    return build_parser().parse_args([
        "--instruction", str(instruction_path),
        "--graph", f"clock={state_graph_path}",
        "--node-dir", f"clock={node_dir}",
        "--capability-graph", f"clock={capability_graph_path}",
        "--validate-only",
    ])



def test_collection_rejects_unobserved_multi_parameter_tuple(
    tmp_path: Path,
) -> None:
    state_graph_path, node_dir, capability_graph_path, instruction_path = (
        _collection_fixture(tmp_path))
    digest = hashlib.sha256(state_graph_path.read_bytes()).hexdigest()
    authority = _capability_graph(digest)
    capability = authority["capabilities"][2]
    capability["parameters"] = [
        {"name": "city_query", "domain": {"values": ["a", "z"]}},
        {"name": "selected_result", "domain": {
            "values": ["Alpha", "Zulu"]}},
    ]
    capability["parameter_examples"] = [
        {"city_query": "a", "selected_result": "Zulu"},
        {"city_query": "z", "selected_result": "Alpha"},
    ]
    capability["execution_recipe"] = [{
        "action_type": "TYPE",
        "parameters": {"text": "{{city_query}}"},
    }, {
        "action_type": "CLICK",
        "selector": {"element_label": "{{selected_result}}"},
    }]
    capability_graph_path.write_text(
        json.dumps(authority, ensure_ascii=False), encoding="utf-8")
    instruction = next(
        item for item in synthesize_single_capability_instructions(authority)
        if item.capability_refs[0].capability_id == "create_alarm"
    ).to_dict()
    instruction_path.write_text(
        json.dumps(instruction, ensure_ascii=False), encoding="utf-8")

    prepared = prepare_collection(_collection_args(
        state_graph_path, node_dir, capability_graph_path, instruction_path))
    assert prepared.instruction["capability_refs"][0]["params"] == {
        "city_query": "a", "selected_result": "Zulu"}

    instruction["capability_refs"][0]["params"] = {
        "city_query": "a", "selected_result": "Alpha"}
    instruction_path.write_text(
        json.dumps(instruction, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="observed parameter combination"):
        prepare_collection(_collection_args(
            state_graph_path, node_dir,
            capability_graph_path, instruction_path))

def test_collection_rehydrates_from_capability_graph_authority(
    tmp_path: Path,
) -> None:
    state_graph_path, node_dir, capability_graph_path, instruction_path = (
        _collection_fixture(tmp_path))
    args = _collection_args(
        state_graph_path, node_dir, capability_graph_path, instruction_path)

    prepared = prepare_collection(args)

    ref = prepared.instruction["capability_refs"][0]
    assert prepared.capability_count == 4
    assert ref["verification_level"] == "effect_verified"
    assert ref["node_id"] == "n1"
    assert ref["target_node"] == ""
    assert ref["params"] == {"time": "07:30"}
    assert ref["execution_recipe"][0]["selector"]["element_label"] == "Save"
    assert ref["effects"][0]["kind"] == "state_change"
    assert ref["success_predicate"]["all"][0]["equals"]["fact"] == "alarm.enabled"
    assert ref["source_path"] == str(capability_graph_path.resolve())
    source_graph_bytes = state_graph_path.read_bytes()
    source_digest = hashlib.sha256(source_graph_bytes).hexdigest()
    assert ref["source_graph_digest"] == source_digest
    assert CapabilityExecutionRef.from_mapping(ref, 0).target_node == ""
    authority = json.loads(
        capability_graph_path.read_text(encoding="utf-8"))
    authority["source_graph_digest"] = "0" * 64
    capability_graph_path.write_text(json.dumps(authority), encoding="utf-8")
    with pytest.raises(ValueError, match="different collection graph"):
        prepare_collection(args)
    authority["source_graph_digest"] = source_digest
    capability_graph_path.write_text(json.dumps(authority), encoding="utf-8")
    unprojected = StateGraph.load(str(state_graph_path))
    unprojected.graph.nodes["n1"]["elements"] = []
    unprojected.graph.nodes["n1"]["semantic_blocks"] = []
    unprojected.save(str(state_graph_path))
    authority["source_graph_digest"] = hashlib.sha256(
        state_graph_path.read_bytes()).hexdigest()
    capability_graph_path.write_text(json.dumps(authority), encoding="utf-8")
    with pytest.raises(ValueError, match="lacks source Region"):
        prepare_collection(args)
    state_graph_path.write_bytes(source_graph_bytes)
    authority["source_graph_digest"] = source_digest
    capability_graph_path.write_text(json.dumps(authority), encoding="utf-8")



    instruction = json.loads(instruction_path.read_text(encoding="utf-8"))
    instruction["capability_refs"][0]["node_id"] = "n2"
    instruction_path.write_text(json.dumps(instruction), encoding="utf-8")
    with pytest.raises(ValueError, match="not a declared entry surface"):
        prepare_collection(args)

    instruction["capability_refs"][0]["node_id"] = "n1"
    instruction["capability_refs"][0]["params"]["time"] = "09:00"
    instruction_path.write_text(json.dumps(instruction), encoding="utf-8")
    with pytest.raises(ValueError, match="outside its confirmed domain"):
        prepare_collection(args)

    instruction["capability_refs"][0]["params"]["time"] = "07:30"
    instruction_path.write_text(json.dumps(instruction), encoding="utf-8")
    graph = _capability_graph(source_digest)
    capability = graph["capabilities"][2]
    capability["evidence_refs"] = []
    capability["effect_refs"] = []
    for level in ("discovered", "executable"):
        capability["verification_level"] = level
        capability_graph_path.write_text(json.dumps(graph), encoding="utf-8")
        ref = prepare_collection(args).instruction["capability_refs"][0]
        assert ref["verification_level"] == level
        assert ref["availability_status"] == level
        assert ref["evidence_refs"] == []
    capability["verification_level"] = "unknown"
    capability_graph_path.write_text(json.dumps(graph), encoding="utf-8")
    with pytest.raises(ValueError, match="recognized discovery status"):
        prepare_collection(args)

def test_autonomous_writer_bundle_reaches_m13_validate_only(
    tmp_path: Path, capsys,
) -> None:
    raw_graph_path = tmp_path / "graph.json"
    entries_path = tmp_path / "autonomous_entries.json"
    regions_path = tmp_path / "autonomous_regions.json"
    annotated_path = tmp_path / "annotated_graph.json"
    capability_path = tmp_path / "capability_graph.json"
    instruction_path = tmp_path / "instruction.json"
    node_dir = tmp_path / "node_artifacts"
    node_dir.mkdir()

    graph = StateGraph("clock")
    graph.add_state(
        "auto-state", [], "alarms.png", "clock",
        page_name="Alarms", page_id="auto-page", variant_id="auto-state",
        observed_facts={"summary": "Alarms"},
        perception_mode="autonomous_vlm",
    )
    for probe_id in ("probe-1", "probe-2"):
        graph.record_action_event(
            source="auto-state",
            action={
                "action_type": "CLICK",
                "selector": {"element_label": "Open alarm settings"},
            },
            outcome="executed",
            committed=True,
            evidence={
                "probe_id": probe_id,
                "explicit_entry_task": True,
                "entry_id": "ae1",
                "source_region_ref": "rg-actions",
            },
        )
        graph.record_action_event(
            source="auto-state",
            action={
                "action_type": "CLICK",
                "selector": {"element_label": "Enable alarm"},
            },
            outcome="executed",
            committed=True,
            evidence={"probe_id": probe_id},
        )

    entries_path.write_text(json.dumps({
        "schema": "gui_rewalk.autonomous_entries.v3",
        "next_action": 1,
        "entries": [{
            "entry_id": "ae1",
            "page_name": "Alarms",
            "region_name": "Alarm Actions",
            "target": "Open alarm settings",
            "control_type": "button",
            "status": "verified",
            "source_state_id": "auto-state",
            "task_eligible": False,
        }],
        "pending_actions": [],
    }), encoding="utf-8")
    regions_path.write_text(json.dumps({
        "schema": "gui_rewalk.autonomous_regions_by_page.v4",
        "region_groups": {
            "schema": "gui_rewalk.autonomous_region_groups.v1",
            "groups": [
                {
                    "region_ref": "rg-actions",
                    "representative": {
                        "page_name": "Alarms",
                        "region_name": "Alarm Actions",
                    },
                    "occurrences": [],
                },
                {
                    "region_ref": "rg-details",
                    "representative": {
                        "page_name": "Alarms",
                        "region_name": "Alarm Details",
                    },
                    "occurrences": [],
                },
            ],
        },
    }), encoding="utf-8")
    effect = {
        "schema_version": "gui_rewalk.effect_observation.v1",
        "capability_name": "Enable alarm",
        "reason": "The enabled state visibly changed from off to on.",
        "effect_kind": "state_change",
        "observed_changes": [{
            "scope": {"region_ref": "rg-details"},
            "fact": "alarm.enabled",
            "before": False,
            "after": True,
        }],
        "parameter_bindings": {},
        "predicate_candidate": "The alarm details show enabled.",
        "verdict": "supported",
    }
    graph.append_effect_observation(2, effect)
    graph.append_effect_observation(4, effect)
    graph.save(str(raw_graph_path))

    assert run_capability_induction([
        "--graph_path", str(raw_graph_path),
        "--entries_path", str(entries_path),
        "--regions_path", str(regions_path),
        "--annotated_graph_output", str(annotated_path),
        "--output", str(capability_path),
    ]) == 0

    annotated = StateGraph.load(str(annotated_path))
    node = annotated.graph.nodes["auto-state"]
    assert [item["uid"] for item in node["elements"]] == [
        "autonomous-entry:ae1"]
    assert {
        item["region_id"] for item in node["semantic_blocks"]
    } == {"rg-actions", "rg-details"}

    capability_graph = json.loads(
        capability_path.read_text(encoding="utf-8"))
    assert capability_graph["source_graph_digest"] == hashlib.sha256(
        annotated_path.read_bytes()).hexdigest()
    assert len(capability_graph["capabilities"]) == 1
    capability = capability_graph["capabilities"][0]
    assert capability["verification_level"] == "effect_verified"
    attempt_ids = {
        attempt["attempt_id"]
        for edge in annotated.action_edges
        for attempt in edge.get("attempts") or []
    }
    assert {
        ref["attempt_id"] for ref in capability["evidence_refs"]
    } <= attempt_ids
    assert {
        ref["attempt_id"] for ref in capability["effect_refs"]
    } <= attempt_ids

    capability_id = capability["capability_id"]
    assert run_task_synthesis([
        "--capability-graph", str(capability_path),
        "--capability-id", capability_id,
        "--output", str(instruction_path),
    ]) == 0
    assert run_visual_collection([
        "--instruction", str(instruction_path),
        "--graph", f"clock={annotated_path}",
        "--node-dir", f"clock={node_dir}",
        "--capability-graph", f"clock={capability_path}",
        "--validate-only",
    ]) == 0
    validation = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert validation == {
        "valid": True,
        "apps": ["clock"],
        "capabilities": 1,
        "refs": 1,
    }

