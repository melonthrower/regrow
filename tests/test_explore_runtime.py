"""Existing modular exploration contracts: runtime."""


import json

import pytest

from gui_rewalk.src.core.explore.status import build_task_view
from gui_rewalk.src.core.explore.anchors import capture_click_anchor
from gui_rewalk.src.core.explore.artifacts import ArtifactStore
from gui_rewalk.src.core.explore.contracts import ActionRequest, parse_turn
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.models import (
    ActionAttempt,
    Operation,
    PageState,
    RegionOccurrence,
    RegionVariant,
    Task,
    Transition,
)
from gui_rewalk.src.core.explore.runtime import (
    ExplorationRuntime,
    run as run_exploration,
)
from gui_rewalk.src.core.explore.tasks import TaskScheduler

from .explore_fixtures import (
    _Agent,
    _Env,
    _anchor_scene,
    _image_png,
    _known_screen,
    _ledger_with_current_canonical_binding,
    _new_screen,
    _png,
    _report,
    _seed_ledger,
    _survey_scroll_report,
    _turn,
)


def test_recorded_current_binding_can_execute_an_open_shared_task():
    ledger, focus = _ledger_with_current_canonical_binding()
    ledger.operations["o2"].status = "recorded"
    ledger.tasks["t-current"].status = "done"
    focus.status = "active"
    ledger.operations[focus.operation_id].status = "active"
    ledger.current_task_id = focus.task_id

    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.platform = "desktop"
    card = build_task_view(
        runtime.ledger,
        focus,
        rediscovering=getattr(runtime, "resume_region_rediscovery_required", False),
    )
    requested = ActionRequest(
        kind="click", purpose="", operation_ref="", owner_ref="el2",
        target="Alarms 页面",
        point_1000=(500.0, 100.0), text="", direction="", amount=650,
    )
    bound = runtime._bind_action(focus, requested)

    assert "required_source_state_ref" not in card
    assert card["element_ref"] == "el2"
    assert runtime._validate_action(focus, bound) == ""
    assert focus.status == "active"
    assert ledger.operations["o2"].status == "recorded"


@pytest.mark.parametrize("terminal_gap", [False, True])
def test_framework_ends_without_requesting_model_finish(tmp_path, terminal_gap):
    reports = [_turn(screen=_new_screen(), page_report=_report(include_start=terminal_gap))]
    if terminal_gap:
        reports.append(_turn(screen=_known_screen(), current_task_result="failed"))
    for report in reports:
        report.pop("finish")
    agent = _Agent([(report, False) for report in reports])
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(env=env, app_name="test", platform="desktop",
                                 output_root=str(tmp_path), agent=agent, max_actions=3)

    result = runtime.run(env._get_obs())

    assert result.status == ("partial" if terminal_gap else "complete")
    assert result.stop_reason == ("terminal_gaps" if terminal_gap else "complete")
    assert bool(result.gaps) is terminal_gap
    assert len(agent.contexts) == len(reports)
    assert env.actions == []


def test_runtime_preserves_action_reason_across_taskless_recovery(tmp_path):
    execute = _turn(screen=_known_screen(), action={
        "kind": "click", "owner_ref": "el1", "target": "开始按钮",
        "point_1000": [500, 700],
    })
    execute["reason"] = "预计控制区保留，运行内容出现。"
    recover = _turn(screen=_known_screen(), previous={
        "attempt_ref": "a1", "element_actions": [
            {"element_ref": "el1", "action": "click", "completed": True}],
        "region_actions": [], "function_info": [], "parameter_info": None,
        "reason": "运行内容出现，原操作完成。",
    }, action={"kind": "back", "owner_ref": "", "target": "关闭干扰"})
    recover["reason"] = "预计应用区块保留，无关干扰消失。"
    settled = _turn(screen=_known_screen(), previous={
        "attempt_ref": "a2", "element_actions": [], "region_actions": [],
        "function_info": [], "parameter_info": None,
        "reason": "干扰已消失，应用区块保留。",
    }, finish=True)

    class SequenceEnv(_Env):
        def step(self, action, pause=0):
            self.after = _png("gray" if not self.actions else "black")
            return super().step(action, pause)

    agent = _Agent([(execute, False), (recover, True), (settled, True)])
    runtime = ExplorationRuntime(
        env=SequenceEnv(_png("white"), _png("gray")), app_name="test",
        platform="desktop", output_root=str(tmp_path), agent=agent,
        max_actions=3)
    runtime.ledger = _seed_ledger()
    original_task_count = len(runtime.ledger.tasks)

    result = runtime.run(runtime.env._get_obs())

    assert result.status == "partial"
    assert result.stop_reason == "action_result_unconfirmed"
    assert len(runtime.env.actions) == 2
    assert len(runtime.ledger.tasks) == original_task_count
    assert runtime.ledger.operation_task("o1").attempt_count == 1
    assert runtime.ledger.operations["o1"].status == "verified"
    assert runtime.ledger.attempts["a2"].task_id == ""
    assert runtime.ledger.attempts["a2"].purpose == "recover"
    assert runtime.ledger.attempts["a2"].outcome == "uncertain"
    assert runtime.ledger.attempts["a2"].after_ref
    key = "动作前说明（含预测，不是已验证事实）"
    assert agent.contexts[1][key] == "预计控制区保留，运行内容出现。"
    assert agent.contexts[2][key] == "预计应用区块保留，无关干扰消失。"
    restored = ExplorationLedger.load(tmp_path / "exploration_ledger.json")
    assert restored.attempts["a1"].agent_reason == execute["reason"]
    assert restored.attempts["a2"].agent_reason == recover["reason"]

    old = restored.snapshot()
    for attempt in old["attempts"]:
        attempt.pop("agent_reason")
    (tmp_path / "old_ledger.json").write_text(json.dumps(old), encoding="utf-8")
    assert ExplorationLedger.load(tmp_path / "old_ledger.json").attempts[
        "a1"].agent_reason == ""


