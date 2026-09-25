from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from gui_rewalk.src.core.visual_traversal.agents.explorer import ExplorerAgent
from gui_rewalk.src.core.visual_traversal.agents.identity import BlockIdentityJudge
from gui_rewalk.src.core.visual_traversal.runtime.contracts import (
    RunCursor, StageDirective,
)
from gui_rewalk.src.core.visual_traversal.runtime.scheduling import (
    MAX_EXPLORER_REGION_FAILURES,
    _apply_verified_reverse_control_coverage,
    _apply_verified_stable_control_coverage,
    _qwen_frontier_choice,
    _stable_control_binding,
    available_unvisited_candidates,
    plan_candidate,
    schedule_frontier,
)
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement
from gui_rewalk.src.core.visual_traversal.action_space import (
    normalize_native_action,
)


def _png(width=100, height=200):
    stream = BytesIO()
    Image.new("RGB", (width, height), "white").save(stream, format="PNG")
    return stream.getvalue()


def test_block_identity_uses_prompt_local_choice(monkeypatch):
    captured = {}
    def predict(_agent, role, prompt, images, _ledger, **_kwargs):
        captured.update(role=role, prompt=prompt, images=images)
        return ('{"same_regions":[{"same_region":"S1",'
                '"interface_a_region":"A1","interface_b_region":"B1"}],'
                '"interface_a_final_regions":["S1"],'
                '"interface_b_final_regions":["S1"]}'), None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    choice = BlockIdentityJudge(object()).align_regions(
        "Clock", [{"region": "A1", "contains": ["More options"]}],
        "Alarm", [{"region": "B1", "contains": ["More options"]}],
    )
    assert choice["same_regions"] == [{
        "same_region": "S1",
        "interface_a_region": "A1",
        "interface_b_region": "B1",
    }]
    assert captured["role"] == "region_identity"
    assert captured["images"] == []
    assert "预计在同一界面状态下共同呈现" in captured["prompt"]
    assert "directly interactive" not in captured["prompt"]
    assert "局部文字或目标重合不足以建立对应" in captured["prompt"]
    assert "即使区块只包含一个目标" in captured["prompt"]
    assert "current block" not in captured["prompt"]


@pytest.mark.skip(reason="superseded by *_region_ids mapping contract")
def test_region_partition_mapping_accepts_set_to_set_cardinality(monkeypatch):
    def predict(_agent, role, prompt, images, _ledger, **_kwargs):
        assert role == "region_partition_mapping"
        assert images == []
        assert "一对多、多对一或多对多" in prompt
        return (
            '{"matches":['
            '{"known_regions":["A1"],"current_regions":["B1","B2"]},'
            '{"known_regions":["A2","A3"],"current_regions":["B3"]}],'
            '"new_current_regions":["B4"],'
            '"unresolved_current_regions":["B5"]}',
            None,
        )

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    result = BlockIdentityJudge(object()).align_region_partitions(
        "old",
        [{"region": "A1"}, {"region": "A2"}, {"region": "A3"}],
        "new",
        [{"region": f"B{index}"} for index in range(1, 6)],
    )

    assert result["matches"][0]["current_regions"] == ["B1", "B2"]
    assert result["matches"][1]["known_regions"] == ["A2", "A3"]
    assert result["new_current_regions"] == ["B4"]
    assert result["unresolved_current_regions"] == ["B5"]


@pytest.mark.skip(reason="superseded by *_region_ids mapping contract")
def test_region_partition_mapping_receives_frames_and_trigger_action(
        monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.identity._img_arr",
        lambda value: f"image:{value.decode()}")

    def predict(_agent, role, prompt, images, _ledger, **_kwargs):
        captured.update(role=role, prompt=prompt, images=images)
        return (
            '{"matches":[],"new_current_regions":["B1"],'
            '"unresolved_current_regions":[]}',
            None,
        )

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    result = BlockIdentityJudge(object()).align_region_partitions(
        "Alarms",
        [{"region": "A1", "name": "Top Navigation"}],
        "New Alarm",
        [{"region": "B1", "name": "Dialog Header"}],
        [b"before", b"after"],
        "Add Alarm",
    )

    assert result["new_current_regions"] == ["B1"]
    assert captured["images"] == ["image:before", "image:after"]
    assert "图 1 对应界面 A，图 2 对应界面 B" in captured["prompt"]
    assert "Add Alarm" in captured["prompt"]
    assert "哪些可见容器或内容身份" in captured["prompt"]
    assert "候选范围是本次映射的权威范围" in captured["prompt"]
    assert "仅作为不可操作背景可见不属于持续存在" in captured["prompt"]
    assert "只有持续存在的 A 区块才能进入 match" in captured["prompt"]
    assert "不表示旧容器消失后由相似角色的新容器接替" in (
        captured["prompt"])
    assert "不单独证明容器身份延续" in captured["prompt"]


@pytest.mark.skip(reason="superseded by selected_entry_id Explorer contract")
def test_explorer_uses_compact_click_only_prompt_without_internal_region_id(
        monkeypatch):
    replies = iter([
        '{"covered":[],"semantic_only":[],"next_action":'
        '{"action_type":"click","choice_id":"c0",'
        '"reason":"It may open a functional interface."}}',
        '{"covered":[],"semantic_only":[],"next_action":'
        '{"action_type":"CLICK","choice_id":"c0",'
        '"reason":"It may open a functional interface."}}',
    ])
    prompts = []
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value)

    def predict(_agent, _role, prompt, _images, _ledger, **_kwargs):
        prompts.append(prompt)
        return next(replies), None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    explorer = ExplorerAgent(object())
    context = {
        "application_name": "Clock",
        "current_interface": "Alarm",
        "region_name": "Top app bar",
        "region_description": "top_app_bar",
        "pending_buttons": [{
            "choice_id": "c0", "name": "Settings", "attempts": [],
            "failures": [{
                "failure_kind": "visible_target_not_confirmed",
                "attempts": 1,
            }],
        }],
        "verified_buttons": [],
        "shared_verified_buttons": [{
            "verified_id": "v0", "name": "Home",
            "source_interface": "Documents",
            "attempts": [{
                "action": {"action_type": "CLICK"},
                "outcome": "success", "actual_result": "Home",
                "verified": True,
            }],
        }],
    }
    mobile = explorer.choose(b"screen", context, platform="android")
    desktop = explorer.choose(b"screen", context, platform="desktop")
    assert mobile["next_action"]["action"] == {"action_type": "click"}
    assert mobile["next_action"]["choice_id"] == "c0"
    assert desktop["next_action"]["action"] == {
        "action_type": "CLICK", "parameters": {}}
    assert "应用：Clock" in prompts[0]
    assert "当前 Region：Top app bar" in prompts[0]
    assert "r0" not in prompts[0]
    assert "本轮可执行动作只有 click" in prompts[0]
    assert "只让控件准备接受后续非 click 动作" in prompts[0]
    assert "Home on Documents; CLICK -> Home (verified)" in prompts[0]
    assert "这些结果都可作为 covered 的代表" in prompts[0]
    assert "所有其他参数值或数据实例统一归入 covered" in prompts[0]
    assert "next_action 只从尚无此类代表" in prompts[0]
    assert "文字、位置或同属一个 Region 只提供上下文" in prompts[0]
    assert "visible target not confirmed × 1" in prompts[0]
    assert "历史失败不阻止当前截图支持的重试" in prompts[0]
    assert "open_app" not in prompts[0]
    assert "DRAG_TO" not in prompts[1]
    assert "RIGHT_CLICK" not in prompts[1]
    assert "{\"attempts\"" not in prompts[0]


