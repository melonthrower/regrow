"""Existing modular exploration contracts: tasks routes."""


import pytest

from gui_rewalk.src.core.explore.contracts import parse_turn
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.models import (
    ActionAttempt,
    CanonicalOperation,
    Operation,
    Region,
    PageState,
    RegionOccurrence,
    RegionVariant,
    Task,
    Transition,
)
from gui_rewalk.src.core.explore.region_routes import (
    page_region_refs,
    plan_region_route,
    region_relations,
    refresh_transition_region_effects,
)
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.status import known_graph
from gui_rewalk.src.core.explore.tasks import (
    TaskScheduler,
    directed_state_distances,
    logical_task_count,
)

from .explore_fixtures import (
    _Env,
    _contextual_region_route_ledger,
    _directed_route_ledger,
    _known_screen,
    _ledger_with_current_canonical_binding,
    _parameter_ledger,
    _png,
    _region_reveal_runtime,
    _seed_ledger,
    _turn,
)


def test_region_effects_keep_external_changes_out_of_action_edges():
    from gui_rewalk.src.core.explore.region_routes import record_region_effects
    ledger = _contextual_region_route_ledger()
    edge = ledger.transitions[0]
    edge.revealed_region_ids = []
    edge.hidden_region_ids = []
    target = ledger.state_occurrences(edge.target_state_id)[0].region_id
    source = ledger.state_occurrences(edge.source_state_id)[0].region_id
    refresh_transition_region_effects(ledger, edge)
    assert edge.revealed_region_ids == []
    record_region_effects(ledger, edge.attempt_id, [
        {"region_ref": target, "report_index": None, "change": "appeared", "cause": "action"},
        {"region_ref": source, "report_index": None, "change": "disappeared", "cause": "external"},
    ], [])
    refresh_transition_region_effects(ledger, edge)
    assert edge.revealed_region_ids == [target]
    assert edge.hidden_region_ids == []
    assert ledger.events[-1]["payload"]["changes"][1]["cause"] == "external"


def test_model_can_change_visible_focus_without_completing_old_work():
    from dataclasses import replace
    ledger = _seed_ledger()
    old = ledger.tasks["t2"]
    old.status = "active"
    ledger.current_task_id = old.task_id
    operation = ledger.operations[old.operation_id]
    ledger.operations["o-next"] = replace(operation, operation_id="o-next", canonical_operation_id="co-next")
    ledger.tasks["t-next"] = Task("t-next", "explore_operation", "pending", "s1", "o-next")
    selected = TaskScheduler().select_visible_operation(ledger, "co-next", "The other visible branch adds new information")
    assert selected.task_id == "t-next"
    assert old.status == "pending"
    assert not ledger.attempts


def test_selecting_current_focus_keeps_task_even_before_survey_finishes():
    from copy import deepcopy
    ledger = _seed_ledger()
    held = ledger.tasks["t2"]
    held.status = "active"
    ledger.current_task_id = held.task_id
    ledger.states["s1"].survey_complete = False
    ref = ledger.operations[held.operation_id].canonical_operation_id
    before = deepcopy(vars(ledger))
    assert TaskScheduler().select_visible_operation(ledger, ref, "continue") is held
    assert vars(ledger) == before


@pytest.mark.parametrize("case, detail", [
    ("survey", "清点尚未完成"), ("unknown", "不存在"),
    ("recorded", "没有开放探索任务"), ("elsewhere", "来源 State"),
    ("duplicate", "匹配到 2 个"),
])
def test_task_selection_feedback_names_field_cause_and_continuation(case, detail):
    from dataclasses import replace
    ledger = _seed_ledger()
    held = ledger.tasks["t2"]
    operation = ledger.operations[held.operation_id]
    ref = operation.canonical_operation_id
    if case == "survey":
        ledger.states["s1"].survey_complete = False
    elif case == "unknown":
        ref = "co-missing"
    elif case == "recorded":
        held.status = "done"
        operation.status = "recorded"
    elif case == "elsewhere":
        ledger.current_state_id = "s-elsewhere"
        ledger.states["s-elsewhere"] = replace(ledger.states["s1"], state_id="s-elsewhere")
    else:
        ledger.tasks["t-copy"] = replace(held, task_id="t-copy")
    with pytest.raises(ValueError) as caught:
        TaskScheduler().select_visible_operation(ledger, ref, "switch")
    message = str(caught.value)
    assert "next_operation_ref" in message
    assert detail in message
    assert "留空" in message