def test_taskless_recovery_stops_after_two_no_effect_attempts(tmp_path):
    action = {"kind": "back", "owner_ref": "", "target": "关闭干扰"}
    turns = []
    for attempt_ref in ("a1", "a2"):
        turns.append((_turn(screen=_known_screen(), previous={
            "attempt_ref": attempt_ref, "element_actions": [],
            "region_actions": [], "function_info": [], "parameter_info": None,
            "reason": "干扰仍在，没有变化。",
        }, action=action, finish=True), True))
    runtime = ExplorationRuntime(
        env=_Env(_png("white"), _png("white")), app_name="test",
        platform="desktop", output_root=str(tmp_path), agent=_Agent(turns),
        max_actions=5)
    runtime.max_turns = 3
    runtime.ledger = _seed_ledger()
    runtime.scheduler.settle(
        runtime.ledger, runtime.ledger.operation_task("o1"),
        result="completed", reason="功能已完成")
    task_count = len(runtime.ledger.tasks)
    runtime._execute(task=None, action=ActionRequest(
        kind="back", purpose="recover", target="关闭干扰", point_1000=None,
        text="", direction="", amount=650, operation_ref="", owner_ref=""),
        screenshot=_png("white"))

    result = runtime.run(runtime.env._get_obs())

    assert result.status == "partial"
    assert result.stop_reason == "action_result_unconfirmed"
    assert len(runtime.env.actions) == 1
    assert len(runtime.ledger.tasks) == task_count
    assert runtime.pending_attempt_id == ""
    assert all(a.outcome == "uncertain" for a in runtime.ledger.attempts.values())
    assert not result.gaps
    assert any(event["kind"] == "action_result_unconfirmed"
               for event in runtime.ledger.events)


@pytest.mark.parametrize("kind,owner,operation", [
    ("scroll", "", ""), ("click", "el1", "o1"),
])
def test_taskless_recovery_keeps_owner_and_scroll_guards(
        tmp_path, kind, owner, operation):
    runtime = ExplorationRuntime(
        env=_Env(_png("white"), _png("gray")), app_name="test",
        platform="desktop", output_root=str(tmp_path), agent=_Agent([]),
        max_actions=3)
    action = ActionRequest(
        kind=kind, purpose="recover", target="目标", point_1000=[500, 500],
        text="", direction="down" if kind == "scroll" else "", amount=650,
        operation_ref=operation, owner_ref=owner)
    assert runtime._validate_action(None, action)
    assert not runtime.env.actions


def test_runtime_settles_pending_report_without_page_resolver(tmp_path):
    first = _turn(screen=_new_screen(), page_report=_report())
    execute = _turn(
        screen=_known_screen(),
        action={
            "kind": "click", "purpose": "execute", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o1",
        },
    )
    settle = _turn(
        screen=_known_screen(),
        page_report=_report(),
        previous={
            "attempt_ref": "a1", "outcome": "success",
            "task_result": "completed", "visible_result": "秒表已开始计时。",
            "corrected_target": "", "reason": "前后图显示开始操作生效。",
        },
        finish=True,
    )

    class _NoPageResolverAgent(_Agent):
        @staticmethod
        def resolve_page(*, payload):
            pytest.fail(f"Page Resolver must not be called: {payload}")

    env = _Env(_png("white"), _png("gray"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=_NoPageResolverAgent([
            (first, False), (execute, False), (settle, True),
        ]),
        max_actions=2,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "complete"
    assert runtime.ledger.attempts["a1"].outcome == "success"


def test_runtime_finishes_partial_when_only_failed_gaps_remain(tmp_path):
    ledger = _seed_ledger()
    task = TaskScheduler().choose(ledger)
    TaskScheduler.settle(
        ledger, task, result="failed", reason="恢复尝试已耗尽。")
    agent = _Agent([(_turn(screen=_known_screen(), finish=True), False)])
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=1,
    )
    runtime.ledger = ledger
    runtime.confirmed_state_id = ledger.current_state_id
    runtime.confirmed_screenshot = env._get_obs()["screenshot"]

    result = runtime.run(env._get_obs())

    assert result.status == "partial"
    assert result.stop_reason == "terminal_gaps"
    assert result.gaps == (
        f"{task.task_id} explore_operation {task.operation_id}: failed",)
    completion = json.loads(
        (tmp_path / "modular_completion.json").read_text(encoding="utf-8"))
    assert completion["status"] == "partial"
    assert completion["stop_reason"] == "terminal_gaps"
    assert completion["gaps"] == list(result.gaps)
    assert completion["tasks"] == 2
    assert completion["task_bindings"] == 2
    graph = json.loads(
        (tmp_path / "modular_graph.json").read_text(encoding="utf-8"))
    assert graph["stop_reason"] == "terminal_gaps"


def test_top_level_modular_run_restores_before_exploring(tmp_path, monkeypatch):
    ledger = _seed_ledger()
    task = ledger.operation_task("o1")
    task.status = "done"
    ledger.operations["o1"].status = "recorded"
    ledger.current_task_id = ""
    ledger.save(tmp_path / "exploration_ledger.json")
    (tmp_path / "screenshots").mkdir(exist_ok=True)
    live = _png("white")
    (tmp_path / "screenshots" / "first.png").write_bytes(live)
    rediscovered_screen = {
        **_known_screen(), "identity": "new_state", "state_ref": "",
        "state_name": "恢复状态", "state_summary": "最新 Region 清点",
    }
    agent = _Agent([
        (_turn(
            screen=rediscovered_screen,
            page_report=_report(include_start=False),
        ), False),
        (_turn(screen={
            **rediscovered_screen, "identity": "known", "state_ref": "s2",
        }, finish=True), False),
    ])
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.runtime._build_explorer_agent",
        lambda **_kwargs: agent)

    result = run_exploration(
        env=_Env(live, live), app_name="clocks", output_root=str(tmp_path),
        initial_obs={"screenshot": live}, model="fixture", transport_agent=None,
        max_actions=10, backend="codex_cli",
        resume_path=str(tmp_path / "exploration_ledger.json"),
    )

    assert result.status == "complete"
    assert agent.contexts[0]["当前任务精确卡"]["kind"] == (
        "resume_region_rediscovery")
    assert len(agent.contexts) == 1  # No final completion-check call.
    assert ExplorationLedger.load(tmp_path / "exploration_ledger.json").current_state_id == "s2"