@pytest.mark.skip(reason="Explorer no longer makes coverage decisions")
def test_explorer_accepts_reviewed_shared_region_coverage(monkeypatch):
    replies = iter([
        '{"covered":[{"choice_ids":["c0"],"by_verified":"v0",'
        '"reason":"The other entry has the same verified result."}],'
        '"semantic_only":[],"next_action":null}',
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: (next(replies), None))
    reviewer_calls = []

    def review(_shot, context):
        reviewer_calls.append(context)
        return {"verdict": "same_result", "reason": "same verified result"}

    explorer = ExplorerAgent(
        object(), coverage_reviewer=review)
    decision = explorer.choose(b"screen", {
        "application_name": "Mingle",
        "current_interface": "Contacts",
        "region_description": "primary navigation",
        "pending_buttons": [{
            "choice_id": "c0", "name": "Explore",
            "category": "navigation", "attempts": [],
        }],
        "verified_buttons": [],
        "shared_verified_buttons": [{
            "verified_id": "v0", "name": "Explore",
            "category": "navigation", "source_interface": "Chats",
            "attempts": [{
                "outcome": "success", "actual_result": "Explore",
                "verified": True,
            }],
        }],
    }, platform="desktop")

    assert decision["covered"] == [{
        "choice_ids": ["c0"],
        "by_verified": "v0",
        "reason": "The other entry has the same verified result.",
    }]
    assert decision["next_action"] is None
    assert reviewer_calls[0]["representative_actual_results"] == ["Explore"]


@pytest.mark.skip(reason="Explorer no longer makes coverage decisions")
def test_explorer_repairs_same_source_navigation_coverage_rejected_by_observer(
        monkeypatch):
    replies = iter([
        '{"covered":[{"choice_ids":["c0"],"by_verified":"v0",'
        '"reason":"Both controls are in the same navigation bar."}],'
        '"semantic_only":[],"next_action":null}',
        '{"covered":[],"semantic_only":[],"next_action":'
        '{"action_type":"CLICK","choice_id":"c0",'
        '"reason":"The destinations differ and this control needs execution."}}',
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: (next(replies), None))
    reviewed = []

    def review(_shot, context):
        reviewed.append(context)
        return {
            "verdict": "different_result",
            "reason": "Contacts and Me identify different destinations",
        }

    explorer = ExplorerAgent(object(), coverage_reviewer=review)
    decision = explorer.choose(b"screen", {
        "application_name": "Mingle",
        "current_interface": "Chats",
        "region_description": "primary navigation",
        "pending_buttons": [{
            "choice_id": "c0", "name": "Me",
            "category": "navigation", "attempts": [],
        }],
        "verified_buttons": [{
            "verified_id": "v0", "choice_id": "",
            "name": "Contacts", "category": "navigation",
            "attempts": [{
                "outcome": "success", "actual_result": "Contacts",
                "verified": True,
            }],
        }],
        "shared_verified_buttons": [],
    }, platform="desktop")

    assert decision["covered"] == []
    assert decision["next_action"]["choice_id"] == "c0"
    assert reviewed[0]["pending_control"] == "Me"
    assert reviewed[0]["representative_actual_results"] == ["Contacts"]


@pytest.mark.skip(reason="Explorer now returns only selected_entry_id")
def test_explorer_requires_reasons_and_uses_focused_repair(monkeypatch):
    replies = iter([
        '{"covered":[],"semantic_only":[{"choice_id":"c1",'
        '"reason":"Its familiar formatting semantics are sufficient."}],'
        '"next_action":{"action_type":"CLICK","choice_id":"c0",'
        '"reason":""}}',
        '{"covered":[],"semantic_only":[],"next_action":'
        '{"action_type":"CLICK","choice_id":"c0",'
        '"reason":"It may open a separate information interface."}}',
    ])
    calls = []
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value)

    def predict(_agent, role, prompt, images, _ledger, **kwargs):
        calls.append((role, prompt, images, kwargs))
        return next(replies), None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    context = {
        "application_name": "Dayline",
        "current_interface": "Workspace menu",
        "pending_buttons": [
            {"choice_id": "c0", "name": "About Dayline", "attempts": []},
            {"choice_id": "c1", "name": "Bold", "attempts": []},
        ],
        "verified_buttons": [{
            "verified_id": "v0", "choice_id": "",
            "name": "Settings", "attempts": [{
                "action": {"action_type": "CLICK"},
                "outcome": "success", "actual_result": "Settings",
                "verified": True,
            }],
        }],
    }
    explorer = ExplorerAgent(object())

    decision = explorer.choose(
        b"MENU", context, platform="desktop")

    assert decision["semantic_only"] == [{
        "choice_id": "c1",
        "reason": "Its familiar formatting semantics are sufficient.",
    }]
    assert decision["next_action"]["choice_id"] == "c0"
    assert decision["next_action"]["reason"].startswith("It may open")
    assert len(calls) == 2
    assert calls[0][1] != calls[1][1]
    assert calls[0][2] == calls[1][2]
    assert calls[1][3]["use_response_cache"] is False
    assert "next_action is missing a reason" in calls[1][1]
    assert "c0: About Dayline" in calls[1][1]
    assert "c1: Bold" not in calls[1][1]
    assert "v0: Settings; CLICK -> Settings (verified)" in calls[1][1]
    assert len(explorer.last_raw_responses) == 2


@pytest.mark.skip(reason="Explorer now returns only selected_entry_id")
def test_explorer_rejects_done_and_finished_fields_then_repairs(monkeypatch):
    replies = iter([
        '{"decision":"DONE","finished_buttons":["c0"],'
        '"covered":[],"semantic_only":[],"next_action":null}',
        '{"covered":[],"semantic_only":[{"choice_id":"c0",'
        '"reason":"The visible command has complete familiar semantics and '
        'does not expose another interface."}],"next_action":null}',
    ])
    prompts = []
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value)

    def predict(_agent, _role, prompt, _images, _ledger, **_kwargs):
        prompts.append(prompt)
        return next(replies), None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    decision = ExplorerAgent(object()).choose(
        b"screen", {
            "pending_buttons": [{
                "choice_id": "c0", "name": "Bold", "attempts": []}],
            "verified_buttons": [],
        }, platform="desktop")

    assert decision["semantic_only"][0]["choice_id"] == "c0"
    assert decision["next_action"] is None
    assert "finished_buttons is unavailable" in prompts[1]
    assert "Do not return EXECUTE or DONE" in prompts[1]


