"""Offline contracts for flag-gated map-guided post-click identity."""
from __future__ import annotations

from types import SimpleNamespace

import networkx as nx
import pytest
from PIL import Image

from gui_rewalk.src.core.visual_traversal.agents.identity import PageIdentityJudge
from gui_rewalk.src.core.visual_traversal.navigation.router import VisualRouter
from gui_rewalk.src.core.visual_traversal.runtime.contracts import (
    CandidateContext, PerceptionUnavailable, RunCursor, StageDirective,
)
from gui_rewalk.src.core.visual_traversal.runtime.execution import execute_candidate
from gui_rewalk.src.core.visual_traversal.runtime.landing import (
    _clear_stale_inherited_marker, _known_return_failure_landing,
    _refresh_verified_return_landing, register_landing,
)
from gui_rewalk.src.core.visual_traversal.state.map_guided import confirm_arrival
from gui_rewalk.src.core.visual_traversal.state import registration
from gui_rewalk.src.core.visual_traversal.visual_state import VisualStateRegistry


class _Debug:
    enabled = False

    def __init__(self):
        self.events = []

    def record_event(self, event, **payload):
        self.events.append((event, payload))


def _element(name, template=None):
    return SimpleNamespace(
        name=name, _template=template, center=[10, 10], scroll_steps=0,
        region_bbox=None, id=1, uid=f"uid-{name}", region="content",
    )


def test_button_containment_page_identity_is_removed():
    registry = VisualStateRegistry()
    assert not hasattr(registry, "identify_by_buttons")


class _Registry:
    def __init__(self, paths=None):
        self.paths = paths or {}
        self.region_sets = {}

    def known_path(self, sid):
        return self.paths.get(sid)

    def common_buttons(self):
        return frozenset({"shared"})

    def region_set_of(self, sid):
        return set(self.region_sets.get(sid, set()))

    def record_page_variant(self, sid, page_name, **kwargs):
        return f"page-{sid}", f"variant-{sid}"


def test_expected_destinations_orders_direct_source_and_dedupes():
    router = object.__new__(VisualRouter)
    router.node_out_edges = lambda _sid: {
        "zeta": {"dst": "z"},
        "network": {"dst": "target"},
        "alpha": {"dst": "target"},
        "unknown": {"dst": None},
    }
    assert router.expected_destinations("source", " Network ") == [
        "target", "source", "z"]
    assert router.expected_destinations("source", "missing") == [
        "source", "target", "z"]


def test_expected_destinations_excludes_unverified_real_graph_edge():
    graph = SimpleNamespace(graph=nx.DiGraph())
    graph.graph.add_edge(
        "source", "verified", element_label="Network", region="content",
        routing_verified=True, landing_verified=True)
    graph.graph.add_edge(
        "source", "unverified", element_label="Bluetooth", region="content",
        routing_verified=False, landing_verified=None)
    router = VisualRouter(
        graph, SimpleNamespace(_regions={}), {}, lambda _obs: None,
        lambda _name, _region, obs: obs)
    assert router.expected_destinations("source", "Bluetooth") == [
        "source", "verified"]


def test_template_support_does_not_bypass_page_identity_vlm():
    state_data = {
        "a": {"elements": [_element("one", "t1"), _element("two", "t2")]},
        "b": {"elements": [_element("other", "t3")]},
    }
    reloc = SimpleNamespace(relocate_unique=lambda template, _shot: (
        (1, 1, 0.95, 0.2) if template in {"t1", "t2"} else None))
    judge = SimpleNamespace(
        last_reason="live surface matches b",
        which_page=lambda *_a, **_k: "b")
    sid, reason = confirm_arrival(
        state_data, _Registry(), reloc, ["a", "b"], b"shot", judge,
        lambda sid: {"name": "Target" if sid == "b" else "Other"},
        current_observation={"page": "Target"})
    assert sid == "b"
    assert reason.startswith("vlm:b:")


def test_ambiguous_template_evidence_calls_vlm(tmp_path):
    paths = {}
    for sid in ("a", "b"):
        path = tmp_path / f"{sid}.png"
        path.write_bytes(sid.encode())
        paths[sid] = str(path)
    state_data = {
        "a": {"elements": [_element("one", "ta")]},
        "b": {"elements": [_element("two", "tb")]},
    }
    calls = []
    judge = SimpleNamespace(
        last_reason="content matches b",
        which_page=lambda shot, candidates, transition=None, **_kwargs: (
            calls.append((shot, candidates, transition)) or "b"),
    )
    sid, reason = confirm_arrival(
        state_data, _Registry(paths),
        SimpleNamespace(relocate_unique=lambda *_a, **_k: (1, 1, .9, .2)),
        ["a", "b"], b"shot", judge,
        lambda sid: {"name": "Target" if sid == "b" else "Other"},
        current_observation={"page": "Target"},
        transition={"source_id": "s", "clicked_label": "go"})
    assert sid == "b"
    assert reason.startswith("vlm:b:")
    assert [item["sid"] for item in calls[0][1]] == ["a", "b"]


