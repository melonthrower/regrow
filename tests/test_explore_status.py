"""Existing modular exploration contracts: status."""


import json


from gui_rewalk.src.core.explore.status import (
    build_agent_context,
    build_task_view,
    current_page_record,
    pending_action_record,
    render_status_bar,
)
from gui_rewalk.src.core.explore.models import (
    ActionAttempt,
    CanonicalOperation,
    PageState,
    Region,
    RegionOccurrence,
    RegionVariant,
    Task,
    Transition,
)
from gui_rewalk.src.core.explore.region_routes import plan_region_route
from gui_rewalk.src.core.explore.resume import prepare_resume_region_rediscovery
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.tasks import TaskScheduler

from .explore_fixtures import (
    _agent_context_for_task,
    _contextual_region_route_ledger,
    _focus_with_successful_nonfocus_attempt,
    _ledger_with_current_canonical_binding,
    _opportunistic_world_route_runtime,
    _parameter_ledger,
    _pending_parameter_attempt,
    _seed_ledger,
)


def test_parameter_status_is_visible_in_page_and_pending_cards():
    ledger = _parameter_ledger("unknown", handling="explore")
    operation, attempt = _pending_parameter_attempt(ledger)

    page_operation = current_page_record(ledger)["regions"][0][
        "elements"][0]["operations"][0]
    pending = pending_action_record(ledger, attempt.attempt_id)

    assert page_operation["parameter_status"] == "unknown"
    assert page_operation["parameter_summary"] == "完整值域尚未观察"
    assert pending["parameter_confirmation_required"] is True
    assert pending["parameter_status"] == "unknown"


def test_unknown_parameter_task_view_requires_one_confirmation_action():
    ledger = _parameter_ledger("unknown", handling="explore")
    operation = next(iter(ledger.operations.values()))
    task = ledger.operation_task(operation.operation_id)
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger

    view = build_task_view(
        runtime.ledger,
        task,
        rediscovering=getattr(runtime, "resume_region_rediscovery_required", False),
    )

    assert view["parameter_status"] == "unknown"
    assert view["parameter_summary"] == "完整值域尚未观察"
    assert view["parameter_confirmation_required"] is True


def test_context_uses_focus_instead_of_model_facing_opportunistic_tasks():
    runtime = _opportunistic_world_route_runtime()

    context = runtime._context(runtime.ledger.tasks["t35"], "target")
    assert "可能顺路完成的任务" not in context
    assert context["探索焦点"]["goal"]


def test_survey_task_card_does_not_repeat_the_full_static_contract():
    ledger = _seed_ledger()
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger

    instruction = build_task_view(runtime.ledger,
        ledger.survey_task("s1"), rediscovering=getattr(runtime, "resume_region_rediscovery_required", False))["instruction"]

    assert len(instruction) <= 260


def test_pending_context_marks_source_inventory_as_before_only():
    ledger, held = _ledger_with_current_canonical_binding()
    held.status = "done"
    task = ledger.tasks["t-current"]
    task.status = "active"
    ledger.current_task_id = task.task_id
    ledger.attempts["a-new-page"] = ActionAttempt(
        "a-new-page", task.task_id, "s2", "execute",
        {
            "kind": "click", "purpose": "execute",
            "target": "打开新页面", "point_1000": [500.0, 500.0],
            "text": "", "direction": "", "amount": 650,
            "operation_ref": "o2", "owner_ref": "el2",
        },
        "action_attempts/a-new-page/before.png",
    )
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.app_name = "example"
    runtime.platform = "desktop"
    runtime.pending_attempt_id = "a-new-page"
    runtime.state_identity_rechecks = set()
    runtime.correction = ""
    runtime.rejection_task_id = ""
    runtime.rejection_issue = ""
    runtime.rejection_streak = 0
    runtime.last_context_task_id = task.task_id

    context = runtime._context(task, "target")

    assert "page_report 只根据图2" in context["状态栏"]
    assert "动作前页面的详细控件清单已省略" in context["状态栏"]
    assert context["当前页面已登记内容"] == {}


