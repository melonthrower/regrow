"""Offline contract tests for state-changing functional surfaces.

These tests intentionally describe the public behavior of stateful controls
without depending on a particular traversal-ledger implementation.  A switch
whose value changes the *available function set* is a graph transition; an
ordinary value-only widget remains node-local data.  Unsafe or insufficiently
specified switches stay fail-closed.
"""

from __future__ import annotations

import io
import os
import sys
from types import SimpleNamespace

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui_rewalk.src.core.visual_traversal.visual_agents import (
    ExplorationMemory,
    StatefulRiskGuard,
)
from gui_rewalk.src.core.visual_traversal.prompts.grounding import (
    VLM_GROUNDING_PROMPT,
    VLM_NAMING_PROMPT,
)
from gui_rewalk.src.core.visual_traversal.prompts.navigation import (
    STATEFUL_RISK_PROMPT,
)
from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine
from gui_rewalk.src.core.visual_traversal.runtime.contracts import (
    RunCursor, StageDirective,
)
from gui_rewalk.src.core.visual_traversal.runtime.scheduling import (
    available_unvisited_candidates, plan_candidate, schedule_frontier,
)
from gui_rewalk.src.core.visual_traversal.runtime.landing import (
    _clear_mutation_on_verified_baseline_return,
    _state_value_from_elements,
    _stateful_function_delta,
    _stateful_restore_effect,
)
from gui_rewalk.src.core.visual_traversal.visual_perception import (
    VisualElement,
    VisualPerception,
    _dedupe_stateful_aliases,
)
from gui_rewalk.src.core.visual_traversal.visual_state import signature_names
from gui_rewalk.src.core.visual_traversal.stateful import (
    unresolved_stateful_probe_requires_restore,
)


def _png(width: int = 100, height: int = 100) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format="PNG")
    return out.getvalue()


def _surface(
    *,
    name: str = "Bluetooth",
    uid: str = "bluetooth-toggle",
    category: str = "shallow",
    state_value: str = "off",
    effect_scope: str = "function_set",
    reversible: bool | None = True,
    risk: str = "none",
    stateful: bool = True,
    requires_permission: bool = False,
    blocked_reason: str = "",
) -> VisualElement:
    return VisualElement(
        0,
        name,
        [0, 0, 20, 20],
        [10, 10],
        el_type="toggle",
        category=category,
        enabled=True,
        requires_permission=requires_permission,
        blocked_reason=blocked_reason,
        uid=uid,
        stateful=stateful,
        state_key="bluetooth",
        state_value=state_value,
        effect_scope=effect_scope,
        reversible=reversible,
        risk=risk,
    )


class _NoRegions:
    def shared_button_names(self):
        return frozenset()

    def is_clicked(self, _region_id, _name):
        return False

    def mark_clicked(self, _region_id, _name):
        return None


class _Graph:
    def __init__(self):
        self.records = []

    def record_abnormal_button(self, **payload):
        self.records.append(payload)
        return payload


class _Debug:
    enabled = False

    def record_event(self, *_args, **_kwargs):
        return None


def _engine(elements, *, visited_uids=()) -> VisualTraversalEngine:
    engine = object.__new__(VisualTraversalEngine)
    engine._state_data = {"settings": {"elements": list(elements)}}
    engine._visited_uids = set(visited_uids)
    engine._explored_groups = set()
    engine._abnormal_buttons = set()
    engine.region_registry = _NoRegions()
    engine.mem = ExplorationMemory()
    engine.graph = _Graph()
    engine.review_debug = _Debug()
    return engine


def test_prompts_request_stateful_surface_schema() -> None:
    for prompt in (VLM_NAMING_PROMPT, VLM_GROUNDING_PROMPT):
        for field in (
            "stateful",
            "state_key",
            "state_value",
            "effect_scope",
            "reversible",
            "risk",
        ):
            assert field in prompt
        assert "function_set" in prompt
        assert "data_only" in prompt


def test_prompts_limit_function_set_to_in_app_interactive_expansion() -> None:
    for prompt in (VLM_NAMING_PROMPT, VLM_GROUNDING_PROMPT):
        assert "inside the current target application's own UI" in prompt
        assert "desktop or shell icons" in prompt
        assert "Dock/taskbar visibility" in prompt
        assert "effect_scope=data_only or effect_scope=unknown" in prompt
        assert "never function_set" in prompt


