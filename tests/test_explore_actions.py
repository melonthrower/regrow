"""Existing modular exploration contracts: actions."""


import pytest
from PIL import Image, ImageDraw

from gui_rewalk.src.core.explore.status import build_task_view, render_status_bar
from gui_rewalk.src.core.explore.anchors import (
    capture_click_anchor,
    compare_action_effects,
    relocate_click_anchor,
    visible_change_ratio,
)
from gui_rewalk.src.core.explore.artifacts import ArtifactStore
from gui_rewalk.src.core.explore.contracts import ActionRequest, parse_turn
from gui_rewalk.src.core.explore.ledger import ExplorationLedger
from gui_rewalk.src.core.explore.location import bind_screen
from gui_rewalk.src.core.explore.models import (
    ActionAttempt,
    CanonicalOperation,
    Operation,
    Region,
    PageState,
    RegionOccurrence,
    RegionVariant,
    Task,
)
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.settlement import settle_completed_actions
from gui_rewalk.src.core.explore.tasks import TaskScheduler

from .explore_fixtures import (
    _anchor_scene,
    _effect_frames,
    _focus_with_successful_nonfocus_attempt,
    _image_png,
    _known_screen,
    _ledger_with_current_canonical_binding,
    _new_screen,
    _owner_previous,
    _parameter_ledger,
    _pending_parameter_attempt,
    _png,
    _seed_ledger,
    _turn,
)


def test_click_anchor_relocates_uniquely_and_rejects_duplicates():
    source = _anchor_scene(x=90)
    source_point = [90 * 1000 / 359, 120 * 1000 / 239]
    captured = capture_click_anchor(_image_png(source), source_point)
    assert captured is not None

    relocated_scene = _anchor_scene(x=210)
    match = relocate_click_anchor(
        captured.png,
        captured.click_offset_px,
        _image_png(relocated_scene),
    )
    assert match is not None
    assert abs(match.point_px[0] - 210) <= 1
    assert abs(match.point_px[1] - 120) <= 1

    repeated = _anchor_scene(x=90, duplicate=True)
    assert relocate_click_anchor(
        captured.png,
        captured.click_offset_px,
        _image_png(repeated),
    ) is None
    assert capture_click_anchor(_png("white"), [500, 500]) is None


def test_action_effect_comparison_requires_same_visible_change():
    first_before, first_after = _effect_frames("#e8e8e8")
    second_before, second_after = _effect_frames("#d8e4ee")
    different_before, different_after = _effect_frames(
        "#e8e8e8", different=True)

    same = compare_action_effects(
        first_before, first_after, second_before, second_after)
    different = compare_action_effects(
        first_before, first_after, different_before, different_after)

    assert same.accepted is True
    assert same.score >= 0.94
    assert same.edge_score >= 0.80
    assert different.accepted is False


def test_visible_change_ratio_distinguishes_local_noise_from_large_change():
    before = Image.new("RGB", (200, 200), "white")
    local = before.copy()
    ImageDraw.Draw(local).rectangle((80, 80, 99, 99), fill="black")
    large = before.copy()
    ImageDraw.Draw(large).rectangle((20, 30, 179, 169), fill="black")

    local_ratio = visible_change_ratio(
        _image_png(before), _image_png(local))
    large_ratio = visible_change_ratio(
        _image_png(before), _image_png(large))

    assert local_ratio is not None and local_ratio < 0.08
    assert large_ratio is not None and large_ratio > 0.50