def test_task_keeps_the_known_destination_owner_without_claiming_arrival():
    ledger, task = _ledger_with_current_canonical_binding()
    before_state = ledger.current_state_id
    before_operation = ledger.operations[task.operation_id].status
    card = build_task_view(ledger, task)

    assert card["known_source_bindings"] == [
        {"state_ref": "s1", "region_ref": "r1", "owner_ref": "el1"}]
    assert card["current_state_ref"] == before_state == "s2"
    assert card["element_ref"] == "el2"
    assert "不证明当前可见" in card["source_binding_note"]
    assert ledger.current_state_id == before_state
    assert ledger.operations[task.operation_id].status == before_operation


def test_shared_region_is_not_arrived_without_target_operation_context():
    ledger = _contextual_region_route_ledger()

    plan = plan_region_route(
        ledger, current_state_id="s-unseen", target_region_id="r-nav",
        target_operation_id="o-world")

    assert plan["status"] == "unreachable"
    assert plan["steps"] == []


def test_exact_task_card_projects_region_route_to_required_binding():
    ledger = _contextual_region_route_ledger()
    task = Task(
        "t-duration", "explore_operation", "active",
        "s-alarm-editor", "o-duration")
    ledger.tasks[task.task_id] = task
    ledger.current_page_id = "p-alarm"
    ledger.current_state_id = "s-alarm"
    ledger.current_task_id = task.task_id
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger

    card = build_task_view(
        runtime.ledger,
        task,
        rediscovering=getattr(runtime, "resume_region_rediscovery_required", False),
    )

    assert card["required_region_ref"] == "r-alarm-editor"
    assert "required_variant_ref" not in card
    assert "required_occurrence_refs" not in card
    assert card["region_route"]["status"] == "ready"
    assert card["region_route"]["target_canonical_operation_ref"] == (
        "co-duration")
    assert card["region_route"]["steps"][0]["operation_ref"] == "co-alarm"
    assert "canonical_operation_ref" not in card["region_route"]["steps"][0]
    assert "source_variant_ref" not in card["region_route"]["steps"][0]
    assert "Region 路线第一跳" in card["instruction"]


def test_agent_context_exposes_region_operation_with_current_element_binding():
    ledger, focus = _ledger_with_current_canonical_binding()
    ledger.tasks["t-current"].status = "done"
    focus.status = "active"
    ledger.operations[focus.operation_id].status = "active"
    ledger.current_task_id = focus.task_id
    ledger.attempts["a-current"] = ActionAttempt(
        "a-current", focus.task_id, "s2", "execute",
        {
            "kind": "click", "purpose": "execute",
            "target": "开始按钮", "point_1000": [500.0, 700.0],
            "text": "", "direction": "", "amount": 650,
            "operation_ref": "o2", "owner_ref": "el2",
        },
        "action_attempts/a-current/before.png",
        after_ref="action_attempts/a-current/after.png",
        outcome="success", visible_result="当前按钮已生效",
        target_state_id="s2",
    )
    context = _agent_context_for_task(ledger, focus)
    card = context["当前任务精确卡"]
    current_operation = context["当前页面已登记内容"]["regions"][0][
        "elements"][0]["operations"][0]
    receipt = context["当前焦点动作回执"][-1]

    assert card["region_ref"] == "r1"
    assert card["operation_ref"] == "co1"
    assert card["element_ref"] == "el2"
    assert "当前 State 已有同一稳定 Operation" in card["instruction"]
    assert "参数形式或代表值尚未确认" in card["instruction"]
    assert "required_variant_ref" not in card
    assert "required_occurrence_refs" not in card
    assert current_operation["operation_ref"] == "co1"
    assert "canonical_operation_ref" not in current_operation
    assert receipt["focus_operation_ref"] == "co1"
    assert receipt["actual_operation_ref"] == "co1"
    assert receipt["actual_element_ref"] == "el2"
    assert receipt["completed_focus"] is True


