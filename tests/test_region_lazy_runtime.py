import io
from collections import deque
from types import SimpleNamespace

import networkx as nx
import pytest
from PIL import Image

from gui_rewalk.src.core.visual_traversal.runtime.region_observation import (
    observe_next_region,
    pending_region_ids,
    register_region_map,
    unresolved_region_ids,
)
from gui_rewalk.src.core.visual_traversal.runtime.agent_tools import (
    ToolContext, current_region_directory, execute_agent_tool, tool_catalog,
)
from gui_rewalk.src.core.graph.state_graph import StateGraph
from gui_rewalk.src.core.visual_traversal.artifacts import ArtifactWriter
from gui_rewalk.src.core.visual_traversal.runtime.contracts import (
    PerceptionUnavailable,
)
from gui_rewalk.src.core.visual_traversal.state.registry import (
    VisualStateRegistry,
)
from gui_rewalk.src.core.visual_traversal.state.resolver import (
    IdentityResolution,
)


def _png_bytes():
    payload = io.BytesIO()
    Image.new("RGB", (200, 120), "white").save(payload, format="PNG")
    return payload.getvalue()


class _Experiment:
    def __init__(self, *, fail=False, regions=None, interface_name="Demo",
                 elements=None, scrollable=False):
        self.fail = fail
        self.regions = regions
        self.interface_name = interface_name
        self.elements = elements
        self.scrollable = scrollable
        self.located = []
        self.inventoried = []

    def discover(self, _shot, force_refresh=False):
        return {
            "status": "ok", "interface_name": self.interface_name,
            "regions": self.regions or [{
                "region_id": "r0", "name": "Main",
                "description": "Primary functions.",
            }],
        }

    def locate(self, _shot, _discovery, selected, force_refresh=False):
        self.located.append((selected["region_id"], force_refresh))
        if self.fail:
            return {"status": "not_found", "reason": "unstable frame"}
        return {
            "status": "ok", "region_id": selected["region_id"],
            "bbox_1000": [0, 0, 500, 1000],
            "scrollable": self.scrollable,
        }

    def inventory(self, _shot, _discovery, selected, _localization,
                  force_refresh=False, image_mode="crop"):
        self.inventoried.append(
            (selected["region_id"], force_refresh, image_mode))
        return ({
            "status": "ok",
            "function_entries": (
                self.elements if self.elements is not None else [{
                "entry_id": "e0", "target": "Open details",
            }]
            ),
        }, Image.new("RGB", (20, 20), "white"))


class _Writer:
    def __init__(self):
        self.saved = []

    def save_region_image(self, state_id, region_id, payload):
        self.saved.append((state_id, region_id, payload))


class _RegionRegistry:
    def mark_seen(self, *_args):
        pass

    def record_mapped_elements(self, *_args):
        pass


class _Graph:
    def __init__(self):
        self.graph = nx.DiGraph()
        self.graph.add_node("s1")
        self.records = []
        self.scroll_ledger = {}

    def register_capability_candidates(self, _state_id, records):
        self.records = list(records)
        return [record["capability_id"] for record in self.records]

    def record_scroll_scope(self, **payload):
        record = dict(payload)
        record["state_ids"] = [str(payload.get("state_id") or "")]
        record["complete"] = (
            payload.get("classification") == "static"
            and payload.get("termination") == "static"
            and payload.get("top_restored") is True
        )
        self.scroll_ledger[payload["scope_id"]] = record
        return record


def _host(experiment):
    block = {
        "local_id": "r0", "region_id": "s1:r0", "role": "Main",
        "description": "Primary functions.", "element_ids": [],
        "element_names": [], "observation_status": "pending",
    }
    data = {
        "page_name": "Demo", "page_id": "p1", "variant_id": "v1",
        "observed_facts": {}, "visible_capabilities": [],
        "elements": [], "semantic_blocks": [block],
        "region_observation": {
            "s1:r0": {"status": "pending", "attempts": 0, "reason": ""},
        },
    }
    return SimpleNamespace(
        _state_data={"s1": data},
        _region_inventory_experiment=experiment,
        writer=_Writer(),
        registry=SimpleNamespace(set_buttons=lambda *_args: None),
        region_registry=_RegionRegistry(),
        graph=_Graph(),
        perception=SimpleNamespace(
            last_page_name="", last_semantic_blocks=[]),
        _last_live_observation_state_id="",
        _last_live_observation_elements=None,
        _persist_exploration_state=lambda *_args: None,
        _persist_online_capabilities=lambda *_args: None,
        review_debug=SimpleNamespace(record_event=lambda *_args, **_kwargs: None),
    )


