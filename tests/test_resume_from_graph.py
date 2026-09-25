"""[2026-07-08 用户 断点续跑] resume_from_graph rebuilds the in-memory dedup /
identity ledgers from a saved graph.json so traversal CONTINUES instead of re-
exploring. Proves: (1) ledgers repopulate from persisted nodes and all runtime
collaborators are rebound to the rebuilt objects; (2) a sidebar
item clicked before the save is dropped from candidates on resume via the region
ledger — even with a DIFFERENT uid (the cross-page case uid-dedup misses); (3)
an unclicked sibling still enqueues; (4) invalid input cannot partially mutate the
existing engine or the loaded graph. No model/key needed (dummy agent stubs)."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from gui_rewalk.src.core.graph.state_graph import StateGraph
from gui_rewalk.src.core.scenario.capability_induction import (
    project_autonomous_inventory,
)
from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine
from gui_rewalk.src.core.visual_traversal import visual_engine as visual_engine_module
from gui_rewalk.src.core.visual_traversal.visual_resume import (
    runtime_state_consistency_issues,
    sync_live_to_graph,
)
from gui_rewalk.src.core.visual_traversal.visual_state import (
    compute_page_id,
    compute_variant_id,
    observed_variant_facts,
    semantic_page_key,
    variant_signature,
)


class _Stub:
    """Answers any attribute/call with a no-op — stands in for agent/env/perception
    (engine __init__ only stores refs; nothing is invoked during resume)."""
    action_space = "pyautogui"
    vm_platform = "docker"          # -> desktop (is_touch False), region path live
    vlm_response_cache_dir = None
    def __getattr__(self, _n):
        return _Stub()
    def __call__(self, *a, **k):
        return None


def _el(eid, name, uid, region_id, visited, role="nav_sidebar",
        abnormal_reason=""):
    return {"id": eid, "name": name, "uid": uid, "region_id": region_id,
            "region": role, "visited": visited, "center": [10, 10 + eid * 5],
            "bbox_xywh": [0, eid * 5, 20, 5], "el_type": "link",
            "interactive": True, "category": "navigation", "group": "",
            "abnormal_reason": abnormal_reason, "abnormal_detail": "test crash"}


def _fp():
    # a valid pHash hex (16 hex chars) so the registry tuple rebuilds cleanly
    return {"version": "visual_fingerprint_v1", "phash": "0" * 16}


def _build_engine(tmp):
    return VisualTraversalEngine(
        env=_Stub(), agent=_Stub(), perception=_Stub(), app_name="settings",
        output_root=tmp, focus_guard_enabled=False, region_dedup=True)


def _runtime_refs(engine):
    """Object identities that an unsuccessful resume must not disturb."""
    return {
        "graph": engine.graph,
        "registry": engine.registry,
        "region_registry": engine.region_registry,
        "memory": engine.mem,
        "state_data": engine._state_data,
        "frontier": engine._bfs_queue,
        "visited_uids": engine._visited_uids,
        "explored_groups": engine._explored_groups,
        "abnormal_buttons": engine._abnormal_buttons,
        "router_graph": engine.router.graph,
        "router_regions": engine.router.regions,
        "router_state_data": engine.router.state_data,
        "identity_registry": engine.identity_resolver.registry,
        "identity_state_data": engine.identity_resolver.state_data,
        "live_sync": engine.graph._live_sync,
    }


def _assert_runtime_refs_unchanged(engine, before):
    assert engine.graph is before["graph"]
    assert engine.registry is before["registry"]
    assert engine.region_registry is before["region_registry"]
    assert engine.mem is before["memory"]
    assert engine._state_data is before["state_data"]
    assert engine._bfs_queue is before["frontier"]
    assert engine._visited_uids is before["visited_uids"]
    assert engine._explored_groups is before["explored_groups"]
    assert engine._abnormal_buttons is before["abnormal_buttons"]
    assert engine.router.graph is before["router_graph"]
    assert engine.router.regions is before["router_regions"]
    assert engine.router.state_data is before["router_state_data"]
    assert engine.identity_resolver.registry is before["identity_registry"]
    assert engine.identity_resolver.state_data is before["identity_state_data"]
    assert engine.graph._live_sync == before["live_sync"]


def _make_graph(tmp):
    """Two pages sharing sidebar region r1. Page A clicked 'Network' (visited);
    page B has 'Network' UNclicked with a DIFFERENT uid (so only the region
    ledger — not uid dedup — can catch it) plus an unclicked 'Bluetooth'."""
    sg = StateGraph("settings")
    a = [_el(0, "Network", "uidA_net", "r1", False),
         _el(1, "Bluetooth", "uidA_bt", "r1", True),
         _el(2, "Sound", "uidA_snd", "r1", True,
             abnormal_reason="app_crash")]
    b = [_el(0, "Network", "uidB_net", "r1", False),   # diff uid, same region+name
         _el(1, "Bluetooth", "uidB_bt", "r1", False),
         _el(2, "Sound", "uidB_snd", "r1", False),
         _el(3, "Wi-Fi list", "uidB_wifi", "r2", False, role="content")]
    sg.add_state("A", a, os.path.join(tmp, "A.png"), "settings",
                 action_path_from_root=[], state_type="visual", visual_fingerprint=_fp())
    sg.add_state("B", b, os.path.join(tmp, "B.png"), "settings",
                 action_path_from_root=[{"type": "CLICK", "element_id": 0}],
                 state_type="visual", visual_fingerprint=_fp())
    sg.record_action_event(
        source="A", target="B", action={"type": "CLICK"}, element_id="0",
        element_label="Network", region="nav_sidebar",
        outcome="transitioned_consistent", committed=True, landing_verified=True)
    sg.record_abnormal_button(
        state_id="A", element_id="2", element_uid="uidA_snd",
        element_name="Sound", region="nav_sidebar", region_id="r1",
        reason="app_crash", detail="target window disappeared")
    sg._action_counter = 7
    p = os.path.join(tmp, "graph.json")
    sg.save(p)
    return p


def _make_mid_build_bad_graph(tmp):
    """A valid first node followed by a malformed persisted element row."""
    graph = StateGraph("settings")
    valid = [_el(0, "Network", "uidA_net", "r1", True),
             _el(1, "Bluetooth", "uidA_bt", "r1", False)]
    graph.add_state(
        "A", valid, os.path.join(tmp, "A.png"), "settings",
        action_path_from_root=[], state_type="visual", visual_fingerprint=_fp())
    graph.add_state(
        "B", valid, os.path.join(tmp, "B.png"), "settings",
        action_path_from_root=[], state_type="visual", visual_fingerprint=_fp())
    # add_state needs dictionaries for its coarse signature, so corrupt the
    # persisted payload after insertion. The rebuilder processes A before B.
    graph.graph.nodes["B"]["elements"] = [42]
    graph._action_counter = 99
    live_sync_sentinel = object()
    graph._live_sync = live_sync_sentinel
    return graph, live_sync_sentinel


def test_resume_rebuilds_ledgers_and_dedups():
    with tempfile.TemporaryDirectory() as tmp:
        path = _make_graph(tmp)
        eng = _build_engine(tmp)
        before = _runtime_refs(eng)
        loaded = StateGraph.load(path)
        assert eng.resume_from_graph(loaded), "resume must succeed"

        # The atomic commit publishes fresh ledgers and rebinds every collaborator.
        assert eng.graph is loaded
        assert eng.registry is not before["registry"]
        assert eng.region_registry is not before["region_registry"]
        assert eng.mem is not before["memory"]
        assert eng._state_data is not before["state_data"]
        assert eng._bfs_queue is not before["frontier"]
        assert eng.router.graph is eng.graph
        assert eng.router.regions is eng.region_registry
        assert eng.router.state_data is eng._state_data
        assert eng.identity_resolver.registry is eng.registry
        assert eng.identity_resolver.state_data is eng._state_data
        hook = eng.graph._live_sync
        assert getattr(hook, "__self__", None) is eng
        assert getattr(hook, "__func__", None) is eng._sync_live_to_graph.__func__
        assert eng._action_count == 7
        assert list(eng._bfs_queue) == ["A", "B"]

        # (1) ledgers rebuilt
        assert "uidA_net" not in eng._visited_uids, \
            "one verified action must not close every action on the control"
        assert eng._state_data["A"]["elements"][0].visited is False, \
            "resume requires an explicit exploration terminal status"
        assert eng.registry._region_sets.get("A"), "A region-set rebuilt"
        assert not eng.region_registry.is_clicked("r1", "Network"), \
            "action history must not become whole-control Region coverage"
        assert not eng.region_registry.is_clicked("r1", "Bluetooth")
        assert not eng.region_registry.is_clicked("r1", "Sound"), \
            "crash retirement must not masquerade as successful region coverage"
        assert len(eng._abnormal_buttons) == 1
        assert eng._state_data["A"]["elements"][1].visited is False, \
            "optimistic visited without a verified source action must reopen"
        # r1 shared across A and B -> seen_on>1
        assert len(eng.region_registry._regions["r1"].seen_on) == 2

        names_a = [e.name for e in eng._unvisited_candidates("A")]
        assert "Network" in names_a, \
            "verified action history is Explorer context, not frontier closure"

        # (2)+(3) candidate filtering on page B (the resume payoff)
        names = [e.name for e in eng._unvisited_candidates("B")]
        assert "Network" in names, \
            "shared click on A must not replace B-local peer navigation evidence"
        assert "Bluetooth" in names, "unclicked sibling still enqueues"
        assert "Sound" in names, \
            "a terminal result on page A must not retire page B's shared control"
        assert "Wi-Fi list" in names, "page-B own content still enqueues"
        print("PASS: resume rebuilds ledgers; peer-navigation coverage remains "
              "source-local; unclicked items kept")


def test_resume_restores_semantic_region_table_and_perception_mode():
    with tempfile.TemporaryDirectory() as tmp:
        graph = StateGraph("settings")
        graph.add_state(
            "A", [_el(0, "Network", "uidA_net", "r1", False)],
            os.path.join(tmp, "A.png"), "settings",
            action_path_from_root=[], state_type="visual",
            visual_fingerprint=_fp(),
            semantic_blocks=[{
                "region_id": "r1", "scrollable": False,
                "element_ids": [0], "element_names": ["Network"],
            }],
            perception_mode="semantic_inventory",
        )

        engine = _build_engine(tmp)
        assert engine.resume_from_graph(graph)
        assert engine._state_data["A"]["semantic_blocks"] == [{
            "region_id": "r1", "scrollable": False,
            "element_ids": [0], "element_names": ["Network"],
        }]
        assert engine._state_data["A"]["perception_mode"] == \
            "semantic_inventory"


def test_resume_preserves_external_variant_and_projected_inventory():
    with tempfile.TemporaryDirectory() as tmp:
        graph = StateGraph("clock")
        graph.add_state(
            "auto-state", [], os.path.join(tmp, "auto-state.png"), "clock",
            page_name="Alarms", page_id="auto-page",
            variant_id="auto-state",
            observed_facts={"summary": "Alarms"},
            perception_mode="autonomous_vlm",
        )
        project_autonomous_inventory(
            graph,
            {
                "entries": [{
                    "entry_id": "ae1",
                    "page_name": "Alarms",
                    "region_name": "Toolbar",
                    "target": "Add alarm",
                    "status": "discovered",
                    "source_state_id": "auto-state",
                    "task_eligible": True,
                }],
                "pending_actions": [],
            },
            {
                "region_groups": {
                    "groups": [{
                        "region_ref": "rg1",
                        "representative": {
                            "page_name": "Alarms",
                            "region_name": "Toolbar",
                        },
                        "occurrences": [],
                    }],
                },
            },
        )
        path = os.path.join(tmp, "collection-graph.json")
        graph.save(path)

        engine = _build_engine(tmp)
        assert engine.resume_from_graph(StateGraph.load(path))
        state = engine._state_data["auto-state"]
        assert state["page_id"] == "auto-page"
        assert state["variant_id"] == "auto-state"
        assert engine.registry.variant_id_of("auto-state") == "auto-state"
        assert state["elements"][0].uid == "autonomous-entry:ae1"
        assert "rg1" in engine.region_registry._regions

        resumed_path = os.path.join(tmp, "resumed-collection-graph.json")
        engine.graph.save(resumed_path)
        assert not runtime_state_consistency_issues(
            engine.graph, engine._state_data, registry=engine.registry)


def test_resume_reopens_legacy_shared_terminal_marker():
    with tempfile.TemporaryDirectory() as tmp:
        graph = StateGraph("settings")
        element = _el(
            0, "Settings", "shared-settings", "r1", True,
            abnormal_reason="terminal_observed_outcome")
        element["exploration_status"] = "terminal"
        graph.add_state(
            "activity", [element], os.path.join(tmp, "activity.png"),
            "settings", action_path_from_root=[], state_type="visual",
            visual_fingerprint=_fp())
        path = os.path.join(tmp, "graph.json")
        graph.save(path)

        engine = _build_engine(tmp)
        assert engine.resume_from_graph(StateGraph.load(path))
        restored = engine._state_data["activity"]["elements"][0]
        assert restored.abnormal_reason == ""
        assert restored.exploration_status == ""
        assert restored.visited is False
        assert [item.name for item in engine._unvisited_candidates("activity")] \
            == ["Settings"]


def test_resume_reopens_bounded_terminal_without_structured_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        graph = StateGraph("settings")
        element = _el(
            0, "Retry target", "retry-target", "r1", True,
            abnormal_reason="target_rebind_failed")
        element["exploration_status"] = "terminal"
        graph.add_state(
            "activity", [element], os.path.join(tmp, "activity.png"),
            "settings", action_path_from_root=[], state_type="visual",
            visual_fingerprint=_fp())
        graph.record_abnormal_button(
            state_id="activity", element_id="0",
            element_uid="retry-target", element_name="Retry target",
            region="content", region_id="r1",
            reason="target_rebind_failed", detail="legacy record")

        engine = _build_engine(tmp)
        assert engine.resume_from_graph(graph)
        restored = engine._state_data["activity"]["elements"][0]
        assert restored.abnormal_reason == ""
        assert restored.exploration_status == ""
        assert restored.visited is False
        assert engine._abnormal_buttons == set()
        assert [item.name for item in engine._unvisited_candidates("activity")] \
            == ["Retry target"]


def test_resume_keeps_bounded_terminal_with_structured_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        graph = StateGraph("settings")
        element = _el(
            0, "Retry target", "retry-target", "r1", True,
            abnormal_reason="target_rebind_failed")
        element["exploration_status"] = "terminal"
        graph.add_state(
            "activity", [element], os.path.join(tmp, "activity.png"),
            "settings", action_path_from_root=[], state_type="visual",
            visual_fingerprint=_fp())
        graph.record_abnormal_button(
            state_id="activity", element_id="0",
            element_uid="retry-target", element_name="Retry target",
            region="content", region_id="r1",
            reason="target_rebind_failed", detail="bounded retry",
            evidence={
                "kind": "bounded_local_failure",
                "attempts_used": 2,
                "failure_kind": "visible_target_not_confirmed",
            })

        engine = _build_engine(tmp)
        assert engine.resume_from_graph(graph)
        restored = engine._state_data["activity"]["elements"][0]
        assert restored.abnormal_reason == "target_rebind_failed"
        assert restored.exploration_status == "terminal"
        assert restored.visited is True
        assert len(engine._abnormal_buttons) == 1
        assert engine._unvisited_candidates("activity") == []


def test_resume_applies_valid_abnormal_ledger_to_stale_node_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        graph = StateGraph("settings")
        element = _el(0, "Historical target", "", "r1", False)
        graph.add_state(
            "activity", [element], os.path.join(tmp, "activity.png"),
            "settings", action_path_from_root=[], state_type="visual",
            visual_fingerprint=_fp())
        graph.add_state(
            "known-landing", [], os.path.join(tmp, "landing.png"),
            "settings", action_path_from_root=[], state_type="visual",
            visual_fingerprint=_fp())
        graph.record_abnormal_button(
            state_id="activity", element_id="0",
            element_uid="", element_name="Historical target",
            region="content", region_id="r1",
            reason="route_unavailable", detail="bounded route replay",
            evidence={
                "kind": "route_unavailable",
                "attempts_used": 2,
                "failure_kind": "identity_unknown",
                "landed_state_id": "known-landing",
            })

        engine = _build_engine(tmp)
        assert engine.resume_from_graph(graph)
        restored = engine._state_data["activity"]["elements"][0]
        assert restored.abnormal_reason == "route_unavailable"
        assert restored.exploration_status == "terminal"
        assert restored.visited is True
        assert engine._unvisited_candidates("activity") == []


def test_graph_sync_uses_source_local_element_id_when_uid_is_empty():
    graph = StateGraph("settings")
    graph.add_state(
        "A", [_el(0, "Target", "", "r1", False)],
        "A.png", "settings", visual_fingerprint=_fp())
    element_type = visual_engine_module.VisualElement
    live = element_type(**_el(0, "Target", "", "r1", True))
    live.exploration_status = "terminal"
    live.abnormal_reason = "route_unavailable"
    live.abnormal_detail = "bounded route replay"

    sync_live_to_graph(
        graph, {"A": {"elements": [live]}}, set())

    persisted = graph.graph.nodes["A"]["elements"][0]
    assert persisted["visited"] is True
    assert persisted["exploration_status"] == "terminal"
    assert persisted["abnormal_reason"] == "route_unavailable"


def test_graph_sync_never_propagates_appearance_uid_between_sources():
    graph = StateGraph("settings")
    shared_uid = "same-overflow-crop"
    graph.add_state("A", [_el(0, "More options", shared_uid, "r1", False)],
                    "A.png", "settings", visual_fingerprint=_fp())
    graph.add_state("B", [_el(0, "More options", shared_uid, "r1", False)],
                    "B.png", "settings", visual_fingerprint=_fp())
    element_type = visual_engine_module.VisualElement
    a = element_type(**_el(0, "More options", shared_uid, "r1", True))
    b = element_type(**_el(0, "More options", shared_uid, "r1", False))
    a.exploration_status = "covered"
    a.covered_by = "9"
    a.covered_by_state = "source"
    a.exploration_reason = "Explorer mapped a verified shared result."
    sync_live_to_graph(
        graph, {"A": {"elements": [a]}, "B": {"elements": [b]}},
        {shared_uid})
    assert graph.graph.nodes["A"]["elements"][0]["visited"] is True
    assert graph.graph.nodes["A"]["elements"][0]["covered_by"] == "9"
    assert graph.graph.nodes["A"]["elements"][0]["covered_by_state"] == "source"
    assert graph.graph.nodes["A"]["elements"][0]["exploration_reason"].startswith(
        "Explorer mapped")
    assert graph.graph.nodes["B"]["elements"][0]["visited"] is False


def test_graph_sync_projects_the_complete_live_state_observation():
    graph = StateGraph("settings")
    graph.add_state(
        "A", [_el(0, "Old", "old", "r1", False)],
        "A.png", "settings", visual_fingerprint=_fp(),
        page_name="Old", page_id="page-old", variant_id="variant-old",
    )
    element_type = visual_engine_module.VisualElement
    live = element_type(**_el(0, "Current", "current", "r2", False))
    state_data = {"A": {
        "elements": [live],
        "page_name": "Current",
        "page_id": "page-current",
        "variant_id": "variant-current",
        "observed_facts": {"selected": ["Current"]},
        "visible_capabilities": [],
        "semantic_blocks": [{
            "region_id": "r2",
            "observation_status": "complete",
            "scrollable": False,
        }],
        "region_observation": {
            "r2": {"status": "complete", "attempts": 1, "reason": ""},
        },
        "perception_mode": "region_lazy",
        "node_local_functions": [],
    }}

    sync_live_to_graph(graph, state_data, set())

    node = graph.graph.nodes["A"]
    assert node["elements"] == [live.to_dict()]
    assert node["page_id"] == "page-current"
    assert node["variant_id"] == "variant-current"
    assert node["region_observation"]["r2"]["status"] == "complete"
    assert graph.pages["page-current"]["variants"][
        "variant-current"]["state_ids"] == ["A"]


def test_consistency_checker_reports_region_scroll_and_action_drift():
    graph = StateGraph("settings")
    graph.add_state(
        "A", [], "A.png", "settings", visual_fingerprint=_fp(),
        page_id="page", variant_id="variant",
        semantic_blocks=[{
            "region_id": "r1",
            "observation_status": "complete",
            "scrollable": False,
        }],
        perception_mode="region_lazy",
    )
    graph.graph.nodes["A"]["region_observation"] = {
        "r1": {"status": "complete", "attempts": 1, "reason": ""},
    }
    graph.scroll_ledger["state:A:page"] = {
        "scope_id": "state:A:page",
        "state_ids": ["A"],
        "region_id": "r1",
        "classification": "static",
        "termination": "static",
        "top_restored": True,
        "complete": True,
    }
    graph.action_edges.append({
        "action_edge_id": "bad-edge",
        "source": "missing",
        "target": "",
        "source_page_id": "",
        "source_variant_id": "",
        "attempts": [],
    })
    state_data = {"A": {
        "elements": [],
        "page_id": "page",
        "variant_id": "variant",
        "semantic_blocks": [{
            "region_id": "r1",
            "observation_status": "pending",
            "scrollable": False,
        }],
        "region_observation": {
            "r1": {"status": "complete", "attempts": 1, "reason": ""},
        },
        "perception_mode": "region_lazy",
    }}

    issues = runtime_state_consistency_issues(graph, state_data)

    assert any("different block and observation statuses" in issue
               for issue in issues)
    assert any("non-canonical scroll scope" in issue for issue in issues)
    assert any("missing source" in issue for issue in issues)


def test_graph_save_refuses_to_persist_after_live_sync_failure(tmp_path):
    graph = StateGraph("settings")
    graph.add_state("A", [], "A.png", "settings", visual_fingerprint=_fp())
    path = tmp_path / "graph.json"
    graph.save(str(path))
    original = path.read_bytes()
    graph.stop_reason = "new-runtime-state"
    graph._live_sync = lambda _graph: (_ for _ in ()).throw(
        RuntimeError("state copies disagree"))

    with pytest.raises(RuntimeError, match="state copies disagree"):
        graph.save(str(path))

    assert path.read_bytes() == original


def test_resume_bad_graph_returns_false():
    with tempfile.TemporaryDirectory() as tmp:
        eng = _build_engine(tmp)
        before = _runtime_refs(eng)
        assert eng.resume_from_graph(None) is False, \
            "None graph must fail-safe to False without mutating the engine"
        _assert_runtime_refs_unchanged(eng, before)
        assert eng._action_count == 0
        assert not eng._state_data and not eng._visited_uids
        print("PASS: None graph fails safe without changing runtime identities")


def test_resume_mid_build_failure_is_atomic():
    with tempfile.TemporaryDirectory() as tmp:
        eng = _build_engine(tmp)
        before = _runtime_refs(eng)
        bad_graph, sentinel = _make_mid_build_bad_graph(tmp)

        assert eng.resume_from_graph(bad_graph) is False, \
            "a malformed later node must reject the entire resume"
        _assert_runtime_refs_unchanged(eng, before)
        assert bad_graph._live_sync is sentinel, \
            "failed rebuild must not install a save hook on the input graph"
        assert "A" not in eng._state_data
        assert "A" not in eng.registry._buttons
        assert "r1" not in eng.region_registry._regions
        assert "uidA_net" not in eng._visited_uids
        assert not eng.mem.is_explored_in_state("A", "Network")
        assert list(eng._bfs_queue) == [] and eng._action_count == 0
        print("PASS: mid-build failure leaves engine and input graph untouched")


def test_resume_uses_persisted_variant_facts_after_richer_revisit():
    """Strict schema-v3 resume must hash the durable observed facts, not a
    lossy final element snapshot that omits aliases accumulated on revisits."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = StateGraph("settings")
        elements = [
            _el(0, "Applications", "uid_apps", "r1", True),
            _el(1, "Accerciser", "uid_acc", "r2", False, role="content"),
        ]
        page_name = "Application Settings"
        page_id = compute_page_id(
            page_name,
            semantic_key=semantic_page_key(page_name, elements),
            namespace="settings",
        )
        richer_elements = elements + [
            _el(2, "Notifications", "uid_notifications", "r2", False,
                role="content"),
            _el(3, "System features used by this application.", "uid_features",
                "r2", False, role="content"),
        ]
        persisted_facts = observed_variant_facts(richer_elements)
        variant_id = compute_variant_id(page_id, persisted_facts)
        graph.add_state(
            "A", elements, os.path.join(tmp, "A.png"), "settings",
            action_path_from_root=[], state_type="visual",
            visual_fingerprint=_fp(), page_name=page_name,
            page_id=page_id, variant_id=variant_id,
            page_identity_version="semantic_page_variant_v1",
            observed_facts=persisted_facts,
            variant_signature=variant_signature(persisted_facts),
        )

        eng = _build_engine(tmp)
        assert eng.resume_from_graph(graph), \
            "resume must accept a valid persisted variant richer than elements"
        assert eng.registry.variant_id_of("A") == variant_id
        assert eng.registry.variant_facts_of("A") == persisted_facts
        assert eng._state_data["A"]["variant_id"] == variant_id
        print("PASS: resume hydrates strict variant identity from persisted facts")