def test_local_identity_sends_all_variant_deduplicated_neighbors():
    neighbors = [f"page-{index}" for index in range(7)]
    calls = []
    judge = SimpleNamespace(
        last_reason="last neighbor matches",
        which_page=lambda _shot, candidates, transition=None, **_kwargs: (
            calls.append([item["sid"] for item in candidates])
            or neighbors[-1]),
    )
    sid, reason = confirm_arrival(
        {item: {"elements": []} for item in neighbors},
        _Registry(), SimpleNamespace(relocate_unique=lambda *_a: None),
        neighbors, b"shot", judge, lambda sid: {"name": sid},
        current_observation={"page": neighbors[-1]})
    assert sid == neighbors[-1]
    assert reason.startswith(f"vlm:{neighbors[-1]}:")
    assert calls == [neighbors]


def test_which_page_shortlists_by_text_then_compares_one_full_screenshot(
        monkeypatch, tmp_path):
    captured = []
    candidate_path = tmp_path / "candidate.png"
    source_path = tmp_path / "source.png"
    candidate_path.write_bytes(b"CANDIDATE")
    source_path.write_bytes(b"SOURCE")
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.identity._img_arr",
        lambda value: value)

    def predict(_agent, role, prompt, images, _ledger):
        captured.append({"role": role, "prompt": prompt, "images": images})
        if role == "page_identity_candidate_selection":
            return (
                '{"candidate_page_ids":["C2"],'
                '"proposed_new_page_name":"Clock schedule",'
                '"reason":"Clock entry points"}',
                None,
            )
        return (
            '{"is_interruption":false,"same_page":true,'
            '"reason":"same active interface"}', None)

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    judge = PageIdentityJudge(object())
    candidates = [
        {
            "sid": "a", "page_id": "clock-settings",
            "state_ids": ["a"],
            "descriptor": {"interface_name": "Clock settings"},
        },
        {
            "sid": "b", "page_id": "clock-main",
            "state_ids": ["b", "b-populated"],
            "descriptor": {
                "interface_name": "Clock main",
                "regions": [{
                    "name": "Alarm list",
                    "description": "Shows current alarms.",
                }],
            },
         "screenshot_path": str(candidate_path)},
    ]
    assert judge.which_page(
        b"CURRENT", candidates,
        transition={
            "source_screenshot_path": str(source_path),
            "clicked_label": "Expected privacy destination",
            "clicked_bbox": [10, 20, 30, 40],
            "clicked_point": [25, 40],
        },
        current_observation={
            "page": "Clock main",
            "blocks": [{"role": "main_action_area",
                        "targets": ["Transient bedtime notice"]}],
            }) == "b"
    assert captured[0]["role"] == "page_identity_candidate_selection"
    assert captured[0]["images"] == [b"CURRENT", b"SOURCE"]
    assert '"candidate_page_id": "C2"' in captured[0]["prompt"]
    assert "source_id" not in captured[0]["prompt"]
    assert "Expected privacy destination" in captured[0]["prompt"]
    assert "[10, 20, 30, 40]" in captured[0]["prompt"]
    assert "来源页面，只用于理解到达路径和命名" in captured[0]["prompt"]
    assert captured[1]["images"] == [b"CANDIDATE", b"CURRENT"]
    assert "atlas" not in captured[1]["prompt"]
    assert "图1是已登记截图" in captured[1]["prompt"]
    assert "当前操作界面是截图中最前方、实际接收用户下一步操作的界面" in (
        captured[1]["prompt"])
    assert "same_page_variant" not in captured[1]["prompt"]
    assert judge.last_reason == "same active interface"
    assert judge.last_proposed_new_page_name == "Clock schedule"
    assert judge.last_candidate_page_ids == ("clock-main",)
    assert judge.last_matched_candidate_state_ids == ("b", "b-populated")

    replies = iter([
        (
            '{"candidate_page_ids":["C2"],'
            '"proposed_new_page_name":"Clock schedule",'
            '"reason":"closest candidate"}',
            None,
        ),
        ('{"is_interruption":false,"same_page":false,'
         '"reason":"different"}', None),
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_a, **_k: next(replies))
    assert judge.which_page(
        b"CURRENT", candidates,
        current_observation={"page": "Clock main"}) == "NEW"
    assert judge.last_choice == "NEW"


def test_which_page_sends_registered_and_current_full_images_without_atlas(
        monkeypatch, tmp_path):
    captured = {}
    candidate_path = tmp_path / "candidate.png"
    Image.new("RGB", (30, 40), "navy").save(candidate_path)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.identity._img_arr",
        lambda value: value)

    replies = iter([
        (
            '{"candidate_page_ids":["C1"],'
            '"proposed_new_page_name":"Advanced settings",'
            '"reason":"closest candidate"}',
            None,
        ),
        ('{"is_interruption":false,"same_page":true,'
         '"reason":"same"}', None),
    ])

    def predict(_agent, role, prompt, images, _ledger):
        captured.setdefault("calls", []).append({
            "role": role, "prompt": prompt, "images": images})
        return next(replies)

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    judge = PageIdentityJudge(object())
    assert judge.which_page(b"CURRENT", [{
        "sid": "stable-secret-id",
        "descriptor": {"name": "Settings"},
        "screenshot_path": str(candidate_path),
    }], current_observation={"page": "Settings"}) == "stable-secret-id"
    assert captured["calls"][0]["images"] == [b"CURRENT"]
    assert captured["calls"][1]["images"][1] == b"CURRENT"
    assert "atlas" not in captured["calls"][1]["prompt"]
    assert "stable-secret-id" not in captured["calls"][0]["prompt"]