def test_observes_only_one_selected_region_then_exposes_its_controls():
    experiment = _Experiment()
    host = _host(experiment)

    result = observe_next_region(
        host, "s1", {"screenshot": b"current"})

    assert result == "updated"
    assert pending_region_ids(host, "s1") == []
    assert [element.name for element in
            host._state_data["s1"]["elements"]] == ["Open details"]
    element = host._state_data["s1"]["elements"][0]
    assert element.el_type == "button"
    assert element.action_label == "e0"
    assert element.category == "control"
    assert element.execution_safety == "safe"
    assert element.semantic_evidence == ""
    assert experiment.located == [("r0", False)]
    assert experiment.inventoried == [("r0", False, "context_crop")]
    assert host.writer.saved[0][:2] == ("s1", "s1:r0")
    assert host.graph.scroll_ledger["region:s1:r0"]["complete"] is True
    assert host.graph.scroll_ledger["region:s1:r0"][
        "classification"] == "static"
    assert host._state_data["s1"]["semantic_blocks"][0][
        "viewport_bbox_1000"] == [0, 0, 500, 1000]


def test_agent_inspect_region_tool_reuses_region_observation_contract():
    host = _host(_Experiment())
    host._state_data["s1"]["semantic_blocks"][0][
        "viewport_bbox_1000"] = [0, 0, 500, 1000]
    directory = current_region_directory(host, "s1")

    result = execute_agent_tool(
        ToolContext(
            host=host,
            state_id="s1",
            observation={"screenshot": _png_bytes()},
            page_graph={"state_ids_by_ref": {"p0": ["s1"]}},
            region_directory=directory,
        ),
        {
            "tool_name": "inspect_region",
            "arguments": {"region_ref": "r0"},
        },
    )

    assert result.status == "ok"
    assert result.data["outcome"] == "updated"
    assert result.data["evidence_images"] == ["current_full", "region_crop"]
    assert result.data["region"]["observation_status"] == "complete"
    assert result.data["region"]["controls"] == [{
        "target": "Open details", "status": "pending"}]


def test_agent_tool_catalog_declares_evidence_and_effect():
    by_name = {row["name"]: row for row in tool_catalog()}

    assert by_name["recall_page"]["evidence_mode"] == "none"
    assert by_name["recall_page"]["effect"] == "read_only"
    assert by_name["inspect_region"][
        "evidence_mode"] == "current_and_region"
    assert by_name["inspect_region"]["effect"] == "perception_write"


def test_agent_tool_reports_missing_required_screenshot():
    host = _host(_Experiment())
    directory = current_region_directory(host, "s1")

    result = execute_agent_tool(
        ToolContext(
            host=host,
            state_id="s1",
            observation={},
            page_graph={},
            region_directory=directory,
        ),
        {
            "tool_name": "inspect_region",
            "arguments": {"region_ref": "r0"},
        },
    )

    assert result.status == "missing_evidence"
    assert result.message == "current screenshot unavailable"


def test_read_only_agent_tool_does_not_require_a_screenshot():
    host = _host(_Experiment())

    result = execute_agent_tool(
        ToolContext(
            host=host,
            state_id="s1",
            observation={},
            page_graph={"state_ids_by_ref": {"p0": ["s1"]}},
            region_directory=current_region_directory(host, "s1"),
        ),
        {
            "tool_name": "recall_page",
            "arguments": {"page_ref": "p0"},
        },
    )

    assert result.status == "ok"
    assert result.data["page_name"] == "Demo"
    assert result.observation_changed is False
    assert result.ledger_changed is False