@pytest.mark.skip(reason="Explorer no longer makes coverage decisions")
def test_explorer_covered_requires_a_different_verified_button(monkeypatch):
    replies = iter([
        '{"covered":[{"choice_ids":["c0"],"by_verified":"v0",'
        '"reason":"Same button."}],"semantic_only":[],"next_action":null}',
        '{"covered":[],"semantic_only":[],"next_action":'
        '{"action_type":"CLICK","choice_id":"c0",'
        '"reason":"It still needs a real result."}}',
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value)

    def predict(_agent, _role, _prompt, _images, _ledger, **_kwargs):
        return next(replies), None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    decision = ExplorerAgent(object()).choose(
        b"screen", {
            "pending_buttons": [{
                "choice_id": "c0", "name": "Open", "attempts": []}],
            "verified_buttons": [{
                "verified_id": "v0", "choice_id": "c0", "name": "Open",
                "attempts": [{"verified": True}],
            }],
        }, platform="desktop")

    assert decision["covered"] == []
    assert decision["next_action"]["choice_id"] == "c0"


@pytest.mark.skip(reason="Explorer no longer makes coverage decisions")
def test_explorer_keeps_valid_action_when_coverage_reference_is_invalid(
        monkeypatch):
    calls = []
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value)

    def predict(_agent, _role, _prompt, _images, _ledger, **_kwargs):
        calls.append(True)
        return (
            '{"covered":[{"choice_ids":["c1"],'
            '"by_verified":"v_invented","reason":"Same result."}],'
            '"semantic_only":[],"next_action":{"action_type":"click",'
            '"choice_id":"c0","reason":"It may reveal another interface."}}'
        ), None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    explorer = ExplorerAgent(object())
    decision = explorer.choose(
        b"screen", {
            "pending_buttons": [
                {"choice_id": "c0", "name": "Add attachment", "attempts": []},
                {"choice_id": "c1", "name": "Message", "attempts": []},
            ],
            "verified_buttons": [],
        }, platform="android")

    assert decision["covered"] == []
    assert decision["next_action"]["choice_id"] == "c0"
    assert "unknown verified_id" in explorer.last_reason
    assert len(calls) == 1


@pytest.mark.skip(reason="superseded by selected_entry_id Explorer contract")
def test_explorer_uses_final_json_when_model_revises_a_fenced_draft(
        monkeypatch):
    calls = []
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value)

    def predict(_agent, _role, _prompt, _images, _ledger, **_kwargs):
        calls.append(True)
        return (
            '```json\n'
            '{"covered":[{"choice_ids":["c1"],"by_verified":"v0",'
            '"reason":"Same pattern."}],"semantic_only":[],'
            '"next_action":{"action_type":"click","choice_id":"c1",'
            '"reason":"Open it."}}\n'
            '```\n'
            'That draft was wrong because the results differ.\n'
            '```json\n'
            '{"covered":[],"semantic_only":[{"choice_id":"c0",'
            '"reason":"It returns to a known interface."}],'
            '"next_action":{"action_type":"click","choice_id":"c1",'
            '"reason":"Open the distinct interface."}}\n'
            '```'
        ), None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    explorer = ExplorerAgent(object())
    decision = explorer.choose(
        b"screen", {
            "pending_buttons": [
                {
                    "choice_id": "c0", "name": "Back",
                    "category": "navigation", "selected": False,
                    "attempts": [],
                },
                {
                    "choice_id": "c1", "name": "Screen saver",
                    "category": "navigation", "selected": False,
                    "attempts": [],
                },
            ],
            "verified_buttons": [{
                "verified_id": "v0", "choice_id": "", "name": "Lock screen",
                "attempts": [{"verified": True}],
            }],
        }, platform="android")

    assert decision["covered"] == []
    assert decision["semantic_only"] == [{
        "choice_id": "c0",
        "reason": "It returns to a known interface.",
    }]
    assert decision["next_action"]["choice_id"] == "c1"
    assert len(calls) == 1


@pytest.mark.skip(reason="Explorer no longer makes coverage decisions")
def test_explorer_accepts_model_coverage_across_inventory_labels(monkeypatch):
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: (
            '{"covered":[{"choice_ids":["c0"],"by_verified":"v0",'
            '"reason":"The verified result establishes the same function."}],'
            '"semantic_only":[],"next_action":null}', None))
    decision = ExplorerAgent(object()).choose(
        b"screen", {
            "pending_buttons": [{
                "choice_id": "c0", "name": "Me",
                "category": "navigation", "group": "", "attempts": [],
            }],
            "verified_buttons": [{
                "verified_id": "v0", "choice_id": "", "name": "Contacts",
                "category": "navigation", "group": "", "attempts": [{
                    "verified": True,
                }],
            }],
        }, platform="android")

    assert decision["covered"][0]["choice_ids"] == ["c0"]
    assert decision["next_action"] is None


@pytest.mark.skip(reason="Explorer no longer makes coverage decisions")
def test_explorer_accepts_coverage_for_same_repeated_content_group(monkeypatch):
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: (
            '{"covered":[{"choice_ids":["c0"],"by_verified":"v0",'
            '"reason":"Both open another instance of the same detail template."}],'
            '"semantic_only":[],"next_action":null}', None))
    decision = ExplorerAgent(object()).choose(
        b"screen", {
            "pending_buttons": [{
                "choice_id": "c0", "name": "Open Alex",
                "category": "navigation", "group": "conversation", "attempts": [],
            }],
            "verified_buttons": [{
                "verified_id": "v0", "choice_id": "", "name": "Open Mira",
                "category": "navigation", "group": "conversation",
                "attempts": [{"verified": True}],
            }],
        }, platform="android")

    assert decision["covered"][0]["choice_ids"] == ["c0"]
    assert decision["next_action"] is None


@pytest.mark.skip(reason="Explorer no longer returns semantic_only")
def test_explorer_accepts_selected_navigation_as_semantic_only(monkeypatch):
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: (
            '{"covered":[],"semantic_only":[{"choice_id":"c0",'
            '"reason":"It is visibly selected and would only reselect the current '
            'interface."}],"next_action":null}', None))
    decision = ExplorerAgent(object()).choose(
        b"screen", {"pending_buttons": [{
            "choice_id": "c0", "name": "Current", "category": "navigation",
            "group": "", "selected": True, "attempts": [],
        }], "verified_buttons": []}, platform="android")

    assert decision["semantic_only"][0]["choice_id"] == "c0"
    assert decision["next_action"] is None