def test_repeated_current_ref_reaches_normal_action_binding(tmp_path, monkeypatch):
    from .explore_fixtures import _Agent
    ledger = _seed_ledger()
    task = ledger.tasks["t2"]
    task.status = "active"
    ledger.current_task_id = task.task_id
    operation = ledger.operations[task.operation_id]
    raw = _turn(screen=_known_screen(), action={
        "kind": "click", "owner_ref": operation.element_id, "point_1000": [500, 500]})
    raw["next_operation_ref"] = operation.canonical_operation_id
    runtime = ExplorationRuntime(env=_Env(_png("white"), _png("black")), app_name="fixture", platform="desktop",
                                 output_root=str(tmp_path), agent=_Agent([(raw, False)]), max_actions=1)
    runtime.ledger = ledger

    class BoundActionReached(BaseException):
        pass

    def execute(**kwargs):
        assert kwargs["action"].operation_ref == operation.operation_id
        assert kwargs["task"].task_id == task.task_id
        raise BoundActionReached()

    monkeypatch.setattr(runtime, "_execute", execute)
    with pytest.raises(BoundActionReached):
        runtime.run(runtime.env._get_obs())
    assert not any(event["kind"] == "action_rejected" for event in ledger.events)


def test_survey_selection_correction_is_in_next_model_context(tmp_path):
    from .explore_fixtures import _Agent
    ledger = _seed_ledger()
    ledger.states["s1"].survey_complete = False
    task = Task("t-survey", "survey_page", "active", "s1")
    ledger.tasks[task.task_id] = task
    ledger.current_task_id = task.task_id
    runtime = ExplorationRuntime(env=_Env(_png("white"), _png("black")), app_name="fixture", platform="desktop",
                                 output_root=str(tmp_path), agent=_Agent([]), max_actions=1)
    runtime.ledger = ledger
    with pytest.raises(ValueError) as caught:
        TaskScheduler().select_visible_operation(ledger, "co1", "scroll to see more")
    runtime._record_action_rejection(task, str(caught.value))
    context = runtime._context(task, "target")
    assert "next_operation_ref 留空" in context["状态栏"]
    assert "action.owner_ref" in context["状态栏"]
    assert not ledger.attempts
    assert not ledger.states["s1"].survey_complete


def test_v5_completion_reports_one_canonical_parameter_gap():
    ledger = _parameter_ledger("unknown")
    operation = next(iter(ledger.operations.values()))

    gaps = TaskScheduler.gaps(ledger)

    assert gaps == [
        f"{operation.canonical_operation_id} parameter_unknown: "
        "完整值域尚未观察"
    ]


def test_v5_completion_keeps_parameter_conflict_as_nonblocking_audit():
    ledger = _parameter_ledger("none")
    first = next(iter(ledger.operations.values()))
    identity = ledger.canonical_operations[first.canonical_operation_id]
    second = Operation(
        operation_id="o-conflict",
        region_id=first.region_id,
        action=first.action,
        target=first.target,
        status="verified",
        canonical_operation_id=identity.canonical_operation_id,
        parameter_status="observed",
        parameter_summary="可选 Control volume、Snooze、Dismiss",
        parameter_evidence_refs=["screenshots/selector.png"],
        source_occurrence_ids=list(first.source_occurrence_ids),
        variant_id=first.variant_id,
    )
    ledger.operations[second.operation_id] = second
    identity.operation_ids.append(second.operation_id)

    assert TaskScheduler.gaps(ledger) == []


def test_directed_state_distance_does_not_infer_reverse_reachability():
    ledger = _directed_route_ledger()

    assert directed_state_distances(
        ledger, "s1") == {"s1": 0, "s2": 1, "s3": 2}
    assert directed_state_distances(ledger, "s3") == {"s3": 0}

    states = {
        item["state_ref"]: item
        for item in known_graph(ledger)["states"]
    }
    assert states["s1"]["distance"] is None


