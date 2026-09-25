import io
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from gui_rewalk.src.core.visual_traversal.agents.explorer import ExplorerAgent
from gui_rewalk.src.core.visual_traversal.agents.identity import (
    BlockIdentityJudge,
)
from gui_rewalk.src.core.visual_traversal.prompts.exploration import (
    build_explorer_prompt,
)
from gui_rewalk.src.core.visual_traversal.prompts.identity_candidates import (
    build_region_partition_mapping_prompt,
)
from gui_rewalk.src.core.visual_traversal.runtime.contracts import (
    RunCursor, StageDirective,
)
from gui_rewalk.src.core.visual_traversal.runtime.scheduling import (
    plan_candidate,
)
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement


def _png(width=100, height=100):
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


def test_region_mapping_prompt_is_the_confirmed_complete_wrapper():
    prompt = build_region_partition_mapping_prompt(
        "Alarms",
        [{"region": "A1", "name": "Alarm navigation"}],
        "New Alarm",
        [{"region": "B1", "name": "Dialog actions"}],
        has_screenshots=True,
        triggering_action="Add Alarm",
    )

    assert "对应关系只表示同一内容容器或同一对象身份" in prompt
    assert "位置相近、覆盖原位置、功能相似或由同一动作触发" in prompt
    assert "known_region_ids" in prompt
    assert "current_region_ids" in prompt
    assert "new_current_region_ids" in prompt
    assert "CURRENT_OPERABLE_INTERFACE" not in prompt


def test_region_mapping_accepts_set_to_set_contract(monkeypatch):
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: (
            '{"matches":[{"known_region_ids":["A1"],'
            '"current_region_ids":["B1","B2"],"reason":"same content"}],'
            '"new_current_region_ids":["B3"],'
            '"unresolved_current_region_ids":[]}', None))

    result = BlockIdentityJudge(object()).align_region_partitions(
        "old", [{"region": "A1"}],
        "new", [{"region": "B1"}, {"region": "B2"}, {"region": "B3"}])

    assert result["matches"] == [{
        "known_region_ids": ["A1"],
        "current_region_ids": ["B1", "B2"],
        "reason": "same content",
    }]
    assert result["new_current_region_ids"] == ["B3"]
    assert result["unmatched_known_region_ids"] == []


def test_explorer_prompt_allows_qwen_to_choose_across_entries():
    prompt = build_explorer_prompt({
        "region_id": "stable-r0",
        "region_name": "Application menu",
        "region_description": "Visible menu entries",
        "function_entries": [
            {"entry_id": "e0", "target": "Keyboard Shortcuts"},
            {"entry_id": "e1", "target": "Help"},
        ],
    })

    assert "selected_entry_id" in prompt
    assert "自由选择任意一个入口" in prompt
    assert "选择列表中的第一个入口" not in prompt
    assert "exploration_status" in prompt
    assert "attempts" in prompt
    assert "problems" in prompt
    assert "没有 entry_id 的记录" in prompt
    assert "covered" not in prompt
    assert "semantic_only" not in prompt
    assert "expected_immediate_effect" not in prompt


def test_explorer_sees_completed_target_but_cannot_select_it(monkeypatch):
    captured = {}

    def predict(_agent, _role, prompt, _images, _ledger, **_kwargs):
        captured["prompt"] = prompt
        return ('{"selected_entry_id":"e0",'
                '"reason":"Settings remains untried."}'), None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    result = ExplorerAgent(object()).choose(
        _png(),
        {"function_entries": [
            {
                "entry_id": "e0", "target": "Settings",
                "exploration_status": "untried",
            },
            {
                "target": "Chat info", "exploration_status": "explored",
                "previous_results": [{
                    "observed_outcome": "Chat details opened",
                    "verified": True,
                }],
            },
        ]},
        platform="desktop",
    )

    assert result["selected_entry_id"] == "e0"
    assert '"target": "Chat info"' in captured["prompt"]
    assert '"exploration_status": "explored"' in captured["prompt"]
    assert '"entry_id": "e0"' in captured["prompt"]