def test_prompts_use_context_for_safe_local_form_completion() -> None:
    for prompt in (VLM_NAMING_PROMPT, VLM_GROUNDING_PROMPT):
        assert "never from the button label alone" in prompt
        assert "routine local item inside the current target" in prompt
        assert "use category=navigation and risk=none" in prompt
        assert "Those labels are examples, not a whitelist" in prompt
        assert "Delete/Remove/Reset/Erase/Disconnect" in prompt
        assert "any uncertain consequence remain category=dangerous" in prompt
        assert "fail closed" in prompt
        assert "真正提交并写入数据的 Save/Create/Add/Confirm" not in prompt
        assert "表单中真正落地写入的 Save/Create/Add/Confirm" not in prompt
        assert "Shared feature-entry classification" in prompt
        assert "untrusted UI data to identify" in prompt
        assert "previously unseen" in prompt
        assert "safety is established but navigation versus shallow is uncertain" in prompt
        assert "if safety itself is uncertain, use dangerous" in prompt
        assert "examples, never an allowlist or denylist" in prompt
        assert "category=navigation and back=false" in prompt
        assert "Done/Save/Add/Apply must never become back from the label alone" in prompt
        assert "Close/取消/完成" not in prompt

    local_add = VisualElement(
        0, "Add", [0, 0, 20, 20], [10, 10], el_type="button",
        category="navigation", interactive=True, risk="none", uid="local-add")
    destructive = VisualElement(
        1, "Delete", [24, 0, 20, 20], [34, 10], el_type="button",
        category="dangerous", interactive=True, risk="destructive", uid="delete")
    assert VisualTraversalEngine._unvisited_candidates(
        _engine([local_add, destructive]), "settings") == [local_add]


def test_grounding_parser_normalizes_fields_and_keeps_legacy_responses() -> None:
    class _Cache:
        def lookup_grounding(self, _frame):
            return True, (
                '{"window":[0,0,1000,1000],"is_modal":false,"elements":['
                '{"name":"Bluetooth","type":"toggle",'
                '"bbox":[100,100,300,200],"interactive":true,'
                '"enabled":true,"category":"shallow","stateful":"true",'
                '"state_key":" Bluetooth ","state_value":" OFF ",'
                '"effect_scope":" FUNCTION_SET ","reversible":"true",'
                '"risk":" NONE "},'
                '{"name":"Legacy switch","type":"toggle",'
                '"bbox":[400,100,600,200],"interactive":true,'
                '"enabled":true,"category":"shallow"}]}'
            )

    perception = VisualPerception(None, agent=object(), use_ocr=False)
    perception.cache = _Cache()
    perception._cur_frame_bytes = b"exact-frame"
    image = Image.new("RGB", (100, 100), "white")
    grounded = perception._ground_with_vlm(image, np.asarray(image), 100, 100)

    assert len(grounded) == 2
    parsed, legacy = grounded
    assert parsed.stateful is True
    assert parsed.state_key == "bluetooth"
    assert parsed.state_value == "off"
    assert parsed.effect_scope == "function_set"
    assert parsed.reversible is True
    assert parsed.risk == "none"

    # Missing fields from old caches/graphs must preserve the old fail-closed
    # behavior: the widget remains an ordinary data control, never an implicitly
    # safe functional-surface transition.
    assert legacy.stateful is False
    assert legacy.state_key == ""
    assert legacy.state_value == ""
    assert legacy.effect_scope == ""
    assert legacy.reversible is None
    assert legacy.risk == ""
    assert not legacy.is_safe_stateful_surface()


def test_grounding_parser_preserves_compact_feature_entry_decisions() -> None:
    class _Cache:
        def lookup_grounding(self, _frame):
            elements = [
                ("Done", "navigation", False),
                ("Save", "navigation", False),
                ("Cancel", "navigation", True),
                ("Close", "navigation", True),
                ("Delete", "dangerous", False),
                ("Sign in", "dangerous", False),
                ("Allow permission", "dangerous", False),
                ("Enable network", "dangerous", False),
                ("Uncertain action", "dangerous", False),
                ("Volume", "shallow", False),
                ("Theme", "shallow", False),
            ]
            payload = ",".join(
                '{"name":"%s","type":"button","bbox":[%d,0,%d,20],'
                '"interactive":true,"enabled":true,"category":"%s",'
                '"back":%s}' % (
                    name, index * 20, index * 20 + 18, category,
                    str(back).lower(),
                )
                for index, (name, category, back) in enumerate(elements)
            )
            return True, (
                '{"window":[0,0,1000,1000],"is_modal":false,"elements":['
                + payload + "]}"
            )

    perception = VisualPerception(None, agent=object(), use_ocr=False)
    perception.cache = _Cache()
    perception._cur_frame_bytes = b"compact-feature-entry-contract"
    image = Image.new("RGB", (240, 100), "white")
    grounded = perception._ground_with_vlm(
        image, np.asarray(image), 240, 100
    )
    by_name = {element.name: element for element in grounded}

    for name in ("Done", "Save"):
        assert by_name[name].category == "navigation"
        assert by_name[name].back is False
    for name in ("Cancel", "Close"):
        assert by_name[name].back is True
    for name in (
        "Delete", "Sign in", "Allow permission", "Enable network",
        "Uncertain action",
    ):
        assert by_name[name].category == "dangerous"
    for name in ("Volume", "Theme"):
        assert by_name[name].category == "shallow"