def test_region_inventory_elements_keep_the_localized_region_guard():
    experiment = _Experiment()
    host = _host(experiment)
    image = Image.new("RGB", (200, 120), "white")
    payload = io.BytesIO()
    image.save(payload, format="PNG")

    assert observe_next_region(
        host, "s1", {"screenshot": payload.getvalue()}) == "updated"

    assert host._state_data["s1"]["elements"][0].region_bbox == [
        0, 0, 100, 120]
    assert host._state_data["s1"]["elements"][0].to_dict()["region_bbox"] == [
        0, 0, 100, 120]
    from gui_rewalk.src.core.visual_traversal.visual_perception import (
        VisualElement,
    )
    from gui_rewalk.src.core.visual_traversal.visual_resume import (
        element_from_dict,
    )
    restored = element_from_dict(
        host._state_data["s1"]["elements"][0].to_dict(), VisualElement)
    assert restored.region_bbox == [0, 0, 100, 120]


def test_empty_region_entries_complete_observation_without_capability_enrichment():
    host = _host(_Experiment(elements=[]))

    assert observe_next_region(
        host, "s1", {"screenshot": b"current"}) == "updated"

    assert host._state_data["s1"]["elements"] == []
    assert host._state_data["s1"]["region_observation"]["s1:r0"][
        "status"] == "complete"
    assert host.graph.scroll_ledger["region:s1:r0"]["complete"] is True
    assert host.graph.records == []


def test_scrollable_region_inventory_remains_pending_for_scroll_audit():
    host = _host(_Experiment(scrollable=True))

    assert observe_next_region(
        host, "s1", {"screenshot": b"current"}) == "updated"

    record = host.graph.scroll_ledger["region:s1:r0"]
    assert record["classification"] == "unknown"
    assert record["termination"] == "pending"
    assert record["complete"] is False


def test_static_region_observation_scroll_and_scheduler_share_one_scope():
    from gui_rewalk.src.core.graph.traversal_completion import (
        evaluate_traversal_completion,
    )
    from gui_rewalk.src.core.visual_traversal.grounding.scroll import (
        ScrollContext,
        ScrollRuntime,
    )
    from gui_rewalk.src.core.visual_traversal.runtime.scheduling import (
        prepare_current_scroll_audit,
    )

    host = _host(_Experiment(scrollable=False))
    graph = StateGraph("demo")
    graph.add_state(
        "s1", [], "s1.png", "demo",
        page_name="Demo", page_id="p1", variant_id="v1",
        semantic_blocks=host._state_data["s1"]["semantic_blocks"],
        perception_mode="region_lazy",
    )
    graph.graph.nodes["s1"]["region_observation"] = {
        "s1:r0": {"status": "pending", "attempts": 0, "reason": ""},
    }
    host.graph = graph
    host._retry_incomplete_scroll_audit = lambda *_args: (_ for _ in ()).throw(
        AssertionError("completed static Region must not be retried"))

    assert observe_next_region(
        host, "s1", {"screenshot": b"current"}) == "updated"

    runtime = ScrollRuntime(ScrollContext(
        env=SimpleNamespace(
            provider_name="desktop",
            step=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("static Region must not receive a scroll probe"))),
        perception=SimpleNamespace(
            use_semantic_inventory=True,
            last_surface_scrollable=False,
            last_semantic_blocks=host.perception.last_semantic_blocks,
        ),
        focus_guard=None, page_judge=None, block_identity_judge=None,
        region_registry=host.region_registry, writer=host.writer,
        state_data=host._state_data, pending_transition=None,
        is_touch=False, stitch_node_image=False,
        last_scroll_frames=[], last_scroll_offsets=[],
        semantic_scroll_seed_region_crops={},
        semantic_scroll_seed_region_bboxes={},
        frame_phash=lambda _shot: 0,
        screen_wh=lambda _obs: (100, 100),
        record_scroll_evidence=graph.record_scroll_scope,
        map_to_top=lambda *_args, **_kwargs: None,
        begin_node_local_accumulation=lambda: None,
        accumulate_node_local_functions=lambda: None,
        collected_node_local_functions=lambda rows: rows,
    ))
    runtime._scroll_aggregate(
        {"screenshot": b"current"},
        host._state_data["s1"]["elements"],
        state_id="s1",
    )

    assert set(graph.scroll_ledger) == {"region:s1:r0"}
    assert graph.scroll_ledger["region:s1:r0"]["complete"] is True
    assert prepare_current_scroll_audit(
        host, "s1", {"screenshot": b"current"}, [], [], 0) is None
    report = evaluate_traversal_completion(graph)
    assert report["checks"]["scroll_exhaustion"]["passed"] is True