@pytest.mark.skip(reason="Explorer no longer returns semantic_only")
def test_explorer_can_accept_unselected_control_as_semantic_only(monkeypatch):
    replies = iter([
        '{"covered":[],"semantic_only":[{"choice_id":"c0",'
        '"reason":"The profile label is familiar."}],"next_action":null}',
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value)
    prompts = []

    def predict(_agent, _role, prompt, _images, _ledger, **_kwargs):
        prompts.append(prompt)
        return next(replies), None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    decision = ExplorerAgent(object()).choose(
        b"screen", {"pending_buttons": [{
            "choice_id": "c0", "name": "Me", "category": "navigation",
            "group": "", "selected": False, "attempts": [],
        }], "verified_buttons": []}, platform="android")

    assert decision["semantic_only"] == [{
        "choice_id": "c0",
        "reason": "The profile label is familiar.",
    }]
    assert decision["next_action"] is None
    assert len(prompts) == 1
    assert "category=navigation" not in prompts[0]


def test_native_action_contract_rejects_cross_platform_or_invalid_actions():
    mobile, error = normalize_native_action(
        {"action_type": "open_app", "app_name": "Clock"},
        platform="android")
    assert error == ""
    assert mobile == {"action_type": "open_app", "app_name": "Clock"}

    invalid_mobile, error = normalize_native_action(
        {"action_type": "swipe", "direction": "diagonal"},
        platform="android")
    assert invalid_mobile is None
    assert error == "invalid direction"

    desktop, error = normalize_native_action(
        {"action_type": "HOTKEY", "parameters": {"keys": ["ctrl", "s"]}},
        platform="desktop")
    assert error == ""
    assert desktop["action_type"] == "HOTKEY"

    cross_platform, error = normalize_native_action(
        {"action_type": "navigate_back"}, platform="desktop")
    assert cross_platform is None
    assert error == "invalid platform action"


@pytest.mark.skip(reason="Explorer no longer returns classifications")
def test_framework_computes_region_completion_from_classifications():
    element = SimpleNamespace(
        id=3, name="Settings", region="toolbar", region_id="r1",
        visited=False, abnormal_reason="", abnormal_detail="",
        exploration_status="", covered_by="")
    records = []
    persisted = []
    host = SimpleNamespace(
        _is_touch=False,
        explorer=SimpleNamespace(choose=lambda *_args, **_kwargs: {
            "semantic_only": [{
                "choice_id": "c0", "reason": "Visible semantics suffice."}],
            "covered": [], "next_action": None}),
        graph=SimpleNamespace(action_edges=[]),
        app_name="Clock",
        _state_data={"state": {"page_name": "Home", "elements": [element]}},
        _action_count=0,
        review_debug=SimpleNamespace(
            record_agent=lambda *args, **kwargs: records.append((args, kwargs))),
        _persist_exploration_state=lambda state_id: persisted.append(
            (state_id, element.exploration_status)),
    )
    outcome = plan_candidate(
        host, RunCursor("state", {"screenshot": b"screen"}), [element])
    assert outcome.directive is StageDirective.CONTINUE
    assert outcome.candidate is None
    assert element.visited is True
    assert element.exploration_status == "semantic_only"
    assert element.abnormal_reason == ""
    assert records
    assert persisted == [("state", "semantic_only")]


def test_verified_click_auto_completes_without_calling_explorer():
    element = VisualElement(
        1, "About Dayline", [0, 0, 1, 1], [1, 1],
        region="menu", region_id="r1")
    graph = SimpleNamespace(action_edges=[{
        "source": "menu", "element_id": "1",
        "action": {"action_type": "CLICK"},
        "attempts": [{
            "target": "about", "outcome": "success",
            "committed": True, "landing_verified": True,
        }],
    }], stop_reason="")
    persisted = []

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("verified click must not return to Explorer")

    host = SimpleNamespace(
        _is_touch=False, app_name="Dayline",
        explorer=SimpleNamespace(choose=fail_if_called),
        graph=graph,
        _state_data={"menu": {
            "page_name": "Workspace Menu", "elements": [element]}},
        _action_count=0,
        review_debug=SimpleNamespace(
            record_agent=lambda *args, **kwargs: None),
        _persist_exploration_state=lambda state_id: persisted.append(state_id),
    )

    outcome = plan_candidate(
        host, RunCursor("menu", {"screenshot": b"screen"}), [element])

    assert outcome.directive is StageDirective.CONTINUE
    assert element.visited is True
    assert element.exploration_status == "complete"
    assert persisted == ["menu"]


def test_verified_nonstateful_group_folds_to_one_function_template():
    representative = VisualElement(
        1, "Open Mira", [0, 0, 1, 1], [1, 1],
        region="content", region_id="r1", group="conversation")
    peer = VisualElement(
        2, "Open Alex", [0, 0, 1, 1], [2, 2],
        region="content", region_id="r1", group="conversation")
    graph = SimpleNamespace(action_edges=[{
        "source": "inbox", "element_id": "1",
        "action": {"action_type": "CLICK"},
        "attempts": [{
            "target": "detail", "outcome": "success",
            "committed": True, "landing_verified": True,
        }],
    }])
    persisted = []
    host = SimpleNamespace(
        graph=graph,
        _state_data={"inbox": {
            "page_name": "Inbox", "elements": [representative, peer]}},
        _active_state_mutation=None,
        _explorer_deferred_regions=set(),
        _unvisited_candidates=lambda _state_id: [
            element for element in (representative, peer)
            if not element.visited
        ],
        _persist_exploration_state=lambda state_id: persisted.append(state_id),
    )

    assert available_unvisited_candidates(host, "inbox") == []
    assert representative.exploration_status == "complete"
    assert peer.exploration_status == "covered"
    assert peer.covered_by == "1"
    assert peer.covered_by_state == "inbox"
    assert persisted == ["inbox"]


def test_verified_stateful_group_remains_explicit():
    representative = VisualElement(
        1, "30 seconds", [0, 0, 1, 1], [1, 1],
        region="content", region_id="r1", group="timeout",
        stateful=True, state_key="timeout", state_value="30 seconds",
        effect_scope="function_set", reversible=True, risk="none")
    peer = VisualElement(
        2, "1 minute", [0, 0, 1, 1], [2, 2],
        region="content", region_id="r1", group="timeout",
        stateful=True, state_key="timeout", state_value="1 minute",
        effect_scope="function_set", reversible=True, risk="none")
    host = SimpleNamespace(
        graph=SimpleNamespace(action_edges=[{
            "source": "timeout", "element_id": "1",
            "action": {"action_type": "CLICK"},
            "attempts": [{
                "target": "timeout-30", "outcome": "success",
                "committed": True, "landing_verified": True,
            }],
        }]),
        _state_data={"timeout": {"elements": [representative, peer]}},
        _active_state_mutation=None,
        _explorer_deferred_regions=set(),
        _unvisited_candidates=lambda _state_id: [representative, peer],
        _persist_exploration_state=lambda _state_id: (
            (_ for _ in ()).throw(
                AssertionError("stateful alternatives must not be folded"))),
    )

    assert available_unvisited_candidates(host, "timeout") == [
        representative, peer]
    assert representative.exploration_status == ""
    assert peer.exploration_status == ""


@pytest.mark.skip(reason="Explorer no longer makes coverage decisions")
def test_reviewed_shared_region_result_covers_without_forging_attempt():
    current = VisualElement(
        1, "Home", [0, 0, 1, 1], [1, 1],
        region="sidebar", region_id="shared-nav")
    representative = VisualElement(
        9, "Home destination", [0, 0, 1, 1], [1, 1],
        region="sidebar", region_id="shared-nav")
    graph = SimpleNamespace(action_edges=[{
        "source": "settings", "target": "home", "element_id": "9",
        "action": {"action_type": "CLICK"},
        "attempts": [{
            "target": "home", "target_page_name": "Home",
            "outcome": "success", "committed": True,
            "landing_verified": True,
        }],
    }], stop_reason="")
    captured = {}
    persisted = []

    def choose(_shot, context, **_kwargs):
        captured.update(context)
        return {
            "semantic_only": [],
            "covered": [{
                "choice_ids": ["c0"], "by_verified": "v0",
                "reason": "The verified result covers this current button.",
            }],
            "next_action": None,
        }

    host = SimpleNamespace(
        _is_touch=False, app_name="Dayline",
        explorer=SimpleNamespace(choose=choose), graph=graph,
        _state_data={
            "home": {"page_name": "Home", "elements": [current]},
            "settings": {
                "page_name": "Settings", "elements": [representative]},
        },
        _action_count=0,
        review_debug=SimpleNamespace(
            record_agent=lambda *args, **kwargs: None,
            record_event=lambda *args, **kwargs: None),
        _persist_exploration_state=lambda state_id: persisted.append(state_id),
    )

    outcome = plan_candidate(
        host, RunCursor("home", {"screenshot": b"screen"}), [current])

    assert outcome.directive is StageDirective.CONTINUE
    assert captured["verified_buttons"] == []
    assert len(captured["shared_verified_buttons"]) == 1
    assert captured["shared_verified_buttons"][0]["verified_id"] == "v0"
    assert captured["shared_verified_buttons"][0]["source_interface"] == "Settings"
    assert current.exploration_status == "covered"
    assert current.covered_by == "9"
    assert current.covered_by_state == "settings"
    assert current.exploration_reason == (
        "The verified result covers this current button.")
    assert persisted == ["home"]
    assert len(graph.action_edges) == 1, "coverage must not forge a local attempt"


def test_historical_state_work_rebinds_to_same_control_in_mapped_region():
    target = VisualElement(
        1, "Add Alarm", [0, 0, 1, 1], [1, 1],
        region="old wording", region_id="stable-alarm-actions")
    live = VisualElement(
        9, "Add Alarm", [0, 0, 1, 1], [1, 1],
        region="new wording", region_id="stable-alarm-actions")
    host = SimpleNamespace(
        _state_data={
            "historical": {"elements": [target]},
            "live": {"elements": [live]},
        },
        _unvisited_candidates=lambda state_id: (
            [target] if state_id == "historical" else [live]),
    )

    assert _stable_control_binding(
        host, "historical", "live") == (target, live)


def test_historical_state_work_does_not_rebind_an_ambiguous_repeated_label():
    target = VisualElement(
        1, "Edit", [0, 0, 1, 1], [1, 1],
        region="items", region_id="stable-items")
    live_a = VisualElement(
        9, "Edit", [0, 0, 1, 1], [1, 1],
        region="items", region_id="stable-items")
    live_b = VisualElement(
        10, "Edit", [0, 0, 1, 1], [1, 1],
        region="items", region_id="stable-items")
    host = SimpleNamespace(
        _state_data={
            "historical": {"elements": [target]},
            "live": {"elements": [live_a, live_b]},
        },
        _unvisited_candidates=lambda state_id: (
            [target] if state_id == "historical" else [live_a, live_b]),
    )

    assert _stable_control_binding(host, "historical", "live") is None


def test_verified_exact_control_covers_historical_occurrence_after_region_map():
    target = VisualElement(
        1, "Add Alarm", [0, 0, 1, 1], [1, 1],
        region="old wording", region_id="stable-alarm-actions")
    representative = VisualElement(
        9, "Add Alarm", [0, 0, 1, 1], [1, 1],
        region="new wording", region_id="stable-alarm-actions")
    host = SimpleNamespace(
        _state_data={
            "historical": {"elements": [target]},
            "live": {"elements": [representative]},
        },
        _unvisited_candidates=lambda state_id: (
            [target] if state_id == "historical" else []),
        graph=SimpleNamespace(action_edges=[{
            "source": "live", "target": "dialog", "element_id": "9",
            "action": {"action_type": "CLICK"},
            "attempts": [{
                "target": "dialog", "outcome": "success",
                "committed": True, "landing_verified": True,
            }],
        }]),
    )

    assert _apply_verified_stable_control_coverage(
        host, "historical") is True
    assert target.exploration_status == "covered"
    assert target.covered_by_state == "live"
    assert target.covered_by == "9"


def test_verified_reverse_probe_closes_control_discovered_after_probe():
    target = VisualElement(
        1, "World", [0, 0, 1, 1], [1, 1],
        region="tabs", region_id="timer:r0")
    host = SimpleNamespace(
        _state_data={"timer": {"elements": [target]}},
        _unvisited_candidates=lambda _state: (
            [] if target.visited else [target]),
        graph=SimpleNamespace(action_edges=[{
            "source": "timer", "target": "world",
            "element_id": "", "element_label": "World",
            "action": {"action_type": "CLICK"},
            "attempts": [{
                "target": "world", "outcome": "transitioned_consistent",
                "committed": True, "landing_verified": True,
                "evidence": {"reverse_probe": {
                    "status": "verified_to_source",
                }},
            }],
        }]),
    )

    assert _apply_verified_reverse_control_coverage(
        host, "timer") is True
    assert target.exploration_status == "complete"
    assert target.visited is True


@pytest.mark.skip(reason="Explorer no longer receives cross-state coverage")
def test_same_page_named_region_is_not_shared_without_vlm_region_mapping():
    current = VisualElement(
        1, "Add Button", [0, 0, 1, 1], [1, 1],
        region="Top Navigation Bar", region_id="alarm-list:r0")
    representative = VisualElement(
        9, "Add Button", [0, 0, 1, 1], [1, 1],
        region="Top Navigation Bar", region_id="empty-alarm:r0")
    graph = SimpleNamespace(action_edges=[{
        "source": "empty", "target": "dialog", "element_id": "9",
        "action": {"action_type": "CLICK"},
        "attempts": [{
            "target": "dialog", "target_page_name": "New Alarm",
            "outcome": "success", "committed": True,
            "landing_verified": True,
        }],
    }], stop_reason="")
    captured = {}

    def choose(_shot, context, **_kwargs):
        captured.update(context)
        return {
            "semantic_only": [],
            "covered": [{
                "choice_ids": ["c0"], "by_verified": "v0",
                "reason": "Both buttons open the same New Alarm dialog.",
            }],
            "next_action": None,
        }

    host = SimpleNamespace(
        _is_touch=False, app_name="Clock",
        explorer=SimpleNamespace(choose=choose), graph=graph,
        _state_data={
            "list": {
                "page_name": "Clocks - Alarms",
                "page_id": "alarms-page",
                "elements": [current],
            },
            "empty": {
                "page_name": "Clocks - Alarms",
                "page_id": "alarms-page",
                "elements": [representative],
            },
        },
        _action_count=0,
        review_debug=SimpleNamespace(
            record_agent=lambda *args, **kwargs: None,
            record_event=lambda *args, **kwargs: None),
        _persist_exploration_state=lambda _state_id: None,
    )

    outcome = plan_candidate(
        host, RunCursor("list", {"screenshot": b"screen"}), [current])

    assert outcome.directive is StageDirective.CONTINUE
    assert captured["shared_verified_buttons"] == []
    assert current.exploration_status == ""
    assert current.covered_by == ""
    assert current.covered_by_state == ""


@pytest.mark.skip(reason="Explorer no longer receives cross-state coverage")
def test_same_region_name_from_different_page_is_not_shared_without_mapping():
    current = VisualElement(
        1, "Add Button", [0, 0, 1, 1], [1, 1],
        region="Top Navigation Bar", region_id="alarm-list:r0")
    representative = VisualElement(
        9, "Add Button", [0, 0, 1, 1], [1, 1],
        region="Top Navigation Bar", region_id="world:r0")
    captured = {}

    def choose(_shot, context, **_kwargs):
        captured.update(context)
        return {
            "semantic_only": [],
            "covered": [],
            "next_action": {
                "action": {"action_type": "CLICK", "parameters": {}},
                "choice_id": "c0", "reason": "No relevant verified result.",
            },
        }

    host = SimpleNamespace(
        _is_touch=False, app_name="Clock",
        explorer=SimpleNamespace(choose=choose),
        graph=SimpleNamespace(action_edges=[{
            "source": "world", "target": "world-dialog", "element_id": "9",
            "action": {"action_type": "CLICK"},
            "attempts": [{
                "target": "world-dialog", "outcome": "success",
                "committed": True, "landing_verified": True,
            }],
        }]),
        _state_data={
            "alarms": {
                "page_name": "Clocks - Alarms",
                "page_id": "alarms-page",
                "elements": [current],
            },
            "world": {
                "page_name": "Clocks - World",
                "page_id": "world-page",
                "elements": [representative],
            },
        },
        _action_count=0, _active_state_mutation=None,
        perception=SimpleNamespace(use_semantic_inventory=True),
        review_debug=SimpleNamespace(
            record_agent=lambda *args, **kwargs: None,
            record_event=lambda *args, **kwargs: None),
    )

    outcome = plan_candidate(
        host, RunCursor("alarms", {"screenshot": b"screen"}), [current])

    assert outcome.directive is StageDirective.EXECUTION
    assert captured["shared_verified_buttons"] == []


def test_plan_candidate_presents_all_current_regions_with_feedback():
    toolbar = VisualElement(
        1, "More options", [0, 0, 1, 1], [1, 1],
        region="toolbar", region_id="r1")
    content = VisualElement(
        2, "Add alarm", [0, 0, 1, 1], [2, 2],
        region="content", region_id="r2")
    explored = VisualElement(
        3, "Alarm details", [0, 0, 1, 1], [3, 3],
        region="toolbar", region_id="r1")
    explored.exploration_status = "complete"
    explored.exploration_reason = "landing-verified CLICK"
    captured = {}
    agent_records = []

    def choose(_shot, context, **_kwargs):
        captured.update(context)
        return {
            "selected_entry_id": "e0",
            "next_action": {
                "action": {"action_type": "CLICK", "parameters": {}},
                "choice_id": "e0", "reason": "It may open a menu.",
            },
        }

    def explore_target(_shot, _context):
        return {
            "decision": "act", "reason": "It may open a menu.",
            "current_page": {"kind": "known", "page_ref": "p0"},
            "discovered_controls": [],
            "next_action": {
                "type": "CLICK", "target": "More options",
                "point_1000": [10, 10], "direction": None,
                "safety": "safe", "action_role": "goal",
                "reason": "Open the menu.", "expected_result": "Menu opens.",
            },
        }

    host = SimpleNamespace(
        _is_touch=False, app_name="Clock",
        explorer=SimpleNamespace(choose=choose, explore_target=explore_target),
        router=SimpleNamespace(plan_route=lambda *_args: []),
        graph=SimpleNamespace(action_edges=[{
            "source": "state", "element_id": "3",
            "action": {"action_type": "CLICK", "parameters": {}},
            "attempts": [{
                "target": "details", "outcome": "transitioned_consistent",
                "detail": "opened details", "committed": True,
                "landing_verified": True,
                "evidence": {"transition_observer": {
                    "observed_outcome": "Alarm details opened",
                    "relation_to_target": "related",
                }},
            }],
        }]),
        _state_data={"state": {
            "page_name": "Alarm", "page_id": "alarm",
            "elements": [toolbar, content, explored]},
            "details": {"page_name": "Alarm details",
                        "page_id": "alarm-details"}},
        _action_count=0, _active_state_mutation=None,
        _element_exploration_task=None,
        _explorer_deferred_regions=set(),
        _explorer_region_failure_counts={},
        _click_failure_history={
            ("state", str(toolbar.uid or toolbar.name)): {
                "visible_target_not_confirmed": 1,
            },
        },
        perception=SimpleNamespace(use_semantic_inventory=True),
        review_debug=SimpleNamespace(
            record_event=lambda *args, **kwargs: None,
            record_agent=lambda *args, **kwargs: agent_records.append(
                (args, kwargs))),
    )
    outcome = plan_candidate(
        host, RunCursor("state", {"screenshot": _png()}),
        [toolbar, content])

    assert outcome.directive is StageDirective.EXECUTION
    assert outcome.candidate.element is toolbar
    assert captured["function_entries"] == [
        {
            "entry_id": "e0",
            "target": "More options",
            "region_name": "toolbar",
            "exploration_status": "available_with_previous_problem",
            "status_detail": "",
            "previous_results": [],
            "framework_feedback": [{
                "failure_kind": "visible_target_not_confirmed",
                "attempts": 1,
            }],
        },
        {
            "entry_id": "e1",
            "target": "Add alarm",
            "region_name": "content",
            "exploration_status": "untried",
            "status_detail": "",
            "previous_results": [],
            "framework_feedback": [],
        },
        {
            "target": "Alarm details",
            "region_name": "toolbar",
            "exploration_status": "explored",
            "status_detail": "landing-verified CLICK",
            "previous_results": [{
                "outcome": "transitioned_consistent",
                "detail": "opened details",
                "actual_result": "Alarm details",
                "observed_outcome": "Alarm details opened",
                "relation_to_target": "related",
                "verified": True,
            }],
            "framework_feedback": [],
        },
    ]
    assert "current_region" not in captured
    explorer_record = next(
        kwargs for args, kwargs in agent_records if args == ("explorer",))
    assert explorer_record["verdict"] == "More options"
    assert explorer_record["target_records"] == captured["function_entries"]


def test_qwen_frontier_choice_maps_prompt_local_page_to_state(monkeypatch):
    pending = VisualElement(
        1, "Open details", [0, 0, 1, 1], [1, 1],
        region="content", region_id="r1")
    captured = {}

    def choose_route(_shot, context):
        captured.update(context)
        return {
            "selected_page_id": "p0",
            "reason": "This page still has a visible detail entry.",
        }

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.runtime.scheduling."
        "_frontier_state_candidates",
        lambda _host, _current: [("details", ["r2"], [pending])],
    )
    host = SimpleNamespace(
        app_name="Clock",
        explorer=SimpleNamespace(choose_route=choose_route),
        _state_data={
            "home": {"page_name": "Home"},
            "details": {
                "page_name": "Details",
                "semantic_blocks": [{
                    "region_id": "r2", "role": "Detail content",
                }],
            },
        },
        _route_failures={},
        _action_count=0,
        review_debug=SimpleNamespace(
            record_agent=lambda *_args, **_kwargs: None),
    )

    selected, stopped = _qwen_frontier_choice(
        host, "home", {"screenshot": b"screen"})

    assert selected == "details"
    assert stopped is False
    assert captured["candidate_pages"] == [{
        "page_id": "p0",
        "name": "Details",
        "pending_entries": ["Open details"],
        "pending_regions": ["Detail content"],
        "previous_route_feedback": [],
    }]


