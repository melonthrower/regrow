from types import SimpleNamespace

from gui_rewalk.src.core.visual_traversal.runtime.scheduling import (
    available_unvisited_candidates,
    schedule_frontier,
)
from gui_rewalk.src.core.visual_traversal.visual_engine import (
    VisualTraversalEngine,
)
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement


def test_frontier_route_refresh_pins_router_confirmed_old_state():
    calls = []
    target = "known-target"

    class Graph:
        stop_reason = ""
        graph = SimpleNamespace(number_of_nodes=lambda: 2)

        @staticmethod
        def save(_path):
            pass

    host = SimpleNamespace(
        _nearest_unexplored_node=lambda _current: target,
        _active_state_mutation=None,
        _moves_without_new=0,
        MAX_MOVES_WITHOUT_NEW=20,
        app_name="fixture",
        graph=Graph(),
        graph_save_path="unused.json",
        _unvisited_candidates=lambda _state: [],
        _state_data={
            target: {"path": [{"known": True}], "replay_hints": [None]},
        },
        router=SimpleNamespace(route_to=lambda *_args: SimpleNamespace(
            arrived=True,
            observation={"screenshot": b"live-known-target"},
            status="arrived",
            failure_kind="",
            landed_id=target,
        )),
        _ensure_on_app=lambda observation: (observation, False, True),
        _route_blocked_targets=set(),
        _route_failures={},
        _backtrack_fail_count=0,
        review_debug=SimpleNamespace(record_event=lambda *_args, **_kwargs: None),
    )

    def register(observation, path, hints):
        preferred = getattr(host, "_registration_preferred_state_once", "")
        calls.append((preferred, observation, path, hints))
        return (preferred or "duplicate-node", False)

    host._register = register
    result = schedule_frontier(
        host,
        "source",
        {"screenshot": b"source"},
        [],
        [],
        0,
    )

    assert result.stop is False
    assert result.state_id == target
    assert result.path == [{"known": True}]
    assert calls == [(
        target,
        {"screenshot": b"live-known-target"},
        [{"known": True}],
        [None],
    )]


def test_stateful_route_adopts_live_variant_with_exact_inverse():
    old_target = "old-disabled"
    live_target = "live-disabled"
    inverse = VisualElement(
        1, "Show notifications", [0, 0, 20, 20], [10, 10],
        el_type="target", category="shallow", interactive=True,
        stateful=True, state_key="show notifications", state_value="off",
        effect_scope="data_only", reversible=True, risk="none",
    )
    restore_key = VisualTraversalEngine._stateful_candidate_key(inverse)
    events = []

    class Graph:
        stop_reason = ""
        graph = SimpleNamespace(number_of_nodes=lambda: 3)

        @staticmethod
        def save(_path):
            pass

    host = SimpleNamespace(
        _nearest_unexplored_node=lambda _current: (_ for _ in ()).throw(
            AssertionError(
                "an open mutation must route to its host without ordinary "
                "frontier evidence")),
        _active_state_mutation={
            "mutation_id": "m1",
            "source_state": "enabled",
            "mutated_state": old_target,
            "state_key": "show_notifications",
            "before_value": "on",
            "after_value": "unknown",
            "restore_candidate_key": restore_key,
        },
        _moves_without_new=0,
        MAX_MOVES_WITHOUT_NEW=20,
        app_name="fixture",
        graph=Graph(),
        graph_save_path="unused.json",
        _unvisited_candidates=lambda _state: [inverse],
        _state_data={
            old_target: {"path": [{"old": True}], "replay_hints": []},
            live_target: {
                "path": [{"live": True}],
                "replay_hints": [None],
                "elements": [inverse],
            },
        },
        router=SimpleNamespace(route_to=lambda *_args: SimpleNamespace(
            arrived=False,
            observation={"screenshot": b"live-disabled"},
            status="retryable",
            failure_kind="prediction_mismatch",
            landed_id=live_target,
            attempts_used=1,
        )),
        _route_blocked_targets=set(),
        _route_failures={},
        _route_target_failure_counts={},
        _backtrack_fail_count=0,
        review_debug=SimpleNamespace(
            record_event=lambda event, **payload:
            events.append((event, payload))),
        _stateful_candidate_key=VisualTraversalEngine._stateful_candidate_key,
    )
    host._is_active_restore_candidate = (
        lambda active, element:
        VisualTraversalEngine._is_active_restore_candidate(
            host, active, element))

    result = schedule_frontier(
        host, "enabled", {"screenshot": b"enabled"}, [], [], 0)

    assert result.stop is False
    assert result.state_id == live_target
    assert result.path == [{"live": True}]
    assert host._active_state_mutation["mutated_state"] == live_target
    assert host._active_state_mutation["inverse_element"] is inverse
    assert events[-1][0] == "stateful_restore_landing_adopted"