def test_explorer_can_use_codex_cli_model(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr(
        ExplorerAgent, "_codex_command", staticmethod(lambda: ["codex-test"]))

    def run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        output_path = command[command.index("-o") + 1]
        Path(output_path).write_text(
            '{"selected_entry_id":"e0","reason":"untried"}',
            encoding="utf-8",
        )
        return SimpleNamespace(
            returncode=0,
            stdout='{"type":"thread.started","thread_id":"codex-thread"}\n',
            stderr="",
        )

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer.subprocess.run",
        run)
    explorer = ExplorerAgent(
        None, codex_model="codex-fixture-model",
        codex_temp_root=str(tmp_path))
    result = explorer.choose(
        _png(),
        {"function_entries": [
            {"entry_id": "e0", "target": "Settings"},
        ]},
        platform="desktop",
    )

    assert result["selected_entry_id"] == "e0"
    assert captured["command"][:4] == [
        "codex-test", "exec", "-m", "codex-fixture-model"]
    assert explorer.last_backend_runs == [{
        "backend": "codex_cli",
        "model": "codex-fixture-model",
        "thread_id": "codex-thread",
        "returncode": 0,
    }]


def test_explorer_receives_the_latest_full_frame(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.explorer._img_arr",
        lambda value: Image.open(io.BytesIO(value)).size)

    def predict(_agent, role, prompt, images, _ledger, **_kwargs):
        captured.update(role=role, prompt=prompt, images=images)
        return ('{"selected_entry_id":"e1",'
                '"reason":"Help may expose another interface."}'), None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    decision = ExplorerAgent(object()).choose(
        _png(200, 100),
        {
            "region_id": "r0",
            "region_name": "Menu",
            "region_description": "Menu entries",
            "region_bbox_1000": [250, 0, 750, 1000],
            "function_entries": [
                {"entry_id": "e0", "target": "Keyboard Shortcuts"},
                {"entry_id": "e1", "target": "Help"},
            ],
        },
        platform="desktop",
    )

    assert captured["images"] == [(200, 100)]
    assert decision["selected_entry_id"] == "e1"
    assert decision["next_action"]["choice_id"] == "e1"
    assert decision["next_action"]["action"]["action_type"] == "CLICK"


def test_explorer_rejects_unknown_entry_id(monkeypatch):
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: (
            '{"selected_entry_id":"not-present",'
            '"reason":"It looks useful."}', None))
    explorer = ExplorerAgent(object())

    result = explorer.choose(
        _png(),
        {
            "region_bbox_1000": [0, 0, 1000, 1000],
            "function_entries": [{"entry_id": "e0", "target": "Help"}],
        },
        platform="android",
    )

    assert result == {}
    assert "not-present" in explorer.last_reason
    assert "不在本次候选中" in explorer.last_reason


def test_explorer_returns_framework_feedback_before_accepting_correction(
        monkeypatch):
    replies = iter([
        ('{"selected_entry_id":"missing",'
         '"reason":"It looks useful."}'),
        ('{"selected_entry_id":"e1",'
         '"reason":"The visible Help entry can open more information."}'),
    ])
    prompts = []

    def predict(_agent, _role, prompt, _images, _ledger, **_kwargs):
        prompts.append(prompt)
        return next(replies), None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    result = ExplorerAgent(object()).choose(
        _png(),
        {"function_entries": [
            {"entry_id": "e0", "target": "Settings"},
            {"entry_id": "e1", "target": "Help"},
        ]},
        platform="desktop",
    )

    assert result["selected_entry_id"] == "e1"
    assert len(prompts) == 2
    assert "框架对上一项意见的反馈" in prompts[1]
    assert "missing" in prompts[1]