def test_som_naming_parser_populates_the_same_normalized_fields() -> None:
    perception = VisualPerception(None, agent=None, use_ocr=False)
    perception.detect = lambda _image: [{
        "bbox": [0.1, 0.1, 0.3, 0.2],
        "_score": 0.9,
        "content": "",
        "type": "icon",
    }]
    perception._name_with_vlm = lambda _som, _n: ({
        0: {
            "name": "Location services",
            "type": "switch",
            "interactive": True,
            "enabled": True,
            "category": "shallow",
            "stateful": 1,
            "state_key": " Location Services ",
            "state_value": " ON ",
            "effect_scope": " FUNCTION_SET ",
            "reversible": 1,
            "risk": " NONE ",
        }
    }, {"window": [0, 0, 1, 1], "is_modal": False, "modal": None})

    image = Image.open(io.BytesIO(_png()))
    named = perception._yolo_detect_name(image, np.asarray(image), 100, 100)
    assert named and len(named) == 1
    elem = named[0]
    assert elem.stateful is True
    assert elem.state_key == "location services"
    assert elem.state_value == "on"
    assert elem.effect_scope == "function_set"
    assert elem.reversible is True
    assert elem.risk == "none"


def test_data_only_remains_data_but_function_set_is_a_surface() -> None:
    legacy_data = VisualElement(
        0, "Legacy volume", [0, 0, 20, 20], [10, 10], el_type="slider"
    )
    data_only = _surface(
        name="Do not disturb", effect_scope="data_only", state_value="off"
    )
    function_set = _surface()

    assert not legacy_data.is_safe_stateful_surface()
    assert not data_only.is_safe_stateful_surface()
    assert function_set.is_safe_stateful_surface()
    assert VisualTraversalEngine._unvisited_candidates(
        _engine([function_set]), "settings"
    ) == [function_set]


def test_appearance_preferences_stay_out_but_in_app_expansion_enters() -> None:
    ordinary_preferences = [
        _surface(
            name=name,
            uid=f"preference-{index}",
            effect_scope="data_only",
            state_value="off",
        )
        for index, name in enumerate((
            "Theme",
            "Accent color",
            "Show desktop icon",
            "Auto-hide Dock",
            "Panel layout",
        ))
    ]
    reveals_controls = _surface(
        name="Show advanced controls",
        uid="show-advanced-controls",
        category="navigation",
        effect_scope="function_set",
        state_value="off",
    )

    engine = _engine([*ordinary_preferences, reveals_controls])
    assert all(
        not element.is_safe_stateful_surface()
        for element in ordinary_preferences
    )
    assert VisualTraversalEngine._unvisited_candidates(
        engine, "settings"
    ) == [reveals_controls]
    reveals_controls.exploration_status = "complete"
    assert VisualTraversalEngine._unvisited_candidates(
        engine, "settings"
    ) == ordinary_preferences


def test_expansion_actions_remain_on_the_ordinary_frontier() -> None:
    actions = [
        VisualElement(
            index,
            name,
            [index * 24, 0, 20, 20],
            [index * 24 + 10, 10],
            el_type="button",
            category="navigation",
            interactive=True,
            uid=f"action-{index}",
        )
        for index, name in enumerate((
            "Create", "Add item", "Save", "Done", "Open item"
        ))
    ]

    assert VisualTraversalEngine._unvisited_candidates(
        _engine(actions), "settings"
    ) == actions


def test_stateful_row_and_compact_widget_aliases_collapse_by_state_key() -> None:
    row = _surface(name="Allow notification dot")
    row.el_type = "link"
    row.bbox_xywh = [0, 100, 1080, 140]
    row.center = [540, 170]
    compact = _surface(name="Allow notification dot")
    compact.el_type = "switch"
    compact.bbox_xywh = [875, 112, 173, 115]
    compact.center = [961, 169]

    deduped = _dedupe_stateful_aliases([row, compact])
    assert deduped == [compact]

    conflicting = _surface(name="Conflicting", state_value="on")
    conflicting.bbox_xywh = [900, 112, 100, 80]
    assert len(_dedupe_stateful_aliases([row, conflicting])) == 2, (
        "conflicting structured values must remain fail-closed")


def test_signature_injects_only_function_set_state_tokens() -> None:
    off = _surface(state_value="off")
    on = _surface(state_value="on")
    data_only = _surface(
        name="Do not disturb",
        uid="dnd-toggle",
        state_value="off",
        effect_scope="data_only",
    )

    off_names = signature_names([off])
    on_names = signature_names([on])
    data_names = signature_names([data_only])
    assert "state:bluetooth=off" in off_names
    assert "state:bluetooth=on" in on_names
    assert set(off_names) != set(on_names)
    assert not any(name.startswith("state:") for name in data_names)