def test_verified_operation_reuse_waits_for_both_visual_results(tmp_path):
    first_before, first_after = _effect_frames("#e8e8e8")
    second_before, second_after = _effect_frames("#d8e4ee")
    store = ArtifactStore(str(tmp_path))
    ledger = ExplorationLedger()
    ledger.regions["r1"] = Region(
        "r1", "全局应用栏", "跨页面复用的应用栏",
        ["o1", "o2"], ["ro1", "ro2"], ["rv1", "rv2"],
        ["co1", "co2"],
    )
    ledger.region_variants["rv1"] = RegionVariant(
        "rv1", "r1", ["ro1"], ["o1"])
    ledger.region_variants["rv2"] = RegionVariant(
        "rv2", "r1", ["ro2"], ["o2"])
    ledger.occurrences["ro1"] = RegionOccurrence(
        "ro1", "r1", "s-o1", "全局应用栏", "第一页", "rv1")
    ledger.occurrences["ro2"] = RegionOccurrence(
        "ro2", "r1", "s-o2", "全局应用栏", "第二页", "rv2")
    ledger.canonical_operations["co1"] = CanonicalOperation(
        "co1", "r1", "click", "更多选项", ["o1"])
    ledger.canonical_operations["co2"] = CanonicalOperation(
        "co2", "r1", "click", "更多选项", ["o2"])
    ledger.operations["o1"] = Operation(
        "o1", "r1", "click", "更多选项", "verified",
        source_occurrence_ids=["ro1"], variant_id="rv1",
        canonical_operation_id="co1",
    )
    ledger.operations["o2"] = Operation(
        "o2", "r1", "click", "更多选项", "verified",
        source_occurrence_ids=["ro2"],
        reuse_candidate_operation_id="o1",
        variant_id="rv2", canonical_operation_id="co2",
    )
    for attempt_id, operation_id, before, after in (
        ("a1", "o1", first_before, first_after),
        ("a2", "o2", second_before, second_after),
    ):
        before_ref = store.save_attempt_before(attempt_id, before)
        after_ref = store.save_attempt_after(attempt_id, after)
        ledger.attempts[attempt_id] = ActionAttempt(
            attempt_id,
            "t-" + operation_id,
            "s-" + operation_id,
            "execute",
            {"kind": "click", "operation_ref": operation_id},
            before_ref,
            after_ref=after_ref,
            outcome="success",
            visible_result="弹出了相同的更多选项菜单。",
            target_state_id="target-" + operation_id,
        )
    ledger.save(tmp_path / "ledger.json")
    ledger = ExplorationLedger.load(tmp_path / "ledger.json")
    assert ledger.operations["o2"].reuse_candidate_operation_id == "o1"
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.artifacts = store

    runtime._reconcile_verified_operation_reuse("o2")

    assert list(runtime.ledger.operations) == ["o1", "o2"]
    assert list(runtime.ledger.canonical_operations) == ["co1"]
    assert runtime.ledger.operations["o1"].canonical_operation_id == "co1"
    assert runtime.ledger.operations["o2"].canonical_operation_id == "co1"
    assert any(
        item["kind"] == "verified_operations_reused"
        for item in runtime.ledger.events
    )


def test_settlement_binds_observed_parameters_to_completed_owner():
    ledger = _parameter_ledger("unknown", handling="explore")
    operation, attempt = _pending_parameter_attempt(ledger)

    settlement = settle_completed_actions(
        ledger,
        attempt,
        _owner_previous({
            "status": "observed",
            "summary": "可选 Control volume、Snooze、Dismiss；未逐项执行",
        }),
    )

    assert settlement.operation_refs == (operation.operation_id,)
    assert operation.status == "verified"
    assert operation.parameter_status == "observed"
    assert operation.parameter_summary == (
        "可选 Control volume、Snooze、Dismiss；未逐项执行")
    assert operation.parameter_evidence_refs == [
        "action_attempts/a1/after.png"]


def test_settlement_enriches_observed_parameter_range_with_after_evidence():
    ledger = _parameter_ledger("observed", handling="explore")
    operation, attempt = _pending_parameter_attempt(ledger)
    operation.parameter_summary = "Selector format observed; choices not opened"
    operation.parameter_evidence_refs = ["before.png"]
    settle_completed_actions(ledger, attempt, _owner_previous({
        "status": "observed", "summary": "Choices: A, B, C; no value applied"}))
    assert operation.parameter_summary == "Choices: A, B, C; no value applied"
    assert operation.parameter_evidence_refs[-1] == attempt.after_ref
    assert any(event["kind"] == "parameter_observation_revised" for event in ledger.events)


def test_unrequested_parameter_note_does_not_replace_known_parameters():
    ledger = _parameter_ledger("none", handling="explore")
    operation, attempt = _pending_parameter_attempt(ledger)
    region = next(iter(ledger.regions.values()))
    old_parameters = operation.parameter_summary
    result = settle_completed_actions(
        ledger,
        attempt,
        _owner_previous({
            "status": "observed",
            "summary": "出现了一个参数列表",
        }, function_info=[{
            "region_ref": region.region_id,
            "memory": "已观察到的来源区块功能说明。",
        }]),
    )

    assert result.operation_refs == (operation.operation_id,)
    assert operation.status == "verified"
    assert operation.parameter_status == "none"
    assert operation.parameter_summary == old_parameters
    assert region.memory == "已观察到的来源区块功能说明。"
    assert any(x["kind"] == "parameter_info_ignored_not_requested" for x in ledger.events)