def test_runtime_replays_verified_route_anchor_before_calling_agent(tmp_path):
    before = _image_png(_anchor_scene(x=90))
    after = _image_png(_anchor_scene(x=210))
    point = [90 * 1000 / 359, 120 * 1000 / 239]
    captured = capture_click_anchor(before, point)
    assert captured is not None
    settle_route = _turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a2",
            "outcome": "success",
            "task_result": "unchanged",
            "visible_result": "已到达目标状态。",
            "corrected_target": "",
            "reason": "前后图显示路线入口生效。",
        },
    )
    release_task = _turn(
        screen=_known_screen(),
        current_task_result="failed",
    )
    finish = _turn(screen=_known_screen(), finish=True)

    class _TrackingAgent(_Agent):
        def __init__(self, turns):
            super().__init__(turns)
            self.pending_flags = []

        def decide(self, **kwargs):
            self.pending_flags.append(bool(kwargs.get("has_pending_action")))
            return super().decide(**kwargs)

    agent = _TrackingAgent([
        (settle_route, True),
        (release_task, False),
        (finish, False),
    ])
    env = _Env(before, after)
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=2,
    )
    ledger = _seed_ledger()
    source_state_id = ledger.mint("state")
    source_occurrence_id = "ro-route-source"
    source_variant_id = "rv-route-source"
    ledger.states[source_state_id] = PageState(
        source_state_id, "p1", "路线来源状态", "等待返回秒表",
        "screenshots/source.png", [source_occurrence_id],
        survey_complete=True, inventory_passes=1,
    )
    ledger.pages["p1"].state_ids.append(source_state_id)
    ledger.occurrences[source_occurrence_id] = RegionOccurrence(
        source_occurrence_id, "r1", source_state_id,
        "秒表显示与控制", "同一 Region 的另一个状态", source_variant_id)
    ledger.region_variants[source_variant_id] = RegionVariant(
        source_variant_id, "r1", [source_occurrence_id])
    ledger.regions["r1"].occurrence_ids.append(source_occurrence_id)
    ledger.regions["r1"].variant_ids.append(source_variant_id)
    task = ledger.operation_task("o1")
    task.status = "active"
    historical_attempt_id = ledger.mint("attempt")
    transition_id = ledger.mint("transition")
    anchor_ref = runtime.artifacts.save_attempt_anchor(
        historical_attempt_id, captured.png)
    historical_action = {
        "kind": "click",
        "purpose": "execute",
        "target": "打开目标状态",
        "point_1000": point,
        "text": "",
        "direction": "",
        "amount": 650,
        "operation_ref": "old-operation",
    }
    ledger.attempts[historical_attempt_id] = ActionAttempt(
        historical_attempt_id,
        "historical-task",
        source_state_id,
        "execute",
        historical_action,
        "action_attempts/a1/before.png",
        outcome="success",
        visible_result="已到达目标状态。",
        target_state_id="s1",
        anchor_ref=anchor_ref,
        anchor_offset_px=list(captured.click_offset_px),
    )
    ledger.transitions.append(Transition(
        transition_id,
        source_state_id,
        "s1",
        historical_attempt_id,
        historical_action,
        "已到达目标状态。",
    ))
    ledger.current_page_id = "p1"
    ledger.current_state_id = source_state_id
    ledger.current_task_id = task.task_id
    runtime.ledger = ledger
    runtime.confirmed_state_id = source_state_id
    runtime.confirmed_screenshot = before
    assert runtime._visual_anchor_route_action(
        task=task,
        screenshot=_image_png(_anchor_scene(x=91)),
    ) is None

    result = runtime.run(env._get_obs())

    assert result.status == "partial"
    assert result.stop_reason == "terminal_gaps"
    assert len(env.actions) == 1
    assert agent.pending_flags == [True, False]
    assert runtime.model_turns == 2
    assert any(
        item["kind"] == "visual_anchor_route_replayed"
        for item in runtime.ledger.events
    )
    replay = runtime.ledger.attempts["a2"]
    assert replay.anchor_ref.endswith("/anchor.png")
    assert replay.action["purpose"] == "route"
    restored = ExplorationLedger.load(tmp_path / "exploration_ledger.json")
    assert restored.attempts["a2"].anchor_ref == replay.anchor_ref
    assert restored.attempts["a2"].anchor_offset_px == replay.anchor_offset_px