def test_which_page_reuses_same_page_candidate(
        monkeypatch, tmp_path):
    candidate_path = tmp_path / "empty.png"
    candidate_path.write_bytes(b"EMPTY")
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.identity._img_arr",
        lambda value: value)
    replies = iter([
        (
            '{"candidate_page_ids":["C1"],'
            '"proposed_new_page_name":"Alarm list",'
            '"reason":"closest page"}',
            None,
            ),
            (
                '{"is_interruption":false,"same_page":true,'
                '"reason":"a newly created item is visible"}',
                None,
            ),
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: next(replies))

    judge = PageIdentityJudge(object())
    result = judge.which_page(b"POPULATED", [{
        "sid": "alarm-empty",
        "screenshot_path": str(candidate_path),
    }])

    assert result == "alarm-empty"
    assert judge.last_comparison_status == "same_page"


def test_which_page_stops_after_the_first_confirmed_page(
        monkeypatch, tmp_path):
    variant_path = tmp_path / "variant.png"
    same_path = tmp_path / "same.png"
    variant_path.write_bytes(b"VARIANT")
    same_path.write_bytes(b"SAME")
    replies = iter([
        (
            '{"candidate_page_ids":["C1","C2"],'
            '"proposed_new_page_name":"Clock detail",'
            '"reason":"both are plausible"}',
            None,
            ),
            ('{"is_interruption":false,"same_page":true,'
             '"reason":"same page with another tab active"}', None),
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.identity._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: next(replies))

    judge = PageIdentityJudge(object())
    result = judge.which_page(b"CURRENT", [
        {"sid": "source-variant", "screenshot_path": str(variant_path)},
        {"sid": "existing-state", "screenshot_path": str(same_path)},
    ])

    assert result == "source-variant"
    assert judge.last_comparison_status == "same_page"


def test_which_page_text_selector_chooses_one_candidate_for_pair_check(
        monkeypatch, tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"FIRST")
    second.write_bytes(b"SECOND")
    calls = []
    replies = iter([
        (
            '{"candidate_page_ids":["C2"],'
            '"proposed_new_page_name":"Clock schedule",'
            '"reason":"best semantic match"}',
            None,
        ),
        ('{"is_interruption":false,"same_page":true,'
         '"reason":"matched second"}', None),
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.identity._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda _agent, _role, _prompt, images, _ledger: (
            calls.append(images) or next(replies)))
    judge = PageIdentityJudge(object())
    candidates = [
        {"sid": "a", "descriptor": {"name": "Clock"},
         "screenshot_path": str(first)},
        {"sid": "b", "descriptor": {"name": "Clock"},
         "screenshot_path": str(second)},
    ]
    assert judge.which_page(
        b"CURRENT", candidates,
        current_observation={"page": "Clock"}) == "b"
    assert calls == [[b"CURRENT"], [b"SECOND", b"CURRENT"]]
    assert judge.last_reason == "matched second"


def test_which_page_retries_remaining_candidates_after_bad_shortlist(
        monkeypatch, tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"FIRST")
    second.write_bytes(b"SECOND")
    calls = []
    replies = iter([
        (
            '{"candidate_page_ids":["C1","C2"],'
            '"proposed_new_page_name":"Timer setup",'
            '"reason":"both are plausible"}',
            None,
        ),
        ('{"is_interruption":false,"same_page":false,'
         '"reason":"different controls"}', None),
        ('{"is_interruption":false,"same_page":true,'
         '"reason":"same controls, different data"}', None),
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.identity._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda _agent, role, _prompt, images, _ledger: (
            calls.append((role, images)) or next(replies)))
    judge = PageIdentityJudge(object())
    assert judge.which_page(b"CURRENT", [
        {"sid": "wrong", "descriptor": {"name": "Timer keypad"},
         "screenshot_path": str(first)},
        {"sid": "right", "descriptor": {"name": "Timer start control"},
         "screenshot_path": str(second)},
    ], current_observation={"name": "Timer start button"}) == "right"
    assert calls == [
        ("page_identity_candidate_selection", [b"CURRENT"]),
        ("page_identity", [b"FIRST", b"CURRENT"]),
        ("page_identity", [b"SECOND", b"CURRENT"]),
    ]


@pytest.mark.parametrize("selector_reply", [
    "not-json",
    '{"candidate_page_ids":[],"reason":"none"}',
    '{"candidate_page_ids":["C1"],"reason":"missing fallback name"}',
])
def test_candidate_selection_failure_cannot_directly_create_new_page(
        monkeypatch, tmp_path, selector_reply):
    candidate_path = tmp_path / "candidate.png"
    candidate_path.write_bytes(b"CANDIDATE")
    calls = []
    replies = iter([
        (selector_reply, None),
        ('{"is_interruption":false,"same_page":false,'
         '"reason":"different"}', None),
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.identity._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda _agent, role, _prompt, images, _ledger: (
            calls.append((role, images)) or next(replies)))

    judge = PageIdentityJudge(object())
    result = judge.which_page(b"CURRENT", [{
        "sid": "fallback",
        "descriptor": {"interface_name": "Settings", "regions": []},
        "screenshot_path": str(candidate_path),
    }])

    assert result == "UNRESOLVED"
    assert judge.last_selection_status == "fallback"
    assert calls == [
        ("page_identity_candidate_selection", [b"CURRENT"]),
        ("page_identity", [b"CANDIDATE", b"CURRENT"]),
    ]


def test_invalid_shortlist_can_create_new_page_only_after_exhaustive_pairs(
        monkeypatch, tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"FIRST")
    second.write_bytes(b"SECOND")
    calls = []
    replies = iter([
        (
            '{"candidate_page_ids":[],'
            '"proposed_new_page_name":"Alarms",'
            '"reason":"no registered Page is plausible"}',
            None,
        ),
        ('{"is_interruption":false,"same_page":false,'
         '"reason":"different from World"}', None),
        ('{"is_interruption":false,"same_page":false,'
         '"reason":"different from Timer"}', None),
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.identity._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda _agent, role, _prompt, images, _ledger: (
            calls.append((role, images)) or next(replies)))

    judge = PageIdentityJudge(object())
    result = judge.which_page(b"CURRENT", [
        {"sid": "world", "screenshot_path": str(first)},
        {"sid": "timer", "screenshot_path": str(second)},
    ])

    assert result == "NEW"
    assert judge.last_selection_status == "fallback_exhaustive"
    assert judge.last_proposed_new_page_name == "Alarms"
    assert calls == [
        ("page_identity_candidate_selection", [b"CURRENT"]),
        ("page_identity", [b"FIRST", b"CURRENT"]),
        ("page_identity", [b"SECOND", b"CURRENT"]),
    ]


def test_reverse_edge_explorer_uses_two_images_and_visible_target(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.identity._img_arr",
        lambda value: value)

    def predict(_agent, role, prompt, images, _ledger):
        captured.update(role=role, prompt=prompt, images=images)
        return ('{"action":{"action_type":"CLICK",'
                '"target":"顶部导航栏中的 World 标签"}}', None)

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    judge = PageIdentityJudge(object())
    decision = judge.choose_return(
        b"WORLD", b"ALARMS", source_name="World", target_name="Alarms",
        transition="顶部 Alarms 标签")

    assert decision == {
        "action": {"action_type": "CLICK"},
        "target": "顶部导航栏中的 World 标签",
        "reason": "",
    }
    assert captured["role"] == "return_path"
    assert captured["images"] == [b"WORLD", b"ALARMS"]
    assert "这不是要求一定返回的任务" in captured["prompt"]
    assert "图2是否应当继续作为当前操作界面遍历" in captured["prompt"]
    assert "刚才入口正常产生、仍实际接收操作的界面" in captured["prompt"]
    assert "不要仅为了建立或验证返回路径而离开图2" in captured["prompt"]
    assert "只有图2不应继续遍历、且必须立即恢复图1时" in captured["prompt"]
    assert "如果不能确认必须立即返回" in captured["prompt"]
    assert "优先点击该可见入口" in captured["prompt"]
    assert "choice_id" not in captured["prompt"]


def test_reverse_edge_explorer_accepts_dialog_cancel(monkeypatch):
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.identity._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_a, **_k: (
            '{"action":{"action_type":"CLICK",'
            '"target":"New Alarm 对话框左上角的 Cancel 按钮"}}', None))

    decision = PageIdentityJudge(object()).choose_return(
        b"ALARMS", b"DIALOG", source_name="Alarms",
        target_name="New Alarm", transition="Add Alarm")

    assert decision["action"] == {"action_type": "CLICK"}
    assert decision["target"] == "New Alarm 对话框左上角的 Cancel 按钮"


@pytest.mark.parametrize(
    ("platform", "reply", "expected"),
    [
        ("android", '{"action":{"action_type":"navigate_back"}}',
         {"action_type": "navigate_back"}),
        ("desktop",
         '{"action":{"action_type":"PRESS","parameters":{"key":"esc"}}}',
         {"action_type": "PRESS", "parameters": {"key": "esc"}}),
    ],
)
def test_reverse_edge_explorer_accepts_only_platform_return(
        monkeypatch, platform, reply, expected):
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.identity._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_a, **_k: (reply, None))

    decision = PageIdentityJudge(object()).choose_return(
        b"SOURCE", b"TARGET", source_name="Source",
        target_name="Target", transition="Open", platform=platform)

    assert decision["action"] == expected
    assert decision["target"] == ""


@pytest.mark.parametrize(
    "reply",
    [
        '{"action":null}',
        '{"action":{"action_type":"swipe","direction":"down"}}',
        '{"action":{"action_type":"CLICK","target":""}}',
    ],
)
def test_reverse_edge_explorer_null_or_invalid_action_abstains(
        monkeypatch, reply):
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.identity._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_a, **_k: (reply, None))

    decision = PageIdentityJudge(object()).choose_return(
        b"SOURCE", b"TARGET", source_name="Source",
        target_name="Target", transition="Open",
        platform="android")

    assert decision["action"] is None


def _map_host(registry, state_data, router, judge):
    host = SimpleNamespace(
        registry=registry, _state_data=state_data, router=router,
        page_judge=judge, _pending_transition={
            "source_id": "source", "clicked_label": "Network"},
        _map_guided_bypass_once=False, review_debug=_Debug(),
        _node_descriptor=lambda sid: {
            "name": str((state_data.get(sid) or {}).get("page_name") or sid)},
        app_name="demo",
        perception=SimpleNamespace(use_vlm_grounding=True),
    )
    return host


def test_flag_off_never_calls_map_judge(monkeypatch):
    monkeypatch.setenv("GUIWALK_MAP_GUIDED_ID", "0")
    judge = SimpleNamespace(which_page=lambda *_a, **_k: pytest.fail("judge called"))
    host = _map_host(_Registry(), {}, SimpleNamespace(
        expected_destinations=lambda *_a: pytest.fail("router called")), judge)
    assert registration._try_map_guided(host, b"shot") == (None, None, None)


def test_semantic_unknown_action_still_uses_two_layer_candidates(monkeypatch):
    monkeypatch.setenv("GUIWALK_MAP_GUIDED_ID", "1")
    router = SimpleNamespace(expected_destinations=lambda *_a: ["source"])
    host = _map_host(
        _Registry(), {}, router,
        SimpleNamespace(which_page=lambda *_a, **_k: "NEW", last_reason="new"))
    host._pending_transition = {
        "source_id": "source", "clicked_label": " More Options "}
    host.perception.use_semantic_inventory = True
    assert registration._try_map_guided(host, b"shot") == (None, None, None)
    assert any(name == "map_guided_decision" for name, _ in host.review_debug.events)


def test_semantic_known_direct_destination_keeps_fast_path(monkeypatch):
    monkeypatch.setenv("GUIWALK_MAP_GUIDED_ID", "1")
    from gui_rewalk.src.core.visual_traversal.state import map_guided

    registry = _Registry()
    registry.region_sets["network"] = {"semantic:content:x"}
    data = {"network": {"elements": [_element("Wired")],
                        "page_name": "Network"}}
    router = SimpleNamespace(
        node_out_edges=lambda _sid: {
            "network": {"dst": "network", "provenance": "direct_verified"}},
        expected_destinations=lambda *_a: ["network"])
    host = _map_host(registry, data, router, SimpleNamespace())
    host.perception.use_semantic_inventory = True
    monkeypatch.setattr(
        map_guided, "confirm_arrival",
        lambda *_a, **_k: ("network", "verified-direct"))
    result, arrival, names = registration._try_map_guided(host, b"shot")
    assert result is None
    assert arrival is None and names is None
    assert host._map_guided_preferred_state == "network"
    assert getattr(host, "_map_guided_inherited", None) is None


@pytest.mark.parametrize("transition", [
    {"source_id": "network", "clicked_label": "Bluetooth",
     "requires_fresh_observation": True},
    {"source_id": "network", "clicked_label": "Expand",
     "visual_changed": True},
])
def test_effectful_same_page_match_requires_fresh_observation(
        monkeypatch, transition):
    monkeypatch.setenv("GUIWALK_MAP_GUIDED_ID", "1")
    from gui_rewalk.src.core.visual_traversal.state import map_guided

    data = {"network": {
        "elements": [_element("Bluetooth")], "page_name": "Network"}}
    host = _map_host(
        _Registry(), data,
        SimpleNamespace(expected_destinations=lambda *_a: ["network"]),
        SimpleNamespace())
    host._pending_transition = transition
    monkeypatch.setattr(
        map_guided, "confirm_arrival",
        lambda *_a, **_k: ("network", "known-same-page"))

    assert registration._try_map_guided(host, b"live-after") == \
        (None, None, None)
    assert getattr(host, "_map_guided_inherited", None) is None


def test_page_vlm_can_reuse_without_running_perception(monkeypatch):
    monkeypatch.setenv("GUIWALK_MAP_GUIDED_ID", "1")
    old_reloc = registration._reloc
    registration._reloc = SimpleNamespace(
        relocate_unique=lambda template, _shot: (1, 1, .95, .2))
    try:
        registry = _Registry()
        registry.region_sets["network"] = {"region:content"}
        data = {"network": {"elements": [
            _element("wired", "t1"), _element("proxy", "t2")],
            "page_name": "Network"}}
        host = _map_host(
            registry, data,
            SimpleNamespace(expected_destinations=lambda *_a: ["network"]),
            SimpleNamespace(
                last_reason="same live interface",
                which_page=lambda *_a, **_k: "network"),
        )
        host.perception.detect_and_name = lambda *_a: pytest.fail("grounding called")
        result, _elements, _names = registration._try_map_guided(
            host, b"shot", current_observation={"page": "Network"})
        assert result == ("network", False)
        assert host._map_guided_inherited["state_id"] == "network"
        assert host._last_arrival_rset == {"region:content"}
        assert set(host._last_arrival_names) == {"wired", "proxy"}
    finally:
        registration._reloc = old_reloc


def test_global_fallback_adds_every_page_before_grounding(monkeypatch, tmp_path):
    monkeypatch.setenv("GUIWALK_MAP_GUIDED_ID", "1")
    local = tmp_path / "local.png"; local.write_bytes(b"local")
    remote_path = tmp_path / "remote.png"; remote_path.write_bytes(b"remote")
    registry = _Registry({"local": str(local), "remote": str(remote_path)})
    calls = []

    class Judge:
        last_reason = ""
        def which_page(self, _shot, candidates, transition=None):
            calls.append([item["sid"] for item in candidates])
            self.last_reason = "new locally" if len(calls) == 1 else "remote match"
            return "NEW" if len(calls) == 1 else "remote"

    data = {
        "local": {"elements": [], "page_name": "Local"},
        "remote": {"elements": [_element("remote action")],
                   "page_name": "Remote"},
    }
    host = _map_host(registry, data, SimpleNamespace(
        expected_destinations=lambda *_a: ["local"]), Judge())
    host.perception.detect_and_name = lambda _shot: pytest.fail(
        "known all-page match must skip grounding")
    result, pregrounded, names = registration._try_map_guided(
        host, b"shot", current_observation={"page": "Remote"})
    assert result == ("remote", False)
    assert pregrounded is None and names is None
    assert calls == [["local"], ["local", "remote"]]


def test_vlm_overlay_choice_is_not_rejected_by_framework_labels(monkeypatch):
    monkeypatch.setenv("GUIWALK_MAP_GUIDED_ID", "1")
    from gui_rewalk.src.core.visual_traversal.state import map_guided

    data = {
        "documents": {"elements": [], "page_name": "Documents",
                      "surface_kind": "page"},
        "home_menu": {"elements": [_element("Close menu")],
                      "page_name": "Home", "surface_kind": "popup_menu"},
    }
    host = _map_host(
        _Registry(), data,
        SimpleNamespace(expected_destinations=lambda *_a: ["home_menu"]),
        SimpleNamespace())
    host.perception.use_semantic_inventory = True
    host._pending_transition = {
        "source_id": "documents", "clicked_label": "More options"}
    monkeypatch.setattr(
        map_guided, "confirm_arrival",
        lambda *_a, **_k: ("home_menu", "same shared menu"))

    assert registration._try_map_guided(host, b"documents-menu") == \
        (None, None, None)
    assert host._map_guided_preferred_state == "home_menu"


def test_candidate_payloads_deduplicate_registered_variant(tmp_path):
    from gui_rewalk.src.core.visual_traversal.state.map_guided import \
        candidate_payloads

    registry = _Registry()
    registry.variant_id_of = lambda sid: {
        "a": "shared", "a-copy": "shared", "b": "other"}[sid]
    payloads = candidate_payloads(
        ["a", "a-copy", "b"], registry,
        lambda sid: {"name": "Same" if sid != "b" else "Other"},
        page_name="Same")
    assert [item["sid"] for item in payloads] == ["a", "b"]


def test_global_fallback_skips_duplicate_variant_round():
    registry = _Registry()
    registry.variant_id_of = lambda _sid: "shared"
    calls = []
    judge = SimpleNamespace(
        last_reason="no match",
        which_page=lambda _shot, candidates, **_kwargs:
        calls.append([item["sid"] for item in candidates]) or "NEW",
    )
    state_id, reason = confirm_arrival(
        {}, registry, None, ["a"], b"shot", judge,
        lambda _sid: {"name": "Same"},
        current_observation={"page": "Same"},
        fallback_candidate_ids=["a", "a-copy"])
    assert state_id is None
    assert calls == [["a"]]
    assert reason.startswith("vlm:NEW:")


@pytest.mark.parametrize("raises", [False, True])
def test_pending_transition_is_scoped_and_restored(raises):
    seen = []
    host = SimpleNamespace(_pending_transition={"prior": True})
    def register(*_args):
        seen.append(dict(host._pending_transition))
        if raises:
            raise RuntimeError("boom")
        return "sid", False
    host._register = register
    if raises:
        with pytest.raises(RuntimeError):
            register_landing(host, {}, [], [], {"source_id": "s"})
    else:
        assert register_landing(
            host, {}, [], [], {"source_id": "s"}).state_id == "sid"
    assert seen == [{"source_id": "s"}]
    assert host._pending_transition == {"prior": True}


def test_landing_carries_fresh_elements_separately_from_node_history():
    fresh = _element("Live switch")
    fresh.state_key = "setting.enabled"
    fresh.state_value = "on"
    host = SimpleNamespace()

    def register(*_args):
        host._last_live_observation_elements = [fresh]
        return "old-node", False

    host._register = register
    result = register_landing(host, {}, [], [], {"source_id": "old-node"})

    assert result.observation_fresh is True
    assert result.live_elements == [fresh]


def test_source_local_occurrence_reuses_page_but_forces_new_state():
    from gui_rewalk.src.core.visual_traversal.state import registration

    live = _element("Visible app")
    host = SimpleNamespace(
        _pending_transition={
            "source_id": "storage-apps",
            "clicked_label": "Search",
            "force_new_occurrence": True,
            "matched_page_state_id": "all-apps-search",
        },
        _state_data={
            "storage-apps": {"page_id": "page-storage-apps"},
            "all-apps-search": {"page_id": "page-search"},
        },
        router=SimpleNamespace(
            expected_destinations=lambda *_args: ["all-apps-search"]),
        page_judge=SimpleNamespace(
            which_page=lambda *_args, **_kwargs:
            pytest.fail("page identity should not run twice")),
        registry=SimpleNamespace(),
        review_debug=_Debug(),
        _map_guided_bypass_once=False,
        perception=SimpleNamespace(use_semantic_inventory=True),
    )

    fast, arrival, names = registration._try_map_guided(
        host, b"same-search", arrival_elements=[live],
        current_observation={"name": "Search", "targets": ["Visible app"]})

    assert fast is None
    assert arrival == [live]
    assert names == ["Visible app"]
    assert host._map_guided_preferred_state is None
    assert host._map_guided_force_new is True
    assert host._map_guided_occurrence_page_state == "all-apps-search"


def test_verified_return_refreshes_live_registration_before_reconcile():
    calls = []
    host = SimpleNamespace(
        _state_data={
            "target": {"path": [{"target": 1}], "replay_hints": [None]},
        },
        _register=lambda obs, path, hints: (
            calls.append((obs, path, hints)) or ("target", False)),
    )

    state_id, path, hints = _refresh_verified_return_landing(
        host, {"screenshot": b"restored"}, "target")

    assert state_id == "target"
    assert path == [{"target": 1}]
    assert hints == [None]
    assert calls == [(
        {"screenshot": b"restored"}, [{"target": 1}], [None])]


def test_failed_return_refresh_discards_stale_reconcile_evidence():
    def fail_register(*_args):
        raise PerceptionUnavailable("temporary VLM failure")

    host = SimpleNamespace(
        _state_data={"target": {"path": [], "replay_hints": []}},
        _register=fail_register,
        _last_arrival_rset={"stale-root"},
        _last_arrival_names=["stale"],
        _last_arrival_page_name="Stale root",
    )

    assert _refresh_verified_return_landing(
        host, {"screenshot": b"restored"}, "target") == (
            "target", [], [])
    assert host._last_arrival_rset == set()
    assert host._last_arrival_names == []
    assert host._last_arrival_page_name == ""


def test_return_restore_failure_continues_from_known_actual_landing():
    host = SimpleNamespace(
        _state_data={
            "actual": {"path": [{"actual": 1}], "replay_hints": [None]},
        },
        _route_blocked_targets=set(),
    )
    result = SimpleNamespace(
        action_dispatched=True, landed_id="actual",
        failure_kind="target_restore_failed",
    )

    assert _known_return_failure_landing(host, result, "target") == (
        "actual", [{"actual": 1}], [None])
    assert host._route_blocked_targets == {"target"}


def test_unknown_return_failure_still_fails_closed():
    host = SimpleNamespace(_state_data={}, _route_blocked_targets=set())
    result = SimpleNamespace(
        action_dispatched=True, landed_id=None,
        failure_kind="return_identity_unknown",
    )

    assert _known_return_failure_landing(host, result, "target") is None
    assert host._route_blocked_targets == set()


def test_unattempted_return_probe_stays_on_known_target():
    host = SimpleNamespace(
        _state_data={"target": {"path": [], "replay_hints": []}},
        _route_blocked_targets=set(),
    )
    result = SimpleNamespace(
        action_dispatched=False, landed_id="target",
        failure_kind="return_control_not_attempted",
    )

    assert _known_return_failure_landing(host, result, "target") == (
        "target", [], [])
    assert host._route_blocked_targets == set()


def test_landing_outcome_clears_marker_for_noninherited_current_state():
    host = SimpleNamespace(
        _map_guided_inherited={"state_id": "fast-target"})
    _clear_stale_inherited_marker(host, "source")
    assert host._map_guided_inherited is None

    host._map_guided_inherited = {"state_id": "fast-target"}
    _clear_stale_inherited_marker(host, "fast-target")
    assert host._map_guided_inherited == {"state_id": "fast-target"}


@pytest.mark.parametrize("scroll_steps", [0, 1])
def test_inherited_target_failure_recovers_before_retire(scroll_steps):
    elem = _element("Network Proxy")
    elem.scroll_steps = scroll_steps
    plan = CandidateContext(
        element=elem, decision_reason="test", is_seed=False,
        is_stateful=False, is_restore=False, mutation_id="",
        stateful_evidence={}, active_mutation=None, pre_click_id=None)
    debug = _Debug(); registrations = []; failures = []
    host = SimpleNamespace(
        _map_guided_inherited={"state_id": "old"},
        _map_guided_bypass_once=False,
        _live_center_for=lambda *_a: None,
        _retire_live_noninteractive_reclassification=lambda *_a: pytest.fail(
            "historical inherited element retired before identity recovery"),
        _register=lambda obs, path, hints: (
            registrations.append((obs, path, hints)) or ("corrected", False)),
        _state_data={"corrected": {"path": [{"fixed": 1}],
                                   "replay_hints": [{"hint": 1}]}},
        _record_click_failure=lambda *_a: failures.append(1),
        _maybe_save=lambda: None, review_debug=debug, _is_touch=False,
    )
    cursor = RunCursor("old", {"screenshot": b"shot"}, [{"old": 1}], [])
    outcome = execute_candidate(host, cursor, plan)
    assert outcome.directive == StageDirective.CONTINUE
    assert outcome.cursor.state_id == "corrected"
    assert outcome.cursor.path == [{"fixed": 1}]
    assert len(registrations) == 1
    assert failures == []
    assert host._map_guided_inherited is None


def test_identity_resolver_target_failure_uses_bounded_retry_not_registration():
    elem = _element("Menu icon")
    plan = CandidateContext(
        element=elem, decision_reason="test", is_seed=False,
        is_stateful=False, is_restore=False, mutation_id="",
        stateful_evidence={}, active_mutation=None, pre_click_id=None)
    failures = []
    host = SimpleNamespace(
        _map_guided_inherited={"state_id": "calendar"},
        _map_guided_bypass_once=False,
        perception=SimpleNamespace(use_semantic_inventory=True),
        identity_resolver=object(),
        _live_center_for=lambda *_a: None,
        _retire_live_noninteractive_reclassification=lambda *_a: False,
        _register=lambda *_a: pytest.fail(
            "a confirmed Page must not be registered again after grounding "
            "failure"),
        _state_data={},
        _record_click_failure=lambda *_a: (
            failures.append(1) or len(failures)),
        _maybe_save=lambda: None, review_debug=_Debug(), _is_touch=False,
    )
    cursor = RunCursor("calendar", {"screenshot": b"shot"}, [], [])

    for _attempt in range(3):
        outcome = execute_candidate(host, cursor, plan)
        assert outcome.directive == StageDirective.CONTINUE
        cursor = outcome.cursor

    assert len(failures) == 3
    assert host._map_guided_inherited is None


def test_failed_forced_registration_records_one_failure_per_scheduled_attempt():
    elem = _element("Missing")
    plan = CandidateContext(
        element=elem, decision_reason="test", is_seed=False,
        is_stateful=False, is_restore=False, mutation_id="",
        stateful_evidence={}, active_mutation=None, pre_click_id=None)
    registrations = []; failures = []
    def fail_register(*_args):
        registrations.append(1)
        raise RuntimeError("offline failure")
    host = SimpleNamespace(
        _map_guided_inherited={"state_id": "old"},
        _map_guided_bypass_once=False,
        _live_center_for=lambda *_a: None,
        _retire_live_noninteractive_reclassification=lambda *_a: False,
        _register=fail_register, _state_data={},
        _record_click_failure=lambda *_a: failures.append(1),
        _maybe_save=lambda: None, review_debug=_Debug(), _is_touch=False,
    )
    cursor = RunCursor("old", {"screenshot": b"shot"}, [], [])
    first = execute_candidate(host, cursor, plan)
    second = execute_candidate(host, first.cursor, plan)
    assert first.directive == second.directive == StageDirective.CONTINUE
    assert len(registrations) == 1
    assert len(failures) == 2
    assert host._map_guided_inherited is None


def test_visible_target_rebind_failure_returns_to_scheduler_with_history():
    elem = _element("Settings")
    plan = CandidateContext(
        element=elem, decision_reason="test", is_seed=False,
        is_stateful=False, is_restore=False, mutation_id="",
        stateful_evidence={}, active_mutation=None, pre_click_id="settings",
        action={"action_type": "CLICK"}, targeted=True)
    failures = []

    class Env:
        def step(self, _action, pause=None):
            pytest.fail("an ungrounded target must not be clicked")

    host = SimpleNamespace(
        _map_guided_inherited=None, _is_touch=False,
        _live_center_for=lambda *_a: None,
        _retire_live_noninteractive_reclassification=lambda *_a: False,
        _record_click_failure=lambda *_a: failures.append(1) or len(failures),
        _verify_navigation_effect=False, review_debug=_Debug(),
        _edge_label=lambda *_a: "Settings",
        _portable_graph_action=lambda action, _elem: action,
        _stateful_edge_label=lambda _elem: "",
        _stateful_inflight=None, _action_count=0,
        graph=SimpleNamespace(), _settle_enabled=False,
        _ensure_on_app=lambda obs: (obs, False, True),
        env=Env(), _maybe_save=lambda: None,
    )

    outcome = execute_candidate(
        host, RunCursor("settings", {"screenshot": b"before"}), plan)

    assert outcome.directive is StageDirective.CONTINUE
    assert failures == [1]


def test_registration_scoped_preferred_does_not_leak_between_landings(monkeypatch):
    from gui_rewalk.src.core.visual_traversal.state import registration

    observed = {}
    host = SimpleNamespace(
        perception=SimpleNamespace(
            use_semantic_inventory=True, last_page_name="Clock"),
        _registration_preferred_state_once="clock",
        _map_guided_preferred_state="stale-dialog",
        _map_guided_force_new=True,
    )
    monkeypatch.setattr(
        registration, "_semantic_inventory_for_landing",
        lambda _host, _shot: ["live"])

    def try_identity(current, _shot, **_kwargs):
        observed["preferred_before_identity"] = (
            current._map_guided_preferred_state)
        return None, None, None

    def register_semantic(current, *_args, **_kwargs):
        observed["preferred_at_registration"] = (
            current._map_guided_preferred_state)
        return "clock", False

    monkeypatch.setattr(registration, "_try_map_guided", try_identity)
    monkeypatch.setattr(
        registration, "_register_semantic_observation", register_semantic)

    assert registration.register_observation(
        host, {"screenshot": b"current"}, []) == ("clock", False)
    assert observed == {
        "preferred_before_identity": "clock",
        "preferred_at_registration": "clock",
    }
    assert not hasattr(host, "_registration_preferred_state_once")


def test_known_fixture_revisit_keeps_registered_readable_name(monkeypatch):
    """A coarse live fixture label must not rename an identified old node."""
    host = SimpleNamespace(
        _state_data={"menu": {"page_name": "Workspace Menu Overlay"}},
        perception=SimpleNamespace(last_page_name="Home"),
        _map_guided_preferred_state="menu",
    )

    assert registration._preferred_page_name(host, "Home") == (
        "Workspace Menu Overlay")