def test_confirmed_new_state_registers_region_directory_without_controls(
        tmp_path):
    image = Image.new("RGB", (20, 20), "white")
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    screenshot = payload.getvalue()
    temp_shot = tmp_path / "registration.png"

    def screenshot_to_tmp(value):
        temp_shot.write_bytes(value)
        return str(temp_shot)

    host = SimpleNamespace(
        app_name="demo", agent=object(), vlm_ledger=None,
        _region_inventory_experiment=_Experiment(),
        registry=VisualStateRegistry(namespace="demo"),
        writer=ArtifactWriter(str(tmp_path / "artifacts")),
        graph=StateGraph("demo"), _state_data={}, _bfs_queue=deque(),
        _screenshot_to_tmp=screenshot_to_tmp,
        perception=SimpleNamespace(
            last_page_name="", last_semantic_blocks=[]),
        review_debug=SimpleNamespace(
            record_event=lambda *_args, **_kwargs: None),
    )

    state_id, is_new = register_region_map(
        host, {"screenshot": screenshot}, [], [],
        proposed_page_name="Account security settings")

    assert is_new is True
    assert host._state_data[state_id]["elements"] == []
    assert host._state_data[state_id]["page_name"] == (
        "Account security settings")
    assert pending_region_ids(host, state_id) == [f"{state_id}:r0"]
    node = host.graph.graph.nodes[state_id]
    assert node["perception_mode"] == "region_lazy"
    assert node["region_observation"][f"{state_id}:r0"]["status"] == "pending"


def test_new_region_map_uses_candidate_fallback_name_without_collision_probe(
        monkeypatch):
    from gui_rewalk.src.core.visual_traversal.runtime import region_observation
    from gui_rewalk.src.core.visual_traversal.state import registration

    captured = {}
    host = SimpleNamespace(
        perception=SimpleNamespace(use_semantic_inventory=True),
        identity_resolver=SimpleNamespace(
            resolve=lambda *_args, **_kwargs: IdentityResolution(
                "new", reason="shortlisted Pages differ",
                proposed_new_page_name="Network settings")),
        review_debug=SimpleNamespace(
            record_event=lambda *_args, **_kwargs: None),
        agent=object(),
        _map_guided_preferred_state=None,
        _map_guided_force_new=False,
        _map_guided_occurrence_page_state=None,
    )
    monkeypatch.setattr(
        region_observation, "register_region_map",
        lambda _host, _obs, _path, replay_hints=None, **kwargs:
        captured.update(kwargs) or ("new-state", True))
    monkeypatch.setenv("GUIWALK_REGION_LAZY_INVENTORY", "1")

    result = registration.register_observation(
        host, {"screenshot": b"current"}, [])

    assert result == ("new-state", True)
    assert captured["proposed_page_name"] == "Network settings"
    assert "variant_of_state_id" not in captured
    assert "variant_candidate_state_ids" not in captured


def test_known_fixture_stateful_landing_refreshes_live_inventory(monkeypatch):
    from gui_rewalk.src.core.visual_traversal.state import registration

    captured = {}
    host = SimpleNamespace(
        perception=SimpleNamespace(
            use_semantic_inventory=True,
            fixture_inventory_provider=lambda *_args: None,
        ),
        identity_resolver=SimpleNamespace(
            resolve=lambda *_args, **_kwargs: IdentityResolution(
                "known", "chats", "same page")),
        review_debug=SimpleNamespace(
            record_event=lambda *_args, **_kwargs: None),
        _pending_transition={
            "source_id": "chats",
            "requires_fresh_observation": True,
        },
        _map_guided_preferred_state=None,
        _map_guided_force_new=False,
        _map_guided_occurrence_page_state=None,
    )
    monkeypatch.setattr(
        registration, "_semantic_inventory_for_landing",
        lambda *_args, **_kwargs: ["fresh-search-state"])
    monkeypatch.setattr(
        registration, "_refresh_passive_feedback_observation",
        lambda _host, obs, elements: (obs, elements))

    def register_semantic(current, _obs, _path, **kwargs):
        captured["preferred_state"] = current._map_guided_preferred_state
        captured["arrival_elements"] = kwargs["arrival_elements"]
        return "chats", False

    monkeypatch.setattr(
        registration, "_register_semantic_observation", register_semantic)

    assert registration.register_observation(
        host, {"screenshot": b"after"}, []) == ("chats", False)
    assert captured == {
        "preferred_state": "chats",
        "arrival_elements": ["fresh-search-state"],
    }