def test_safe_stateful_uid_is_scoped_by_value_not_global_visit() -> None:
    # The same visual toggle normally has the same name and appearance UID in
    # both states.  A visit to ``on`` must not globally erase the inverse action
    # exposed by the ``off`` surface (or vice versa).
    off = _surface(state_value="off", uid="same-toggle-uid", category="navigation")
    engine = _engine([off], visited_uids={"same-toggle-uid"})
    assert VisualTraversalEngine._unvisited_candidates(engine, "settings") == [off]
    assert not off.visited


def test_appearance_uid_does_not_retire_navigation_across_states() -> None:
    overflow = VisualElement(
        7, "More options", [0, 0, 20, 20], [10, 10],
        el_type="button", category="navigation", interactive=True,
        uid="same-appearance-on-another-surface",
    )
    engine = _engine(
        [overflow], visited_uids={"same-appearance-on-another-surface"})
    candidates = VisualTraversalEngine._unvisited_candidates(engine, "settings")
    assert candidates == [overflow]
    assert overflow.visited is False


def test_stateful_probe_caps_are_opt_in_and_fail_closed() -> None:
    surface = _surface(uid="remaining-safe-surface")
    engine = _engine([surface])
    engine.max_actions = 1200
    engine._action_count = 100
    engine._active_state_mutation = None
    engine._stateful_probe_count = 20
    engine._stateful_probe_sources = {
        ("settings", f"axis-{index}", "off") for index in range(4)
    }
    engine._stateful_probe_limit = 0
    engine._stateful_per_node_limit = 0
    engine._stateful_budget_blocked = False
    assert engine._stateful_scope_candidates("settings", [surface]) == [surface]
    assert engine._stateful_budget_blocked is False

    engine._stateful_probe_limit = 20
    assert engine._stateful_scope_candidates("settings", [surface]) == []
    assert engine._stateful_budget_blocked is True
    assert "stateful_probe_budget" in __import__("inspect").getsource(schedule_frontier)


def test_active_mutation_explores_only_new_host_functions_then_inverse() -> None:
    inverse = _surface(name="Disable advanced mode", state_value="on")
    existing = VisualElement(
        1, "Existing destination", [0, 0, 20, 20], [10, 10],
        el_type="button", category="navigation", interactive=True,
        region="content")
    exposed = VisualElement(
        2, "New advanced action", [0, 0, 20, 20], [10, 10],
        el_type="button", category="navigation", interactive=True,
        region="content")
    engine = _engine([inverse, existing, exposed])
    engine.max_actions = 20
    engine._action_count = 2
    engine._active_state_mutation = {
        "source_state": "settings",
        "mutated_state": "settings",
        "state_key": "bluetooth",
        "inverse_element": inverse,
        "explore_local_functions": True,
        "baseline_candidates": [engine._stateful_candidate_key(existing)],
    }

    assert engine._stateful_scope_candidates(
        "settings", [inverse, existing, exposed]) == [exposed]
    assert engine._stateful_scope_candidates(
        "child", [exposed]) == []
    assert engine._stateful_scope_candidates(
        "settings", [inverse, existing]) == [inverse]


def test_active_mutation_inverse_bypasses_explorer_and_prior_click_history() -> None:
    inverse = _surface(name="Disable advanced mode", state_value="on")
    events = []
    host = SimpleNamespace(
        _is_touch=True,
        _active_state_mutation={
            "mutation_id": "m1", "state_key": "bluetooth",
            "before_value": "off", "after_value": "unknown"},
        _stateful_target_value=VisualTraversalEngine._stateful_target_value,
        _action_count=1,
        review_debug=SimpleNamespace(
            record_event=lambda *args, **kwargs: events.append((args, kwargs))),
        perception=SimpleNamespace(use_semantic_inventory=True),
    )

    planned = plan_candidate(
        host,
        RunCursor("settings", {"screenshot": b"frame"}),
        [inverse],
    )

    assert planned.directive is StageDirective.EXECUTION
    assert planned.candidate.element is inverse
    assert planned.candidate.is_restore is True
    assert planned.candidate.action == {
        "action_type": "CLICK", "parameters": {}}
    assert planned.candidate.stateful_evidence["purpose"] == "restore"
    assert planned.candidate.stateful_evidence["before_value"] == "unknown"
    assert planned.candidate.stateful_evidence["expected_after_value"] == "off"
    assert events[0][0] == ("stateful_restore_select",)