def test_explorer_accepts_explicit_null_after_framework_challenge(monkeypatch):
    replies = iter([
        ('{"selected_entry_id":null,'
         '"reason":"The entries are not on the foreground menu."}'),
        ('{"selected_entry_id":null,'
         '"reason":"The foreground dialog hides every listed entry."}'),
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: (next(replies), None))
    explorer = ExplorerAgent(object())

    result = explorer.choose(
        _png(),
        {"function_entries": [{"entry_id": "e0", "target": "Add"}]},
        platform="desktop",
    )

    assert result["selected_entry_id"] is None
    assert result["next_action"] is None
    assert "foreground dialog" in result["reason"]
    assert len(explorer.last_raw_responses) == 2


def test_explorer_chooses_which_known_page_to_revisit(monkeypatch):
    captured = {}

    def predict(_agent, role, prompt, images, _ledger, **_kwargs):
        captured.update(role=role, prompt=prompt, images=images)
        return (
            '{"selected_page_id":"p1",'
            '"reason":"The search page has two unexplored entries."}',
            None,
        )

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    result = ExplorerAgent(object()).choose_route(
        _png(),
        {
            "application_name": "Calendar",
            "current_interface": "Month view",
            "candidate_pages": [
                {"page_id": "p0", "name": "Settings"},
                {
                    "page_id": "p1",
                    "name": "Search",
                    "pending_entries": ["Search calendars", "Date filter"],
                },
            ],
        },
    )

    assert result["selected_page_id"] == "p1"
    assert captured["role"] == "explorer_route"
    assert len(captured["images"]) == 1
    assert "框架随后使用已有的真实动作边" in captured["prompt"]


def test_plan_candidate_passes_entry_target_and_locator_bbox_to_explorer():
    element = VisualElement(
        0, "Add Alarm", [0, 0, 0, 0], [0, 0],
        source="region_inventory", region="Alarm content",
        region_id="state:r0", action_label="e0",
        geometry_status="semantic_only", execution_safety="safe")
    captured = {}

    def choose(_shot, context, **_kwargs):
        captured.update(context)
        return {
            "selected_entry_id": "e0",
            "next_action": {
                "action": {"action_type": "CLICK", "parameters": {}},
                "choice_id": "e0",
                "reason": "selected",
            },
        }

    def explore_target(_shot, _context):
        return {
            "decision": "act", "reason": "selected",
            "current_page": {"kind": "known", "page_ref": "p0"},
            "discovered_controls": [],
            "next_action": {
                "type": "CLICK", "target": "Add Alarm",
                "point_1000": [500, 500], "direction": None,
                "safety": "safe", "action_role": "goal",
                "reason": "Explore Add Alarm.",
                "expected_result": "Alarm editor opens.",
            },
        }

    host = SimpleNamespace(
        _is_touch=False,
        app_name="Clock",
        explorer=SimpleNamespace(choose=choose, explore_target=explore_target),
        router=SimpleNamespace(plan_route=lambda *_args: []),
        graph=SimpleNamespace(action_edges=[]),
        _state_data={"state": {
            "page_name": "Alarms", "page_id": "alarms",
            "elements": [element],
            "semantic_blocks": [{
                "region_id": "state:r0",
                "role": "Alarm content",
                "description": "Alarm list and add entry",
                "bbox_1000": [0, 100, 1000, 900],
            }],
        }},
        _action_count=0,
        _active_state_mutation=None,
        _element_exploration_task=None,
        _explorer_deferred_regions=set(),
        _explorer_region_failure_counts={},
        perception=SimpleNamespace(use_semantic_inventory=True),
        review_debug=SimpleNamespace(
            record_event=lambda *_args, **_kwargs: None,
            record_agent=lambda *_args, **_kwargs: None),
    )

    outcome = plan_candidate(
        host, RunCursor("state", {"screenshot": _png()}), [element])

    assert outcome.directive is StageDirective.EXECUTION
    assert captured["function_entries"] == [{
        "entry_id": "e0",
        "target": "Add Alarm",
        "region_name": "Alarm content",
        "exploration_status": "untried",
        "status_detail": "",
        "previous_results": [],
        "framework_feedback": [],
    }]
    assert "region_bbox_1000" not in captured