@pytest.mark.skip(reason="Explorer no longer receives verified coverage rows")
def test_plan_candidate_exposes_same_state_verified_result_across_regions():
    toolbar_add = VisualElement(
        1, "Add Button", [0, 0, 1, 1], [1, 1],
        region="toolbar", region_id="r1")
    content_add = VisualElement(
        2, "Add Alarm", [0, 0, 1, 1], [2, 2],
        region="content", region_id="r2")
    captured = {}
    persisted = []

    def choose(_shot, context, **_kwargs):
        captured.update(context)
        return {
            "semantic_only": [],
            "covered": [{
                "choice_ids": ["c0"],
                "by_verified": "v0",
                "reason": "Both entries open the same verified dialog.",
            }],
            "next_action": None,
        }

    host = SimpleNamespace(
        _is_touch=False, app_name="Clock",
        explorer=SimpleNamespace(choose=choose),
        graph=SimpleNamespace(action_edges=[{
            "source": "state", "target": "dialog", "element_id": "1",
            "action": {"action_type": "CLICK"},
            "attempts": [{
                "target": "dialog", "outcome": "success",
                "committed": True, "landing_verified": True,
            }],
        }]),
        _state_data={"state": {
            "page_name": "Alarm",
            "elements": [toolbar_add, content_add],
        }},
        _action_count=0, _active_state_mutation=None,
        _explorer_deferred_regions=set(),
        _persist_exploration_state=lambda state_id: persisted.append(state_id),
        perception=SimpleNamespace(use_semantic_inventory=True),
        review_debug=SimpleNamespace(
            record_event=lambda *args, **kwargs: None,
            record_agent=lambda *args, **kwargs: None),
    )

    outcome = plan_candidate(
        host, RunCursor("state", {"screenshot": b"screen"}),
        [content_add])

    assert outcome.directive is StageDirective.CONTINUE
    assert [row["name"] for row in captured["pending_buttons"]] == [
        "Add Alarm"]
    assert [(row["verified_id"], row["name"])
            for row in captured["verified_buttons"]] == [
        ("v0", "Add Button")]
    assert content_add.exploration_status == "covered"
    assert content_add.covered_by == "1"
    assert content_add.covered_by_state == "state"
    assert persisted == ["state"]