def test_active_mutation_restores_through_state_key_and_scope_drift() -> None:
    durable = _surface(
        name="Show notifications",
        state_value="on",
        effect_scope="function_set",
    )
    durable.state_key = "show notifications"
    durable.group = "notification_mode"
    inverse = _surface(
        name="Show notifications",
        state_value="off",
        effect_scope="data_only",
    )
    inverse.state_key = "notification setting"
    inverse.group = "Notification mode"
    engine = _engine([inverse])
    engine._action_count = 1
    engine.perception = SimpleNamespace(use_semantic_inventory=True)
    restore_key = engine._stateful_candidate_key(durable)
    engine._active_state_mutation = {
        "mutation_id": "m-notifications",
        "source_state": "enabled",
        "mutated_state": "settings",
        "state_key": "show_notifications",
        "before_value": "on",
        "after_value": "off",
        "restore_candidate_key": restore_key,
        "explore_local_functions": True,
        "baseline_candidates": [],
    }

    candidates = engine._stateful_scope_candidates("settings", [inverse])
    planned = plan_candidate(
        engine,
        RunCursor("settings", {"screenshot": b"frame"}),
        candidates,
    )

    assert engine._state_value_on_state(
        "settings", "show_notifications") == "unknown"
    assert _state_value_from_elements(
        [inverse],
        "show_notifications",
        candidate_key=restore_key,
        key_fn=engine._stateful_candidate_key,
    ) == "off"
    assert candidates == [inverse]
    assert planned.directive is StageDirective.EXECUTION
    assert planned.candidate.element is inverse
    assert planned.candidate.is_restore is True
    assert planned.candidate.stateful_evidence["purpose"] == "restore"


def test_active_mutation_restores_through_live_region_role_drift() -> None:
    durable = _surface(
        name="Show notifications",
        state_value="off",
        effect_scope="function_set",
    )
    durable.region = ""
    live_inverse = _surface(
        name="Show notifications",
        state_value="on",
        effect_scope="function_set",
    )
    live_inverse.region = "notification_controls"
    engine = _engine([durable])
    engine._action_count = 1
    engine.perception = SimpleNamespace(use_semantic_inventory=True)
    restore_key = engine._stateful_candidate_key(durable)

    changed, _added, _removed, inverse = _stateful_function_delta(
        engine, "settings", "settings", durable.state_key,
        target_elements=[
            live_inverse,
            VisualElement(
                2, "Notification category", [0, 0, 20, 20], [10, 10],
                el_type="target", category="navigation", interactive=True,
                region="notification_controls",
            ),
        ],
        restore_candidate_key=restore_key,
    )
    assert changed is True
    assert inverse is live_inverse

    engine._active_state_mutation = {
        "mutation_id": "m-region-drift",
        "source_state": "settings",
        "mutated_state": "settings",
        "state_key": durable.state_key,
        "before_value": "off",
        "after_value": "on",
        "probe_candidate_key": restore_key,
        "restore_candidate_key": restore_key,
        "inverse_element": live_inverse,
        "explore_local_functions": True,
        "baseline_candidates": [],
    }
    candidates = engine._stateful_scope_candidates("settings", [durable])
    planned = plan_candidate(
        engine,
        RunCursor("settings", {"screenshot": b"frame"}),
        candidates,
    )

    assert candidates == [live_inverse]
    assert planned.directive is StageDirective.EXECUTION
    assert planned.candidate.element is live_inverse
    assert planned.candidate.is_restore is True


def test_active_mutation_uses_only_live_variant_owned_inverse() -> None:
    stale_baseline = _surface(
        name="Show notifications",
        state_value="on",
        effect_scope="function_set",
    )
    live_inverse = _surface(
        name="Show notifications",
        state_value="off",
        effect_scope="data_only",
    )
    stale_baseline.state_key = "show_notifications"
    live_inverse.state_key = "show notifications"
    unrelated = VisualElement(
        2, "Open details", [0, 0, 20, 20], [10, 10],
        el_type="target", category="navigation", interactive=True,
    )
    engine = _engine([live_inverse])
    restore_key = engine._stateful_candidate_key(live_inverse)
    engine._active_state_mutation = {
        "mutation_id": "m-variant-drift",
        "source_state": "enabled",
        "mutated_state": "stale-disabled",
        "state_key": "show_notifications",
        "before_value": "on",
        "after_value": "unknown",
        "probe_candidate_key": restore_key,
        "restore_candidate_key": restore_key,
        "inverse_element": live_inverse,
        "explore_local_functions": True,
        "baseline_candidates": [],
    }

    assert engine._stateful_scope_candidates(
        "enabled", [stale_baseline]) == []
    assert engine._stateful_scope_candidates(
        "live-disabled", [live_inverse]) == [live_inverse]
    assert engine._stateful_scope_candidates(
        "unrelated", [unrelated]) == []