def test_resume_reopens_unresolved_stateful_probe_for_restore():
    with tempfile.TemporaryDirectory() as tmp:
        graph = StateGraph("settings")
        original = _el(0, "Original", "uid_original", "r1", False)
        original.update({
            "el_type": "target",
            "category": "shallow",
            "selected": True,
            "group": "mode",
            "stateful": True,
            "state_key": "mode",
            "state_value": "on",
            "effect_scope": "function_set",
            "reversible": True,
            "risk": "none",
        })
        alternative = _el(1, "Alternative", "uid_alternative", "r1", False)
        alternative.update({
            "el_type": "target",
            "category": "shallow",
            "selected": False,
            "group": "mode",
            "stateful": True,
            "state_key": "mode",
            "state_value": "off",
            "effect_scope": "function_set",
            "reversible": True,
            "risk": "none",
        })
        graph.add_state(
            "permission", [original, alternative],
            os.path.join(tmp, "permission.png"), "settings",
            action_path_from_root=[], state_type="visual",
            visual_fingerprint=_fp(),
        )
        graph.record_action_event(
            source="permission",
            target="permission",
            action={"action_type": "CLICK"},
            element_id="1",
            element_label="Alternative",
            semantic_description="Set mode on",
            outcome="uncertain",
            detail="pixels changed but structured state did not",
            landing_verified=False,
            committed=False,
            evidence={
                "mutation_id": "m-unresolved",
                "purpose": "probe",
                "stateful": True,
                "state_key": "mode",
                "before_value": "off",
                "after_value": "off",
                "reversible": True,
                "risk": "none",
                "probe_candidate_key": "alternative||target|mode",
                "restore_candidate_key": "original||target|mode",
                "baseline_candidates": [
                    "original||target|mode",
                    "alternative||target|mode",
                ],
                "fresh_post_action_observation": True,
                "post_action_phash_distance": 2,
            },
        )

        engine = _build_engine(tmp)
        assert engine.resume_from_graph(graph)
        assert engine._active_state_mutation == {
            "mutation_id": "m-unresolved",
            "source_state": "permission",
            "mutated_state": "permission",
            "state_key": "mode",
            "before_value": "off",
            "after_value": "unknown",
            "restore_before_value": "",
            "baseline_frame_phash": "",
            "probe_candidate_key": "alternative||target|mode",
            "restore_candidate_key": "original||target|mode",
            "baseline_candidates": [
                "original||target|mode",
                "alternative||target|mode",
            ],
            "explore_local_functions": False,
        }
        assert (
            "permission", "mode", "off"
        ) in engine._stateful_probe_sources

        graph.add_state(
            "confirmation", [],
            os.path.join(tmp, "confirmation.png"), "settings",
            action_path_from_root=[], state_type="visual",
            visual_fingerprint=_fp(),
        )
        graph.record_action_event(
            source="confirmation",
            target="permission",
            action={"action_type": "CLICK"},
            element_id="0",
            element_label="Cancel",
            semantic_description="Cancel and verify original selection",
            outcome="transitioned_consistent",
            detail="fresh baseline verified",
            landing_verified=True,
            committed=True,
            evidence={
                "mutation_id": "m-unresolved",
                "purpose": "restore",
                "stateful": True,
                "state_key": "mode",
                "before_value": "unknown",
                "after_value": "on",
                "restore_before_value": "on",
                "restoration_kind": "verified_baseline_return",
                "fresh_post_action_observation": True,
            },
        )
        restored = _build_engine(tmp)
        assert restored.resume_from_graph(graph)
        assert restored._active_state_mutation is None