def test_scheduler_returns_to_earlier_ancestor_frontier_before_deeper_work():
    ledger = _directed_route_ledger()
    ledger.pages["p1"].state_ids.extend(["s4", "s5"])
    for state_id in ("s4", "s5"):
        ledger.states[state_id] = PageState(
            state_id=state_id,
            page_id="p1",
            name=state_id,
            summary=f"State {state_id}",
            screenshot_ref=f"screenshots/{state_id}.png",
            survey_complete=True,
            inventory_passes=1,
        )
    ledger.transitions.extend([
        Transition(
            transition_id="e34", source_state_id="s3",
            target_state_id="s4", attempt_id="a34",
            action={"kind": "click", "target": "Next"},
            visible_result="Reached s4",
        ),
        Transition(
            transition_id="e45", source_state_id="s4",
            target_state_id="s5", attempt_id="a45",
            action={"kind": "click", "target": "Next"},
            visible_result="Reached s5",
        ),
    ])
    ledger.tasks["t-unreachable"] = Task(
        task_id="t-unreachable", kind="survey_page", status="pending",
        state_id="s1", created_seq=1,
    )
    ledger.tasks["t-reachable"] = Task(
        task_id="t-reachable", kind="survey_page", status="pending",
        state_id="s5", created_seq=2,
    )

    chosen = TaskScheduler().choose(ledger)

    assert chosen.task_id == "t-unreachable"


def test_scheduler_ignores_unrelated_unreachable_older_state():
    ledger = _directed_route_ledger()
    ledger.states["detached"] = PageState(
        state_id="detached", page_id="p1", name="detached",
        summary="与当前路径无连接", screenshot_ref="screenshots/detached.png",
        survey_complete=True, inventory_passes=1,
    )
    ledger.pages["p1"].state_ids.extend(["detached", "s4"])
    ledger.states["s4"] = PageState(
        state_id="s4", page_id="p1", name="s4", summary="可达目标",
        screenshot_ref="screenshots/s4.png", survey_complete=True,
        inventory_passes=1,
    )
    ledger.transitions.append(Transition(
        transition_id="e34", source_state_id="s3", target_state_id="s4",
        attempt_id="a34", action={"kind": "click", "target": "Next"},
        visible_result="Reached s4",
    ))
    ledger.tasks["t-detached"] = Task(
        task_id="t-detached", kind="survey_page", status="pending",
        state_id="detached", created_seq=1,
    )
    ledger.tasks["t-reachable"] = Task(
        task_id="t-reachable", kind="survey_page", status="pending",
        state_id="s4", created_seq=2,
    )

    chosen = TaskScheduler().choose(ledger)

    assert chosen.task_id == "t-reachable"


def test_scheduler_prefers_new_current_region_at_same_distance():
    ledger = _seed_ledger()
    ledger.current_task_id = ""
    ledger.states["s2"] = PageState(
        state_id="s2", page_id="p1", name="菜单打开",
        summary="当前状态新显露一个菜单区块",
        screenshot_ref="screenshots/menu.png",
        region_occurrence_ids=["ro2", "ro3"],
        survey_complete=True, inventory_passes=1,
    )
    ledger.pages["p1"].state_ids.append("s2")
    ledger.current_state_id = "s2"
    ledger.occurrences["ro2"] = RegionOccurrence(
        occurrence_id="ro2", region_id="r1", state_id="s2",
        name="秒表显示与控制", summary="旧背景区块仍可见",
    )
    ledger.regions["r1"].occurrence_ids.append("ro2")
    ledger.operations["o1"].source_occurrence_ids.append("ro2")
    ledger.regions["r2"] = Region(
        region_id="r2", name="新显露菜单", summary="当前状态新增的前景区块",
        operation_ids=["o2"], occurrence_ids=["ro3"],
    )
    ledger.occurrences["ro3"] = RegionOccurrence(
        occurrence_id="ro3", region_id="r2", state_id="s2",
        name="新显露菜单", summary="当前状态新增的前景区块",
    )
    ledger.operations["o2"] = Operation(
        operation_id="o2", region_id="r2", action="click",
        target="菜单项", status="pending", source_occurrence_ids=["ro3"],
    )
    ledger.tasks["t3"] = Task(
        task_id="t3", kind="explore_operation", status="pending",
        state_id="s2", operation_id="o2", created_seq=99,
    )

    chosen = TaskScheduler().choose(ledger)

    assert chosen.operation_id == "o2"