def test_agent_context_keeps_context_specific_region_operations_separate():
    ledger, focus = _ledger_with_current_canonical_binding()
    ledger.canonical_operations["co1"].operation_ids.remove("o2")
    ledger.canonical_operations["co2"] = CanonicalOperation(
        "co2", "r1", "click", "打开当前页面专属功能", ["o2"])
    ledger.operations["o2"].canonical_operation_id = "co2"
    ledger.tasks["t-current"].status = "done"
    focus.status = "active"
    ledger.operations[focus.operation_id].status = "active"
    ledger.current_task_id = focus.task_id
    context = _agent_context_for_task(ledger, focus)
    card = context["当前任务精确卡"]
    current_operation = context["当前页面已登记内容"]["regions"][0][
        "elements"][0]["operations"][0]

    assert card["operation_ref"] == "co1"
    assert card["element_ref"] == ""
    assert current_operation["operation_ref"] == "co2"


def test_current_binding_context_drops_any_previous_task_correction():
    ledger, held = _ledger_with_current_canonical_binding()
    held.strategy = "上一任务要求返回旧状态。"
    ledger.attempts["a-old"] = ActionAttempt(
        "a-old", held.task_id, "s1", "recover",
        {"kind": "click", "purpose": "recover", "target": "旧任务恢复按钮"},
        "action_attempts/a-old/before.png",
        after_ref="action_attempts/a-old/after.png",
        outcome="no_effect", visible_result="上一任务恢复没有效果。",
        target_state_id="s1",
    )
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.app_name = "clocks"
    runtime.platform = "desktop"
    runtime.pending_attempt_id = ""
    runtime.state_identity_rechecks = set()
    runtime.correction = "上一任务的 page_report 不符合当前 State。"
    runtime.rejection_task_id = ""
    runtime.rejection_issue = ""
    runtime.rejection_streak = 0
    runtime.last_context_task_id = held.task_id
    runtime.last_context_operation_id = "o1"

    task = TaskScheduler().choose(ledger)
    context = runtime._context(task, "target")
    serialized = json.dumps(context, ensure_ascii=False)

    assert task.task_id == held.task_id
    assert "必须修正" not in context["状态栏"]
    assert runtime.correction == ""
    assert task.strategy == ""
    assert ledger.attempts["a-old"].source_state_id == "s1"
    assert context["当前页面已登记内容"]["state_ref"] == "s2"
    assert any(
        item["state_ref"] == "s1"
        for item in context["已知页面图"]["states"])


def test_same_task_context_keeps_its_correction():
    ledger = _seed_ledger()
    task = TaskScheduler().choose(ledger)
    task.strategy = "旧计划把两个不同按钮当成同一个。"
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.app_name = "clocks"
    runtime.platform = "desktop"
    runtime.pending_attempt_id = ""
    runtime.state_identity_rechecks = set()
    runtime.correction = "当前任务必须修正 page_report。"
    runtime.rejection_task_id = ""
    runtime.rejection_issue = ""
    runtime.rejection_streak = 0
    runtime.last_context_task_id = task.task_id

    context = runtime._context(task, "target")

    assert "必须修正" in context["状态栏"]
    assert "page_report" in context["状态栏"]
    assert "旧计划" not in context["状态栏"]
    assert task.strategy == "旧计划把两个不同按钮当成同一个。"


def test_no_effect_status_names_settled_attempt_and_actual_owner():
    ledger, focus = _focus_with_successful_nonfocus_attempt()
    attempt = ledger.attempts["a-nonfocus"]
    attempt.outcome = "no_effect"
    attempt.visible_result = "点击后界面没有变化"

    status = render_status_bar(
        ledger, focus, system_scope="target",
        pending_attempt_id="",
    )

    assert "a-nonfocus 已结算为 no_effect" in status
    assert "previous_action 必须为 null" in status
    assert "上次实际 owner_ref=el2" in status