def test_stateful_restore_routes_through_original_source_before_shared_surface():
    source = "transaction-source"
    shared_surface = "shared-dialog"
    routed_targets = []

    class Graph:
        stop_reason = ""
        graph = SimpleNamespace(number_of_nodes=lambda: 3)

        @staticmethod
        def save(_path):
            pass

    state_data = {
        source: {"path": [{"to": "source"}], "replay_hints": []},
        shared_surface: {
            "path": [{"to": "shared"}],
            "replay_hints": [],
        },
    }
    host = SimpleNamespace(
        _nearest_unexplored_node=lambda _current: (_ for _ in ()).throw(
            AssertionError(
                "an open mutation must not use the ordinary frontier")),
        _active_state_mutation={
            "mutation_id": "m-shared",
            "source_state": source,
            "mutated_state": shared_surface,
            "state_key": "setting",
            "before_value": "on",
            "after_value": "unknown",
        },
        _moves_without_new=0,
        MAX_MOVES_WITHOUT_NEW=20,
        app_name="fixture",
        graph=Graph(),
        graph_save_path="unused.json",
        _unvisited_candidates=lambda _state: [],
        _state_data=state_data,
        _route_blocked_targets=set(),
        _route_failures={},
        _route_target_failure_counts={},
        _backtrack_fail_count=0,
        _ensure_on_app=lambda observation: (observation, False, True),
        review_debug=SimpleNamespace(
            record_event=lambda *_args, **_kwargs: None),
    )

    def route_to(_observation, _current, target):
        routed_targets.append(target)
        return SimpleNamespace(
            arrived=True,
            observation={"screenshot": target.encode()},
            status="arrived",
            failure_kind="",
            landed_id=target,
        )

    def register(observation, path, hints):
        del observation, path, hints
        return host._registration_preferred_state_once, False

    host.router = SimpleNamespace(route_to=route_to)
    host._register = register

    first = schedule_frontier(
        host, "root", {"screenshot": b"root"}, [], [], 0)
    second = schedule_frontier(
        host, first.state_id, first.observation,
        first.path, first.replay_hints, 0)

    assert routed_targets == [source, shared_surface]
    assert first.state_id == source
    assert second.state_id == shared_surface
    assert host._active_state_mutation["mutated_state"] == shared_surface


def test_stateful_restore_closes_from_fresh_source_before_reopening_surface():
    source = "transaction-source"
    shared_surface = "shared-dialog"
    ordinary_target = "ordinary-target"
    baseline = VisualElement(
        1, "Original option", [0, 0, 20, 20], [10, 10],
        el_type="target", category="shallow", interactive=True,
        stateful=True, state_key="mode", state_value="on",
        effect_scope="function_set", reversible=True, risk="none",
        group="mode_choices",
    )
    restore_key = VisualTraversalEngine._stateful_candidate_key(baseline)
    routed_targets = []

    class Graph:
        stop_reason = ""
        graph = SimpleNamespace(number_of_nodes=lambda: 3)

        @staticmethod
        def save(_path):
            pass

    host = SimpleNamespace(
        _nearest_unexplored_node=lambda _current: ordinary_target,
        _active_state_mutation={
            "mutation_id": "m-cancelled",
            "source_state": source,
            "mutated_state": shared_surface,
            "state_key": "mode",
            "before_value": "off",
            "after_value": "unknown",
            "restore_candidate_key": restore_key,
            "restore_before_value": "",
        },
        _stateful_inflight=None,
        _last_live_observation_state_id=source,
        _last_live_observation_elements=[baseline],
        _moves_without_new=0,
        MAX_MOVES_WITHOUT_NEW=20,
        app_name="fixture",
        graph=Graph(),
        graph_save_path="unused.json",
        _unvisited_candidates=lambda _state: [],
        _state_data={
            source: {"elements": [baseline], "path": [], "replay_hints": []},
            shared_surface: {"path": [], "replay_hints": []},
            ordinary_target: {
                "path": [{"to": "ordinary"}],
                "replay_hints": [],
            },
        },
        _route_blocked_targets=set(),
        _route_failures={},
        _route_target_failure_counts={},
        _backtrack_fail_count=0,
        _ensure_on_app=lambda observation: (observation, False, True),
        review_debug=SimpleNamespace(
            record_event=lambda *_args, **_kwargs: None),
        _stateful_candidate_key=VisualTraversalEngine._stateful_candidate_key,
    )

    def route_to(_observation, _current, target):
        routed_targets.append(target)
        return SimpleNamespace(
            arrived=True,
            observation={"screenshot": target.encode()},
            status="arrived",
            failure_kind="",
            landed_id=target,
        )

    def register(observation, path, hints):
        del observation, path, hints
        return host._registration_preferred_state_once, False

    host.router = SimpleNamespace(route_to=route_to)
    host._register = register

    result = schedule_frontier(
        host, source, {"screenshot": b"source"}, [], [], 0)

    assert result.stop is False
    assert result.state_id == ordinary_target
    assert routed_targets == [ordinary_target]
    assert host._active_state_mutation is None