def test_page_identity_dismisses_interruption_before_region_map(monkeypatch):
    from gui_rewalk.src.core.visual_traversal.runtime import region_observation
    from gui_rewalk.src.core.visual_traversal.state import registration

    screenshots = []
    resolutions = iter([
        IdentityResolution(
            "unresolved", reason="external foreground notification",
            is_interruption=True),
        IdentityResolution(
            "new", reason="selected Pages differ",
            proposed_new_page_name="Calendar"),
    ])

    def dismiss(obs, *, page_identity_flagged=False):
        assert page_identity_flagged is True
        assert obs["screenshot"] == b"popup"
        return {"screenshot": b"clean"}

    host = SimpleNamespace(
        perception=SimpleNamespace(use_semantic_inventory=True),
        identity_resolver=SimpleNamespace(
            resolve=lambda shot, **_kwargs:
            screenshots.append(shot) or next(resolutions)),
        review_debug=SimpleNamespace(
            record_event=lambda *_args, **_kwargs: None),
        agent=object(),
        _dismiss_interruptions=dismiss,
        _startup_surface_unresolved=False,
        _map_guided_preferred_state=None,
        _map_guided_force_new=False,
        _map_guided_occurrence_page_state=None,
    )
    captured = {}
    monkeypatch.setattr(
        region_observation, "register_region_map",
        lambda _host, obs, _path, replay_hints=None, **_kwargs:
        captured.update(obs) or ("new-state", True))
    monkeypatch.setenv("GUIWALK_REGION_LAZY_INVENTORY", "1")
    observation = {"screenshot": b"popup"}

    result = registration.register_observation(host, observation, [])

    assert result == ("new-state", True)
    assert screenshots == [b"popup", b"clean"]
    assert observation["screenshot"] == b"clean"
    assert captured["screenshot"] == b"clean"


def test_unremoved_page_identity_interruption_is_not_registered(monkeypatch):
    from gui_rewalk.src.core.visual_traversal.runtime import region_observation
    from gui_rewalk.src.core.visual_traversal.state import registration

    host = SimpleNamespace(
        perception=SimpleNamespace(use_semantic_inventory=True),
        identity_resolver=SimpleNamespace(
            resolve=lambda *_args, **_kwargs: IdentityResolution(
                "unresolved", reason="external foreground notification",
                is_interruption=True)),
        review_debug=SimpleNamespace(
            record_event=lambda *_args, **_kwargs: None),
        _dismiss_interruptions=lambda obs, **_kwargs: obs,
        _startup_surface_unresolved=False,
        _map_guided_preferred_state=None,
        _map_guided_force_new=False,
        _map_guided_occurrence_page_state=None,
    )
    monkeypatch.setattr(
        region_observation, "register_region_map",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("interruption screenshot must not be registered")))

    with pytest.raises(
            PerceptionUnavailable,
            match="interruption remains unresolved"):
        registration.register_observation(
            host, {"screenshot": b"popup"}, [])


def test_region_failure_retries_three_times_then_stays_unresolved():
    host = _host(_Experiment(fail=True))

    results = [
        observe_next_region(host, "s1", {"screenshot": b"current"})
        for _ in range(3)
    ]

    assert results == ["retry", "retry", "unresolved"]
    assert pending_region_ids(host, "s1") == []
    assert unresolved_region_ids(host) == ["s1:s1:r0"]