def test_context_exposes_exact_focus_refs_and_actual_action_receipt():
    ledger, focus = _focus_with_successful_nonfocus_attempt()
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.app_name = "clocks"
    runtime.platform = "desktop"
    runtime.pending_attempt_id = ""
    runtime.state_identity_rechecks = set()
    runtime.correction = ""
    runtime.rejection_task_id = ""
    runtime.rejection_issue = ""
    runtime.rejection_streak = 0
    runtime.last_context_task_id = focus.task_id

    context = runtime._context(focus, "target")
    card = context["当前任务精确卡"]
    receipt = context["当前焦点动作回执"][-1]

    assert card["operation_ref"] == "co1"
    assert card["region_ref"] == "r1"
    assert card["element_ref"] == "el1"
    assert card["required_region_ref"] == "r1"
    assert "required_variant_ref" not in card
    assert "required_occurrence_refs" not in card
    assert card["current_state_ref"] == "s1"
    assert card["source_state_refs"] == ["s1"]
    assert "at_source_state" not in card
    assert receipt == {
        "attempt_ref": "a-nonfocus",
        "kind": "click",
        "point_1000": [100.0, 100.0],
        "focus_operation_ref": "co1",
        "actual_operation_ref": "o2",
        "actual_region_ref": "r2",
        "actual_element_ref": "el2",
        "source_state_ref": "s1",
        "target_state_ref": "s1",
        "outcome": "success",
        "visible_result": "替代入口已打开",
        "completed_focus": False,
    }


def test_main_context_sends_routes_only_when_current_task_needs_navigation():
    ledger = _seed_ledger()
    ledger.states["s2"] = PageState(
        state_id="s2", page_id="p1", name="运行中",
        summary="另一状态", screenshot_ref="screenshots/running.png",
        survey_complete=True, inventory_passes=1,
    )
    ledger.pages["p1"].state_ids.append("s2")
    ledger.transitions.append(Transition(
        transition_id="e1", source_state_id="s1", target_state_id="s2",
        attempt_id="a1", action={"kind": "click", "target": "开始按钮"},
        visible_result="进入运行中状态",
    ))
    runtime = object.__new__(ExplorationRuntime)
    runtime.ledger = ledger
    runtime.app_name = "clocks"
    runtime.platform = "desktop"
    runtime.pending_attempt_id = ""
    runtime.correction = ""
    runtime.rejection_streak = 0
    runtime.rejection_task_id = ""
    task = ledger.operation_task("o1")

    ledger.current_state_id = "s1"
    at_source = runtime._context(task, "target")
    assert at_source["已知页面图"]["connections"] == []

    ledger.current_state_id = "s2"
    away = runtime._context(task, "target")
    assert away["已知页面图"]["connections"] == [{
        "from": "s1", "to": "s2", "action": "开始按钮"}]


def test_pending_context_exposes_history_refs_for_the_actual_return_path():
    ledger = _seed_ledger()
    ledger.states["s2"] = PageState("s2", "p1", "Dialog", "Active dialog", "dialog.png")
    ledger.states["s3"] = PageState("s3", "p1", "Unrelated", "Other state", "other.png")
    ledger.pages["p1"].state_ids.extend(["s2", "s3"])
    ledger.transitions.append(Transition("e1", "s1", "s2", "a0", {}, "Opened dialog"))
    ledger.current_state_id = "s2"
    ledger.attempts["a1"] = ActionAttempt(
        "a1", "", "s2", "recover", {"kind": "back"}, "before.png")

    context = build_agent_context(
        ledger, None, "target", app_name="fixture", platform="desktop",
        pending_attempt_id="a1", correction="", rejection_count=0, rejection_limit=4,
    )

    states = {s["state_ref"]: s for s in context["已知页面图"]["states"]}
    assert states["s1"]["known_regions"][0]["region_ref"] == "r1"
    assert states["s1"]["known_regions"][0]["name"] == ledger.regions["r1"].name
    assert "s3" not in states
    assert context["当前页面已登记内容"] == {}