def test_plan_candidate_lets_explorer_decide_a_normal_deferred_return():
    leave = VisualElement(
        1, "Back", [0, 0, 1, 1], [1, 1],
        region="toolbar", region_id="r1")
    leave.back = True
    leave.exploration_status = "deferred_return"

    calls = []

    def choose(_shot, context, **_kwargs):
        calls.append(context)
        return {
            "selected_entry_id": "e0",
            "next_action": {
                "action": {"action_type": "click"},
                "choice_id": "e0",
                "reason": "No current work remains, so leave this interface.",
            },
        }

    def explore_target(_shot, _context):
        return {
            "decision": "act",
            "reason": "No current work remains, so leave this interface.",
            "current_page": {"kind": "known", "page_ref": "p0"},
            "discovered_controls": [],
            "next_action": {
                "type": "CLICK", "target": "Back",
                "point_1000": [10, 10], "direction": None,
                "safety": "safe", "action_role": "goal",
                "reason": "Leave this interface.",
                "expected_result": "Previous page opens.",
            },
        }

    host = SimpleNamespace(
        _is_touch=True, app_name="Settings",
        explorer=SimpleNamespace(choose=choose, explore_target=explore_target),
        router=SimpleNamespace(plan_route=lambda *_args: []),
        graph=SimpleNamespace(action_edges=[], stop_reason=""),
        _state_data={"state": {
            "page_name": "Notifications", "page_id": "notifications",
            "elements": [leave]}},
        _action_count=0, _active_state_mutation=None,
        _element_exploration_task=None,
        _explorer_deferred_regions=set(),
        _explorer_region_failure_counts={},
        perception=SimpleNamespace(use_semantic_inventory=True),
        review_debug=SimpleNamespace(
            record_event=lambda *args, **kwargs: None,
            record_agent=lambda *args, **kwargs: None),
    )

    outcome = plan_candidate(
        host, RunCursor("state", {"screenshot": _png()}), [leave])

    assert outcome.directive is StageDirective.EXECUTION
    assert outcome.candidate.element is leave
    assert outcome.candidate.action == {
        "action_type": "click", "x": 1, "y": 2}
    assert outcome.candidate.targeted is True
    assert outcome.candidate.direct_action is True
    assert outcome.candidate.pre_click_id == "state"
    assert calls[0]["function_entries"][0]["target"] == "Back"
    assert "No current work remains" in outcome.candidate.decision_reason