def test_same_page_variant_records_region_introduced_by_the_action(tmp_path):
    def screenshot(color):
        image = Image.new("RGB", (20, 20), color)
        payload = io.BytesIO()
        image.save(payload, format="PNG")
        return payload.getvalue()

    temp_shot = tmp_path / "registration.png"

    def screenshot_to_tmp(value):
        temp_shot.write_bytes(value)
        return str(temp_shot)

    host = SimpleNamespace(
        app_name="clock", agent=object(), vlm_ledger=None,
        _region_inventory_experiment=_Experiment(regions=[{
            "region_id": "r0", "name": "Alarm list",
            "description": "Shows alarms or the empty state.",
        }], interface_name="Alarm"),
        registry=VisualStateRegistry(namespace="clock"),
        writer=ArtifactWriter(str(tmp_path / "artifacts")),
        graph=StateGraph("clock"), _state_data={}, _bfs_queue=deque(),
        _screenshot_to_tmp=screenshot_to_tmp,
        perception=SimpleNamespace(
            last_page_name="", last_semantic_blocks=[]),
        review_debug=SimpleNamespace(
            record_event=lambda *_args, **_kwargs: None),
    )
    empty_id, _ = register_region_map(
        host, {"screenshot": screenshot("white")}, [], [])

    class PartitionJudge:
        last_raw_response = '{"matches":[]}'

        @staticmethod
        def align_region_partitions(*_args):
            return {
                "matches": [{
                    "known_region_ids": ["A1"],
                    "current_region_ids": ["B1"],
                    "reason": "same alarm container",
                }],
                "new_current_region_ids": ["B2"],
                "unresolved_current_region_ids": [],
                "unmatched_known_region_ids": [],
            }

    host.block_identity_judge = PartitionJudge()
    host._region_inventory_experiment = _Experiment(
        interface_name="Alarm",
        regions=[
            {
                "region_id": "r0", "name": "Alarm list",
                "description": "Shows alarms or the empty state.",
            },
            {
                "region_id": "r1", "name": "New alarm details",
                "description": "Configures the newly created alarm.",
            },
        ],
    )
    event = host.graph.record_action_event(
        source=empty_id, action={"action_type": "CLICK"},
        element_label="Create alarm")
    host._pending_transition = {
        "source_id": empty_id,
        "clicked_label": "Create alarm",
        "event_index": event,
    }

    populated_id, _ = register_region_map(
        host, {"screenshot": screenshot("gray")}, [], [],
        variant_of_state_id=empty_id)

    source = host._state_data[empty_id]
    target = host._state_data[populated_id]
    transition = target["region_transition"]
    assert target["page_id"] == source["page_id"]
    assert target["variant_id"] != source["variant_id"]
    assert transition["relationship"] == "same_page_variant"
    assert transition["persisted_region_ids"] == [
        source["semantic_blocks"][0]["region_id"]]
    assert len(transition["introduced_regions"]) == 1
    introduced = transition["introduced_regions"][0]
    assert introduced["name"] == "New alarm details"
    assert introduced["introduced_by_attempt_id"] == "clock:1"
    assert transition["result_binding"] == {
        "kind": "introduced_region",
        "status": "bound",
        "attempt_id": "clock:1",
        "region_ids": [introduced["region_id"]],
    }


def test_region_mapping_uses_the_vlm_candidate_with_persisted_correspondence(
        tmp_path):
    def screenshot(color):
        image = Image.new("RGB", (20, 20), color)
        payload = io.BytesIO()
        image.save(payload, format="PNG")
        return payload.getvalue()

    temp_shot = tmp_path / "registration.png"

    def screenshot_to_tmp(value):
        temp_shot.write_bytes(value)
        return str(temp_shot)

    host = SimpleNamespace(
        app_name="clock", agent=object(), vlm_ledger=None,
        _region_inventory_experiment=_Experiment(
            interface_name="New Alarm",
            regions=[{
                "region_id": "r0", "name": "Dialog controls",
                "description": "Controls for creating one alarm.",
            }]),
        registry=VisualStateRegistry(namespace="clock"),
        writer=ArtifactWriter(str(tmp_path / "artifacts")),
        graph=StateGraph("clock"), _state_data={}, _bfs_queue=deque(),
        _screenshot_to_tmp=screenshot_to_tmp,
        perception=SimpleNamespace(
            last_page_name="", last_semantic_blocks=[]),
        review_debug=SimpleNamespace(
            record_event=lambda *_args, **_kwargs: None),
    )
    dialog_id, _ = register_region_map(
        host, {"screenshot": screenshot("white")}, [], [])
    host._region_inventory_experiment = _Experiment(
        interface_name="Alarms",
        regions=[{
            "region_id": "r0", "name": "Top navigation",
            "description": "Alarm navigation and creation entry.",
        }])
    list_id, _ = register_region_map(
        host, {"screenshot": screenshot("gray")}, [], [])

    class CandidateJudge:
        last_raw_response = '{"matches":[]}'

        def align_region_partitions(
                self, _known_name, known_rows, _current_name, _current_rows,
                _screenshots, _action):
            if known_rows[0]["name"] == "Top navigation":
                return {
                    "matches": [{
                        "known_region_ids": ["A1"],
                        "current_region_ids": ["B1"],
                        "reason": "same stable navigation region",
                    }],
                    "new_current_region_ids": [],
                    "unresolved_current_region_ids": [],
                    "unmatched_known_region_ids": [],
                }
            return {
                "matches": [],
                "new_current_region_ids": ["B1"],
                "unresolved_current_region_ids": [],
                "unmatched_known_region_ids": ["A1"],
            }

    host.block_identity_judge = CandidateJudge()
    host._pending_transition = {
        "source_id": dialog_id,
        "clicked_label": "Add",
    }
    host._region_inventory_experiment = _Experiment(
        interface_name="Alarms",
        regions=[{
            "region_id": "r0", "name": "Alarm navigation",
            "description": "Current alarm navigation and creation entry.",
        }])

    target_id, _ = register_region_map(
        host, {"screenshot": screenshot("black")}, [], [],
        variant_of_state_id=dialog_id,
        variant_candidate_state_ids=(dialog_id, list_id))

    target = host._state_data[target_id]
    assert target["region_partition_mapping"][
        "mapping_source_state_id"] == list_id
    assert target["semantic_blocks"][0]["region_id"] == (
        host._state_data[list_id]["semantic_blocks"][0]["region_id"])
    assert target["page_id"] == host._state_data[list_id]["page_id"]