def test_runtime_completes_one_survey_then_one_operation(tmp_path):
    first = _turn(
        screen=_new_screen(),
        page_report=_report(),
        action={
            "kind": "click", "purpose": "execute", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "invented",
        },
    )
    second = _turn(
        screen=_known_screen(),
        action={
            "kind": "click", "purpose": "execute", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o1",
        },
    )
    third = _turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a1",
            "outcome": "success",
            "task_result": "completed",
            "visible_result": "计时数字开始增加，暂停按钮出现。",
            "corrected_target": "启动秒表（播放图标）",
            "reason": "变化属于开始按钮的预期直接效果。",
        },
        finish=True,
    )
    env = _Env(_png("white"), _png("gray"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=_Agent([
            (first, False), (second, False), (third, True),
        ]),
        max_actions=3,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "complete"
    assert len(env.actions) == 1
    saved = json.loads(
        (tmp_path / "exploration_ledger.json").read_text(encoding="utf-8"))
    assert saved["operations"][0]["status"] == "verified"
    assert saved["operations"][0]["target"] == "启动秒表（播放图标）"
    assert saved["history"][0]["target"] == "启动秒表（播放图标）"
    assert len(saved["states"]) == 1
    assert sum(item["kind"] == "page_inventory_recorded"
               for item in saved["events"]) == 1
    completion = json.loads(
        (tmp_path / "modular_completion.json").read_text(encoding="utf-8"))
    assert completion["bundle_status"] == "compiled"
    graph = json.loads(
        (tmp_path / "modular_graph.json").read_text(encoding="utf-8"))
    assert graph["stop_reason"] == "frontier_empty"
    assert {
        node["page_identity_version"] for node in graph["nodes"]
    } == {"semantic_page_variant_v1"}
    assert completion["bundle"]["projected_elements"] == 1
    assert (tmp_path / "annotated_graph.json").exists()
    assert (tmp_path / "capability_graph.json").exists()
    wrong_kind = parse_turn(_turn(
        screen=_known_screen(),
        action={
            "kind": "input_text", "purpose": "execute", "target": "开始按钮",
            "point_1000": [500, 700], "text": "test", "direction": "",
            "amount": 650, "operation_ref": "o1",
        },
    ), has_pending_action=False).action
    assert "kind=click、action.owner_ref=" in runtime._validate_action(
        runtime.ledger.operation_task("o1"), wrong_kind)


def test_action_limit_stops_before_an_extra_model_turn_after_settlement(
    tmp_path,
):
    report = _report()
    report["regions"][0]["operations"].append({
        "action": "click",
        "target": "重置按钮",
        "handling": "explore",
        "reason": "会重置当前秒表状态。",
    })
    first = _turn(screen=_new_screen(), page_report=report)
    execute = _turn(
        screen=_known_screen(),
        action={
            "kind": "click", "purpose": "execute", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o1",
        },
    )
    settle = _turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a1",
            "outcome": "success",
            "task_result": "completed",
            "visible_result": "计时数字开始增加。",
            "corrected_target": "",
            "reason": "开始操作已生效。",
        },
    )
    over_budget = _turn(
        screen=_known_screen(),
        action={
            "kind": "click", "purpose": "execute", "target": "重置按钮",
            "point_1000": [600, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o2",
        },
    )
    agent = _Agent([
        (first, False),
        (execute, False),
        (settle, True),
        (over_budget, False),
    ])
    env = _Env(_png("white"), _png("gray"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=1,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "partial"
    assert result.stop_reason == "action_limit"
    assert len(env.actions) == 1
    assert runtime.ledger.attempts["a1"].outcome == "success"
    assert runtime.model_turns == 3
    assert len(agent.contexts) == 3


def test_zero_action_budget_still_records_initial_inventory(tmp_path):
    first = _turn(screen=_new_screen(), page_report=_report())
    blocked_action = _turn(
        screen=_known_screen(),
        action={
            "kind": "click", "purpose": "execute", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o1",
        },
    )
    agent = _Agent([(first, False), (blocked_action, False)])
    env = _Env(_png("white"), _png("gray"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=0,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "partial"
    assert result.stop_reason == "action_limit"
    assert runtime.model_turns == 1
    assert len(runtime.ledger.pages) == 1
    assert len(runtime.ledger.states) == 1
    assert env.actions == []


def test_pending_landing_accepts_new_regions_without_state_text_recheck(
        tmp_path):
    material_report = {
        "regions": [
            {
                "name": "秒表显示与控制",
                "summary": "显示运行中的计时数字",
                "operations": [],
            },
            {
                "name": "检查器面板",
                "summary": "新出现的独立右侧面板",
                "operations": [{
                    "action": "click",
                    "target": "关闭检查器",
                    "handling": "record",
                    "reason": "直接关闭当前面板。",
                }],
            },
        ],
        "survey_complete": True,
        "coverage_note": "当前布局已完整清点。",
    }
    previous = {
        "attempt_ref": "a1",
        "outcome": "success",
        "task_result": "completed",
        "visible_result": "秒表开始运行并出现检查器面板。",
        "corrected_target": "",
        "reason": "前后图显示开始操作生效。",
    }
    first = _turn(screen=_new_screen(), page_report=_report())
    execute = _turn(
        screen=_known_screen(),
        action={
            "kind": "click", "purpose": "execute", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o1",
        },
    )
    wrong_known = _turn(
        screen=_known_screen(), page_report=material_report,
        previous=previous)
    finish = _turn(screen=_known_screen(), finish=True)
    env = _Env(_png("white"), _png("gray"))
    agent = _Agent([
        (first, False), (execute, False), (wrong_known, True),
        (finish, False),
    ])
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=2,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "complete"
    assert len(env.actions) == 1
    assert len(runtime.ledger.states) == 1
    assert runtime.ledger.attempts["a1"].target_state_id == "s1"
    assert len(runtime.ledger.states["s1"].region_occurrence_ids) == 2
    assert len(agent.contexts) == 3
    assert not any(
        item["kind"] in {
            "known_state_material_structure_rejected",
            "redundant_page_report_ignored",
        } for item in runtime.ledger.events)


@pytest.mark.parametrize("change", ["none", "wording", "parameter"])
def test_redundant_known_report_without_action_requires_immediate_progress(
        tmp_path, change):
    initial_report = _report()
    repeated_report = _report()
    if change == "wording":
        repeated_report["regions"][0].update(
            summary="同一秒表的另一种描述", memory="显示时间并可开始计时。")
    elif change == "parameter":
        initial_report["regions"][0]["operations"][0].update(
            parameter_status="unknown", parameter_summary="参数尚未观察")
        repeated_report["regions"][0]["operations"][0].update(
            parameter_status="observed", parameter_summary="可选择计时模式")
    first = _turn(screen=_new_screen(), page_report=initial_report)
    waits_again = _turn(screen=_known_screen(), page_report=repeated_report)
    execute = _turn(
        screen=_known_screen(),
        action={
            "kind": "click", "purpose": "execute", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o1",
        },
    )
    settle = _turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a1", "outcome": "success",
            "task_result": "completed", "visible_result": "秒表开始计时。",
            "corrected_target": "", "reason": "前后图显示开始操作生效。",
        },
        finish=True,
    )
    env = _Env(_png("white"), _png("gray"))
    agent = _Agent([
        (first, False), (waits_again, False),
        (execute, False), (settle, True),
    ])
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=3,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "complete"
    assert len(env.actions) == 1
    rejected = any(
        item["kind"] == "redundant_page_report_without_progress_rejected"
        for item in runtime.ledger.events
    )
    assert rejected is (change != "parameter")
    if change != "parameter":
        assert "不能再用 action=null 等待下一轮派发" in agent.contexts[2]["状态栏"]
    else:
        assert runtime.ledger.operations["o1"].parameter_status == "observed"


def test_active_operation_turn_without_any_progress_is_rejected(tmp_path):
    first = _turn(screen=_new_screen(), page_report=_report())
    no_progress = _turn(screen=_known_screen())
    execute = _turn(
        screen=_known_screen(),
        action={
            "kind": "click", "purpose": "execute", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o1",
        },
    )
    settle = _turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a1", "outcome": "success",
            "task_result": "completed", "visible_result": "秒表开始计时。",
            "corrected_target": "", "reason": "前后图显示开始操作生效。",
        },
        finish=True,
    )
    env = _Env(_png("white"), _png("gray"))
    agent = _Agent([
        (first, False), (no_progress, False),
        (execute, False), (settle, True),
    ])
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=3,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "complete"
    assert len(env.actions) == 1
    assert "没有产生任何探索进展" in agent.contexts[2]["状态栏"]
    assert any(
        item["kind"] == "operation_turn_without_progress_rejected"
        for item in runtime.ledger.events
    )


def test_runtime_can_release_current_operation_without_another_action(tmp_path):
    report = _report()
    report["regions"][0]["operations"].append({
        "action": "click",
        "target": "重置按钮",
        "handling": "explore",
        "reason": "会重置当前计时状态。",
    })
    first = _turn(screen=_new_screen(), page_report=report)
    defer_first = _turn(
        screen=_known_screen(), current_task_result="deferred")
    fail_second = _turn(
        screen=_known_screen(), current_task_result="failed")
    fail_first = _turn(
        screen=_known_screen(), current_task_result="failed")
    finish = _turn(screen=_known_screen(), finish=True)
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=_Agent([
            (first, False), (defer_first, False), (fail_second, False),
            (fail_first, False), (finish, False),
        ]),
        max_actions=2,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "partial"
    assert result.stop_reason == "terminal_gaps"
    assert len(result.gaps) == 2
    assert result.actions_used == 0
    # A blocked Region round does not immediately reopen a deferred obligation
    # without new applicability evidence merely because other tasks ran out.
    assert [runtime.ledger.operations[item].status for item in ("o1", "o2")] == [
        "deferred", "failed"]
    settled = [
        item for item in runtime.ledger.events
        if item["kind"] == "current_task_settled"
    ]
    assert [item["payload"]["result"] for item in settled] == [
        "deferred", "failed"]


def test_runtime_accepts_natural_same_page_state_with_open_task(tmp_path):
    empty_report = _report(include_start=False)
    first = _turn(screen=_new_screen(), page_report=_report())
    result_screen = {
        **_known_screen(),
        "identity": "new_state",
        "state_ref": "",
        "state_name": "异步结果已显示",
        "state_summary": "无需新动作，页面自然显示了结果列表",
    }
    third = _turn(screen=result_screen, page_report=empty_report,
                  current_task_result="failed")
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=_Agent([
            (first, False), (third, False),
        ]),
        max_actions=1,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "partial"
    assert result.actions_used == 0
    assert len(runtime.ledger.pages) == 1
    assert len(runtime.ledger.states) == 2
    assert runtime.ledger.survey_task("s1").status == "done"
    assert runtime.ledger.states["s2"].survey_complete is True
    completion = json.loads(
        (tmp_path / "modular_completion.json").read_text(encoding="utf-8"))
    assert completion["bundle_status"] == "compiled"


def test_runtime_allows_repeated_survey_actions_before_complete_report(tmp_path):
    scroll = {
        "kind": "scroll", "purpose": "", "owner_ref": "r1",
        "target": "页面内容区", "point_1000": [500, 700],
        "text": "", "direction": "up", "amount": 300, "operation_ref": "",
    }
    first = _turn(screen=_new_screen(), page_report=_survey_scroll_report())
    second = _turn(screen=_known_screen(), action=scroll)
    third = _turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a1", "outcome": "no_effect", "task_result": "retry",
            "visible_result": "页面没有滚动。", "reason": "换一个位置继续观察。",
        },
        action={**scroll, "point_1000": [500, 500]},
    )
    fourth = _turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a2", "outcome": "no_effect", "task_result": "retry",
            "visible_result": "页面仍没有滚动。", "reason": "已确认当前方向到达边界。",
        },
        page_report=_survey_scroll_report(complete=True, known=True),
    )
    fifth = _turn(screen=_known_screen(), finish=True)
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(
        env=env, app_name="clocks", platform="desktop",
        output_root=str(tmp_path),
        agent=_Agent([
            (first, False), (second, False), (third, True),
            (fourth, True), (fifth, False),
        ]),
        max_actions=3,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "complete"
    assert result.actions_used == 2
    assert len(env.actions) == 2
    assert runtime.ledger.states["s1"].survey_complete is True


def test_runtime_does_not_override_no_effect_from_global_pixel_change(tmp_path):
    complete_report = _survey_scroll_report(complete=True, known=True)
    incomplete_report = _survey_scroll_report()
    scroll = {
        "kind": "scroll", "purpose": "", "owner_ref": "r1",
        "target": "页面内容区",
        "point_1000": [500, 700], "text": "", "direction": "down",
        "amount": 300, "operation_ref": "",
    }
    first = _turn(screen=_new_screen(), page_report=incomplete_report)
    execute = _turn(screen=_known_screen(), action=scroll)
    no_effect = _turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a1",
            "outcome": "no_effect", "task_result": "retry",
            "visible_result": "页面异步更新，但目标 Region 没有滚动。",
            "reason": "全局像素变化不是该 Region 滚动成功的证据。",
        },
        page_report=complete_report,
    )
    finish = _turn(
        screen=_known_screen(), page_report=complete_report, finish=True)
    agent = _Agent([
        (first, False), (execute, False), (no_effect, True), (finish, False),
    ])
    env = _Env(_png("white"), _png("black"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=2,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "complete"
    assert result.actions_used == 1
    assert runtime.ledger.attempts["a1"].outcome == "no_effect"
    rejected = [
        item for item in runtime.ledger.events
        if item["kind"] == "no_effect_visual_change_rejected"
    ]
    assert rejected == []


def test_unbound_route_ignores_reported_operation_completion(
        tmp_path, monkeypatch):
    ledger = _seed_ledger()
    task = TaskScheduler().choose(ledger)
    attempt = ActionAttempt(
        attempt_id="a-route", task_id=task.task_id, source_state_id="s1",
        purpose="route", action={
            "kind": "scroll", "purpose": "route", "owner_ref": "",
            "operation_ref": "", "target": "查看上方分类",
            "point_1000": [180.0, 400.0], "text": "", "direction": "up",
            "amount": 500,
        }, before_ref="action_attempts/a-route/before.png",
    )
    ledger.attempts[attempt.attempt_id] = attempt
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()
    runtime.artifacts = ArtifactStore(str(tmp_path))
    runtime.pending_attempt_id = attempt.attempt_id
    runtime.pending_before = b"before"
    runtime.pending_action_error = ""
    runtime.state_identity_rechecks = set()
    runtime.pending_report_correction = {}
    monkeypatch.setattr(
        "gui_rewalk.src.core.explore.runtime.visible_change_ratio",
        lambda *_args: 0.05,
    )
    turn = parse_turn(
        _turn(
            screen=_known_screen(),
            previous={
                "attempt_ref": attempt.attempt_id,
                "element_actions": [],
                "region_actions": [{
                    "region_ref": "r1", "action": "scroll",
                    "direction": "up", "completed": True,
                }],
                "function_info": [], "parameter_info": None,
                "reason": "列表已经向上移动。",
            },
        ),
        has_pending_action=True,
        pending_attempt_id=attempt.attempt_id,
    )

    runtime._settle_pending(
        turn, screenshot=b"after", frame_ref="screenshots/after.png")

    assert attempt.outcome == "uncertain"
    assert ledger.operations[task.operation_id].status == "pending"
    assert task.status == "active"
    assert runtime.pending_attempt_id == ""
    assert any(
        item["kind"] == "unbound_action_completed_owners_ignored"
        for item in ledger.events)


def test_runtime_rejects_android_scroll_while_soft_keyboard_visible():
    class _KeyboardEnv:
        keyboard_visible = True

        def is_soft_keyboard_visible(self):
            return self.keyboard_visible

    runtime = object.__new__(ExplorationRuntime)
    runtime.platform = "android"
    runtime.env = _KeyboardEnv()
    runtime.ledger = _seed_ledger()
    runtime.ledger.operations["o-scroll"] = Operation(
        "o-scroll", "r1", "scroll", "搜索结果列表", "recorded",
        source_occurrence_ids=["ro1"], variant_id="rv1",
        canonical_operation_id="co-scroll", scope="region",
        direction="down", parameter_status="none", parameter_summary="无参数",
    )
    runtime.ledger.regions["r1"].operation_ids.append("o-scroll")
    runtime.ledger.region_variants["rv1"].operation_ids.append("o-scroll")
    task = Task("t-keyboard", "survey_page", "active", "s1")
    action = ActionRequest(
        kind="scroll", purpose="survey", target="搜索结果列表",
        point_1000=[500, 500], text="", direction="down", amount=500,
        operation_ref="o-scroll", owner_ref="r1",
    )

    issue = runtime._validate_action(task, action)

    assert "软键盘" in issue
    runtime.env.keyboard_visible = False
    assert runtime._validate_action(task, action) == ""


def test_runtime_keeps_main_agent_observation_after_incomplete_region_scroll(
    tmp_path,
):
    complete_report = _survey_scroll_report(complete=True, known=True)
    complete_report["regions"][0]["memory"] = "滚动未成功，当前显示异步更新后的内容。"
    first = _turn(screen=_new_screen(), page_report=_survey_scroll_report())
    execute = _turn(
        screen=_known_screen(),
        action={
            "kind": "scroll", "purpose": "", "owner_ref": "r1",
            "target": "连续内容", "point_1000": [500, 600],
            "text": "", "direction": "down", "amount": 500, "operation_ref": "",
        },
    )
    observed = _turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a1", "element_actions": [],
            "region_actions": [{
                "region_ref": "r1", "action": "scroll",
                "direction": "down", "completed": False,
            }],
            "function_info": [], "parameter_info": None,
            "reason": "列表没有位移，但当前画面内容已异步更新。",
        },
        page_report=complete_report,
    )
    finish = _turn(screen=_known_screen(), finish=True)
    env = _Env(_png("white"), _png("black"))
    runtime = ExplorationRuntime(
        env=env, app_name="clocks", platform="desktop",
        output_root=str(tmp_path),
        agent=_Agent([
            (first, False), (execute, False), (observed, True), (finish, False),
        ]),
        max_actions=2,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "partial"
    assert result.stop_reason == "action_result_unconfirmed"
    assert result.actions_used == 1
    assert runtime.ledger.attempts["a1"].outcome == "uncertain"
    assert "异步更新" in runtime.ledger.regions["r1"].memory
    assert not any(
        item["kind"] == "scroll_visual_mismatch_quarantined"
        for item in runtime.ledger.events)


def test_runtime_rejects_scroll_without_region_owner_before_dispatch():
    runtime = object.__new__(ExplorationRuntime)
    runtime.platform = "desktop"
    runtime.ledger = _seed_ledger()
    task = Task("t-survey", "survey_page", "active", "s1")
    action = ActionRequest(
        kind="scroll", purpose="survey", target="页面内容",
        point_1000=[500, 600], text="", direction="down", amount=500,
        operation_ref="", owner_ref="",
    )

    assert "不允许空 owner 滚动" in runtime._validate_action(task, action)


def test_runtime_quarantines_delivery_error_landing_before_state_binding(
    tmp_path,
):
    input_report = {
        "regions": [{
            "name": "搜索工具栏",
            "summary": "提供搜索输入",
            "memory": "搜索输入框尚未填写。",
            "operations": [{
                "action": "input_text",
                "target": "Search 输入框",
                "handling": "explore",
                "reason": "代表输入会显示搜索结果。",
            }],
        }],
        "survey_complete": True,
        "coverage_note": "搜索页清点完成。",
    }
    first = _turn(screen=_new_screen(), page_report=input_report)
    execute = _turn(
        screen=_known_screen(),
        action={
            "kind": "input_text", "purpose": "execute",
            "owner_ref": "el1", "target": "Search 输入框",
            "point_1000": [500, 200], "text": "GUITRAV",
            "direction": "", "amount": 650, "operation_ref": "o1",
        },
    )
    selector_report = {
        "regions": [{
            "name": "月份年份选择器",
            "summary": "错误点位打开的选择器",
            "memory": "不应进入目标输入 Operation 的图。",
            "operations": [],
        }],
        "survey_complete": True,
        "coverage_note": "错误 landing。",
    }
    wrong_landing = _turn(
        screen={
            **_known_screen(),
            "identity": "new_state",
            "state_ref": "",
            "state_name": "月份年份选择器",
            "state_summary": "错误 input_text 点位打开了选择器。",
        },
        previous={
            "attempt_ref": "a1",
            "element_actions": [{
                "element_ref": "el1", "action": "input_text",
                "completed": True,
            }],
            "region_actions": [],
            "function_info": [{
                "region_ref": "r1",
                "memory": "错误 landing 不应写入。",
            }],
            "parameter_info": None,
            "reason": "错误点位没有聚焦输入框。",
        },
        page_report=selector_report,
    )
    release = _turn(
        screen=_known_screen(), current_task_result="failed")
    finish = _turn(screen=_known_screen(), finish=True)

    class _DeliveryErrorEnv(_Env):
        def step(self, action, pause=0):
            observation = super().step(action, pause=pause)
            observation["action_error"] = "input_text_target_not_focused"
            return observation

    agent = _Agent([
        (first, False), (execute, False), (wrong_landing, True),
        (release, False), (finish, False),
    ])
    env = _DeliveryErrorEnv(_png("white"), _png("black"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="android",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=2,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "partial"
    assert len(runtime.ledger.states) == 1
    assert not any(
        region.name == "月份年份选择器"
        for region in runtime.ledger.regions.values())
    assert runtime.ledger.attempts["a1"].outcome == "no_effect"
    assert any(
        item["kind"] == "action_delivery_error_landing_quarantined"
        for item in runtime.ledger.events)
    assert "异常 landing" in agent.contexts[3]["状态栏"]


def test_runtime_rejects_fourth_no_effect_survey_in_same_direction(tmp_path):
    incomplete = _survey_scroll_report()
    complete_report = _survey_scroll_report(complete=True, known=True)
    scroll_up = {
        "kind": "scroll", "purpose": "", "owner_ref": "r1",
        "target": "页面内容区",
        "point_1000": [500, 700], "text": "", "direction": "up",
        "amount": 300, "operation_ref": "",
    }
    no_effect = lambda attempt_ref: {
        "attempt_ref": attempt_ref,
        "outcome": "no_effect", "task_result": "retry",
        "visible_result": "页面没有滚动。",
        "reason": "需要改变调查参数。",
    }
    first = _turn(screen=_new_screen(), page_report=incomplete)
    execute = _turn(screen=_known_screen(), action=scroll_up)
    second = _turn(
        screen=_known_screen(), previous=no_effect("a1"),
        action={**scroll_up, "point_1000": [500, 650]})
    third = _turn(
        screen=_known_screen(), previous=no_effect("a2"),
        action={**scroll_up, "point_1000": [500, 800]})
    rejected = _turn(
        screen=_known_screen(), previous=no_effect("a3"),
        action={**scroll_up, "point_1000": [500, 850]})
    corrected = _turn(
        screen=_known_screen(),
        action={**scroll_up, "direction": "down"})
    complete = _turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a4",
            "outcome": "success", "task_result": "retry",
            "visible_result": "已显示视口下方的同质内容。",
            "reason": "已有足够证据完成清点。",
        },
        page_report=complete_report,
    )
    finish = _turn(screen=_known_screen(), finish=True)
    agent = _Agent([
        (first, False), (execute, False), (second, True),
        (third, True), (rejected, True),
        (corrected, False), (complete, True), (finish, False),
    ])
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=6,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "complete"
    assert result.actions_used == 4
    assert len(env.actions) == 4
    assert [
        action["parameters"]["dy"] for action in env.actions
    ] == [2, 2, 2, -2]
    assert "查看视口下方用 down" in agent.contexts[5]["状态栏"]
    rejected_events = [
        item for item in runtime.ledger.events
        if item["kind"] == "action_rejected"
    ]
    assert len(rejected_events) == 1
    assert rejected_events[0]["payload"]["task_id"] == "t1"


def test_runtime_registers_region_before_region_owned_survey_scroll(tmp_path):
    region = {
        "region_ref": "",
        "name": "可滚动内容",
        "summary": "包含被截断的连续内容",
        "memory": "当前只看到顶部，需要向下调查。",
        "elements": [],
        "region_operations": [{
            "operation_ref": "",
            "action": "scroll",
            "target": "查看下方内容",
            "direction": "down",
            "handling": "record",
            "reason": "截图显示下方还有连续内容。",
            "parameter_status": "none",
            "parameter_summary": "无参数",
        }],
    }
    incomplete = {
        "regions": [region],
        "survey_complete": False,
        "coverage_note": "先登记 Region，再执行调查滚动。",
    }
    complete = {
        "regions": [{
            **region,
            "region_ref": "r1",
            "region_operations": [{
                **region["region_operations"][0],
                "operation_ref": "co1",
            }],
        }],
        "survey_complete": True,
        "coverage_note": "已看到下方代表内容。",
    }
    first = _turn(screen=_new_screen(), page_report=incomplete)
    second = _turn(
        screen=_known_screen(),
        action={
            "kind": "scroll", "purpose": "", "owner_ref": "r1",
            "target": "查看下方内容", "point_1000": [500, 700],
            "text": "", "direction": "down", "amount": 300,
            "operation_ref": "",
        },
    )
    third = _turn(
        screen=_known_screen(),
        previous={
            "attempt_ref": "a1",
            "element_actions": [],
            "region_actions": [{
                "region_ref": "r1", "action": "scroll",
                "direction": "down", "completed": True,
            }],
            "function_info": [], "parameter_info": None,
            "reason": "内容已向上移动，并显示下方代表内容。",
        },
        page_report=complete,
        finish=True,
    )
    agent = _Agent([(first, False), (second, False), (third, True)])
    env = _Env(_png("white"), _png("black"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=2,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "complete"
    assert result.actions_used == 1
    assert len(env.actions) == 1
    assert runtime.ledger.states["s1"].survey_complete is True
    attempt = runtime.ledger.attempts["a1"]
    assert attempt.action["owner_ref"] == "r1"
    assert attempt.action["operation_ref"] == "o1"
    assert attempt.purpose == "survey"
    assert runtime.ledger.operations["o1"].status == "verified"


def test_incomplete_report_correction_does_not_promise_operation_dispatch(tmp_path):
    report = _report()
    incomplete = {**report, "survey_complete": False}
    first = _turn(
        screen=_new_screen(),
        page_report=incomplete,
        action={
            "kind": "click", "purpose": "execute", "target": "开始按钮",
            "owner_ref": "el1",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o1",
        },
    )
    complete = _turn(screen=_known_screen(), page_report=report)
    fail_operation = _turn(
        screen=_known_screen(), current_task_result="failed")
    finish = _turn(screen=_known_screen(), finish=True)
    agent = _Agent([
        (first, False), (complete, False),
        (fail_operation, False), (finish, False),
    ])
    env = _Env(_png("white"), _png("white"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=agent,
        max_actions=1,
    )

    result = runtime.run(env._get_obs())

    assert result.status == "partial"
    assert result.stop_reason == "terminal_gaps"
    assert len(result.gaps) == 1
    correction = agent.contexts[1]["状态栏"]
    assert "survey_complete=false" in correction
    assert "下一轮使用当前卡片的 owner_ref" in correction
    assert "无需为了放行点击把未完成的调查标为完整" in correction
    assert "下一轮使用框架派发" not in correction


def test_runtime_settles_external_result_before_recovery(tmp_path):
    first = _turn(screen=_new_screen(), page_report=_report())
    second = _turn(screen=_known_screen(), page_report=_report())
    third = _turn(
        screen=_known_screen(),
        action={
            "kind": "click", "purpose": "execute", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o1",
        },
    )
    external = {
        "app_scope": "target_app",
        "strategy": "误把外部选择器识别成目标应用页面。",
        "screen": {
            "identity": "new_page",
            "page_ref": "",
            "page_name": "系统选择器",
            "page_summary": "外部系统选择器。",
            "state_ref": "",
            "state_name": "默认",
            "state_summary": "外部系统选择器默认状态。",
        },
        "previous_action": {
            "attempt_ref": "a1",
            "outcome": "success",
            "task_result": "completed",
            "visible_result": "打开了系统选择器。",
            "reason": "目标入口的外部效果已经可见。",
        },
        "page_report": None,
        "action": None,
        "finish": False,
        "reason": "外部界面不写入目标应用地图。",
    }
    fifth = _turn(screen=_known_screen(), finish=True)
    before = _png("white")
    env = _Env(before, _png("gray"))
    runtime = ExplorationRuntime(
        env=env,
        app_name="clocks",
        platform="desktop",
        output_root=str(tmp_path),
        agent=_Agent([
            (first, False), (second, False), (third, False),
            (external, True), (fifth, False),
        ]),
        max_actions=2,
    )

    class _RecoverScope:
        last_reason = "测试中的委托外部界面"

        def __init__(self):
            self.calls = 0
            self.checks = 0

        def check(self):
            self.checks += 1
            return "external" if env.actions and not self.calls else "target"

        def recover(self):
            self.calls += 1
            env.observation = {"screenshot": before}
            return env.observation

    recovery = _RecoverScope()
    runtime.scope = recovery

    result = runtime.run(env._get_obs())

    # Recovery returns to observation before deciding the run is complete.
    assert result.status == "complete"
    assert result.stop_reason == "complete"
    assert runtime.agent.contexts[-1]["推进阶段"]["phase"] == "observe"
    assert len(runtime.agent.contexts) == 5
    assert recovery.calls == 1
    assert runtime.ledger.operation_task("o1").status == "done"
    assert runtime.ledger.operations["o1"].status == "verified"
    assert len(runtime.ledger.transitions) == 0
    assert all(page.name != "系统选择器" for page in runtime.ledger.pages.values())