def test_scheduler_suppresses_verified_canonical_sibling_without_result_reuse():
    ledger = _seed_ledger()
    known = ledger.operations["o1"]
    known.status = "verified"
    known.result = "搜索框显示 Beijing 结果。"
    ledger.operation_task("o1").status = "done"
    duplicate = Operation(
        operation_id="o2",
        region_id=known.region_id,
        action=known.action,
        target=known.target,
        status="pending",
        source_occurrence_ids=["ro1"],
        canonical_operation_id=known.canonical_operation_id,
        scope=known.scope,
        element_id=known.element_id,
    )
    ledger.operations["o2"] = duplicate
    ledger.canonical_operations[
        known.canonical_operation_id].operation_ids.append("o2")
    ledger.tasks["t-duplicate"] = Task(
        task_id="t-duplicate",
        kind="explore_operation",
        status="pending",
        state_id="s1",
        operation_id="o2",
        created_seq=99,
    )

    chosen = TaskScheduler().choose(ledger)

    assert chosen is None
    assert ledger.tasks["t-duplicate"].status == "done"
    assert duplicate.status == "recorded"
    assert duplicate.result == ""
    assert any(
        item["kind"] == "canonical_operation_task_suppressed"
        and item["payload"].get("operation_id") == "o2"
        and item["payload"].get("verified_operation_id") == "o1"
        for item in ledger.events
    )


def test_logical_tasks_group_same_canonical_operation_across_states():
    ledger = ExplorationLedger()
    ledger.regions["r1"] = Region(
        region_id="r1", name="应用导航", summary="跨状态共享导航")
    ledger.canonical_operations["co1"] = CanonicalOperation(
        canonical_operation_id="co1", region_id="r1", action="click",
        target="Stopwatch 页签", operation_ids=["o1", "o2"])
    ledger.operations["o1"] = Operation(
        operation_id="o1", region_id="r1", action="click",
        target="Stopwatch 页签", status="deferred",
        canonical_operation_id="co1",
        parameter_status="none", parameter_summary="无参数")
    ledger.operations["o2"] = Operation(
        operation_id="o2", region_id="r1", action="click",
        target="Stopwatch 页签", status="pending",
        canonical_operation_id="co1",
        parameter_status="none", parameter_summary="无参数")
    ledger.tasks["survey-s1"] = Task(
        task_id="survey-s1", kind="survey_page", status="done",
        state_id="s1", created_seq=1)
    ledger.tasks["t1"] = Task(
        task_id="t1", kind="explore_operation", status="deferred",
        state_id="s1", operation_id="o1", created_seq=2)
    ledger.tasks["t2"] = Task(
        task_id="t2", kind="explore_operation", status="pending",
        state_id="s2", operation_id="o2", created_seq=3)

    assert logical_task_count(ledger) == 2
    assert TaskScheduler.gaps(ledger) == [
        "co1 explore_operation bindings=o1,o2: pending"]


def test_verified_binding_closes_logical_gap_but_keeps_failed_evidence():
    ledger = ExplorationLedger()
    ledger.regions["r1"] = Region(
        region_id="r1", name="应用导航", summary="跨状态共享导航")
    ledger.canonical_operations["co1"] = CanonicalOperation(
        canonical_operation_id="co1", region_id="r1", action="click",
        target="Stopwatch 页签", operation_ids=["o1", "o2"])
    ledger.operations["o1"] = Operation(
        operation_id="o1", region_id="r1", action="click",
        target="Stopwatch 页签", status="failed",
        canonical_operation_id="co1", result="旧 Stage 执行失败",
        parameter_status="none", parameter_summary="无参数")
    ledger.operations["o2"] = Operation(
        operation_id="o2", region_id="r1", action="click",
        target="Stopwatch 页签", status="verified",
        canonical_operation_id="co1", result="另一 Stage 已验证",
        parameter_status="none", parameter_summary="无参数")
    ledger.tasks["t1"] = Task(
        task_id="t1", kind="explore_operation", status="failed",
        state_id="s1", operation_id="o1", reason="旧 Stage 执行失败",
        created_seq=1)

    assert TaskScheduler.gaps(ledger) == []
    assert ledger.tasks["t1"].status == "failed"
    assert ledger.operations["o1"].result == "旧 Stage 执行失败"