def test_stateful_restore_withholds_source_frontier_until_mutation_closes():
    ordinary = VisualElement(
        1, "Ordinary source action", [0, 0, 20, 20], [10, 10])
    host = SimpleNamespace(
        _active_state_mutation={
            "source_state": "source",
            "mutated_state": "shared-dialog",
            "after_value": "unknown",
        },
        _last_live_observation_state_id="",
        _explorer_deferred_regions=set(),
        _unvisited_candidates=lambda _state: [ordinary],
        router=None,
    )

    assert available_unvisited_candidates(host, "source") == []


def test_stateful_resume_adopts_current_live_inverse_over_stale_ledger():
    target = "notification-settings"
    durable_baseline = VisualElement(
        1, "Show notifications", [0, 0, 20, 20], [10, 10],
        el_type="target", category="shallow", interactive=True,
        stateful=True, state_key="show notifications", state_value="off",
        effect_scope="function_set", reversible=True, risk="none",
    )
    live_inverse = VisualElement(
        1, "Show notifications", [0, 0, 20, 20], [10, 10],
        el_type="target", category="shallow", interactive=True,
        stateful=True, state_key="show notifications", state_value="on",
        effect_scope="function_set", reversible=True, risk="none",
        region="notification_controls",
    )
    restore_key = VisualTraversalEngine._stateful_candidate_key(
        durable_baseline)

    class Graph:
        stop_reason = ""
        graph = SimpleNamespace(number_of_nodes=lambda: 1)

        @staticmethod
        def save(_path):
            pass

    host = SimpleNamespace(
        _nearest_unexplored_node=lambda _current: None,
        _active_state_mutation={
            "mutation_id": "m-live-resume",
            "source_state": target,
            "mutated_state": target,
            "state_key": "show_notifications",
            "before_value": "off",
            "after_value": "on",
            "probe_candidate_key": restore_key,
            "restore_candidate_key": restore_key,
        },
        _last_live_observation_state_id=target,
        _last_live_observation_elements=[live_inverse],
        _moves_without_new=0,
        MAX_MOVES_WITHOUT_NEW=20,
        app_name="fixture",
        graph=Graph(),
        graph_save_path="unused.json",
        _state_data={
            target: {
                "path": [],
                "replay_hints": [],
                "elements": [durable_baseline],
            },
        },
        _route_blocked_targets=set(),
        review_debug=SimpleNamespace(
            record_event=lambda *_args, **_kwargs: None),
        _stateful_candidate_key=VisualTraversalEngine._stateful_candidate_key,
    )
    host._is_active_restore_candidate = (
        lambda active, element:
        VisualTraversalEngine._is_active_restore_candidate(
            host, active, element))

    result = schedule_frontier(
        host, target, {"screenshot": b"live"}, [], [], 0)

    assert result.stop is False
    assert result.state_id == target
    assert host._active_state_mutation["inverse_element"] is live_inverse