def test_verified_return_copy_executes_for_pending_mutation():
    leave = VisualElement(
        1, "Cancel", [0, 0, 1, 1], [1, 1],
        region="dialog", region_id="r1")
    leave.back = True
    leave.visited = True
    leave.exploration_status = "complete"
    graph = SimpleNamespace(action_edges=[{
        "source": "dialog", "target": "source", "element_id": "1",
        "action": {"action_type": "CLICK"},
        "attempts": [{
            "target": "source", "outcome": "success",
            "committed": True, "landing_verified": True,
        }],
    }], stop_reason="")

    def unexpected_choose(*_args, **_kwargs):
        raise AssertionError("the restoration return copy must bypass Explorer")

    host = SimpleNamespace(
        _is_touch=True, app_name="Settings",
        _active_state_mutation={
            "mutation_id": "m1",
            "source_state": "source",
            "mutated_state": "dialog",
            "after_value": "unknown",
            "state_key": "permission mode",
        },
        _last_live_observation_state_id="",
        _explorer_deferred_regions=set(),
        _unvisited_candidates=lambda _state: [],
        router=SimpleNamespace(node_out_edges=lambda *_args, **_kwargs: {
            "return": {
                "action": {"action_type": "CLICK"},
                "dst": "source",
                "provenance": "direct_verified",
                "effect_kind": "return_native_action",
                "element_id": "1",
                "label": "Cancel",
                "region": "dialog",
            },
        }),
        explorer=SimpleNamespace(choose=unexpected_choose),
        graph=graph,
        _state_data={"dialog": {
            "page_name": "Confirmation", "elements": [leave]}},
        _action_count=0,
        perception=SimpleNamespace(use_semantic_inventory=True),
        review_debug=SimpleNamespace(
            record_event=lambda *args, **kwargs: None),
    )

    candidates = available_unvisited_candidates(host, "dialog")
    outcome = plan_candidate(
        host, RunCursor("dialog", {"screenshot": b"screen"}), candidates)

    assert len(candidates) == 1
    assert candidates[0] is not leave
    assert candidates[0]._pending_restore_execution is True
    assert leave.exploration_status == "complete"
    assert outcome.directive is StageDirective.EXECUTION
    assert outcome.candidate.element is candidates[0]
    assert outcome.candidate.action == {"action_type": "click"}


