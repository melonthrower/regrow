from types import SimpleNamespace

from gui_rewalk.src.core.visual_traversal.agents.observer import ObserverAgent
from gui_rewalk.src.core.visual_traversal.prompts.observation import (
    build_transition_observer_prompt,
)
from gui_rewalk.src.core.visual_traversal.runtime.landing import (
    _observe_navigation_effect,
    _observer_effect_evidence,
)


def test_transition_prompt_uses_only_target_and_visual_evidence():
    prompt = build_transition_observer_prompt({
        "target": "Add Alarm",
        "control_purpose": "must not appear",
        "expected_immediate_effect": "must not appear",
    })

    assert "Add Alarm" in prompt
    assert '"target"' in prompt
    assert "observed_outcome" in prompt
    assert "relation_to_target" in prompt
    assert "你是一名 GUI 操作结果观察助手" in prompt
    assert "先根据两张截图检查这个目标名称是否准确" in prompt
    assert "任务：" in prompt
    assert "关系标签：" in prompt
    assert "约束：" in prompt
    assert "related|unrelated|no_relevant_change|uncertain" in prompt
    assert "目标被点击" in prompt
    assert "当前 target 只是待校验候选" in prompt
    assert "先依据截图独立确定控件语义" in prompt
    assert "target 原样使用该文字，不添加或改写控件类型" in prompt
    assert "不把无关结果页面的名称当作控件名称" in prompt
    assert "Page" not in prompt
    assert "Region identity" not in prompt
    assert "只读的视觉核验" not in prompt
    assert "不提出后续动作" not in prompt
    assert "must not appear" not in prompt
    assert "result_type" not in prompt
    assert "matched" not in prompt


def test_observer_parses_confirmed_contract(monkeypatch):
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.observer._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: (
            '{"target":"Add Alarm",'
            '"observed_outcome":"出现 New Alarm 对话框",'
            '"relation_to_target":"related"}', None))

    result = ObserverAgent(object()).observe_transition(
        b"before", b"after", {"target": "Add Alarm"})

    assert result == {
        "target": "Add Alarm",
        "observed_outcome": "出现 New Alarm 对话框",
        "relation_to_target": "related",
    }
    assert _observer_effect_evidence(result) == {
        "verdict": "transitioned_consistent",
        "note": "出现 New Alarm 对话框",
    }


def test_observer_retries_invalid_relation_without_repeating_action(
        monkeypatch):
    replies = iter([
        '{"target":"Add Alarm","observed_outcome":"变化",'
        '"relation_to_target":"matched"}',
        '{"target":"Add Alarm","observed_outcome":"出现 World 页面",'
        '"relation_to_target":"unrelated"}',
    ])
    calls = []
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.observer._img_arr",
        lambda value: value)

    def predict(*_args, **_kwargs):
        calls.append(1)
        return next(replies), None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    result = ObserverAgent(object()).observe_transition(
        b"before", b"after", {"target": "Add Alarm"})

    assert len(calls) == 2
    assert result["relation_to_target"] == "unrelated"
    assert _observer_effect_evidence(result)["verdict"] == (
        "transitioned_inconsistent")


def test_observer_fails_closed_after_three_invalid_outputs(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.observer._img_arr",
        lambda value: value)

    def predict(*_args, **_kwargs):
        calls.append(1)
        return "{}", None

    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        predict)
    result = ObserverAgent(object()).observe_transition(
        b"before", b"after", {"target": "Add Alarm"})

    assert len(calls) == 3
    assert result == {
        "target": "Add Alarm",
        "observed_outcome": "",
        "relation_to_target": "uncertain",
    }


def test_landing_observer_context_does_not_include_predicted_effect():
    captured = {}
    host = SimpleNamespace(
        observer=SimpleNamespace(
            observe_transition=lambda before, after, context:
            captured.update(context) or {
                "target": "Add Alarm",
                "observed_outcome": "出现对话框",
                "relation_to_target": "related",
            }),
        _state_data={},
    )
    element = SimpleNamespace(
        name="Add Alarm",
        purpose="legacy purpose",
        expected_immediate_effect="legacy prediction",
    )

    result = _observe_navigation_effect(
        host, source_id="a", target_id="b", element=element,
        before_shot=b"before", after_shot=b"after", live_elements=[])

    assert captured == {"target": "Add Alarm"}
    assert result["relation_to_target"] == "related"


def test_observer_returns_corrected_target_from_visible_evidence(monkeypatch):
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.agents.observer._img_arr",
        lambda value: value)
    monkeypatch.setattr(
        "gui_rewalk.src.core.visual_traversal.visual_cache.predict_mm_role",
        lambda *_args, **_kwargs: (
            '{"target":"Manage your calendars",'
            '"observed_outcome":"出现日历管理页面",'
            '"relation_to_target":"related"}', None))

    result = ObserverAgent(object()).observe_transition(
        b"before", b"after", {"target": "Date picker"})

    assert result == {
        "target": "Manage your calendars",
        "observed_outcome": "出现日历管理页面",
        "relation_to_target": "related",
    }