def test_deny_return_clears_unknown_mutation_only_with_fresh_baseline() -> None:
    events = []
    restore_records = []
    host = SimpleNamespace(
        _active_state_mutation={
            "mutation_id": "m-confirm",
            "source_state": "permission-detail",
            "state_key": "allow_do_not_disturb",
            "before_value": "off",
            "after_value": "unknown",
            "probe_candidate_key": "",
            "restore_candidate_key": "",
        },
        _stateful_inflight={"mutation_id": "m-confirm"},
        _stateful_candidate_key=lambda _element: "",
        review_debug=SimpleNamespace(
            record_event=lambda *args, **kwargs: events.append(
                (args, kwargs))),
    )
    baseline = _surface(name="Allow Do Not Disturb", state_value="off")
    baseline.state_key = "allow_do_not_disturb"

    assert _clear_mutation_on_verified_baseline_return(
        host,
        "permission-detail",
        [baseline],
        observation_fresh=True,
        record_restore=restore_records.append,
    )
    assert host._active_state_mutation is None
    assert host._stateful_inflight is None
    assert events[0][0] == ("stateful_baseline_return",)
    assert restore_records == [{
        "mutation_id": "m-confirm",
        "purpose": "restore",
        "stateful": True,
        "state_key": "allow_do_not_disturb",
        "before_value": "unknown",
        "after_value": "off",
        "restore_before_value": "",
        "restoration_kind": "verified_baseline_return",
        "fresh_post_action_observation": True,
    }]

    host._active_state_mutation = {
        "mutation_id": "m-confirm",
        "source_state": "permission-detail",
        "state_key": "allow_do_not_disturb",
        "before_value": "off",
    }
    changed = _surface(name="Allow Do Not Disturb", state_value="on")
    changed.state_key = "allow_do_not_disturb"
    assert not _clear_mutation_on_verified_baseline_return(
        host,
        "permission-detail",
        [changed],
        observation_fresh=True,
    )
    assert host._active_state_mutation is not None

    assert not _clear_mutation_on_verified_baseline_return(
        host,
        "permission-detail",
        [baseline],
        observation_fresh=False,
    )
    assert host._active_state_mutation is not None


def test_baseline_return_uses_frozen_selector_across_state_axis_wording_drift(
        ) -> None:
    durable = _surface(
        name="Allow only while using the app", state_value="on")
    durable.el_type = "target"
    durable.group = "camera_access_level"
    durable.state_key = "camera permission mode"
    restore_key = VisualTraversalEngine._stateful_candidate_key(durable)

    live = _surface(
        name="Allow only while using the app", state_value="on",
        effect_scope="data_only")
    live.el_type = "target"
    live.group = "Camera access level"
    live.state_key = "Camera access level"
    host = SimpleNamespace(
        _active_state_mutation={
            "mutation_id": "m-confirm",
            "source_state": "permission-detail",
            "state_key": durable.state_key,
            "before_value": "off",
            "after_value": "unknown",
            "restore_candidate_key": restore_key,
            "restore_before_value": "on",
        },
        _stateful_inflight={"mutation_id": "m-confirm"},
        _stateful_candidate_key=VisualTraversalEngine._stateful_candidate_key,
        review_debug=_Debug(),
    )

    assert _clear_mutation_on_verified_baseline_return(
        host,
        "permission-detail",
        [live],
        observation_fresh=True,
    )
    assert host._active_state_mutation is None
    assert host._stateful_inflight is None


def test_candidate_selection_closes_resumed_mutation_on_fresh_source_baseline() -> None:
    baseline = _surface(name="Original", state_value="on")
    baseline.state_key = "mode"
    restore_key = "original-key"
    route_event = {
        "action_index": 7,
        "target": "settings",
        "committed": True,
        "landing_verified": True,
        "evidence": {"prediction_provenance": "direct_verified"},
    }
    graph = SimpleNamespace(
        transition_events=[route_event],
        update_action_event=lambda _index, **changes: route_event.update(
            changes),
    )
    host = SimpleNamespace(
        _active_state_mutation={
            "mutation_id": "m-resumed",
            "source_state": "settings",
            "mutated_state": "confirmation",
            "state_key": "mode",
            "before_value": "off",
            "after_value": "unknown",
            "restore_candidate_key": restore_key,
        },
        _stateful_inflight={"mutation_id": "m-resumed"},
        _state_data={"settings": {"elements": [baseline]}},
        _last_live_observation_state_id="settings",
        _last_live_observation_elements=[baseline],
        _stateful_candidate_key=lambda element: (
            restore_key if element is baseline else ""),
        _unvisited_candidates=lambda _state_id: [],
        _explorer_deferred_regions=set(),
        graph=graph,
        review_debug=_Debug(),
    )

    assert available_unvisited_candidates(host, "settings") == []
    assert host._active_state_mutation is None
    assert host._stateful_inflight is None
    assert route_event["evidence"]["prediction_provenance"] == \
        "direct_verified"
    assert route_event["evidence"]["mutation_id"] == "m-resumed"
    assert route_event["evidence"]["purpose"] == "restore"