def test_verified_return_to_live_ancestor_reopens_for_pending_mutation():
    leave = VisualElement(
        1, "Dismiss", [0, 0, 1, 1], [1, 1],
        region="dialog", region_id="r1")
    leave.visited = True
    leave.exploration_status = "complete"
    router = SimpleNamespace(
        node_out_edges=lambda *_args, **_kwargs: {
            "return": {
                "action": {"action_type": "CLICK"},
                "dst": "older-parent",
                "provenance": "direct_verified",
                "effect_kind": "return_via_control",
                "element_id": "1",
                "label": "Dismiss",
                "region": "dialog",
            },
        },
        _is_live_stack_ancestor=lambda context, destination: (
            context == "current-parent" and destination == "older-parent"),
    )
    host = SimpleNamespace(
        _active_state_mutation={
            "mutation_id": "m1",
            "source_state": "current-parent",
            "mutated_state": "dialog",
            "after_value": "unknown",
        },
        _last_live_observation_state_id="",
        _explorer_deferred_regions=set(),
        _unvisited_candidates=lambda _state: [],
        router=router,
        _state_data={"dialog": {"elements": [leave]}},
    )

    candidates = available_unvisited_candidates(host, "dialog")

    assert len(candidates) == 1
    assert candidates[0] is not leave
    assert candidates[0]._pending_restore_execution is True
    assert leave.exploration_status == "complete"

    router._is_live_stack_ancestor = lambda *_args: False
    assert available_unvisited_candidates(host, "dialog") == []


def test_plan_candidate_never_chooses_first_button_without_explorer_decision():
    element = VisualElement(
        1, "Delete", [0, 0, 1, 1], [1, 1],
        region="content", region_id="r1")
    graph = SimpleNamespace(action_edges=[], stop_reason="")
    host = SimpleNamespace(
        _is_touch=False, app_name="Clock",
        explorer=SimpleNamespace(
            last_reason="invalid explorer response",
            choose=lambda *_args, **_kwargs: {}),
        graph=graph,
        _state_data={"state": {
            "page_name": "Alarm", "elements": [element]}},
        _action_count=0,
        review_debug=SimpleNamespace(
            record_agent=lambda *args, **kwargs: None,
            record_event=lambda *args, **kwargs: None),
        _maybe_save=lambda: None,
    )

    outcome = plan_candidate(
        host, RunCursor("state", {"screenshot": b"screen"}), [element])

    assert outcome.directive is StageDirective.CONTINUE
    assert outcome.candidate is None
    assert graph.stop_reason == ""
    assert host._explorer_deferred_regions == {("state", "r1")}
    assert host._explorer_region_failure_counts == {("state", "r1"): 1}


@pytest.mark.skip(reason="Explorer no longer returns partial classifications")
def test_explorer_keeps_valid_partial_results_when_repair_still_fails(
        monkeypatch):
    replies = iter([
        (
            '{"covered":[{"choice_ids":["c1"],"by_verified":"v0",'
            '"reason":"Same verified destination pattern."}],'
            '"semantic_only":[{"choice_id":"c0",'
            '"reason":"It is only navigation."}],"next_action":null}'
        ),
        (
            '{"covered":[],"semantic_only":[{"choice_id":"c0",'
            '"reason":"It is only navigation."}],"next_action":null}'
        ),
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: (next(replies), None))
    explorer = ExplorerAgent(object())

    decision = explorer.choose(
        b"screen",
        {
            "pending_buttons": [
                {
                    "choice_id": "c0", "name": "Back",
                    "category": "navigation", "selected": False,
                },
                {
                    "choice_id": "c1", "name": "Another app",
                    "category": "navigation", "selected": False,
                },
            ],
            "verified_buttons": [{
                "verified_id": "v0", "choice_id": "",
                "name": "Calendar", "category": "navigation",
            }],
        },
        platform="android",
    )

    assert decision["covered"] == [{
        "choice_ids": ["c1"],
        "by_verified": "v0",
        "reason": "Same verified destination pattern.",
    }]
    assert decision["semantic_only"] == [{
        "choice_id": "c0",
        "reason": "It is only navigation.",
    }]
    assert decision["next_action"] is None


def test_explorer_failure_defers_only_its_region():
    blocked = VisualElement(
        1, "Back", [0, 0, 1, 1], [1, 1],
        region="toolbar", region_id="toolbar")
    available = VisualElement(
        2, "Add", [0, 0, 1, 1], [2, 2],
        region="content", region_id="content")
    host = SimpleNamespace(
        _explorer_deferred_regions={("state", "toolbar")},
        _unvisited_candidates=lambda _state_id: [blocked, available],
    )

    assert available_unvisited_candidates(host, "state") == [available]


def test_deferred_explorer_region_gets_later_retry_then_stops_incomplete():
    element = VisualElement(
        1, "Search", [0, 0, 1, 1], [1, 1],
        region="toolbar", region_id="toolbar")
    key = ("state", "toolbar")
    events = []
    host = SimpleNamespace(
        _nearest_unexplored_node=lambda _current_id: None,
        _active_state_mutation=None,
        _stateful_budget_blocked=False,
        _state_data={"state": {
            "path": [], "replay_hints": [], "elements": [element]}},
        _route_blocked_targets=set(),
        _route_target_failure_counts={},
        _explorer_deferred_regions={key},
        _explorer_region_failure_counts={key: 1},
        _unvisited_candidates=lambda _state_id: [element],
        _backtrack_fail_count=0,
        graph=SimpleNamespace(scroll_ledger={}, stop_reason=""),
        review_debug=SimpleNamespace(
            record_event=lambda event, **payload:
            events.append((event, payload))),
    )

    retry = schedule_frontier(
        host, "state", {"screenshot": b"screen"}, [], [], 0)

    assert retry.stop is False
    assert host._explorer_deferred_regions == set()
    assert events[-1][0] == "explorer_region_retry"

    host._explorer_deferred_regions.add(key)
    host._explorer_region_failure_counts[key] = (
        MAX_EXPLORER_REGION_FAILURES)
    exhausted = schedule_frontier(
        host, "state", {"screenshot": b"screen"}, [], [], 0)

    assert exhausted.stop is True
    assert host.graph.stop_reason == "explorer_unavailable"
    assert events[-1][0] == "explorer_unavailable"