def test_explicit_resume_load_failure_never_starts_fresh():
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = os.path.join(tmp, "graph.json")
        original_bytes = b"{ definitely not valid graph json"
        with open(graph_path, "wb") as stream:
            stream.write(original_bytes)
        ran = {"value": False}

        class _Engine:
            def __init__(self, **_kwargs):
                pass

            def run(self, _initial_obs):
                ran["value"] = True
                raise AssertionError("fresh traversal must not start")

        original_engine = visual_engine_module.VisualTraversalEngine
        visual_engine_module.VisualTraversalEngine = _Engine
        try:
            try:
                visual_engine_module.run(
                    env=_Stub(), agent=_Stub(), perception=_Stub(),
                    app_name="settings", output_root=tmp, initial_obs={},
                    resume_path=graph_path,
                )
            except Exception:
                pass
            else:
                raise AssertionError("invalid explicit resume must raise")
        finally:
            visual_engine_module.VisualTraversalEngine = original_engine

        assert ran["value"] is False
        with open(graph_path, "rb") as stream:
            assert stream.read() == original_bytes
        print("PASS: invalid explicit resume is fail-closed and preserves graph.json")


def test_load_repairs_capability_membership_from_grounded_source_variants():
    with tempfile.TemporaryDirectory() as tmp:
        graph = StateGraph("clock")
        graph.add_state(
            state_id="empty", elements=[{
                "id": "add", "name": "Add Alarm",
                "interactive": True, "region_id": "alarm-actions",
            }],
            screenshot_path="", app_name="clock",
            page_name="Alarms", page_id="alarms",
            variant_id="variant-empty",
            observed_facts={"alarm_count": 0},
            visible_capabilities=["cap-add"],
        )
        graph.add_state(
            state_id="populated", elements=[{
                "id": "add", "name": "Add Alarm",
                "interactive": True, "region_id": "alarm-actions",
            }],
            screenshot_path="", app_name="clock",
            page_name="Alarms", page_id="alarms",
            variant_id="variant-populated",
            observed_facts={"alarm_count": 1},
            visible_capabilities=["cap-add"],
        )
        graph.capabilities["cap-add"] = {
            "capability_id": "cap-add",
            "page_id": "alarms",
            "availability_status": "discovered",
            "requires": [],
            "entry_variants": ["stale-variant"],
            "evidence_variants": ["stale-variant"],
            "available_when": {
                "variant_ids": ["stale-variant"],
                "facts_by_variant": {"stale-variant": {}},
            },
            "source_elements": [
                {
                    "state_id": "empty", "variant_id": "stale-variant",
                    "element_id": "add", "element_label": "Add Alarm",
                },
                {
                    "state_id": "populated", "variant_id": "stale-variant",
                    "element_id": "add", "element_label": "Add Alarm",
                },
            ],
        }
        path = os.path.join(tmp, "graph.json")
        graph.save(path)

        loaded = StateGraph.load(path)
        capability = loaded.capabilities["cap-add"]

        assert capability["entry_variants"] == [
            "variant-empty", "variant-populated"]
        assert capability["evidence_variants"] == [
            "variant-empty", "variant-populated"]
        assert capability["available_when"]["variant_ids"] == [
            "variant-empty", "variant-populated"]
        assert {
            ref["state_id"]: ref["variant_id"]
            for ref in capability["source_elements"]
        } == {
            "empty": "variant-empty",
            "populated": "variant-populated",
        }


if __name__ == "__main__":
    test_resume_rebuilds_ledgers_and_dedups()
    test_graph_sync_never_propagates_appearance_uid_between_sources()
    test_resume_bad_graph_returns_false()
    test_resume_mid_build_failure_is_atomic()
    test_resume_uses_persisted_variant_facts_after_richer_revisit()
    test_resume_reopens_unresolved_stateful_probe_for_restore()
    test_explicit_resume_load_failure_never_starts_fresh()
    test_load_repairs_capability_membership_from_grounded_source_variants()
    print("ALL PASS")