def test_grouped_state_restores_the_original_selected_choice() -> None:
    def choice(name: str, selected: bool, value: str) -> VisualElement:
        return VisualElement(
            0, name, [0, 0, 20, 20], [10, 10],
            el_type="target", category="shallow", interactive=True,
            enabled=True, selected=selected, group="mode_choice",
            stateful=True, state_key="mode", state_value=value,
            effect_scope="function_set", reversible=True, risk="none")

    original = choice("Original", True, "on")
    probe = choice("Alternative", False, "off")
    selected_probe = choice("Alternative", True, "on")
    deselected_original = choice("Original", False, "off")
    engine = _engine([selected_probe, deselected_original])
    engine.max_actions = 20
    engine._action_count = 3
    probe_key = engine._stateful_candidate_key(probe)
    restore_key = engine._stateful_candidate_key(original)
    live_original = choice("Original", True, "on")
    live_original.region = "renamed live block"

    assert _state_value_from_elements(
        [deselected_original, selected_probe], "mode",
        candidate_key=probe_key,
        key_fn=engine._stateful_candidate_key,
    ) == "on"
    assert _state_value_from_elements(
        [live_original, probe], "mode",
        candidate_key=restore_key,
        key_fn=engine._stateful_candidate_key,
    ) == "on"
    changed, added, removed, inverse = _stateful_function_delta(
        engine, "settings", "settings", "mode",
        target_elements=[selected_probe, deselected_original],
        restore_candidate_key=restore_key,
    )
    assert changed is False and added == [] and removed == []
    assert inverse is deselected_original

    engine._active_state_mutation = {
        "mutation_id": "m-grouped-choice",
        "source_state": "settings",
        "mutated_state": "settings",
        "state_key": "mode",
        "before_value": "off",
        "after_value": "on",
        "restore_candidate_key": restore_key,
        "restore_before_value": "on",
        "explore_local_functions": False,
        "baseline_candidates": [],
    }
    assert engine._stateful_scope_candidates(
        "settings", [selected_probe, deselected_original]
    ) == [deselected_original]
    assert _clear_mutation_on_verified_baseline_return(
        engine,
        "settings",
        [live_original, probe],
        observation_fresh=True,
    )
    assert engine._active_state_mutation is None


def test_no_effect_retry_reuses_runtime_click_feedback() -> None:
    surface = _surface()
    engine = _engine([surface])
    engine._click_failures = {}
    engine._targeting_corrections = {}
    engine._last_live_rebind_observation = {
        "diagnostic": {"click_point_1000": [231, 320]}}

    assert engine._record_click_failure(
        "settings", surface, "no_effect") == 1
    correction = engine._targeting_correction_for("settings", surface)
    assert "[231,320]" in correction
    assert "Do not repeat that point" in correction

    engine._commit_explored("settings", surface, False)
    assert engine._targeting_correction_for("settings", surface) == ""


def test_restore_accepts_fresh_baseline_even_when_stored_element_is_stale() -> None:
    active = {"before_value": "on", "after_value": "unknown"}

    assert _stateful_restore_effect(active, "on", True) == {
        "verdict": "transitioned_consistent",
        "note": "structured state restored to baseline on",
    }
    assert _stateful_restore_effect(active, "off", True)["verdict"] == \
        "transitioned_inconsistent"
    assert _stateful_restore_effect(active, "unknown", True)["verdict"] == \
        "uncertain"
    assert _stateful_restore_effect(
        active, "unknown", True, baseline_frame_match=True
    ) == {
        "verdict": "transitioned_consistent",
        "note": (
            "live frame returned to the exact pre-mutation baseline "
            "for state on"),
    }
    assert _stateful_restore_effect(active, "on", False)["verdict"] == \
        "uncertain"


def test_stateful_restore_edge_label_uses_transaction_target() -> None:
    stale = _surface(name="Feature", state_value="on")
    assert VisualTraversalEngine._stateful_edge_label(stale) == \
        "Set bluetooth off"
    assert VisualTraversalEngine._stateful_edge_label(stale, "on") == \
        "Set bluetooth on"


def test_only_structured_value_flip_opens_a_mutation() -> None:
    changed = VisualTraversalEngine._verified_state_value_changed
    assert changed("off", "on")
    assert changed("ON", " off ")
    assert not changed("off", "off")
    assert not changed("off", "unknown")
    assert not changed("unknown", "on")
    assert not changed("", "")


def test_fresh_pixel_change_with_conflicting_state_requires_restore() -> None:
    evidence = {
        "mutation_id": "m-uncertain",
        "purpose": "probe",
        "stateful": True,
        "before_value": "off",
        "after_value": "off",
        "reversible": True,
        "risk": "none",
        "restore_candidate_key": "original||target|mode",
        "fresh_post_action_observation": True,
        "post_action_phash_distance": 2,
    }

    assert unresolved_stateful_probe_requires_restore(
        evidence, outcome="uncertain", committed=False)
    assert not unresolved_stateful_probe_requires_restore(
        evidence, outcome="no_effect", committed=False)
    assert not unresolved_stateful_probe_requires_restore(
        {**evidence, "post_action_phash_distance": 0},
        outcome="uncertain", committed=False)
    assert not unresolved_stateful_probe_requires_restore(
        {**evidence, "risk": "permission"},
        outcome="uncertain", committed=False)