def test_exact_operation_at_source_cannot_be_mislabeled_as_route():
    ledger = _seed_ledger()
    task = TaskScheduler().choose(ledger)
    action = parse_turn(_turn(
        screen=_known_screen(),
        action={
            "kind": "click", "purpose": "route", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o1",
        },
    ), has_pending_action=False).action
    runtime = object.__new__(ExplorationRuntime)
    runtime.platform = "desktop"
    runtime.ledger = ledger

    issue = runtime._validate_action(task, action)

    assert "请使用 action.owner_ref=" in issue
    assert "不要填写内部 purpose/operation_ref" in issue
    task_view = build_task_view(
        runtime.ledger,
        task,
        rediscovering=getattr(runtime, "resume_region_rediscovery_required", False),
    )
    assert task_view["source_page_ref"] == "p1"
    assert task_view["source_page_name"] == "Stopwatch"
    assert "派发不要求重复点击" in task_view["instruction"]
    wrong_operation = parse_turn(_turn(
        screen=_known_screen(), action={
            "kind": "click", "purpose": "execute", "target": "前置按钮",
            "point_1000": [400, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o2",
        }), has_pending_action=False).action
    assert "改用当前真实动作对象的 action.owner_ref" in runtime._validate_action(
        task, wrong_operation)
    wrong_issue = runtime._validate_action(task, wrong_operation)
    assert "当前任务 o1（click 开始按钮）仍未结束" in wrong_issue
    assert "请移除内部 purpose/operation_ref" in wrong_issue
    assert "前置动作不等于目标任务已完成" in wrong_issue

    repeated_action = parse_turn(_turn(
        screen=_known_screen(), action={
            "kind": "click", "purpose": "execute", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o1",
        }), has_pending_action=False).action
    repeated_dict = {
        "kind": "click", "purpose": "execute", "target": "开始按钮",
        "point_1000": [500.0, 700.0], "text": "", "direction": "",
        "amount": 650, "operation_ref": "o1",
    }
    for number in range(1, 4):
        ledger.attempts[f"a{number}"] = ActionAttempt(
            attempt_id=f"a{number}", task_id=task.task_id,
            source_state_id="s1", purpose="execute", action=repeated_dict,
            before_ref=f"action_attempts/a{number}/before.png",
            after_ref=f"action_attempts/a{number}/after.png",
            outcome="no_effect", target_state_id="s1",
        )
    repeated_issue = runtime._validate_action(task, repeated_action)
    assert "连续 3 次以完全相同参数执行且均无可见效果" in repeated_issue
    assert "框架会自动保留 failed gap" in repeated_issue
    for attempt in ledger.attempts.values():
        attempt.purpose = "route"
        attempt.action["purpose"] = "route"
    repeated_route = parse_turn(_turn(
        screen=_known_screen(), action={
            "kind": "click", "purpose": "route", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o1",
        }), has_pending_action=False).action
    assert "连续 3 次" in runtime._validate_action(task, repeated_route)


def test_survey_task_routes_back_to_its_source_state():
    ledger = _seed_ledger()
    survey = ledger.survey_task("s1")
    survey.status = "active"
    ledger.current_task_id = survey.task_id
    ledger.states["s2"] = PageState(
        state_id="s2", page_id="p1", name="菜单已关闭",
        summary="当前不在待调查菜单", screenshot_ref="screenshots/s2.png",
        survey_complete=True, inventory_passes=1,
    )
    ledger.pages["p1"].state_ids.append("s2")
    ledger.current_state_id = "s2"
    runtime = object.__new__(ExplorationRuntime)
    runtime.platform = "desktop"
    runtime.ledger = ledger

    task_view = build_task_view(
        runtime.ledger,
        survey,
        rediscovering=getattr(runtime, "resume_region_rediscovery_required", False),
    )
    status = render_status_bar(ledger, survey, system_scope="target")
    assert "不要重复提交当前位置的 page_report" in task_view["instruction"]
    assert "screen 仍须按最新截图报告" in task_view["instruction"]
    assert "purpose=route 返回 source_state_ref" in task_view["instruction"]
    assert "先导航回待清点状态" in status

    route = parse_turn(_turn(
        screen={**_known_screen(), "state_ref": "s2", "state_name": "菜单已关闭"},
        action={
            "kind": "click", "purpose": "route", "target": "更多选项",
            "point_1000": [900, 100], "text": "", "direction": "",
            "amount": 650, "operation_ref": "",
        },
    ), has_pending_action=False).action
    assert runtime._validate_action(survey, route) == ""

    wrong_survey = parse_turn(_turn(
        screen={**_known_screen(), "state_ref": "s2", "state_name": "菜单已关闭"},
        action={
            "kind": "scroll", "purpose": "survey", "target": "当前内容",
            "point_1000": [500, 500], "text": "", "direction": "up",
            "amount": 300, "operation_ref": "",
        },
    ), has_pending_action=False).action
    issue = runtime._validate_action(survey, wrong_survey)
    assert "scroll 必须绑定当前可见 Region" in issue
    assert "不允许空 owner 滚动" in issue


def test_page_state_mismatch_names_the_correct_owner():
    ledger = _seed_ledger()
    ledger.pages["p2"] = ledger.pages["p1"].__class__(
        page_id="p2", name="Timer", summary="计时器功能页面")
    wrong = parse_turn(_turn(screen={
        **_known_screen(),
        "page_ref": "p2",
        "page_name": "Timer",
    }), has_pending_action=False).screen

    result = bind_screen(
        ledger, wrong, screenshot_ref="screenshots/current.png")

    assert result.ok is False
    assert "状态 s1 属于页面 p1（Stopwatch），不是 p2" in result.issue


def test_operation_attempt_budget_records_failure_and_releases_task():
    ledger = _seed_ledger()
    task = TaskScheduler().choose(ledger)
    task.attempt_count = 12
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()

    assert runtime._fail_exhausted_task(task) is True
    assert task.status == "failed"
    assert ledger.operations[task.operation_id].status == "failed"
    assert ledger.current_task_id == ""
    assert ledger.events[-1]["kind"] == "operation_attempt_budget_exhausted"


def test_two_no_effect_recoveries_fail_current_task_and_leave_gap():
    ledger = _seed_ledger()
    task = TaskScheduler().choose(ledger)
    operation = ledger.operations[task.operation_id]
    operation.status = "active"

    class _Artifacts:
        @staticmethod
        def save_attempt_after(attempt_id, _screenshot):
            return f"action_attempts/{attempt_id}/after.png"

    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()
    runtime.artifacts = _Artifacts()
    runtime.pending_attempt_id = ""
    runtime.pending_before = b""
    runtime.state_identity_rechecks = set()

    def settle_recovery(attempt_id, target, point):
        ledger.attempts[attempt_id] = ActionAttempt(
            attempt_id=attempt_id,
            task_id=task.task_id,
            source_state_id="s1",
            purpose="recover",
            action={
                "kind": "click", "purpose": "recover", "target": target,
                "point_1000": point, "text": "", "direction": "",
                "amount": 650, "operation_ref": "",
            },
            before_ref=f"action_attempts/{attempt_id}/before.png",
        )
        task.attempt_count += 1
        runtime.pending_attempt_id = attempt_id
        runtime.pending_before = _png("white")
        turn = parse_turn(
            _turn(
                screen=_known_screen(),
                previous={
                    "attempt_ref": attempt_id,
                    "outcome": "no_effect",
                    "task_result": "retry",
                    "visible_result": "前景菜单没有关闭。",
                    "reason": "恢复动作没有产生可见结果。",
                },
            ),
            has_pending_action=True,
            pending_attempt_id=attempt_id,
        )
        runtime._settle_pending(
            turn, screenshot=_png("white"),
            frame_ref=f"screenshots/{attempt_id}.png")

    settle_recovery("a1", "关闭菜单", [574, 606])
    assert task.status == "active"

    settle_recovery("a2", "点击菜单外部", [430, 700])

    assert task.status == "failed"
    assert operation.status == "failed"
    assert ledger.current_task_id == ""
    assert any(
        item["kind"] == "recovery_no_effect_budget_exhausted"
        and item["payload"]["task_id"] == task.task_id
        and item["payload"]["attempt_count"] == 2
        for item in ledger.events)
    assert TaskScheduler.gaps(ledger) == [
        f"{task.task_id} explore_operation {task.operation_id}: failed"]


def test_alternating_action_rejections_release_current_task_for_other_work():
    ledger = _seed_ledger()
    task = TaskScheduler().choose(ledger)
    another = Task(
        "t-extra", "explore_operation", "pending", "s1", "o-extra",
        created_seq=99)
    ledger.tasks[another.task_id] = another
    ledger.operations["o-extra"] = Operation(
        "o-extra", "r1", "click", "Extra", "pending",
        source_occurrence_ids=["ro1"])
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()
    runtime.correction = ""
    runtime.rejection_task_id = ""
    runtime.rejection_issue = ""
    runtime.rejection_streak = 0
    issues = [
        "当前 State 没有该任务可执行的本地 Operation binding。",
        "当前任务 o1 仍未结束，本轮却提交 o2。",
    ]

    for count in range(1, 4):
        issue = issues[(count - 1) % len(issues)]
        assert runtime._record_action_rejection(task, issue) is False
        assert task.status == "active"
        assert runtime.rejection_streak == count
    status = render_status_bar(
        ledger, task, system_scope="target", correction=issues[0],
        rejection_count=runtime.rejection_streak, rejection_limit=4,
    )
    assert "当前任务动作拒绝：3/4 次" in status

    assert runtime._record_action_rejection(task, issues[1]) is True
    assert task.status == "failed"
    assert ledger.operations[task.operation_id].status == "failed"
    assert ledger.current_task_id == ""
    assert runtime.rejection_streak == 0
    assert runtime.correction == ""
    assert ledger.events[-1]["kind"] == "operation_rejection_budget_exhausted"
    assert runtime.scheduler.choose(ledger).task_id == another.task_id


def test_page_survey_attempt_budget_records_failure_and_releases_task():
    ledger = ExplorationLedger()
    screen = parse_turn(
        _turn(screen=_new_screen()), has_pending_action=False).screen
    bound = bind_screen(
        ledger, screen, screenshot_ref="screenshots/first.png")
    task = TaskScheduler().choose(bound.ledger)
    task.attempt_count = 12
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = bound.ledger
    runtime.scheduler = TaskScheduler()

    assert task.kind == "survey_page"
    assert runtime._fail_exhausted_task(task) is True
    assert task.status == "failed"
    assert bound.ledger.current_task_id == ""
    assert bound.ledger.events[-1]["kind"] == "survey_attempt_budget_exhausted"


def test_page_survey_rejects_navigation_without_current_owner():
    ledger = ExplorationLedger()
    screen = parse_turn(
        _turn(screen=_new_screen()), has_pending_action=False).screen
    bound = bind_screen(
        ledger, screen, screenshot_ref="screenshots/first.png")
    task = TaskScheduler().choose(bound.ledger)
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = bound.ledger
    runtime.platform = "desktop"
    action = parse_turn(_turn(
        screen=_known_screen(),
        action={
            "kind": "click", "purpose": "route", "target": "其他页面",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "o2",
        },
    ), has_pending_action=False).action

    issue = runtime._validate_action(task, action)

    assert "当前已登记的 owner_ref" in issue
    assert "不要求清点提前完成" in issue

    stale_operation = parse_turn(_turn(
        screen=_known_screen(),
        action={
            "kind": "scroll", "purpose": "survey", "target": "当前列表",
            "point_1000": [500, 800], "text": "", "direction": "down",
            "amount": 300, "operation_ref": "o16",
        },
    ), has_pending_action=False).action
    stale_issue = runtime._validate_action(task, stale_operation)
    assert "scroll 必须绑定当前可见 Region" in stale_issue


def test_no_effect_budget_counts_current_canonical_binding_per_source_state():
    ledger, focus = _ledger_with_current_canonical_binding()
    ledger.tasks["t-current"].status = "done"
    focus.status = "active"
    ledger.operations[focus.operation_id].status = "active"
    ledger.current_task_id = focus.task_id
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.scheduler = TaskScheduler()

    def add_no_effect(attempt_id, source_state_id, operation_id, owner_ref):
        ledger.attempts[attempt_id] = ActionAttempt(
            attempt_id, focus.task_id, source_state_id, "execute",
            {
                "kind": "click", "purpose": "execute",
                "target": "开始按钮", "point_1000": [500.0, 700.0],
                "text": "", "direction": "", "amount": 650,
                "operation_ref": operation_id, "owner_ref": owner_ref,
            },
            f"action_attempts/{attempt_id}/before.png",
            after_ref=f"action_attempts/{attempt_id}/after.png",
            outcome="no_effect", visible_result="点击后界面没有变化",
            target_state_id=source_state_id,
        )

    add_no_effect("a-old", "s1", "o1", "el1")
    add_no_effect("a-current-1", "s2", "o2", "el2")

    assert runtime._fail_repeated_no_effect_operation(focus) is False
    assert focus.status == "active"

    add_no_effect("a-current-2", "s2", "o2", "el2")

    assert runtime._fail_repeated_no_effect_operation(focus) is True
    assert focus.status == "failed"
    event = ledger.events[-1]
    assert event["kind"] == "operation_no_effect_retry_exhausted"
    assert event["payload"]["canonical_operation_id"] == "co1"
    assert event["payload"]["actual_operation_id"] == "o2"
    assert event["payload"]["source_state_id"] == "s2"
    assert event["payload"]["attempt_count"] == 2


def test_successful_nonfocus_operation_can_repeat_within_focus():
    ledger, focus = _focus_with_successful_nonfocus_attempt()
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.platform = "desktop"
    repeated = ActionRequest(
        kind="click", purpose="execute", target="替代按钮",
        point_1000=[100.0, 100.0], text="", direction="", amount=650,
        operation_ref="o2", owner_ref="el2",
    )

    issue = runtime._validate_action(focus, repeated)

    assert issue == ""


@pytest.mark.parametrize("verified_route", [True, False])
def test_previous_success_does_not_block_preparatory_navigation(verified_route):
    from dataclasses import replace
    from .explore_fixtures import _contextual_region_route_ledger
    ledger = _contextual_region_route_ledger()
    focus = Task("t-route-focus", "explore_operation", state_id="s-alarm-editor",
                 operation_id="o-duration", status="active")
    ledger.tasks[focus.task_id] = focus
    ledger.current_state_id = "s-alarm"
    ledger.current_page_id = "p-alarm"
    ledger.attempts["a-alarm"].task_id = focus.task_id
    if not verified_route:
        ledger.transitions = [edge for edge in ledger.transitions if edge.attempt_id != "a-alarm"]
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger, runtime.platform = ledger, "desktop"
    action = ActionRequest(kind="click", purpose="execute", owner_ref="el-alarm",
                           operation_ref="o-alarm", target="Add Alarm", point_1000=[500, 500],
                           text="", direction="", amount=650)

    issue = runtime._validate_action(focus, action)

    assert issue == ""
    with pytest.raises(ValueError):
        runtime._bind_action(focus, replace(action, purpose="", operation_ref="", owner_ref="el-world"))


@pytest.mark.parametrize("outcome", ["success", "no_effect", "uncertain"])
def test_preparatory_scroll_can_continue_after_real_effect(outcome):
    ledger, focus = _focus_with_successful_nonfocus_attempt()
    operation = ledger.operations["o2"]
    operation.scope, operation.action, operation.direction = "region", "scroll", "down"
    action = ActionRequest(kind="scroll", purpose="execute", owner_ref="r2",
                           operation_ref="o2", target="Reveal more content", point_1000=[500, 500],
                           text="", direction="down", amount=650)
    from dataclasses import asdict
    previous = ledger.attempts["a-nonfocus"]
    previous.action, previous.outcome = asdict(action), outcome
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger, runtime.platform = ledger, "desktop"

    issue = runtime._validate_action(focus, action)

    assert (issue == "") is (outcome == "success")
    if outcome != "success":
        assert "不能立即原样重复" in issue


def test_task_target_at_source_state_cannot_be_mislabeled_as_route():
    ledger, _held = _ledger_with_current_canonical_binding()
    task = TaskScheduler().choose(ledger)
    runtime = object.__new__(ExplorationRuntime)
    runtime.platform = "desktop"
    runtime.ledger = ledger
    action = parse_turn(_turn(
        screen={**_known_screen(), "state_ref": "s2", "state_name": "运行状态"},
        action={
            "kind": "click", "purpose": "route", "target": "开始按钮",
            "point_1000": [500, 700], "text": "", "direction": "",
            "amount": 650, "operation_ref": "",
        },
    ), has_pending_action=False).action

    issue = runtime._validate_action(task, action)

    assert "action.owner_ref=" in issue
    assert "action.owner_ref=el2" in issue


def test_operation_kind_mismatch_names_the_only_valid_choices():
    ledger = _seed_ledger()
    task = TaskScheduler().choose(ledger)
    runtime = object.__new__(ExplorationRuntime)
    runtime.platform = "desktop"
    runtime.ledger = ledger
    action = parse_turn(_turn(
        screen=_known_screen(),
        action={
            "kind": "input_text", "purpose": "execute", "target": "开始按钮",
            "point_1000": [500, 700], "text": "test", "direction": "",
            "amount": 650, "operation_ref": task.operation_id,
        },
    ), has_pending_action=False).action

    issue = runtime._validate_action(task, action)

    assert "kind=click、action.owner_ref=" in issue
    assert "不要填写内部 purpose/operation_ref" in issue
    assert "先修正清单" in issue
    assert "准备动作请用 route" not in issue