def test_resume_context_recalls_last_observed_state_refs_without_live_position():
    ledger = _seed_ledger()
    ledger.states["s30"] = PageState("s30", "p1", "Search open", "Search", "search.png")
    ledger.states["s31"] = PageState("s31", "p1", "Unrelated", "Other", "other.png")
    ledger.pages["p1"].state_ids.extend(["s30", "s31"])
    for region_id, name in [("r100", "Toolbar"), ("r102", "Navigation")]:
        occurrence_id, variant_id = f"occ-{region_id}", f"rv-{region_id}"
        ledger.regions[region_id] = Region(region_id, name, name)
        ledger.region_variants[variant_id] = RegionVariant(variant_id, region_id)
        ledger.occurrences[occurrence_id] = RegionOccurrence(
            occurrence_id, region_id, "s30", name, name, variant_id)
        ledger.states["s30"].region_occurrence_ids.append(occurrence_id)
    ledger.event("region_review_observed", state_id="s30")
    ledger.current_state_id = "s30"
    task = ledger.operation_task("o1")
    prepare_resume_region_rediscovery(ledger)

    context = build_agent_context(
        ledger, task, "target", app_name="fixture", platform="desktop",
        pending_attempt_id="", correction="", rejection_count=0, rejection_limit=4,
        rediscovering=True,
    )

    states = {s["state_ref"]: s for s in context["已知页面图"]["states"]}
    assert states["s30"]["known_regions"] == [
        {"region_ref": "r100", "name": "Toolbar", "parent_region_ref": ""},
        {"region_ref": "r102", "name": "Navigation", "parent_region_ref": ""},
    ]
    assert states["s1"]["known_regions"][0]["region_ref"] == "r1"
    assert "s31" not in states
    assert context["当前页面已登记内容"] == {}
    assert ledger.current_state_id == ""
    assert "历史引用目录，不证明当前可见" in context["状态栏"]


def test_known_state_catalog_exposes_survey_completion_without_inheriting_it():
    from gui_rewalk.src.core.explore.status import known_graph
    from .explore_fixtures import _seed_ledger
    ledger = _seed_ledger()
    ledger.states['s1'].survey_complete = True
    ledger.states['s2'] = PageState('s2', 'p1', 'New menu', '', 'menu.png')
    ledger.pages['p1'].state_ids.append('s2')
    states = {item['state_ref']: item for item in known_graph(ledger)['states']}
    assert states['s1']['survey_complete'] is True
    assert states['s2']['survey_complete'] is False


def test_pending_return_reuses_task_bindings_without_another_page_catalog():
    ledger = _seed_ledger()
    ledger.states['s2'] = PageState('s2', 'p1', 'Menu', '', 'menu.png', survey_complete=True)
    ledger.states['s3'] = PageState('s3', 'p1', 'Other', '', 'other.png', survey_complete=True)
    ledger.pages['p1'].state_ids.extend(['s2', 's3'])
    ledger.transitions.extend([
        Transition('e0', 's3', 's2', 'a0', {}, 'Earlier entry'),
        Transition('e1', 's1', 's2', 'a1', {}, 'Opened menu'),
        Transition('e2', 's2', 's2', 'a2', {}, 'Scrolled menu'),
    ])
    ledger.current_state_id = 's2'
    ledger.attempts['a3'] = ActionAttempt('a3', '', 's2', 'recover',
        {'kind': 'back'}, 'before.png')
    task = ledger.operation_task('o1')
    before = ledger.snapshot()

    context = build_agent_context(ledger, task, 'target', app_name='fixture', platform='desktop',
        pending_attempt_id='a3', correction='', rejection_count=0, rejection_limit=4)

    card = context['当前任务精确卡']
    assert card['known_source_bindings'] == [
        {'state_ref': 's1', 'region_ref': 'r1', 'owner_ref': 'el1'}]
    assert '来自图1' in card['instruction']
    assert 'known_source_bindings' in card['instruction']
    assert '当前 State 不能完成' not in card['instruction']
    assert '已知State候选绑定' not in context
    assert context['当前页面已登记内容'] == {}
    assert ledger.snapshot() == before

    context = build_agent_context(ledger, task, 'target', app_name='fixture', platform='desktop',
        pending_attempt_id='', correction='', rejection_count=0, rejection_limit=4)
    assert '已知State候选绑定' not in context
    assert '来自图1' not in context['当前任务精确卡']['instruction']
    assert '当前 State 不能完成' in context['当前任务精确卡']['instruction']