def test_non_none_semantic_risks_are_blocked_before_explorer() -> None:
    login = _surface(
        name="Sign in to enable",
        uid="login",
        requires_permission=True,
        blocked_reason="application_login",
        risk="authentication",
    )
    irreversible = _surface(
        name="Erase protection",
        uid="irreversible",
        reversible=False,
        risk="none",
    )
    risky = _surface(
        name="Disable networking",
        uid="connectivity",
        reversible=True,
        risk="connectivity",
    )

    engine = _engine([login, irreversible, risky])
    assert VisualTraversalEngine._unvisited_candidates(engine, "settings") == [
        irreversible]
    assert login.visited is True and risky.visited is True
    assert irreversible.visited is False
    assert [record["element_name"] for record in engine.graph.records] == [
        "Sign in to enable", "Disable networking"]


def test_semantic_danger_control_has_terminal_safety_outcome() -> None:
    shutdown = VisualElement(
        9, "Confirm action", [0, 0, 20, 20], [10, 10],
        el_type="button", category="dangerous", interactive=True,
        risk="destructive", uid="destructive-action",
    )
    engine = _engine([shutdown])
    assert VisualTraversalEngine._unvisited_candidates(engine, "settings") == []
    assert shutdown.visited is True
    assert engine.graph.records == [{
        "state_id": "settings",
        "element_id": "9",
        "element_uid": "destructive-action",
        "element_name": "Confirm action",
        "region": "",
        "region_id": "",
        "reason": "blocked",
        "detail": (
            "safety policy forbids executing a dangerous or uncertain-risk "
            "control during exploration"),
        "action": None,
            "evidence": None,
    }]


def test_independent_stateful_risk_guard_is_strict_and_network_aware() -> None:
    assert "transport/control channel" in STATEFUL_RISK_PROMPT
    assert "do not decide from the control's name alone" in STATEFUL_RISK_PROMPT
    assert "Do not trust the upstream risk label" in STATEFUL_RISK_PROMPT
    assert StatefulRiskGuard(None).assess(_png(), _surface())["allow"] is False

    class _Agent:
        def __init__(self, response: str):
            self.response = response

        def predict_mm(self, _prompt, _images):
            return self.response, None

    # Explicit connectivity risk vetoes even a contradictory allow=true claim.
    denied = StatefulRiskGuard(_Agent(
        '{"allow":true,"risk":"connectivity","reason":"changes the control transport"}'
    )).assess(_png(), _surface(name="Primary service gate"))
    assert denied == {
        "allow": False, "risk": "connectivity",
        "reason": "changes the control transport"
    }
    # Boolean strings are parsed strictly; "false" must not become truthy.
    assert StatefulRiskGuard(_Agent(
        '{"allow":"false","risk":"none","reason":"not cleared"}'
    )).assess(_png(), _surface())["allow"] is False
    allowed = StatefulRiskGuard(_Agent(
        '{"allow":true,"risk":"none","reason":"local reversible feature"}'
    )).assess(_png(), _surface())
    assert allowed["allow"] is True


def main() -> None:
    tests = [
        test_prompts_request_stateful_surface_schema,
        test_prompts_limit_function_set_to_in_app_interactive_expansion,
        test_prompts_use_context_for_safe_local_form_completion,
        test_grounding_parser_normalizes_fields_and_keeps_legacy_responses,
        test_grounding_parser_preserves_compact_feature_entry_decisions,
        test_som_naming_parser_populates_the_same_normalized_fields,
        test_data_only_remains_data_but_function_set_is_a_surface,
        test_appearance_preferences_stay_out_but_in_app_expansion_enters,
        test_expansion_actions_remain_on_the_ordinary_frontier,
        test_stateful_row_and_compact_widget_aliases_collapse_by_state_key,
        test_signature_injects_only_function_set_state_tokens,
        test_safe_stateful_uid_is_scoped_by_value_not_global_visit,
        test_appearance_uid_does_not_retire_navigation_across_states,
        test_stateful_probe_caps_are_opt_in_and_fail_closed,
        test_only_structured_value_flip_opens_a_mutation,
        test_permission_irreversibility_and_risk_stay_fail_closed,
        test_direct_danger_control_has_terminal_safety_outcome,
        test_independent_stateful_risk_guard_is_strict_and_network_aware,
    ]
    for test in tests:
        test()
    print(f"stateful function surfaces: {len(tests)} tests passed")


if __name__ == "__main__":
    main()