def test_deferred_bindings_remain_one_logical_gap_for_final_recheck():
    ledger = ExplorationLedger()
    ledger.regions["r1"] = Region(
        region_id="r1", name="应用导航", summary="跨状态共享导航")
    ledger.canonical_operations["co1"] = CanonicalOperation(
        canonical_operation_id="co1", region_id="r1", action="click",
        target="World 页签", operation_ids=["o1", "o2"])
    for index in (1, 2):
        operation_id = f"o{index}"
        task_id = f"t{index}"
        ledger.operations[operation_id] = Operation(
            operation_id=operation_id, region_id="r1", action="click",
            target="World 页签", status="deferred",
            canonical_operation_id="co1",
            parameter_status="none", parameter_summary="无参数")
        ledger.tasks[task_id] = Task(
            task_id=task_id, kind="explore_operation", status="deferred",
            state_id=f"s{index}", operation_id=operation_id,
            created_seq=index)

    assert TaskScheduler.gaps(ledger) == [
        "co1 explore_operation bindings=o1,o2: deferred"]
    assert TaskScheduler().choose(ledger).task_id == "t1"


def test_transition_region_effects_record_revealed_and_hidden_regions(tmp_path):
    runtime, _payload = _region_reveal_runtime()
    transition = runtime.ledger.transitions[0]
    transition.revealed_region_ids = ["r2"]
    transition.hidden_region_ids = ["r1"]  # Explicitly reported action effect.

    assert refresh_transition_region_effects(
        runtime.ledger, transition) is True

    assert transition.revealed_region_ids == ["r2"]
    assert transition.hidden_region_ids == ["r1"]
    runtime.ledger.save(tmp_path / "ledger.json")
    restored = ExplorationLedger.load(tmp_path / "ledger.json")
    assert restored.transitions[0].revealed_region_ids == ["r2"]
    assert restored.transitions[0].hidden_region_ids == ["r1"]


def test_transition_region_effects_wait_for_complete_target_inventory():
    runtime, _payload = _region_reveal_runtime()
    transition = runtime.ledger.transitions[0]
    runtime.ledger.states["s2"].survey_complete = False

    assert refresh_transition_region_effects(
        runtime.ledger, transition) is False
    assert transition.revealed_region_ids == []
    assert transition.hidden_region_ids == []


def test_page_region_group_is_union_of_page_state_regions():
    ledger = _contextual_region_route_ledger()

    assert page_region_refs(ledger, "p-world") == [
        "r-nav", "r-world-body", "r-world-dialog"]


def test_region_route_uses_context_specific_add_operation():
    ledger = _contextual_region_route_ledger()

    alarm_plan = plan_region_route(
        ledger, current_state_id="s-alarm",
        target_region_id="r-alarm-editor")
    wrong_plan = plan_region_route(
        ledger, current_state_id="s-alarm",
        target_region_id="r-world-dialog")

    assert alarm_plan["status"] == "ready"
    assert alarm_plan["steps"][0]["operation_ref"] == "o-alarm"
    assert alarm_plan["steps"][0]["source_variant_ref"] == "rv-nav-alarm"
    assert alarm_plan["steps"][0]["expected_revealed_region_refs"] == [
        "r-alarm-editor"]
    assert wrong_plan["status"] == "unreachable"


def test_unseen_variant_identity_does_not_authorize_route_result():
    ledger = _contextual_region_route_ledger()
    plan = plan_region_route(
        ledger, current_state_id="s-unseen", target_region_id="r-alarm-editor")
    assert ledger.operations["o-unseen"].status == "verified"
    assert plan["status"] == "unreachable"


def test_unseen_variant_reuses_explicit_result():
    ledger = _contextual_region_route_ledger()
    ledger.event(
        "variant_operation_result_reused",
        current_operation_id="o-unseen", known_operation_id="o-alarm",
        canonical_operation_id="co-alarm")
    plan = plan_region_route(
        ledger, current_state_id="s-unseen", target_region_id="r-alarm-editor")
    assert plan["status"] == "ready"
    assert plan["steps"][0]["operation_ref"] == "o-unseen"
    assert plan["steps"][0]["evidence_transition_ref"] == "e-alarm"


def test_region_route_plans_multiple_region_hops_to_target():
    ledger = _contextual_region_route_ledger()

    plan = plan_region_route(
        ledger, current_state_id="s-alarm",
        target_region_id="r-duration")

    assert plan["status"] == "ready"
    assert [item["operation_ref"] for item in plan["steps"]] == [
        "o-alarm", "o-duration"]
    assert plan["steps"][-1]["expected_revealed_region_refs"] == [
        "r-duration"]