def test_different_page_keeps_region_identity_page_scoped(tmp_path):
    def screenshot(color):
        image = Image.new("RGB", (20, 20), color)
        payload = io.BytesIO()
        image.save(payload, format="PNG")
        return payload.getvalue()

    temp_shot = tmp_path / "registration.png"

    def screenshot_to_tmp(value):
        temp_shot.write_bytes(value)
        return str(temp_shot)

    host = SimpleNamespace(
        app_name="clock", agent=object(), vlm_ledger=None,
        _region_inventory_experiment=_Experiment(regions=[{
            "region_id": "r0", "name": "Alarm list",
            "description": "Shows alarms or the empty state.",
        }], interface_name="Alarms"),
        registry=VisualStateRegistry(namespace="clock"),
        writer=ArtifactWriter(str(tmp_path / "artifacts")),
        graph=StateGraph("clock"), _state_data={}, _bfs_queue=deque(),
        _screenshot_to_tmp=screenshot_to_tmp,
        perception=SimpleNamespace(
            last_page_name="", last_semantic_blocks=[]),
        review_debug=SimpleNamespace(
            record_event=lambda *_args, **_kwargs: None),
    )
    source_id, _ = register_region_map(
        host, {"screenshot": screenshot("white")}, [], [])

    class UnexpectedJudge:
        last_raw_response = ""

        @staticmethod
        def align_region_partitions(*_args):
            raise AssertionError(
                "different-page Regions must not inherit source identities")

    host.block_identity_judge = UnexpectedJudge()
    host._region_inventory_experiment = _Experiment(
        interface_name="New Alarm",
        regions=[
            {
                "region_id": "r0", "name": "Dialog header",
                "description": "Cancel and Add actions.",
            },
            {
                "region_id": "r1", "name": "Time selector",
                "description": "Hour and minute controls.",
            },
        ],
    )
    event = host.graph.record_action_event(
        source=source_id, action={"action_type": "CLICK"},
        element_label="Add Alarm")
    host._pending_transition = {
        "source_id": source_id,
        "clicked_label": "Add Alarm",
        "event_index": event,
    }

    target_id, _ = register_region_map(
        host, {"screenshot": screenshot("gray")}, [], [])

    target = host._state_data[target_id]
    transition = target["region_transition"]
    assert target["region_partition_mapping"]["status"] == "page_scoped_new"
    assert [block["mapping_status"] for block in target["semantic_blocks"]] == [
        "new", "new"]
    assert transition["persisted_region_ids"] == []
    assert [item["name"] for item in transition["introduced_regions"]] == [
        "Dialog header", "Time selector"]
    assert transition["removed_region_ids"] == [
        host._state_data[source_id]["semantic_blocks"][0]["region_id"]]