def test_unseen_variant_does_not_reuse_conflicting_canonical_effects():
    ledger = _contextual_region_route_ledger()
    ledger.event(
        "variant_operation_result_reused",
        current_operation_id="o-unseen", known_operation_id="o-alarm",
        canonical_operation_id="co-alarm",
    )
    other = Region("r-other", "另一个添加结果", "另一个业务对象")
    ledger.regions[other.region_id] = other
    ledger.pages["p-alarm"].state_ids.append("s-other")
    ledger.states["s-other"] = PageState(
        "s-other", "p-alarm", "其他添加结果", "其他添加结果",
        "screenshots/s-other.png", ["ro-other"], True, 1)
    ledger.occurrences["ro-other"] = RegionOccurrence(
        "ro-other", "r-other", "s-other", "其他添加结果",
        "其他添加结果", "rv-other")
    ledger.region_variants["rv-other"] = RegionVariant(
        "rv-other", "r-other", ["ro-other"])
    other.occurrence_ids = ["ro-other"]
    other.variant_ids = ["rv-other"]
    action = {
        "kind": "click", "operation_ref": "o-alarm",
        "owner_ref": "el-alarm", "target": "Add Alarm",
    }
    ledger.attempts["a-conflict"] = ActionAttempt(
        "a-conflict", "task-conflict", "s-alarm", "execute", action,
        "before.png", after_ref="after.png", outcome="success",
        target_state_id="s-other")
    ledger.transitions.append(Transition(
        "e-conflict", "s-alarm", "s-other", "a-conflict", action,
        "出现另一个业务对象", revealed_region_ids=["r-other"]))

    plan = plan_region_route(
        ledger, current_state_id="s-unseen",
        target_region_id="r-alarm-editor")

    assert plan["status"] == "ambiguous"
    assert plan["steps"] == []
    relations = region_relations(ledger)
    assert {item["evidence_transition_ref"] for item in relations} >= {
        "e-alarm", "e-conflict"}


def test_active_task_uses_current_canonical_binding_without_route():
    from gui_rewalk.src.core.explore.status import current_operation_binding
    ledger, held = _ledger_with_current_canonical_binding()
    scheduler = TaskScheduler()

    task = scheduler.choose(ledger)

    assert task is held
    assert current_operation_binding(ledger, task.operation_id).operation_id == "o2"
    assert ledger.current_task_id == held.task_id
    assert "t-current" not in ledger.tasks
    action = parse_turn(_turn(
        screen={**_known_screen(), "state_ref": "s2", "state_name": "运行状态"},
        action={
            "kind": "click", "purpose": "execute", "target": "开始按钮",
            "owner_ref": "el2",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o2",
        },
    ), has_pending_action=False).action

    class _Artifacts:
        @staticmethod
        def save_attempt_before(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/before.png"

        @staticmethod
        def save_attempt_after(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/after.png"

    class _Env:
        @staticmethod
        def step(_primitive, pause):
            assert pause == 2.0
            return {"screenshot": _png("white")}

    runtime = object.__new__(ExplorationRuntime)
    runtime.platform = "desktop"
    runtime.ledger = ledger
    runtime.scheduler = scheduler
    runtime.artifacts = _Artifacts()
    runtime.env = _Env()
    runtime.actions_used = 0
    runtime.pending_attempt_id = ""
    runtime.pending_before = b""
    runtime.confirmed_state_id = "s2"
    runtime.confirmed_screenshot = _png("white")
    runtime.state_identity_rechecks = set()

    assert runtime._validate_action(task, action) == ""
    runtime._execute(task=task, action=action, screenshot=_png("white"))
    attempt = runtime.ledger.attempts[runtime.pending_attempt_id]
    assert attempt.task_id == held.task_id
    assert attempt.source_state_id == "s2"
    assert attempt.action["operation_ref"] == "o2"

    settled_turn = parse_turn(
        _turn(
            screen={
                **_known_screen(), "state_ref": "s2", "state_name": "运行状态",
            },
            previous={
                "attempt_ref": attempt.attempt_id,
                "element_actions": [{"element_ref": "el2", "action": "click", "completed": True}],
                "region_actions": [], "function_info": [], "region_effects": [],
                "parameter_info": {"status": "none", "summary": "无参数"},
                "reason": "前后图确认当前本地菜单按钮已执行。",
            },
        ),
        has_pending_action=True,
        pending_attempt_id=attempt.attempt_id,
    )
    runtime._settle_pending(
        settled_turn, screenshot=_png("blue"), frame_ref="screenshots/after.png")
    assert attempt.after_ref == "action_attempts/a1/after.png"
    assert attempt.action["operation_ref"] == "o2"
    assert runtime.ledger.operations["o2"].result == (
        "前后图确认当前本地菜单按钮已执行。")
    assert scheduler.choose(runtime.ledger) is None
    assert runtime.ledger.operations["o2"].status == "verified"
    assert runtime.ledger.operations["o1"].status == "recorded"
    assert held.status == "done"


@pytest.mark.parametrize("pending_action", [False, True])
def test_unreachable_focus_yields_to_visible_new_function_after_settlement(pending_action):
    ledger, held = _ledger_with_current_canonical_binding()
    ledger.canonical_operations["co1"].operation_ids.remove("o2")
    ledger.canonical_operations["co2"] = CanonicalOperation("co2", "r1", "click", "Other function", ["o2"])
    ledger.operations["o2"].canonical_operation_id = "co2"
    if pending_action:
        ledger.attempts["a-pending"] = ActionAttempt("a-pending", held.task_id, "s1", "route",
            {"kind": "back"}, "before.png")

    selected = TaskScheduler().choose(ledger)

    if pending_action:
        assert selected is held
    else:
        assert selected.task_id == "t-current"
        assert held.status == "pending"
        assert ledger.operations[held.operation_id].status == "pending"
        assert any(e["kind"] == "unreachable_focus_parked" for e in ledger.events)
    assert ledger.operations["o2"].canonical_operation_id == "co2"
    assert ledger.operations["o1"].status != "verified"
    assert not ledger.transitions


def test_active_focus_with_verified_route_is_not_parked_for_other_work():
    ledger = _contextual_region_route_ledger()
    ledger.current_state_id = "s-alarm"
    ledger.current_page_id = "p-alarm"
    ledger.operations["o-duration"].status = "pending"
    ledger.operations["o-alarm"].status = "pending"
    held = Task("t-target", "explore_operation", "active", "s-alarm-editor", "o-duration")
    ledger.tasks[held.task_id] = held
    ledger.tasks["t-local"] = Task("t-local", "explore_operation", "pending", "s-alarm", "o-alarm")
    ledger.current_task_id = held.task_id
    assert TaskScheduler().choose(ledger) is held


def test_active_task_routes_when_current_canonical_binding_is_deferred():
    ledger, held = _ledger_with_current_canonical_binding(executable=False)
    task = TaskScheduler().choose(ledger)
    action = parse_turn(_turn(
        screen={**_known_screen(), "state_ref": "s2", "state_name": "运行状态"},
        action={
            "kind": "click", "purpose": "execute", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o1",
        },
    ), has_pending_action=False).action
    runtime = object.__new__(ExplorationRuntime)
    runtime.platform = "desktop"
    runtime.ledger = ledger

    assert task is held
    assert "action.owner_ref" in runtime._validate_action(task, action)


@pytest.mark.parametrize("boundary", ["cross_region", "unconfirmed_canonical"])
def test_scheduler_does_not_confuse_other_work_with_the_focus_identity(
    boundary,
):
    ledger, held = _ledger_with_current_canonical_binding()
    if boundary == "cross_region":
        ledger.regions["r2"] = Region(
            "r2", "Other Region", "不同规范区块",
            operation_ids=["o2"], occurrence_ids=["ro2"],
            variant_ids=["rv2"], element_ids=["el2"])
        ledger.regions["r1"].operation_ids.remove("o2")
        ledger.regions["r1"].occurrence_ids.remove("ro2")
        ledger.regions["r1"].variant_ids.remove("rv2")
        ledger.regions["r1"].element_ids.remove("el2")
        ledger.operations["o2"].region_id = "r2"
        ledger.occurrences["ro2"].region_id = "r2"
        ledger.region_variants["rv2"].region_id = "r2"
        ledger.elements["el2"].region_id = "r2"
    else:
        ledger.canonical_operations["co1"].operation_ids.remove("o2")
        ledger.canonical_operations["co2"] = CanonicalOperation(
            "co2", "r1", "click", "开始按钮", ["o2"])
        ledger.operations["o2"].canonical_operation_id = "co2"

    chosen = TaskScheduler().choose(ledger)
    if boundary == "cross_region":
        assert chosen is held
    else:
        assert chosen.task_id == "t-current"
        assert held.status == "pending"
        assert ledger.operations["o1"].canonical_operation_id == "co1"
        assert ledger.operations["o2"].canonical_operation_id == "co2"
    assert ledger.current_task_id == chosen.task_id
